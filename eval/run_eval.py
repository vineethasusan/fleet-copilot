"""Run the evaluation set and report execution accuracy, latency and cost.

Usage:
    python eval/run_eval.py                 # uses LLM_PROVIDER / API key from env
    python eval/run_eval.py --limit 5       # quick smoke run

Writes eval/results/latest.json and eval/results/latest.md
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fleet_copilot.copilot import FleetCopilot  # noqa: E402
from fleet_copilot.evaluation import percentile, results_match  # noqa: E402
from fleet_copilot.prompts import PROMPT_VERSION  # noqa: E402


def judge(case: dict, ans, copilot: FleetCopilot) -> tuple[bool, str]:
    expect = case.get("expect")
    if expect == "cannot_answer":
        ok = (not ans.ok) and ans.error and "blocked" not in ans.error.lower()
        return bool(ok), "refused" if ok else "answered an unanswerable question"
    if expect == "blocked_or_refused":
        return (not ans.ok), "blocked" if not ans.ok else "executed a destructive request"
    if not ans.ok:
        return False, f"error: {ans.error}"
    gold = copilot.db.run(case["gold_sql"])
    ok = results_match(gold, ans.data, case["gold_sql"])
    return ok, "match" if ok else f"mismatch (gold {gold.shape}, pred {ans.data.shape})"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--cases", default=str(ROOT / "eval" / "eval_set.json"))
    args = ap.parse_args()

    cases = json.loads(Path(args.cases).read_text())[: args.limit]
    copilot = FleetCopilot()
    print(f"Mode: {copilot.mode} | retriever: {copilot.kb.backend} | prompt {PROMPT_VERSION} | {len(cases)} cases\n")

    rows, by_cat = [], defaultdict(lambda: [0, 0])
    t_start = time.perf_counter()
    for case in cases:
        ans = copilot.ask(case["question"], explain=False)
        ok, note = judge(case, ans, copilot)
        by_cat[case["category"]][0] += ok
        by_cat[case["category"]][1] += 1
        rows.append({
            "id": case["id"], "category": case["category"], "question": case["question"], "passed": ok,
            "note": note, "latency_ms": round(ans.total_ms, 1), "attempts": ans.attempts,
            "tokens": ans.input_tokens + ans.output_tokens, "sql": ans.sql,
        })
        print(f"{'✅' if ok else '❌'} {case['id']} [{case['category']}] {case['question'][:60]:<60} "
              f"{ans.total_ms / 1000:5.2f}s  {note}")

    passed = sum(r["passed"] for r in rows)
    lat = [r["latency_ms"] for r in rows]
    summary = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "mode": copilot.mode, "retriever": copilot.kb.backend, "prompt_version": PROMPT_VERSION,
        "cases": len(rows), "passed": passed, "accuracy": round(passed / max(1, len(rows)), 3),
        "by_category": {k: {"passed": v[0], "total": v[1]} for k, v in sorted(by_cat.items())},
        "latency_ms_p50": round(percentile(lat, 50), 1), "latency_ms_p95": round(percentile(lat, 95), 1),
        "avg_tokens": round(sum(r["tokens"] for r in rows) / max(1, len(rows))),
        "repaired_queries": sum(1 for r in rows if r["attempts"] > 1),
        "wall_time_s": round(time.perf_counter() - t_start, 1),
    }

    out = ROOT / "eval" / "results"
    out.mkdir(exist_ok=True)
    (out / "latest.json").write_text(json.dumps({"summary": summary, "results": rows}, indent=2))
    md = [f"# Evaluation results ({summary['run_at']})", "",
          f"- **Mode:** {summary['mode']} · retriever {summary['retriever']} · prompt {summary['prompt_version']}",
          f"- **Execution accuracy:** {passed}/{len(rows)} ({summary['accuracy']:.0%})",
          f"- **Latency:** p50 {summary['latency_ms_p50'] / 1000:.2f}s · p95 {summary['latency_ms_p95'] / 1000:.2f}s "
          f"(SQL generation + execution, excluding the written explanation)",
          f"- **Avg tokens per question:** {summary['avg_tokens']:,} · self-repaired queries: {summary['repaired_queries']}",
          "", "| Category | Passed |", "|---|---|"]
    md += [f"| {k} | {v['passed']}/{v['total']} |" for k, v in summary["by_category"].items()]
    md += ["", "| ID | Question | Result | Latency |", "|---|---|---|---|"]
    md += [f"| {r['id']} | {r['question']} | {'✅' if r['passed'] else '❌ ' + r['note']} | {r['latency_ms'] / 1000:.2f}s |"
           for r in rows]
    (out / "latest.md").write_text("\n".join(md) + "\n")
    print(f"\nAccuracy {passed}/{len(rows)} = {summary['accuracy']:.0%} | p50 {summary['latency_ms_p50']:.0f} ms "
          f"| p95 {summary['latency_ms_p95']:.0f} ms\nSaved eval/results/latest.md")


if __name__ == "__main__":
    main()
