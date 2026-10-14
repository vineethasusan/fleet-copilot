"""Every verified example in the knowledge base must run and return rows."""
import json

import pytest

from fleet_copilot.config import ROOT
from fleet_copilot.db import FleetDB
from fleet_copilot.sql_guard import validate

EXAMPLES = json.loads((ROOT / "knowledge" / "examples.json").read_text())
EVAL = [c for c in json.loads((ROOT / "eval" / "eval_set.json").read_text()) if "gold_sql" in c]


@pytest.mark.parametrize("ex", EXAMPLES, ids=[e["question"][:40] for e in EXAMPLES])
def test_example_sql_runs(db_path, ex):
    db = FleetDB(db_path)
    db.run(validate(ex["sql"], db.tables))


@pytest.mark.parametrize("case", EVAL, ids=[c["id"] for c in EVAL])
def test_gold_sql_runs(db_path, case):
    db = FleetDB(db_path)
    db.run(validate(case["gold_sql"], db.tables))
