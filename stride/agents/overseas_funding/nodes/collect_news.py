import re
from datetime import timedelta
from difflib import SequenceMatcher

from dateutil.relativedelta import relativedelta

from agents.overseas_funding.config import NEWS_ACTIONS, NEWS_KEYWORDS, NEWS_MAX_ITEMS, NEWS_RECENT_DAYS, NEWS_TITLE_SIMILARITY
from agents.overseas_funding.schemas import GenerateNewsQueriesOutput
from core import evidence as ev
from core.clients import news as news_mod
from core.llm import call_llm
from core.nodeguard import guarded
from core.schemas import Evidence

PROMPT = "agents/overseas_funding/prompts/generate_news_queries.md"
_ws = lambda s: re.sub(r"\s+", "", s or "")


def base_queries(corp_name: str) -> list[str]:
    return [f'"{corp_name}" {k}' for k in NEWS_KEYWORDS]


def signal_sentences(signals, evidence) -> tuple[str, set[str]]:
    """공시 기반 신호(S1·S4·S5)의 문장 자료. 근거 quote가 있으면 함께 준다."""
    quotes = {e.evidence_id: e.quote for e in evidence if e.quote}
    lines, ids = [], set()
    for s in signals:
        if s.signal_type.value in ("S1_plan", "S4_confirmed", "S5_funding") and s.value_status == "ok" and s.is_overseas is not False:
            for eid in s.evidence_ids[:1]:
                ids.add(eid)
                lines.append(f"[{eid}] {s.summary} {s.target_country or ''} {quotes.get(eid, '')}".strip())
    return "\n".join(lines), ids


def validate_queries(output: GenerateNewsQueriesOutput, corp_name: str, sentences: str, ids: set[str]) -> tuple[list[str], list[dict]]:
    """D2 검증기: 고유명사가 자료 문장에 실제로 있고, 검색어가 기업명 + 그 고유명사 + 허용 행위로만 이뤄져야 한다."""
    good, rejected = [], []
    text = _ws(sentences)
    for q in output.queries[:3]:
        reason = None
        rest = _ws(q.query).replace(_ws(corp_name), "", 1) if _ws(corp_name) in _ws(q.query) else None
        if rest is None:
            reason = "기업명 없음"
        elif not q.proper_nouns:
            reason = "고유명사 없음"
        elif missing := [n for n in q.proper_nouns if _ws(n) not in text]:
            reason = f"자료에 없는 고유명사: {missing}"
        elif not set(q.evidence_ids) & ids:
            reason = "근거 없음"
        else:
            for n in sorted(q.proper_nouns, key=len, reverse=True):
                rest = rest.replace(_ws(n), "")
            if rest not in NEWS_ACTIONS:      # 선언하지 않은 고유명사가 끼어드는 것을 막는다
                reason = f"허용되지 않은 검색어 구성: {rest}"
        if reason:
            rejected.append({"point": "D2", "action": "reject_query", "reason": f"{q.query}: {reason}"})
        else:
            good.append(q.query)
    return good, rejected


def select_source(company, as_of, today):
    return news_mod.NaverNewsSource() if (today - as_of).days <= NEWS_RECENT_DAYS else news_mod.FileNewsSource(company.corp_code)


def refine(items: list[dict], corp_name: str, start, as_of) -> list[dict]:
    """기간·제목 필터, URL·제목 유사도 중복 제거, 최신순 상위 N건 (7.6)."""
    seen, out = set(), []
    for x in sorted(items, key=lambda i: i["pubDate"], reverse=True):
        if not (start <= x["pubDate"] <= as_of) or corp_name not in (x["title"] or "") or x["url"] in seen:
            continue
        if any(SequenceMatcher(None, x["title"], y["title"]).ratio() >= NEWS_TITLE_SIMILARITY for y in out):
            continue
        seen.add(x["url"])
        out.append(x)
    return out[:NEWS_MAX_ITEMS]


@guarded
def collect_news(state) -> dict:
    """as_of 이전 기사를 수집한다 (7.6). 추가 검색어는 D2 LLM + 코드 검증. 실패하면 기본 검색어만."""
    if state.get("news_items") is not None:
        return {}
    from datetime import date
    req, company = state["request"], state["company"]
    start = req.as_of - relativedelta(months=req.lookback_months)
    queries, decisions, errors, llm = base_queries(company.corp_name), [], [], state.get("llm_calls", 0)
    sentences, ids = signal_sentences(state.get("signals") or [], state.get("evidence") or [])
    extra = []
    if sentences and not req.context.get("no_llm"):
        try:
            out = call_llm(PROMPT, {"corp_name": company.corp_name, "signal_sentences": sentences}, GenerateNewsQueriesOutput, run_id=state["run_id"], as_of=req.as_of)
            llm += 1
            extra, decisions = validate_queries(out, company.corp_name, sentences, ids)
        except Exception as e:      # 7.6 2d: LLM 실패 → 기본 검색어만
            errors.append(f"collect_news: D2 {type(e).__name__}")
    source = select_source(company, req.as_of, date.today())
    items = []
    for q in queries + extra:
        items += source.search(q, start, req.as_of)
    picked = refine(items, company.corp_name, start, req.as_of)
    evidence = [Evidence(evidence_id=ev.news(x["url"]), source_grade="C", source_type="news", corp_code=company.corp_code, published_at=x["pubDate"], title=x["title"], url=x["url"], quote=(x["description"] or "")[:300] or None) for x in picked]
    return {"news_items": [{**x, "evidence_id": ev.news(x["url"])} for x in picked], "news_queries": extra, "decisions": decisions, "evidence": evidence, "errors": errors, "llm_calls": llm}
