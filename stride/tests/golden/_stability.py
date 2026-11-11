"""같은 입력 2회 비교 (2026-11-07 결정). 금액·단계·경보 입력이 LLM 라벨 흔들림과 무관한지 본다. 실제 claude -p를 호출한다.
사용: python tests/golden/_stability.py <결과 json 경로>  (stride 폴더에서). 경보는 8단계라 경보 입력(프로젝트 방향, 연결된 S6)을 비교한다."""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agents.overseas_funding.graph import run_company  # noqa: E402
from core.schemas import Request  # noqa: E402

G = Path(__file__).parent / "overseas_funding"
CASES = [("G-POS_주", None), ("G-POS_보조", None), ("G-POS_MIXED", None), ("G-POS_HALTED", None), ("G-CHANGE_1", "2025-07-07"), ("G-MIX_1", None)]
LABEL = ("purpose_category", "is_overseas", "method", "change_direction", "part_of_earlier", "fund_use_scopes", "target_country", "related_project")


def fixed(r):
    """라벨 흔들림과 무관해야 하는 값."""
    m = {x.metric_id: x.value for x in r.metrics}
    return {"metrics": {k: m.get(k) for k in ("ovs.overseas_investment_amount", "ovs.available_internal_funds", "ovs.funding_gap", "ovs.funding_gap_ratio", "ovs.confirmed_overseas_funding")}, "project_count_info_only": None,
            "classes": {c.key: c.value for c in r.classifications},
            "projects": sorted(([p["project_key"], p["stage"], p["change_direction"], p["amount_krw"], p.get("gate_pass")] for p in r.extra["projects"] if p["amount_source"] == "major_event"), key=str),
            "linked_s6": sorted([s["signal_id"], s["change_direction"]] for s in r.extra["signals"] if s["signal_type"] == "S6_alert"),
            "working_capital": (r.extra["funding_gap"] or {}).get("overseas_subsidiary_working_capital_krw")}


def main(out):
    rows = []
    for name, as_of in CASES:
        doc = json.loads((G / f"{name}.json").read_text(encoding="utf-8"))
        day = as_of or doc["request"]["as_of"]
        runs = [run_company(Request(request_id="s", agent="overseas_funding", mode="single", corp_code=doc["corp_code"], as_of=date.fromisoformat(day), context={"db_path": ":memory:"})) for _ in range(2)]
        a, b = fixed(runs[0]), fixed(runs[1])
        la, lb = runs[0].extra["major_labels"], runs[1].extra["major_labels"]
        diff = [{"rcept_no": k, **{f: [la[k].get(f), lb[k].get(f)] for f in LABEL if la[k].get(f) != lb[k].get(f)}} for k in sorted(la.keys() & lb.keys()) if any(la[k].get(f) != lb[k].get(f) for f in LABEL)]
        rows.append({"case": name, "as_of": day, "same": a == b, "first": a, "second": b if a != b else None, "labels": len(la.keys() & lb.keys()), "label_diffs": diff, "unlinked": [len(x.extra["unlinked_s6"]) for x in runs], "llm_calls": [x.extra["llm_calls"] for x in runs], "errors": [x.errors for x in runs], "unverified": [len([f for f in x.findings if f.kind == "unverified"]) for x in runs]})
        Path(out).write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(name, "같음" if a == b else "다름", "라벨 차이", len(diff), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
