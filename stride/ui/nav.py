"""페이지 이동. app.py가 st.navigation 페이지 객체를 session_state에 둔다."""
import time

import streamlit as st

POLL_SECONDS = 2      # 화면_데이터_연결명세 1.3: 2초 간격으로 진행 상황을 읽는다


def poll() -> None:
    """작업이 끝날 때까지 2초마다 페이지를 다시 그린다. 화면 위쪽 내용은 그대로 보인다."""
    time.sleep(POLL_SECONDS)
    st.rerun()


def go(name: str, **state) -> None:
    """name: track | discover | company."""
    for k, v in state.items():
        st.session_state[k] = v
    if name == "company" and state.get("company"):
        recent = [state["company"]] + [c for c in st.session_state.get("recent", []) if c != state["company"]]
        st.session_state["recent"] = recent[:5]
    st.switch_page(st.session_state["_pages"][name])
