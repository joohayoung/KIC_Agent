"""9단계 사람 검토용 보고서 샘플 3건 → tests/golden/_review_report.md. 사용: python tests/golden/_build_review_report.py (stride 폴더).
추출 노드는 같은 입력의 호출 기록을 재사용하고(입력이 다르면 실제 호출), 보고서 작성은 실제로 호출한다."""
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agents.overseas_funding.graph import run_company  # noqa: E402
from agents.overseas_funding.nodes.write_report import allowed_numbers, check_report  # noqa: E402
from core.schemas import Request  # noqa: E402
from tests.golden import llm_replay  # noqa: E402

G = Path(__file__).parent / "overseas_funding"
llm_replay.install()
db = str(Path(tempfile.mkdtemp()) / "review.db")


def run(cc, as_of):
    return run_company(Request(request_id="review", agent="overseas_funding", mode="single", corp_code=cc, as_of=date.fromisoformat(as_of), context={"db_path": db}))


def load(name):
    return json.loads((G / f"{name}.json").read_text(encoding="utf-8"))


samples = []
pos = load("G-POS_주")
samples.append(("G-POS (양성 기본형)", pos, pos["request"]["as_of"], run(pos["corp_code"], pos["request"]["as_of"]), "범위 안. 보고서를 LLM(opus)이 쓰고 출력 검사 4종을 통과해야 한다"))
change = load("G-CHANGE_1")
run(change["corp_code"], "2025-01-19")      # 같은 DB에서 앞 시점을 먼저 실행해 경보가 나오게 한다 (12.3)
samples.append(("G-CHANGE (계획 취소)", change, "2025-07-07", run(change["corp_code"], "2025-07-07"), "2025-01-19 실행 뒤 같은 DB에서 2025-07-07 실행. 범위 밖(취소)이라 코드 템플릿"))
none = load("G-NONE_H")
samples.append(("G-NONE (신호 없음)", none, none["request"]["as_of"], run(none["corp_code"], none["request"]["as_of"]), "범위 밖(신호 없음)이라 코드 템플릿, 보고서 LLM 호출 없음"))
L = ["# 해외진출 9단계 보고서 샘플 검토표", "", "보고서 본문은 에이전트 출력 그대로다. 출력 검사 4종: 각주 매핑, 자료에 없는 숫자, 내부 이름, 판단 표현 (개발문서 7.13 3).", ""]
for title, doc, as_of, r, note in samples:
    text = r.report_markdown or "(보고서 없음)"
    checks = ([e for e in check_report(text, 99, allowed_numbers(text)) if not e.startswith("각주 매핑 실패: 각주 없음")] or "통과") if r.extra.get("report_source") == "template" else "LLM 출력은 노드 안에서 검사 통과 후 채택"
    L += [f"## {title} — {doc['corp_name']}, 기준일 {as_of}", "", f"- 작성: {r.extra.get('report_source')} / {note}", f"- 상태: {next((c.value for c in r.classifications if c.key == 'ovs.signal_status'), '-')}, 범위: {next((c.rule for c in r.classifications if c.key == 'ovs.in_scope'), '-')}",
          f"- 경보: {[a.alert_type for a in r.alerts] or '없음'} / LLM 호출 {r.extra.get('llm_calls')} / errors {r.errors or '없음'}", f"- 템플릿 검사: {checks}", "", "---", "", text, "", "---", "",
          "검토 항목: ☐ 판단·평가 표현 없음 ☐ 숫자가 출처와 맞음 ☐ 각주가 출처와 맞음 ☐ 확인 필요가 빠짐없음 ☐ 읽기 쉬움", "", "메모:", "", ""]
(Path(__file__).parent / "_review_report.md").write_text("\n".join(L), encoding="utf-8")
print("작성", [(t, r.extra.get("report_source"), r.errors) for t, _, _, r, _ in samples])
