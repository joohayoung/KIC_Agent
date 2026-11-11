"""해외진출 3단계 검수표: G-POS·G-CHANGE 기업 사업보고서 '사업의 내용' 추출과 신규 문단 표시 → tests/golden/_review_text.md."""
import json
import sys
from datetime import date
from pathlib import Path

G = Path(__file__).resolve().parent
sys.path.insert(0, str(G.parents[1]))
from agents.overseas_funding.nodes.collect_disclosures import report_section  # noqa: E402
from agents.overseas_funding.text.dart_sections import filter_overseas_paragraphs  # noqa: E402
from agents.overseas_funding.text.diff import explain_new  # noqa: E402
from core.clients.dart import get_client  # noqa: E402
from core.filings import select_reports  # noqa: E402

URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"
AS = date(2026, 11, 5)
MAX_NEW = 60
c = get_client()


def annual_reports(cc):
    filings = c.list_filings(AS, date(2022, 1, 1), AS, corp_code=cc, pblntf_ty="A")
    return {g["year"]: g["latest"] for g in select_reports(filings) if g["kind"] == "annual"}


def clip(s, n=260):
    return s if len(s) <= n else s[:n] + " …"


def section(name, cc, year):
    rep = annual_reports(cc)
    cur, prev = rep[year], rep[year - 1]
    cur_p, prev_p = report_section(c, cur["rcept_no"]), report_section(c, prev["rcept_no"])
    picked = filter_overseas_paragraphs(cur_p)
    info = explain_new(picked, prev_p)
    new = [p for p in picked if info[p.paragraph_id]["new"]]
    old = [p for p in picked if not info[p.paragraph_id]["new"]]
    out = [f"\n## {name}: {year} 사업보고서 vs {year - 1} 사업보고서\n",
           f"- [{year} 사업보고서]({URL.format(cur['rcept_no'])}) `{cur['rcept_no']}` / [{year - 1} 사업보고서]({URL.format(prev['rcept_no'])}) `{prev['rcept_no']}`\n",
           f"- 문단 수 {len(cur_p)} (직전 {len(prev_p)}), 해외 키워드 문단(앞뒤 포함) {len(picked)}, 신규 표시 {len(new)}\n",
           "\n### 1. 섹션 추출 확인\n",
           f"- [ ] 첫 문단이 II장 시작이 맞는지: `{clip(cur_p[0].text, 120)}` (소제목 {cur_p[0].subsection or '없음'})\n" if cur_p else "- [ ] 추출 문단 없음\n",
           f"- [ ] 끝 문단이 II장 끝이 맞는지: `{clip(cur_p[-1].text, 120)}` (소제목 {cur_p[-1].subsection or '없음'})\n" if cur_p else "",
           f"\n### 2. 신규 표시 문단 ({len(new)}건{f', 앞 {MAX_NEW}건만' if len(new) > MAX_NEW else ''}). 실제로 직전 보고서에 없는 내용인지\n"]
    for p in new[:MAX_NEW]:
        i = info[p.paragraph_id]
        why = "; ".join(x for x in (f"새 고유명사 {i['new_nouns'][:4]}" if i["new_nouns"] else "", f"새 실행어 {i['new_actions']}" if i["new_actions"] else "") if x)
        out.append(f"- [ ] `{p.paragraph_id}` 유사도 {i['similarity']}, {why}. 소제목 {p.subsection or '없음'}\n  - {clip(p.text)}\n")
    out.append("\n### 3. 기존 표시 문단 표본. 정말 직전 보고서에도 있는 내용인지 (신규 누락 확인)\n")
    step = max(1, len(old) // 8)
    for p in old[::step][:8]:
        out.append(f"- [ ] `{p.paragraph_id}` 유사도 {info[p.paragraph_id]['similarity']}\n  - {clip(p.text, 180)}\n")
    print(name, year, "문단", len(cur_p), "키워드", len(picked), "신규", len(new), "표현 변경", sum(v["label"] == "표현 변경" for v in info.values()), "소제목", sum(v["label"] == "소제목" for v in info.values()), flush=True)
    return "".join(out)


def doc(path):
    return json.loads((G / path).read_text(encoding="utf-8"))


targets = [(doc("overseas_funding/G-POS_MIXED.json"), 2025), (doc("overseas_funding/G-POS_보조.json"), 2025), (doc("overseas_funding/G-CHANGE_1.json"), 2024), (doc("overseas_funding/G-CHANGE_1.json"), 2025)]
lines = ["# 해외진출 3단계 검수표: '사업의 내용' 추출과 신규 문단\n",
         "\n값은 코드 결과다 (`text/dart_sections.py`, `text/diff.py`). 판정 기준 (개발문서 8.5 v0.18): 소제목은 제외, 국가·법인·지명이 직전 보고서에 없으면 신규, 유사도 0.80 미만이면서 가장 비슷한 직전 문단에 없던 실행어가 있으면 신규, 나머지 저유사도는 표현 변경. 1차 검수 결과는 `_review_text_검수결과.md`.\n",
         "\n회귀 테스트: `tests/golden/test_text_regression.py`.\n"]
for d, y in targets:
    lines.append(section(f"{d['case_type']} {d['corp_name']}", d["corp_code"], y))
(G / "_review_text.md").write_text("".join(lines), encoding="utf-8")
