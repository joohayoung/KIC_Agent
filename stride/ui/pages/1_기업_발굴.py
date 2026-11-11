"""페이지 1 — 기업 발굴 (화면_데이터_연결명세 2장)."""
import pandas as pd
import streamlit as st

from orchestrator.answer import apply_board_filters
from orchestrator.config import INSTANT_FILTER_FIELDS, REGION_LABELS, STAGE_LABELS
from orchestrator.store import DEFAULT_SEARCH_ID
from orchestrator import common
from ui import charts, jobs, nav, queries, texts
from ui import format as f

as_of = st.session_state["as_of"].isoformat()
st.header("기업 발굴")
searches = queries.get_searches()
ids = [s["search_id"] for s in searches]
cur = st.session_state.get("search_id") if st.session_state.get("search_id") in ids else DEFAULT_SEARCH_ID

# 2.1 탭
labels = [s["name"] + (" · 저장 안 됨" if not s["is_saved"] else "") + (f" ({s['new_match_unread']})" if s["new_match_unread"] else "") for s in searches]
c1, c2 = st.columns([6, 1])
pick = c1.radio("탐색", labels, index=ids.index(cur) if cur in ids else 0, horizontal=True, label_visibility="collapsed")
search = searches[labels.index(pick)]
st.session_state["search_id"] = search["search_id"]
if c2.button("+ 새 조건"):
    nav.go("discover", search_id=jobs.new_search("새 조건"))

# 2.2 찾는 조건
with st.container(border=True):
    st.markdown("**찾는 조건** · 탭 하나가 조건 한 세트입니다. 칩은 모두 동시에 만족해야 해요.")
    if search["is_system"]:
        st.caption(texts.DEFAULT_SEARCH_TEXT)
    nl = st.text_input("자연어 조건", value=search.get("nl_text") or "", key=f"nl_{search['search_id']}", disabled=bool(search["is_system"]))
    crit = search["criteria"]
    b1, b2, b3 = st.columns(3)
    if b1.button("조건 해석", disabled=bool(search["is_system"]) or not nl.strip()):
        st.session_state["job"] = jobs.enqueue("discover", {"stage": "parse_only", "search_id": search["search_id"], "nl_text": nl.strip(), "as_of": as_of})
    if b2.button("다시 탐색"):
        st.session_state["job"] = jobs.enqueue("discover", {"search_id": search["search_id"], "as_of": as_of})
    if b3.button("★ 이 조건 저장 · 추적", disabled=bool(search["is_saved"])):
        jobs.save_search(search["search_id"], nl[:30] or search["name"])
        st.rerun()
    chips = []
    for k, v in crit.items():
        if v in (None, [], "") or k in ("unparsed", "as_of"):
            continue
        if k == "target_regions":
            v = [REGION_LABELS.get(x, x) for x in v]
        elif k == "stages":
            v = [f"{s} {STAGE_LABELS[s]}" for s in v]
        elif k == "markets":
            v = [texts.MARKET_LABELS.get(x, x) for x in v]
        elif k == "min_investment_amount":
            v = f.eok(v)
        chips.append(f"`{texts.CRITERIA_LABELS.get(k, k)}: {', '.join(map(str, v)) if isinstance(v, list) else v}`")
    st.markdown(" ".join(chips) or "조건 없음")
    if crit.get("unparsed"):
        st.caption("해석 보류: " + ", ".join(crit["unparsed"]) + " — 수치 기준이 없는 표현은 조건에 넣지 않았어요.")
    with st.expander("상세 조건"):
        st.json({texts.CRITERIA_LABELS.get(k, k): v for k, v in crit.items()})
    run = queries.latest_run(search["search_id"], as_of) or queries.latest_run(search["search_id"])
    st.caption(f"마지막 탐색 {run['created_at'] if run else '-'} · ⚡ 금액·비율·단계는 아래 표에서 바로 거를 수 있어요. 지역·업종·기간을 바꾸면 [다시 탐색]")

job_id = st.session_state.get("job")
if job_id:
    job = queries.get_job(job_id)
    if job and job["status"] in ("queued", "running"):
        prog = job["progress"] or {}
        st.info("탐색 중 · 자동으로 갱신돼요 · " + " → ".join(f"{texts.PROGRESS_STEPS.get(x['step'], x['step'])} {x.get('count', '')}" for x in prog.get("funnel", [])) + (f" · 분석 완료 {prog.get('deep_done', 0)}곳" if prog else " · 공시 목록 조회 중"))
        nav.poll()
    elif job and job["status"] == "failed":
        st.error("실행 실패: " + (job["error"] or "").splitlines()[0])

if run and run["as_of"] != as_of:
    st.warning(f"이 기준일({as_of}) 결과 없음 · 아래는 {run['as_of']} 결과입니다. [다시 탐색]으로 이 기준일 결과를 만들 수 있어요.")
if not run:
    st.info("아직 탐색 결과가 없습니다. 위 조건 칩을 확인하고 [다시 탐색]을 누르세요. "
            "탐색은 최근 12개월 상장사 전체의 취득·시설투자 공시 목록을 훑고(LLM 없음), 조건에 맞는 기업을 최근 공시일 순으로 최대 20곳(첫 탐색은 5곳) 분석합니다. "
            "기업당 약 1분이 걸리고, 처음 보는 기준일이면 공시 목록 조회에 몇 분이 더 걸려요.")
    st.stop()

# 2.4 깔때기·요약
cols = st.columns(len(run["funnel"]) or 1)
for c, x in zip(cols, run["funnel"]):
    c.metric(texts.PROGRESS_STEPS.get(x["step"], x["step"]), f"{x['count']:,}")
st.markdown(run["summary_md"] or "")
for s in run["suggestions"]:
    st.caption(f"제안: {s['action']} — {s['reason']} (실행하지 않음)")

# 2.5 후보 기업 표
board = queries.get_board(search["search_id"], run["run_id"])
rows = board["matched"]
st.caption("진행 단계: " + " → ".join(f"{k} {v}" for k, v in STAGE_LABELS.items()))
fc = st.columns([2, 2, 2])
sort = fc[0].selectbox("정렬", ["기본 정렬", "원천÷소요 (낮은 순)", "원천−소요 (작은 순)", "24개월 내 해외 투자액", "부채비율", "최근 신호일"])
filters = st.session_state.get("board_filters") or []
if filters:
    fc[1].write("필터: " + ", ".join(f"{INSTANT_FILTER_FIELDS[x['field']]} {x['op']} {x['value']}" for x in filters))
    if fc[2].button("필터 지우기"):
        st.session_state["board_filters"] = []
        st.rerun()
    rows = apply_board_filters(rows, filters)
liq = lambda r, k: ((r.get("liquidity") or {}).get(k) or {}).get("value")
if sort == "기본 정렬":
    rows = sorted(rows, key=common.default_sort_key)
    st.caption(common.DEFAULT_SORT_TEXT)
elif sort.startswith("원천"):      # 낮은 순, 산출 불가는 뒤
    k = "ratio" if "÷" in sort else "surplus"
    rows = sorted(rows, key=lambda r: (liq(r, k) is None, liq(r, k) or 0))
else:
    key = {"24개월 내 해외 투자액": lambda r: liq(r, "investment_24m") or 0, "부채비율": lambda r: r["debt_ratio"].get("value") or 0, "최근 신호일": lambda r: r["project"].get("latest_signal_date") or ""}[sort]
    rows = sorted(rows, key=key, reverse=True)
st.caption(texts.LIQUIDITY_NOTE)
view = st.radio("보기", ["표", "분포도"], horizontal=True, label_visibility="collapsed")
if view == "표":
    head = st.columns([0.4, 2, 2.2, 1.6, 1.3, 1.4, 1.1, 2, 1, 0.8])
    for c, t in zip(head[1:], ["기업", "해외 투자 (국가·금액)", "해외 용도 조달", "원천÷소요", "원천−소요", "부채비율", "재무 위험 경고 · 변경", "검증"]):
        c.caption(t)
if view == "분포도":
    fig, hidden = charts.scatter(rows)
    st.plotly_chart(fig, use_container_width=True)
    st.caption("원 크기 = 24개월 내 해외 투자액 · 빨강 = 재무 위험 경고 있음 · 점선 = 원천÷소요 1배" + (f" · 분포도 미표시 {hidden}곳(값 없음)" if hidden else ""))
else:
    for r in rows:
        with st.container(border=True):
            cols = st.columns([0.4, 2, 2.2, 1.6, 1.3, 1.4, 1.1, 2, 1, 0.8])
            star = cols[0].checkbox("☆", value=r["is_watched"], key=f"w_{r['corp_code']}", label_visibility="collapsed")
            if star != r["is_watched"]:
                jobs.toggle_watch(r["corp_code"], r["corp_name"], star, "board")
                st.rerun()
            cols[1].markdown(f"**{r['corp_name']}**  \n{texts.MARKET_LABELS.get(r['market'], r['market'])} · {r['industry']}")
            p, inv, lq, fs = r["project"], r["investment_amount"], r.get("liquidity") or {}, r.get("funding_status") or {}
            in24 = lq.get("investment_24m")
            cols[2].markdown(f"{p['country'] or '-'} · {f.value(inv)} {texts.SOURCE_LABELS.get(inv.get('source'), '')}  \n{p['stage']}단계 {p['stage_label'] or ''} · 최근 신호 {f.mmdd(p.get('latest_signal_date'))}" if p["stage"] else f"{p['country'] or '-'} · {f.value(inv)}",
                             help=f"24개월 내 {f.value(in24)} · 24개월 밖 {f.value(lq.get('investment_beyond_24m'))}. " + f.tooltip(in24 or inv))
            cols[3].markdown(fs.get("label") or "없음", help=f"결과 공시 전 {f.eok(fs.get('unconfirmed'))} · 납입 확정 {f.eok(fs.get('confirmed'))}. 결과 공시 전 조달은 원천에 넣지 않음" if fs.get("label") not in (None, "없음") else "해외 용도 조달 결정 공시 없음")
            cols[4].markdown(f.value(lq.get("ratio"), "배"), help=f.period_label((lq.get("ratio") or {}).get("period")) + " · " + f.tooltip(lq.get("ratio")))
            cols[5].markdown(f.value(lq.get("surplus")), help=f"원천 {f.value(lq.get('sources'))} − 소요 {f.value(lq.get('uses'))}. " + f.tooltip(lq.get("surplus")))
            cols[6].markdown(f.value(r["debt_ratio"], "%"), help=f.period_label(r["debt_ratio"].get("period")) + " · (부채총계/자본총계)×100, 한국기업평가 정의 " + f.tooltip(r["debt_ratio"]))
            cols[7].write(", ".join((r.get("risk_warnings") or r["rule_hits"]) + [texts.ALERT_LABELS.get(b, b) for b in r["change_badges"]]) or "-")
            cols[8].write(texts.VERIFICATION_LABELS[r["verification"]])
            if cols[9].button("상세", key=f"d_{r['corp_code']}"):
                nav.go("company", company=r["corp_code"])
    if not rows:
        st.caption("조건을 충족한 기업이 없습니다.")

# 2.7 분석 대기·제외
st.subheader(f"분석 대기 {len(board['pending'])}개 기업")
if board["pending"] and st.button("추가 분석"):
    st.session_state["job"] = jobs.enqueue("add_analysis", {"search_id": search["search_id"], "as_of": as_of})
    st.rerun()
if board["pending"]:
    st.dataframe(pd.DataFrame(board["pending"]).rename(columns={"corp_name": "기업", "latest_filing_date": "최근 공시일"})[["기업", "최근 공시일"]], hide_index=True)
st.subheader(f"제외 목록 {len(board['excluded'])}개 기업")
if board["excluded"]:
    st.dataframe(pd.DataFrame([{"기업": x["corp_name"], "단계": x["excluded_step"], "제외 조건": x["excluded_condition"], "값": x["excluded_value"], "근거": f.evidence_link(x["evidence_ids"][0]) if x["evidence_ids"] else None} for x in board["excluded"]]),
                 hide_index=True, column_config={"근거": st.column_config.LinkColumn("근거")})
