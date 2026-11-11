"""신규 문단 판정 (개발문서 8.5, v0.18 구조 수정).

순서: ① 소제목·기준일 문단은 번호를 지워 비교하고 그래도 다르면 신규에서 제외 ② 고유명사(국가·법인·지명)가 새로 등장하면 신규
③ 유사도가 threshold 미만이어도 고유명사가 모두 직전 보고서에 있으면 "표현 변경". 단 가장 비슷한 직전 문단에 없던 실행어(인수·건립 등)가 있으면 신규.
금액 변화만으로는 신규가 아니다.
"""
import re
from difflib import SequenceMatcher

COUNTRIES = ("미국", "북미", "캐나다", "멕시코", "유럽", "헝가리", "폴란드", "스페인", "독일", "베트남", "인도네시아", "인도", "중국", "일본", "말레이시아", "태국", "중동", "사우디", "싱가포르", "필리핀", "브라질", "튀르키예", "영국", "프랑스", "대만", "호주")
ACTION_WORDS = ("인수", "건립", "신설", "설립", "착공", "준공", "증설", "출자", "합작")     # 7.4 해외 확장 계획의 실행 행위. '회사명 없는 신규 투자' 문장을 놓치지 않기 위해 둔다
HEADING_MAX_CHARS = 40      # 보정 전: 2026-11-06 검수 오탐 소제목이 모두 30자 이내
_HEADING_NO = re.compile(r"^\s*(?:\(?\d+\)|\d+[.)]|\(?[가-힣]\)|[가-힣]\.|[①-⑳]|[IVX]+\.)\s*")
_AS_OF = re.compile(r"^\s*\(?\s*기준일\s*:")
_LEGAL = r"(?:LLC|INC|Inc|CO|Co|LTD|Ltd|GMBH|GmbH|CORP|Corp|PTE|LIMITED|Limited)\b\.?"
_LATIN_NAME = re.compile(r"((?:PT\.?\s*)?[A-Z][A-Za-z0-9&'.-]*(?:\s+[A-Z][A-Za-z0-9&'.-]*)*?)[,\s]+" + _LEGAL)
_KOREAN_NAME = re.compile(r"[가-힣A-Za-z]{2,}(?:유한공사|유한회사)|([가-힣A-Za-z]{2,})법인")
_GENERIC_ENTITY = {"판매", "생산", "현지", "해외", "국내", "종속", "신규", "합작", "자회사", "지배", "모", "연결", "상장", "비상장", "외국", "내국"}
_SITE = re.compile(r"([가-힣]{2,})(?:사업장|공장|산업단지|농공단지|공단|특별시|광역시)|([가-힣]{2,3})시(?=[\s,.·)|]|$)")
_BUILDING = re.compile(r"제\d+공장|\b[A-Z]동")
_GENERIC_STEM = {"생산", "임차", "신", "본사", "통합", "제조", "해외", "국내", "현지", "자사", "당사", "기존", "신규", "제", "역", "당", "수", "즉", "일", "동", "임", "미국", "중국"}


def normalize(text: str) -> str:
    """공백·숫자·연도 표기를 지운다. 연도·수치만 바뀐 반복 문구를 같은 문단으로 보기 위해서다."""
    return re.sub(r"\d{4}\s*년|\d+\s*(?:월|일|기|분기)|[\d,.]+|\s", "", text or "")


def is_heading(text: str) -> bool:
    """소제목 문단: 기준일 표기, 또는 번호 접두어가 있는 짧은 문단."""
    t = (text or "").strip()
    return bool(_AS_OF.match(t)) or (len(t) <= HEADING_MAX_CHARS and bool(_HEADING_NO.match(t)))


def _squash(text: str) -> str:
    return re.sub(r"[\s,.]", "", text or "").upper()


def proper_nouns(text: str) -> set[str]:
    """국가명·법인명·지명(사업장·공장 이름의 앞부분)·건물명. 대조하기 쉽게 공백과 쉼표를 지운다."""
    t = text or ""
    found = {c for c in COUNTRIES if c in t}
    found |= {_squash(m) for m in _LATIN_NAME.findall(t)}
    found |= {m.group(0) for m in _KOREAN_NAME.finditer(t) if m.group(1) not in _GENERIC_ENTITY}
    for a, b in _SITE.findall(t):
        stem = a or b
        if stem not in _GENERIC_STEM:
            found.add(stem)
    found |= {_squash(m) for m in _BUILDING.findall(t)}
    return found


def _best(norm: str, previous: list[tuple[str, str]]) -> tuple[float, str]:
    best, raw = 0.0, ""
    for pn, ptext in previous:
        sm = SequenceMatcher(None, norm, pn, autojunk=False)
        if sm.real_quick_ratio() <= best or sm.quick_ratio() <= best:
            continue
        r = sm.ratio()
        if r > best:
            best, raw = r, ptext
    return best, raw


def explain_new(latest, previous, threshold: float = 0.80) -> dict[str, dict]:
    """문단 ID → {"new", "label", "similarity", "new_nouns", "new_actions"}. label: 신규 / 표현 변경 / 소제목 / 기존."""
    prev = [(normalize(p.text), p.text) for p in previous]
    prev_all = _squash(" ".join(p.text for p in previous))
    out = {}
    for p in latest:
        score, similar = _best(normalize(p.text), prev)
        if is_heading(p.text):
            out[p.paragraph_id] = {"new": False, "label": "소제목", "similarity": round(score, 3), "new_nouns": [], "new_actions": []}
            continue
        fresh = sorted(n for n in proper_nouns(p.text) if _squash(n) not in prev_all)
        actions = [w for w in ACTION_WORDS if w in p.text and w not in similar] if score < threshold else []
        label = "신규" if fresh or actions else "표현 변경" if score < threshold else "기존"
        out[p.paragraph_id] = {"new": label == "신규", "label": label, "similarity": round(score, 3), "new_nouns": fresh, "new_actions": actions}
    return out


def mark_new_paragraphs(latest, previous, threshold: float = 0.80) -> set[str]:
    """latest 문단 중 신규 판정 문단 ID. 소제목·표현 변경·금액 변화는 신규가 아니다."""
    return {k for k, v in explain_new(latest, previous, threshold).items() if v["new"]}
