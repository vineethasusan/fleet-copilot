import pandas as pd

from fleet_copilot.evaluation import percentile, results_match


def test_match_ignores_column_names_order_and_extra_columns():
    gold = pd.DataFrame({"name": ["A", "B"], "km": [10.04, 20.0]})
    pred = pd.DataFrame({"total_km": [20.0, 10.0], "customer": ["B", "A"], "extra": [1, 2]})
    assert results_match(gold, pred, "SELECT name, km FROM t")


def test_order_matters_for_top_n():
    gold = pd.DataFrame({"name": ["A", "B"]})
    pred = pd.DataFrame({"name": ["B", "A"]})
    assert not results_match(gold, pred, "SELECT name FROM t ORDER BY x LIMIT 2")


def test_row_count_mismatch_fails():
    assert not results_match(pd.DataFrame({"a": [1, 2]}), pd.DataFrame({"a": [1]}))


def test_percentile():
    assert percentile([1, 2, 3, 4], 50) == 2.5
