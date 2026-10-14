"""Fleet Copilot – REST API (FastAPI).

Lets other systems (e.g. a fleet-management web app) embed the copilot.

Run:   uvicorn api:app --reload
Docs:  http://localhost:8000/docs
"""
from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from fleet_copilot.copilot import FleetCopilot

app = FastAPI(title="Fleet Copilot API", version="1.0.0",
              description="Natural-language questions over fleet telematics data.")


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500,
                          examples=["Which vehicles are underperforming this month?"])
    explain: bool = True


class AskResponse(BaseModel):
    question: str
    answer: str
    sql: str | None
    columns: list[str]
    rows: list[list]
    row_count: int
    latency_ms: float
    sql_attempts: int
    tokens: int


@lru_cache(maxsize=1)
def copilot() -> FleetCopilot:
    return FleetCopilot()


@app.get("/health")
def health() -> dict:
    c = copilot()
    return {"status": "ok", "mode": c.mode, "retriever": c.kb.backend, "tables": sorted(c.db.tables)}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    ans = copilot().ask(req.question, explain=req.explain)
    if not ans.ok:
        raise HTTPException(status_code=422, detail={"error": ans.error, "sql": ans.sql})
    df = ans.data
    return AskResponse(
        question=ans.question, answer=ans.summary, sql=ans.sql,
        columns=list(df.columns), rows=df.astype(object).where(df.notna(), None).values.tolist(),
        row_count=len(df), latency_ms=round(ans.total_ms, 1), sql_attempts=ans.attempts,
        tokens=ans.input_tokens + ans.output_tokens,
    )
