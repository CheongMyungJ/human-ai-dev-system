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
  ]
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

PROMPT_BY_PURPOSE = {
    "intent_authoring": INTENT_AUTHORING_PROMPT,
    "intent_gate_review": GATE_REVIEW_PROMPT,
    "limited_analysis": LIMITED_ANALYSIS_PROMPT,
}


def build(purpose: str, instruction: bytes) -> str:
    """목적별 지시문 + 원문."""
    template = PROMPT_BY_PURPOSE.get(purpose)
    if template is None:
        raise ValueError(f"프롬프트가 정의되지 않은 목적: {purpose}")
    return template + instruction.decode("utf-8", errors="replace")


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
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """AI가 쓴 초안을 여섯 항목·질문·성공 기준으로 바꾼다.

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
    return fields, questions, criteria


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
