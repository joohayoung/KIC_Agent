"""기능 1 평가 (2026-11-10 자율성 지시): 빈 지표 채우기. 사용: python scripts/eval_fill.py <골든 결과 덤프 폴더>
대상: 골든 범위 안 실행(덤프 중 유동성 지표가 있는 것) + 데모 DB(data/stride.db)의 matched 기업. 조사 기록은 data/eval_fill.db.
결과: data/logs/eval_fill_{오늘}.json, .md — (a) 원천÷소요 산출률 전후 (b) 채운 값과 정답지 비교 (c) 기업당 추가 호출·토큰·시간. 기업명은 콘솔에 쓰지 않는다."""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stride"))
from core.schemas import AgentResult  # noqa: E402
from orchestrator import fill, store  # noqa: E402

GOLD = ROOT / "stride/tests/golden/overseas_funding"
GOLD_KEYS = {"fin.cash_and_equivalents": "cash_krw", "fin.short_term_financial_assets": "short_term_krw", "fin.maturing_debt_1y": "maturing_debt_1y_krw", "fin.dividends_paid_last_fy": "dividends_paid_last_fy_krw"}
RATIO = "ovs.liquidity_sources_to_uses"
FIRST_RUN_MAX = 5      # 첫 실행 5곳 제한 (LLM을 부르는 기업 수)


def gold_expect(cc: str, as_of: str) -> dict:
    for p in GOLD.glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        co = d.get("request", {}).get("company") or d.get("corp_code")
        if co != cc:
            continue
        e = d["expect"]
        for s in e.get("steps", [e]):
            if s.get("as_of", d.get("request", {}).get("as_of")) == as_of:
                return {"name": p.stem, **s, **(s.get("liquidity_draft") or {})}
    return {}


def val(r, mid):
    m = next((x for x in r.metrics if x.metric_id == mid), None) if r else None
    return m.value if m else None


def main(dump_dir):
    cases = []
    for f in sorted(Path(dump_dir).glob("*.json")):
        r = AgentResult.model_validate_json(f.read_text(encoding="utf-8"))
        if any(m.metric_id == "ovs.liquidity_uses" for m in r.metrics):
            cases.append(("golden", r, None))
    demo = store.connect(str(ROOT / "data/stride.db"))
    run = demo.execute("SELECT run_id FROM orc_search_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    for row in demo.execute("SELECT corp_code, as_of FROM orc_search_matches WHERE run_id=? AND status='matched'", (run["run_id"],)) if run else []:
        o, fn = store.load_result(demo, row["corp_code"], "overseas_funding", row["as_of"]), store.load_result(demo, row["corp_code"], "financial_health", row["as_of"])
        cases.append(("demo", o, fn))
    con = store.connect(str(ROOT / "data/eval_fill.db"))
    rows, llm_companies = [], set()
    for kind, o, fn in cases:
        as_of = o.as_of
        targets, skipped = fill.collect_targets(o, fn, as_of)
        if targets and o.corp_code not in llm_companies and len(llm_companies) >= FIRST_RUN_MAX:
            rows.append({"kind": kind, "corp_code": o.corp_code, "as_of": str(as_of), "deferred": True})
            continue
        if targets:
            llm_companies.add(o.corp_code)
        o2, fn2, d, s = fill.fill_missing(con, f"evalfill-{o.corp_code}-{as_of}", o, fn, as_of)
        g = gold_expect(o.corp_code, str(as_of)) if kind == "golden" else {}
        checks = []
        for a in s["adopted"]:
            mid = a["key"].split(":")[0]
            want = g.get(GOLD_KEYS.get(mid, "_"))
            checks.append({"key": a["key"], "value": a["value"], "golden": want, "verdict": "정답지 없음(사람 확인)" if want in (None, "missing") else ("일치" if want == a["value"] else "불일치"), "source": f"{a['rcept_no']} {a['table']} · {a['row']}"})
        rows.append({"kind": kind, "corp_code": o.corp_code, "as_of": str(as_of), "golden": g.get("name"), "targets": [t["key"] for t in targets], "skipped": s["skipped"],
                     "ratio_before": val(o, RATIO), "ratio_after": val(o2, RATIO), "adopted": checks, "rejected": s["rejected"], "not_found": s["not_found"], "applied": s.get("applied", []),
                     "calls": s["calls"], "tokens": s["tokens"], "seconds": s["seconds"], "trace_id": s["trace_id"], "decision": d.action, "tool_calls": s.get("tool_calls", {}), "repeats": s.get("repeats", 0)})
        print(o.corp_code, as_of, "대상", len(targets), "채택", len(s["adopted"]), "기각", len(s["rejected"]), "호출", s["calls"], flush=True)
    done = [r for r in rows if not r.get("deferred")]
    n = len(done)
    before = sum(r["ratio_before"] is not None for r in done)
    after = sum(r["ratio_after"] is not None for r in done)
    wrong = [c for r in done for c in r["adopted"] if c["verdict"] == "불일치"]
    with_t = [r for r in done if r["targets"]]
    summary = {"cases": n, "ratio_computable_before": before, "ratio_computable_after": after, "adopted": sum(len(r["adopted"]) for r in done), "rejected": sum(len(r["rejected"]) for r in done),
               "not_found": sum(len(r["not_found"]) for r in done), "wrong_vs_golden": len(wrong), "companies_with_targets": len({r["corp_code"] for r in with_t}),
               "avg_calls": round(sum(r["calls"] for r in with_t) / len(with_t), 1) if with_t else 0, "avg_tokens": round(sum(r["tokens"] for r in with_t) / len(with_t)) if with_t else 0,
               "avg_seconds": round(sum(r["seconds"] for r in with_t) / len(with_t), 1) if with_t else 0, "deferred": len(rows) - n,
               "tool_calls": {k: sum(r.get("tool_calls", {}).get(k, 0) for r in done) for k in sorted({k for r in done for k in r.get("tool_calls", {})})}, "repeats_blocked": sum(r.get("repeats", 0) for r in done)}
    out = ROOT / f"data/logs/eval_fill_{date.today()}"
    out.with_suffix(".json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    lines = ["# 빈 지표 채우기 평가", "", f"- 원천÷소요 산출: {before}/{n} → {after}/{n}", f"- 채택 {summary['adopted']} · 기각 {summary['rejected']} · 못 찾음 {summary['not_found']} · 정답지와 불일치 {summary['wrong_vs_golden']}",
             f"- 대상 있는 실행당 평균: LLM {summary['avg_calls']}회, 토큰 {summary['avg_tokens']:,}, {summary['avg_seconds']}초",
             f"- 도구별 호출: {summary['tool_calls']} · 반복 차단 {summary['repeats_blocked']}회", "",
             "| 구분 | 기업 | as_of | 대상 | 채택(값·출처·정답지) | 기각 사유 | 못 찾음 | 원천÷소요 전→후 | 호출 | 토큰 | 초 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in done:
        lines.append(f"| {r['kind']} {r['golden'] or ''} | {r['corp_code']} | {r['as_of']} | {', '.join(r['targets']) or '-'} | {'; '.join(f'{c['key']} {c['value']:,} ({c['source']}, {c['verdict']})' for c in r['adopted']) or '-'} | "
                     f"{'; '.join(x['reason'][:60] for x in r['rejected']) or '-'} | {', '.join(r['not_found']) or '-'} | {r['ratio_before']} → {r['ratio_after']} | {r['calls']} | {r['tokens']:,} | {r['seconds']} |")
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
