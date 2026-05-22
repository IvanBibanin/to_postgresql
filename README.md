# to_postgresql

Маленький helper для загрузки `pandas.DataFrame` в PostgreSQL из Jupyter Notebook.

## Установка

```python
%pip uninstall -y to-postgresql
%pip install --upgrade --force-reinstall --no-cache-dir git+https://github.com/IvanBibanin/to_postgresql.git@main
```

После установки перезапустите kernel Jupyter.

## Использование

```python
from to_postgresql import to_postgresql

pg = to_postgresql(
    host="your-postgres-host",
    port=5432,
    user="your-user",
    password="your-password",
    database="postgres",
)
```

Создать таблицу:

```python
pg.create_table(data=df, table_name="table_name", schema="public")
```

Выполнить свой SQL:

```python
pg.sql_query("""
DELETE FROM "public"."table_name"
WHERE "date" BETWEEN DATE '2026-05-01' AND DATE '2026-05-10'
""")
```

Вставить датафрейм:

```python
pg.insert_into_table(data=df, table_name="table_name", schema="public")
```

Можно импортировать класс напрямую:

```python
from to_postgresql import ToPostgreSQL
```

## Что делает helper

- создает схему, если ее нет;
- создает таблицу по колонкам DataFrame;
- делает `DATE` для колонок `date` и `Дата`;
- остальные колонки создает как `TEXT`;
- заменяет `NaN` на `NULL`;
- вставляет строки через SQLAlchemy.

`insert_into_table()` не удаляет старые строки и не делает `UPSERT`. Если нужна повторная загрузка без дублей, сначала выполните свой `DELETE` через `sql_query()`.
