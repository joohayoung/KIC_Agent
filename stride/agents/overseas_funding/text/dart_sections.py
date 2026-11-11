"""원문 섹션 추출 (개발문서 8.4)."""
import re
from dataclasses import dataclass

OVERSEAS_KEYWORDS = [
    "해외", "현지", "법인 설립", "법인설립", "공장", "생산기지", "증설", "인수", "지분",
    "합작", "JV", "M&A", "진출",
    "미국", "북미", "캐나다", "멕시코", "유럽", "헝가리", "폴란드", "스페인", "독일",
    "베트남", "인도네시아", "인도", "중국", "일본", "말레이시아", "태국", "중동", "사우디",
]
PLAN_WORDS = ("향후", "계획", "예정", "추진")
_START = re.compile(r"^\s*I{1,3}\.\s*사업의\s*내용")
_END = re.compile(r"^\s*I{2,3}V?\.\s*")
_BLOCK = re.compile(r"<TITLE[^>]*>(?P<title>.*?)</TITLE>|<TABLE\b.*?</TABLE>|<P\b[^>]*>(?P<p>.*?)</P>", re.S)


@dataclass
class Paragraph:
    paragraph_id: str
    text: str
    subsection: str = ""


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def _table_text(tbl: str) -> str:
    rows = [[_plain(c) for c in re.findall(r"<T[DEHU][^>]*>(.*?)</T[DEHU]>", tr, re.S)] for tr in re.findall(r"<TR.*?</TR>", tbl, re.S)]
    return " | ".join(" ".join(c for c in r if c) for r in rows if any(r))


def extract_business_section(xml_bytes: bytes) -> list["Paragraph"]:
    """'II. 사업의 내용' 섹션을 문단 리스트로 반환한다. 표는 행 단위로 ' | '로 이어 한 문단. 섹션이 없으면 빈 리스트."""
    xml = xml_bytes.decode("utf-8", "replace")
    out, inside, sub, n = [], False, "", 0
    for m in _BLOCK.finditer(xml):
        title = m.group("title")
        if title is not None:
            text = _plain(title)
            if _START.search(text):
                inside = True
            elif inside and _END.search(text):
                break
            elif inside:
                sub = text
            continue
        if not inside:
            continue
        text = _plain(m.group("p")) if m.group("p") is not None else _table_text(m.group(0))
        if text:
            n += 1
            out.append(Paragraph(f"p{n}", text, sub))
    return out


def filter_overseas_paragraphs(paragraphs: list["Paragraph"], window: int = 1, max_chars: int = 15000) -> list["Paragraph"]:
    """키워드가 포함된 문단과 앞뒤 window개 문단만 남긴다. max_chars를 넘으면 계획 단어가 함께 있는 문단을 우선해 자른다. 순서는 원문 순서."""
    hit = {i for i, p in enumerate(paragraphs) if any(k in p.text for k in OVERSEAS_KEYWORDS)}
    keep = sorted({j for i in hit for j in range(max(0, i - window), min(len(paragraphs), i + window + 1))})
    picked = [paragraphs[i] for i in keep]
    if sum(len(p.text) for p in picked) <= max_chars:
        return picked
    order = sorted(keep, key=lambda i: (i not in hit, not any(w in paragraphs[i].text for w in PLAN_WORDS), i))
    chosen, total = set(), 0
    for i in order:
        if total + len(paragraphs[i].text) > max_chars:
            continue
        chosen.add(i)
        total += len(paragraphs[i].text)
    return [paragraphs[i] for i in sorted(chosen)]
