"""'조사 과정' 펼침 영역 (2026-11-10 자율성 지시). 에이전트가 고른 도구·이유·결과와 채택 판정을 그대로 보여준다."""
import pandas as pd
import streamlit as st

from ui import format as f

OUTCOME = {"repeat": "반복 차단(이미 확인함)", "news_unavailable": "뉴스 사용 불가 → 공시로 진행", "call": "조회", "stop": "종료", "budget": "예산 소진", "error": "오류", "adopted": "채택", "rejected": "기각", "not_found": "없음"}
TOOL = {"gate": "채택 게이트(코드 재확인)", "verify": "검증 에이전트"}
PURPOSE = {"fill": "빈 지표 찾기", "investigate": "새 공시 조사"}


def show(trace: dict) -> None:
    st.markdown(f"**{PURPOSE.get(trace['purpose'], trace['purpose'])}** · {trace['subject']} · 기준일 {trace['as_of']} · {trace['created_at']}")
    rows = []
    for s in trace["steps"]:
        src = s["source"] or {}
        no = src.get("rcept_no") or (s["args"] or {}).get("rcept_no")
        rows.append({"스텝": s["step"], "도구": TOOL.get(s["tool"], s["tool"] or "-"), "인자": ", ".join(f"{k}={v}" for k, v in (s["args"] or {}).items())[:80], "이유": s["reason"],
                     "결과": OUTCOME.get(s["outcome"], s["outcome"]) + (f" · {s['result_summary'][:120]}" if s["result_summary"] else ""),
                     "출처": f.evidence_link(f"DART:{no}:x") if no else None, "토큰": s["tokens"], "초": s["seconds"]})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, column_config={"출처": st.column_config.LinkColumn("출처", display_text=r"rcpNo=(\d+)")})
