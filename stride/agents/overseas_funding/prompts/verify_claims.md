## 작업
각 주장(claim)이 연결된 근거 문장으로 뒷받침되는지 판정하세요.
당신의 배경지식으로 판단하지 말고, 근거 문장만 보고 판단합니다.

- supported: 근거 문장이 주장과 같은 내용을 말한다 (표현이 달라도 됨)
- contradicted: 근거 문장이 주장과 다른 사실(다른 금액, 다른 국가, 다른 날짜, 다른 대상)을 말한다
- not_enough: 근거 문장만으로는 판단할 수 없다

특히 확인할 것:
- '계획'을 '확정'으로, '검토'를 '결정'으로 강하게 쓴 주장 → contradicted
- 근거에 없는 국가·금액·시기가 주장에 들어 있음 → not_enough

## 자료
<자료>
{claims_with_evidence}
</자료>
(형식: [CLAIM:id] 주장 / [근거 ID] 근거 문장 ...)

## 출력 형식 (JSON)
{ "results": [ { "finding_id": "...", "verdict": "supported|contradicted|not_enough",
                 "reason": "50자 이내" } ] }
