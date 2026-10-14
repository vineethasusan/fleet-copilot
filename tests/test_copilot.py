"""Pipeline tests with a scripted fake LLM (no API key or network needed)."""
from fleet_copilot.charts import suggest_chart
from fleet_copilot.config import ROOT, Settings
from fleet_copilot.copilot import FleetCopilot
from fleet_copilot.db import FleetDB
from fleet_copilot.llm import LLMResponse, OfflineClient
from fleet_copilot.retrieval import KnowledgeBase


class ScriptedLLM:
    name = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, system, user, max_tokens=1200):
        self.calls.append(user)
        return LLMResponse(self.replies.pop(0), input_tokens=100, output_tokens=20)


def make(db_path, replies):
    cfg = Settings(db_path=db_path)
    kb = KnowledgeBase(ROOT / "knowledge", backend="tfidf")
    llm = ScriptedLLM(replies)
    return FleetCopilot(cfg, llm=llm, kb=kb, db=FleetDB(db_path)), llm


def test_happy_path_generates_runs_and_explains(db_path):
    cp, llm = make(db_path, ["```sql\nSELECT vehicle_type, COUNT(*) AS n FROM vehicles GROUP BY vehicle_type\n```",
                             "There are five vehicle types."])
    ans = cp.ask("How many vehicles of each type?")
    assert ans.ok and len(ans.data) > 0
    assert ans.summary == "There are five vehicle types."
    assert ans.attempts == 1
    assert [s.name for s in ans.steps] == ["retrieve", "generate", "execute", "explain"]
    # the prompt carries schema, KPI definitions and retrieved examples
    assert "TABLE vehicles" in llm.calls[0] and "Time periods" in llm.calls[0] and "Q: " in llm.calls[0]


def test_failed_sql_is_repaired(db_path):
    cp, _ = make(db_path, ["SELECT no_such_column FROM vehicles",
                           "SELECT COUNT(*) AS n FROM vehicles",
                           "Done."])
    ans = cp.ask("How many vehicles?")
    assert ans.ok and ans.attempts == 2
    assert "repair" in [s.name for s in ans.steps]


def test_cannot_answer_is_passed_through(db_path):
    cp, _ = make(db_path, ["CANNOT_ANSWER: salaries are not in the data"])
    ans = cp.ask("What do drivers earn?")
    assert not ans.ok and "salaries" in ans.error


def test_unsafe_sql_is_blocked_and_not_repaired(db_path):
    cp, llm = make(db_path, ["DELETE FROM trips"])
    ans = cp.ask("Delete all trips")
    assert not ans.ok and ans.error.startswith("Blocked")
    assert len(llm.calls) == 1


def test_offline_mode_uses_closest_verified_example(db_path):
    cfg = Settings(db_path=db_path)
    kb = KnowledgeBase(ROOT / "knowledge", backend="tfidf")
    cp = FleetCopilot(cfg, llm=OfflineClient(), kb=kb, db=FleetDB(db_path))
    ans = cp.ask("Which vehicles are overdue for service?")
    assert ans.ok and "Offline mode" in ans.summary
    assert not cp.ask("tell me a joke about camels").ok


def test_database_is_read_only(db_path):
    import sqlite3

    import pytest

    db = FleetDB(db_path)
    with pytest.raises(Exception):
        db.run("DELETE FROM trips")  # bypassing the guard still cannot write
    assert sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM trips").fetchone()[0] > 0


def test_chart_suggestion():
    import pandas as pd

    assert suggest_chart(pd.DataFrame({"month": ["2026-07", "2026-08"], "km": [1, 2]})).kind == "line"
    assert suggest_chart(pd.DataFrame({"customer": ["A", "B"], "km": [1, 2]})).kind == "bar"
    assert suggest_chart(pd.DataFrame({"n": [5]})) is None
