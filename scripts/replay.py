"""백테스트 (구성문서 10.1, 시점 리플레이). 사용: python scripts/replay.py [사례 파일]
기본 사례: stride/tests/golden/backtest_cases.json. 결과: data/logs/backtest_{오늘}.json, .md (기업명 포함 파일은 data/logs에만).

자체 결정 (2026-11-09): 사례마다 전체 시장 discover_graph를 돌리면 시점 1개에 최대 K(20)곳을 분석한다. 그래서
  1) 탐색 단계 = LLM 없는 screen_universe(기본 탐색과 같은 12개월)에 사례 기업이 들어가는지,
  2) 보드 등장 = 사례 기업을 실제로 분석해 기본 탐색 조건(apply_criteria, apply_rules)을 충족하는지
로 판정한다. 둘 다 discover_graph가 쓰는 같은 함수다. 근거 날짜 ≤ as_of 검증을 통과한 결과만 집계한다.
"""
import json
import sys
import time
from datetime import date
from pathlib import Path

from dateutil.relativedelta import relativedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stride"))
from agents.overseas_funding.batch import screen_universe  # noqa: E402
from orchestrator import common, store  # noqa: E402
from orchestrator.discover import default_criteria  # noqa: E402
from orchestrator.rules import apply_criteria, apply_rules  # noqa: E402

OFFSETS = (6, 3)      # 조달 공시일 기준 몇 개월 전 (10.1)


def run_case(case: dict, con, db_path) -> list[dict]:
    rows = []
    funding = date.fromisoformat(case["funding_date"])
    for months in OFFSETS:
        as_of = funding - relativedelta(months=months)
        t0 = time.monotonic()
        crit = default_criteria(as_of)
        in_events = any(x["corp_code"] == case["corp_code"] for x in screen_universe(as_of - relativedelta(months=crit.lookback_months), as_of, as_of))
        ovs, fin, _ = common.run_agents(con, case["corp_code"], as_of, db_path, run_id=f"bt-{case['corp_code']}-{as_of}")
        ver = common.verify(ovs, fin, as_of, "bt", case["corp_code"])
        info = common.company_info(con, case["corp_code"])
        rules = apply_rules(fin, ver, info.get("market"), as_of)
        ok, why, needs = apply_criteria(common.row_inputs(ovs, fin, info), crit, rules)
        late = [e.evidence_id for r in (ovs, fin) for e in r.evidence if e.published_at > as_of]
        unknown = sum(1 for r in (ovs, fin) for m in r.metrics if m.data_status == "unknown") + sum(1 for s in ovs.extra.get("signals") or [] if s.get("value_status") == "unknown")
        p = common.main_project(ovs)
        b = common.board_row(ovs, fin, info, rules, ver, matched_search_ids=[], is_watched=False, change_badges=[])
        v = lambda d: (d or {}).get("value")
        axes = {"A_signals": sorted({s["signal_type"] for s in ovs.extra.get("signals") or []}), "A_investment": v(b.investment_amount), "B_funding_status": b.funding_status.get("label"),
                "B_ratio": v(b.liquidity.get("ratio")), "B_surplus": v(b.liquidity.get("surplus")), "B_note": (b.liquidity.get("ratio") or {}).get("note"), "B_investment_24m": v(b.liquidity.get("investment_24m")),
                "C_debt_ratio": v(b.debt_ratio), "C_net_debt_to_ebitda": v(common.mdict(common.metric(fin, "fin.net_debt_to_ebitda", prefer="annual"))), "C_ebitda_interest": v(common.mdict(common.metric(fin, "fin.ebitda_interest_coverage", prefer="annual"))),
                "D_warnings": b.risk_warnings, "sort_key": list(common.default_sort_key(b))}
        rows.append({**axes, "corp_name": case["corp_name"], "funding_rcept_no": case["funding_rcept_no"], "funding_date": case["funding_date"], "as_of": as_of.isoformat(), "months_before": months,
                     "in_events": in_events, "on_board": bool(ok and in_events and not late), "excluded_by": None if ok else why, "needs_check": needs,
                     "signal_status": next((c.value for c in ovs.classifications if c.key == "ovs.signal_status"), None), "project": f"{p['target_country']}·{p['method']}·{p['stage']}단계" if p else None,
                     "evidence_after_as_of": len(late), "unknown_count": unknown, "evidence": [s["evidence_ids"][0] for s in (ovs.extra.get("signals") or [])[:3]], "llm_calls": ovs.extra.get("llm_calls", 0), "seconds": round(time.monotonic() - t0, 1)})
        print(case["corp_code"], as_of, "events" if in_events else "-", "board" if rows[-1]["on_board"] else "-", flush=True)
    return rows


def main(path=None):
    cases = json.loads(Path(path or ROOT / "stride/tests/golden/backtest_cases.json").read_text(encoding="utf-8"))["cases"]
    db = ROOT / "data/backtest.db"
    con = store.connect(str(db))
    rows = [r for c in cases for r in run_case(c, con, str(db))]
    caught = {(r["funding_rcept_no"]) for r in rows if r["on_board"]}
    first_seen = {}
    for r in sorted(rows, key=lambda r: r["as_of"]):
        if r["on_board"]:
            first_seen.setdefault(r["funding_rcept_no"], r)
    leads = [(date.fromisoformat(r["funding_date"]) - date.fromisoformat(r["as_of"])).days for r in first_seen.values()]
    summary = {"cases": len(cases), "pre_capture_rate": round(len(caught) / len(cases), 3) if cases else None, "avg_lead_days": round(sum(leads) / len(leads), 1) if leads else None,
               "evidence_after_as_of": sum(r["evidence_after_as_of"] for r in rows), "unknown_count": sum(r["unknown_count"] for r in rows), "llm_calls": sum(r["llm_calls"] for r in rows),
               "board_accuracy": "사람 확인 필요 (보드에 오른 기업의 해외투자 신호를 공시로 확인)"}
    out = ROOT / f"data/logs/backtest_{date.today()}"
    out.with_suffix(".json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# 백테스트 결과 (구성문서 10.1)", "", "사례 수가 적어 일반화하지 않는다. 조달 공시가 없었던 기업은 '틀림'이 아니라 '조달 방식 미확인'으로 분류한다. 근거 날짜 ≤ as_of를 통과한 결과만 집계했다.", "",
             f"- 사전 포착률: {summary['pre_capture_rate']} ({len(caught)}/{len(cases)})", f"- 평균 선행 기간: {summary['avg_lead_days']}일", f"- as_of 이후 근거: {summary['evidence_after_as_of']}건", f"- 정정공시 영향 건수(unknown): {summary['unknown_count']}", f"- 보드 정확도: {summary['board_accuracy']}", "",
             "| 기업 | 조달 공시 | 조달일 | as_of | 해외 관련 공시 탐색 포함 | 보드 등장 | 제외 사유 | 신호 상태 | 대표 프로젝트 | 정정 영향 | 근거 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['corp_name']} | {r['funding_rcept_no']} | {r['funding_date']} | {r['as_of']} ({r['months_before']}개월 전) | {'예' if r['in_events'] else '아니오'} | {'예' if r['on_board'] else '아니오'} | {r['excluded_by'] or '-'} | {r['signal_status']} | {r['project'] or '-'} | {r['unknown_count']} | {', '.join(r['evidence'])} |")
    e = lambda x: "산출 불가" if x is None else f"{x / 1e8:,.0f}억"
    n = lambda x, s="": "산출 불가" if x is None else f"{x:,.2f}{s}"
    lines += ["", "## 시점별 A~D 값 (2026-11-10 방향 수정)", "", "보드 순위: 백테스트는 사례 기업만 분석하므로 같은 시점 다른 기업과의 순위는 없다. 기본 정렬 키(조달 진행 여부, 원천÷소요, 24개월 내 투자액)를 대신 적는다.", "",
              "| 기업 | as_of | 보드 등장 | A 신호 | A 해외 투자액 | B 해외 용도 조달 | B 원천÷소요 | B 원천−소요 | C 부채비율 | C 순차입금/EBITDA | C EBITDA/이자비용 | D 재무 위험 경고 | B 산출 불가 사유 |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['corp_name']} | {r['as_of']} | {'예' if r['on_board'] else '아니오'} | {', '.join(r['A_signals']) or '-'} | {e(r['A_investment'])} | {r['B_funding_status']} | {n(r['B_ratio'], '배')} | {e(r['B_surplus'])} | {n(r['C_debt_ratio'], '%')} | {n(r['C_net_debt_to_ebitda'], '배')} | {n(r['C_ebitda_interest'], '배')} | {', '.join(r['D_warnings']) or '-'} | {r['B_note'] or '-'} |")
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
