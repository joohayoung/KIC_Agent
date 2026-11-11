"""검증 노드 (검증 개발문서 6·8장). 12개 노드. 판단하지 않고 통과·불일치·확인 불가만 기록한다.

노드는 모두 짧은 코드 검사라 한 파일에 둔다 (자체 결정 2026-11-09: 공통 양식의 '노드 1개 = 파일 1개'는 LLM·외부 호출 노드를 나누는 목적이고, 이 모듈의 외부 호출은 recheck_sources·check_claims 두 개뿐이다).
"""
import math
import re

from agents.verifier.config import DISPLAY_TOLERANCE, MAX_CLAIM_CHECKS, REPRT_BY_MONTH, RULE_PHRASES, VALUE_TOLERANCE
from agents.verifier.schemas import CheckItem, ClaimCheckOutput, VerificationReport
from core import catalog
from core.clients import dart
from core.evidence import _recalc_ok
from core.llm import call_llm
from core.report_guard import FORBIDDEN_TERMS, forbidden_fields
from core.clients.dart import DartQuotaError

PROMPT = "agents/verifier/prompts/check_claim.md"
CROSS_IDS = ("fin.cash_and_equivalents", "fin.short_term_financial_assets", "fin.ttm_operating_cash_flow")
_NUM_UNIT = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s*(조|억\s*원|억원|억|백만\s*원|만\s*원|원|%|%p|배)")
_FOOT = re.compile(r"\[(\d+)\]")


def item(code, outcome, target, kind=None, **k) -> CheckItem:
    return CheckItem(code=code, outcome=outcome, kind=kind, target=target, **k)


def _items(r):
    for m in r.metrics:
        yield "metric", m.metric_id, m
    for c in r.classifications:
        yield "classification", c.key, c
    for f in r.findings:
        yield "finding", f.finding_id, f


# ---- results 모드 ----
def check_evidence_links(state) -> dict:
    """R-01 근거 연결, R-07 카탈로그 등록."""
    out = []
    for r in state.get("results") or []:
        have = {e.evidence_id for e in r.evidence}
        for kind, target, x in _items(r):
            missing = [i for i in x.evidence_ids if i not in have]
            out.append(item("R-01", "fail" if missing or not x.evidence_ids else "pass", f"{r.agent}:{target}", "missing_evidence" if missing or not x.evidence_ids else None, actual=", ".join(missing) or None, evidence_ids=x.evidence_ids))
        for msg in catalog.validate(r):
            out.append(item("R-07", "fail", f"{r.agent}", "unregistered_metric", note=msg))
    return {"checks": out}


def _fin_row(e, account_id):
    """FIN 근거 재조회 (원래 rcept_no로만). 반환 (행, 사유)."""
    m = re.search(r"\((\d{4})\.(\d{2})\)", e.title or "")
    if not m or m.group(2) not in REPRT_BY_MONTH:
        return None, "보고서 기간을 근거 제목에서 알 수 없음"
    _, rcept_no, fs_div, _ = e.evidence_id.split(":", 3)
    try:
        d = dart.get_client().get_json("fnlttSinglAcntAll.json", corp_code=e.corp_code, bsns_year=m.group(1), reprt_code=REPRT_BY_MONTH[m.group(2)], fs_div=fs_div)
    except DartQuotaError:      # DART 일일 한도(020): 삼키지 않고 올린다 (2026-11-11)
        raise
    except Exception as x:      # 캐시·재조회 모두 실패
        return None, f"재조회 실패: {type(x).__name__}"
    rows = [r for r in d.get("list", []) if r.get("account_id") == account_id]
    if not rows:
        return None, "재조회 응답에 계정 없음"
    if rows[0].get("rcept_no") != rcept_no:      # 최신 정정본으로 바꿔 대조하지 않는다 (7장)
        return None, f"응답이 다른 접수번호 {rows[0].get('rcept_no')}"
    return rows[0], None


def recheck_sources(state) -> dict:
    """R-02. FIN: 재조회 값과 단일 근거 Metric 값 비교. CALC: meta로 재계산. 그 밖(문서·목록·기사)은 재조회 대상 값이 없어 확인 불가."""
    out = []
    for r in state.get("results") or []:
        ev = {e.evidence_id: e for e in r.evidence}
        single = {m.evidence_ids[0]: m for m in r.metrics if len(m.evidence_ids) == 1}
        for eid, e in ev.items():
            target = f"{r.agent}:{eid}"
            if eid.startswith("CALC:"):
                ok = _recalc_ok(e.meta)
                out.append(item("R-02", "pass" if ok else "fail", target, None if ok else "value_mismatch", expected=str(e.meta.get("value")), evidence_ids=[eid]))
            elif eid.startswith("FIN:"):
                row, why = _fin_row(e, eid.split(":", 3)[3])
                if row is None:
                    out.append(item("R-02", "unverifiable", target, "unverifiable", note=why, evidence_ids=[eid]))
                    continue
                m = single.get(eid)
                got = row.get("thstrm_amount")
                if m is None or m.value is None or not re.fullmatch(r"-?\d+", (got or "").replace(",", "")):
                    out.append(item("R-02", "pass", target, note="재조회 행 확인", evidence_ids=[eid]))
                    continue
                diff = abs(int(got.replace(",", "")) - m.value)
                out.append(item("R-02", "pass" if diff <= VALUE_TOLERANCE else "fail", f"{r.agent}:{m.metric_id}", None if diff <= VALUE_TOLERANCE else "value_mismatch", expected=got, actual=str(m.value), evidence_ids=[eid]))
            else:
                out.append(item("R-02", "unverifiable", target, "unverifiable", note="재조회 값 대조 대상 아님", evidence_ids=[eid]))
    return {"checks": out}


def check_asof(state) -> dict:
    """R-03 근거 날짜 ≤ as_of."""
    as_of = state["request"]["as_of"]
    out = []
    for r in state.get("results") or []:
        for e in r.evidence:
            late = e.published_at.isoformat() > as_of
            out.append(item("R-03", "fail" if late else "pass", f"{r.agent}:{e.evidence_id}", "future_evidence" if late else None, actual=e.published_at.isoformat(), expected=f"≤ {as_of}", evidence_ids=[e.evidence_id]))
    return {"checks": out}


def check_cross_agent(state) -> dict:
    """R-04 같은 metric_id를 두 에이전트가 낸 경우 값 일치 (허용오차 0원)."""
    by = {}
    for r in state.get("results") or []:
        for m in r.metrics:
            if m.metric_id in CROSS_IDS and m.data_status == "ok":      # 같은 기간끼리만 비교한다 (재무 에이전트는 여러 기간을 낸다)
                by.setdefault((m.metric_id, m.period), []).append((r.agent, m))
    out = []
    for (mid, _), rows in by.items():
        if len({a for a, _ in rows}) < 2:
            continue
        values = {m.value for _, m in rows}
        same = len(values) == 1
        out.append(item("R-04", "pass" if same else "fail", mid, None if same else "cross_agent_mismatch", note=" / ".join(f"{a} {m.value} ({m.period})" for a, m in rows), evidence_ids=[i for _, m in rows for i in m.evidence_ids]))
    return {"checks": out}


def check_coverage(state) -> dict:
    """R-05 필수 지표 커버리지. data_status를 그대로 적는다."""
    status = {}
    for r in state.get("results") or []:
        for m in r.metrics:
            status.setdefault(m.metric_id, m.data_status)
        for c in r.classifications:
            status.setdefault(c.key, "ok" if c.value not in ("missing", "unknown") else c.value)
    out, coverage = [], {}
    for mid in state["request"].get("required_metrics") or []:
        s = status.get(mid, "absent")
        coverage[mid] = s
        out.append(item("R-05", "pass" if s == "ok" else "fail", mid, None if s == "ok" else "coverage_gap", actual=s))
    return {"checks": out, "coverage": coverage}


def check_forbidden(state) -> dict:
    """R-06 / A-04 금지 필드·평가어. 오케스트레이터 규칙 문구는 허용한다."""
    out = []
    code = "A-04" if state["request"]["mode"] == "answer" else "R-06"
    texts = []
    for r in state.get("results") or []:
        for p in forbidden_fields(r.model_dump()):
            out.append(item("R-06", "fail", f"{r.agent}:{p}", "forbidden_term", note="금지 필드"))
        texts.append((r.agent, r.report_markdown or ""))
    if state.get("document"):
        texts.append(("document", state["document"]))
    for target, text in texts:
        clean = text
        for phrase in RULE_PHRASES:
            clean = clean.replace(phrase, "")
        hits = [t for t in FORBIDDEN_TERMS if t in clean]
        out.append(item(code, "fail" if hits else "pass", target, ("judgment_without_source" if code == "A-04" else "forbidden_term") if hits else None, actual=", ".join(hits) or None))
    return {"checks": out}


# ---- answer 모드 ----
def split_sentences(state) -> dict:
    """문장 단위로 나누고 각주 [n]을 근거 ID로 바꾼다."""
    doc, foot = state.get("document") or "", state.get("footnotes") or {}
    rows = []
    for no, text in enumerate([s for s in re.split(r"(?<=\.)\s+|\n+", doc) if s.strip() and not s.lstrip().startswith(("#", "|", "["))], 1):
        nums = [int(n) for n in _FOOT.findall(text)]
        rows.append({"no": no, "text": text.strip(), "footnotes": nums, "evidence_ids": [i for n in nums for i in foot.get(str(n), foot.get(n, []))]})
    return {"sentences": rows}


def _norm(value: str, unit: str) -> tuple[float, str]:
    v = float(value.replace(",", ""))
    u = unit.replace(" ", "")
    if u.startswith("억"):
        return v * 1e8, "원"
    if u == "조":
        return v * 1e12, "원"
    if u.startswith("백만"):
        return v * 1e6, "원"
    if u.startswith("만"):
        return v * 1e4, "원"
    return (v, "%") if u in ("%", "%p") else (v, "배") if u == "배" else (v, "원")


def check_numbers(state) -> dict:
    """A-01. 단위가 붙은 숫자를 정규화해 같은 문장 각주 근거의 값과 비교. 억 원은 ±0.5억, %·배는 ±0.05 허용."""
    cited = state.get("cited") or {}
    out = []
    for s in state.get("sentences") or []:
        for m in _NUM_UNIT.finditer(_FOOT.sub("", s["text"])):
            v, unit = _norm(m.group(1), m.group(2))
            target = f"문장 {s['no']}"
            if not s["evidence_ids"]:
                out.append(item("A-01", "fail", target, "number_without_source", actual=m.group(0)))
                continue
            pool = [c for i in s["evidence_ids"] if i in cited for c in (cited[i].get("values") or [cited[i]]) if isinstance(c.get("value"), (int, float))]      # 근거 1개에 지표 여러 개가 걸릴 수 있다
            tol = DISPLAY_TOLERANCE["억"] if unit == "원" and "억" in m.group(2) else DISPLAY_TOLERANCE.get(unit, 0.5)
            ok = any(math.isclose(abs(v), abs(c["value"] * (100 if unit == "%" and c.get("unit") == "비율" else 1)), abs_tol=tol) for c in pool)
            out.append(item("A-01", "pass" if ok else "fail", target, None if ok else "number_mismatch", actual=m.group(0), expected=", ".join(str(c["value"]) for c in pool) or None, evidence_ids=s["evidence_ids"]))
    return {"checks": out}


def check_footnotes(state) -> dict:
    """A-02 각주가 실존하는 근거를 가리키는지."""
    foot, cited = state.get("footnotes") or {}, state.get("cited") or {}
    out = []
    for s in state.get("sentences") or []:
        for n in s["footnotes"]:
            ids = foot.get(str(n), foot.get(n))
            ok = bool(ids) and all(i in cited for i in ids)
            out.append(item("A-02", "pass" if ok else "fail", f"문장 {s['no']} [{n}]", None if ok else "broken_footnote", evidence_ids=ids or []))
    return {"checks": out}


def check_claims(state) -> dict:
    """A-03. A-01·A-02를 통과하고 숫자나 고유명사(영문 대문자, 따옴표)가 있는 문장만 LLM으로 확인. 최대 MAX_CLAIM_CHECKS건."""
    failed = {c.target.split(" [")[0] for c in state.get("checks") or [] if c.code in ("A-01", "A-02") and c.outcome == "fail"}
    cited = state.get("cited") or {}
    targets = [s for s in state.get("sentences") or [] if f"문장 {s['no']}" not in failed and s["evidence_ids"] and re.search(r"\d|[A-Z]{2,}|[\"'「]", _FOOT.sub("", s["text"]))]
    out, llm = [], state.get("llm_calls", 0)
    for i, s in enumerate(targets):
        target = f"문장 {s['no']}"
        if i >= MAX_CLAIM_CHECKS:
            out.append(item("A-03", "unverifiable", target, "claim_check_skipped"))
            continue
        quotes = " / ".join(f"[{e}] {cited[e].get('quote') or cited[e].get('value')}" for e in s["evidence_ids"] if e in cited)
        try:
            r = call_llm(PROMPT, {"sentence": _FOOT.sub("", s["text"]), "quotes": quotes}, ClaimCheckOutput, run_id=state["request"]["request_id"], as_of=state["request"]["as_of"])
            llm += 1
        except Exception as e:      # 판정을 못 받으면 확인 불가
            out.append(item("A-03", "unverifiable", target, "unverifiable", note=f"LLM {type(e).__name__}"))
            continue
        kind = {"supported": None, "not_supported": "claim_not_supported", "insufficient": "claim_insufficient"}[r.verdict]
        out.append(item("A-03", "pass" if kind is None else "fail", target, kind, note=r.reason, evidence_ids=s["evidence_ids"]))
    return {"checks": out, "llm_calls": llm}


def build_report(state) -> dict:
    req = state["request"]
    checks = state.get("checks") or []
    failed = [c for c in checks if c.outcome == "fail"]
    return {"report": VerificationReport(request_id=req["request_id"], mode=req["mode"], as_of=req["as_of"], corp_code=req.get("corp_code"), checks=checks, failed=failed,
                                         unverifiable=[c for c in checks if c.outcome == "unverifiable"], coverage=state.get("coverage") or {}, failed_targets=list(dict.fromkeys(c.target for c in failed)), llm_calls=state.get("llm_calls", 0))}


def route_mode(state) -> dict:
    return {}
