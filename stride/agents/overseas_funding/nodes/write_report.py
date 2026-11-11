import re

from agents.overseas_funding.config import AGENT_KEY
from agents.overseas_funding.nodes.update_state import decide_status, main_project
from agents.overseas_funding.schemas import ReportOutput
from core import catalog
from core.llm import call_llm
from core.nodeguard import guarded
from core.report_guard import forbidden_terms

PROMPT = "agents/overseas_funding/prompts/write_report.md"
SOURCE = {"dart_document": "DART 공시", "dart_api": "DART 공시 API", "dart_list": "DART 공시 목록", "news": "언론 보도", "calc": "STRIDE 계산"}
STAGE = {1: "검토·언급", 2: "계획 공표", 3: "협의", 4: "이사회 결의", 5: "집행"}
METHOD = {"new_plant": "공장 신설", "expansion": "증설", "new_subsidiary": "법인 설립", "acquisition": "인수", "equity_investment": "지분 출자", "jv": "합작", "other": "기타"}
# 10.6 작성 규칙의 판단 표현. 공통 목록(core.report_guard)에 더한다
EXTRA_TERMS = ("매력", "위험하다", "좋다", "나쁘다", "적합")
INTERNAL = ("parse_request", "resolve_company", "collect_disclosures", "extract_periodic_plan", "parse_major_events", "collect_news", "extract_news", "merge_signals", "resolve_conflicts", "scope_gate", "compute_funding_gap", "verify", "update_state", "write_report", AGENT_KEY, "signal_id", "evidence_id", "project_key")
KIND = {"fact": "사실", "calc": "계산", "inference": "추정", "unverified": "미검증"}
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
DIRECTION = {"cancelled": "취소", "postponed": "연기", "reduced": "축소", "expanded": "확대"}
LEAD = {"신호 없음": "기준일까지 해외 투자 관련 공시·계획·기사 신호가 확인되지 않았다.", "범위 밖": "해외 관련 신호가 신규 해외 성장 투자 조건을 충족하지 않는다.", "취소": "해외 투자 결정이 철회·취소 공시로 취소 상태다."}


def eok(v) -> str:
    return "-" if v is None else f"{round(v / 1e8):,}"


def clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def notes(findings, alerts, evidence: dict) -> tuple[dict, list[str]]:
    """각주: 같은 문서(출처·문서명·날짜)는 번호 1개. 반환 ({evidence_id: 번호}, 출처 줄)."""
    num, lines, by_line = {}, [], {}
    for i in dict.fromkeys([i for f in findings for i in f.evidence_ids] + [i for a in alerts for i in a.evidence_ids]):
        e = evidence.get(i)
        title = catalog.get(e.title)["name"] if e and e.source_type == "calc" and e.title in catalog.load() else clean(e.title if e else "")      # 계산 근거는 지표 이름 (지표 ID가 보고서에 옮겨지면 내부 이름 검사에 걸린다)
        line = f"{SOURCE.get(e.source_type, e.source_type)}, {title}, {e.published_at}, {e.source_grade}" if e else "근거 없음"
        if line not in by_line:
            by_line[line] = len(lines) + 1
            lines.append(f"[{by_line[line]}] {line}")
        num[i] = by_line[line]
    return num, lines


def feet(ids, num) -> str:
    got = sorted({num[i] for i in ids if i in num})
    return "".join(f"[{n}]" for n in got)


def project_rows(projects: list[dict], signals: dict, num: dict, *, all_projects=False) -> list[str]:
    rows = []
    for p in projects:
        if not (p.get("gate_pass") or (all_projects and p.get("amount_source") == "major_event")):
            continue
        ids = [e for s in p.get("amount_signal_ids") or p["signal_ids"] if s in signals for e in signals[s].evidence_ids]
        stage = STAGE.get(p["stage"], p["stage"])
        if p.get("change_direction") in DIRECTION:      # 단계를 낮춘 이유를 같이 적는다 (7.8 4)
            stage = f"{stage} ({DIRECTION[p['change_direction']]} 공시 반영)"
        rows.append(f"| {p.get('name') or p.get('target_country') or '-'} | {p.get('target_country') or '-'} | {METHOD.get(p.get('method'), '-')} | {eok(p.get('amount_krw'))} | {stage} | {p['latest_event_date']} | {feet(ids, num)} |")
    return rows


def material(state, findings, num, source_lines) -> str:
    """LLM 자료: 검증을 거친 Finding, 표에 쓸 코드 값, 확인 필요, 출처. 원문·기사 본문은 넘기지 않는다 (7.13 1)."""
    signals = {s.signal_id: s for s in state.get("signals_merged") or []}
    lines = ["[사실] (종류) 문장 각주. 종류 fact는 공시·기사 근거와 대조를 마친 사실이다"]
    lines += [f"- ({f.kind}{', 언론 보도' if press(f, state) else ''}) {f.text} {feet(f.evidence_ids, num)}" for f in findings]
    lines += ["", "[해외 투자 내용 표 값] (금액은 최신 정정본 기준 억원. 단계 칸은 그대로 쓴다)", "| 프로젝트 | 국가 | 방식 | 금액(억원) | 단계 | 최근 신호일 | 근거 |"]
    lines += project_rows(state.get("projects") or [], signals, num)
    lines += ["", "[경보]"] + [f"- {a.message} {feet(a.evidence_ids, num)}" for a in state.get("alerts") or []]
    lines += ["", "[확인 필요]"] + [f"- {q}" for q in confirm_items(state)]
    lines += ["", "[출처]"] + source_lines
    return "\n".join(lines)


def press(f, state) -> bool:
    """근거가 모두 언론 보도(C등급)인 fact. 보고서는 '~로 보도되었다'로 쓴다 (10.6, D9)."""
    ev = {e.evidence_id: e for e in state.get("evidence") or []}
    return f.kind == "fact" and bool(f.evidence_ids) and all(ev.get(i) is not None and ev[i].source_grade == "C" for i in f.evidence_ids)


def confirm_items(state) -> list[str]:
    items = [f"거래 상태 공시: {w['report_nm']} ({w['since']})" for w in state.get("trading_status_warnings") or []]
    return items + list(dict.fromkeys(state.get("open_questions") or []))[:10]


def allowed_numbers(text: str) -> set[str]:
    """자료에 있는 숫자 표기와, 원 단위 금액의 억원 환산(반올림·내림)."""
    out = {n.replace(",", "") for n in _NUM.findall(text)}
    for m in _NUM.finditer(text):      # '원'이 없는 칸 금액(fdpp_op 20,000,000,000)도 억원 환산을 허용한다
        v = float(m.group(0).replace(",", ""))
        if v >= 1e7:
            out |= {str(round(v / 1e8)), str(int(v / 1e8))}
    return out


def check_report(text: str, n_sources: int, allowed: set[str]) -> list[str]:
    """7.13 3 출력 검사 4종. 위반 목록 (빈 목록 = 통과)."""
    errs = []
    feet = [int(x) for x in re.findall(r"\[(\d+)\]", text)]
    bad = sorted({n for n in feet if not 1 <= n <= n_sources})
    if bad or not feet:
        errs.append(f"각주 매핑 실패: {bad or '각주 없음'}")
    body = re.sub(r"\[\d+\]", "", text)
    new = sorted({n.replace(",", "") for n in _NUM.findall(body)} - allowed)
    if new:
        errs.append(f"자료에 없는 숫자: {new[:8]}")
    inner = [w for w in INTERNAL if w in text] + re.findall(r"\bS[1-6]\b", text)
    if inner:
        errs.append(f"내부 이름: {inner}")
    terms = forbidden_terms(text) + [t for t in EXTRA_TERMS if t in text]
    if terms:
        errs.append(f"판단 표현: {terms}")
    return errs


def template_report(state, findings, num, source_lines, status) -> str:
    """코드 보고서 (10.6 형식). LLM 실패·범위 밖·사실 없음에 쓴다."""
    company, req = state["company"], state["request"]
    signals = {s.signal_id: s for s in state.get("signals_merged") or []}
    main = main_project(state.get("projects") or [])
    if main:
        lead = f"{main.get('target_country') or '국가 미상'} {main.get('name') or ''} 투자가 '{STAGE.get(main['stage'], main['stage'])}' 단계다.".replace("  ", " ")
    else:
        lead = f"{LEAD.get(status.value, '')} (범위 조건 {state.get('scope_reason') or '판정 없음'})".strip()
    gap = state.get("funding_gap") if state.get("in_scope") else None
    m = {x.metric_id: x for x in state.get("metrics") or []}

    def row(label, mid):
        x = m.get(mid)
        return f"| {label} | {eok(x.value) if x else '-'} | {feet(x.evidence_ids if x else [], num)} |"
    lines = [f"### {company.corp_name} — 해외진출·자금수요 사실 요약 (기준일 {req.as_of})", "", f"**신호 상태**: {status.value}", lead, "", "**해외 투자 내용**",
             "| 프로젝트 | 국가 | 방식 | 금액(억원) | 단계 | 최근 신호일 | 근거 |", "|---|---|---|---|---|---|---|"]
    lines += project_rows(state.get("projects") or [], signals, num, all_projects=not state.get("in_scope")) or ["| 없음 | | | | | | |"]
    lines += ["", "**자금 공백**", "| 항목 | 금액(억원) | 근거 |", "|---|---|---|"]
    if gap:
        lines += [row("해외 투자액", "ovs.overseas_investment_amount"), row("현금성 자산", "fin.cash_and_equivalents"), row("단기금융상품", "fin.short_term_financial_assets"), row("최근 4분기 영업현금흐름", "fin.ttm_operating_cash_flow"),
                  row("확정 조달", "ovs.confirmed_overseas_funding"), row("자금 공백", "ovs.funding_gap"), row("미확정 조달 (자금 공백 계산에 넣지 않음)", "ovs.unconfirmed_overseas_funding")]
    else:
        lines.append("| 계산하지 않음 (범위 밖) | - | |")
    facts = [f"- {'△ ' if f.kind == 'unverified' or f.text.split(' ', 1)[-1][:2] in [d[:2] for d in DIRECTION.values()] else ''}{f.text}{' (로 보도되었다)' if press(f, state) else ''} {feet(f.evidence_ids, num)}" + (" (공시로 확인되지 않음)" if f.kind == "unverified" else "") for f in findings[:5]]
    facts += [f"- △ {a.message} {feet(a.evidence_ids, num)}" for a in state.get("alerts") or []]
    lines += ["", "**주요 사실**"] + (facts or ["- 없음"])
    lines += ["", "**확인 필요**"] + ([f"- {q}" for q in confirm_items(state)] or ["- 없음"])
    lines += ["", "**출처**"] + (source_lines or ["없음"])
    return "\n".join(lines)


def out_of_scope_findings(state) -> list:
    """범위 밖이면 verify를 거치지 않는다. 템플릿에 쓸 정형 사실(S4·S5·S6 요약)만 코드로 만든다."""
    from core.schemas import Finding
    rows = [s for s in state.get("signals_merged") or [] if s.signal_type.value in ("S4_confirmed", "S5_funding", "S6_alert")]

    def text(s):
        if s.signal_type.value == "S6_alert":
            return f"{s.event_date} {DIRECTION.get(s.change_direction, '변경')} 공시: {s.summary.split(': ', 1)[-1]}"
        return f"{s.event_date} {s.summary}" + (" (국내)" if s.is_overseas is False else f" ({s.target_country})" if s.target_country else "")
    return [Finding(finding_id=f"G{i}", kind="fact", text=text(s), evidence_ids=s.evidence_ids, verified=True, verify_note="정형 칸") for i, s in enumerate(sorted(rows, key=lambda s: s.event_date, reverse=True)[:5], 1)]


@guarded
def write_report(state) -> dict:
    """검증된 Finding만으로 사실 요약을 만든다 (7.13). 범위 안은 LLM이 쓰고 출력 검사 4종을 통과해야 한다. 1회 재생성 뒤에도 실패하면 템플릿."""
    req, company = state["request"], state.get("company")
    if not company:      # 기업을 특정하지 못함: LLM 없이
        names = [q for q in state.get("open_questions") or [] if q.startswith("기업 후보")]
        return {"report_markdown": f"### {req.company or req.corp_code} — 해외진출·자금수요 사실 요약 (기준일 {req.as_of})\n\n기업을 특정하지 못했습니다.\n" + "".join(f"\n- {n}" for n in names), "report_source": "template"}
    evidence = {e.evidence_id: e for e in state.get("evidence") or []}
    status = state.get("signal_status") or decide_status(state)
    findings = [f for f in state.get("findings") or [] if f.verified or f.kind == "unverified"]
    alerts = state.get("alerts") or []
    if not state.get("in_scope") or not findings:
        findings = findings or out_of_scope_findings(state)
        num, source_lines = notes(findings, alerts, evidence)
        text = template_report(state, findings, num, source_lines, status)
        errs = [e for e in check_report(text, len(source_lines), allowed_numbers(text)) if not e.startswith("각주") or source_lines]
        return {"report_markdown": text if not errs else None, "report_source": "template", "errors": [f"write_report: 템플릿 검사 실패 {errs}"] if errs else []}
    num, source_lines = notes(findings, alerts, evidence)
    data = material(state, findings, num, source_lines)
    allowed = allowed_numbers(data) | allowed_numbers(f"{req.as_of}")      # 각주 번호는 검사 전에 지우므로 허용 숫자에 넣지 않는다
    feedback, llm, last = "", state.get("llm_calls", 0), []
    for _ in range(2):
        try:
            out = call_llm(PROMPT, {"corp_name": company.corp_name, "as_of": req.as_of, "signal_status": status.value, "findings_and_evidence": data, "재생성_피드백": feedback}, ReportOutput, run_id=state["run_id"], as_of=req.as_of)
        except Exception as e:      # 호출 실패는 템플릿으로 간다
            last = [f"LLM {type(e).__name__}"]
            break
        llm += 1
        last = check_report(out.markdown, len(source_lines), allowed)
        if any(press(f, state) for f in findings) and "보도" not in out.markdown:      # D9: 보도 근거 사실을 단정형으로만 쓰지 않았는지
            last.append("언론 보도 근거 사실에 '보도되었다' 표현 없음")
        if not last:
            return {"report_markdown": out.markdown, "report_source": "llm", "llm_calls": llm}
        feedback = "## 이전 출력의 문제\n" + "\n".join(f"- {x}" for x in last) + "\n위 문제를 고쳐 다시 작성하세요."
    text = template_report(state, findings, num, source_lines, status)
    return {"report_markdown": text, "report_source": "template", "llm_calls": llm, "errors": [f"write_report: 템플릿 대체 ({'; '.join(last)[:200]})"]}
