"""D1 재계획 실제 구현 (2026-11-10 자율성 지시 기능 1). 자체 결정 S13(mark_missing만 실행)을 이 동작으로 바꾼다.

비어 있는 원천·소요 구성 항목과 이자비용(상각비·리스부채는 후보 기록만)을 조사 루프가 찾는다. 루프는 어디를 볼지만 정하고,
값은 agents/common/gate.py가 원문을 다시 읽어 일치할 때만 채택한다. 파생 지표는 기존 계산 함수로 다시 계산한다.
"""
import re
import uuid
from datetime import date

from agents.common import gate, tools
from agents.overseas_funding.calc import funding as F
from agents.overseas_funding.nodes.compute_funding_gap import metric as make_metric
from core import evidence as ev
from core.evidence import validate_evidence
from core.agent_loop import run_loop
from core.asof import UNKNOWN_NOTE, to_date
from core.calc import cashflow, fin_items, ratios
from core.clients.dart import VIEWER_URL
from core.schemas import Evidence, RouteDecision
from orchestrator import store

# 그 지표로 인정하는 표 행 이름 (규칙). 목록 밖 행(예: 기타유동금융자산 안의 '정기예금')은 분류가 애매해 채택하지 않는다 (원칙 2·3)
ALLOWED_ROWS = {"fin.cash_and_equivalents": ("현금및현금성자산",), "fin.short_term_financial_assets": ("단기금융상품", "단기예금"),
                "fin.dividends_paid_last_fy": ("배당금지급", "배당금의지급", "배당의지급", "배당금지급액"), "fin.ebitda_interest_coverage": ("이자비용",),
                "fin.ttm_operating_cash_flow": ("영업활동현금흐름", "영업활동으로인한현금흐름", "영업활동순현금흐름", "영업활동으로부터의현금흐름"),
                "fin.ebitda": ("감가상각비", "무형자산상각비", "사용권자산상각비", "감가상각비및무형자산상각비"), "fin.total_borrowings": ("리스부채", "유동리스부채", "비유동리스부채")}
OVS_TARGETS = {"fin.cash_and_equivalents": "현금및현금성자산", "fin.short_term_financial_assets": "단기금융상품", "fin.maturing_debt_1y": "1년 내 만기 차입금의 빈 금액 행", "fin.dividends_paid_last_fy": "직전 사업연도 배당금 지급액"}
# 원칙상 찾아도 쓸 수 없는 사유: 비원화(환산 금지), as_of 이후 정정(누수), 미분류 차입 행(분류는 규칙), 보고서 자체가 없음
NOT_FILLABLE = ("비원화", UNKNOWN_NOTE, "미분류", "직전 사업보고서 없음")
FILL_TOOLS = {k: v for k, v in tools.TOOLS.items() if k != "search_news"}      # 재무 값은 기사에서 찾지 않는다
RULES = ("findings: 찾은 값마다 {\"target\": 위 key 그대로, \"rcept_no\": 그 key의 기대 보고서 접수번호, \"table_hint\": 그 표 제목에 있는 낱말(예: 연결재무상태표, 연결현금흐름표, 단기금융상품, 이자비용), "
         "\"row_label\": 표의 행 이름 그대로, \"claimed_raw\": 그 행 당기 숫자를 표에 적힌 그대로(단위 환산 없음)}. 기대 보고서가 아닌 다른 기간·다른 보고서의 값은 넣지 않는다. 못 찾은 항목은 넣지 않는다. timing·sentences·related는 비운다.")


def _m(result, mid, period=None):
    rows = [m for m in (result.metrics if result else []) if m.metric_id == mid and (period is None or m.period == period)]
    return rows[-1] if rows else None


def _annual_reports(as_of, cc, fy: int) -> list[str]:
    """fy 사업연도 사업보고서(정정 포함) 중 as_of 이하 접수번호."""
    return _reports(as_of, cc, rf"사업보고서\s*\({fy}\.\d\d\)", f"{fy + 1}-01-01")


def _reports(as_of, cc, pattern: str, bgn: str) -> list[str]:
    return [r["rcept_no"] for r in tools.list_filings(as_of, cc, bgn) if re.search(pattern, r["report_nm"])]


SAME_PERIOD = {"H1": (r"반기보고서", "06"), "1Q": (r"분기보고서", "03"), "3Q": (r"분기보고서", "09")}      # 12월 결산 기준 (자체 결정 S22와 같음)


def _ttm_targets(snap, why, as_of, cc) -> list[dict]:
    """TTM 구성 3개(당기 누적, 직전 사업연도, 전기 동기 누적)를 각 보고서의 당기 열에서. 사업보고서 기준이면 당기 1개."""
    base, fs, label = snap["source_rcept_no"], snap.get("fs_div") or "CFS", snap.get("base_period") or ""
    y, code = int(label[:4]), label[4:]
    t = lambda part, name, exp: {"key": f"fin.ttm_operating_cash_flow:{part}", "metric_id": "fin.ttm_operating_cash_flow", "part": part, "name": f"현금흐름표 영업활동현금흐름 당기 열 — {name}", "why": why, "expected": exp, "scope": fs, "absolute": False, "kind": "apply"}
    out = [t("cum", f"재무 기준 보고서({label}) 누적", [base])]
    if code != "FY":
        nm, mm = SAME_PERIOD[code]
        out.append(t("fy_prev", f"{y - 1} 사업보고서 연간", _annual_reports(as_of, cc, y - 1)))
        out.append(t("prev_same", f"{y - 1}년 같은 기간 보고서 누적", _reports(as_of, cc, rf"{nm}\s*\({y - 1}\.{mm}\)", f"{y - 1}-{mm}-01")))
    return [x for x in out if x["expected"]] if all(x["expected"] for x in out) else []


def collect_targets(ovs, fin, as_of) -> tuple[list[dict], list[dict]]:
    """(대상, 건너뜀). 대상 {key, metric_id, name, why, expected, scope, absolute, kind(apply|candidate), row?}."""
    out, skipped = [], []
    snap = (ovs.extra.get("financial_snapshot") or {}) if ovs else {}
    base, fs = snap.get("source_rcept_no"), snap.get("fs_div") or "CFS"
    lnote = (_m(ovs, "ovs.liquidity_sources_to_uses").note or "") if _m(ovs, "ovs.liquidity_sources_to_uses") else ""
    ttm = _m(ovs, "fin.ttm_operating_cash_flow")
    if ttm and ttm.value is None and base:
        why = ttm.note or lnote
        if ttm.data_status == "unknown" or any(k in why for k in NOT_FILLABLE):
            skipped.append({"key": "fin.ttm_operating_cash_flow", "why": why})
        elif got := _ttm_targets(snap, why, as_of, ovs.corp_code):
            out += got
        else:
            skipped.append({"key": "fin.ttm_operating_cash_flow", "why": "TTM 구성 보고서 중 as_of 이하에 없는 것이 있음"})
    for mid, name in OVS_TARGETS.items():
        m = _m(ovs, mid)
        if not m or m.value is not None or not base:
            continue
        why = m.note or lnote
        if m.data_status == "unknown" or any(k in why for k in NOT_FILLABLE):
            skipped.append({"key": mid, "why": why})
            continue
        if mid == "fin.maturing_debt_1y":
            rows = re.search(r"금액 빈 값: (.+)", why or "")
            if not rows:
                skipped.append({"key": mid, "why": why or "사유 불명"})
                continue
            for r in rows.group(1).split(", "):
                out.append({"key": f"{mid}:{r}", "metric_id": mid, "name": f"재무상태표 유동부채 '{r}' 행 금액", "why": why, "expected": [base], "scope": fs, "absolute": False, "kind": "apply", "row": r})
            continue
        expected = [base]
        if mid == "fin.dividends_paid_last_fy":
            fy = int(snap.get("base_period", "0000")[:4]) - (0 if (snap.get("base_period") or "").endswith("FY") else 1)
            expected = _annual_reports(as_of, ovs.corp_code, fy)
            if not expected:
                skipped.append({"key": mid, "why": f"{fy} 사업보고서 없음"})
                continue
        out.append({"key": mid, "metric_id": mid, "name": name, "why": why, "expected": expected, "scope": fs, "absolute": mid == "fin.dividends_paid_last_fy", "kind": "apply"})
    fy_rows = sorted((m for m in (fin.metrics if fin else []) if m.metric_id == "fin.ebitda_interest_coverage" and (m.period or "").endswith("FY")), key=lambda m: m.period)
    if fy_rows and fy_rows[-1].value is None and "이자비용" in (fy_rows[-1].note or "") and "비원화" not in (fy_rows[-1].note or ""):
        fy = int(fy_rows[-1].period[:4])
        if exp := _annual_reports(as_of, fin.corp_code, fy):
            out.append({"key": f"interest:{fy_rows[-1].period}", "metric_id": "fin.ebitda_interest_coverage", "name": f"{fy} 사업연도 이자비용 (현금흐름표 조정 또는 금융비용 주석의 '이자비용' 행)", "why": fy_rows[-1].note, "expected": exp, "scope": "CFS", "absolute": True, "kind": "apply", "period": fy_rows[-1].period})
    for mid, word, name in (("fin.ebitda", "상각", "감가상각비·무형자산상각비"), ("fin.total_borrowings", "리스", "리스부채")):
        rows = sorted((m for m in (fin.metrics if fin else []) if m.metric_id == mid), key=lambda m: m.period or "")
        if rows and rows[-1].value is None and word in (rows[-1].note or "") and "비원화" not in (rows[-1].note or ""):
            ids = [i for i in rows[-1].evidence_ids if re.match(r"(DART|FIN):\d{14}", i)]
            if ids:
                out.append({"key": f"{mid}:candidate", "metric_id": mid, "name": f"{name} (후보 기록만, 연쇄 재계산 안 함)", "why": rows[-1].note, "expected": [re.match(r"(?:DART|FIN):(\d{14})", ids[0]).group(1)], "scope": "CFS", "absolute": False, "kind": "candidate"})
    return out, skipped


def context_text(ovs, fin, targets, as_of) -> str:
    snap = (ovs.extra.get("financial_snapshot") or {}) if ovs else {}
    lines = [f"기업: {(ovs or fin).corp_name} (corp_code {(ovs or fin).corp_code}), 기준일 {as_of}",
             f"재무 기준 보고서 접수번호 {snap.get('source_rcept_no')} (기간 {snap.get('base_period')}, {'연결' if snap.get('fs_div', 'CFS') == 'CFS' else '별도'})", "찾을 값:"]
    for t in targets:
        rows = (t["row"],) if t.get("row") else ALLOWED_ROWS.get(t["metric_id"], ())
        lines.append(f"- key {t['key']}: {t['name']} / 비어 있는 사유: {t['why'] or '-'} / 기대 보고서 접수번호: {', '.join(t['expected'])} / {'연결' if t['scope'] == 'CFS' else '별도'} 기준 / 인정하는 행 이름: {', '.join(rows)} (다른 이름의 행은 보고하지 않는다)")
    return "\n".join(lines)


def fill_missing(con, run_id: str, ovs, fin, as_of: date) -> tuple:
    """반환 (ovs, fin, RouteDecision, 요약 {targets, adopted, rejected, not_found, skipped, calls, tokens, seconds, trace_id})."""
    corp = (ovs or fin).corp_code
    targets, skipped = collect_targets(ovs, fin, as_of)
    trace_id = f"fill_{uuid.uuid4().hex[:10]}"
    summary = {"targets": len(targets), "adopted": [], "rejected": [], "not_found": [], "skipped": skipped, "calls": 0, "tokens": 0, "seconds": 0, "trace_id": trace_id}
    if not targets:
        d = RouteDecision(point="D1", action="mark_missing", reason=("채울 수 있는 대상 없음: " + "; ".join(f"{s['key']} ({(s['why'] or '')[:60]})" for s in skipped))[:300] or "대상 없음", accepted=True)
        store.save_decision(con, run_id, "orchestrator.fill", corp, d)
        return ovs, fin, d, summary
    loop = run_loop("재무 지표 계산에 필요한 아래 값이 비어 있다. 이 값이 적힌 공시 원문의 표와 행을 찾아 위치를 보고하라.", context_text(ovs, fin, targets, as_of), RULES, FILL_TOOLS, as_of=as_of, run_id=run_id)
    summary.update(calls=loop["calls"], tokens=loop["tokens"], seconds=loop["seconds"], tool_calls=loop.get("tool_calls", {}), repeats=loop.get("repeats", 0))
    steps = list(loop["steps"])
    found = {f.target: f for f in (loop["final"].findings if loop["final"] else [])}
    tried = ", ".join(f"{s['tool']}({','.join(str(v) for v in (s['args'] or {}).values())[:40]})" for s in loop["steps"] if s["tool"]) or "도구 호출 없음"
    adopted = {}
    for t in targets:
        f = found.get(t["key"])
        if f is None:
            summary["not_found"].append(t["key"])
            steps.append({"step": len(steps) + 1, "tool": "gate", "reason": f"{t['name']}: 못 찾음. 시도 경로: {tried}", "result": "missing 유지", "outcome": "not_found", "source": {"key": t["key"]}})
            continue
        g = gate.check(f.model_dump(), expected_rcept_nos=t["expected"], expected_scope=t["scope"], absolute=t["absolute"], allowed_rows=(t["row"],) if t.get("row") else ALLOWED_ROWS.get(t["metric_id"], ()))
        src = {"key": t["key"], "rcept_no": f.rcept_no, "table": f.table_hint, "row": f.row_label, "claimed_raw": f.claimed_raw}
        steps.append({"step": len(steps) + 1, "tool": "gate", "reason": f"{t['name']}: {g['reason']}", "result": f"채택 {g['value']:,}원" if g["adopted"] else "기각", "outcome": "adopted" if g["adopted"] else "rejected", "source": src})
        (summary["adopted"] if g["adopted"] else summary["rejected"]).append({**src, "value": g["value"], "reason": g["reason"]})
        if g["adopted"]:
            adopted[t["key"]] = {**t, **src, "value": g["value"], "gate": g["reason"]}
    store.save_trace(con, trace_id, run_id, corp, as_of.isoformat(), "fill", ", ".join(t["key"] for t in targets)[:200], steps)
    ovs, fin, applied = apply(ovs, fin, adopted, run_id, as_of)
    ovs, fin = (validate_evidence(ovs) if ovs else ovs), (validate_evidence(fin) if fin else fin)      # 새 근거도 형식·as_of·재계산 검사
    summary["applied"] = applied
    d = RouteDecision(point="D1", action="agent_search", reason=f"대상 {len(targets)}, 채택 {len(summary['adopted'])}, 기각 {len(summary['rejected'])}, 못 찾음 {len(summary['not_found'])} (조사 {trace_id})"[:300],
                      evidence_ids=[ev.dart_section(a["rcept_no"], "에이전트탐색") for a in adopted.values()], accepted=True)
    store.save_decision(con, run_id, "orchestrator.fill", corp, d)
    return ovs, fin, d, summary


# ---- 채택 값 반영: 기존 계산 함수로 다시 계산 ----
def _pointer_evidence(a: dict, corp: str) -> Evidence:
    eid = ev.dart_section(a["rcept_no"], f"에이전트탐색#{a['row']}")
    return Evidence(evidence_id=eid, source_grade="A", source_type="dart_document", corp_code=corp, published_at=to_date(a["rcept_no"][:8]), title=f"{a['table']} · {a['row']}",
                    url=VIEWER_URL.format(rcept_no=a["rcept_no"]), quote=f"{a['row']} {a['claimed_raw']} — 에이전트 탐색으로 확보, 채택 게이트: {a['gate']}"[:300])


def _calc(run_id, mid, impl, args, value, corp, as_of, inputs) -> Evidence:
    return Evidence(evidence_id=ev.calc(run_id, mid) + ":fill", source_grade="A", source_type="calc", corp_code=corp, published_at=as_of, title=mid, meta={"impl": impl, "args": args, "value": value, "inputs": inputs})


def apply(ovs, fin, adopted: dict, run_id: str, as_of: date) -> tuple:
    applied = []
    if not adopted:
        return ovs, fin, applied
    if ovs is not None and any(a["metric_id"] in OVS_TARGETS or a["metric_id"] == "fin.ttm_operating_cash_flow" for a in adopted.values()):
        ovs, applied = _apply_ovs(ovs, adopted, run_id, as_of)
    for a in adopted.values():
        if a["metric_id"] == "fin.ebitda_interest_coverage" and fin is not None:
            fin = _apply_interest(fin, a, run_id, as_of)
            applied.append(a["key"])
        elif a["kind"] == "candidate" and fin is not None:
            fin = fin.model_copy(update={"extra": {**fin.extra, "agent_candidates": (fin.extra.get("agent_candidates") or []) + [{k: a[k] for k in ("key", "rcept_no", "table", "row", "value", "gate")}]}})
    return ovs, fin, applied


def _apply_ovs(ovs, adopted, run_id, as_of):
    corp, applied = ovs.corp_code, []
    val = lambda mid: (_m(ovs, mid).value if _m(ovs, mid) and _m(ovs, mid).data_status == "ok" else None)
    v = {mid: val(mid) for mid in ("fin.cash_and_equivalents", "fin.short_term_financial_assets", "fin.ttm_operating_cash_flow", "ovs.confirmed_overseas_funding", "ovs.overseas_investment_amount", "ovs.overseas_investment_within_24m", "fin.maturing_debt_1y", "fin.dividends_paid_last_fy")}
    new, evs, notes = {}, [], {}
    for a in adopted.values():
        if a["metric_id"] in ("fin.cash_and_equivalents", "fin.short_term_financial_assets", "fin.dividends_paid_last_fy"):
            v[a["metric_id"]] = a["value"]
            evs.append(_pointer_evidence(a, corp))
            new[a["metric_id"]] = (a["value"], [evs[-1].evidence_id])
            notes[a["metric_id"]] = f"에이전트 탐색으로 확보: {a['rcept_no']} {a['table']} · {a['row']}"
            applied.append(a["key"])
    rows_ov = {a["row"]: a["value"] for a in adopted.values() if a["metric_id"] == "fin.maturing_debt_1y"}
    if rows_ov:
        snap = ovs.extra.get("financial_snapshot") or {}
        _, rows, _ = tools.financial_rows(as_of, corp, snap["source_rcept_no"])
        mat, _ = fin_items.maturing_debt_1y([r for r in rows if r.get("sj_div") == "BS"], rows_ov)
        if mat is not None:
            pe = [_pointer_evidence(a, corp) for a in adopted.values() if a["metric_id"] == "fin.maturing_debt_1y"]
            evs += pe
            v["fin.maturing_debt_1y"] = mat
            new["fin.maturing_debt_1y"] = (mat, [e.evidence_id for e in pe])
            notes["fin.maturing_debt_1y"] = "빈 금액 행을 에이전트 탐색으로 확보: " + ", ".join(f"{a['row']} ({a['rcept_no']})" for a in adopted.values() if a["metric_id"] == "fin.maturing_debt_1y")
            applied += [a["key"] for a in adopted.values() if a["metric_id"] == "fin.maturing_debt_1y"]
    parts = {a["part"]: a for a in adopted.values() if a["metric_id"] == "fin.ttm_operating_cash_flow"}
    code = ((ovs.extra.get("financial_snapshot") or {}).get("base_period") or "")[4:]
    if parts and ("cum" in parts and (code == "FY" or {"fy_prev", "prev_same"} <= set(parts))):
        ttm = cashflow.ttm_operating_cash_flow(parts["cum"]["value"], parts.get("prev_same", {}).get("value"), parts.get("fy_prev", {}).get("value"), code)
        if ttm is not None:
            pe = [_pointer_evidence(a, corp) for a in parts.values()]
            ce = _calc(run_id, "fin.ttm_operating_cash_flow", "core.calc.cashflow.ttm_operating_cash_flow", {"cum_current": parts["cum"]["value"], "cum_prev_same": parts.get("prev_same", {}).get("value"), "fy_prev": parts.get("fy_prev", {}).get("value"), "period": code}, ttm, corp, as_of, [e.evidence_id for e in pe])
            evs += pe + [ce]
            v["fin.ttm_operating_cash_flow"] = ttm
            new["fin.ttm_operating_cash_flow"] = (ttm, [ce.evidence_id])
            notes["fin.ttm_operating_cash_flow"] = "구성 값을 에이전트 탐색으로 확보: " + ", ".join(f"{a['part']} {a['rcept_no']} · {a['row']}" for a in parts.values()) + (" · TTM 영업현금흐름 음수" if ttm < 0 else "")
            applied += [a["key"] for a in parts.values()]
    if not new:
        return ovs, applied
    P = "agents.overseas_funding.calc.funding."
    avail = F.available_funds(v["fin.cash_and_equivalents"], v["fin.short_term_financial_assets"], v["fin.ttm_operating_cash_flow"], v["ovs.confirmed_overseas_funding"])
    gap = F.funding_gap(v["ovs.overseas_investment_amount"], avail)
    uses = F.liquidity_uses(v["ovs.overseas_investment_within_24m"], v["fin.maturing_debt_1y"], v["fin.dividends_paid_last_fy"])
    derived = {"ovs.available_internal_funds": (avail, "available_funds", {"cash": v["fin.cash_and_equivalents"], "short_term": v["fin.short_term_financial_assets"], "ttm_ocf": v["fin.ttm_operating_cash_flow"], "confirmed": v["ovs.confirmed_overseas_funding"]}),
               "ovs.funding_gap": (gap, "funding_gap", {"investment": v["ovs.overseas_investment_amount"], "available": avail}),
               "ovs.funding_gap_ratio": (F.funding_gap_ratio(gap, v["ovs.overseas_investment_amount"]), "funding_gap_ratio", {"gap": gap, "investment": v["ovs.overseas_investment_amount"]}),
               "ovs.liquidity_uses": (uses, "liquidity_uses", {"investment_24m": v["ovs.overseas_investment_within_24m"], "maturing_debt": v["fin.maturing_debt_1y"], "dividends": v["fin.dividends_paid_last_fy"]}),
               "ovs.liquidity_surplus": (F.liquidity_surplus(avail, uses), "liquidity_surplus", {"sources": avail, "uses": uses}),
               "ovs.liquidity_sources_to_uses": (F.liquidity_ratio(avail, uses), "liquidity_ratio", {"sources": avail, "uses": uses})}
    inputs = [i for _, ids in new.values() for i in ids]
    for mid, (value, impl, args) in derived.items():
        old = _m(ovs, mid)
        if value is None or (old and old.value == value):
            continue
        e = _calc(run_id, mid, P + impl, args, value, corp, as_of, inputs)
        evs.append(e)
        new[mid] = (value, [e.evidence_id])
        missing_left = [k for k, x in (("원천", avail), ("소요", uses)) if x is None]
        notes[mid] = "에이전트 탐색 값 반영 재계산" + (f" ({', '.join(missing_left)} 산출 불가)" if missing_left else "") + (" · 소요 0" if mid == "ovs.liquidity_sources_to_uses" and uses == 0 else "") + (" · 원천 음수" if mid in ("ovs.liquidity_sources_to_uses", "ovs.liquidity_surplus") and avail is not None and avail < 0 else "")
    metrics = []
    for m in ovs.metrics:
        if m.metric_id in new:
            value, ids = new.pop(m.metric_id)
            metrics.append(make_metric(m.metric_id, value, m.period, ids, note=notes[m.metric_id]))
        else:
            metrics.append(m)
    fills = [{k: a[k] for k in ("key", "metric_id", "rcept_no", "table", "row", "value", "gate")} for a in adopted.values() if a["key"] in applied]
    gap_extra = {**(ovs.extra.get("funding_gap") or {}), "available_funds_krw": avail, "gap_krw": gap, "gap_ratio": F.funding_gap_ratio(gap, v["ovs.overseas_investment_amount"])}
    return ovs.model_copy(update={"metrics": metrics, "evidence": ovs.evidence + evs, "extra": {**ovs.extra, "agent_fills": (ovs.extra.get("agent_fills") or []) + fills, "funding_gap": gap_extra}}), applied


def _apply_interest(fin, a, run_id, as_of):
    period = a["period"]
    eb = _m(fin, "fin.ebitda", period)
    pe = _pointer_evidence(a, fin.corp_code)
    cov, cov_note = ratios.ebitda_interest_coverage(eb.value if eb else None, a["value"])
    evs = [pe]
    metrics = []
    for m in fin.metrics:
        if m.metric_id == "fin.ebitda_interest_coverage" and m.period == period and cov is not None:
            e = _calc(run_id, m.metric_id, "core.calc.ratios.ebitda_interest_coverage", {"ebitda": eb.value, "interest": a["value"]}, cov, fin.corp_code, as_of, [pe.evidence_id])
            evs.append(e)
            metrics.append(m.model_copy(update={"value": cov, "data_status": "ok", "evidence_ids": [e.evidence_id], "note": "이자비용을 에이전트 탐색으로 확보: " + f"{a['rcept_no']} {a['table']} · {a['row']}" + (f" · {cov_note}" if cov_note else "")}))
        else:
            metrics.append(m)
    fills = (fin.extra.get("agent_fills") or []) + [{k: a[k] for k in ("key", "metric_id", "rcept_no", "table", "row", "value", "gate")}]
    return fin.model_copy(update={"metrics": metrics, "evidence": fin.evidence + evs, "extra": {**fin.extra, "agent_fills": fills}})
