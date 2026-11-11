"""공통 시험 설정."""
import pytest

from core.clients import dart


@pytest.fixture(autouse=True)
def _reset_dart_quota():
    """DART 020(일일 한도) 표시는 프로세스 전역이다. 한 시험의 표시가 다른 시험으로 새지 않게 지운다."""
    dart.QUOTA_DAY["day"] = None
    yield
    dart.QUOTA_DAY["day"] = None
