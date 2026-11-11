"""새 공시 추가 조사 (2026-11-10 자율성 지시 기능 2). 감시가 새 공시를 찾으면 조사 루프가
 (1) 이 공시가 추적 중인 프로젝트·기업에 어떤 의미인지 보고 (2) 필요하면 관련 공시·기사를 더 찾고 (3) 알림 시점과 조사 요약을 정한다.

상태 변경(프로젝트 연결, 단계, 경보 종류)은 해외진출 7.12 규칙이 이미 정했다. 루프는 바꾸지 않는다.
요약 문장은 검증 에이전트(answer 모드)를 통과한 문장만 남긴다. 근거는 루프가 도구로 본 as_of 이하 공시·기사뿐이다.
"""
import json
import re
import uuid

from agents.common import tools
from agents.verifier.graph import verify_answer
from core.agent_loop import run_loop
from orchestrator import common, store

RULES = ("stop 할 때: timing은 immediate(추적 프로젝트의 단계·금액·일정·취소에 직접 관련되거나 아래 규칙 경보가 있음) 또는 digest(그 밖). "
         "sentences는 1~3개 사실 문장. 각 문장 evidence_ids에는 아래 '근거 ID' 또는 도구로 본 공시의 'DART:{접수번호}:목록', 기사의 'NEWSURL:{url}'만 쓴다. "
         "숫자는 근거에 적힌 것만 쓴다. 평가·전망·권유를 쓰지 않는다. related에는 함께 확인한 관련 공시 접수번호. findings는 비운다.")


def context_text(ovs, filing: dict, as_of) -> tuple[str, dict]:
    """(자료 글, cited 시작값). cited: {근거 ID: {"values": [], "quote"}}."""
    p = common.main_project(ovs)
    fid = f"DART:{filing['rcept_no']}:목록"
    cited = {fid: {"values": [], "quote": f"{filing['rcept_dt']} {filing['report_nm']}"}}
    lines = [f"기업: {ovs.corp_name} (corp_code {ovs.corp_code}), 기준일 {as_of}",
             f"새 공시: {filing['report_nm']} (접수 {filing['rcept_dt']}, 접수번호 {filing['rcept_no']}) 근거 ID {fid}",
             f"추적 프로젝트: {p['target_country']} · {p.get('method')} · {p['stage']}단계 · 최근 신호 {p.get('latest_event_date')}" if p else "추적 프로젝트: 없음",
             "규칙이 정한 경보: " + ("; ".join(f"{a.alert_type} — {a.message[:120]}" for a in ovs.alerts) or "없음")]
    for s in (ovs.extra.get("signals") or [])[-6:]:
        lines.append(f"- 신호 {s.get('event_date')} {s.get('signal_type')}: {(s.get('summary') or '')[:100]} 근거 ID {(s.get('evidence_ids') or [])[:1]}")
        for i in (s.get("evidence_ids") or [])[:1]:
            cited.setdefault(i, {"values": [], "quote": s.get("summary") or ""})
    return "\n".join(lines), cited


def _cited_from_seen(seen: list[dict], cited: dict, as_of) -> int:
    """루프가 본 도구 결과에서 근거를 만든다. as_of 이후 항목이 섞여 있으면 세어서 돌려준다 (누수 검사, 0이어야 한다)."""
    late, day = 0, as_of.strftime("%Y%m%d")
    for x in seen:      # 루프가 읽은 공시 본문·주석·첨부 글을 그 공시 근거의 인용으로 둔다 (검증 에이전트가 문장과 대조)
        no = (x.get("args") or {}).get("rcept_no")
        if no and isinstance(x["result"], str) and no[:8] <= day:
            c = cited.setdefault(f"DART:{no}:목록", {"values": [], "quote": ""})
            c["quote"] = (c["quote"] + " / " + x["result"][:2500]).strip(" /")
        rows = x["result"] if isinstance(x["result"], list) else []
        for r in rows:
            if not isinstance(r, dict):
                continue
            if r.get("rcept_no"):
                late += r["rcept_no"][:8] > day
                cited.setdefault(f"DART:{r['rcept_no']}:목록", {"values": [], "quote": f"{r.get('rcept_dt')} {r.get('report_nm')}"})
            if r.get("url"):
                late += str(r.get("pubDate")) > as_of.isoformat()
                cited.setdefault(f"NEWSURL:{r['url']}", {"values": [], "quote": f"{r.get('pubDate')} {r.get('title')}"})
    return late


def investigate_filing(con, run_id: str, ovs, filing: dict, as_of) -> dict:
    """반환 {timing, summary_md, verification_status, calls, tokens, seconds, late, trace_id}. 조사 루프 1회 (최대 6스텝)."""
    ctx, cited = context_text(ovs, filing, as_of)
    trace_id = f"inv_{uuid.uuid4().hex[:10]}"
    loop = run_loop("새로 접수된 공시가 추적 중인 해외 프로젝트와 기업에 어떤 의미인지 확인하라. 필요하면 관련 공시(모회사 출자, 자금 조달, 정정, 발행결과)와 최근 기사를 더 찾아보라.",
                    ctx, RULES, tools.TOOLS, as_of=as_of, run_id=run_id)
    late = _cited_from_seen(loop["seen"], cited, as_of)
    final = loop["final"]
    timing = final.timing if final and final.timing else "digest"
    sentences = [s for s in (final.sentences if final else []) if any(i in cited for i in s.evidence_ids)]
    text, foot, status, calls = "", {}, "no_data", loop["calls"]
    if sentences:
        text, foot = common.render(sentences, cited)
        rep = verify_answer(text, foot, cited, as_of, request_id=f"{run_id}:inv", corp_code=ovs.corp_code)
        calls += rep.llm_calls
        bad = {int(t.split()[1]) for t in rep.failed_targets if re.match(r"문장 \d+", t)}
        keep = [s for i, s in enumerate(sentences, 1) if i not in bad]
        text, foot = common.render(keep, cited)
        status = "passed" if not bad else ("partially_failed" if keep else "failed")
    steps = loop["steps"] + [{"step": len(loop["steps"]) + 1, "tool": "verify", "reason": f"알림 시점 {timing}, 요약 검증 {status}", "result": text[:300], "outcome": "stop", "source": {"related": final.related if final else [], "late": late}}]
    store.save_trace(con, trace_id, run_id, ovs.corp_code, as_of.isoformat(), "investigate", f"{filing['rcept_no']} {filing['report_nm']}"[:200], steps)
    con.execute("INSERT OR REPLACE INTO orc_investigations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (f"{trace_id}", trace_id, run_id, ovs.corp_code, filing["rcept_no"], as_of.isoformat(), timing, text, json.dumps(foot, ensure_ascii=False), status,
                                                                                             json.dumps(final.related if final else [], ensure_ascii=False), store.now()))
    con.commit()
    return {"timing": timing, "summary_md": text, "verification_status": status, "calls": calls, "tokens": loop["tokens"], "seconds": loop["seconds"], "late": late, "trace_id": trace_id, "related": final.related if final else []}
