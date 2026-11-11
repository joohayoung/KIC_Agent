"""STRIDE 화면 진입점 (화면_데이터_연결명세 1장, 5장). 실행: streamlit run stride/ui/app.py (저장소 최상위 폴더).
화면은 SQLite를 읽기만 하고, 실행은 worker(`python -m stride.cli orchestrator worker`)가 orc_jobs를 처리한다."""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from ui import jobs, nav, queries, texts  # noqa: E402

st.set_page_config(page_title="STRIDE 해외진출 자금수요 기업 발굴", layout="wide")
PAGES = {"track": st.Page(str(ROOT / "ui/pages/2_관심_기업_추적.py"), title="관심 기업 추적", default=True), "discover": st.Page(str(ROOT / "ui/pages/1_기업_발굴.py"), title="기업 발굴"), "company": st.Page(str(ROOT / "ui/pages/3_기업_상세.py"), title="기업 상세")}


def sidebar():
    with st.sidebar:
        st.markdown("### STRIDE")
        st.session_state.setdefault("as_of", date.today())
        st.session_state["as_of"] = st.date_input("기준일", st.session_state["as_of"], help="이 날짜 이후 자료는 사용하지 않음")
        n = queries.unread_feed_count()
        st.caption(f"관심 기업 추적 · 새 항목 {n}건" if n else "관심 기업 추적")
        recent = st.session_state.get("recent", [])
        if recent:
            st.markdown("**최근 본 기업**")
            names = queries.company_names()
            for cc in recent[:5]:
                if st.button(names.get(cc, cc), key=f"recent_{cc}"):
                    st.session_state["company"] = cc
                    st.switch_page(PAGES["company"])
        u = queries.last_update()
        st.caption(f"마지막 업데이트 {u['updated_at'] or '-'}" + (f" · 공시 {u['polled']}건 확인" if u.get("polled") is not None else ""))


def query_box():
    """1.1 상단 질의창: route_intent 실행 요청. 결과는 최근 intent 작업에서 읽는다."""
    cols = st.columns([6, 1])
    text = cols[0].text_input("질문", key="query_text", label_visibility="collapsed", placeholder="조건으로 기업 찾기, 기업 검토, 결과 질문, 표 필터")
    if cols[1].button("보내기", use_container_width=True) and text.strip():
        st.session_state["intent_job"] = jobs.enqueue("intent", {"text": text.strip(), "as_of": st.session_state["as_of"].isoformat()})
    chips = st.columns(len(texts.USAGE_CHIPS))
    names = list(queries.company_names().values())
    known = next((n for n in names if n), "OO")      # 예시 문장의 기업명은 분석한 기업 중 하나로 채운다
    for i, (c, (label, example)) in enumerate(zip(chips, texts.USAGE_CHIPS)):
        # 입력창 값은 위젯이 그려지기 전에 바꿔야 한다. 클릭 콜백은 다음 실행에서 위젯보다 먼저 돈다
        c.button(label, key=f"chip_{i}", use_container_width=True, on_click=lambda e=example: st.session_state.__setitem__("query_text", e.replace("OO", known)))
    job_id = st.session_state.get("intent_job")
    if not job_id:
        return
    job = queries.get_job(job_id)
    if job and job["status"] in ("queued", "running"):
        st.info("처리 중입니다 · 자동으로 갱신돼요 (worker가 실행 중이어야 합니다).")
        nav.poll()
    elif job and job["status"] == "failed":
        st.error("처리하지 못했습니다: " + (job["error"] or "").splitlines()[0])
    elif job and job["status"] == "done":
        res = json.loads(job["result_ref"] or "{}")
        it = res.get("intent", {})
        if it.get("intent") == "answer" and res.get("answer"):
            a = res["answer"]
            with st.container(border=True):
                st.markdown(f"**{a['question']}**")
                st.markdown(a["answer_md"])
                st.caption({"passed": "검증 통과", "partially_failed": "일부 문장 검증 실패로 제외", "no_data": "분석 결과 없음"}.get(a["verification_status"], ""))
                for link in a.get("links") or []:
                    if st.button(link["label"], key=f"ans_{link.get('corp_code')}"):
                        st.session_state["company"] = link.get("corp_code")
                        st.switch_page(PAGES["company"])
        elif it.get("intent") == "discover" and res.get("search_id"):
            st.session_state["search_id"] = res["search_id"]
            st.session_state.pop("intent_job")
            st.switch_page(PAGES["discover"])
        elif it.get("intent") == "review":
            st.session_state["company_query"] = it.get("company_mention")
            st.session_state.pop("intent_job")
            st.switch_page(PAGES["company"])
        elif it.get("intent") == "board_filter":
            bf = res.get("board_filter") or {}
            st.session_state["board_filters"] = bf.get("filters") or []
            if bf.get("message"):
                st.warning(bf["message"])
            else:
                st.success("기업 발굴 표에 필터를 적용했어요.")
        else:
            st.warning(it.get("clarify_question") or "무엇을 원하시는지 다시 적어 주세요.")


st.session_state["_pages"] = PAGES
sidebar()
query_box()
st.navigation(list(PAGES.values())).run()
