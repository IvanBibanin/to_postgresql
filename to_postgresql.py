from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import sqlalchemy


class ToPostgreSQL:
    def __init__(
        self,
        port: int | str | None = None,
        host: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        connect_timeout: int = 30,
        pool_recycle: int = 1800,
        batch_page_size: int = 500,
    ):
        if not isinstance(batch_page_size, int) or batch_page_size < 1:
            raise ValueError("batch_page_size must be a positive integer")
        self.batch_page_size = batch_page_size

        db_url = sqlalchemy.engine.URL.create(
            "postgresql+psycopg2",
            username=user,
            password=password,
            host=host,
            port=port,
            database=database,
        )
        self.engine = sqlalchemy.create_engine(
            db_url,
            pool_pre_ping=True,
            pool_recycle=pool_recycle,
            connect_args={"connect_timeout": connect_timeout},
            executemany_mode="values_plus_batch",
            executemany_batch_page_size=batch_page_size,
        )

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("SQL identifier cannot be empty")
        if "\x00" in identifier or len(identifier.encode("utf-8")) > 63:
            raise ValueError("SQL identifier contains NUL or exceeds 63 bytes")
        return '"' + identifier.replace('"', '""') + '"'

    def _qualified_table(self, schema: str, table_name: str) -> str:
        return f"{self._quote_identifier(schema)}.{self._quote_identifier(table_name)}"

    @classmethod
    def _validate_data(cls, data: pd.DataFrame) -> None:
        if data is None or not isinstance(data, pd.DataFrame):
            raise ValueError("data must be a pandas DataFrame")
        if not data.columns.is_unique:
            raise ValueError("DataFrame columns must be unique")
        if len(data.index) and len(data.columns) == 0:
            raise ValueError("DataFrame rows must have columns")
        for column in data.columns:
            cls._quote_identifier(column)

    @staticmethod
    def _is_date_column(column: str) -> bool:
        return column in ("date", "Дата") or (
            column.startswith("ym:") and column.endswith(":date")
        )

    @classmethod
    def _normalize_data(cls, data: pd.DataFrame) -> pd.DataFrame:
        normalized = data.copy()
        for column in normalized.columns:
            if cls._is_date_column(column):
                normalized[column] = pd.to_datetime(normalized[column]).dt.date
        # Object dtype is required: a float column otherwise converts None back to NaN.
        return normalized.astype(object).where(pd.notna(normalized), None)

    @classmethod
    def _column_type(cls, column_name: str, values: pd.Series) -> str:
        if cls._is_date_column(column_name):
            return "DATE"
        if pd.api.types.is_bool_dtype(values.dtype):
            return "BOOLEAN"
        if pd.api.types.is_integer_dtype(values.dtype):
            return "BIGINT"
        if pd.api.types.is_float_dtype(values.dtype):
            return "DOUBLE PRECISION"
        if pd.api.types.is_datetime64_any_dtype(values.dtype):
            return "TIMESTAMP WITH TIME ZONE" if values.dt.tz is not None else "TIMESTAMP"
        present = values.dropna()
        if not present.empty:
            if all(isinstance(value, Decimal) for value in present):
                return "NUMERIC"
            if all(isinstance(value, date) and not isinstance(value, datetime) for value in present):
                return "DATE"
        return "TEXT"

    def sql_query(self, query: str | None = None, params: dict | None = None) -> bool:
        if not query:
            raise ValueError("query cannot be empty")

        with self.engine.begin() as connection:
            connection.execute(sqlalchemy.text(query), params or {})

        return True

    def create_table(self, table_name: str, data: pd.DataFrame, schema: str = "public") -> bool:
        self._validate_data(data)
        if len(data.columns) == 0:
            raise ValueError("Cannot create a table without columns")
        columns_sql = ", ".join(
            f"{self._quote_identifier(column)} {self._column_type(column, data[column])}"
            for column in data.columns.tolist()
        )
        table_sql = self._qualified_table(schema, table_name)

        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE SCHEMA IF NOT EXISTS {self._quote_identifier(schema)}"
            )
            connection.exec_driver_sql(
                f"CREATE TABLE IF NOT EXISTS {table_sql} ({columns_sql})"
            )

        print(f"Table {schema}.{table_name} is ready")
        return True

    def insert_into_table(self, table_name: str, data: pd.DataFrame, schema: str = "public") -> bool:
        self._validate_data(data)
        if len(data.index) == 0:
            return True
        data = self._normalize_data(data)
        with self.engine.begin() as connection:
            self._insert(connection, table_name, data, schema)

        print(f"Inserted rows: {len(data)} into {schema}.{table_name}")
        return True

    def _insert(self, connection, table_name: str, data: pd.DataFrame, schema: str) -> None:
        self._qualified_table(schema, table_name)
        table = sqlalchemy.table(
            table_name, *(sqlalchemy.column(column) for column in data.columns), schema=schema
        )
        for start in range(0, len(data), self.batch_page_size):
            rows = data.iloc[start:start + self.batch_page_size].to_dict(orient="records")
            connection.execute(table.insert(), rows)

    def replace_date_range(
        self,
        table_name: str,
        data: pd.DataFrame,
        date_column: str,
        date_from: str | date,
        date_to: str | date,
        schema: str = "public",
        *,
        allow_empty: bool = False,
    ) -> int:
        """Replace an inclusive date range in an EXISTING table, atomically.

        Empty input is skipped unless allow_empty=True. The range must contain
        the COMPLETE report for this table: other accounts in it are also replaced.
        """
        self._validate_data(data)
        table_sql = self._qualified_table(schema, table_name)
        self._quote_identifier(date_column)
        start, end = pd.Timestamp(date_from), pd.Timestamp(date_to)
        if pd.isna(start) or pd.isna(end) or start.date() > end.date():
            raise ValueError("Invalid date range")
        start, end = start.date(), end.date()
        if len(data.index) == 0 and not allow_empty:
            return 0
        if len(data.index):
            if date_column not in data.columns:
                raise ValueError(f"Missing date column: {date_column}")
            data = data.copy()
            dates = pd.to_datetime(data[date_column], errors="raise").dt.date
            if dates.isna().any() or not dates.between(start, end).all():
                raise ValueError("All rows must have a date inside the replacement range")
            data[date_column] = dates
            data = self._normalize_data(data)
        table = sqlalchemy.table(table_name, sqlalchemy.column(date_column), schema=schema)
        delete = table.delete().where(
            sqlalchemy.cast(table.c[date_column], sqlalchemy.Date).between(start, end)
        )
        with self.engine.begin() as connection:
            # Serialize replacements, including when the target date range is empty.
            connection.exec_driver_sql(f"LOCK TABLE {table_sql} IN SHARE ROW EXCLUSIVE MODE")
            connection.execute(delete)
            if len(data.index):
                self._insert(connection, table_name, data, schema)
        return len(data)


to_postgresql = ToPostgreSQL
