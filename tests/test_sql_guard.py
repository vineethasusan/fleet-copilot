import pytest

from fleet_copilot.sql_guard import UnsafeSQLError, strip_sql, validate

TABLES = {"trips", "vehicles", "customers", "drivers", "maintenance", "fuel_transactions"}


def test_plain_select_gets_row_cap():
    out = validate("SELECT * FROM trips", TABLES, max_rows=50)
    assert out.endswith("LIMIT 50")


def test_existing_limit_is_kept():
    assert validate("SELECT * FROM trips LIMIT 5", TABLES) == "SELECT * FROM trips LIMIT 5"


def test_cte_names_are_allowed():
    sql = "WITH v AS (SELECT * FROM trips), w AS (SELECT * FROM v) SELECT * FROM w LIMIT 3"
    assert validate(sql, TABLES) == sql


def test_strips_markdown_fence_and_semicolon():
    assert strip_sql("```sql\nSELECT 1 FROM trips;\n```") == "SELECT 1 FROM trips"


@pytest.mark.parametrize("sql", [
    "DELETE FROM trips",
    "DROP TABLE trips",
    "UPDATE vehicles SET status='x'",
    "SELECT * FROM trips; DROP TABLE trips",
    "WITH x AS (DELETE FROM trips) SELECT 1",
    "PRAGMA table_info(trips)",
    "ATTACH DATABASE 'x.db' AS x",
    "SELECT * FROM sqlite_master",
    "SELECT * FROM salaries",
])
def test_unsafe_queries_are_blocked(sql):
    with pytest.raises(UnsafeSQLError):
        validate(sql, TABLES)


def test_keywords_inside_strings_are_fine():
    sql = "SELECT * FROM customers WHERE name = 'Drop Shipping; Delete Co' LIMIT 1"
    assert validate(sql, TABLES) == sql
