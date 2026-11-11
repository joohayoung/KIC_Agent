"""이 에이전트 전용 모델 (개발문서 4장)."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class PeriodicReport(BaseModel):
    """as_of 이전에 접수된 정기보고서 1건."""
    rcept_no: str
    rcept_dt: date
    report_kind: Literal["annual", "half", "q1", "q3"]
    bsns_year: int
    reprt_code: str
    is_correction: bool = False
    evidence_ids: list[str] = Field(min_length=1)


class AccountValue(BaseModel):
    """재무제표 계정 1개 값."""
    key: str
    account_id: str | None
    account_nm: str
    fs_div: Literal["CFS", "OFS"]
    sj_div: str
    period_label: str
    amount: int | None
    rcept_no: str
    evidence_ids: list[str] = Field(min_length=1)


class FinancialYear(BaseModel):
    """사업연도 1개의 계정 묶음."""
    bsns_year: int
    fs_div: Literal["CFS", "OFS"]
    accounts: dict[str, AccountValue]
    rcept_no: str
    evidence_ids: list[str] = Field(min_length=1)


class MarketSnapshot(BaseModel):
    base_date: date
    market_cap: int | None
    close_price: int | None
    listed_shares: int | None
    source: Literal["krx_open_api", "data_go_kr_stock_price", "missing"]
    evidence_ids: list[str] = Field(min_length=1)


class RestructuringEvent(BaseModel):
    rcept_no: str
    rcept_dt: date
    report_nm: str
    kind: Literal["회생절차", "워크아웃", "파산", "기타 구조조정", "종결"]
    evidence_ids: list[str] = Field(min_length=1)
