"""Pick a sensible chart for a result table (or none)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

TIME_HINTS = ("date", "month", "week", "day", "time", "period")


@dataclass
class ChartSpec:
    kind: str          # "line" | "bar"
    x: str
    y: list[str]


def suggest_chart(df: pd.DataFrame | None) -> ChartSpec | None:
    if df is None or df.empty or len(df.columns) < 2 or len(df) < 2:
        return None
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if not numeric:
        return None
    x = df.columns[0]
    if x in numeric:  # first column is a number: nothing sensible to put on the x axis
        return None
    y = [c for c in numeric if not c.endswith("_id")][:3]
    if not y:
        return None
    if any(h in x.lower() for h in TIME_HINTS):
        return ChartSpec("line", x, y)
    if df[x].nunique() == len(df) and len(df) <= 25:
        return ChartSpec("bar", x, y[:1])
    return None
