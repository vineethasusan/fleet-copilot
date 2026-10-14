"""Safety layer between LLM-generated SQL and the database.

LLM output is untrusted. Before anything is executed we check that it is a
single read-only SELECT/WITH statement, touches only known tables, and has a
row limit. The database connection itself is also opened read-only
(defence in depth), see db.py.
"""
from __future__ import annotations

import re

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|pragma|vacuum|reindex|grant|revoke)\b",
    re.IGNORECASE,
)


class UnsafeSQLError(ValueError):
    """Raised when generated SQL fails a safety check."""


def strip_sql(text: str) -> str:
    """Extract SQL from an LLM reply (handles ```sql fences and trailing semicolons)."""
    fence = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    sql = fence.group(1) if fence else text
    return sql.strip().rstrip(";").strip()


def _remove_strings_and_comments(sql: str) -> str:
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)          # string literals
    sql = re.sub(r"--[^\n]*", " ", sql)                  # line comments
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)  # block comments
    return sql


def validate(sql: str, allowed_tables: set[str], max_rows: int = 500) -> str:
    """Return a safe, row-limited version of `sql` or raise UnsafeSQLError."""
    if not sql or not sql.strip():
        raise UnsafeSQLError("Empty query.")
    sql = strip_sql(sql)
    bare = _remove_strings_and_comments(sql)

    if ";" in bare:
        raise UnsafeSQLError("Only a single statement is allowed.")
    if not re.match(r"^\s*(select|with)\b", bare, re.IGNORECASE):
        raise UnsafeSQLError("Only SELECT queries are allowed.")
    if m := FORBIDDEN.search(bare):
        raise UnsafeSQLError(f"Keyword '{m.group(0).upper()}' is not allowed.")

    # Every table referenced after FROM/JOIN must be a known table or a CTE name.
    ctes = {c.lower() for c in re.findall(r"(?:with|,)\s*([a-zA-Z_]\w*)\s+as\s*\(", bare, re.IGNORECASE)}
    referenced = {t.lower() for t in re.findall(r"\b(?:from|join)\s+([a-zA-Z_]\w*)", bare, re.IGNORECASE)}
    unknown = referenced - {t.lower() for t in allowed_tables} - ctes
    if unknown:
        raise UnsafeSQLError(f"Unknown table(s): {', '.join(sorted(unknown))}.")

    # Enforce a row cap on the outer query without breaking user LIMITs.
    if not re.search(r"\blimit\s+\d+\s*$", bare, re.IGNORECASE):
        sql = f"SELECT * FROM ({sql}) LIMIT {max_rows}"
    return sql
