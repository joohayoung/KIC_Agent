"""공통 지표 목록 로더·검증 (공통 양식 3-1장). 원본: docs/criteria/metrics_catalog.yaml 의 복사본."""
import importlib
from functools import lru_cache
from pathlib import Path

import yaml

from core.schemas import AgentResult

CATALOG_PATH = Path(__file__).with_name("metrics_catalog.yaml")


@lru_cache(maxsize=1)
def load() -> dict[str, dict]:
    rows = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    return {r["metric_id"]: r for r in rows}


def get(metric_id: str) -> dict | None:
    return load().get(metric_id)


def get_impl(metric_id: str):
    """implementation 경로의 함수를 돌려준다. 아직 구현되지 않았으면 ImportError/AttributeError."""
    mod, fn = load()[metric_id]["implementation"].rsplit(".", 1)
    return getattr(importlib.import_module(mod), fn)


def validate(result: AgentResult) -> list[str]:
    """목록에 없는 id, kind 불일치, 단위·방법론 불일치를 오류 문자열 목록으로 돌려준다 (빈 목록 = 통과)."""
    cat = load()
    errs = []
    for m in result.metrics:
        c = cat.get(m.metric_id)
        if c is None:
            errs.append(f"미등록 metric_id: {m.metric_id}")
            continue
        if c["kind"] != "metric":
            errs.append(f"{m.metric_id}: kind={c['kind']}인데 Metric으로 출력")
        if str(c.get("unit")) != m.unit:
            errs.append(f"{m.metric_id}: unit {m.unit!r} != 목록 {c.get('unit')!r}")
        if c.get("methodology") != m.methodology:
            errs.append(f"{m.metric_id}: methodology가 목록과 다름")
    for cl in result.classifications:
        c = cat.get(cl.key)
        if c is None:
            errs.append(f"미등록 classification key: {cl.key}")
        elif c["kind"] != "classification":
            errs.append(f"{cl.key}: kind={c['kind']}인데 Classification으로 출력")
    return errs
