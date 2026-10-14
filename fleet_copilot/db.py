"""Read-only database access and schema introspection."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


class QueryTimeoutError(RuntimeError):
    pass


@dataclass
class TableInfo:
    name: str
    columns: list[tuple[str, str]]  # (name, type)
    row_count: int
    sample_values: dict[str, list]


class FleetDB:
    def __init__(self, path: Path, timeout_s: float = 10.0):
        if not Path(path).exists():
            raise FileNotFoundError(
                f"Database not found at {path}. Run: python scripts/generate_data.py"
            )
        self.path = Path(path)
        self.timeout_s = timeout_s
        self._schema_cache: list[TableInfo] | None = None

    def _connect(self) -> sqlite3.Connection:
        # mode=ro: the connection physically cannot write, even if a bad query slipped through
        con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
        return con

    @property
    def tables(self) -> set[str]:
        return {t.name for t in self.schema()}

    def schema(self) -> list[TableInfo]:
        if self._schema_cache is not None:
            return self._schema_cache
        out = []
        with self._connect() as con:
            names = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            for n in names:
                cols = [(r[1], r[2]) for r in con.execute(f"PRAGMA table_info({n})")]
                count = con.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0]
                samples = {}
                for c, typ in cols:
                    if typ.upper() == "TEXT":
                        vals = [r[0] for r in con.execute(
                            f"SELECT DISTINCT {c} FROM {n} WHERE {c} IS NOT NULL LIMIT 9")]
                        if 0 < len(vals) <= 8:  # low-cardinality: show allowed values to the LLM
                            samples[c] = vals
                out.append(TableInfo(n, cols, count, samples))
        self._schema_cache = out
        return out

    def schema_prompt(self) -> str:
        """Compact DDL-like description of the schema for the LLM prompt."""
        lines = []
        for t in self.schema():
            cols = ", ".join(f"{c} {typ}" for c, typ in t.columns)
            lines.append(f"TABLE {t.name} ({cols})  -- {t.row_count:,} rows")
            for c, vals in t.sample_values.items():
                lines.append(f"    {t.name}.{c} values: {', '.join(map(repr, vals))}")
        return "\n".join(lines)

    def run(self, sql: str) -> pd.DataFrame:
        """Execute a (pre-validated) query with a wall-clock timeout."""
        con = self._connect()
        deadline = time.monotonic() + self.timeout_s

        def _check():  # returning non-zero aborts the query
            return 1 if time.monotonic() > deadline else 0

        con.set_progress_handler(_check, 10_000)
        try:
            return pd.read_sql_query(sql, con)
        except (sqlite3.OperationalError, pd.errors.DatabaseError) as e:
            if "interrupted" in str(e).lower():
                raise QueryTimeoutError(f"Query exceeded {self.timeout_s:.0f}s and was stopped.") from e
            raise
        finally:
            con.close()
