# to_postgresql

Загрузка `pandas.DataFrame` в PostgreSQL из Python-скриптов и Jupyter Notebook.
Версия 0.2.0 добавляет атомарную замену периода и определение типов колонок.

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

Выполнить свой SQL с параметрами:

```python
pg.sql_query(
    'UPDATE "public"."table_name" SET "status" = :status WHERE "id" = :id',
    params={"status": "ready", "id": 123},
)
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
- делает `DATE` для `date`, `Дата` и колонок Метрики вида `ym:ad:date`;
- по dtype DataFrame выбирает `BIGINT`, `DOUBLE PRECISION`, `BOOLEAN`, `TIMESTAMP`;
- для объектов `Decimal` использует `NUMERIC`, для объектов `date` — `DATE`;
- остальные колонки создает как `TEXT` (числа в строках автоматически не преобразует);
- заменяет `NaN`, `NaT`, `pd.NA` на SQL `NULL`;
- вставляет строки пакетами в пределах одной транзакции.

Типы определяются только при создании НОВОЙ таблицы. Типы существующих таблиц
не меняются: миграция должна выполняться отдельно. Для целых счётчиков используйте
dtype `Int64`, для денежных сумм с точной десятичной арифметикой — `Decimal`.
Пустой DataFrame с типизированными колонками можно использовать для создания таблицы.

## Ежедневная замена отчёта за период

```python
if not data_ym.empty:
    pg.create_table(data=data_ym, table_name=table, schema=schema)

    inserted = pg.replace_date_range(
        data=data_ym,
        table_name=table,
        schema=schema,
        date_column="ym:ad:date",
        date_from=DATE_FROM,
        date_to=DATE_TO,
    )
```

Используйте `replace_date_range()` вместо пары `sql_query(DELETE ...)` и
`insert_into_table()`. Удаление и все пакеты вставки выполняются одной транзакцией:
если вставка упала, старые данные сохраняются. Строки вне периода не меняются.
Даты включают обе границы; отсутствующие даты, даты вне периода и неверный порядок
границ отклоняются до удаления. Метод возвращает количество вставленных строк.

Таблица должна существовать. На время замены берётся блокировка таблицы, которая
сериализует записи, но разрешает обычное чтение. Повторная загрузка заменяет период,
а не добавляет вторую копию. Дубликаты внутри самого входного отчёта не удаляются.

**Вход должен содержать полный отчёт для данной таблицы за период.** Если несколько
счётчиков пишут в одну таблицу, объединяйте их отчёты до замены или используйте
отдельные таблицы. Последовательная замена по каждому счётчику удалит строки предыдущего.

Пустой отчёт по умолчанию пропускается (возвращается 0), существующие данные остаются.
Если API успешно подтвердил отсутствие данных и период действительно нужно очистить,
передайте `allow_empty=True`. Ошибку API нельзя превращать в пустой отчёт.

`insert_into_table()` по-прежнему только добавляет строки; пустой DataFrame пропускает.
Прежние методы и alias `to_postgresql` сохранены. Имена SQL-объектов экранируются;
параметры значений передаются отдельно от SQL.

## Проверка с PostgreSQL

Укажите `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD` и запустите:

```sh
python -m unittest discover -s tests -v
```

Тесты создают только собственные схемы `test_to_pg_<uuid>` и удаляют их после проверки.
Проверяются откат второй неудачной пачки, повторные и параллельные замены, пустые
отчёты, границы периода, SQL NULL и типы данных. При отсутствии PGDATABASE тесты пропускаются.
