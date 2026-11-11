"""기능 2 평가 (2026-11-10 자율성 지시): 감시 재생. 사용: python scripts/monitor_replay.py
G-CHANGE_1·G-TRACK_D 시점 순서로 해외진출 에이전트를 빈 DB에서 실행하고(LLM 기록 재사용), 직전 시점 이후 새 공시마다 조사 루프를 돌린다.
본다: (1) 규칙 경보가 정답지대로인지(회귀) (2) 찾은 관련 공시·판단 이유가 기록되는지 (3) as_of 이후 정보 0건.
결과: data/logs/monitor_replay_{오늘}.json, .md. 조사 기록은 data/monitor_replay.db."""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stride"))
from tests.golden import llm_replay  # noqa: E402

llm_replay.install()      # 해외진출 노드는 같은 입력이면 기록 재사용. 조사 루프는 실제 호출
from agents.overseas_funding.graph import run_company  # noqa: E402
from core.clients import dart  # noqa: E402
from core.schemas import Request  # noqa: E402
from orchestrator import store  # noqa: E402
from orchestrator.investigate import investigate_filing  # noqa: E402
from orchestrator.monitor import route_by_event  # noqa: E402

G = ROOT / "stride/tests/golden/overseas_funding"
PER_STEP = 2      # 시점당 조사할 새 공시 수 (평가 비용 상한). 감시 본체 상한은 MONITOR_MAX_COMPANIES와 같다
FIRST_LOOKBACK = 30


def main():
    out_db = ROOT / "data/monitor_replay.db"
    con = store.connect(str(out_db))
    rows = []
    for name in ("G-CHANGE_1", "G-TRACK_D"):
        doc = json.loads((G / f"{name}.json").read_text(encoding="utf-8"))
        cc = doc.get("corp_code") or doc["request"]["company"]
        agent_db = str(ROOT / f"data/monitor_replay_{name}.db")
        Path(agent_db).unlink(missing_ok=True)      # 재생용 임시 상태 DB (매번 빈 DB에서 시작)
        prev = None
        for step in doc["expect"]["steps"]:
            as_of = date.fromisoformat(step["as_of"])
            r = run_company(Request(request_id=f"mr-{name}", agent="overseas_funding", mode="single", corp_code=cc, as_of=as_of, context={"db_path": agent_db}))
            got = {a.alert_type for a in r.alerts}
            miss = [a for a in step.get("alerts_must_have", []) if a not in got]
            extra = [a for a in step.get("alerts_must_not_have", []) if a in got]
            since = prev + timedelta(days=1) if prev else as_of - timedelta(days=FIRST_LOOKBACK)
            new = [f for f in dart.get_client().list_filings(as_of, since, as_of, corp_code=cc) if route_by_event(f["report_nm"])]
            invs = []
            for f in new[-PER_STEP:]:
                got_inv = investigate_filing(con, f"mr-{name}-{as_of}", r, {"rcept_no": f["rcept_no"], "rcept_dt": f["rcept_dt"], "report_nm": f["report_nm"]}, as_of)
                tr = store.traces(con, cc)
                steps = [t for t in tr if t["trace_id"] == got_inv["trace_id"]]
                invs.append({"rcept_no": f["rcept_no"], "report_nm": f["report_nm"], "timing": got_inv["timing"], "verification": got_inv["verification_status"], "summary": got_inv["summary_md"], "related": got_inv["related"],
                             "late": got_inv["late"], "calls": got_inv["calls"], "tokens": got_inv["tokens"], "seconds": got_inv["seconds"], "tools": [s["tool"] for s in steps if s["tool"] not in (None, "verify")], "reasons": [s["reason"] for s in steps][:6]})
                print(name, as_of, f["rcept_no"], got_inv["timing"], "late", got_inv["late"], flush=True)
            rows.append({"golden": name, "corp_code": cc, "as_of": str(as_of), "alerts": sorted(got), "alerts_missing": miss, "alerts_unexpected": extra, "new_filings": len(new), "investigated": invs})
            prev = as_of
    summary = {"steps": len(rows), "alert_regressions": sum(bool(r["alerts_missing"] or r["alerts_unexpected"]) for r in rows), "investigations": sum(len(r["investigated"]) for r in rows),
               "with_related": sum(bool(i["related"]) for r in rows for i in r["investigated"]), "with_reasons": sum(bool(i["reasons"]) for r in rows for i in r["investigated"]),
               "late_items": sum(i["late"] for r in rows for i in r["investigated"]), "calls": sum(i["calls"] for r in rows for i in r["investigated"]), "tokens": sum(i["tokens"] for r in rows for i in r["investigated"]),
               "seconds": round(sum(i["seconds"] for r in rows for i in r["investigated"]), 1), "immediate": sum(i["timing"] == "immediate" for r in rows for i in r["investigated"])}
    out = ROOT / f"data/logs/monitor_replay_{date.today()}"
    out.with_suffix(".json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# 감시 재생 (새 공시 조사)", "", f"- 경보 회귀: {summary['alert_regressions']}건 / {summary['steps']}시점", f"- 조사 {summary['investigations']}건 (즉시 {summary['immediate']}), 관련 공시 기록 {summary['with_related']}건, 판단 이유 기록 {summary['with_reasons']}건",
             f"- as_of 이후 정보: {summary['late_items']}건", f"- LLM {summary['calls']}회, 토큰 {summary['tokens']:,}, {summary['seconds']}초", "",
             "| 정답지 | as_of | 규칙 경보 | 누락·불필요 | 새 공시 | 조사 공시 | 알림 시점 | 검증 | 도구 순서 | 관련 공시 | 요약 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        for i in r["investigated"] or [None]:
            lines.append(f"| {r['golden']} | {r['as_of']} | {', '.join(r['alerts']) or '-'} | {', '.join(r['alerts_missing'] + r['alerts_unexpected']) or '없음'} | {r['new_filings']} | "
                         + (f"{i['rcept_no']} {i['report_nm']} | {i['timing']} | {i['verification']} | {' → '.join(i['tools']) or '-'} | {', '.join(i['related']) or '-'} | {i['summary'].replace(chr(10), ' ')[:200] or '-'} |" if i else "- | - | - | - | - | - |"))
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
