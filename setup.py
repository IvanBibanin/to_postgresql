from pathlib import Path

from setuptools import setup


ROOT = Path(__file__).parent
README = ROOT / "README.md"


setup(
    name="to-postgresql",
    version="0.2.0",
    description="Simple pandas DataFrame loader for PostgreSQL.",
    url="https://github.com/IvanBibanin/to_postgresql",
    long_description=README.read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    py_modules=["to_postgresql"],
    python_requires=">=3.9",
    install_requires=[
        "pandas>=1.5,<3",
        "psycopg2-binary>=2.9,<3",
        "SQLAlchemy>=2.0,<2.1",
    ],
)
