"""보고서 판단 표현·금지 필드 검사 (공통 양식 8장, 검증 개발문서 R-06). 코드로 검사한다."""
from core.schemas import FORBIDDEN_FIELDS

# 해외진출 개발문서 7.11의 판단 표현 목록
FORBIDDEN_TERMS = ("추천", "유망", "투자 적합", "우선순위", "접촉")


def forbidden_terms(text: str | None) -> list[str]:
    return [t for t in FORBIDDEN_TERMS if t in (text or "")]


def forbidden_fields(obj, path: str = "") -> list[str]:
    """dict·list 안까지 금지 필드 이름을 찾는다."""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in FORBIDDEN_FIELDS:
                hits.append(f"{path}.{k}")
            hits += forbidden_fields(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += forbidden_fields(v, f"{path}[{i}]")
    return hits
