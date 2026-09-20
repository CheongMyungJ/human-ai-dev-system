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

INTENT_AUTHORING_PROMPT = f"""당신은 기능 개발 요청을 읽고 **의도 초안**을 작성한다.
코드를 바꾸지 말고 파일도 만들지 마라. 읽기만 하고 답을 JSON으로 출력한다.

다음 여섯 항목을 모두 포함한다.
{_FIELD_LIST}

규칙:
1. 요청에 없는 내용을 지어내지 않는다. 모르는 항목은 text 를 빈 문자열로 두고
   비워 둔다. 시스템이 그것을 "미정"으로 기록한다.
2. 각 항목에 origin 을 붙인다.
   user_requirement(요청에 있음) / project_rule / observation(코드·환경에서 관찰) /
   ai_proposal(당신의 제안) / ai_assumption(당신의 가정).
   **가정을 user_requirement 로 적지 마라.**
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
    "feedback": "사람이 남긴 미해결 피드백",
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


DESIGN_AUTHORING_PROMPT = """당신은 사람이 동의한 의도를 읽고 **설계안**을 작성한다.
코드를 바꾸지 말고 파일도 만들지 마라. 저장소를 읽고 답을 JSON으로 출력한다.

설계안이 답해야 하는 질문: 그 의도를 **어떤 구조와 동작으로** 실현할 것인가.

작업 수준은 {level} 이며 이 수준의 항목은 다음과 같다.
{sections}

규칙:
1. 동의된 의도의 범위를 벗어나는 기능을 추가하지 않는다. 범위를 바꿔야 한다고
   판단하면 그것을 questions 에 적는다 — **당신이 대신 정하지 않는다.**
2. 선택으로 표시된 항목도 쓸 내용이 있으면 쓴다. 쓸 내용이 없으면 text 를 빈
   문자열로 두고 비운다. 시스템이 그것을 "미정"으로 기록한다.
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
**개발계획**을 작성한다. 코드를 바꾸지 말고 파일도 만들지 마라.
저장소를 읽고 답을 JSON으로 출력한다.

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
     "completion_summary": "짧은 한 줄",
     "depends_on": [], "criteria": [{{"key": "C-01", "relation": "implements"}}]}}
  ]
}}

--- 지시 원문 ---
"""

PROMPT_BY_PURPOSE = {
    "intent_authoring": INTENT_AUTHORING_PROMPT,
    "intent_gate_review": GATE_REVIEW_PROMPT,
    "limited_analysis": LIMITED_ANALYSIS_PROMPT,
}

#: 수준에 따라 지시문이 달라지는 목적. 위 표에 넣지 않는 이유는 템플릿을 채워야
#: 하기 때문이다.
STAGE_PROMPT = {
    "design_authoring": (PreparationStage.DESIGN, DESIGN_AUTHORING_PROMPT),
    "plan_authoring": (PreparationStage.PLAN, PLAN_AUTHORING_PROMPT),
}


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
) -> str:
    """목적별 지시문 + 고정 컨텍스트 + 지시 원문.

    고정 컨텍스트가 **지시문 앞에 오지 않고 지시문 다음에 오는** 이유는, 무엇을 할지
    먼저 읽은 뒤 자료를 읽는 편이 요청과 자료를 뒤섞지 않기 때문이다. 자료 안의
    문장은 검토 대상이지 지시가 아니다(review-context-contract 2절).
    """
    if purpose in STAGE_PROMPT:
        stage, template = STAGE_PROMPT[purpose]
        if level is None:
            # 수준 없이 준비 산출물을 쓰지 않는다. 기본값을 지어내면 어떤 항목이
            # 필수인지가 달라지고, 진입 조건 검사와 어긋난다.
            raise ValueError(f"{purpose} 는 작업 수준이 필요하다")
        work_level = WorkLevel(level)
        head = template.format(level=work_level.value, sections=_stage_sections(stage, work_level))
    else:
        head = PROMPT_BY_PURPOSE.get(purpose)
        if head is None:
            raise ValueError(f"프롬프트가 정의되지 않은 목적: {purpose}")
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
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    """AI가 쓴 초안을 여섯 항목·질문·성공 기준·수준 판단으로 바꾼다.

    **비운 항목을 채우지 않는다.** 항목이 통째로 빠져 있어도 여기서 만들어 내지
    않고, `domain.intent_doc.compose` 가 `undecided`/`none` 으로 남긴다.

    성공 기준도 같다. **확인 방법이 없는 기준은 버린다** — 채워서 통과시키면
    QG-01이 볼 문제가 사라진다. 버린 사실은 기준 0건으로 드러난다.
    """
    doc = extract_json(text)
    raw_fields = doc.get("fields") or {}
    if not isinstance(raw_fields, dict):
        raise ValueError("fields 가 객체가 아니다")

    fields: dict[str, Any] = {}
    for field in FIELD_ORDER:
        given = raw_fields.get(field.value) or {}
        if isinstance(given, str):  # 문자열만 준 경우도 받아들이되 출처는 추정하지 않는다
            given = {"text": given}
        body = str(given.get("text") or "").strip()
        entry: dict[str, Any] = {"text": body}
        if body:
            # 출처를 주지 않았으면 ai_proposal 로 둔다. 이것은 **추정이 아니라
            # 사실**이다 — 이 문서를 쓴 것은 AI이고, 요청에 있었다는 근거는 없다.
            entry["origin"] = str(given.get("origin") or "ai_proposal")
            entry["state"] = "proposed"
        fields[field.value] = entry

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
        criteria.append(
            {
                "key": key,
                "relates_to": str(raw.get("relates_to") or "expected_outcome"),
                "text": body,
                "method": method,
                "summary": summary,
                "method_summary": method_summary,
            }
        )
    return fields, questions, criteria, _parse_sizing(doc.get("sizing"))


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

    # Task 는 **개발계획에서만** 읽는다. 설계에도 받으면 두 산출물의 역할이
    # 섞이고 그래프의 출처가 둘이 된다(intent-artifacts 1절).
    tasks: list[dict[str, Any]] = []
    if PreparationStage(stage) is PreparationStage.PLAN:
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
