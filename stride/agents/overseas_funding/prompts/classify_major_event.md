## 작업
{corp_name}의 아래 공시 {n}건을 각각 분류하세요. 공시마다 items 1개를 만들고 evidence_id는 그 공시의 자료 id를 그대로 씁니다.
건너뛰지 않습니다. quote는 그 공시 자료의 문장만 씁니다. 금액을 출력하지 않습니다.

## 분류 기준
purpose_category:
- growth_investment: 해외 또는 국내에서 **새로운** 설비·법인·사업을 만들거나 인수하는 투자
- governance_restructuring: 이미 지배하고 있는 회사의 잔여 지분 매입, 중간지주사 정리,
  계열사 간 지분 이동 (새 사업이 늘지 않음)
- refinancing: 기존 차입금·사채 상환
- working_capital: 원재료 구매, 운영자금
- domestic: 국내 용도의 성장 투자
- unknown: 자료로 판단 불가

is_overseas: 자금이 최종적으로 해외 법인·해외 설비·해외 기업에 쓰이면 true.
  국내 기업 인수는 그 기업이 해외 사업을 하더라도 false.

fund_use_scopes: 조달 공시일 때만. 자료의 자금 사용 목적 칸(fdpp_fclt 시설, fdpp_bsninh 영업양수, fdpp_op 운영,
  fdpp_dtrp 채무상환, fdpp_ocsa 타법인 증권 취득, fdpp_etc 기타) 중 금액이 있는 칸마다 scope를 고릅니다.
  overseas: 그 칸 전체가 해외 용도라고 자료에 나옴 / domestic: 그 칸 전체가 국내 용도 /
  mixed: 국내와 해외가 섞임 / unknown: 자료로 판단 불가. 조달 공시가 아니면 빈 목록.

change_direction: 이 공시가 기존 계획의 정정·변경이면
  postponed(연기) / reduced(축소) / cancelled(취소·해제·철회) / expanded(확대) / none.
  related_project: 어떤 계획의 변경인지 자료에 나온 표현 그대로 (예: "OO국 생산공장 신설").

part_of_earlier: 취득 공시일 때, 이 공시가 같은 대상에 대한 이전 결정의 일부(같은 돈을 다시 공시한 것)이면 yes, 별도 차수·별도 금액임이 자료에 나오면 no, 자료로 알 수 없으면 unknown. 취득 공시가 아니면 unknown.

## 자료
{materials}
(형식: <자료 id="{evidence_id}" report_nm="..." rcept_dt="..."> 구조화 칸 + 원문 발췌 </자료>)

## 출력 형식 (JSON)
{
  "items": [
    {
      "evidence_id": "<자료 id>",
      "purpose_category": "...",
      "is_overseas": true | false,
      "fund_use_scopes": [{"slot": "fdpp_ocsa", "scope": "overseas"}],
      "target_country": "미국" | null,
      "target_entity": "취득 대상 회사·법인명" | null,
      "method": "new_plant|expansion|new_subsidiary|acquisition|equity_investment|jv|other" | null,
      "change_direction": "postponed|reduced|cancelled|expanded|none",
      "related_project": "..." | null,
      "part_of_earlier": "no|yes|unknown",
      "quote": "판단 근거 문장 그대로"
    }
  ]
}
