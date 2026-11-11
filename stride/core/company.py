"""기업 식별 공통 함수 (해외진출 7.2, 재무 건전성 8장)."""
import re

MARKETS = {"Y": "KOSPI", "K": "KOSDAQ", "N": "KONEX"}


def _plain(name: str) -> str:
    return re.sub(r"\s|\(주\)|㈜|주식회사", "", name or "")


def resolve(client, query: str | None, corp_code: str | None = None) -> tuple[dict | None, str | None, list[str]]:
    """반환 (company, 오류, 후보 이름 목록). company = {"corp_code", "corp_name", "stock_code", "market"}. market은 비상장이면 "UNLISTED".
    후보가 여러 개면 임의로 고르지 않는다."""
    q = (corp_code or query or "").strip()
    if not q:
        return None, "기업 입력 없음", []
    rows = client.corp_codes()
    if re.fullmatch(r"\d{8}", q):
        hit = [r for r in rows if r.get("corp_code") == q]
    elif re.fullmatch(r"\d{6}", q):
        hit = [r for r in rows if r.get("stock_code") == q]
    else:
        hit = [r for r in rows if r.get("corp_name") == q] or [r for r in rows if _plain(r.get("corp_name")) == _plain(q)]
    if len(hit) > 1:
        hit = [r for r in hit if r.get("stock_code")] or hit
    if not hit:
        return None, f"기업을 찾지 못함: {q}", []
    if len(hit) > 1:
        return None, f"후보가 여러 개: {q}", [r["corp_name"] for r in hit]
    r = hit[0]
    info = client.get_json("company.json", corp_code=r["corp_code"])
    market = MARKETS.get(info.get("corp_cls"), "UNLISTED") if r.get("stock_code") else "UNLISTED"
    return {"corp_code": r["corp_code"], "corp_name": r["corp_name"], "stock_code": r.get("stock_code") or None, "market": market}, None, []
