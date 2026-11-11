"""오케스트레이터 공통: 에이전트 실행·재사용, 검증, D1, 보드 행, 검증된 문장 작성. 수치를 다시 계산하지 않는다 (0장 5번)."""
import json
import re
from datetime import date

from agents.financial_health.graph import run as run_fin
from agents.overseas_funding.graph import run_company
from agents.verifier.graph import verify_answer, verify_results
from core.clients import dart
from core.llm import LLMRateLimitError, call_llm
from core.schemas import AgentResult, Request, RouteDecision
from orchestrator import store
from orchestrator.config import D1_ACTIONS, REQUIRED_METRICS, STAGE_LABELS
from orchestrator.schemas import BoardRow, RouteOutput, SentencesOutput
from core.clients.dart import DartQuotaError

PROMPTS = "orchestrator/prompts/"
MARKET = {"Y": "KOSPI", "K": "KOSDAQ"}


# ---- 기업 ----
def company_info(con, corp_code: str) -> dict:
    """기업개황(시장·업종). SQLite에 캐시한다 (구성문서 4.0)."""
    row = con.execute("SELECT * FROM orc_companies WHERE corp_code=?", (corp_code,)).fetchone()
    if row:
        return dict(row)
    try:
        d = dart.get_client().get_json("company.json", corp_code=corp_code)
    except DartQuotaError:      # DART 일일 한도(020): 삼키지 않고 올린다 (2026-11-11)
        raise
    except Exception:      # 기업개황을 못 읽으면 빈 칸으로 둔다
        d = {}
    info = {"corp_code": corp_code, "corp_name": d.get("corp_name") or corp_code, "market": MARKET.get(d.get("corp_cls"), d.get("corp_cls") or "-"), "induty_code": d.get("induty_code") or "", "stock_code": (d.get("stock_code") or "").strip(), "updated_at": store.now()}
    con.execute("INSERT OR REPLACE INTO orc_companies VALUES (?,?,?,?,?,?)", tuple(info.values()))
    con.commit()
    return info


# ---- 에이전트 ----
def run_agents(con, corp_code: str, as_of: date, db_path, *, run_id: str) -> tuple[AgentResult, AgentResult, bool]:
    """load_cached → dispatch. 같은 기업·as_of 결과가 있으면 재사용한다 (8장). 반환 (ovs, fin, 재사용 여부)."""
    day = as_of.isoformat()
    ovs, fin = store.load_result(con, corp_code, "overseas_funding", day), store.load_result(con, corp_code, "financial_health", day)
    if ovs and fin:
        return ovs, fin, True
    req = dict(mode="single", corp_code=corp_code, as_of=as_of, context={"db_path": str(db_path)})
    ovs = ovs or run_company(Request(request_id=f"{run_id}:{corp_code}:ovs", agent="overseas_funding", **req))
    if store.llm_failed(ovs):      # 구독 한도 등으로 LLM이 실패하면 결과를 쓰지 않고 호출자가 분석 대기로 둔다
        raise LLMRateLimitError(f"{corp_code}: " + next(e for e in ovs.errors if any(k in e for k in store.LLM_FAILURE))[:200])
    fin = fin or run_fin(Request(request_id=f"{run_id}:{corp_code}:fin", agent="financial_health", **req))
    return ovs, fin, False


def verify(ovs, fin, as_of, run_id, corp_code):
    return verify_results([x for x in (ovs, fin) if x], as_of, REQUIRED_METRICS, request_id=f"{run_id}:{corp_code}:ver", corp_code=corp_code)


def missing_required(ver) -> list[str]:
    """7.2 check_sufficiency: missing·absent만 부족. needs_due_diligence·unknown은 부족이 아니다."""
    return [m for m, s in (ver.coverage or {}).items() if s in ("missing", "absent")]


def replan(con, run_id: str, corp_code: str, missing: list[str], ovs, fin) -> RouteDecision:
    """D1 (7.6). LLM은 허용 선택지 중 하나만 고른다. 실행 경로가 있는 행동은 mark_missing뿐이라, 다른 선택은 기록하고 mark_missing으로 진행한다 (자체 결정)."""
    notes = (ovs.errors + fin.errors + ovs.open_questions[:8] + fin.open_questions[:8]) if ovs and fin else []
    try:
        out = call_llm(PROMPTS + "replan.md", {"missing": ", ".join(missing), "notes": "\n".join(f"- {n}" for n in notes) or "- 없음", "actions": ", ".join(D1_ACTIONS)}, RouteOutput, run_id=run_id)
        valid = out.action in D1_ACTIONS
        d = RouteDecision(point="D1", action=out.action if valid else "mark_missing", reason=out.reason[:300], evidence_ids=out.evidence_ids, accepted=valid, fallback_action=None if out.action == "mark_missing" else "mark_missing")
    except Exception as e:      # 판단 실패는 기본 경로
        d = RouteDecision(point="D1", action="mark_missing", reason=f"LLM 실패: {type(e).__name__}", accepted=False, fallback_action="mark_missing")
    store.save_decision(con, run_id, "orchestrator.replan", corp_code, d)
    return d


# ---- 지표 읽기 ----
def metric(result, metric_id, *, prefer="latest"):
    """같은 지표가 여러 기간이면 최신 시점(…말, TTM) → 최신 사업연도 순."""
    rows = [m for m in (result.metrics if result else []) if m.metric_id == metric_id]
    if not rows:
        return None
    point = [m for m in rows if (m.period or "").endswith("말") or (m.period or "").startswith("TTM") or "기준" in (m.period or "")]
    if prefer == "latest" and point:
        return point[0]
    return max(rows, key=lambda m: m.period or "")


def cls(result, key):
    return next((c for c in (result.classifications if result else []) if c.key == key), None)


def main_project(ovs) -> dict | None:
    return max((p for p in (ovs.extra.get("projects") or []) if p.get("gate_pass")), key=lambda p: p.get("amount_krw") or 0, default=None) if ovs else None


def mdict(m) -> dict:
    return {"value": m.value if m else None, "period": m.period if m else None, "data_status": m.data_status if m else "missing", "note": m.note if m else None, "evidence_ids": m.evidence_ids if m else []}


TRADING_LABELS = {"halted": "거래정지", "administrative": "관리종목", "delisting_review": "상장폐지 심사"}
LIQUIDITY_KEYS = {"ratio": "ovs.liquidity_sources_to_uses", "surplus": "ovs.liquidity_surplus", "sources": "ovs.available_internal_funds", "uses": "ovs.liquidity_uses",
                  "cash": "fin.cash_and_equivalents", "short_term": "fin.short_term_financial_assets", "ttm_ocf": "fin.ttm_operating_cash_flow", "confirmed_funding": "ovs.confirmed_overseas_funding",
                  "investment_24m": "ovs.overseas_investment_within_24m", "investment_beyond_24m": "ovs.overseas_investment_beyond_24m", "maturing_debt": "fin.maturing_debt_1y", "dividends": "fin.dividends_paid_last_fy"}
DEFAULT_SORT_TEXT = "기본 정렬: 해외 용도 조달 진행 기업 먼저 → 원천÷소요 낮은 순(산출 불가는 뒤) → 24개월 내 해외 투자액 큰 순"


def liquidity(ovs) -> dict:
    """B 유동성 원천·소요 (S&P Liquidity Descriptors 준용 STRIDE 정의). 해외진출 에이전트가 계산한 값을 그대로 옮긴다."""
    return {k: mdict(metric(ovs, m)) for k, m in LIQUIDITY_KEYS.items()}


def funding_status(ovs) -> dict:
    """해외 용도 조달 상태: 결정 공시의 11.2 판정(final)을 그대로 묶는다. 해외 용도 금액이 있는 건만."""
    ds = [d for d in ((ovs.extra.get("funding_decisions") or []) if ovs else []) if d.get("overseas_amount")]
    pend = sum(d["overseas_amount"] for d in ds if d.get("final") in ("미확정", "open_question"))
    done = sum(d["overseas_amount"] for d in ds if str(d.get("final", "")).startswith("확정"))
    label = "결과 공시 전·납입 확정" if pend and done else "결과 공시 전" if pend else "납입 확정" if done else "없음"
    return {"label": label, "unconfirmed": pend, "confirmed": done, "rcept_nos": [d["rcept_no"] for d in ds]}


def risk_warnings(rules, ovs) -> list[str]:
    """D 재무 위험 경고: 상장 규정 기준 해당 규칙 + 거래 상태 경고 (사실만)."""
    out = [f"{r.rule_id} {r.label}" for r in rules if r.hit is True and r.rule_id != "R5"]      # R5는 검증 실패 표시라 재무 위험이 아니다
    return out + [f"{TRADING_LABELS.get(w['type'], w['type'])} ({w['since']}~)" for w in ((ovs.extra.get("trading_status_warnings") or []) if ovs else [])]


def default_sort_key(r) -> tuple:
    """DEFAULT_SORT_TEXT 순서. 점수가 아니라 화면 정렬이다. r: BoardRow 또는 그 dict."""
    g = (lambda k: r.get(k) or {}) if isinstance(r, dict) else (lambda k: getattr(r, k) or {})
    ratio = (g("liquidity").get("ratio") or {}).get("value")
    inv = (g("liquidity").get("investment_24m") or {}).get("value") or 0
    return (g("funding_status").get("label", "없음") == "없음", ratio is None, ratio if ratio is not None else 0, -inv)


def row_inputs(ovs, fin, info: dict) -> dict:
    p = main_project(ovs)
    inv, ratio = metric(ovs, "ovs.overseas_investment_amount"), metric(ovs, "ovs.funding_gap_ratio")
    cap = metric(fin, "fin.market_cap")
    in_scope = cls(ovs, "ovs.in_scope")
    gates = (in_scope.value == "true" or (in_scope.rule or "").endswith("실패: G5")) if in_scope else None      # G1~G4 통과 (G5 새 신호는 보지 않는다)
    keys = {x["project_key"] for x in (ovs.extra.get("projects") or []) if x.get("gate_pass")} if ovs else set()
    sigs = [s for s in ((ovs.extra.get("signals") or []) if ovs else []) if not keys or s.get("project_key") in keys]
    return {"market": info.get("market"), "industry_code": info.get("induty_code"), "in_scope": (in_scope.value == "true") if in_scope else None, "gates_g1_g4": gates, "stage": p["stage"] if p else None, "country": p.get("target_country") if p else None,
            "method": p.get("method") if p else None, "investment": inv.value if inv and inv.data_status == "ok" else None, "gap_ratio": ratio.value if ratio and ratio.data_status == "ok" else None,
            "market_cap": cap.value if cap and cap.data_status == "ok" else None, "signal_types": sorted({s["signal_type"] for s in sigs})}


def board_row(ovs, fin, info, rules, ver, *, matched_search_ids, is_watched, change_badges) -> BoardRow:
    p = main_project(ovs)
    inv, gap, ratio, unc = (metric(ovs, k) for k in ("ovs.overseas_investment_amount", "ovs.funding_gap", "ovs.funding_gap_ratio", "ovs.unconfirmed_overseas_funding"))
    src = cls(ovs, "ovs.investment_amount_source")
    partial = (ovs and ovs.status != "complete") or (fin and fin.status != "complete")
    verification = "needs_check" if ver and ver.failed else "partial" if partial else "verified"
    return BoardRow(corp_code=info["corp_code"], corp_name=(ovs.corp_name if ovs else None) or info.get("corp_name") or info["corp_code"], market=info.get("market") or "-", industry=info.get("induty_code") or "-",
                    project={"country": p.get("target_country") if p else None, "method": p.get("method") if p else None, "stage": p["stage"] if p else None, "stage_label": STAGE_LABELS.get(p["stage"]) if p else None, "latest_signal_date": p.get("latest_event_date") if p else None},
                    investment_amount={**mdict(inv), "source": src.value if src else "missing"}, funding_gap={**mdict(gap), "ratio": ratio.value if ratio else None, "unconfirmed_funding": unc.value if unc else None},
                    debt_ratio=mdict(metric(fin, "fin.debt_ratio")), ttm_operating_cash_flow=mdict(metric(fin, "fin.ttm_operating_cash_flow")), rule_hits=[r.rule_id for r in rules if r.hit is True],
                    change_badges=change_badges, verification=verification, matched_search_ids=matched_search_ids, is_watched=is_watched,
                    liquidity=liquidity(ovs), funding_status=funding_status(ovs), risk_warnings=risk_warnings(rules, ovs))


# ---- 근거 있는 문장 ----
def fmt(value, unit) -> str:
    if value is None:
        return "산출 불가"
    if unit == "원":
        return f"{value / 1e8:,.0f}억 원"
    if unit == "비율":
        return f"{value * 100:.1f}%"
    if unit == "%":
        return f"{value:.1f}%"
    if unit == "배":
        return f"{value:.2f}배"
    return f"{value}"


def facts_and_cited(results: list, extra_lines=()) -> tuple[str, dict]:
    """LLM 자료(지표 값·분류·근거 ID)와 검증용 cited {evidence_id: {"values": [...], "quote"}}."""
    lines, cited = list(extra_lines), {}
    for r in results:
        if r is None:
            continue
        ev = {e.evidence_id: e for e in r.evidence}
        for m in r.metrics:
            if m.value is None:
                continue
            lines.append(f"- {m.name} ({m.metric_id}, {m.period}): {fmt(m.value, m.unit)} 근거 {m.evidence_ids}")
            for i in m.evidence_ids:
                c = cited.setdefault(i, {"values": [], "quote": (ev[i].quote or ev[i].title) if i in ev else None})
                c["values"].append({"value": m.value, "unit": m.unit})
        for c in r.classifications:
            lines.append(f"- {c.key}: {c.value} ({c.rule[:60]}) 근거 {c.evidence_ids}")
            for i in c.evidence_ids:
                cited.setdefault(i, {"values": [], "quote": f"{c.key} {c.value}"})
        for f in r.findings:
            lines.append(f"- 사실: {f.text} 근거 {f.evidence_ids}")
            for i in f.evidence_ids:
                cited.setdefault(i, {"values": [], "quote": f.text})["quote"] = f.text
    return "\n".join(lines), cited


def render(sentences, cited) -> tuple[str, dict]:
    """문장 목록 → '문장 [n]' 마크다운과 {n: [evidence_id]}. 같은 근거 묶음은 번호 1개."""
    order, foot, out = {}, {}, []
    for s in sentences:
        ids = [i for i in s.evidence_ids if i in cited]
        key = tuple(ids)
        if ids and key not in order:
            order[key] = len(order) + 1
            foot[order[key]] = ids
        out.append(s.text.rstrip(". ") + (f" [{order[key]}]" if ids else "") + ".")
    return " ".join(out), foot


def verified_sentences(prompt: str, variables: dict, cited: dict, as_of, *, run_id: str, corp_code=None, on_fail="drop", output=SentencesOutput):
    """LLM 작성 → 검증 answer 모드 → 실패 시 1회 재작성 → 그래도 실패한 문장은 제거(drop) 또는 '검증 실패' 표시(mark).
    반환 (마크다운, 각주, 검증 보고서, 원 출력, LLM 호출 수)."""
    feedback, calls, out, rep = "", 0, None, None
    for _ in range(2):
        out = call_llm(PROMPTS + prompt, {**variables, "재작성_피드백": feedback}, output, run_id=run_id, as_of=as_of)
        calls += 1
        text, foot = render(out.sentences, cited)
        rep = verify_answer(text, foot, cited, as_of, request_id=f"{run_id}:answer", corp_code=corp_code)
        calls += rep.llm_calls
        if not rep.failed:
            return text, foot, rep, out, calls
        feedback = "## 이전 출력의 검증 실패\n" + "\n".join(f"- {c.target} {c.kind}: {c.actual or ''} {c.note or ''}" for c in rep.failed[:10]) + "\n실패한 문장을 자료에 맞게 고치거나 빼세요."
    bad = {int(t.split()[1]) for t in rep.failed_targets if re.match(r"문장 \d+", t)}
    keep = [s for i, s in enumerate(out.sentences, 1) if i not in bad or on_fail == "mark"]
    if on_fail == "mark":
        keep = [s.model_copy(update={"text": s.text.rstrip(". ") + " (검증 실패)"}) if i in bad else s for i, s in enumerate(out.sentences, 1)]
    text, foot = render(keep, cited)
    return text, foot, rep, out, calls


def footnote_block(foot: dict, evidence: dict) -> str:
    lines = []
    for n, ids in foot.items():
        e = evidence.get(ids[0])
        lines.append(f"[{n}] " + (f"{e.title}, {e.published_at}, {e.url or ids[0]}" if e else ids[0]))
    return "\n".join(lines)


def all_evidence(*results) -> dict:
    return {e.evidence_id: e for r in results if r for e in r.evidence}


def dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)
