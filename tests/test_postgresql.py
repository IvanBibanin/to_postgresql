"""Integration tests: use PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD.

Only uniquely named test schemas are created and removed.
"""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pandas as pd
import sqlalchemy as sa

from to_postgresql import ToPostgreSQL, to_postgresql


@unittest.skipUnless(os.environ.get("PGDATABASE"), "Set PostgreSQL test connection variables")
class PostgreSQLTests(unittest.TestCase):
    def setUp(self):
        self.pg = ToPostgreSQL(
            host=os.environ["PGHOST"], port=int(os.environ.get("PGPORT", "5432")),
            database=os.environ["PGDATABASE"], user=os.environ["PGUSER"],
            password=os.environ["PGPASSWORD"], batch_page_size=1,
        )
        self.schema = "test_to_pg_" + uuid4().hex
        self.addCleanup(self.cleanup)
        self.pg.sql_query(f'CREATE SCHEMA "{self.schema}"')

    def cleanup(self):
        try:
            self.pg.sql_query(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
        finally:
            self.pg.engine.dispose()

    def frame(self, dates=("2026-11-01",), visits=(1,)):
        return pd.DataFrame({"ym:ad:date": list(dates), "visits": list(visits)})

    def seed(self):
        data = self.frame(("2026-10-31", "2026-11-01"), (99, 1))
        self.pg.create_table("report", data, self.schema)
        self.pg.insert_into_table("report", data, self.schema)

    def read(self):
        with self.pg.engine.connect() as connection:
            return list(connection.exec_driver_sql(
                f'SELECT "ym:ad:date", visits FROM "{self.schema}".report ORDER BY 1, 2'
            ))

    def replace(self, data, **kwargs):
        return self.pg.replace_date_range(
            "report", data, "ym:ad:date", "2026-11-01", "2026-11-02", self.schema, **kwargs
        )

    def test_repeat_replaces_without_duplicates_and_keeps_other_dates(self):
        self.seed()
        data = self.frame(("2026-11-01", "2026-11-02"), (10, 20))
        self.assertEqual(self.replace(data), 2)
        self.assertEqual(self.replace(data), 2)
        self.assertEqual(self.read(), [(date(2026, 10, 31), 99), (date(2026, 11, 1), 10), (date(2026, 11, 2), 20)])

    def test_failed_second_batch_rolls_back_delete_and_first_batch(self):
        self.seed()
        before = self.read()
        self.pg.sql_query(f'ALTER TABLE "{self.schema}".report ADD CHECK (visits >= 0)')
        with self.assertRaises(sa.exc.IntegrityError):
            self.replace(self.frame(("2026-11-01", "2026-11-02"), (10, -1)))
        self.assertEqual(self.read(), before)

    def test_empty_report_skips_by_default_and_can_explicitly_clear(self):
        self.seed()
        before = self.read()
        self.assertEqual(self.replace(pd.DataFrame()), 0)
        self.assertEqual(self.read(), before)
        self.assertTrue(self.pg.insert_into_table("report", pd.DataFrame(), self.schema))
        self.assertEqual(self.replace(pd.DataFrame(), allow_empty=True), 0)
        self.assertEqual(self.read(), [(date(2026, 10, 31), 99)])

    def test_bad_dates_never_delete_existing_rows(self):
        self.seed()
        before = self.read()
        for value in ("2026-10-30", "not-a-date", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.replace(self.frame((value,), (3,)))
            self.assertEqual(self.read(), before)
        with self.assertRaises(ValueError):
            self.replace(pd.DataFrame({"visits": [3]}))
        with self.assertRaises(ValueError):
            self.pg.replace_date_range("report", self.frame(), "ym:ad:date", "2026-11-03", "2026-11-01", self.schema)
        self.assertEqual(self.read(), before)

    def test_types_nulls_and_quoted_identifiers(self):
        data = pd.DataFrame({
            "ym:ad:date": ["2026-11-01", None],
            "count": pd.Series([1, None], dtype="Int64"),
            "rate": [1.5, float("nan")],
            "flag": pd.Series([True, None], dtype="boolean"),
            "money": [Decimal("12.34"), None],
            'quoted"name': ["O'Reilly", None],
            "time": pd.to_datetime(["2026-11-01T10:00:00Z", None]),
        })
        table_name = 'typed"report'
        self.pg.create_table(table_name, data, self.schema)
        self.pg.insert_into_table(table_name, data, self.schema)
        with self.pg.engine.connect() as connection:
            types = dict(connection.execute(sa.text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema=:schema AND table_name=:table"
            ), {"schema": self.schema, "table": table_name}).all())
            rows = list(connection.exec_driver_sql(
                f'SELECT * FROM {self.pg._qualified_table(self.schema, table_name)} ORDER BY "count" NULLS LAST'
            ))
        self.assertEqual(types, {"ym:ad:date": "date", "count": "bigint", "rate": "double precision",
                                "flag": "boolean", "money": "numeric", 'quoted"name': "text",
                                "time": "timestamp with time zone"})
        self.assertEqual(rows[0][4], Decimal("12.34"))
        self.assertEqual(rows[0][5], "O'Reilly")
        self.assertEqual(tuple(rows[1]), (None,) * 7)

    def test_existing_text_date_is_supported_without_migration(self):
        self.pg.sql_query(f'CREATE TABLE "{self.schema}".report ("ym:ad:date" TEXT, visits TEXT)')
        self.replace(self.frame())
        self.replace(self.frame(visits=(2,)))
        with self.pg.engine.connect() as connection:
            rows = list(connection.exec_driver_sql(f'SELECT * FROM "{self.schema}".report'))
        self.assertEqual(rows, [("2026-11-01", "2")])

    def test_concurrent_replacements_do_not_append_duplicates(self):
        self.seed()
        barrier = Barrier(2)
        def run(value):
            barrier.wait(timeout=10)
            return self.replace(self.frame(visits=(value,)))
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(run, (10, 20)))
        self.assertEqual(results, [1, 1])
        rows = self.read()
        self.assertEqual(len(rows), 2)
        self.assertIn(rows[-1][1], (10, 20))

    def test_duplicate_columns_and_empty_table_definition_rejected(self):
        self.assertIs(to_postgresql, ToPostgreSQL)
        with self.assertRaises(ValueError):
            self.pg.create_table("bad", pd.DataFrame([[1, 2]], columns=["a", "a"]), self.schema)
        with self.assertRaises(ValueError):
            self.pg.create_table("bad", pd.DataFrame(), self.schema)


if __name__ == "__main__":
    unittest.main()
