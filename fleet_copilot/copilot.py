"""The Fleet Copilot pipeline.

    question
       │
       ▼
  1. retrieve   ── similar verified examples + KPI definitions (vector search)
       │
       ▼
  2. generate   ── LLM writes SQL from schema + definitions + examples
       │
       ▼
  3. guard      ── single read-only SELECT, known tables, row cap
       │
       ▼
  4. execute    ── read-only connection with timeout
       │   └─ on error: send error back to the LLM and repair (max N attempts)
       ▼
  5. explain    ── LLM writes a short business answer from the actual result
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import pandas as pd

from . import prompts
from .config import Settings, settings as default_settings
from .db import FleetDB
from .llm import LLMClient, OfflineClient, make_client
from .retrieval import KnowledgeBase
from .sql_guard import UnsafeSQLError, strip_sql, validate
from .synthetic import ensure_database

log = logging.getLogger("fleet_copilot")

OFFLINE_MIN_SIMILARITY = 0.45


@dataclass
class Step:
    name: str
    ms: float
    detail: str = ""


@dataclass
class Answer:
    question: str
    sql: str | None = None
    data: pd.DataFrame | None = None
    summary: str = ""
    error: str | None = None
    attempts: int = 0
    steps: list[Step] = field(default_factory=list)
    examples_used: list[str] = field(default_factory=list)
    definitions_used: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None and self.data is not None

    @property
    def total_ms(self) -> float:
        return sum(s.ms for s in self.steps)


class FleetCopilot:
    def __init__(self, cfg: Settings | None = None, llm: LLMClient | None = None,
                 kb: KnowledgeBase | None = None, db: FleetDB | None = None):
        self.cfg = cfg or default_settings
        self.db = db or FleetDB(ensure_database(self.cfg.db_path), self.cfg.query_timeout_s)
        self.kb = kb or KnowledgeBase(self.cfg.knowledge_dir)
        self.llm = llm or make_client(self.cfg.resolved_provider(), self.cfg.anthropic_model, self.cfg.openai_model)
        self._schema_prompt = self.db.schema_prompt()

    @property
    def mode(self) -> str:
        return self.llm.name

    # ---------------------------------------------------------------- public
    def ask(self, question: str, explain: bool = True) -> Answer:
        ans = Answer(question=question.strip())
        if not ans.question:
            ans.error = "Please type a question."
            return ans
        try:
            ex_hits, kpi_hits = self._timed(ans, "retrieve", lambda: self._retrieve(ans.question))
            ans.examples_used = [h.doc.payload["question"] for h in ex_hits]
            ans.definitions_used = [h.doc.payload["title"] for h in kpi_hits]

            if isinstance(self.llm, OfflineClient):
                self._answer_offline(ans, ex_hits)
                return ans

            sql = self._timed(ans, "generate", lambda: self._generate(ans, ex_hits, kpi_hits))
            if sql.upper().startswith("CANNOT_ANSWER"):
                ans.error = sql.split(":", 1)[-1].strip() or "This question can't be answered from the fleet data."
                return ans
            self._execute_with_repair(ans, sql)
            if ans.ok and explain:
                ans.summary = self._timed(ans, "explain", lambda: self._explain(ans))
        except Exception as e:  # surface a clean message; full trace goes to logs
            log.exception("copilot failure")
            ans.error = ans.error or f"{type(e).__name__}: {e}"
        return ans

    # --------------------------------------------------------------- stages
    def _retrieve(self, q: str):
        ex, kpi = self.kb.retrieve(q, self.cfg.top_k_examples, self.cfg.top_k_glossary)
        # Date semantics are needed for almost every question, so always include them.
        if not any(h.doc.payload["title"] == "Time periods" for h in kpi):
            tp = [h for h in self.kb.glossary.search("time periods this month last month dates", 3)
                  if h.doc.payload["title"] == "Time periods"]
            kpi = kpi + tp
        return ex, kpi

    def _generate(self, ans: Answer, ex_hits, kpi_hits) -> str:
        user = prompts.SQL_USER.format(
            schema=self._schema_prompt,
            glossary=prompts.format_glossary(kpi_hits),
            examples=prompts.format_examples(ex_hits),
            question=ans.question,
        )
        r = self.llm.complete(prompts.SQL_SYSTEM, user)
        ans.input_tokens += r.input_tokens
        ans.output_tokens += r.output_tokens
        text = r.text.strip()
        return text if text.upper().startswith("CANNOT_ANSWER") else strip_sql(text)

    def _execute_with_repair(self, ans: Answer, sql: str) -> None:
        for attempt in range(self.cfg.max_repair_attempts + 1):
            ans.attempts = attempt + 1
            try:
                safe = validate(sql, self.db.tables, self.cfg.max_rows)
                ans.sql = sql
                ans.data = self._timed(ans, "execute", lambda: self.db.run(safe), detail=f"attempt {attempt + 1}")
                ans.error = None
                return
            except UnsafeSQLError as e:
                ans.sql, ans.error = sql, f"Blocked unsafe query: {e}"
                return  # never "repair" around a safety block
            except Exception as e:
                ans.sql, ans.error = sql, f"{type(e).__name__}: {e}"
                if attempt == self.cfg.max_repair_attempts:
                    return
                log.info("repairing SQL (attempt %s): %s", attempt + 1, e)
                user = prompts.REPAIR_USER.format(question=ans.question, sql=sql, error=str(e))
                r = self._timed(ans, "repair", lambda: self.llm.complete(prompts.SQL_SYSTEM, user))
                ans.input_tokens += r.input_tokens
                ans.output_tokens += r.output_tokens
                sql = strip_sql(r.text)

    def _explain(self, ans: Answer) -> str:
        df = ans.data
        table = df.head(25).to_csv(index=False) if not df.empty else "(no rows)"
        r = self.llm.complete(
            prompts.ANSWER_SYSTEM,
            prompts.ANSWER_USER.format(question=ans.question, sql=ans.sql, n_rows=len(df), table=table),
            max_tokens=400,
        )
        ans.input_tokens += r.input_tokens
        ans.output_tokens += r.output_tokens
        return r.text.strip()

    def _answer_offline(self, ans: Answer, ex_hits) -> None:
        best = ex_hits[0] if ex_hits else None
        if not best or best.score < OFFLINE_MIN_SIMILARITY:
            ans.error = ("Offline demo mode only answers questions close to the example library. "
                         "Add ANTHROPIC_API_KEY or OPENAI_API_KEY to ask anything.")
            return
        self._execute_with_repair(ans, best.doc.payload["sql"])
        if ans.ok:
            ans.summary = (f"Offline mode: matched the verified example "
                           f"“{best.doc.payload['question']}” (similarity {best.score:.2f}). "
                           f"{len(ans.data)} rows returned.")

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _timed(ans: Answer, name: str, fn, detail: str = ""):
        t0 = time.perf_counter()
        try:
            return fn()
        finally:
            ans.steps.append(Step(name, (time.perf_counter() - t0) * 1000, detail))
