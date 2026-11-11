"""페이지 3 — 기업 상세 / 사전검토서 (화면_데이터_연결명세 4장)."""
import pandas as pd
import streamlit as st

from core import catalog
from orchestrator import common
from orchestrator.config import STAGE_LABELS
from orchestrator.review import TITLES
from ui import charts, jobs, nav, queries, texts, trace_view
from ui import format as f

as_of = st.session_state["as_of"].isoformat()
names = queries.company_names()
cc = st.session_state.get("company")
q = st.session_state.pop("company_query", None)
if q:      # 질의창 '기업 검토'
    st.session_state["review_job"] = jobs.enqueue("review", {"company": q, "as_of": as_of})
if not cc and not st.session_state.get("review_job"):
    pick = st.selectbox("기업", [""] + sorted(names, key=lambda c: names[c]), format_func=lambda c: names.get(c, "기업 선택"))
    if not pick:
        st.info("기업 발굴 표나 관심 기업에서 기업을 고르거나, 상단 질의창에 'OO 검토해줘'를 입력하세요.")
        st.stop()
    cc = st.session_state["company"] = pick

job_id = st.session_state.get("review_job")
if job_id:
    job = queries.get_job(job_id)
    if job and job["status"] in ("queued", "running"):
        st.info("검토서를 만드는 중입니다 · 자동으로 갱신돼요 (보통 1~2분).")
        nav.poll()
    st.session_state.pop("review_job")
    if job and job["status"] == "done" and (job["result_ref"] or "").startswith("rep_"):
        import json
        from orchestrator import store
        con = store.connect(queries.DB_PATH)
        cc = st.session_state["company"] = con.execute("SELECT corp_code FROM orc_reports WHERE report_id=?", (job["result_ref"],)).fetchone()[0]
        con.close()
    elif job and job["status"] == "done":
        st.warning(json.loads(job["result_ref"]).get("clarification") if (job["result_ref"] or "").startswith("{") else "기업을 특정하지 못했습니다.")
        st.stop()
    elif job:
        st.error("검토서 생성 실패: " + (job["error"] or "").splitlines()[0])

rep = queries.get_report(cc, as_of)
ovs, ver, day = queries.latest_result(cc, "overseas_funding", as_of)
fin, _, _ = queries.latest_result(cc, "financial_health", as_of)
info = {"corp_name": names.get(cc, cc)}
if not rep:
    st.subheader(info["corp_name"])
    st.info(f"이 기준일({as_of}) 검토서가 없습니다.")
    if st.button("검토서 만들기"):
        st.session_state["review_job"] = jobs.enqueue("review", {"corp_code": cc, "as_of": as_of})
        st.rerun()
    if not ovs:
        st.stop()
report = rep["report"] if rep else None
head = st.columns([5, 1, 1])
head[0].subheader(f"{ovs.corp_name if ovs else info['corp_name']} · 기업 상세")
watched = cc in {w["corp_code"] for w in queries.get_watchlist_rows(as_of)}
if head[1].button("★ 관심 기업" if watched else "☆ 관심 기업"):
    jobs.toggle_watch(cc, ovs.corp_name if ovs else info["corp_name"], not watched, "company")
    st.rerun()
if report:
    md = "\n\n".join(f"## {TITLES[k]}\n\n{v}" for k, v in report["sections"].items())
    head[2].download_button("검토서 내보내기", md, file_name=f"{cc}_{as_of}_사전검토서.md")
st.caption(f"기준일 {as_of}" + (f" · 분석 결과 기준일 {day}" if day and day != as_of else "") + (" · 부분 검토서" if report and report["is_partial"] else ""))

# 카드 A→B→C→D (2026-11-10 방향 수정 3번). 모든 값에 기준일·계산식·출처 공시
def table(items):
    """[(이름, Metric|None, 단위)] → 항목·값·기준일·계산식·출처 표."""
    out = []
    for label, m, unit in items:
        d = common.mdict(m)
        c_ = catalog.load().get(m.metric_id, {}) if m else {}
        out.append({"항목": label, "값": ("🔎 " if (d.get("note") or "").startswith(("에이전트 탐색", "빈 금액 행을 에이전트", "이자비용을 에이전트")) else "") + f.value(d, unit) + (f" ({d['note']})" if d.get("note") else ""), "기준일": f.period_label(d.get("period")) or "-",
                    "계산식": (c_.get("formula") or "").strip()[:160] or "-", "출처": f.source(d.get("evidence_ids")) or "STRIDE 계산" if m else "-"})
    st.dataframe(pd.DataFrame(out), hide_index=True, use_container_width=True, column_config={"출처": st.column_config.LinkColumn("출처", display_text=r"rcpNo=(\d+)")})


M = lambda r, k, **kw: common.metric(r, k, **kw)
inv, gap, ratio, conf, unc = (M(ovs, k) for k in ("ovs.overseas_investment_amount", "ovs.funding_gap", "ovs.funding_gap_ratio", "ovs.confirmed_overseas_funding", "ovs.unconfirmed_overseas_funding"))
ttm = M(fin, "fin.ttm_operating_cash_flow")
p = common.main_project(ovs)

st.markdown("#### A. 해외 진출 신호")
c = st.columns(3)
c[0].metric("대표 프로젝트", f"{p['target_country'] or '-'} · {texts.METHOD_LABELS.get(p.get('method'), p.get('method') or '-')}" if p else "없음")
c[1].metric("진행 단계", f"{p['stage']} · {STAGE_LABELS.get(p['stage'], '')}" if p else "-")
c[2].metric("해외 투자액", f.value(common.mdict(inv)), help=f.period_label(inv.period) if inv else None)
sig = queries.get_project_history(ovs, p["project_key"] if p else None)
ev_grade = {e.evidence_id: e.source_grade for e in (ovs.evidence if ovs else [])}
st.dataframe(pd.DataFrame([{"날짜": s["event_date"], "신호": texts.SIGNAL_LABELS.get(s["signal_type"], s["signal_type"]), "내용": s["summary"],
                            "출처 등급": "/".join(sorted({ev_grade.get(i, "-") for i in s["evidence_ids"]})) + (" (보도)" if all(ev_grade.get(i) == "C" for i in s["evidence_ids"]) and s["evidence_ids"] else ""),
                            "출처": f.source(s["evidence_ids"])} for s in sig]) if sig else pd.DataFrame([{"날짜": "-", "신호": "대표 프로젝트 신호 없음"}]),
             hide_index=True, use_container_width=True, column_config={"출처": st.column_config.LinkColumn("출처", display_text=r"rcpNo=(\d+)")})
st.caption("S4 취득·투자 결정 공시, S5 해외 용도 조달 공시, S6 정정·철회 공시가 주 신호이고 S1 정기보고서 계획·S2 보도는 보조 신호입니다. 출처 등급 A 공시, C 언론 보도.")

st.markdown("#### B. 유동성 원천·소요")
lq = {k: M(ovs, mid) for k, mid in common.LIQUIDITY_KEYS.items()}
c = st.columns(3)
c[0].metric("원천 ÷ 소요", f.value(common.mdict(lq["ratio"]), "배"), help=texts.LIQUIDITY_NOTE)
c[1].metric("원천 − 소요", f.value(common.mdict(lq["surplus"])))
fs = common.funding_status(ovs)
c[2].metric("해외 용도 조달", fs["label"], help=f"결과 공시 전 {f.eok(fs['unconfirmed'])} (원천에 넣지 않음) · 납입 확정 {f.eok(fs['confirmed'])}")
if lq["ratio"] and lq["ratio"].note:
    st.caption(lq["ratio"].note)
val = lambda m: m.value if m and m.data_status == "ok" else None
src_items = [("현금및현금성자산", val(lq["cash"])), ("단기금융상품", val(lq["short_term"])), ("TTM 영업현금흐름", val(lq["ttm_ocf"])), ("확정 해외 조달", val(lq["confirmed_funding"]))]
use_items = [("24개월 내 해외 투자", val(lq["investment_24m"])), ("1년 내 만기 차입금", val(lq["maturing_debt"])), ("직전 사업연도 배당금", val(lq["dividends"]))]
st.plotly_chart(charts.liquidity_bars(src_items, use_items), use_container_width=True)
table([("원천: 현금및현금성자산", lq["cash"], "원"), ("원천: 단기금융상품", lq["short_term"], "원"), ("원천: TTM 영업현금흐름", lq["ttm_ocf"], "원"), ("원천: 확정 해외 조달", lq["confirmed_funding"], "원"), ("원천 합계", lq["sources"], "원"),
       ("소요: 24개월 내 해외 투자액", lq["investment_24m"], "원"), ("소요: 1년 내 만기 차입금", lq["maturing_debt"], "원"), ("소요: 직전 사업연도 배당금", lq["dividends"], "원"), ("소요 합계", lq["uses"], "원"),
       ("참고: 24개월 밖 해외 투자액 (소요 제외)", lq["investment_beyond_24m"], "원"), ("참고: 결과 공시 전 해외 조달 (원천 제외)", unc, "원")])

st.markdown("#### C. 차입 여력 (한국기업평가 정의)")
table([("부채비율", M(fin, "fin.debt_ratio"), "%"), ("순차입금/EBITDA", M(fin, "fin.net_debt_to_ebitda", prefer="annual"), "배"), ("EBITDA/이자비용", M(fin, "fin.ebitda_interest_coverage", prefer="annual"), "배")])

st.markdown("#### D. 재무 위험 (한국거래소 공시가이드 2026.2.2)")
au, rs = common.cls(fin, "fin.audit_opinion"), common.cls(fin, "fin.restructuring_status")
table([("자본잠식률", M(fin, "fin.capital_impairment_ratio"), "%"), ("자기자본 (지배기업 소유주지분)", M(fin, "fin.equity_ex_nci"), "원")])
rules = [r for r in (report["rule_results"] if report else []) if r["rule_id"] != "R5"]
trading = (ovs.extra.get("trading_status_warnings") or []) if ovs else []
st.dataframe(pd.DataFrame([{"항목": "감사의견", "값": au.value if au else "산출 불가", "출처": f.source(au.evidence_ids) if au else None},
                           {"항목": "회생·워크아웃 관련 공시", "값": rs.value if rs else "산출 불가", "출처": f.source(rs.evidence_ids) if rs else None},
                           {"항목": "거래 상태 경고", "값": ", ".join(f"{common.TRADING_LABELS.get(w['type'], w['type'])} {w['since']}~ ({w['report_nm']})" for w in trading) or "없음", "출처": f.source([f"DART:{w['rcept_no']}:목록" for w in trading])},
                           {"항목": "상장 규정 기준 해당", "값": ", ".join(r["label"] for r in rules if r["hit"]) or (f"확인 불가 {sum(r['hit'] is None for r in rules)}건" if any(r["hit"] is None for r in rules) else "해당 없음" if rules else "검토서 없음"), "출처": None}]),
             hide_index=True, use_container_width=True, column_config={"출처": st.column_config.LinkColumn("출처", display_text=r"rcpNo=(\d+)")})
st.info(texts.FOOTER)
fills = [x for r in (ovs, fin) if r for x in (r.extra.get("agent_fills") or [])]
traces = queries.get_traces(cc, as_of)
with st.expander(f"조사 과정 · 에이전트 탐색 {len(traces)}건" + (f" · 자동으로 채운 값 {len(fills)}개" if fills else ""), expanded=bool(fills)):
    st.caption("에이전트는 어디를 더 찾아볼지만 정합니다. 숫자는 채택 게이트가 같은 공시의 같은 표·행을 다시 읽어 일치할 때만 쓰고, 단계·경보는 규칙으로 정합니다.")
    for x in fills:
        st.markdown(f"🔎 **{x['metric_id']}** = {f.eok(x['value'])} — 에이전트 탐색으로 확보 · {x['table']} · {x['row']} · [원문]({f.evidence_link('DART:' + x['rcept_no'] + ':x')}) · {x['gate']}")
    for tr in traces:
        trace_view.show(tr)
    if not traces:
        st.caption("이 기업은 에이전트 탐색 기록이 없습니다 (빈 지표가 없었거나 탐색 전 결과).")
st.caption("진행 단계: " + " → ".join(f"{k} {v}" for k, v in STAGE_LABELS.items()))

tabs = st.tabs(["요약", "해외 프로젝트", "자금 공백 (검토서)", "재무 건전성", "상장 규정·확인 필요", "검토 의견", "근거 목록"])
sec = report["sections"] if report else {}
with tabs[0]:
    st.markdown(sec.get("summary", "검토서 없음"))
with tabs[1]:
    st.markdown(sec.get("project", ""))
    st.markdown("**해외 프로젝트 진행 이력**")
    for s in queries.get_project_history(ovs, p["project_key"] if p else None):
        red = "🔴 " if s["signal_type"] == "S6_alert" else ""
        st.markdown(f"- {red}{s['event_date']} · {s['summary']} → {s['stage']}단계 · {STAGE_LABELS.get(s['stage'], '')} " + " ".join(f"[원문]({f.evidence_link(i)})" for i in s["evidence_ids"][:1] if f.evidence_link(i)))
with tabs[2]:
    st.markdown(sec.get("funding_gap", ""))
    st.caption(f"자금 공백(참고, 지표 ID 유지): {f.value(common.mdict(gap))} · 투자액 대비 {f.pct(ratio.value if ratio else None)}. 화면 판단 지표는 위 B 유동성 원천·소요입니다.")
with tabs[3]:
    st.markdown(sec.get("financial", ""))
    # 4.1 대표 차트: 같은 최신 정기보고서 기준. 순차입금 note가 '최신 보고서 리스부채 미공시'면 두 값 모두 사업연도말
    nd_latest = common.metric(fin, "fin.net_debt")
    switch = bool(nd_latest and "리스부채 미공시" in (nd_latest.note or ""))
    if switch:
        ttm_c, nd_c = common.metric(fin, "fin.ttm_operating_cash_flow", prefer="annual"), common.metric(fin, "fin.net_debt", prefer="annual")
    else:
        ttm_c, nd_c = ttm, nd_latest
    st.plotly_chart(charts.fin_bars([("영업현금흐름(TTM)", common.mdict(ttm_c) if ttm_c else None, f.period_label(ttm_c.period) if ttm_c else ""), ("순차입금", common.mdict(nd_c) if nd_c else None, f.period_label(nd_c.period) if nd_c else "")]), use_container_width=True)
    if switch:
        st.caption(f"최신 보고서({f.period_label(nd_latest.period)}) 리스부채 미공시로 사업연도말 기준 표시")
    elif ttm_c and nd_c and ttm_c.period.replace("TTM ", "").replace("말", "") != nd_c.period.replace("말", ""):
        st.caption("두 값의 근거 보고서가 다릅니다.")
    if nd_c:
        st.caption("순차입금 산식: " + nd_c.methodology)
    eb = common.metric(fin, "fin.ebitda", prefer="annual")
    if eb and eb.data_status == "ok":
        st.markdown("**보조: EBITDA (산출 기업만)**")
        ebs = [m for m in fin.metrics if m.metric_id in ("fin.ebitda", "fin.net_debt_to_ebitda", "fin.ebitda_margin") and m.period.endswith("FY")]
        st.dataframe(pd.DataFrame([{"지표": m.name, "기간": f.period_label(m.period), "값": f.value(common.mdict(m), m.unit), "산식": m.methodology[:80], "비고": m.note or ""} for m in ebs]), hide_index=True)
    table = [m for m in fin.metrics if m.metric_id in ("fin.debt_ratio", "fin.current_ratio", "fin.borrowing_dependency", "fin.capital_impairment_ratio", "fin.ebitda")] if fin else []
    st.dataframe(pd.DataFrame([{"지표": m.name, "기간": f.period_label(m.period), "값": f.value(common.mdict(m), m.unit), "비고": f.tooltip(common.mdict(m))} for m in table]), hide_index=True)
    au = common.cls(fin, "fin.audit_opinion")
    st.caption(f"감사의견: {au.value if au else '산출 불가'}")
with tabs[4]:
    st.markdown(sec.get("rules", ""))
    if report:
        st.dataframe(pd.DataFrame([{"규칙": r["rule_id"], "시장": r["market"], "결과": r["label"], "출처": f"{r['source']} ({r['source_date']})"} for r in report["rule_results"]]), hide_index=True)
        st.markdown(sec.get("verification", ""))
        st.markdown("**실사 확인 목록**")
        for x in report["due_diligence"]:
            st.markdown(f"- {x}")
with tabs[5]:
    st.markdown(sec.get("opinion", ""))
with tabs[6]:
    st.markdown(sec.get("appendix", ""))
    if report and report["evidence"]:
        ev = {e["evidence_id"]: e for e in report["evidence"]}
        pick = st.selectbox("근거 미리보기", list(ev), format_func=lambda i: f"{ev[i]['title']} ({ev[i]['published_at']})")
        e = ev[pick]
        st.markdown(f"**{e['title']}** (접수 {e['published_at']})  \n{e.get('quote') or ''}")
        link = e.get("url") or f.evidence_link(pick)
        if link:
            st.markdown(f"[원문 열기 ↗]({link})")
