"""공통 Settings. 키는 저장소 최상위 .env 에서만 읽는다."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]          # 저장소 최상위


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    dart_api_key: str = ""
    naver_client_id: str = ""
    naver_client_secret: str = ""
    naver_news_url: str = "https://naverapihub.apigw.ntruss.com/search/v1/news"
    naver_news_provider: str = "ncp"
    stride_db_path: str = "./data/stride.db"
    stride_cache_dir: str = "./data/cache"
    stride_log_dir: str = "./data/logs"
    first_run_max_deep_analysis: int = 5   # 첫 실제 탐색의 심층 분석 상한 (오케스트레이터 prefilter)

    def path(self, p: str) -> Path:
        """.env의 상대 경로는 저장소 최상위 기준."""
        q = Path(p)
        return q if q.is_absolute() else ROOT / q


settings = Settings()
