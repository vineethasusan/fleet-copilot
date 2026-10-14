"""Execution-accuracy scoring for text-to-SQL.

Two queries are judged equivalent when they return the same data, regardless of
column names, column order or extra helper columns. Concretely: the row counts
match and every column of the gold result has a column in the predicted result
with the same multiset of values (numbers compared after rounding). Row order
only matters when the gold query is a top-N (has LIMIT).
"""
from __future__ import annotations

import math
import re

import pandas as pd


def _norm(v, ndigits: int):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, (int, float)):
        return round(float(v), ndigits)
    return str(v).strip().lower()


def _column_signature(s: pd.Series, ordered: bool, ndigits: int):
    vals = [_norm(v, ndigits) for v in s.tolist()]
    return tuple(vals) if ordered else tuple(sorted(vals, key=lambda x: (x is None, str(x))))


def results_match(gold: pd.DataFrame, pred: pd.DataFrame, gold_sql: str = "", ndigits: int = 1) -> bool:
    if pred is None or len(gold) != len(pred):
        return False
    ordered = bool(re.search(r"\blimit\s+\d+\s*$", gold_sql.strip(), re.IGNORECASE)) and len(gold) > 1
    pred_sigs = [_column_signature(pred[c], ordered, ndigits) for c in pred.columns]
    # Also compare at 0 decimals, to forgive ROUND(x, 0) vs ROUND(x, 2) style differences
    pred_sigs0 = [_column_signature(pred[c], ordered, 0) for c in pred.columns]
    for c in gold.columns:
        if (_column_signature(gold[c], ordered, ndigits) not in pred_sigs
                and _column_signature(gold[c], ordered, 0) not in pred_sigs0):
            return False
    return True


def percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)
