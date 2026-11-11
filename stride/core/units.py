"""금액 문자열 → 원 (해외진출 개발문서 10.2). 금액 표현이 불확실하면 None."""
import re

_KRW_UNITS = {"조": 10**12, "억": 10**8, "백만": 10**6, "만": 10**4, "천": 10**3}
_FX_UNITS = {"billion": 10**9, "million": 10**6, "thousand": 10**3}


def parse_krw(text: str | None, fx: dict[str, float] | None = None) -> int | None:
    """'약 1,000억원', '1.1조원', 'USD 150 million' → 원. fx는 {"USD": 기준일 환율}. 환율이 없으면 None. '수천억원'처럼 숫자가 없으면 None."""
    if not text:
        return None
    s = re.sub(r"\s", "", text).replace(",", "")
    if m := re.search(r"([A-Z]{3})(\d+(?:\.\d+)?)(billion|million|thousand)?", s):
        rate = (fx or {}).get(m.group(1))
        return None if rate is None else round(float(m.group(2)) * _FX_UNITS.get(m.group(3), 1) * rate)
    m = re.search(r"(\d+(?:\.\d+)?)(조|억|백만|천만|만|천)?원", s)
    if not m:
        return None
    unit = 10**7 if m.group(2) == "천만" else _KRW_UNITS.get(m.group(2), 1)
    return round(float(m.group(1)) * unit)
