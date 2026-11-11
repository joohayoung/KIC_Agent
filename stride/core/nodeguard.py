"""노드 예외 처리 (공통 양식 5장): 예외는 그래프를 멈추지 않고 errors에 기록한다. CoverageError와 DartQuotaError만 중단한다 (개발문서 6.1, 2026-11-11 도구 보완)."""
from functools import wraps

from core.asof import CoverageError
from core.clients.dart import DartQuotaError


def guarded(fn):
    @wraps(fn)
    def run(state):
        try:
            return fn(state)
        except (CoverageError, DartQuotaError):      # DART 일일 한도: 그래프·배치를 멈추고 호출자가 분석 대기로 둔다
            raise
        except Exception as e:      # 공통 양식 5장: 노드 안 예외는 그래프를 멈추지 않는다
            return {"errors": [f"{fn.__name__}: {type(e).__name__}: {str(e)[:200]}"]}
    return run
