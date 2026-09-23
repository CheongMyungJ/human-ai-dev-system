"""목적별 CLI 지시문 조립과 응답 해석.

**왜 Runner에 있는가.** 지시문은 본문이다. 제어부에 두면 의도·검토 본문이 제어부
코드와 로그를 지나가게 되고, 그것은 "서버에는 상태·요약·참조만" 이라는 경계를
어긴다(data-boundary-review 1절). 제어부는 목적과 원문 참조만 내려보내고, 그
참조로 읽은 본문과 지시문을 합치는 일은 원문을 가진 쪽이 한다.

응답 해석에서 지키는 것:

  AI가 비운 항목을 **채우지 않는다.** 빈 항목은 미정으로 남아 `undecided`/`none`
  이 된다(intent-artifacts 1절). 형식을 못 맞춘 응답은 추측으로 고치지 않고 실패로
  돌린다 — 지어낸 의도에 사람이 동의하게 만들지 않기 위해서다.

  AI 검토가 스스로 "통과"를 선언해도 그것은 참고값이다. 판정은 제어부가 발견
  사항에서 다시 계산한다(controller/gate.py).
"""

from __future__ import annotations

import json
from typing import Any

from domain import profiles
from domain.intent_doc import FIELD_ORDER
from domain.models import PreparationStage, WorkLevel
from domain.prep_doc import SECTION_LABEL, SECTION_ORDER, required_sections

#: 의미 검토가 필수로 올릴 수 있는 기준. controller/gate.py 의 목록과 같아야 한다.
#: 여기서 알려 주지 않으면 AI가 임의의 기준명을 만들어 내고 전부 권고로 내려간다.
REVIEW_CRITERIA = (
    "request_missing_or_contradictory",
    "assumption_presented_as_requirement",
    "unverifiable_success_criteria",
    "important_open_question_unlisted",
)

_FIELD_LIST = "\n".join(f"  - {f.value}" for f in FIELD_ORDER)

def _intent_field_list(profile: str | None, profile_version: str | None) -> str:
    """이 Case 가 채워야 하는 항목 목록(P3-R1).

    공통 여섯 항목 다음에 그 목적의 의미 항목이 온다. **Profile 이 없으면 여섯
    항목이다** — R1 이전 Case 의 형식이며, 여기서 현재 Profile 을 기본값으로 채우면
    문서 형식과 제어부의 필수 항목 검사가 어긋난다.
    """
    if profile is None or profile_version is None:
        return _FIELD_LIST
    definition = profiles.resolve(profile, profile_version)
    lines = [f"  - {f.value}" for f in FIELD_ORDER]
    lines.append(f"  (아래는 {profile} 업무에서 반드시 구별해 적을 내용이다)")
    for field in definition.semantic_fields:
        lines.append(f"  - {field.value} — {profiles.FIELD_LABEL[field.value]}")
    return "\n".join(lines)


def _intent_profile_note(profile: str | None, profile_version: str | None) -> str:
    """그 목적의 의미와 **초안에서 고정하지 않는 것.**

    뒤쪽이 중요하다. 목적에 맞지 않는 내용을 요구하면 AI 가 빈칸을 채우려고 없는
    사실을 만든다(case-profiles 2절 "사용자에게 빈칸을 채우게 하지 않는다").
    """
    if profile is None or profile_version is None:
        return ""
    d = profiles.resolve(profile, profile_version)
    note = (
        f"\n이 업무의 대표 목적은 **{profile}** 이다: {d.purpose}.\n"
        f"정상 완료의 의미: {d.completion_meaning}\n"
        f"이 초안에서 고정하지 않는 것: {d.not_fixed_in_draft}\n"
    )
    if d.completion is not None:
        note += _completion_contract_note(d.completion)
    return note


#: 목적 의무의 설명. 지시문과 화면이 같은 뜻을 쓰도록 정의의 이름표를 그대로 쓴다.
_OBLIGATION_LINES = "\n".join(
    f"     {name} — {label}" for name, label in profiles.OBLIGATION_LABEL.items()
)


def _completion_contract_note(contract: profiles.CompletionContract) -> str:
    """완료 계약이 있는 Profile(정의판 v2)의 **목적·의무·결론 요구** 지시(P4-03).

    세 가지를 따로 말하는 이유가 있다. 목적 선언이 없으면 "원인 확정과 수정" 중 한쪽이
    대표 Profile 에 묻히고, 기준의 의무가 없으면 보존 기준이 개선 기준에 섞이며, 결론
    요구가 없으면 판단 불가를 정상 결과로 볼지 알 수 없다(case-profiles 4·5절).

    **모르면 비운다.** 결론 요구를 요청이 말하지 않았으면 적지 않는다 — 시스템이 확정
    필수로 취급한다. 빈칸을 채우려고 요청에 없는 허용을 지어내면 그것이 완료 조건을
    느슨하게 만든다.
    """
    always = [r.obligation.value for r in contract.requirements if r.when_field_filled is None]
    conditional = [
        f"{r.obligation.value}({r.when_field_filled.value} 항목을 채웠을 때)"
        for r in contract.requirements
        if r.when_field_filled is not None
    ]
    required = ", ".join(always + conditional)
    return f"""
이 업무에는 **완료 계약**이 있다. 다음 셋을 JSON 에 함께 적는다.
  A. 최상위 "objectives": 이 요청이 **명시한** 목적 의무의 목록. 대표 목적
     ({contract.primary.value})은 적지 않아도 항상 요구된다. 요청이 다른 목적을 함께
     요구하면 — 예: 결함 수정과 함께 "원인을 확정해 달라" — 그 의무(cause)를 적는다.
     **요청에 없는 목적을 더하지 마라.** 없으면 빈 목록이다.
  B. criteria 의 기준마다 "obligation": 그 기준이 아래 의무 중 **무엇을 입증하는가.**
{_OBLIGATION_LINES}
     이 업무에서 완료하려면 다음 의무마다 기준이 하나 이상 있어야 한다: {required}.
     보존할 동작·계약·조건은 개선·목표 기준과 **별도 기준**(preservation)으로 쓴다 —
     개선 기준의 통과가 보존을 증명하지 않는다.
  C. cause·answer 기준에는 "conclusion_rule": 확정 결론이 필수면
     definitive_required, 합의한 조사를 마치고 근거·한계를 보고하면 판단 불가도 정상
     결과이면 bounded_report_allowed. **요청이 어느 쪽인지 말하지 않으면 적지 마라** —
     시스템이 확정 필수로 취급한다. 다른 의무의 기준에는 적지 않는다.
예: "objectives": ["cause"], "criteria": [{{"key": "C-01", "relates_to": "goal",
    "obligation": "cause", "conclusion_rule": "definitive_required", ...}}]
"""


INTENT_AUTHORING_PROMPT = f"""당신은 개발 요청을 읽고 **의도 초안**을 작성한다.
지금 이 실행에서는 코드를 바꾸지 말고 파일도 만들지 마라. 읽기만 하고 답을 JSON으로
출력한다.

**이 문단의 제약은 지금 이 실행에만 적용되는 규칙이며 의도가 아니다.** "코드를 바꾸지
않는다"를 의도 문서의 constraints 나 exclusions 에 적지 마라 — 개발하려는 기능은
코드를 바꾸는 일이고, 그렇게 적으면 목표와 정면으로 충돌하는 문서가 된다.

다음 항목을 **모두** 포함한다.
{{FIELD_LIST}}
{{PROFILE_NOTE}}

규칙:
1. 요청에 없는 내용을 지어내지 않는다. 모르는 항목은 text 를 빈 문자열로 두고
   비워 둔다. 시스템이 그것을 "미정"으로 기록한다.
2. 각 항목에 origin 을 붙인다.
   user_requirement(요청에 있음) / project_rule / observation(코드·환경에서 관찰) /
   ai_proposal(당신의 제안) / ai_assumption(당신의 가정).
   **가정을 user_requirement 로 적지 마라.** 그리고 반대도 마찬가지다 —
   고정 컨텍스트의 **질문 답변에서 나온 내용은 사람이 확정한 것**이므로
   `user_requirement` 이며 당신의 가정으로 적지 않는다. 사람이 답한 것을
   ai_assumption 으로 적으면 그 출처를 잃는다.
3. state 는 proposed 로 둔다. 사람이 확인하기 전에 user_confirmed 로 적지 않는다.
4. 사람의 결정이 필요한 미정 사항은 questions 에 넣는다. 질문을 숨기거나 임의로
   답하지 않는다. summary 는 목록에 보일 짧은 한 줄을 **따로** 쓴다(본문 발췌 금지).
5. decide_at 은 intent / design / plan 중 하나다. 지금 사람이 정해야 하면 intent 다.
6. **성공 기준 후보**를 criteria 에 쓴다. 기준마다 관련 의도 항목(relates_to),
   기대값(text), **확인 방법**(method)을 잇는다. 확인할 방법을 쓸 수 없는 기준은
   쓰지 마라 — 그런 기준은 검토에서 `unverifiable_success_criteria` 로 걸린다.
   미정 때문에 기대값을 확정할 수 없으면 그 사실을 text 에 적고 관련 질문을
   questions 에 넣는다. **수치를 모르면 지어내지 않는다.**
   summary 와 method_summary 는 목록용 짧은 한 줄을 따로 쓴다(본문 발췌 금지).
   기준이 하나도 없으면 criteria 를 빈 목록으로 둔다.
7. **작업 수준 판단**을 sizing 에 쓴다. 아래 일곱 축을 **모두** 채운다.
   intent_clarity(의도·성공 기준의 명확성) / change_scope(변경 범위·의존) /
   compatibility_and_data(호환성·데이터 생명주기) /
   permission_and_security(권한·보안·민감 데이터) / reversibility(가역성·실패 비용) /
   uncertainty(해법·환경의 불확실성) / verification_difficulty(검증 난도).
   축마다 weight 를 low / medium / high / insufficient_evidence 중에서 고르고,
   **judgement(현재 판단)를 반드시 쓴다** — 판단 없는 weight 는 숫자 점수와 같다.
   모르는 축은 low 가 아니라 **insufficient_evidence** 다. 모르는 것을 "영향 없음"으로
   적지 마라. unconfirmed 에 아직 확인할 것을 적고, evidence 에 근거를 적는다.
   recommended_level 은 simple / standard / deep 중 하나다. 국소적·가역적이고 기대값이
   분명하면 simple, 여러 인터페이스·데이터 동작의 설계가 필요하면 standard, 넓은 영향·
   어려운 복구·높은 불확실성 중 중요한 근거가 있으면 deep 이다.
   **높은 영향 축 하나를 낮은 축들의 평균으로 상쇄하지 마라.** 시스템이 축에서 수준을
   따로 도출하며, 당신의 제안이 그보다 낮으면 낮은 쪽을 쓰지 않는다.

출력은 이 형태의 JSON **하나만** 낸다. 설명 문장을 앞뒤에 붙이지 않는다.

{{
  "fields": {{
    "goal": {{"text": "...", "origin": "user_requirement"}},
    "expected_outcome": {{"text": "...", "origin": "ai_proposal"}},
    "scope": {{"text": "...", "origin": "..."}},
    "exclusions": {{"text": "...", "origin": "..."}},
    "constraints": {{"text": "...", "origin": "..."}},
    "open_questions": {{"text": "...", "origin": "..."}}
    (위 목록의 나머지 항목도 같은 형태로 **모두** 넣는다)
  }},
  "questions": [
    {{"key": "q1", "text": "질문 본문", "summary": "짧은 요약", "decide_at": "intent"}}
  ],
  "criteria": [
    {{"key": "C-01", "relates_to": "expected_outcome",
      "text": "무엇이 되면 충족인가", "method": "어떻게 확인하는가",
      "summary": "짧은 한 줄", "method_summary": "확인 방법 한 줄"}}
  ],
  "sizing": {{
    "recommended_level": "standard",
    "axes": [
      {{"axis": "intent_clarity", "weight": "medium",
        "evidence": "무엇을 보고 판단했는가", "judgement": "현재 판단 한 줄",
        "unconfirmed": "아직 확인할 것"}}
    ]
  }}
}}

--- 요청 원문 ---
"""

GATE_REVIEW_PROMPT = f"""당신은 **다른 세션이 작성한** 의도 초안을 검토한다.
초안을 고치지 말고, 질문에 답하지도 말고, 코드를 바꾸지 마라.
읽고 문제를 찾아 JSON으로 보고한다.

검토 항목(QG-01):
  - request_missing_or_contradictory: 요청에 있는 내용이 빠졌거나 서로 모순된다
  - assumption_presented_as_requirement: AI 가정이 확정된 요구처럼 적혀 있다
  - unverifiable_success_criteria: 기대 결과를 확인할 방법이 없다
  - important_open_question_unlisted: 사람이 정해야 할 중요한 미정이 질문에 없다

중요:
1. **미정 질문이 있는 것은 문제가 아니다.** 질문을 숨기거나 임의로 답한 것이 문제다.
2. 근거가 분명하면 certainty 를 confirmed, 의심 수준이면 suspected 로 적는다.
   의심을 확정으로 올리지 않는다.
2-1. **대조할 것은 고정 컨텍스트의 요청 원문과 질문 답변이다.** 거기 있는 내용은
   사용자의 요구이며 AI 의 가정이 아니다 — 요청에 적힌 것을
   `assumption_presented_as_requirement` 로 지적하지 마라. 요청 원문이 주어지지
   않았으면 **그 사실 자체를** `other` / `advisory` 로 적고, 대조하지 못한 것을
   확정 지적으로 올리지 마라.
3. 위 네 가지 밖의 지적은 criterion 을 other 로 두고 severity 를 advisory 로 한다.
4. summary 는 한 줄로 짧게 쓴다. 초안 본문을 옮겨 적지 않는다.
5. 문제가 없으면 findings 를 빈 목록으로 둔다.

출력은 이 형태의 JSON **하나만** 낸다.

{{
  "findings": [
    {{"criterion": "{REVIEW_CRITERIA[0]}", "severity": "required",
      "certainty": "confirmed", "target": "goal", "summary": "한 줄 요약"}}
  ]
}}

--- 검토할 의도 초안 ---
"""

QUALITY_GATE_REVIEW_PROMPT = """당신은 **다른 세션이 만든 결과**를 품질 게이트에서
검토한다. 대상을 고치거나 코드를 변경하지 말고, 고정 컨텍스트의 요청·성공 기준·대상
버전·실제 증거를 서로 대조해 발견 사항만 JSON으로 보고한다.

규칙:
1. 작성자의 '완료했다'는 주장 자체를 증거로 쓰지 않는다.
2. 기존 성공 기준의 식별자를 criterion에 정확히 적는다. 연결할 기준이 없는 의견은
   severity를 advisory로 둔다. 새 필수 요구를 만들지 않는다.
3. 실행하지 않은 검사, 읽지 못한 원문, 불완전한 증거를 통과로 추정하지 않는다.
4. certainty는 confirmed 또는 suspected다. summary는 200자 이내 한 줄이며 본문을
   옮겨 적지 않는다.
5. 문제가 없으면 findings를 빈 목록으로 둔다.

출력은 다음 JSON 하나만 낸다.

{
  "findings": [
    {"finding_key": "stable-key", "criterion": "기존-기준-id",
     "severity": "required", "certainty": "confirmed",
     "target": "검토 대상", "summary": "짧은 근거 요약"}
  ]
}

--- 검토할 게이트 대상 ---
"""

LIMITED_ANALYSIS_PROMPT = """당신은 동의된 의도에 따라 **읽기 전용 작업**을 수행한다.
코드를 바꾸거나 파일을 만들지 마라. 저장소를 읽고 결과를 글로 답한다.

--- 지시 원문 ---
"""

#: 고정 컨텍스트 참조의 역할별 설명. 지시문에 **무엇을 주는지**를 적어 준다.
CONTEXT_LABEL = {
    "previous_intent": "직전 의도 초안 (이 내용을 잃지 말고 고칠 곳만 고친다)",
    "agreed_intent": "사람이 동의한 의도 원문 (이 범위를 벗어나지 않는다)",
    "previous_design": "직전 설계안 (이 내용을 잃지 말고 고칠 곳만 고친다)",
    "current_design": "현재 설계안 (이 설계를 구현할 계획을 쓴다)",
    "previous_plan": "직전 개발계획 (이 내용을 잃지 말고 고칠 곳만 고친다)",
    # P3-04. 구현·검증·실험이 **따라야 할 것.** 이전 버전이 아니라 현재 계획이다.
    "current_plan": (
        "이 업무의 **개발계획** (이 계획이 정의한 작업만 한다."
        " 다른 작업은 다른 실행이 한다 — 여기서 미리 해 두지 않는다)"
    ),
    "feedback": "사람이 남긴 미해결 피드백",
    # P3-04. **사람이 그 질문에 답한 내용이다.** 피드백과 나누는 이유는 무엇에
    # 답한 것인지가 달라지기 때문이다 — 피드백은 초안 전체에 대한 의견이고
    # 이것은 초안이 물은 것에 대한 답이다.
    #
    # **출처를 함께 말한다.** 이 답에서 나온 내용은 사람이 확정한 것이며 AI 의
    # 가정이 아니다. 그 구별이 없으면 다시 쓰는 AI 가 사용자의 확정을
    # `ai_assumption` 으로 적고, QG-01 이 그것을 "근거 없는 가정을 확정된 사실로
    # 서술했다"로 잡는다 — 라이브에서 실제로 그렇게 됐다. 사람이 답한 것을 AI
    # 가정으로 적는 것은 **출처를 잃는 일**이다(FR-04).
    # P3-04. **검토자가 대조할 것.** QG-01 은 의도가 원래 요청과 맞는가를 보는데,
    # 그 요청을 주지 않으면 검토자는 요청에 있는 내용을 근거 없는 가정으로
    # 판정한다 — 라이브에서 실제로 그렇게 됐다.
    "original_request": (
        "이 초안이 따라야 했던 **요청 원문**"
        " (의도가 이 요청과 맞는지 대조한다. 여기 있는 내용은 사용자의 요구이며"
        " AI 의 가정이 아니다)"
    ),
    "question_answer": (
        "사람이 **미정 질문에 답한 내용**"
        " (이 답을 초안에 반영하고 그 항목을 다시 미정으로 두지 않는다."
        " 이 답에서 나온 내용의 origin 은 `user_requirement` 이며 `ai_assumption`"
        " 이 아니다 — 사람이 확정한 사실이다)"
    ),
}

CONTEXT_HEADER = """--- 고정 컨텍스트 ---
아래는 이 작업에 고정된 자료다. **처음부터 다시 쓰지 마라.** 이전 버전이 있으면 그
내용을 유지하고 요청받은 곳만 고친다. 읽지 못한 자료는 읽지 못했다고 표시돼 있으며,
그 내용을 추측해 채우지 마라.
"""


def build_context_block(items: list[dict[str, Any]]) -> str:
    """고정 컨텍스트를 지시문에 붙일 문자열로 만든다.

    **읽지 못한 참조를 조용히 빼지 않는다.** 빼면 AI는 그런 자료가 없었다고 생각하고
    처음부터 다시 쓴다 — P2-04에서 초안이 퇴화한 경로가 정확히 그것이다. 읽지 못한
    사실을 적어 두면 AI가 그 사실을 알고 쓴다.
    """
    if not items:
        return ""
    parts = [CONTEXT_HEADER]
    for item in items:
        label = CONTEXT_LABEL.get(item["role"], item["role"])
        head = f"[{label}] {item['artifact_id']}@{item['revision']}"
        if item.get("body") is None:
            parts.append(f"{head}\n(이 자료를 읽지 못했다. 내용을 추측하지 마라.)\n")
        else:
            body = item["body"].decode("utf-8", errors="replace")
            parts.append(f"{head}\n{body}\n")
    parts.append("--- 고정 컨텍스트 끝 ---\n")
    return "\n".join(parts)


def _stage_sections(stage: PreparationStage, level: WorkLevel) -> str:
    required = required_sections(stage, level)
    lines = []
    for section in SECTION_ORDER[stage]:
        mark = "필수" if section in required else "이 수준에서는 선택"
        lines.append(f"  - {section} ({SECTION_LABEL[section]}) — {mark}")
    return "\n".join(lines)


#: **내용이 없는 항목을 어떻게 비우는가.** 설계·계획·결합 기록이 같은 규칙을 받는다.
#:
#: 라이브에서 계획 실행 하나가 이 자리에서 실패했다. AI 가 `open_questions` 에
#: "없다. 계획 안에 미정인 것은 없다."를 적고 origin 을 `none` 으로 뒀고,
#: `prep_doc.compose` 가 그 조합을 거부한다(`section ... has text but origin 'none'`).
#: **거부가 맞다** — origin `none` 은 내용이 없다는 뜻이고, 내용이 있으면 origin 이
#: 출처를 말해야 한다. 틀린 것은 지시문이었다. 비우는 방법을 말하지 않으면 AI 는
#: 빈칸을 문장으로 채운다.
#:
#: 추측으로 고쳐 진행하지 않는다 — origin 을 `ai_proposal` 로 바꾸면 없는 출처를
#: 만드는 일이고, 본문을 지우면 사람이 쓴 것일지도 모르는 내용을 버리는 일이다.
EMPTY_SECTION_RULE = """**내용이 없는 항목은 text 를 빈 문자열로 두고 origin 을
`none` 으로 둔다.** "없다"·"해당 없음"·"미정 없음" 같은 문장을 text 에 적지 마라 —
origin `none` 은 내용이 없다는 뜻이고 내용이 있으면 origin 이 출처를 말해야 하므로,
그렇게 적으면 그 문서는 거부되고 이 실행은 실패한다.
"""

DESIGN_AUTHORING_PROMPT = """당신은 사람이 동의한 의도를 읽고 **설계안**을 작성한다.
지금 이 실행에서는 코드를 바꾸지 말고 파일도 만들지 마라. 저장소를 읽고 답을 JSON으로
출력한다. **이 제약은 이 실행의 규칙이며 설계의 내용이 아니다** — 설계안에 "코드를
바꾸지 않는다"고 적지 마라.

설계안이 답해야 하는 질문: 그 의도를 **어떤 구조와 동작으로** 실현할 것인가.

작업 수준은 {level} 이며 이 수준의 항목은 다음과 같다.
{sections}

규칙:
1. 동의된 의도의 범위를 벗어나는 기능을 추가하지 않는다. 범위를 바꿔야 한다고
   판단하면 그것을 questions 에 적는다 — **당신이 대신 정하지 않는다.**
2. 선택으로 표시된 항목도 쓸 내용이 있으면 쓴다. 쓸 내용이 없으면 text 를 빈
   문자열로 두고 비운다. 시스템이 그것을 "미정"으로 기록한다.
   {EMPTY_SECTION_RULE}
3. **필수 항목을 비우지 마라.** 비우면 이 설계로는 구현 실행이 배정되지 않는다.
4. 각 항목에 origin 을 붙인다: observation(코드·환경에서 관찰) / ai_proposal(제안) /
   ai_assumption(가정) / project_rule / user_requirement.
   **가정을 user_requirement 로 적지 마라.**
5. 사람이 정해야 하는 설계 결정은 questions 에 넣고 decide_at 을 design 으로 둔다.
   summary 는 목록에 보일 짧은 한 줄을 **따로** 쓴다(본문 발췌 금지).
   **질문이 남아 있는 것은 문제가 아니다.** 숨기거나 임의로 답하는 것이 문제다.
6. 수치·정책을 모르면 지어내지 않는다.

출력은 이 형태의 JSON **하나만** 낸다. 설명 문장을 앞뒤에 붙이지 않는다.

{{
  "sections": {{
    "change_summary": {{"text": "...", "origin": "ai_proposal"}}
  }},
  "questions": [
    {{"key": "d1", "text": "질문 본문", "summary": "짧은 요약", "decide_at": "design"}}
  ]
}}

--- 지시 원문 ---
"""

PLAN_AUTHORING_PROMPT = """당신은 동의된 의도와 **검토를 마친 설계안**을 읽고
**개발계획**을 작성한다. 지금 이 실행에서는 코드를 바꾸지 말고 파일도 만들지 마라.
저장소를 읽고 답을 JSON으로 출력한다. **이 제약은 이 실행의 규칙이며 계획의 내용이
아니다** — 계획의 작업은 당연히 코드를 바꾼다.

개발계획이 답해야 하는 질문: 무엇을 **어떤 순서로** 만들고 확인할 것인가.

작업 수준은 {level} 이며 이 수준의 항목은 다음과 같다.
{sections}

규칙:
1. 고정 컨텍스트의 **현재 설계안을 구현하는 계획**을 쓴다. 설계를 다시 하지 않는다.
   설계가 잘못됐다고 판단하면 그것을 questions 에 적는다.
2. 작업마다 목적·산출물·완료 조건을 쓴다. "구현한다" 같은 한 줄은 완료 조건이 아니다.
3. **검증 작업을 빠뜨리지 마라.** 무엇을 어떻게 확인하는지가 없으면 계획이 아니다.
4. **필수 항목을 비우지 마라.** 비우면 이 계획으로는 구현 실행이 배정되지 않는다.
5. 각 항목에 origin 을 붙인다(설계와 같은 목록).
   {EMPTY_SECTION_RULE}
6. 사람이 정해야 하는 것은 questions 에 넣고 decide_at 을 plan 으로 둔다.
7. 실행 환경·선행 조건에 없는 도구·자격증명을 가정하지 않는다.
8. **tasks 에 작업을 하나씩 정의한다.** 이것이 실제 실행 단위가 된다.
   - key 는 짧은 식별자(T1, T2 …)이고 depends_on 은 다른 작업의 key 다.
   - kind 는 investigation / implementation / verification / experiment / integration.
   - **검증 작업을 별도 Task 로 둔다.** 구현 Task 안에 묻으면 무엇이 확인
     작업인지 알 수 없다.
   - criteria 에는 이 작업이 대응하는 성공 기준의 key 와 relation
     (implements / verifies)을 적는다. **모르는 기준 key 를 지어내지 마라.**
   - 의존 관계에 **순환을 만들지 마라.** 순환이 있으면 계획 전체가 거부된다.
9. **각 작업의 *_summary 는 목록에 보일 짧은 한 줄을 따로 쓴다.** 본문 발췌가
   아니다 — 비우면 "요약 없음"으로 표시되고 사람이 원문을 열어야 한다.
10. **questions 의 blocks 에는 그 결정을 기다리는 작업의 key 를 적는다.**
   비워 두면 그 질문이 **모든 작업을 막는다** — 무엇을 막는지 모르기 때문이다.
   설계 단계에서 이월된 질문도 여기서 정의한 key 로 가리킬 수 있다.

{REPOSITORY_RULE}
출력 형태는 설계와 같고(sections / questions) tasks 가 더 있다.

{{
  "sections": {{"tasks": {{"text": "...", "origin": "ai_proposal"}}}},
  "questions": [
    {{"key": "p1", "text": "질문 본문", "summary": "짧은 요약",
     "decide_at": "plan", "blocks": ["T2"]}}
  ],
  "tasks": [
    {{"key": "T1", "kind": "investigation", "purpose": "...",
     "purpose_summary": "짧은 한 줄", "deliverable": "...",
     "deliverable_summary": "짧은 한 줄", "completion": "...",
     "completion_summary": "짧은 한 줄", "repository": "<저장소 이름>",
     "depends_on": [], "criteria": [{{"key": "C-01", "relation": "implements"}}]}}
  ]
}}

--- 지시 원문 ---
"""

# --------------------------------------------------------------------- P3-03

#: 제어부로 올라가는 요약의 길이 상한. `controller/schema.sql` 의 CHECK 와 같다.
MAX_SUMMARY = 200

FEATURE_IMPLEMENTATION_PROMPT = """당신은 검토를 마친 개발계획의 **작업 하나를 구현한다.**
지금 열려 있는 디렉터리는 이 업무 전용 작업공간(git worktree)이며 쓰기 권한이 있다.

규칙:
1. **이 작업의 범위만 고친다.** 계획에 없는 개선을 끼워 넣지 마라.
2. **커밋하지 마라.** 변경은 작업 트리에 남긴다. 무엇이 바뀌었는지는 시스템이
   기준 커밋과 대조해 확인한다.
3. 브랜치를 바꾸거나 만들지 마라. reset·checkout·stash 를 쓰지 마라.
4. **이 작업공간 밖의 파일을 고치지 마라.** 시스템은 경계 밖 변경을 감지해
   드러내며, 그것은 결함으로 보고된다.
5. 실제로 고친 것만 changed_summary 에 적는다. **하지 않은 일을 했다고 적지 마라** —
   시스템이 실제 변경을 따로 확인하고, 변경이 없으면 이 실행은 실패로 기록된다.
6. 막혀서 고칠 수 없으면 blocked 를 true 로 두고 이유를 적는다. 억지로 무언가를
   바꿔 완료로 보이게 만들지 마라. **막혔다고 적는 것이 지어낸 변경보다 낫다.**

출력은 이 형태의 JSON **하나만** 낸다. 설명 문장을 앞뒤에 붙이지 않는다.

{
  "changed_summary": "무엇을 고쳤는가 (짧은 한 줄)",
  "detail": "변경의 서술",
  "blocked": false,
  "blocked_reason": ""
}

--- 지시 원문 ---
"""

VERIFICATION_RUN_PROMPT = """당신은 이 업무의 **검증 작업**을 수행한다.
지금 열려 있는 디렉터리는 이 업무 전용 작업공간(git worktree)이며 빌드·테스트를
실행할 수 있다.

규칙:
1. **계획이 정한 확인 방법을 그대로 실행한다.** 통과시키려고 시험을 고치지 마라.
2. 실행한 명령을 commands 에 **실제로 실행한 그대로** 적고 종료 코드를 함께 적는다.
   **실행하지 않은 명령을 적지 마라** — 미실행을 실행으로 표시하는 것이다.
3. **테스트가 실패해도 그대로 보고한다.** 실패는 이 실행의 실패가 아니라 검증의
   결과다. 숨기거나 건너뛰지 마라.
4. 제품 코드를 고치지 마라. 수정은 별도 구현 작업이다.
5. 명령을 하나도 실행하지 못했으면 commands 를 빈 목록으로 두고 result_summary 에
   이유를 적는다. 시스템은 명령 기록이 없는 검증을 완료로 인정하지 않는다.

출력은 이 형태의 JSON **하나만** 낸다.

{
  "commands": [
    {"command": "실행한 명령", "summary": "짧은 한 줄", "exit_code": 0}
  ],
  "result_summary": "무엇을 확인했고 어떻게 끝났는가 (짧은 한 줄)",
  "detail": "결과의 서술"
}

--- 지시 원문 ---
"""


LOCAL_EXPERIMENT_PROMPT = """당신은 이 업무의 **허용된 로컬 실험**을 수행한다.
지금 열려 있는 디렉터리는 이 업무 전용 작업공간(git worktree)이며 재현·계측·테스트를
위해 임시로 고칠 수 있다.

규칙:
1. **원래 목적 안에서만 움직인다.** 이 업무는 조사·분석이며 제품 수정 요청이 아니다.
   재현·계측에 필요하지 않은 제품 변경을 만들지 마라.
2. **임시 변경과 결론의 근거를 구분해 적는다.** 무엇을 임시로 고쳤는지, 그 변경이
   결론의 근거인지 관측을 위한 장치인지 밝힌다.
3. 실행한 명령을 commands 에 **실제로 실행한 그대로** 적고 종료 코드를 함께 적는다.
   실행하지 않은 명령을 적지 마라.
4. **관측을 프로젝트 전체 규칙으로 일반화하지 마라.** 이 실험이 보여 준 것과 그것이
   일반적으로 참인지는 다른 문제다.
5. 운영 데이터·외부 자원·새 권한이 필요하면 **하지 말고** 그 사실을 적는다.
6. **끝나기 전에 임시 변경을 되돌려** 작업공간을 실험 전 상태로 둔다. 시스템이 실행
   전후의 작업공간을 대조해 남은 변경을 찾는다 — 남은 임시 변경은 제품 결과에 섞일 수
   있어 자동 완료를 막는다. 되돌리지 못했으면 그 사실과 이유를 temporary_changes 에
   적는다.

출력은 이 형태의 JSON **하나만** 낸다.

{
  "commands": [
    {"command": "실행한 명령", "summary": "짧은 한 줄", "exit_code": 0}
  ],
  "result_summary": "무엇을 관측했는가 (짧은 한 줄)",
  "temporary_changes": "임시로 고친 것과 되돌릴 방법 (짧은 한 줄)",
  "detail": "관측과 그 한계의 서술"
}

--- 지시 원문 ---
"""


PROMPT_BY_PURPOSE = {
    "intent_authoring": INTENT_AUTHORING_PROMPT,
    "intent_gate_review": GATE_REVIEW_PROMPT,
    "quality_gate_review": QUALITY_GATE_REVIEW_PROMPT,
    "limited_analysis": LIMITED_ANALYSIS_PROMPT,
    # P3-R4. 허용된 로컬 실험(D-66). `verification_run` 과 **다른 지시문**인 이유는
    # 규칙이 반대 방향이기 때문이다 — 검증은 "제품 코드를 고치지 마라"이고 실험은
    # "재현에 필요한 만큼 임시로 고쳐도 된다"이다. 하나로 합치면 둘 중 하나가 거짓이 된다.
    "local_experiment": LOCAL_EXPERIMENT_PROMPT,
    # P3-03. 이 둘이 생기면서 `has_prompt` 가 `feature_implementation` 에 True 를
    # 돌려준다 — P3-02까지 배정만 열리고 실행은 `failed` 로 끝나던 경로가 닫힌다.
    "feature_implementation": FEATURE_IMPLEMENTATION_PROMPT,
    "verification_run": VERIFICATION_RUN_PROMPT,
}

#: 수준에 따라 지시문이 달라지는 목적. 위 표에 넣지 않는 이유는 템플릿을 채워야
#: 하기 때문이다.
COMBINED_AUTHORING_PROMPT = """당신은 동의된 의도를 읽고 **하나의 결합 기록**을
작성한다. 지금 이 실행에서는 코드를 바꾸지 말고 파일도 만들지 마라. 저장소를 읽고
답을 JSON으로 출력한다.

이 업무는 **명확하고 저위험**으로 판정돼 설계안과 개발계획을 따로 쓰지 않는다.
대신 그 둘의 필요한 내용을 **하나의 최소 논리 기록**으로 합쳐 적는다.

작업 수준은 {level} 이며 이 수준의 항목은 다음과 같다.
{sections}

규칙:
1. **줄이는 것은 문서의 개수이지 내용이 아니다.** 변경 위치·동작·영향, 검증 방법,
   작업과 그 완료 조건은 그대로 있어야 한다.
2. **필수 항목을 비우지 마라.** 비우면 이 기록으로는 구현 실행이 배정되지 않는다.
3. 설계 결정으로 보일 만큼 큰 선택이 필요하면 그것을 questions 에 적는다.
   **결합 기록이라는 이유로 중요한 선택을 조용히 확정하지 마라.**
4. **tasks 에 작업을 하나씩 정의한다.** 형식과 규칙은 개발계획과 같다.
5. 각 항목에 origin 을 붙인다.
   {EMPTY_SECTION_RULE}
{REPOSITORY_RULE}
출력은 이 형태의 JSON **하나만** 낸다. **sections 는 객체이고 키는 위 항목 이름
그대로다** — 목록으로 내거나 이름을 바꾸면 시스템이 읽지 못해 이 실행은 실패한다.

{{
  "sections": {{
    "change_summary": {{"text": "...", "origin": "ai_proposal"}},
    "verifiability": {{"text": "...", "origin": "ai_proposal"}},
    "tasks": {{"text": "...", "origin": "ai_proposal"}},
    "verification": {{"text": "...", "origin": "ai_proposal"}}
  }},
  "questions": [
    {{"key": "q1", "text": "질문 본문", "summary": "짧은 요약",
     "decide_at": "plan", "blocks": ["T2"]}}
  ],
  "tasks": [
    {{"key": "T1", "kind": "implementation", "purpose": "...",
     "purpose_summary": "짧은 한 줄", "deliverable": "...",
     "deliverable_summary": "짧은 한 줄", "completion": "...",
     "completion_summary": "짧은 한 줄", "repository": "<저장소 이름>",
     "depends_on": [], "criteria": [{{"key": "C-01", "relation": "implements"}}]}}
  ]
}}

--- 지시 원문 ---
"""


STAGE_PROMPT = {
    "design_authoring": (PreparationStage.DESIGN, DESIGN_AUTHORING_PROMPT),
    "plan_authoring": (PreparationStage.PLAN, PLAN_AUTHORING_PROMPT),
    # P3-R4. 같은 목적(`plan_authoring`)이 **제어부가 정한 단계**에 따라 다른
    # 지시문을 받는다. 목적을 하나 더 만들지 않는 이유는 진입 조건표·권한표·역할표가
    # 전부 목적별이기 때문이다 — 값을 늘리면 그 표들이 함께 늘어나고, 한 곳만 빠지면
    # 새 목적이 조용히 조건 없는 실행이 된다.
    "combined": (PreparationStage.COMBINED, COMBINED_AUTHORING_PROMPT),
}



def _repository_rule(repositories: list[dict[str, Any]] | None) -> str:
    """계획이 Task 마다 저장소를 적게 하는 규칙(P3-04).

    **목록은 제어부가 준다.** Runner 가 저장소를 찾아 나서면 이 Case 가 고르지
    않은 저장소를 계획에 적게 되고, 그것은 허용을 넓히는 요구가 된다(D-38·D-63).

    **고를 것이 하나뿐이면 규칙을 넣지 않는다.** 고를 것이 없는데 고르라고 하면
    이름을 지어내고, 지어낸 이름은 해석되지 않아 그 작업이 막힌다. 저장소가
    하나인 Case 는 진입 검사도 이것을 묻지 않는다.
    """
    items = [r for r in (repositories or []) if r.get("name")]
    if len(items) < 2:
        return ""
    names = "\n".join(f"   - `{r['name']}`" for r in items)
    return (
        "\n11. **각 작업의 `repository` 에 그 작업이 코드를 바꾸는 저장소를 적는다.**\n"
        "   고를 수 있는 것은 아래 이름뿐이며 **그대로** 쓴다. 다른 이름을 적거나\n"
        "   비워 두면 그 작업으로는 구현·검증 실행이 배정되지 않는다.\n"
        f"{names}\n"
        "   한 작업은 **저장소 하나**만 바꾼다. 두 저장소를 바꿔야 하면 작업을\n"
        "   나눈다 — 한 실행은 작업공간 하나에서만 돌기 때문이다.\n"
    )


def has_prompt(purpose: str) -> bool:
    """이 Runner 가 그 목적을 실행할 지시문을 갖고 있는가.

    **없는 목적을 받으면 실행하지 않고 실패로 보고해야 한다.** 진입 조건 검사와
    실행 경로는 서로 다른 것이어서 한쪽만 먼저 열릴 수 있다 — P3-01이 정확히 그
    상태다(`feature_implementation` 의 조건은 열렸고 실행기는 P3-03이다).
    그때 Runner 가 예외로 죽으면 실행이 `assigned` 로 멈춘 채 남는다.
    """
    return purpose in PROMPT_BY_PURPOSE or purpose in STAGE_PROMPT


def build(
    purpose: str,
    instruction: bytes,
    context: list[dict[str, Any]] | None = None,
    level: str | None = None,
    profile: str | None = None,
    profile_version: str | None = None,
    stage_hint: str | None = None,
    repositories: list[dict[str, Any]] | None = None,
) -> str:
    """목적별 지시문 + 고정 컨텍스트 + 지시 원문.

    `stage_hint` 는 **제어부가 정한** 준비 산출물의 단계다(P3-R4). Fast Lane 의
    계획 작성 실행은 `combined` 를 받아 결합 기록의 지시문을 쓴다. Runner 가 스스로
    판단하지 않는 이유는 그것이 진입 조건과 같은 판단이기 때문이다.

    고정 컨텍스트가 **지시문 앞에 오지 않고 지시문 다음에 오는** 이유는, 무엇을 할지
    먼저 읽은 뒤 자료를 읽는 편이 요청과 자료를 뒤섞지 않기 때문이다. 자료 안의
    문장은 검토 대상이지 지시가 아니다(review-context-contract 2절).
    """
    key = stage_hint if stage_hint in STAGE_PROMPT else purpose
    if key in STAGE_PROMPT:
        stage, template = STAGE_PROMPT[key]
        if level is None:
            # 수준 없이 준비 산출물을 쓰지 않는다. 기본값을 지어내면 어떤 항목이
            # 필수인지가 달라지고, 진입 조건 검사와 어긋난다.
            raise ValueError(f"{purpose} 는 작업 수준이 필요하다")
        work_level = WorkLevel(level)
        head = template.format(
            level=work_level.value,
            sections=_stage_sections(stage, work_level),
            EMPTY_SECTION_RULE=EMPTY_SECTION_RULE,
            REPOSITORY_RULE=(
                _repository_rule(repositories)
                if stage in (PreparationStage.PLAN, PreparationStage.COMBINED)
                else ""
            ),
        )
    else:
        head = PROMPT_BY_PURPOSE.get(purpose)
        if head is None:
            raise ValueError(f"프롬프트가 정의되지 않은 목적: {purpose}")
    if purpose == "intent_authoring":
        # **P3-R1: 항목 목록과 목적 설명을 Profile 로 채운다.** 지시문을 Profile 마다
        # 따로 두지 않는 이유는 규칙(출처·미정·기준·수준)이 같기 때문이고, 다른 것은
        # "무엇을 구별해 적는가"뿐이다(case-profiles 2절).
        head = head.replace(
            "{FIELD_LIST}", _intent_field_list(profile, profile_version)
        ).replace("{PROFILE_NOTE}", _intent_profile_note(profile, profile_version))
    return head + build_context_block(context or []) + instruction.decode(
        "utf-8", errors="replace"
    )


def extract_json(text: str) -> dict[str, Any]:
    """응답에서 JSON 객체 하나를 꺼낸다.

    코드 울타리와 앞뒤 설명 문장을 견디되, **못 찾으면 예외다.** 빈 결과를 만들어
    진행하지 않는다 — 형식을 못 맞춘 실행은 실패로 남는 편이 낫다.
    """
    if not text or not text.strip():
        raise ValueError("빈 응답이다")
    fenced = text
    if "```" in fenced:
        chunks = fenced.split("```")
        for chunk in chunks:
            body = chunk[4:] if chunk.startswith("json") else chunk
            if body.strip().startswith("{"):
                fenced = body
                break
    start = fenced.find("{")
    if start < 0:
        raise ValueError("응답에 JSON 객체가 없다")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(fenced)):
        char = fenced[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(fenced[start : index + 1])
    raise ValueError("JSON 객체가 닫히지 않았다")


def parse_intent_draft(
    text: str,
    profile: str | None = None,
    profile_version: str | None = None,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any] | None,
    list[str] | None,
]:
    """AI가 쓴 초안을 필수 항목·질문·성공 기준·수준 판단·목적 선언으로 바꾼다.

    **목적·의무·결론 요구는 완료 계약이 있는 Profile 에서만 읽는다**(P4-03). 계약이
    없는 Case 의 응답에 그런 값이 있어도 버린다 — 그 Case 의 문서 형식에는 자리가
    없고, 받아 두면 v1 기준에 뜻 없는 값이 붙는다. 모르는 의무 이름은 **버리지 않는다**
    — 문서 작성(`compose`)이 거부해 실행이 실패한다. 조용히 지우면 그 기준이 대표
    의무로 도출되어 다른 목적이 사라진다.

    **비운 항목을 채우지 않는다.** 항목이 통째로 빠져 있어도 여기서 만들어 내지
    않고, `domain.intent_doc.compose` 가 `undecided`/`none` 으로 남긴다.

    성공 기준도 같다. **확인 방법이 없는 기준은 버린다** — 채워서 통과시키면
    QG-01이 볼 문제가 사라진다. 버린 사실은 기준 0건으로 드러난다.
    """
    doc = extract_json(text)
    raw_fields = doc.get("fields") or {}
    if not isinstance(raw_fields, dict):
        raise ValueError("fields 가 객체가 아니다")
    contract = profiles.completion_contract(profile, profile_version)

    fields: dict[str, Any] = {}
    # **P3-R1: 항목 목록은 Profile 이 정한다.** 빠진 항목은 여기서 만들어 내지 않고
    # 빈 항목으로 남겨 `compose` 가 `undecided` 로 적는다 — 그래야 QG-01 이 "무엇이
    # 비었는가"를 볼 수 있다.
    for name in profiles.field_order(profile, profile_version):
        given = raw_fields.get(name) or {}
        if isinstance(given, str):  # 문자열만 준 경우도 받아들이되 출처는 추정하지 않는다
            given = {"text": given}
        body = str(given.get("text") or "").strip()
        entry: dict[str, Any] = {"text": body}
        if body:
            # 출처를 주지 않았으면 ai_proposal 로 둔다. 이것은 **추정이 아니라
            # 사실**이다 — 이 문서를 쓴 것은 AI이고, 요청에 있었다는 근거는 없다.
            entry["origin"] = str(given.get("origin") or "ai_proposal")
            entry["state"] = "proposed"
        fields[name] = entry

    questions: list[dict[str, Any]] = []
    for index, raw in enumerate(doc.get("questions") or [], start=1):
        if not isinstance(raw, dict):
            continue
        text_body = str(raw.get("text") or "").strip()
        if not text_body:
            continue
        summary = " ".join(str(raw.get("summary") or "").split())[:200]
        if not summary:
            # 요약이 없으면 본문을 잘라 쓰지 않는다. 그러면 질문 본문 앞부분이
            # 제어부에 남는다(P2-02에서 고친 문제). 대신 자리표시 문구를 쓴다.
            summary = f"미정 질문 {index} (요약 없음 — 원문을 열람해 확인)"
        questions.append(
            {
                "key": str(raw.get("key") or f"q{index}")[:64],
                "text": text_body,
                "summary": summary,
                "decide_at": str(raw.get("decide_at") or "intent"),
                "blocks": [str(b) for b in (raw.get("blocks") or [])],
            }
        )

    criteria: list[dict[str, Any]] = []
    for index, raw in enumerate(doc.get("criteria") or [], start=1):
        if not isinstance(raw, dict):
            continue
        body = str(raw.get("text") or "").strip()
        method = str(raw.get("method") or "").strip()
        if not body or not method:
            # 확인 방법 없는 기준을 만들어 채우지 않는다. 빠뜨린 것은 빠뜨린 대로
            # 남고, 그 자체가 QG-01의 검토 대상이다.
            continue
        summary = " ".join(str(raw.get("summary") or "").split())[:200]
        method_summary = " ".join(str(raw.get("method_summary") or "").split())[:200]
        key = str(raw.get("key") or f"C-{index:02d}")[:64]
        if not summary:
            summary = f"성공 기준 {key} (요약 없음 — 원문을 열람해 확인)"
        if not method_summary:
            method_summary = f"확인 방법 {key} (요약 없음 — 원문을 열람해 확인)"
        item: dict[str, Any] = {
            "key": key,
            "relates_to": str(raw.get("relates_to") or "expected_outcome"),
            "text": body,
            "method": method,
            "summary": summary,
            "method_summary": method_summary,
        }
        if contract is not None:
            for name in ("obligation", "conclusion_rule"):
                value = str(raw.get(name) or "").strip()
                if value:
                    item[name] = value
        criteria.append(item)

    objectives: list[str] | None = None
    if contract is not None and doc.get("objectives") is not None:
        raw_objectives = doc.get("objectives")
        if not isinstance(raw_objectives, list):
            raise ValueError("objectives 가 목록이 아니다")
        objectives = [str(o).strip() for o in raw_objectives if str(o).strip()]
    return fields, questions, criteria, _parse_sizing(doc.get("sizing")), objectives


def _parse_sizing(raw: Any) -> dict[str, Any] | None:
    """수준 판단 블록을 읽는다.

    **없으면 `None` 이다.** 빈 축 목록으로 바꾸거나 `simple` 로 채우지 않는다 —
    판단하지 않은 것을 가장 얕은 준비로 읽으면 준비 없이 구현이 열린다.

    판단(`judgement`)이 없는 축은 **버린다.** 영향만 적힌 축은 근거 없는 점수이고,
    그것을 받아 두면 축이 채워진 것처럼 보인다. 버린 축은 `insufficient_evidence` 로
    드러난다 — `controller/sizing.py` 가 빠진 축을 그렇게 다룬다.
    """
    if not isinstance(raw, dict):
        return None
    axes: list[dict[str, Any]] = []
    for item in raw.get("axes") or []:
        if not isinstance(item, dict):
            continue
        judgement = " ".join(str(item.get("judgement") or "").split())
        if not item.get("axis") or not item.get("weight") or not judgement:
            continue
        axes.append(
            {
                "axis": str(item["axis"]),
                "weight": str(item["weight"]),
                "evidence": str(item.get("evidence") or ""),
                "judgement": judgement,
                "unconfirmed": " ".join(str(item.get("unconfirmed") or "").split()),
            }
        )
    level = str(raw.get("recommended_level") or "").strip()
    if not level:
        # 수준 제안이 없으면 축만으로 판단하게 둔다. 여기서 값을 고르지 않는다 —
        # 가장 얕은 수준을 넣으면 그것이 곧 AI의 조용한 하향이 된다.
        if not axes:
            return None
        level = "simple"
    return {"recommended_level": level, "axes": axes}


def parse_preparation(
    text: str, stage: PreparationStage
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """AI가 쓴 설계·계획을 항목·질문·Task 로 바꾼다.

    **비운 항목을 채우지 않는다.** 필수 항목을 비운 채 내면 그 산출물로는 구현
    실행이 배정되지 않으며, 그것이 올바른 결과다 — 채워서 통과시키면 진입 조건이
    볼 것이 없어진다.
    """
    doc = extract_json(text)
    raw = doc.get("sections") or {}
    if not isinstance(raw, dict):
        raise ValueError("sections 가 객체가 아니다")

    sections: dict[str, Any] = {}
    for section in SECTION_ORDER[PreparationStage(stage)]:
        given = raw.get(section) or {}
        if isinstance(given, str):
            given = {"text": given}
        body = str(given.get("text") or "").strip()
        entry: dict[str, Any] = {"text": body}
        if body:
            # 출처를 주지 않았으면 ai_proposal 이다. **추정이 아니라 사실이다** —
            # 이 문서를 쓴 것은 AI이고 요청에 있었다는 근거는 없다.
            entry["origin"] = str(given.get("origin") or "ai_proposal")
            entry["state"] = "proposed"
        sections[section] = entry

    default_stage = (
        "design" if PreparationStage(stage) is PreparationStage.DESIGN else "plan"
    )
    questions: list[dict[str, Any]] = []
    for index, item in enumerate(doc.get("questions") or [], start=1):
        if not isinstance(item, dict):
            continue
        body = str(item.get("text") or "").strip()
        if not body:
            continue
        summary = " ".join(str(item.get("summary") or "").split())[:200]
        if not summary:
            # 요약이 없으면 본문을 잘라 쓰지 않는다. 그러면 질문 본문 앞부분이
            # 제어부에 남는다(P2-02에서 고친 문제).
            summary = f"{default_stage} 질문 {index} (요약 없음 — 원문을 열람해 확인)"
        questions.append(
            {
                "key": str(item.get("key") or f"{default_stage[0]}{index}")[:64],
                "text": body,
                "summary": summary,
                "decide_at": str(item.get("decide_at") or default_stage),
                "blocks": [str(b) for b in (item.get("blocks") or [])],
            }
        )

    # Task 는 **계획 쪽 산출물에서만** 읽는다. 설계에도 받으면 두 산출물의 역할이
    # 섞이고 그래프의 출처가 둘이 된다(intent-artifacts 1절).
    #
    # **P3-R4: 결합 기록도 계획 쪽이다.** Fast Lane 에서 그 기록이 계획의 자리를
    # 대신하므로 Task 를 정의하는 것도 그쪽이다 — 읽지 않으면 그 Case 는 작업
    # 그래프가 없어 구현이 영원히 `work_graph_missing` 이 된다.
    tasks: list[dict[str, Any]] = []
    if PreparationStage(stage) in (PreparationStage.PLAN, PreparationStage.COMBINED):
        for index, item in enumerate(doc.get("tasks") or [], start=1):
            if not isinstance(item, dict):
                continue
            purpose = str(item.get("purpose") or "").strip()
            if not purpose:
                # 목적 없는 Task 는 만들지 않는다. 지어내면 계획이 무엇을
                # 빠뜨렸는지 사람 검토가 볼 수 없다.
                continue
            tasks.append(
                {
                    "key": str(item.get("key") or f"T{index}")[:64],
                    "kind": str(item.get("kind") or "implementation"),
                    "purpose": purpose,
                    # 요약이 없으면 **본문을 잘라 쓰지 않는다.** 빈 문자열로 두면
                    # 구조 보고가 자리표시 문구를 붙인다(P2-02에서 고친 문제).
                    "purpose_summary": " ".join(
                        str(item.get("purpose_summary") or "").split()
                    )[:200],
                    "deliverable": str(item.get("deliverable") or "").strip(),
                    "deliverable_summary": " ".join(
                        str(item.get("deliverable_summary") or "").split()
                    )[:200],
                    "completion": str(item.get("completion") or "").strip(),
                    "completion_summary": " ".join(
                        str(item.get("completion_summary") or "").split()
                    )[:200],
                    "relates_to": str(item.get("relates_to") or "").strip(),
                    # **적힌 그대로 올린다**(P3-04). 여기서 이름을 고치거나 비어
                    # 있을 때 채우면 계획이 무엇을 말했는지가 사라진다 — 해석은
                    # 제어부가 이 Case 의 선택 안에서 한다.
                    "repository": " ".join(str(item.get("repository") or "").split())[:100],
                    "depends_on": [
                        str(d) for d in (item.get("depends_on") or []) if str(d).strip()
                    ],
                    "criteria": [c for c in (item.get("criteria") or [])],
                    "origin": str(item.get("origin") or "ai_proposal"),
                }
            )

    return sections, questions, tasks


def parse_gate_review(text: str) -> list[dict[str, Any]]:
    """AI 검토 응답에서 발견 사항 목록을 꺼낸다.

    판정값은 읽지 않는다. 실행자가 스스로 통과를 선언하게 두지 않기 때문이다.
    """
    doc = extract_json(text)
    raw = doc.get("findings")
    if raw is None:
        raise ValueError("findings 가 없다")
    if not isinstance(raw, list):
        raise ValueError("findings 가 목록이 아니다")
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "criterion": str(item.get("criterion") or "other"),
                "severity": str(item.get("severity") or "advisory"),
                "certainty": str(item.get("certainty") or "suspected"),
                "target": str(item.get("target") or "document"),
                "summary": str(item.get("summary") or ""),
            }
        )
    return out


def parse_implementation(text: str) -> dict[str, Any]:
    """구현 실행의 응답을 읽는다.

    **`changed_summary` 를 변경의 증거로 쓰지 않는다.** 그것은 작성자의 주장이고,
    실제로 무엇이 바뀌었는지는 작업공간을 기준 커밋과 대조해 따로 확인한다
    (FR-09 "실제 실행 증거를 작성자의 완료 주장으로 대체하지 않는다").
    여기서 하는 일은 형식을 맞췄는지 보고 짧은 요약을 꺼내는 것뿐이다.

    **질문을 받지 않는 이유**는, 받아 두고 어디에도 연결하지 않으면 사람이
    물어본 적 없는 결정을 한 것이 되기 때문이다. 구현 중에 막히면 `blocked` 로
    보고하고 그 실행은 실패로 남는다 — 무엇이 막혔는지가 사람에게 보인다.
    """
    data = extract_json(text)
    summary = " ".join(str(data.get("changed_summary") or "").split())
    blocked = bool(data.get("blocked"))
    if not summary and not blocked:
        raise ValueError("구현 응답에 changed_summary 가 없다")
    return {
        "changed_summary": summary[:MAX_SUMMARY],
        "blocked": blocked,
        "blocked_reason": " ".join(str(data.get("blocked_reason") or "").split())[:MAX_SUMMARY],
    }


def parse_verification(text: str) -> dict[str, Any]:
    """검증 실행의 응답을 읽는다.

    **종료 코드가 0이 아닌 명령을 걸러내지 않는다.** "테스트가 실패했다"와
    "검증을 수행하지 못했다"는 다른 것이고, 전자는 기준 판정의 입력이다.
    걸러 내면 실패한 시험이 없었던 일이 된다.

    명령이 0건이면 0건으로 돌려준다 — 여기서 만들어 채우지 않는다. 그 경우
    호출자가 이 실행을 완료로 올리지 않는다.
    """
    data = extract_json(text)
    commands: list[dict[str, Any]] = []
    for raw in data.get("commands") or []:
        if not isinstance(raw, dict):
            continue
        summary = " ".join(str(raw.get("summary") or raw.get("command") or "").split())
        if not summary:
            continue
        exit_code = raw.get("exit_code")
        commands.append(
            {
                "seq": len(commands) + 1,
                "command_summary": summary[:MAX_SUMMARY],
                # **정수가 아니면 `None` 이다.** 모르는 종료 코드를 0으로 적으면
                # 실행하지 못한 명령이 성공한 것처럼 보인다.
                "exit_code": exit_code if isinstance(exit_code, int) else None,
                "duration_ms": raw.get("duration_ms")
                if isinstance(raw.get("duration_ms"), int)
                else None,
            }
        )
    return {
        "commands": commands,
        "result_summary": " ".join(str(data.get("result_summary") or "").split())[:MAX_SUMMARY],
    }


def parse_experiment(text: str) -> dict[str, Any]:
    """실험 실행의 응답을 읽는다(P3-R4·D-66).

    `parse_verification` 과 같은 명령 목록 위에 **임시 변경 기록** 하나를 더한다.
    그 한 줄이 "증거와 임시 변경을 구분한다"(D-66)의 자리이며, 비어 있으면 비어
    있는 채로 둔다 — 여기서 만들어 채우면 무엇이 임시였는지가 지어낸 값이 된다.
    """
    parsed = parse_verification(text)
    data = extract_json(text)
    temporary = " ".join(str(data.get("temporary_changes") or "").split())
    return {
        **parsed,
        "temporary_changes": temporary[:MAX_SUMMARY] or None,
    }
