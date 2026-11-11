"""읽기 전용 조사 도구 (2026-11-10 자율성 지시 1). 기존 함수를 감싸기만 하고 새 계산을 하지 않는다.

모든 도구는 as_of를 첫 인자로 받는다. 접수번호 앞 8자리(접수일)가 as_of보다 뒤인 공시, as_of 뒤에 나온 기사는 돌려주지 않는다.
도구 결과는 LLM이 읽는 글이다. 숫자를 채택할 때는 agents/common/gate.py가 원문을 다시 읽는다.
"""
import re
from datetime import date, timedelta

from core.asof import to_date
from core.clients import dart
from core.clients.dart_docs import audit_statements, body_xml, consolidated_audit_statements, note_sources
from core.clients.dart_notes import read_amortization, read_interest_note, read_lease_note, table_rows
from core.filings import classify_filing, select_reports
from core.clients.dart import DartQuotaError

MAX_CHARS = 6000


class AsOfError(ValueError):
    pass


def _d(x) -> date:
    return to_date(x) if not isinstance(x, date) else x


def check_rcept(rcept_no: str, as_of) -> None:
    if not re.fullmatch(r"\d{14}", str(rcept_no or "")):
        raise AsOfError(f"접수번호 형식 아님: {rcept_no}")
    if rcept_no[:8] > _d(as_of).strftime("%Y%m%d"):
        raise AsOfError(f"as_of 이후 공시: {rcept_no}")


def render(seg: str, limit: int = MAX_CHARS) -> str:
    """XML 구간 → 표는 '칸 | 칸' 줄, 나머지 태그는 지운 글."""
    seg = re.sub(r"<TABLE.*?</TABLE>", lambda m: "\n" + "\n".join(" | ".join(r) for r in table_rows(m.group(0))) + "\n", seg, flags=re.S)
    text = re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", " ", seg))
    return re.sub(r"\n\s*\n+", "\n", text).strip()[:limit]


def _around(xml: str, keyword: str, span: int = 20000) -> str:
    k = re.escape(re.sub(r"\s", "", keyword))
    m = re.search(r"<TITLE[^>]*>[^<]*" + k, re.sub(r"(?<=[가-힣])\s+(?=[가-힣])", "", xml)) or re.search(k, xml)
    if not m:
        return ""
    end = m.start() + span
    if (o := xml.rfind("<TABLE", m.start(), end)) > xml.rfind("</TABLE>", m.start(), end):      # 잘린 표는 끝까지
        end = (xml.find("</TABLE>", end) + 8) if xml.find("</TABLE>", end) >= 0 else len(xml)
    return xml[m.start(): end]


# ---- 도구 ----
def list_filings(as_of, corp_code: str, bgn: str, end: str | None = None, pblntf_ty: str | None = None) -> list[dict]:
    rows = dart.get_client().list_filings(_d(as_of), _d(bgn), _d(end or as_of), corp_code=corp_code, pblntf_ty=pblntf_ty)
    return [{"rcept_no": r["rcept_no"], "rcept_dt": r["rcept_dt"], "report_nm": re.sub(r"\s+", " ", r["report_nm"]).strip()} for r in rows][-40:]


def read_document_section(as_of, rcept_no: str, section: str) -> str:
    check_rcept(rcept_no, as_of)
    seg = _around(body_xml(dart.get_client().document(rcept_no)), section)
    return render(seg) if seg else f"'{section}' 절을 찾지 못함"


def read_zip_attachment(as_of, rcept_no: str, kind: str = "연결감사보고서", section: str | None = None) -> str:
    check_rcept(rcept_no, as_of)
    files = dart.get_client().document(rcept_no)
    xml = consolidated_audit_statements(files) if "연결" in kind else "".join(audit_statements(v.decode("utf-8", "ignore")) for v in files.values())
    if section:
        xml = _around(xml, section) or ""
    return render(xml) if xml else f"{kind} 첨부를 찾지 못함"


def financial_rows(as_of, corp_code: str, rcept_no: str) -> tuple[str | None, list[dict], dict | None]:
    """rcept_no 정기보고서의 fnlttSinglAcntAll 행 (연결 우선). 반환 (fs_div, 행, 보고서 묶음). compute_funding_gap.load_rows를 쓴다."""
    from agents.overseas_funding.nodes.compute_funding_gap import load_rows
    check_rcept(rcept_no, as_of)
    raw = dart.get_client().list_filings(_d(as_of), _d(as_of) - timedelta(days=3 * 365), _d(as_of), corp_code=corp_code, pblntf_ty="A")
    me = next((r for r in raw if r["rcept_no"] == rcept_no), None)
    period = re.search(r"\(\d{4}\.\d{2}\)", re.sub(r"\s", "", me["report_nm"])) if me else None
    norm = classify_filing(me["report_nm"])["norm"] if me else None
    g = next((x for x in select_reports(raw) if period and period.group(0) in re.sub(r"\s", "", x["latest"]["report_nm"]) and classify_filing(x["latest"]["report_nm"])["norm"] == norm), None)      # 정정본도 같은 기간 묶음
    if g is None:
        return None, [], None
    fs, rows = load_rows(dart.get_client(), corp_code, g["year"], g["kind"], raw, g["first_dt"])
    return fs, rows, g


def read_financials(as_of, corp_code: str, rcept_no: str, keyword: str = "") -> list[dict]:
    fs, rows, g = financial_rows(as_of, corp_code, rcept_no)
    if g is None:
        return [{"error": "정기보고서 묶음을 찾지 못함"}]
    if any(r.get("_version") == "unknown" for r in rows):
        return [{"error": "as_of 이후 정정된 보고서라 값 확인 불가"}]
    k = re.sub(r"\s", "", keyword)
    return [{"fs_div": fs, "sj_div": r.get("sj_div"), "account_id": r.get("account_id"), "account_nm": r.get("account_nm"), "thstrm_amount": r.get("thstrm_amount")}
            for r in rows if not k or k in re.sub(r"\s", "", r.get("account_nm") or "")][:40]


def find_related_filings(as_of, corp_code: str, rcept_no: str) -> list[dict]:
    """같은 공시의 정정, 조달 발행결과·증권발행실적보고서, 종속회사 주요경영사항. 기준 공시 30일 전부터 as_of까지."""
    check_rcept(rcept_no, as_of)
    rows = list_filings(as_of, corp_code, (_d(rcept_no[:8]) - timedelta(days=30)).isoformat())
    base = next((r for r in rows if r["rcept_no"] == rcept_no), None)
    norm = classify_filing(base["report_nm"])["norm"] if base else ""
    pat = re.compile(r"발행결과|증권발행실적|종속회사|자회사|정정")
    return [r for r in rows if r["rcept_no"] != rcept_no and (pat.search(r["report_nm"]) or (norm and classify_filing(r["report_nm"])["norm"] == norm))][:30]


def search_news(as_of, query: str, bgn: str, end: str | None = None) -> list[dict]:
    from core.clients.news import NaverNewsSource
    end_d = min(_d(end or as_of), _d(as_of))
    items = NaverNewsSource().search(query, _d(bgn), end_d)
    return [{"title": x["title"], "pubDate": str(x["pubDate"]), "url": x["url"]} for x in items if x["pubDate"] <= _d(as_of)][:15]


def read_note_table(as_of, rcept_no: str, kind: str) -> str | dict:
    """kind: lease | interest | amortization (기존 주석 판독 함수 결과) 또는 주석 표 제목 낱말 (그 표를 글로)."""
    check_rcept(rcept_no, as_of)
    files = dart.get_client().document(rcept_no)
    if kind in ("lease", "interest", "amortization"):
        got = {"lease": lambda: read_lease_note(files), "interest": lambda: read_interest_note(files), "amortization": lambda: read_amortization(files)}[kind]()
        return {k: v for k, v in got.items() if k in ("values", "value", "route", "reason", "current", "noncurrent", "total", "currency", "unit", "has_section", "N", "C")}
    out = []
    for name, seg in note_sources(files):
        for tm in re.finditer(r"<TABLE.*?</TABLE>", seg, re.S):
            ctx = re.sub(r"\s", "", re.sub(r"<[^>]+>", " ", seg[max(0, tm.start() - 300): tm.start()]))
            if re.sub(r"\s", "", kind) in ctx:
                end = tm.end()
                if len(table_rows(tm.group(0))) <= 1 and (nxt := seg.find("</TABLE>", end)) >= 0:      # 단위만 적힌 표 뒤의 본 표까지
                    end = nxt + 8
                out.append(f"[{name}] " + render(seg[max(0, tm.start() - 300): end], 2500))
            if len(out) >= 3:
                return "\n\n".join(out)
    return "\n\n".join(out) or f"'{kind}' 표를 찾지 못함"


# 도구 설명 = "언제 부르나 / 입력 / 출력" 한 줄. core/prompts/agent_loop.md의 {tools}에 그대로 들어간다 (2026-11-11 도구 설계 보완)
TOOLS = {
    "read_financials": (read_financials, "언제: 원천·소요 구성 항목이 비었을 때 재무 API 계정 행 확인 / 입력: corp_code, rcept_no(정기보고서), keyword? / 출력: 계정 행(fs_div, sj_div, account_id, account_nm, thstrm_amount) 최대 40개"),
    "read_document_section": (read_document_section, "언제: 공시 본문이나 사업보고서 특정 절의 문장·표가 필요할 때 / 입력: rcept_no, section(절·표 이름 낱말) / 출력: 그 절의 글(표는 '칸 | 칸' 줄) 최대 6,000자"),
    "find_related_filings": (find_related_filings, "언제: 새 공시를 정정·발행결과·종속회사 공시와 연결할 때 / 입력: corp_code, rcept_no / 출력: 관련 공시 목록(rcept_no, rcept_dt, report_nm) 최대 30개"),
    "search_news": (search_news, "언제: 공시만으로 진출 배경·진행 상황 맥락이 부족할 때 / 입력: query, bgn(YYYY-MM-DD), end? / 출력: 기사 제목·날짜·URL 최대 15개(기준일 이후 기사 제외)"),
    "list_filings": (list_filings, "언제: 기간 내 공시 전체를 훑어야 할 때 / 입력: corp_code, bgn(YYYY-MM-DD), end?, pblntf_ty?(A 정기 B 주요사항 I 거래소) / 출력: 공시 목록 최근 40개"),
    "read_note_table": (read_note_table, "언제: 상각비·리스·금융원가 등 주석 표가 필요할 때 / 입력: rcept_no, kind(lease|interest|amortization 또는 주석 표 제목 낱말) / 출력: 주석 판독 값 또는 표 글 최대 3개"),
    "read_zip_attachment": (read_zip_attachment, "언제: 본문에 없는 연결감사보고서 첨부가 필요할 때 / 입력: rcept_no, kind(연결감사보고서|감사보고서), section? / 출력: 첨부 재무제표 글 최대 6,000자"),
}


def run_tool(name: str, args: dict, as_of):
    """도구 실행. 잘못된 이름·인자·as_of 위반은 오류 글로 돌려준다 (루프가 다음 선택에 쓴다)."""
    if name not in TOOLS:
        return {"error": f"없는 도구: {name}"}
    try:
        return TOOLS[name][0](as_of, **(args or {}))
    except AsOfError as e:
        return {"error": str(e)}
    except TypeError as e:
        return {"error": f"인자 오류: {e}"[:200]}
    except DartQuotaError:      # DART 일일 한도(020): 삼키지 않고 올린다 (2026-11-11)
        raise
    except Exception as e:      # 조사 도구 실패는 조사 결과로 기록하고 계속한다
        return {"error": f"{type(e).__name__}: {e}"[:200]}
