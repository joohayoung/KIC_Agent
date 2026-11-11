"""페이지 2 — 관심 기업 추적 (첫 화면, 화면_데이터_연결명세 3장)."""
import streamlit as st

from orchestrator.config import MONITOR_TIMES, STAGE_LABELS
from ui import charts, jobs, nav, queries, texts, trace_view
from ui import format as f

as_of = st.session_state["as_of"].isoformat()
u = queries.last_update()
st.header("관심 기업 추적")
st.caption(f"마지막 업데이트 {u['updated_at'] or '-'}" + (f" · 공시 {u['polled']}건 확인" if u.get("polled") is not None else "") + f" · 업데이트 시각 {', '.join(MONITOR_TIMES)}")
st.write("저장한 조건과 관심 기업을 매일 2회 새 공시로 다시 확인합니다.")

# 3.2 추적 중인 조건
st.subheader("추적 중인 조건")
searches = queries.tracked_searches()
for s in [x for x in searches if x["tracking"]]:
    with st.container(border=True):
        c1, c2 = st.columns([5, 1])
        c1.markdown(f"**{s['name']}**" + (" · 기본" if s["is_system"] else ""))
        on = c2.toggle("추적", value=True, key=f"trk_{s['search_id']}")
        if not on:
            jobs.set_tracking(s["search_id"], False)
            st.rerun()
        crit = s["criteria"]
        st.caption(" · ".join(f"{texts.CRITERIA_LABELS.get(k, k)}: {v}" for k, v in crit.items() if v not in (None, [], "") and k in ("markets", "target_regions", "investment_types", "stages", "min_funding_gap_ratio", "exclude_rule_ids")))
        st.write(f"현재 {s['matched_count']}개 기업")
        for item in s["feed"][:5]:
            st.markdown(f"- {'새로 맞음' if item['kind'] == 'new_match' else '빠짐'} · {queries.company_names().get(item['corp_code'], item['corp_code'])} {f.mmdd(item['event_date'])} · {item['reason']}")
        if st.button("목록 보기", key=f"go_{s['search_id']}"):
            nav.go("discover", search_id=s["search_id"])
off = [x for x in searches if not x["tracking"]]
if off:
    st.caption("추적 꺼짐: " + ", ".join(x["name"] for x in off))
    for x in off:
        if st.button(f"{x['name']} 켜기", key=f"on_{x['search_id']}"):
            jobs.set_tracking(x["search_id"], True)
            st.rerun()

# 3.3 관심 기업 표
st.subheader("관심 기업")
st.caption("진행 단계: " + " → ".join(f"{k} {v}" for k, v in STAGE_LABELS.items()))
rows = queries.get_watchlist_rows(as_of)
if not rows:
    st.info("관심 기업이 없습니다. 기업 발굴·기업 상세에서 ☆를 누르면 추가돼요.")
for w in rows:
    r = w["row"]
    with st.container(border=True):
        cols = st.columns([2.2, 2, 1.6, 1.8, 1.4, 1.6, 1.6, 1.6, 0.8])
        cols[0].markdown(f"**★ {w['corp_name']}**  \n{texts.MARKET_LABELS.get(r['market'], r['market']) if r else '-'}")
        if not r:
            cols[1].write("분석 결과 없음")
            continue
        p = r["project"]
        cols[1].write(f"{p['country'] or '-'} · {texts.METHOD_LABELS.get(p['method'], p['method'] or '-')}")
        cols[2].write(f"{p['stage']} · {p['stage_label']}" if p["stage"] else "-")
        cols[3].write(f"{f.value(r['funding_gap'])} ({f.pct(r['funding_gap'].get('ratio'))})")
        cols[4].markdown(f.value(r["debt_ratio"], "%"), help=f.period_label(r["debt_ratio"].get("period")) + " · (부채총계/자본총계)×100, 한국기업평가 정의")
        cols[5].markdown(f.value(r["ttm_operating_cash_flow"]), help=f.period_label(r["ttm_operating_cash_flow"].get("period")) + " " + f.tooltip(r["ttm_operating_cash_flow"]))
        hits = [x for x in w["rules"] if x["rule_id"] != "R5"]
        cols[6].write(", ".join(x["label"] for x in hits if x["hit"]) or ("확인 불가 " + str(sum(x["hit"] is None for x in hits)) + "건" if any(x["hit"] is None for x in hits) else "해당 없음"))
        ch = w["latest_change"]
        cols[7].write(f"{texts.ALERT_LABELS.get(ch['alert_type'], ch['alert_type'])} {f.mmdd(ch['event_date'])}" if ch else "변경 없음")
        if cols[8].button("상세", key=f"wl_{w['corp_code']}"):
            nav.go("company", company=w["corp_code"])

# 3.4 변경 내역
st.subheader("관심 기업 변경 내역")
names = queries.company_names()
feed = queries.get_feed("watch_change")
if not feed:
    st.caption("최근 변경 없음")
for x in feed:
    link = f.evidence_link(x["evidence_ids"][0]) if x["evidence_ids"] else None
    st.markdown(f"**{texts.ALERT_LABELS.get(x['alert_type'], x['alert_type'])}** {names.get(x['corp_code'], x['corp_code'])} {f.mmdd(x['event_date'])} · {x['reason']}" + (f" [원문]({link})" if link else ""))

# 새 공시 조사 (2026-11-10 자율성 지시): 알림 시점과 검증 통과 요약. 경보 종류·단계는 규칙 결과 그대로
invs = queries.get_investigations()
with st.expander(f"조사 과정 · 새 공시 조사 {len(invs)}건", expanded=False):
    st.caption("감시가 새 공시를 찾으면 에이전트가 관련 공시·기사를 더 찾아보고 알림 시점(즉시/다음 요약)과 요약을 정합니다. 요약은 검증 에이전트를 통과한 문장만 보입니다.")
    for x in invs:
        st.markdown(f"**{'🔔 즉시' if x['timing'] == 'immediate' else '🗒 다음 요약'}** {names.get(x['corp_code'], x['corp_code'])} · 공시 [{x['rcept_no']}]({f.evidence_link('DART:' + x['rcept_no'] + ':x')}) · 검증 {x['verification_status']}")
        st.markdown(x["summary_md"] or "_요약 없음 (검증 통과 문장 없음)_")
        for tr in queries.get_traces(x["corp_code"], purpose="investigate"):
            if tr["trace_id"] == x["trace_id"]:
                trace_view.show(tr)

# 3.5 주별 신호
st.subheader("추적 범위의 주별 해외투자 신호")
weekly = queries.get_weekly_signals(as_of)
if weekly:
    st.plotly_chart(charts.weekly(weekly), use_container_width=True)
    st.caption("저장 조건 범위에서 새로 확인된 해외투자 계획·결정 건수 · 최근 12주")
else:
    st.caption("최근 12주 새 신호 없음")
if st.button("모두 읽음으로 표시"):
    jobs.mark_read()
    st.rerun()
