"""2단계 둘째 묶음 초안 작성: data/probe/golden_batch1.json, golden_batch2.json → tests/golden/<agent>/*.json + tests/golden/_review_batch2.md

초안의 값은 코드가 읽은 값이다. 검수 결과는 _review_batch1_검수결과.md "둘째 묶음 검수" 절과 사용자 지시대로만 기록한다.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
G = ROOT / "stride/tests/golden"
B1 = json.loads((ROOT / "data/probe/golden_batch1.json").read_text(encoding="utf-8"))
B2 = json.loads((ROOT / "data/probe/golden_batch2.json").read_text(encoding="utf-8"))
S = json.loads((G / "_probe_samples.json").read_text(encoding="utf-8"))["samples"]
URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"
eok = lambda v: None if v is None else round(v / 1e8, 1)
num = lambda s: int(s.replace(",", ""))


def chk(rcept_no, where, *values):
    return {"rcept_no": rcept_no, "url": URL.format(rcept_no), "where": where, "values": list(values), "value_status": ["draft"] * len(values), "status": "draft"}


AI = "AI 검수(claude.ai)"
# check_list 순서대로. v = 값 전부 일치, a = API 응답 대조, d = 미검수, 목록 = 값별. 없는 파일은 전부 미검수
REVIEW = {
    "F-RESTRUCT_KOSPI": ["v", "v", "v", "v"],
    "F-IMPAIR50_KOSPI": ["v", "v", "v"],
    "F-IMPAIR50_KOSDAQ": ["v", "v", "v"],
    "F-FULLIMPAIR_KOSPI": ["v", "v", "v"],
    "F-FULLIMPAIR_KOSDAQ": ["v", "v", "v"],
    "F-KOSDAQ-EQ_KOSDAQ": ["v", "v", "v"],
    "F-NETCASH-NOEBITDA_A": ["v", "v", "v"],
    "F-NEGEBITDA_E": ["v", "v", "v", "v"],
    "F-QUARTER_F": [["a", "v", "v", "v"], "v"],
    "G-MIX_D": ["v", "v"],
}
docs = []


def case(agent, file, case_type, label, corp, request, expect, check, notes=()):
    status, by, at = "draft", None, None
    if file in REVIEW:
        assert len(REVIEW[file]) == len(check), file
        for c_, f in zip(check, REVIEW[file]):
            vs = [f] * len(c_["values"]) if isinstance(f, str) else f
            assert len(vs) == len(c_["values"]), (file, c_["where"])
            c_["value_status"] = ["ai_verified" if x in ("v", "a") else "draft" for x in vs]
            if "a" in vs:      # 원문에 없는 값: list.json·API 응답 대조를 검수로 인정 (2026-11-06 결정)
                c_["verification_method"] = ["api_response" if x == "a" else "document" for x in vs]
            c_["status"] = "ai_verified" if all(x == "v" for x in vs) else "draft"
        every = [x for c_ in check for x in c_["value_status"]]
        status = "ai_verified" if all(x == "ai_verified" for x in every) else "ai_verified_partial"
        by, at = AI, "2026-11-05"
    if file == "F-NOMARKET_F":      # 확인할 공시가 없어 값의 근거인 F-NORMAL_F 상태를 따른다 (2026-11-06 결정)
        status, by, at = json.loads((G / "financial_health/F-NORMAL_F.json").read_text(encoding="utf-8"))["status"], "F-NORMAL_F 상태를 따름", "2026-11-06"
    doc = {"case_type": case_type, "sample": label, **corp, "status": status, "request": request, "verified_by": by, "verified_at": at,
           "human_verified": {"verified": False, "by": None, "at": None}, "expect": expect, "check_list": check, "open_notes": list(notes)}
    (G / agent / f"{file}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    docs.append(doc)


def sample_corp(label):
    return {"corp_code": S[label]["corp_code"], "corp_name": S[label]["corp_name"]}


# ---- 상장 규정 입력 유형 ----
for t, suffix_list, rule in (("F-IMPAIR50", ("KOSPI", "KOSDAQ"), "R3 입력"), ("F-FULLIMPAIR", ("KOSPI", "KOSDAQ"), "자본잠식률 ≥ 100"), ("F-KOSDAQ-EQ", ("KOSDAQ",), "R3-KQ 입력")):
    for x, m in zip(B2[t], suffix_list):
        sig = next(iter(x["signals"].values()))
        notes = []
        if len(x["filings"]) > 1:
            notes.append(f"보고서 정정이 있어 as_of를 마지막 정정 다음 날({x['as_of']})로 둠. 원본 접수 직후 as_of는 7장 규칙상 unknown이 된다")
        if t == "F-KOSDAQ-EQ":
            notes.append("스캔 대상 중 자기자본 0~10억 코스닥 1곳뿐. 과거 사업연도라 as_of도 과거. 자본잠식률도 50% 이상이라 F-IMPAIR50 조건과 겹침")
        if t == "F-FULLIMPAIR":
            notes.append("자기자본 ≤ 0. 부채비율은 자본총계 ≤ 0이라 None")
        notes.append("거래소 내부결산 공시 수치는 감사 전 값이라 기대값에 쓰지 않는다. 기대값은 사업보고서(감사 후) 값")
        extra = {"00303192": "지배지분 기준 잠식률 54.08%. 자본총계(-20,771,452,028, 비지배지분이 큰 음수) 기준이면 전액잠식. fin.equity_ex_nci 정의상 54.08%가 기대값",
                 "00125974": "정정 전 의견거절(계속기업 불확실성) → 정정 후 2025년 재감사 적정의견. as_of는 정정 다음 날. 정정 전 시점 as_of(2026-04-08) 케이스를 정정 규칙 시험용으로 추가할지 제안 중",
                 "01182550": "거래소 내부결산 자본총계 -17,885,319,546 ≠ 감사 후 -22,525,441,423. 보고서 당시 상호 이원다이애그노믹스",
                 "01031229": "거래소 내부결산 자본총계 636,889,882, 자본금 2,520,298,500 ≠ 감사 후 값. 보고서 당시 상호 지티지웰니스",
                 "00122825": "보고서 당시 상호 인스코비"}
        if x["corp_code"] in extra:
            notes.append(extra[x["corp_code"]])
        docs_expect = {"market": x["market"], "bsns_year": x["fy"], "fs_basis": x["fs"], "fs_rcept_no": x["fs_rcept_no"], "capital_stock_krw": x["capital"], "fin.equity_ex_nci_krw": x["equity_ex_nci"],
                       "fin.capital_impairment_ratio_pct": x["impair"], "total_equity_krw": x["equity_total"], "fin.audit_opinion": x["audit"], "rule_input": rule, "must_not_have_after": x["as_of"]}
        case("financial_health", f"{t}_{m}", t, f"{m} 후보", {"corp_code": x["corp_code"], "corp_name": x["corp_name"]}, {"mode": "single", "company": x["corp_code"], "as_of": x["as_of"]}, docs_expect, [
            chk(x["fs_rcept_no"], f"{x['fy']} 사업보고서 연결 재무상태표", f"자본금 {x['capital']:,}", f"지배기업 소유주지분 {x['equity_ex_nci']:,}", f"자본총계 {x['equity_total']:,}", f"자본잠식률 {x['impair']}% = (자본금 − 자기자본) / 자본금"),
            chk(x["fs_rcept_no"], "회계감사인의 명칭 및 감사의견", f"당기 감사의견 {', '.join(x['audit'])}"),
            chk(sig[2], "거래소 공시 (후보 탐색 근거)", f"{sig[1][:40]}, 접수 {sig[0]}", "재무상태표 값과 내용이 맞는지"),
        ], notes)

# ---- F-RESTRUCT ----
x = B2["F-RESTRUCT"]
case("financial_health", "F-RESTRUCT_KOSPI", "F-RESTRUCT", "KOSPI 후보", {"corp_code": x["corp_code"], "corp_name": x["corp_name"]}, {"mode": "single", "company": x["corp_code"], "as_of": "2026-07-01"}, {
    "fin.restructuring_status": "회생절차", "note": None,
    "events": [{"rcept_no": "20260615000002", "report_nm_norm": "회생절차개시신청", "kind": "회생절차"}, {"rcept_no": "20260630800563", "report_nm_norm": "회생절차개시결정", "kind": "회생절차"}],
    "corrected_same_event": ["20260616000222"], "excluded_subsidiary": ["20260615800033", "20260616800652", "20260630800581"], "must_not_have_after": "2026-07-01",
}, [
    chk("20260615000002", "회생절차 개시신청", "신청인이 이 회사 자신", "서울회생법원, 신청일 2026-06-14"),
    chk("20260616000222", "같은 건 정정", "정정사항이 재산보전처분·포괄적금지명령 결정 내용뿐인지"),
    chk("20260630800563", "회생절차개시결정", "결정일 2026-06-30, 사건번호 2026회합1104"),
    chk("20260615800033", "종속회사 회생절차개시신청 (제외 대상)", "다른 법인의 신청인지"),
], ["9.3 패턴은 정규화 이름 완전 일치. 정정은 같은 사건 1건으로 본다", "2026-11-05까지 종결·폐지 공시 없음 (2024-07 이후 목록 확인)"])

# ---- F-NETCASH-NOEBITDA (A) ----
x = B2["F-NETCASH-NOEBITDA"]
case("financial_health", "F-NETCASH-NOEBITDA_A", "F-NETCASH-NOEBITDA", "A", sample_corp("A"), {"mode": "single", "company": S["A"]["corp_code"], "as_of": "2026-11-05"}, {
    "period": "2025FY", "fs_rcept_no": x["fs_rcept_no"], "total_borrowings_krw": x["total_borrowings"], "cash_krw": x["cash"], "short_term_krw": x["st"], "fin.net_debt_krw": x["net_debt"], "net_debt_sign": "negative",
    "fin.ebitda": "missing", "ebitda_note": "상각비 출처 불일치", "fin.net_debt_to_ebitda": "missing", "fin.ebitda_margin": "missing", "fin.ebitda_interest_coverage": "missing", "interest_note": f"이자비용 확인 불가: {x['interest_why']}", "interest_missing_test": True,
}, [
    chk(x["fs_rcept_no"], "2025 사업보고서 정정본 재무상태표", f"현금 {x['cash']:,}", f"단기금융상품 {x['st']:,}", f"총차입금 {x['total_borrowings']:,} (리스부채 포함)"),
    chk(x["fs_rcept_no"], "비용의 성격별 분류 / 영업에서 창출된 현금", "N 감가+무형 합산 3,597.3억", "C 감가 3,573.0억, 무형 2,651.1억, 사용권 112.3억", "두 출처가 정말 다른지"),
    chk(x["fs_rcept_no"], "금융원가 표 / 현금흐름 조정 표", "이자비용(금융원가) 291.7억", "이자비용에 대한 조정 377.0억", "두 값의 차이"),
], ["순차입금은 음수지만 EBITDA missing이라 순차입금/EBITDA는 missing이어야 한다. 0·음수로 채우면 실패"])

# ---- F-NEGEBITDA (E) ----
x = B2["F-NEGEBITDA"]
margin = round(x["ebitda"] / x["revenue"] * 100, 2)
cov = round(x["ebitda"] / x["note_interest"], 2)
case("financial_health", "F-NEGEBITDA_E", "F-NEGEBITDA", "E", sample_corp("E"), {"mode": "single", "company": S["E"]["corp_code"], "as_of": "2026-11-05"}, {
    "period": "2025FY", "fs_rcept_no": x["fs_rcept_no"], "operating_income_krw": x["oi"], "depreciation_krw": x["dep"], "amortization_krw": x["amort"], "depreciation_source": "연결감사보고서 첨부 현금흐름표와 성격별 분류 합계 대조", "fin.ebitda_krw": x["ebitda"],
    "fin.net_debt_krw": x["net_debt"], "fin.net_debt_to_ebitda": None, "net_debt_to_ebitda_note": "EBITDA ≤ 0으로 계산 안 함", "fin.ebitda_margin_pct": margin, "interest_expense_krw": x["note_interest"], "interest_source": "금융원가 주석 (금융비용 표 + 첨부 현금흐름표 조정 행 일치)", "fin.ebitda_interest_coverage": cov, "coverage_note": "EBITDA 음수",
}, [
    chk(x["fs_rcept_no"], "2025 사업보고서 손익계산서", f"영업손실 {x['oi']:,}", f"매출액 {x['revenue']:,}"),
    chk(x["fs_rcept_no"], "비용의 성격별 분류 / 연결감사보고서 첨부 현금흐름표", f"감가상각비와 무형자산상각비 합산 {x['N']['combined']:,}", f"감가상각비(사용권 포함) {x['dep']:,}", f"무형자산상각비 {x['amort']:,}"),
    chk(x["fs_rcept_no"], "재무상태표·리스 주석", f"현금 {x['cash']:,}", f"단기금융상품 {x['st']:,}", f"총차입금 {x['total_borrowings']:,} (리스 주석 값 포함)"),
    chk(x["fs_rcept_no"], "금융비용 표 / 연결감사보고서 첨부 현금흐름표", f"이자비용 {x['note_interest']:,}", "두 표의 값이 같은지 (별도 감사보고서 값이 아닌지)"),
], ["AI 검수로 기대값 변경: 이자비용 missing → 21.4억 채택. 값은 본문이 아니라 연결감사보고서 쪽에서 두 표로 확인된다", "이자비용 missing 시험은 F-NETCASH-NOEBITDA(표끼리 값 다름)로 옮겼다", "EBITDA 음수라 EBITDA/이자비용도 음수. 값 그대로 + note \"EBITDA 음수\" (재무 3.2)"])

# ---- F-QUARTER, F-NOMARKET (F) ----
h = B1["G-RICH"]["h1_2026"]
y25 = B1["F-NORMAL"]["2025"]
case("financial_health", "F-QUARTER_F", "F-QUARTER", "F", sample_corp("F"), {"mode": "single", "company": S["F"]["corp_code"], "as_of": "2026-08-15"}, {
    "latest_report": {"rcept_no": h["rcept_no"], "period": "2026H1"}, "annual_report": {"rcept_no": y25["fs_rcept_no"], "period": "2025FY"},
    "latest_basis": {"cash_krw": h["cash"], "short_term_krw": h["st"], "fin.ttm_operating_cash_flow_krw": h["ttm"], "fin.total_borrowings_krw": h["total_borrowings"], "fin.net_debt_krw": h["net_debt"], "fin.debt_ratio_pct": h["debt_ratio"], "period": "2026H1말"},
    "annual_basis": {"fin.ebitda_krw": y25["ebitda"], "fin.net_debt_krw": y25["net_debt"], "fin.net_debt_to_ebitda": y25["nd_ebitda"], "fin.ebitda_interest_coverage": y25["coverage"], "fin.ebitda_margin_pct": y25["margin"], "fin.ttm_operating_cash_flow_2025FY_krw": y25["ocf"]},
    "must_not_have_after": "2026-08-15",
}, [
    chk(h["rcept_no"], "2026 반기보고서", f"접수 2026-08-14 (as_of 하루 전)", f"현금 {h['cash']:,}, 단기금융상품 {h['st']:,}", f"총차입금 {h['total_borrowings']:,}", f"반기 누적 영업현금흐름 {h['cum']:,}, 전년 동기 {h['prev_same']:,}"),
    chk(y25["fs_rcept_no"], "2025 사업보고서 정정본", f"연간 영업현금흐름 {y25['ocf']:,}", f"TTM {h['ttm']:,} = 누적 + 연간 − 전년 동기"),
], ["재무 기본 항목·순차입금은 반기 기준, 핵심 지표는 2025 사업보고서 기준"])
case("financial_health", "F-NOMARKET_F", "F-NOMARKET", "F", sample_corp("F"), {"mode": "single", "company": S["F"]["corp_code"], "as_of": "2026-11-05", "env": "시장 데이터 키를 비운 상태로 실행"}, {
    "fin.market_data_source": "missing", "missing_metrics": ["fin.market_cap", "fin.net_debt_to_ev", "fin.per", "fin.pbr", "fin.ev_to_ebitda"], "result_status": "complete",
    "other_metrics_same_as": "F-NORMAL_F 2025FY", "fin.net_debt_to_ebitda_2025FY": y25["nd_ebitda"], "fin.ebitda_interest_coverage_2025FY": y25["coverage"], "fin.ebitda_margin_pct_2025FY": y25["margin"],
}, [], ["확인할 공시 없음. 원문 값은 F-NORMAL_F 검수를 따른다"])

# ---- G-MIX (D) ----
t = B1["G-TRACK"]
cb = t["cb_2026"][0]
rights = t["funding_2025"][1]
case("overseas_funding", "G-MIX_D", "G-MIX", "D", sample_corp("D"), {"mode": "single", "company": S["D"]["corp_code"], "as_of": "2026-08-22"}, {
    "must_have_signals": [
        {"signal_type": "S5_funding", "rcept_no": rights["rcept_no"], "fund_use_scopes": {"fdpp_ocsa": "overseas", "fdpp_fclt": "unknown"}, "overseas_amount_krw": num(rights["fdpp_ocsa"]), "open_question": f"해외 용도 불명 칸: fdpp_fclt {num(rights['fdpp_fclt']):,}"},
        {"signal_type": "S5_funding", "rcept_no": cb["rcept_no"], "fund_use_scopes": {"fdpp_ocsa": "overseas", "fdpp_op": "unknown"}, "overseas_amount_krw": num(cb["fdpp_ocsa"]), "open_question": f"해외 용도 불명 칸: fdpp_op {num(cb['fdpp_op']):,}"},
    ],
    "reference_domestic_slot": {"case": "G-RICH_F", "rcept_no": "20260629000433", "fund_use_scopes": {"fdpp_fclt": "domestic", "fdpp_etc": "unknown"}, "s5_amount_krw": None},
    "must_not_have_after": "2026-08-22",
}, [
    chk(rights["rcept_no"], "2025 유상증자 결정 【조달자금의 구체적 사용 목적】", "시설 30억 세부 'ESS 생산설비 구축', 소재지 표기 없음", "타법인 120억 대상 Hanjung America Co."),
    chk(cb["rcept_no"], "2026 CB 결정 정정본 【조달자금의 구체적 사용 목적】", "운영 200억 '생산물량 대응을 위한 운영자금', 국내·해외 표기 없음", "타법인 600억 '미국 에너지저장장치 제조시설 구축'"),
], ["부분 후보. 이 두 공시는 해외 칸 + 불명 칸이고, 국내와 해외가 모두 명시된 공시가 아니다. 칸 단위 분리와 open_question은 시험하지만 G-MIX 본래 조건은 후보 탐색이 더 필요", "라벨 기대값은 scripts/probe_excerpt_label.py 수정 발췌 결과와 AI 추가 검수가 같다"])

# ---- 검토표 ----
lines = ["# 2단계 둘째 묶음 검토표\n", "값은 코드가 읽은 값이다. [x]는 AI 검수 일치(사람 확인 아님), [ ]는 미검수다. 상호는 list.json 현재 값이라 보고서 당시 상호와 다를 수 있다. 상세는 `_review_batch1_검수결과.md`.\n"]
for d in docs:
    lines.append(f"\n## {d['case_type']} — {d['corp_name']} ({d['sample']}) — {d['status']}\n- as_of: {d['request'].get('as_of')}\n")
    for c in d["check_list"]:
        lines.append(f"- [{c['where']}]({c['url']})\n" + "".join(f"  - [{'x' if s == 'ai_verified' else ' '}] {v}{' (API 응답 대조)' if m == 'api_response' else ''}\n" for v, s, m in zip(c["values"], c["value_status"], c.get("verification_method", [None] * len(c["values"])))))
    if d["open_notes"]:
        lines.append("- 참고\n" + "".join(f"  - {n}\n" for n in d["open_notes"]))
(G / "_review_batch2.md").write_text("".join(lines), encoding="utf-8")
print("초안", len(docs), [d["case_type"] + "/" + d["sample"] for d in docs])
