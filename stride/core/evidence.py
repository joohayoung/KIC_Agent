"""근거 ID 생성·검증 (공통 양식 4장)."""
import hashlib
import importlib
import math

from core.schemas import AgentResult


def dart_section(rcept_no: str, section: str) -> str:
    return f"DART:{rcept_no}:{section}"


def dart_api(rcept_no: str, api: str, field: str) -> str:
    return f"DART:{rcept_no}:{api}:{field}"


def fin(rcept_no: str, fs_div: str, account_id: str) -> str:
    return f"FIN:{rcept_no}:{fs_div}:{account_id}"


def krx(bas_dd: str, isu_cd: str, field: str) -> str:
    return f"KRX:{bas_dd}:{isu_cd}:{field}"


def pub(org: str, doc: str, item: str) -> str:
    return f"PUB:{org}:{doc}:{item}"


def news(url: str) -> str:
    return f"NEWS:{hashlib.sha1(url.encode('utf-8')).hexdigest()[:12]}"


def calc(run_id: str, metric_id: str) -> str:
    return f"CALC:{run_id}:{metric_id}"


PREFIXES = ("DART:", "FIN:", "KRX:", "PUB:", "NEWS:", "CALC:")


def _recalc_ok(meta: dict) -> bool:
    """CALC 근거 meta = {"impl": "모듈.함수", "args": {...}, "value": 기록값, "inputs": [evidence_id...]}.
    impl을 args로 다시 호출해 value와 같은지 본다."""
    try:
        mod, fn = meta["impl"].rsplit(".", 1)
        got = getattr(importlib.import_module(mod), fn)(**meta.get("args", {}))
    except Exception:
        return False
    if isinstance(got, tuple):      # (값, note)를 돌려주는 함수
        got = got[0]
    want = meta.get("value")
    if got is None or want is None:
        return got is want
    return math.isclose(float(got), float(want), rel_tol=1e-9, abs_tol=1e-9)


def validate_evidence(result: AgentResult) -> AgentResult:
    """반환 전 필수 호출. 실패 항목은 버리고 errors에 기록한 새 결과를 돌려준다.

    1) 형식이 틀리거나 published_at > as_of 이거나 CALC 재계산이 다른 근거 → 제거
    2) evidence_ids가 남은 근거에 없는 id → 제거. 남은 id가 0개인 항목은 항목째 제거
    """
    errors = list(result.errors)
    good = {}
    for ev in result.evidence:
        eid = ev.evidence_id
        if not eid.startswith(PREFIXES):
            errors.append(f"validate_evidence: 형식 오류 {eid}")
        elif ev.published_at > result.as_of:
            errors.append(f"validate_evidence: as_of 이후 근거 {eid} ({ev.published_at})")
        elif eid.startswith("CALC:") and not _recalc_ok(ev.meta):
            errors.append(f"validate_evidence: CALC 재계산 불일치 {eid}")
        else:
            good[eid] = ev

    def keep(items, label):
        out = []
        for it in items:
            ids = [i for i in it.evidence_ids if i in good]
            missing = [i for i in it.evidence_ids if i not in good]
            if missing:
                errors.append(f"validate_evidence: {label} 근거 없음 {missing}")
            if ids:
                out.append(it.model_copy(update={"evidence_ids": ids}))
        return out

    return result.model_copy(update={
        "evidence": list(good.values()),
        "metrics": keep(result.metrics, "metric"),
        "classifications": keep(result.classifications, "classification"),
        "findings": keep(result.findings, "finding"),
        "alerts": keep(result.alerts, "alert"),
        "errors": errors,
    })
