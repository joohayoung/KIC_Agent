## 작업
아래 문장이 근거 인용문과 같은 사실을 말하는지 확인하세요. 문장이 맞는지 틀린지 세상 지식으로 판단하지 마세요.
근거 인용문에 없는 내용이 문장에 있으면 insufficient 입니다.

## 판단 기준
- supported: 문장의 사실(주체, 대상, 수치, 날짜, 행위)이 모두 인용문에 있다
- not_supported: 인용문과 다른 사실을 말한다
- insufficient: 인용문만으로는 확인할 수 없다

## 자료
<자료>
문장: {sentence}
근거: {quotes}
</자료>

## 출력 형식 (JSON)
{"verdict": "supported" | "not_supported" | "insufficient", "reason": "200자 이내"}
