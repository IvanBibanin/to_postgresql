from __future__ import annotations

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
        return '"' + identifier.replace('"', '""') + '"'

    def _qualified_table(self, schema: str, table_name: str) -> str:
        return f"{self._quote_identifier(schema)}.{self._quote_identifier(table_name)}"

    @staticmethod
    def _validate_data(data: pd.DataFrame) -> None:
        if data is None or not isinstance(data, pd.DataFrame):
            raise ValueError("data must be a pandas DataFrame")
        if data.empty:
            raise ValueError("data must not be empty")

    @staticmethod
    def _normalize_data(data: pd.DataFrame) -> pd.DataFrame:
        normalized = data.copy()
        for column in ("date", "Дата"):
            if column in normalized.columns:
                normalized[column] = pd.to_datetime(normalized[column]).dt.date
        return normalized.where(pd.notna(normalized), None)

    @staticmethod
    def _column_type(column_name: str) -> str:
        return "DATE" if column_name in ("date", "Дата") else "TEXT"

    def sql_query(self, query: str | None = None) -> bool:
        if not query:
            raise ValueError("query cannot be empty")

        with self.engine.begin() as connection:
            connection.execute(sqlalchemy.text(query))

        return True

    def create_table(self, table_name: str, data: pd.DataFrame, schema: str = "public") -> bool:
        self._validate_data(data)
        columns_sql = ", ".join(
            f"{self._quote_identifier(column)} {self._column_type(column)}"
            for column in data.columns.tolist()
        )
        table_sql = self._qualified_table(schema, table_name)

        with self.engine.begin() as connection:
            connection.execute(
                sqlalchemy.text(
                    f"CREATE SCHEMA IF NOT EXISTS {self._quote_identifier(schema)}"
                )
            )
            connection.execute(
                sqlalchemy.text(f"CREATE TABLE IF NOT EXISTS {table_sql} ({columns_sql})")
            )

        print(f"Table {schema}.{table_name} is ready")
        return True

    def insert_into_table(self, table_name: str, data: pd.DataFrame, schema: str = "public") -> bool:
        self._validate_data(data)
        data = self._normalize_data(data)
        columns = data.columns.tolist()
        columns_sql = ", ".join(self._quote_identifier(column) for column in columns)
        placeholders_sql = ", ".join(f":p{index}" for index in range(len(columns)))
        table_sql = self._qualified_table(schema, table_name)

        rows = [
            {f"p{index}": row.get(column) for index, column in enumerate(columns)}
            for row in data.to_dict(orient="records")
        ]

        insert_sql = sqlalchemy.text(
            f"INSERT INTO {table_sql} ({columns_sql}) VALUES ({placeholders_sql})"
        )

        with self.engine.begin() as connection:
            connection.execute(insert_sql, rows)

        print(f"Inserted rows: {len(rows)} into {schema}.{table_name}")
        return True


to_postgresql = ToPostgreSQL
