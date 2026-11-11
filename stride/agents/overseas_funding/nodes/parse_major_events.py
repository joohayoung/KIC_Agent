import re

from agents.overseas_funding.calc.funding import canon_country, decision_amount, decision_sub, overseas_amount
from agents.overseas_funding.config import ALERT_EXCERPT_CHARS, CLASSIFY_BATCH_MAX_CHARS, FUNDING_EXCERPT_CHARS, KOREA_NAMES
from agents.overseas_funding.schemas import MajorEventBatchOutput, Signal, SignalType, Stage
from core import evidence as ev
from core.asof import UNKNOWN_NOTE
from core.clients import dart
from core.clients.dart import VIEWER_URL
from core.clients.dart_docs import plain_text
from core.llm import call_llm
from core.nodeguard import guarded
from core.schemas import Evidence

PROMPT = "agents/overseas_funding/prompts/classify_major_event.md"
FUNDING = {"rights_issue": "rights", "cb": "cb", "bw": "bw"}
SLOTS = ("fdpp_fclt", "fdpp_bsninh", "fdpp_op", "fdpp_dtrp", "fdpp_ocsa", "fdpp_etc")
API = {"rights": "piicDecsn", "cb": "cvbdIsDecsn", "bw": "bdwtIsDecsn"}
NOT_COUNTRY = ("주", "유", "사", "재", "가칭")     # 이름 끝 괄호가 국적이 아닌 실측 표기 (api_fields.md 33장)
USE_SLOT = {"시설자금": "fdpp_fclt", "영업양수자금": "fdpp_bsninh", "운영자금": "fdpp_op", "채무상환자금": "fdpp_dtrp", "타법인증권취득자금": "fdpp_ocsa", "기타자금": "fdpp_etc"}
SLOT_PURPOSE = {"시설자금": "growth_investment", "운영자금": "working_capital", "채무상환자금": "refinancing"}      # 7.5 R1 분할: 정형 칸이 근거이고 LLM 라벨보다 우선한다
_USE = r"【[^】]*(?:구체적\s*사용\s*목적|타법인\s*증권\s*취득자금|시설자금|운영자금|채무상환자금|영업양수자금)[^】]*】"
_num = lambda s: int(s.replace(",", "")) if s and re.fullmatch(r"-?[\d,]+", s.strip()) else None
_ws = lambda s: re.sub(r"\s+", "", s or "")


def parse_acquisition_form(text: str) -> dict:
    """거래소 타법인 취득 양식. 정정 공시는 정정표 뒤 본문을 쓰도록 마지막 양식에서 읽는다 (7.5, api_fields.md 21장). 칸을 못 읽으면 None."""
    starts = list(re.finditer(r"1\.\s*발행회사\s*회사명", text))
    t = text[starts[-1].start():] if starts else text
    name, country = None, None
    if m := re.search(r"회사명\s*\(\s*국적\s*\)\s*(.{1,120}?)\s*대표", t):      # 국적을 안 적은 양식이 있다: 회사명(국적) (주)이름 대표
        name = m.group(1)
        if tail := re.fullmatch(r"(.+?)\s*\(([^()]+)\)", name):
            if tail.group(2).strip() not in NOT_COUNTRY:
                name, country = tail.group(1), tail.group(2).strip()
    elif m := re.search(r"회사명\s*(.{1,120}?)\s*국적\s*(.{1,40}?)\s*대표", t):
        name, country = m.group(1), m.group(2)
    if name and not country:      # 회사명 칸에 국적이 없으면 상대방 표의 국적 칸을 쓴다: 성명(명칭) 국적 주소… 이름 국적 (api_fields.md 33장)
        if m := re.search(r"성명\(명칭\)\s*국적.{0,80}?" + re.escape(name) + r"\s+([가-힣]{2,12})\s", t):
            country = m.group(1)
    g = lambda p: m.group(1).strip() if (m := re.search(p, t)) else None
    return {"name": name, "country": country, "shares_acquired": _num(g(r"취득주식수\(주\)\s*([\d,]+)")), "shares_after": _num(g(r"소유주식수\(주\)\s*([\d,]+)")), "amount": _num(g(r"취득금액\(원\)\s*([\d,]+)")), "relation": g(r"회사와\s*의?\s*관계\s*(.*?)\s*(?:발행주식총수|주요사업)"),
            "purpose": g(r"취득목적\s*(.*?)\s*6\.\s*취득예정"), "scheduled": g(r"취득예정일자\s*(\d{4}-\d{2}-\d{2})"), "board": g(r"이사회결의일\(결정일\)\s*(\d{4}-\d{2}-\d{2})")}


def use_section(text: str, limit: int = FUNDING_EXCERPT_CHARS) -> str:
    """사용 목적 절: 첫 표지부터 사용 목적이 아닌 다음 【…】 앞까지 (7.5). 없으면 빈 문자열."""
    m = re.search(_USE, text)
    if not m:
        return ""
    end = next((x.start() for x in re.finditer(r"【[^】]*】", text[m.end():]) if not re.match(_USE, x.group(0))), None)
    return text[m.start(): m.end() + end if end is not None else len(text)][:limit]


def subsidiary_uses(text: str) -> dict[str, int]:
    """증자 공시 자금 목적 칸 {칸 이름: 금액}. 값 없는 칸은 뺀다. 정정 공시는 본문이 정정표 뒤에 있어 같은 이름이면 뒤 값을 쓴다."""
    found = re.findall(r"(시설자금|영업양수자금|운영자금|채무상환자금|타법인\s*증권\s*취득자금|기타자금)\s*\(원\)\s*([\d,]+)", text)
    return {_ws(a): _num(b) for a, b in found if _num(b)}


def corrections_of(filing, filings, client) -> list:
    """같은 공시명의 정정 중 정정표의 원공시 제출일이 이 공시 접수일인 것 (접수 순)."""
    day = filing.rcept_dt.isoformat()
    return [f for f in filings if f.is_correction and f.report_nm_norm == filing.report_nm_norm and f.filer_scope == filing.filer_scope and f.rcept_dt >= filing.rcept_dt and day in plain_text(client.document(f.rcept_no))[:600]]


def make_evidence(corp_code, no, dt, section, title, quote=None, value=None) -> Evidence:
    """value: 정형 칸 금액. 7.11 C3 숫자 대조에 쓴다."""
    return Evidence(evidence_id=ev.dart_section(no, section), source_grade="A", source_type="dart_document", corp_code=corp_code, published_at=dt, title=title, url=VIEWER_URL.format(rcept_no=no), quote=(quote or "")[:300] or None, meta={} if value is None else {"value": value})


def form_quote(form: dict) -> str:
    return f"회사명 {form.get('name')} / 국적 {form.get('country')} / 회사와 관계 {form.get('relation')} / 취득금액 {form.get('amount')} / 취득목적 {form.get('purpose')}"


def material(eid, f, body) -> str:
    return f'<자료 id="{eid}" report_nm="{f.report_nm_norm}" rcept_dt="{f.rcept_dt}">\n{body}\n</자료>'


def excerpt_around(text: str, pattern: str) -> str:
    m = re.search(pattern, text)
    start = max(0, m.start() - 100) if m else 0
    return text[start: start + FUNDING_EXCERPT_CHARS]


class Batch:
    """R1~R5를 지나 분류할 공시를 모으고, 라벨을 받아 신호로 바꾼다."""

    def __init__(self, state):
        self.state, self.client = state, dart.get_client()
        self.cc = state["company"].corp_code
        self.filings, self.raw = state.get("filings") or [], state.get("raw_filings")
        self.entries, self.signals, self.items, self.decisions, self.evidence, self.questions, self.deferred = [], [], [], [], [], [], []

    def add(self, f, kind, body, source, **data):
        eid = ev.dart_section(source.rcept_no, "정형")
        self.evidence.append(make_evidence(self.cc, source.rcept_no, source.rcept_dt, "정형", source.report_nm))
        self.entries.append({"eid": eid, "filing": f, "source": source, "kind": kind, "text": body, "block": material(eid, source, body), **data})

    # ---- 규칙 단계 ----
    def acquisition_exchange(self, f):
        corr = corrections_of(f, self.filings, self.client)
        for src in [*reversed(corr), f]:      # 철회 정정은 칸이 '-'로 비어 있다. 값이 남은 가장 최신 본문을 쓴다
            text = plain_text(self.client.document(src.rcept_no))
            form = parse_acquisition_form(text)
            if form["amount"] is not None and (form["name"] or "-") != "-":
                break
        country = form["country"]
        if country and any(k in country for k in KOREA_NAMES):       # R2
            self.signal_s4(f, src, form, is_overseas=False, purpose="domestic", country=canon_country(country), method=None, summary=f"{form['name']} 취득결정")
            return
        if form["amount"] is None:
            self.questions.append(f"취득 금액 칸 확인 불가: {src.rcept_no}")
        fields = f"회사명 {form['name']} / 국적 {country} / 회사와 관계 {form['relation']} / 취득금액 {form['amount']} / 취득목적 {form['purpose']} / 취득예정일자 {form['scheduled']}"
        self.add(f, "acquisition", fields + "\n" + excerpt_around(text, r"기타 투자판단"), src, form=form, corrections=[c.rcept_no for c in corr])

    def acquisition_ds005(self, f):
        rows = self.client.major_event("acquisition_stock", self.cc, f.rcept_dt, f.rcept_dt, self.raw)
        for row in rows:
            if row.get("_version") == "unknown":
                self.unknown_signal(f, SignalType.CONFIRMED)
                continue
            form = {"name": row.get("iscmp_cmpnm"), "country": row.get("iscmp_nt"), "amount": _num(row.get("inhdtl_inhprc")), "relation": row.get("iscmp_rl_cmpn"), "purpose": row.get("inh_pp"), "scheduled": None, "board": row.get("bddd")}
            src = next((x for x in self.filings if x.rcept_no == row["rcept_no"]), f)
            if form["country"] and any(k in form["country"] for k in KOREA_NAMES):     # R2
                self.signal_s4(f, src, form, is_overseas=False, purpose="domestic", country=canon_country(form["country"]), method=None, summary=f"{form['name']} 취득결정")
                continue
            text = plain_text(self.client.document(src.rcept_no))
            fields = f"회사명 {form['name']} / 국적 {form['country']} / 회사와 관계 {form['relation']} / 취득금액 {form['amount']} / 취득목적 {form['purpose']}"
            self.add(f, "acquisition", fields + "\n" + excerpt_around(text, r"기타 투자판단|취득목적"), src, form=form, corrections=[])

    def funding(self, f):
        kind = FUNDING[f.sub_kind]
        for i, row in enumerate(self.client.major_event(f.sub_kind, self.cc, f.rcept_dt, f.rcept_dt, self.raw)):
            if row.get("_version") == "unknown":
                self.unknown_signal(f, SignalType.FUNDING, i)
                self.decisions.append({"rcept_no": f.rcept_no, "rcept_dt": f.rcept_dt.strftime("%Y%m%d"), "kind": kind, "sub": None, "amount": None, "board": None, "overseas_amount": None, "version": "unknown"})
                continue
            slots = {s: _num(row.get(s)) for s in SLOTS}
            board = re.findall(r"\d+", row.get("bddd") or "")
            dec = {"rcept_no": row["rcept_no"], "rcept_dt": f.rcept_dt.strftime("%Y%m%d"), "kind": kind, "sub": decision_sub(kind, row), "amount": decision_amount(kind, row), "board": "".join(x.zfill(2) for x in board) if len(board) == 3 else None, "overseas_amount": None, "version": "ok", "filing_rcept_no": f.rcept_no}
            self.decisions.append(dec)
            src = next((x for x in self.filings if x.rcept_no == row["rcept_no"]), f)
            if not any(slots[s] for s in ("fdpp_fclt", "fdpp_bsninh", "fdpp_ocsa", "fdpp_etc")):     # R3
                purpose = "refinancing" if slots["fdpp_dtrp"] and not slots["fdpp_op"] else "working_capital"
                self.signal_s5(f, row["rcept_no"], i, kind, is_overseas=False, purpose=purpose, amount=None, slots=slots)
                continue
            text = plain_text(self.client.document(src.rcept_no))
            fields = " / ".join(f"{s} {v:,}" for s, v in slots.items() if v)
            section = use_section(text) or excerpt_around(text, r"자금조달의 목적")
            self.add(f, "funding", fields + "\n" + section, src, slots=slots, decision=dec, index=i, rcept_no=row["rcept_no"], fund_kind=kind, section=section)

    def needs_label(self, f):
        text = plain_text(self.client.document(f.rcept_no))
        kind = {"new_facility": "facility", "acquisition_asset": "asset", "business_transfer": "transfer"}[f.sub_kind]
        pattern = r"투자금액\(원\)\s*([\d,]+)" if kind == "facility" else r"취득금액\(원\)\s*([\d,]+)" if kind == "asset" else r"양수금액\(원\)\s*([\d,]+)"
        amount = _num(m.group(1)) if (m := re.search(pattern, text)) else None
        if amount is None and kind == "facility":
            self.questions.append(f"투자 금액 칸 확인 불가: {f.rcept_no}")
        self.add(f, kind, excerpt_around(text, r"투자목적|취득목적|양수목적"), f, amount=amount, corrections=[c.rcept_no for c in corrections_of(f, self.filings, self.client)])

    def alert(self, f):
        eid = ev.dart_section(f.rcept_no, "정형")
        same = next((x for x in self.entries if x["eid"] == eid), None)
        if same:      # 취득 자료로 이미 들어간 최신 정정본이다. 라벨 1개로 S4와 S6을 함께 만든다
            same["also_alert"] = True
            return
        self.add(f, "alert", plain_text(self.client.document(f.rcept_no))[:ALERT_EXCERPT_CHARS], f)

    def alert_signal(self, f, eid, lab):
        """변경 공시마다 S6 후보를 만든다. 라벨이 none이거나 없어도 만든다: 방향은 merge_signals가 정형 칸으로 다시 읽고, 연결되지 않은 것은 기록만 남긴다 (7.9)."""
        direction = lab.change_direction if lab else "none"
        self.signals.append(Signal(signal_id=f"{self.cc}:S6:{f.rcept_no}", corp_code=self.cc, signal_type=SignalType.ALERT, event_date=f.rcept_dt, is_overseas=lab.is_overseas if lab else False, target_country=canon_country(lab.target_country) if lab else None, method=lab.method if lab else None, purpose_category=lab.purpose_category if lab else "unknown", amount_krw=None, amount_original=None, stage=Stage.MENTIONED, summary=f"{direction}: {(lab.related_project if lab else None) or f.report_nm_norm}"[:200], change_direction=direction, evidence_ids=[eid]))

    def attach_subsidiary_funding(self):
        """같은 날 같은 대상의 종속회사 증자 공시 칸을 취득 자료에 붙이고, 연결 종속회사 출자면 칸 분할을 예약한다 (7.5 R1). 증자 공시 자체의 신호는 만들지 않는다."""
        for f in self.deferred:
            corr = corrections_of(f, self.filings, self.client)
            src = corr[-1] if corr else f
            t = plain_text(self.client.document(src.rcept_no))
            name = re.search(r"종속회사인\s*(.+?)\s*의\s*주요경영사항", t)
            uses = subsidiary_uses(t)
            if not name or not uses:
                continue
            for x in self.entries:
                if x["kind"] == "acquisition" and x["filing"].rcept_dt == f.rcept_dt and _ws(x["form"]["name"]) == _ws(name.group(1)):
                    note = "같은 날 대상 회사 증자 공시의 자금 목적: " + ", ".join(f"{a} {b:,}" for a, b in uses.items())
                    x["block"] = x["block"].replace("</자료>", note + "\n</자료>")
                    x["text"] += " " + note
                    if not re.search(r"종속|자회사", x["form"]["relation"] or ""):
                        continue
                    if sum(uses.values()) == x["form"]["amount"]:
                        x["split"] = {"uses": uses, "filing": f, "source": src}
                    else:      # 출자금과 증자 칸이 1:1로 대응하지 않으면 칸으로 나눌 근거가 없다
                        self.questions.append(f"종속회사 증자 칸 합계 불일치, 분할 안 함: 취득 {x['form']['amount']} / 칸 합계 {sum(uses.values())}: {src.rcept_no}")

    def split_signals(self, x, lab, country) -> tuple[int, list[dict]]:
        """연결 종속회사 출자를 증자 공시 칸으로 나눈다 (7.5 R1). 투자액은 시설 칸뿐이다. 운영 = working_capital(별도 필드), 채무상환 = refinancing, 그 외 칸 = LLM 라벨. 금액·제외 여부는 라벨과 무관하다."""
        f, src, form, s = x["filing"], x["source"], x["form"], x["split"]
        base = make_evidence(self.cc, src.rcept_no, src.rcept_dt, "정형:취득금액(원)", src.report_nm, form_quote(form), form.get("amount"))
        self.evidence.append(base)
        invested, growth_ids, rows, others = 0, [], [], []
        for use, amount in s["uses"].items():
            purpose = SLOT_PURPOSE.get(use) or (lab.purpose_category if lab else "unknown")
            e = make_evidence(self.cc, s["source"].rcept_no, s["source"].rcept_dt, f"정형:{use}(원)", s["source"].report_nm, f"{use}(원) {amount:,}", amount)
            self.evidence.append(e)
            rows.append({"use": use, "amount": amount, "purpose": purpose, "included": use == "시설자금"})
            if use == "시설자금":
                invested += amount
                growth_ids.append(e.evidence_id)
            else:
                others.append((use, amount, purpose, e.evidence_id))
                if use == "채무상환자금":
                    self.questions.append(f"종속회사 증자 채무상환 용도 {amount:,}: {purpose}, 투자액에서 제외")
                elif use != "운영자금":      # 운영 칸은 s4_items·FundingGap의 해외 법인 운영자금 필드로 표시한다
                    self.questions.append(f"종속회사 증자 {use} {amount:,}: {purpose}, 투자액에서 제외")
        common = dict(is_overseas=True, country=country, method=lab.method if lab else None)
        if invested:
            self.signal_s4(f, src, form, purpose="growth_investment", summary=f"{form['name']} 출자 중 시설자금 칸", amount=invested, ids=[base.evidence_id, *growth_ids], **common)
        for use, amount, purpose, eid in others:
            self.signal_s4(f, src, form, purpose=purpose, summary=f"{form['name']} 취득결정 ({use})", amount=amount, ids=[base.evidence_id, eid], suffix=USE_SLOT[use], **common)
        return invested, rows

    def hybrid(self, f):
        """R5: 신호 없음. 같은 날 CB와 회차·금액·납입일이 맞으면 결정 1건, 아니면 open_question."""
        text = plain_text(self.client.document(f.rcept_no))
        same_day = [x for x in self.filings if x.sub_kind == "cb" and x.rcept_dt == f.rcept_dt and not x.is_correction]
        amount = re.search(r"권면(?:\(전자등록\))?총액\s*\(?원?\)?\s*([\d,]+)", text)
        if not same_day or not amount:
            self.questions.append(f"자본인정 채무증권 짝 확인 불가: {f.rcept_no}")

    # ---- 신호 ----
    def unknown_signal(self, f, sig_type, i=0):
        eid = ev.dart_section(f.rcept_no, "list")
        self.evidence.append(Evidence(evidence_id=eid, source_grade="A", source_type="dart_list", corp_code=self.cc, published_at=f.rcept_dt, title=f.report_nm))
        code = "S4" if sig_type == SignalType.CONFIRMED else "S5"
        self.signals.append(Signal(signal_id=f"{self.cc}:{code}:{f.rcept_no}:{i}" if code == "S5" else f"{self.cc}:S4:{f.rcept_no}", corp_code=self.cc, signal_type=sig_type, event_date=f.rcept_dt, is_overseas=None, target_country=None, method=None, purpose_category="unknown", amount_krw=None, amount_original=None, stage=Stage.DECIDED, summary=f.report_nm_norm[:200], value_status="unknown", value_note=UNKNOWN_NOTE, evidence_ids=[eid]))
        self.questions.append(f"정정 전 원본 값 확인 불가: {f.report_nm_norm} {f.rcept_dt}")

    def signal_s4(self, f, src, form, *, is_overseas, purpose, country, method, summary, amount=None, ids=None, suffix=None):
        if ids is None:
            e = make_evidence(self.cc, src.rcept_no, src.rcept_dt, "정형:취득금액(원)", src.report_nm, form_quote(form), form.get("amount"))
            self.evidence.append(e)
            ids = [e.evidence_id]
        value = (form.get("amount") if amount is None else amount) if is_overseas else None
        prefix = "종속회사 공시: " if f.filer_scope == "subsidiary" and not summary.startswith("종속회사 집행") else ""
        self.signals.append(Signal(signal_id=f"{self.cc}:S4:{f.rcept_no}" + (f":{suffix}" if suffix else ""), corp_code=self.cc, signal_type=SignalType.CONFIRMED, event_date=f.rcept_dt, is_overseas=is_overseas, target_country=country, method=method, purpose_category=purpose, amount_krw=value, amount_original=None, stage=Stage.DECIDED, summary=(prefix + summary)[:200], evidence_ids=ids))

    def signal_s5(self, f, no, i, kind, *, is_overseas, purpose, amount, slots=None):
        eid = ev.dart_api(no, API[kind], "fdpp")
        quote = " / ".join(f"{s} {v:,}" for s, v in (slots or {}).items() if v) or None
        self.evidence.append(Evidence(evidence_id=eid, source_grade="A", source_type="dart_api", corp_code=self.cc, published_at=f.rcept_dt, title=f.report_nm, url=VIEWER_URL.format(rcept_no=no), quote=quote, meta={"slots": {k: v for k, v in (slots or {}).items() if v}, "value": amount}))
        self.signals.append(Signal(signal_id=f"{self.cc}:S5:{no}:{i}", corp_code=self.cc, signal_type=SignalType.FUNDING, event_date=f.rcept_dt, is_overseas=is_overseas, target_country=None, method=None, purpose_category=purpose, amount_krw=amount, amount_original=None, stage=Stage.DECIDED, summary=f.report_nm_norm[:200], evidence_ids=[eid]))

    # ---- 라벨 적용 ----
    def apply(self, labels: dict) -> dict:
        """labels: {evidence_id: 검증 통과 라벨}. 없으면 purpose unknown. 금액은 정형 칸 값만 쓴다."""
        kept = {}
        for x in self.entries:
            lab = labels.get(x["eid"])
            f, src = x["filing"], x["source"]
            if lab:
                kept[f.rcept_no] = lab.model_dump()
            purpose = lab.purpose_category if lab else "unknown"
            if x["kind"] == "acquisition":
                form = x["form"]
                country = canon_country(form["country"]) or (canon_country(lab.target_country) if lab else None)
                overseas = bool(form["country"]) or bool(lab and lab.is_overseas)
                amount, split = form["amount"], None
                if x.get("split") and overseas:
                    amount, split = self.split_signals(x, lab, country)
                else:
                    if overseas and "운영자금" in (form.get("purpose") or ""):      # 칸 분할 근거가 없어 전액이 투자액이다 (v0.21)
                        self.questions.append(f"목적에 운영자금 포함, 금액 구분 없음: {f.rcept_no}")
                    self.signal_s4(f, src, form, is_overseas=overseas, purpose=purpose, country=country, method=lab.method if lab else None, summary=f"{form['name']} 취득결정")
                if overseas and (amount or not split):      # 성장 투자 칸이 하나도 없으면 프로젝트 금액 항목을 만들지 않는다
                    self.items.append({"rcept_no": f.rcept_no, "latest_rcept_no": src.rcept_no, "rcept_dt": f.rcept_dt.isoformat(), "amount": amount, "split": split, "form_amount": form["amount"], "subsidiary_working_capital": sum(r["amount"] for r in split or [] if r["use"] == "운영자금"), "shares_acquired": form.get("shares_acquired"), "shares_after": form.get("shares_after"), "relation": form["relation"], "scheduled_date": form["scheduled"], "name": form["name"], "country": country, "board": form["board"], "corrections": x["corrections"], "part_of_earlier": lab.part_of_earlier if lab else "unknown"})
            elif x["kind"] == "funding":
                scopes = {s.slot: s.scope for s in lab.fund_use_scopes} if lab else {}
                amount, q = overseas_amount(x["slots"], {s: scopes.get(s, "unknown") for s in SLOTS}, {s: x["section"][:200] for s, v in scopes.items() if v == "mixed"})
                x["decision"]["overseas_amount"] = amount
                self.questions += q
                self.signal_s5(f, x["rcept_no"], x["index"], x["fund_kind"], is_overseas=(amount is not None) if lab else None, purpose=purpose, amount=amount, slots=x["slots"])
            elif x["kind"] in ("facility", "asset", "transfer"):
                overseas = lab.is_overseas if lab else None
                if not lab:      # 국적 칸이 없어 라벨 없이는 해외인지 알 수 없다
                    self.questions.append(f"국내·해외 라벨 없음: {f.report_nm_norm} {f.rcept_no}")
                    continue
                if not overseas and x["kind"] != "asset":      # 국내 시설·영업양수는 신호를 만들지 않는다. 라벨은 major_labels에 남는다 (12.2 G-DOM, G-NONE)
                    continue
                if x["kind"] == "asset" and f.filer_scope == "subsidiary":
                    if not (lab and lab.is_overseas and lab.quote):
                        self.questions.append(f"종속회사 유형자산 소재지 확인 불가: {f.rcept_no}")
                        continue
                    summary = f"종속회사 집행: {f.report_nm_norm}"
                else:
                    summary = f.report_nm_norm
                e = make_evidence(self.cc, src.rcept_no, src.rcept_dt, "정형", src.report_nm, f"금액 칸 {x['amount']} / {lab.quote}", x["amount"])
                self.evidence.append(e)
                self.signal_s4(f, src, {}, is_overseas=bool(overseas), purpose=purpose, country=canon_country(lab.target_country), method=lab.method, summary=summary, amount=x["amount"], ids=[e.evidence_id])
                if overseas:
                    self.items.append({"rcept_no": f.rcept_no, "latest_rcept_no": src.rcept_no, "rcept_dt": f.rcept_dt.isoformat(), "amount": x["amount"], "relation": "", "scheduled_date": None, "name": lab.target_entity, "country": canon_country(lab.target_country), "board": None, "corrections": x["corrections"], "part_of_earlier": lab.part_of_earlier, "execution": x["kind"] == "asset" and f.filer_scope == "subsidiary"})
            elif x["kind"] == "alert" and not lab:
                self.questions.append(f"변경 공시 라벨 없음: {f.rcept_no}")
            if x["kind"] == "alert" or x.get("also_alert"):
                self.alert_signal(src, x["eid"], lab)
        return kept


def pick_entries(entries: list[dict]) -> tuple[list[dict], list[str]]:
    """입력 상한 (7.5). 넘으면 최신순으로 자르고 open_question."""
    picked, total, dropped = [], 0, []
    for x in sorted(entries, key=lambda e: e["filing"].rcept_dt, reverse=True):
        if total + len(x["block"]) > CLASSIFY_BATCH_MAX_CHARS:
            dropped.append(f"분류 입력 상한 초과: {x['filing'].rcept_no}")
            continue
        picked.append(x)
        total += len(x["block"])
    return picked, dropped


def validate_labels(output: MajorEventBatchOutput, entries: list[dict]) -> tuple[dict, list[str]]:
    """evidence_id가 입력에 있고 quote가 그 자료에 있어야 라벨을 쓴다. 재호출하지 않는다."""
    by_id = {x["eid"]: x for x in entries}
    good, questions = {}, []
    for it in output.items:
        x = by_id.get(it.evidence_id)
        if x is None:
            questions.append(f"분류 결과 폐기(근거 없음): {it.evidence_id}")
        elif _ws(it.quote) not in _ws(x["text"]):
            questions.append(f"분류 결과 폐기(인용 불일치): {it.evidence_id}")
        else:
            good[it.evidence_id] = it
    for eid in by_id.keys() - good.keys():
        if not any(eid in q for q in questions):
            questions.append(f"분류 결과 누락: {eid}")
    return good, questions


@guarded
def parse_major_events(state) -> dict:
    """주요사항에서 S4·S5·S6을 만든다 (7.5). 규칙 R1~R5 뒤 남은 공시를 묶어 1회 분류한다. 금액은 정형 칸만, LLM은 라벨만."""
    req, company = state["request"], state["company"]
    b = Batch(state)
    no_llm = req.context.get("no_llm")
    for f in b.filings:
        if f.kind == "major_event" and not f.is_correction:
            if f.sub_kind in FUNDING:
                if f.filer_scope == "subsidiary":       # R1
                    b.deferred.append(f)
                else:
                    b.funding(f)
            elif f.sub_kind == "acquisition_stock":
                b.acquisition_ds005(f) if f.report_nm_norm and "주요사항보고서" in re.sub(r"\s", "", f.report_nm) else b.acquisition_exchange(f)
            else:
                b.needs_label(f)
        elif f.sub_kind == "hybrid_capital" and not f.is_correction:
            b.hybrid(f)
        elif not no_llm and (f.kind == "alert" or (f.kind == "major_event" and f.is_correction and "주요사항보고서" not in re.sub(r"\s", "", f.report_nm))):
            b.alert(f)      # R4: DS005 대상의 정정은 원공시 기준 최신본으로 이미 읽었다
    labels, llm = {}, state.get("llm_calls", 0)
    b.attach_subsidiary_funding()
    if b.entries and not no_llm:
        picked, dropped = pick_entries(b.entries)
        b.questions += dropped
        out = call_llm(PROMPT, {"corp_name": company.corp_name, "n": len(picked), "materials": "\n".join(x["block"] for x in picked)}, MajorEventBatchOutput, run_id=state["run_id"], as_of=req.as_of)
        labels, q = validate_labels(out, picked)
        b.questions += q
        llm += 1
    kept = b.apply(labels)
    targets = {_ws(x["name"]) for x in b.items if x.get("name")}
    split_done = {x["split"]["filing"].rcept_no for x in b.entries if x.get("split")}
    for f in b.deferred:
        if f.rcept_no in split_done:
            continue
        t = plain_text(b.client.document(f.rcept_no))
        name, debt = re.search(r"종속회사인\s*(.+?)\s*의\s*주요경영사항", t), subsidiary_uses(t).get("채무상환자금")
        if name and debt and _ws(name.group(1)) in targets:       # R1 예외 (v0.14)
            b.questions.append(f"종속회사 증자 채무상환 용도 {debt:,}: 자금 공백에 차입 상환 수요 포함 가능")
    return {"signals": b.signals, "s4_items": b.items, "funding_decisions": b.decisions, "evidence": b.evidence, "open_questions": b.questions, "major_labels": kept, "llm_calls": llm}
