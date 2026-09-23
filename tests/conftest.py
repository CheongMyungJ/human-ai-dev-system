"""시험 공통 설비.

각 시험은 자기만의 임시 데이터 경로를 쓴다. 개발용 `var/` 를 건드리지 않는다.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from controller.app import create_app  # noqa: E402
from controller.config import ControllerConfig  # noqa: E402
from domain.models import CapabilityState, Permission, RunOutcome  # noqa: E402
from runner.agent import RunnerAgent, local_executor_capabilities  # noqa: E402
from runner.cli_adapter import ExecutionOutput  # noqa: E402
from runner.client import ControllerClient  # noqa: E402
from runner.config import RunnerConfig  # noqa: E402

RUNNER_ID = "runner-test-1"

#: 시험이 쓰는 가짜 코딩 CLI의 식별자.
#:
#: 이름을 `codex` 로 두는 이유는 제어부의 진입 검사·권한 매핑이 도구 이름으로
#: 판단하기 때문이다. **실제 codex 를 부르지는 않는다** — 실행기는 아래 가짜이고,
#: 실제 CLI 실행은 라이브 검증에서만 한다(P1-02가 세운 구분).
FAKE_TOOL_ID = "codex"
FAKE_TOOL_MODE = "exec"

#: 기본 AI 초안 응답. 여섯 항목을 모두 채우고 출처를 구분해 적는다.
FAKE_DRAFT_RESPONSE = """여기 초안입니다.

```json
{
  "fields": {
    "goal": {"text": "로그 파일에서 오류 줄만 뽑는 기능", "origin": "user_requirement"},
    "expected_outcome": {"text": "ERROR 로 시작하는 줄만 출력된다", "origin": "ai_proposal"},
    "scope": {"text": "읽기 전용 조회", "origin": "ai_proposal"},
    "exclusions": {"text": "로그 회전과 보존 정책은 다루지 않는다", "origin": "ai_proposal"},
    "constraints": {"text": "Windows 로컬 파일만", "origin": "observation"},
    "open_questions": {"text": "대소문자 구분 여부가 미정", "origin": "ai_assumption"}
  },
  "questions": [],
  "criteria": [
    {"key": "C-01", "relates_to": "expected_outcome",
     "text": "ERROR 로 시작하는 줄만 출력되고 다른 줄은 나오지 않는다",
     "method": "ERROR 2줄과 INFO 2줄이 섞인 표본 파일로 출력 줄 수를 비교한다",
     "summary": "ERROR 줄만 출력된다", "method_summary": "표본 파일로 출력 줄 수 비교"},
    {"key": "C-02", "relates_to": "constraints",
     "text": "Windows 로컬 경로의 파일을 읽을 수 있다",
     "method": "로컬 경로 한 건으로 읽기를 확인한다",
     "summary": "Windows 로컬 경로를 읽는다", "method_summary": "로컬 경로 한 건 확인"}
  ],
  "sizing": {
    "recommended_level": "simple",
    "axes": [
      {"axis": "intent_clarity", "weight": "low",
       "evidence": "요청에 목표가 분명히 적혀 있다", "judgement": "의도가 분명하다",
       "unconfirmed": "대소문자 구분 여부"},
      {"axis": "change_scope", "weight": "low",
       "evidence": "한 파일을 읽는 조회", "judgement": "국소적이다", "unconfirmed": ""},
      {"axis": "compatibility_and_data", "weight": "low",
       "evidence": "저장 구조를 바꾸지 않는다", "judgement": "데이터 영향 없음",
       "unconfirmed": ""},
      {"axis": "permission_and_security", "weight": "low",
       "evidence": "읽기 전용", "judgement": "권한 경계를 바꾸지 않는다", "unconfirmed": ""},
      {"axis": "reversibility", "weight": "low",
       "evidence": "쓰지 않는다", "judgement": "되돌릴 것이 없다", "unconfirmed": ""},
      {"axis": "uncertainty", "weight": "low",
       "evidence": "표준 파일 읽기", "judgement": "해법이 분명하다", "unconfirmed": ""},
      {"axis": "verification_difficulty", "weight": "low",
       "evidence": "표본 파일로 확인 가능", "judgement": "확인이 쉽다", "unconfirmed": ""}
    ]
  }
}
```
"""

#: 성공 기준이 하나도 없는 초안. "기준 0건"이 0건으로 남는지 확인할 때 쓴다.
#: 시스템이 빈 자리를 채우지 않는다는 것을 확인하는 데 쓴다.
FAKE_DRAFT_WITHOUT_CRITERIA = """초안입니다.

```json
{
  "fields": {
    "goal": {"text": "로그 파일에서 오류 줄만 뽑는 기능", "origin": "user_requirement"},
    "expected_outcome": {"text": "ERROR 로 시작하는 줄만 출력된다", "origin": "ai_proposal"},
    "scope": {"text": "읽기 전용 조회", "origin": "ai_proposal"},
    "exclusions": {"text": "로그 회전과 보존 정책은 다루지 않는다", "origin": "ai_proposal"},
    "constraints": {"text": "Windows 로컬 파일만", "origin": "observation"},
    "open_questions": {"text": "대소문자 구분 여부가 미정", "origin": "ai_assumption"}
  },
  "questions": [],
  "criteria": []
}
```
"""

#: 확인 방법이 빠진 기준. 채워서 통과시키지 않고 **버린다**는 것을 확인할 때 쓴다.
FAKE_DRAFT_UNVERIFIABLE_CRITERION = FAKE_DRAFT_WITHOUT_CRITERIA.replace(
    '"criteria": []',
    '"criteria": [{"key": "C-01", "relates_to": "expected_outcome",'
    ' "text": "빠르게 동작한다", "summary": "빠르다", "method_summary": ""}]',
)

#: 기본 AI 검토 응답. 문제를 찾지 못한 경우.
FAKE_REVIEW_CLEAN = '{"findings": []}'

#: 사람이 화면에서 쓰는 초안의 기본 성공 기준. 확인 방법을 반드시 함께 쓴다 —
#: 확인 방법이 없는 기준은 기준이 아니라 바람이다(intent-artifacts 1절).
DEFAULT_CRITERIA = [
    {
        "key": "C-01",
        "relates_to": "expected_outcome",
        "text": "ERROR 로 시작하는 줄만 출력되고 다른 줄은 나오지 않는다",
        "method": "ERROR 2줄과 INFO 2줄이 섞인 표본으로 출력 줄 수를 비교한다",
        "summary": "ERROR 줄만 출력된다",
        "method_summary": "표본 파일로 출력 줄 수 비교",
    },
    {
        "key": "C-02",
        "relates_to": "constraints",
        "text": "Windows 로컬 경로의 파일을 읽을 수 있다",
        "method": "로컬 경로 한 건으로 읽기를 확인한다",
        "summary": "Windows 로컬 경로를 읽는다",
        "method_summary": "로컬 경로 한 건 확인",
    },
]


#: 사람이 화면에서 쓰는 초안의 기본 수준 판단. 일곱 축을 모두 채운다.
#: 축을 빼면 `controller/sizing.py` 가 근거 부족으로 표준 이상을 도출한다 —
#: 그 동작은 그것을 보는 시험에서 따로 확인한다.
DEFAULT_SIZING: dict[str, Any] = {
    "recommended_level": "simple",
    "axes": [
        {
            "axis": axis,
            "weight": "low",
            "evidence": f"{axis} 근거",
            "judgement": f"{axis} 판단",
            "unconfirmed": "",
        }
        for axis in (
            "intent_clarity",
            "change_scope",
            "compatibility_and_data",
            "permission_and_security",
            "reversibility",
            "uncertainty",
            "verification_difficulty",
        )
    ],
}

#: 설계·계획 작성의 가짜 응답을 만드는 도우미.
#:
#: **항목을 다 채운 것과 필수 항목을 비운 것**을 둘 다 만들 수 있어야 한다.
#: 비운 산출물이 진입 조건을 통과하지 않는 것이 P3-01의 성공 기준이기 때문이다.
def fake_preparation_response(
    stage: str,
    sections: dict[str, str],
    questions: list[dict[str, Any]] | None = None,
    tasks: list[dict[str, Any]] | None = None,
) -> str:
    import json as _json

    body = {
        "sections": {k: {"text": v, "origin": "ai_proposal"} for k, v in sections.items()},
        "questions": questions or [],
        "tasks": tasks or [],
    }
    return f"{stage} 산출물입니다.\n\n```json\n{_json.dumps(body, ensure_ascii=False)}\n```\n"


#: 계획이 정의하는 기본 Task 두 개(P3-02).
#:
#: **T2 가 T1 을 기다린다.** 의존이 없는 그래프만 시험하면 "선행 Task 가 끝나지
#: 않으면 배정되지 않는다"를 확인할 수 없다.
FAKE_TASKS: list[dict[str, Any]] = [
    {
        "key": "T1",
        "kind": "investigation",
        "purpose": "표본 파일의 오류 줄 형태를 확인한다",
        "purpose_summary": "표본 파일의 오류 줄 형태 확인",
        "deliverable": "확인한 형태를 적은 메모",
        "deliverable_summary": "형태 메모",
        "completion": "오류 줄의 접두사가 무엇인지 근거와 함께 적혔다",
        "completion_summary": "접두사가 근거와 함께 적혔다",
        "relates_to": "scope",
        "criteria": [{"key": "C-01", "relation": "implements"}],
    },
    {
        "key": "T2",
        "kind": "implementation",
        "purpose": "필터 함수를 구현한다",
        "purpose_summary": "필터 함수 구현",
        "deliverable": "reader.py 의 filter_errors",
        "deliverable_summary": "filter_errors 함수",
        "completion": "표본 파일에서 기대한 줄만 남는다",
        "completion_summary": "표본 파일에서 기대한 줄만 남는다",
        "relates_to": "goal",
        "depends_on": ["T1"],
        "criteria": [{"key": "C-01", "relation": "implements"}],
    },
]


#: 심층 수준까지 필수 항목을 모두 채운 설계 응답.
FAKE_DESIGN_FULL = fake_preparation_response(
    "설계",
    {
        "change_summary": "reader 모듈에 필터 함수를 더하고 CLI 진입점에서 호출한다",
        "requirement_mapping": "C-01 은 필터 함수, C-02 는 경로 처리로 대응한다",
        "interfaces_and_data": "filter_errors(lines) -> list[str]. 저장 구조는 바꾸지 않는다",
        "failure_handling": "파일이 없으면 오류를 그대로 올리고 빈 결과로 감추지 않는다",
        "alternatives": "정규식 대신 startswith 를 쓴다. 조건이 하나뿐이라 단순한 쪽을 택했다",
        "recovery": "읽기 전용이라 되돌릴 상태가 없다. 잘못된 출력은 재실행으로 확인한다",
        "verifiability": "표본 파일의 기대 줄 수와 실제 출력을 비교한다",
    },
)

#: 계획 산출물의 항목. **시험이 Task 만 바꿔 다시 조립할 수 있도록** 따로 둔다
#: (P3-04에서 저장소를 밝힌 Task 가 필요해졌다).
FAKE_PLAN_SECTIONS: dict[str, str] = {
    "tasks": "T1 필터 함수 구현(완료 조건: 단위 시험 통과), T2 진입점 연결",
    "verification": "표본 파일 시험 1건과 기존 회귀 시험을 돌린다",
    "dependencies": "T2 는 T1 을 기다린다",
    "integration_order": "T1 → T2 → 회귀 확인",
    "human_decision_points": "대소문자 구분 여부가 정해지면 기대값을 확정한다",
    "environment_prerequisites": "Python 3.12 와 저장소 checkout 만 필요하다",
    "experiments": "실험은 필요하지 않다. 표본 파일로 직접 확인한다",
    "failure_response": "시험이 실패하면 T1 로 돌아가고 통과를 주장하지 않는다",
}

#: 심층 수준까지 필수 항목을 모두 채운 계획 응답.
FAKE_PLAN_FULL = fake_preparation_response("계획", FAKE_PLAN_SECTIONS, tasks=FAKE_TASKS)


#: 구현 실행의 기본 응답. **파일을 실제로 바꾸지는 않는다** — 바꾸는 것은
#: `write_files` 를 설정한 시험이 한다. 응답과 실제 변경을 따로 두는 이유는
#: "고쳤다고 적었지만 아무 것도 바뀌지 않은" 경우를 시험할 수 있어야 하기 때문이다.
FAKE_IMPLEMENTATION_RESPONSE = """구현했습니다.

```json
{
  "changed_summary": "ERROR 로 시작하는 줄만 거르는 필터를 넣었다",
  "detail": "reader.py 에 필터 한 줄을 넣었다",
  "blocked": false,
  "blocked_reason": ""
}
```
"""

#: 검증 실행의 기본 응답. 명령 하나가 성공으로 끝난다.
FAKE_VERIFICATION_RESPONSE = """확인했습니다.

```json
{
  "commands": [
    {"command": "python -m pytest tests/test_reader.py", "summary": "reader 시험", "exit_code": 0}
  ],
  "result_summary": "시험 2건이 통과했다",
  "detail": "ERROR 2줄·INFO 2줄 표본으로 확인했다"
}
```
"""


class FakeCliExecutor:
    """시험용 가짜 코딩 CLI 실행기.

    **실제 CLI를 부르지 않는다.** 자동 시험은 결정적이어야 하고, 사용자 계정의
    외부 AI 호출에 의존해서는 안 된다. 실제 CLI 연결의 증거는 라이브 검증에서
    따로 만든다(p2/evidence/P2-03-results.md).

    계약(`execute` 의 인자와 반환값)은 `runner.cli_adapter.CliExecutor` 와 같다.
    그래야 이 자리에 실제 실행기를 넣어도 Runner 코드가 달라지지 않는다.
    """

    def __init__(self, effects_dir: Path) -> None:
        self.effects_dir = Path(effects_dir)
        self.effects_dir.mkdir(parents=True, exist_ok=True)
        self.draft_response = FAKE_DRAFT_RESPONSE
        self.review_response = FAKE_REVIEW_CLEAN
        self.analysis_response = "저장소를 읽고 확인했습니다. 변경한 것은 없습니다."
        #: UI-01. 논의 응답. 글이며 JSON 계약이 없다.
        self.discussion_response = "좋은 질문입니다. 두 가지 방향이 있습니다. 어느 쪽이 맞을까요?"
        self.design_response = FAKE_DESIGN_FULL
        self.plan_response = FAKE_PLAN_FULL
        self.combined_response = FAKE_PLAN_FULL
        self.implementation_response = FAKE_IMPLEMENTATION_RESPONSE
        self.verification_response = FAKE_VERIFICATION_RESPONSE
        #: 실행할 때 작업공간에 실제로 쓸 파일 {상대경로: 내용}.
        #: **비어 있으면 아무 것도 바꾸지 않는다** — 그 상태가 "고쳤다고 적었지만
        #: 바뀐 것이 없는" 실행이며 시스템이 그것을 완료로 올리지 않아야 한다.
        self.write_files: dict[str, str] = {}
        self.outcome = RunOutcome.COMPLETED
        #: 어댑터가 보고하는 사용량(P3-R3). 기본값은 **미보고**다 — 실제 어댑터도
        #: 항상 주지는 않으며, 시험 기본값이 "항상 보고함"이면 미제공 경로가 한
        #: 번도 돌지 않는다. `runner.cli_events` 가 만드는 모양을 그대로 쓴다.
        self.usage: Any = "not_reported"
        #: 잔류 활동 보고. `none` 이 아니면 소비가 끝났다는 근거가 없다.
        self.residual_activity = "unknown"
        #: UI-02. 잔류 값의 근거. 기본은 **보내지 않음**(UI-02 이전 계약)이다. 가짜는 Runner
        #: 프로세스 안에서 돌므로 `in_process` 를 줄 수 있다.
        self.residual_basis: str | None = None
        #: UI-02. 시험이 "CLI 가 도는 동안"을 만들 때 쓴다. 세우면 가짜 실행이 풀려날 때까지
        #: 기다린다(중단 신호가 오면 `cancelled` 로 끝난다).
        self.hold: Any = None
        #: 세션 식별자를 고정하면 "작성과 검토가 같은 세션"을 만들 수 있다.
        self.fixed_session_ref: str | None = None
        self.calls: list[dict[str, Any]] = []

    def _session_ref(self, run_id: str) -> str:
        return self.fixed_session_ref or f"fake-session-{run_id}"

    def _final_message(self, prompt: str) -> str:
        from runner import prompts as prompt_templates

        if prompt.startswith(prompt_templates.INTENT_AUTHORING_PROMPT[:40]):
            return self.draft_response
        if prompt.startswith(prompt_templates.QUALITY_GATE_REVIEW_PROMPT[:40]):
            return self.review_response
        if prompt.startswith(prompt_templates.GATE_REVIEW_PROMPT[:40]):
            return self.review_response
        if prompt.startswith(prompt_templates.DESIGN_AUTHORING_PROMPT[:40]):
            return self.design_response
        if prompt.startswith(prompt_templates.PLAN_AUTHORING_PROMPT[:40]):
            return self.plan_response
        if prompt.startswith(prompt_templates.COMBINED_AUTHORING_PROMPT[:40]):
            # P3-R4. Fast Lane 의 결합 기록. 계획과 같은 형식이므로 같은 응답을
            # 쓰되 **다른 지시문을 받았다는 사실**은 구별한다 — 시험이 결합 기록의
            # 내용을 따로 바꿀 수 있어야 한다.
            return self.combined_response
        if prompt.startswith(prompt_templates.FEATURE_IMPLEMENTATION_PROMPT[:40]):
            return self.implementation_response
        if prompt.startswith(prompt_templates.VERIFICATION_RUN_PROMPT[:40]):
            return self.verification_response
        if prompt.startswith(prompt_templates.DISCUSSION_REPLY_PROMPT[:40]):
            return self.discussion_response
        return self.analysis_response

    def count_effects(self, case_id: str) -> int:
        safe = case_id.replace("/", "_").replace("\\", "_")
        path = self.effects_dir / f"{safe}.log"
        if not path.exists():
            return 0
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

    def execute(
        self,
        run_id: str,
        case_id: str,
        prompt: str,
        tool_id: str,
        mode: str,
        permission: Permission,
        workspace: Path,
        raw_dir: Path | None = None,
        *,
        on_launch: Any = None,
        stop_event: Any = None,
        job_name: str | None = None,
    ) -> ExecutionOutput:
        # UI-02. 실제 실행기와 같은 순서로 **시작 기록을 먼저** 남긴다. 가짜는 Runner
        # 프로세스 안에서 돌므로 job 이 없다(`in_process`).
        if on_launch is not None:
            on_launch({"in_process": True, "fake": True})
        # 실제 실행기와 같이 부수효과를 한 줄 남긴다. 중복 실행 판정의 근거다.
        safe = case_id.replace("/", "_").replace("\\", "_")
        with open(self.effects_dir / f"{safe}.log", "a", encoding="utf-8") as fh:
            fh.write(f"fake\t{run_id}\n")
        self.calls.append(
            {
                "run_id": run_id,
                "tool_id": tool_id,
                "mode": mode,
                "permission": permission.value,
                "workspace": str(workspace),
                "prompt": prompt,
            }
        )
        # 요청받았으면 작업공간에 실제로 쓴다. **가짜 CLI 도 진짜 파일을 만든다** —
        # 실행 전후 대조가 실제 git 상태를 보기 때문에, 여기서 쓰지 않으면 변경
        # 감지 경로를 시험할 수 없다.
        for rel, body in self.write_files.items():
            target = Path(workspace) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")

        final = self._final_message(prompt)
        stopped = False
        if self.hold is not None:
            # "CLI 가 도는 동안". 풀려나거나 중단 신호가 올 때까지 기다린다.
            while not self.hold.wait(0.05):
                if stop_event is not None and stop_event.is_set():
                    stopped = True
                    break
        events = [
            {"seq": 1, "ts": "", "type": "run_started", "native_type": "fake.start", "raw_ref": None},
            {
                "seq": 2,
                "ts": "",
                "type": "session_identified",
                "native_type": "fake.session",
                "raw_ref": None,
            },
            {
                "seq": 3,
                "ts": "",
                "type": "assistant_message",
                "native_type": "fake.message",
                "raw_ref": None,
            },
            {"seq": 4, "ts": "", "type": "run_finished", "native_type": "fake.finish", "raw_ref": None},
        ]
        for event in events:
            event["ts"] = "2026-09-20T00:00:00.000000+00:00"
        return ExecutionOutput(
            events=events,
            output_body=f"fake run {run_id}\n{final}".encode("utf-8"),
            outcome=RunOutcome.CANCELLED if stopped else self.outcome,
            exit_code=0,
            usage=self.usage,
            residual_activity=self.residual_activity,
            residual_basis=self.residual_basis,
            stop_reason="stop_requested" if stopped else None,
            session_ref=self._session_ref(run_id),
            observed_tool_version=f"{tool_id}/fake-for-tests",
            final_message=final,
        )


def met_satisfaction_for(obligation: str | None) -> tuple[str | None, str | None]:
    """기준의 목적 의무에 맞는 **가장 흔한** 충족 방식과 결론(P4-03).

    시험이 "이 기준이 충족됐다"만 말하고 싶을 때 쓴다. 의무가 없으면(v1 기준) 아무
    것도 적지 않는다 — v1 기준은 예전 규칙 그대로다.
    """
    if obligation is None:
        return None, None
    if obligation in ("cause", "answer"):
        return "investigated", "determined"
    if obligation == "preservation":
        return "preserved", None
    return "changed_and_verified", None


def fake_capabilities() -> list[dict[str, Any]]:
    """가짜 CLI의 능력 보고.

    실제 설치 여부를 조회하지 않는다. 시험 결과가 이 PC에 무엇이 깔려 있는지에
    좌우되면 안 되기 때문이다. `source` 에 가짜임을 적어 실측과 섞이지 않게 한다.
    """
    source = "시험용 가짜 CLI (실제 실행 아님)"
    rows = local_executor_capabilities()
    for capability, state in (
        ("installed", CapabilityState.VERIFIED),
        ("coding_cli", CapabilityState.VERIFIED),
        (f"permission:{Permission.READ_ONLY.value}", CapabilityState.VERIFIED),
        (f"permission:{Permission.WORKSPACE_WRITE.value}", CapabilityState.VERIFIED),
        ("structured_events", CapabilityState.VERIFIED),
        ("session_identity", CapabilityState.VERIFIED),
    ):
        rows.append(
            {
                "tool_id": FAKE_TOOL_ID,
                "mode": FAKE_TOOL_MODE,
                "capability": capability,
                "state": state.value,
                "source": source,
            }
        )
    return rows


def _git(repo: Path, *args: str) -> str:
    """시험이 진짜 저장소를 만들 때 쓰는 git 호출.

    제품 코드의 `runner.workspace.git` 과 **따로 두는 이유**는, 시험이 제품
    함수를 써서 준비하면 그 함수의 결함이 준비 단계에서 가려지기 때문이다.
    """
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, timeout=60)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    return proc.stdout.decode("utf-8", errors="replace")


@dataclass
class Harness:
    """제어부(TestClient)와 Runner를 한 프로세스에서 연결한 시험 환경."""

    client: TestClient
    agent: RunnerAgent
    controller_config: ControllerConfig
    runner_config: RunnerConfig
    #: 이 시험의 임시 경로. P3-03의 작업공간 시험이 진짜 저장소를 여기에 만든다.
    tmp_path: Path

    # ------------------------------------------------------------ 준비 도우미

    def create_project(self, name: str = "demo") -> dict[str, Any]:
        response = self.client.post(
            "/api/projects",
            json={"name": name, "repo_path": "C:/tmp/demo", "default_tool_id": "codex"},
        )
        assert response.status_code == 201, response.text
        return response.json()

    def create_case(
        self,
        project_id: str,
        title: str = "첫 Case",
        kind: str | None = "feature",
        profile: str | None = None,
    ) -> dict[str, Any]:
        """Case를 만든다.

        `kind` 를 인자로 받는 이유는 P2-03에서 **유형에 따라 진입 조건이 다르기**
        때문이다(FR-29: 비기능 조사에 기능 개발 문서 전체를 일괄 요구하지 않는다).
        실행 배관 자체를 보는 시험은 기능 Case가 아닌 유형을 쓰고, 기능 Case의
        진입 조건은 `test_admission.py` 가 따로 본다.

        `profile` 은 P3-R1의 축이다. 주지 않으면 `kind` 에서 유도되며 그 사실이
        `profile_source` 에 남는다.
        """
        body: dict[str, Any] = {"title": title}
        if profile is not None:
            body["profile"] = profile
        else:
            body["kind"] = kind
        response = self.client.post(f"/api/projects/{project_id}/cases", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    def create_pre_r1_case(
        self, project_id: str, title: str = "R1 이전 Case", kind: str = "feature"
    ) -> dict[str, Any]:
        """**Profile 이 기록되지 않은 Case** 를 만든다(P3-R1 이행 대상의 모습).

        마이그레이션이 만드는 상태를 그대로 재현한다 — `case.profile` 이 NULL 이고
        `case_policy` 는 `migrated_unknown` 이다. 새 Case 경로로는 이 상태를 만들
        수 없으므로(기본값이 붙는다) DB에 직접 넣는다. 이 Case 가 새 정책·새 필수
        항목을 소급으로 받지 않는지 보는 것이 목적이다.
        """
        import sqlite3

        from controller.db import utc_now

        case_id = f"case-legacy{len(title):02d}{project_id[-6:]}"
        now = utc_now()
        conn = sqlite3.connect(self.controller_config.db_path)
        try:
            conn.execute(
                'INSERT INTO "case" (id, project_id, title, kind, status, created_at,'
                " updated_at) VALUES (?, ?, ?, ?, 'received', ?, ?)",
                (case_id, project_id, title, kind, now, now),
            )
            conn.execute(
                "INSERT INTO case_policy (id, case_id, revision, autonomy, autonomy_source,"
                " policy_version, set_by, reason_summary, state, created_at)"
                " VALUES (?, ?, 1, NULL, 'migrated_unknown', '0.6', 'migration', ?,"
                " 'current', ?)",
                (
                    f"pol-legacy{case_id[-8:]}",
                    case_id,
                    "R1 이전 Case. Autonomy 가 기록되지 않았다",
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return self.client.get(f"/api/cases/{case_id}").json()

    def submit_artifact(
        self, case_id: str, content: str, kind: str = "instruction", summary: str = "지시 원문"
    ) -> dict[str, Any]:
        """원문을 접수하고 Runner가 영속 저장할 때까지 진행한다.

        반환값은 저장 완료된 artifact 참조다.
        """
        response = self.client.post(
            f"/api/cases/{case_id}/artifacts",
            json={
                "kind": kind,
                "content": content,
                "summary": summary,
                "target_runner_id": RUNNER_ID,
            },
        )
        assert response.status_code == 202, response.text
        accepted = response.json()
        assert accepted["availability"] == "pending"
        self.agent.persist_pending_intakes()
        intake = self.client.get(f"/api/intakes/{accepted['intake_id']}").json()
        assert intake["state"] == "stored", intake
        return accepted

    def create_run(
        self,
        case_id: str,
        artifact_id: str,
        run_id: str,
        purpose: str = "limited_analysis",
        role: str = "author",
        tool_id: str = "local-echo",
        mode: str = "p2-01-local",
        permission: str = "read_only",
        task_id: str = "task-1",
        repository_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "run_id": run_id,
            "instruction_artifact_id": artifact_id,
            "purpose": purpose,
            "role": role,
            "tool_id": tool_id,
            "mode": mode,
            "permission": permission,
            "task_id": task_id,
        }
        if repository_id is not None:
            body["repository_id"] = repository_id
        response = self.client.post(f"/api/cases/{case_id}/runs", json=body)
        # 201 = 새로 만듦, 200 = 같은 run_id 의 재전송(만들지 않음)
        assert response.status_code in (200, 201), response.text
        return response.json()


    # ------------------------------------------------------ P3-02 도우미

    def complete_task(
        self,
        case_id: str,
        task_key: str,
        run_id: str | None = None,
        repository_id: str | None = None,
    ) -> dict[str, Any]:
        """그 Task 를 **실제 실행으로** 끝낸다.

        사람이 "끝났다"고 적는 경로를 만들지 않았으므로(그것은 실행 증거 없이
        의존을 푸는 문이다) 시험도 같은 경로를 쓴다 — 실행을 만들고 Runner 가
        수행해 결과가 `completed` 로 보고된다.
        """
        instruction = self.submit_artifact(
            case_id, f"{task_key} 를 조사해 주세요.", kind="instruction", summary=f"{task_key} 조사"
        )
        created = self.create_run(
            case_id,
            instruction["artifact_id"],
            run_id or f"run-{task_key.lower()}-1",
            purpose="limited_analysis",
            role="author",
            tool_id=FAKE_TOOL_ID,
            mode=FAKE_TOOL_MODE,
            task_id=task_key,
            repository_id=repository_id,
        )
        self.agent.poll_once()
        return created

    def work_graph(self, case_id: str) -> dict[str, Any]:
        response = self.client.get(f"/api/cases/{case_id}/work-graph")
        assert response.status_code == 200, response.text
        return response.json()

    def task_readiness(self, case_id: str, task_key: str) -> dict[str, Any]:
        return self.work_graph(case_id)["readiness"][task_key]

    def effect_count(self, case_id: str) -> int:
        return self.agent.executor.count_effects(case_id)

    def cli_effect_count(self, case_id: str) -> int:
        """가짜 CLI가 **실제로 몇 번 불렸는지.** 중복 실행 판정의 근거."""
        return self.agent.cli_executor.count_effects(case_id)

    # ------------------------------------------------------ P2-03 도우미

    def ai_draft(
        self,
        case_id: str,
        request_text: str = "로그에서 오류 줄만 뽑아 주세요.",
        run_id: str = "run-draft-1",
    ) -> dict[str, Any]:
        """AI에게 의도 초안을 작성시킨다.

        부품을 이어 붙인 것이다 — 요청 원문 접수 → `intent_authoring` 목적의 Run →
        Runner가 실행하고 **초안을 만들어 의도 버전으로 등록**한다.
        """
        instruction = self.submit_artifact(
            case_id, request_text, kind="instruction", summary="초안 작성 요청"
        )
        created = self.create_run(
            case_id,
            instruction["artifact_id"],
            run_id,
            purpose="intent_authoring",
            role="author",
            tool_id=FAKE_TOOL_ID,
            mode=FAKE_TOOL_MODE,
        )
        self.agent.poll_once()
        return created

    def ai_gate_review(
        self, case_id: str, intent: dict[str, Any], run_id: str = "run-review-1"
    ) -> Any:
        """작성과 **별도 세션**에서 QG-01 의미 검토를 실행한다."""
        response = self.client.post(
            f"/api/cases/{case_id}/runs",
            json={
                "run_id": run_id,
                "instruction_artifact_id": intent["artifact_id"],
                "instruction_artifact_rev": intent["artifact_rev"],
                "purpose": "intent_gate_review",
                "role": "reviewer",
                "tool_id": FAKE_TOOL_ID,
                "mode": FAKE_TOOL_MODE,
                "permission": "read_only",
            },
        )
        if response.status_code in (200, 201):
            self.agent.poll_once()
        return response

    def gate(self, case_id: str) -> dict[str, Any]:
        response = self.client.get(f"/api/cases/{case_id}/gate")
        assert response.status_code == 200, response.text
        return response.json()

    def admission_checks(self, case_id: str) -> list[dict[str, Any]]:
        return self.client.get(f"/api/cases/{case_id}/admission-checks").json()

    # ------------------------------------------------------ P2-04 도우미

    def result(self, case_id: str) -> dict[str, Any]:
        response = self.client.get(f"/api/cases/{case_id}/result")
        assert response.status_code == 200, response.text
        return response.json()

    def criteria(self, case_id: str) -> list[dict[str, Any]]:
        return self.result(case_id)["criteria"]

    def record_result(
        self,
        case_id: str,
        criterion_id: str,
        verdict: str,
        evidence_kind: str = "human_judgement",
        evidence_run_id: str | None = None,
        evidence_artifact_id: str | None = None,
        evidence_artifact_rev: int | None = None,
        summary: str = "확인함",
        recorded_by: str = "owner",
        satisfaction: str | None = None,
        conclusion: str | None = None,
    ):
        body: dict[str, Any] = {
            "verdict": verdict,
            "summary": summary,
            "recorded_by": recorded_by,
            "evidence_kind": evidence_kind,
            "evidence_run_id": evidence_run_id,
            "evidence_artifact_id": evidence_artifact_id,
            "evidence_artifact_rev": evidence_artifact_rev,
        }
        # **어떻게 충족했는가**(P3-R4). 주지 않으면 키를 넣지 않는다 — 미기록과
        # 명시적 `null` 을 API 계약에서 구별할 이유가 없다.
        if satisfaction is not None:
            body["satisfaction"] = satisfaction
        # **결론**(P4-03). 원인·조사 기준에만 붙는다.
        if conclusion is not None:
            body["conclusion"] = conclusion
        return self.client.post(
            f"/api/cases/{case_id}/criteria/{criterion_id}/result", json=body
        )

    def mark_all_criteria_met(self, case_id: str, run_id: str | None = None) -> None:
        """모든 기준을 충족으로 기록한다. 근거는 사람 판단 또는 실행 결과다.

        **P4-03: 기준의 목적 의무에 맞는 충족 방식을 함께 적는다.** Profile 정의 v2 의
        기준은 방식 없는 `met` 을 받지 않는다. 이 도우미가 만드는 상황은 "바꾸고
        확인했다"(제품 의무), "보존을 확인했다"(보존), "조사로 확정했다"(원인·조사)이며,
        v1 기준(의무 없음)에는 예전처럼 아무 방식도 적지 않는다.
        """
        for crit in self.criteria(case_id):
            satisfaction, conclusion = met_satisfaction_for(crit.get("obligation"))
            response = self.record_result(
                case_id,
                crit["id"],
                "met",
                evidence_kind="run_output" if run_id else "human_judgement",
                evidence_run_id=run_id,
                satisfaction=satisfaction,
                conclusion=conclusion,
            )
            assert response.status_code == 200, response.text

    def build_candidate(self, case_id: str) -> dict[str, Any]:
        response = self.client.post(f"/api/cases/{case_id}/completion-candidates")
        assert response.status_code == 201, response.text
        return response.json()["candidate"]

    def accept(
        self,
        case_id: str,
        candidate_id: str,
        statement: str = "이 결과를 인수합니다.",
        actor: str = "owner",
    ):
        return self.client.post(
            f"/api/cases/{case_id}/completion-candidates/{candidate_id}/acceptance",
            json={"actor": actor, "statement": statement},
        )

    def accept_exception(
        self,
        case_id: str,
        candidate_id: str,
        criterion_id: str,
        scope_summary: str = "이번 종료에만 적용",
        actor: str = "owner",
    ):
        return self.client.post(
            f"/api/cases/{case_id}/completion-candidates/{candidate_id}/exceptions",
            json={
                "actor": actor,
                "criterion_id": criterion_id,
                "scope_summary": scope_summary,
            },
        )

    # ------------------------------------------------------ P3-R4 도우미

    def confirm_checkpoint(
        self,
        case_id: str,
        checkpoint: str,
        subject_id: str,
        subject_type: str = "case",
        subject_hash: str | None = None,
        confirmed_by: str = "owner",
        note: str | None = None,
    ):
        """controlled 확인 지점을 사람이 확인한다(D-65)."""
        body = {
            "confirmed_by": confirmed_by,
            "explicit": True,
            "subject_type": subject_type,
            "subject_id": subject_id,
        }
        if subject_hash is not None:
            body["subject_hash"] = subject_hash
        if note is not None:
            body["note_summary"] = note
        response = self.client.post(
            f"/api/cases/{case_id}/controlled-checkpoints/{checkpoint}/confirmation",
            json=body,
        )
        assert response.status_code == 201, response.text
        return response.json()

    def register_combined(
        self,
        case_id: str,
        sections: dict[str, str] | None = None,
        tasks: list[dict[str, Any]] | None = None,
        run_id: str = "run-combined-1",
    ):
        """Fast Lane 의 결합 기록을 만든다(P3-R4).

        설계·계획 두 건 대신 **한 건**이다. 항목은 둘의 필수 항목을 합친 것이며
        새 이름을 만들지 않는다 — 나중에 일반 진행으로 전환할 때 옮겨 적을 대상이
        같아야 하기 때문이다.

        요청은 평범한 `plan_authoring` 이다. **어느 단계를 쓸지는 제어부가 정한다** —
        Fast Lane 이고 설계가 없으면 결합 기록이 된다(`_authoring_stage`).
        """
        harness_sections = sections if sections is not None else {
            "change_summary": "reader 모듈에 필터 함수를 더한다",
            "verifiability": "표본 파일의 기대 줄 수와 실제 출력을 비교한다",
            "tasks": "작업 목록은 tasks 에 있다",
            "verification": "표본 파일 시험 1건",
        }
        self.agent.cli_executor.combined_response = fake_preparation_response(
            "결합", harness_sections, tasks=(FAKE_TASKS if tasks is None else tasks)
        )
        instruction = self.submit_artifact(
            case_id, "요청대로 만들고 확인해 주세요.", kind="instruction", summary="결합 요청"
        )
        response = self.client.post(
            f"/api/cases/{case_id}/runs",
            json={
                "run_id": run_id,
                "instruction_artifact_id": instruction["artifact_id"],
                "purpose": "plan_authoring",
                "role": "author",
                "tool_id": FAKE_TOOL_ID,
                "mode": FAKE_TOOL_MODE,
                "permission": "read_only",
            },
        )
        if response.status_code in (200, 201):
            self.agent.poll_once()
        return response

    def run_experiment(
        self,
        case_id: str,
        instruction_artifact_id: str,
        run_id: str = "run-experiment-1",
        repository_id: str | None = None,
    ):
        """허용된 로컬 실험을 요청한다(D-66)."""
        body: dict[str, Any] = {
            "run_id": run_id,
            "instruction_artifact_id": instruction_artifact_id,
            "purpose": "local_experiment",
            "role": "author",
            "tool_id": FAKE_TOOL_ID,
            "mode": FAKE_TOOL_MODE,
            "permission": "workspace_write",
            "task_id": "task-1",
        }
        if repository_id is not None:
            body["repository_id"] = repository_id
        return self.client.post(f"/api/cases/{case_id}/runs", json=body)

    def light_conformance(self, case_id: str, intent_version_id: str):
        """가벼운 요청 정합성 확인을 기록한다(D-25)."""
        return self.client.post(
            f"/api/cases/{case_id}/conformance-checks/light",
            json={"intent_version_id": intent_version_id},
        )

    def conformance(self, case_id: str) -> dict[str, Any]:
        return self.client.get(f"/api/cases/{case_id}/conformance").json()

    def material_deltas(self, case_id: str) -> dict[str, Any]:
        return self.client.get(f"/api/cases/{case_id}/material-deltas").json()

    def set_completion_mode(self, case_id: str, mode: str, set_by: str = "owner"):
        return self.client.put(
            f"/api/cases/{case_id}/completion-policy",
            json={"mode": mode, "set_by": set_by},
        )

    def ready_for_acceptance(self, case_id: str, project_id: str) -> dict[str, Any]:
        """의도 동의까지 마친 Case 를 만든다. 반환값은 최신 의도 버전이다."""
        intent = self.latest_intent(case_id)
        self.read_intent_original(intent)
        response = self.agree(case_id, intent)
        assert response.status_code == 201, response.text
        return intent

    # ------------------------------------------------------ P2-02 도우미

    def submit_intent_draft(
        self,
        case_id: str,
        fields: dict[str, Any],
        questions: list[dict[str, Any]] | None = None,
        summary: str = "의도 초안",
        reflects_feedback: list[str] | None = None,
        not_reflected: dict[str, str] | None = None,
        persist: bool = True,
        criteria: list[dict[str, Any]] | None = None,
        sizing: dict[str, Any] | None = None,
        with_sizing: bool = True,
        objectives: list[str] | None = None,
    ) -> dict[str, Any]:
        """의도 초안을 제출하고(기본으로) Runner가 저장·구조 보고까지 하게 한다.

        `persist=False` 는 "아직 Runner가 저장하지 않은" 상태를 만들기 위한 것이다.
        `objectives` 는 요청이 명시한 목적 의무(P4-03)이며 주지 않으면 키를 넣지 않는다.
        """
        extra: dict[str, Any] = {}
        if objectives is not None:
            extra["objectives"] = objectives
        response = self.client.post(
            f"/api/cases/{case_id}/intent-drafts",
            json={
                **extra,
                "summary": summary,
                "target_runner_id": RUNNER_ID,
                "fields": fields,
                "questions": questions or [],
                # 기본으로 기준 두 건을 붙인다. 기준 0건의 동작은 그것을 보는
                # 시험에서 명시적으로 `criteria=[]` 를 준다.
                "criteria": DEFAULT_CRITERIA if criteria is None else criteria,
                # 기본으로 일곱 축을 채운 수준 판단을 붙인다. 판단이 **없는** 상태의
                # 동작은 `with_sizing=False` 로 그것을 보는 시험에서 확인한다.
                "sizing": (
                    (sizing if sizing is not None else DEFAULT_SIZING) if with_sizing else None
                ),
                "reflects_feedback": reflects_feedback or [],
                "not_reflected": not_reflected or {},
            },
        )
        assert response.status_code == 202, response.text
        accepted = response.json()
        if persist:
            self.agent.persist_pending_intakes()
        return accepted

    def submit_feedback(
        self,
        case_id: str,
        intent_version_id: str,
        content: str,
        summary: str = "피드백",
        persist: bool = True,
    ) -> dict[str, Any]:
        response = self.client.post(
            f"/api/cases/{case_id}/feedback",
            json={
                "target_intent_version_id": intent_version_id,
                "content": content,
                "summary": summary,
                "target_runner_id": RUNNER_ID,
            },
        )
        assert response.status_code == 202, response.text
        accepted = response.json()
        if persist:
            self.agent.persist_pending_intakes()
        return accepted

    def read_original(self, artifact_id: str, revision: int = 1, serve: bool = True):
        """원문 열람 한 바퀴. (요청 상태, 본문 또는 None) 을 돌려준다."""
        created = self.client.post(
            f"/api/artifacts/{artifact_id}/{revision}/read-requests", json={}
        )
        assert created.status_code == 201, created.text
        request_id = created.json()["id"]
        if serve:
            self.agent.serve_read_requests()
        response = self.client.get(f"/api/read-requests/{request_id}").json()
        return response["request"], response["content"]

    def read_intent_original(self, intent: dict[str, Any]) -> str:
        """의도 원문을 실제로 받아 본다. 이 전달이 열람 기록을 만든다."""
        _request, content = self.read_original(intent["artifact_id"], intent["artifact_rev"])
        assert content is not None, "원문이 전달되지 않았다"
        return content

    def intent_state(self, case_id: str) -> dict[str, Any]:
        response = self.client.get(f"/api/cases/{case_id}/intent-state")
        assert response.status_code == 200, response.text
        return response.json()

    def latest_intent(self, case_id: str) -> dict[str, Any]:
        state = self.intent_state(case_id)
        assert state["latest_intent_version"] is not None
        return state["latest_intent_version"]

    # ------------------------------------------------------ P3-01 도우미

    def preparation(self, case_id: str) -> dict[str, Any]:
        response = self.client.get(f"/api/cases/{case_id}/preparation")
        assert response.status_code == 200, response.text
        return response.json()

    def ai_prepare(
        self,
        case_id: str,
        stage: str,
        run_id: str | None = None,
        request_text: str = "설계를 작성해 주세요.",
        repository_id: str | None = None,
    ) -> Any:
        """AI에게 설계 또는 개발계획을 작성시킨다.

        `ai_draft` 와 같은 구조다 — 요청 원문 접수 → 목적별 Run → Runner가 실행하고
        산출물을 만들어 등록한다. 진입 조건이 막으면 그 응답을 그대로 돌려준다.
        """
        instruction = self.submit_artifact(
            case_id, request_text, kind="instruction", summary=f"{stage} 작성 요청"
        )
        body: dict[str, Any] = {
            "run_id": run_id or f"run-{stage}-1",
            "instruction_artifact_id": instruction["artifact_id"],
            "purpose": f"{stage}_authoring",
            "role": "author",
            "tool_id": FAKE_TOOL_ID,
            "mode": FAKE_TOOL_MODE,
            "permission": "read_only",
        }
        # **작업공간이 둘 이상이면 읽기 전용 실행도 대상을 밝혀야 한다**(P3-R2).
        # 밝히지 않으면 배정이 조용히 사용자의 원래 저장소로 떨어지고, 설계를 쓰는
        # 실행이 이 Case 의 작업이 아니라 사용자의 다른 작업을 읽는다.
        if repository_id is not None:
            body["repository_id"] = repository_id
        response = self.client.post(f"/api/cases/{case_id}/runs", json=body)
        if response.status_code in (200, 201):
            self.agent.poll_once()
        return response

    def set_stage_mode(self, case_id: str, stage: str, mode: str, reason: str = "시험용 설정"):
        return self.client.put(
            f"/api/cases/{case_id}/stage-review-settings/{stage}",
            json={"mode": mode, "reason": reason, "set_by": "owner"},
        )

    def review_stage(self, case_id: str, stage: str, reviewed: bool = True, note: str = "검토함"):
        return self.client.post(
            f"/api/cases/{case_id}/stage-reviews/{stage}",
            json={"reviewed": reviewed, "note": note, "actor": "owner"},
        )

    def auto_proceed(self, case_id: str, stage: str):
        return self.client.post(f"/api/cases/{case_id}/stage-auto-proceed/{stage}", json={})

    def adjust_level(
        self,
        case_id: str,
        level: str,
        reason: str = "사람이 판단해 조정",
        residual_risk: str = "남는 위험 없음이 아니라 확인 필요",
    ):
        return self.client.post(
            f"/api/cases/{case_id}/sizing-adjustment",
            json={
                "level": level,
                "reason": reason,
                "residual_risk": residual_risk,
                "actor": "owner",
            },
        )

    def request_implementation(
        self,
        case_id: str,
        run_id: str = "run-impl-1",
        permission: str = "read_only",
        task_id: str = "T2",
        repository_id: str | None = None,
    ):
        """기능 구현 실행을 요청한다. 허용/거부 응답을 그대로 돌려준다.

        기본 `task_id` 가 `T2` 인 것은 `FAKE_TASKS` 의 구현 Task 이기 때문이다.
        P3-02부터 그래프가 있는 Case 는 그래프의 Task 키로 요청해야 한다.
        """
        instruction = self.submit_artifact(
            case_id, "계획대로 구현해 주세요.", kind="instruction", summary="구현 요청"
        )
        body: dict[str, Any] = {
            "run_id": run_id,
            "instruction_artifact_id": instruction["artifact_id"],
            "purpose": "feature_implementation",
            "role": "author",
            "tool_id": FAKE_TOOL_ID,
            "mode": FAKE_TOOL_MODE,
            "permission": permission,
            "task_id": task_id,
        }
        # **어느 저장소의 작업공간에서 도는가**(P3-R2). 주지 않으면 키 자체를 넣지
        # 않는다 — 명시적 `null` 과 미기록을 API 계약에서 구별할 이유가 없다.
        if repository_id is not None:
            body["repository_id"] = repository_id
        return self.client.post(f"/api/cases/{case_id}/runs", json=body)

    def open_questions(self, case_id: str) -> list[dict[str, Any]]:
        """최신 의도 버전에 붙은 질문 목록. 이월 질문도 여기 들어 있다.

        **목록 순서에 기대지 않는다.** `intent_versions` 는 revision 내림차순이므로
        `[-1]` 은 가장 오래된 버전이다. 최신 버전은 `intent_state` 가 알려 준다.
        """
        latest_id = self.latest_intent(case_id)["id"]
        case = self.client.get(f"/api/cases/{case_id}").json()
        version = next(v for v in case["intent_versions"] if v["id"] == latest_id)
        return version["questions"]

    def context_refs(self, run_id: str) -> list[dict[str, Any]]:
        response = self.client.get(f"/api/runs/{run_id}/context-refs")
        assert response.status_code == 200, response.text
        return response.json()

    def agree(
        self,
        case_id: str,
        intent: dict[str, Any],
        content_hash: str | None = None,
        agree: bool = True,
        statement: str = "이 버전의 의도에 동의합니다.",
    ):
        return self.client.post(
            f"/api/cases/{case_id}/intent-versions/{intent['id']}/agreement",
            json={
                "agree": agree,
                "statement": statement,
                "content_hash": content_hash or intent["content_hash"],
                "actor": "owner",
            },
        )


    # ------------------------------------------------------ P3-03 도우미

    def create_git_project(
        self, name: str = "demo", dirty: bool = False
    ) -> tuple[dict[str, Any], Path]:
        """**실제 git 저장소**를 만들고 그것을 가리키는 프로젝트를 만든다.

        진짜 저장소를 쓰는 이유는 작업공간 시험이 확인하려는 것이 git 의 실제
        동작이기 때문이다 — worktree 가 사용자의 원래 트리를 건드리지 않는다는
        것은 흉내로는 확인할 수 없다.

        `dirty=True` 면 **사용자의 미커밋 변경**을 남긴다. 시스템이 그것을 정리하지
        않는다는 것이 P3-03의 핵심 기준이다(FR-08·FR-26).
        """
        repo = self.tmp_path / f"repo-{name}"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-b", "main")
        _git(repo, "config", "user.email", "test@example.invalid")
        _git(repo, "config", "user.name", "test")
        (repo / "reader.py").write_text("def read(path):\n    return open(path).read()\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "base")
        if dirty:
            # 사용자가 손대던 것. 커밋하지도 지우지도 않는다.
            (repo / "reader.py").write_text(
                "def read(path):\n    return open(path).read()  # 사용자가 쓰던 중\n",
                encoding="utf-8",
            )
            (repo / "scratch.txt").write_text("사용자의 미추적 메모\n", encoding="utf-8")
        response = self.client.post(
            "/api/projects",
            json={"name": name, "repo_path": str(repo), "default_tool_id": "codex"},
        )
        assert response.status_code == 201, response.text
        return response.json(), repo

    def request_workspace(
        self, case_id: str, base_ref: str = "HEAD", repository_id: str | None = None
    ):
        body: dict[str, Any] = {"base_ref": base_ref}
        if repository_id is not None:
            body["repository_id"] = repository_id
        return self.client.post(f"/api/cases/{case_id}/workspace", json=body)

    def prepare_workspace(
        self, case_id: str, base_ref: str = "HEAD", repository_id: str | None = None
    ) -> dict[str, Any]:
        """작업공간을 요청하고 Runner 가 실제로 만들게 한다."""
        assert self.request_workspace(case_id, base_ref, repository_id).status_code == 201
        self.agent.prepare_workspaces()
        return self.workspace(case_id, repository_id)

    def workspace_view(self, case_id: str) -> dict[str, Any] | None:
        """저장소별 작업공간 전부와 조합·선택을 담은 조회 결과(P3-R2)."""
        response = self.client.get(f"/api/cases/{case_id}/workspace")
        assert response.status_code == 200, response.text
        return response.json()

    def workspace(
        self, case_id: str, repository_id: str | None = None
    ) -> dict[str, Any] | None:
        """**한 저장소의** 작업공간.

        P3-R2에서 조회가 저장소별 목록이 됐다. 단일 저장소 Case 의 동작을 보는
        시험은 그 하나를 보면 되므로 여기서 골라 준다 — 저장소를 말하지 않았는데
        여럿이면 **고르지 않는다**(`None`). 아무 것이나 돌려주면 시험이 어느
        저장소를 봤는지 모르는 채로 통과한다.
        """
        view = self.workspace_view(case_id)
        if view is None:
            return None
        spaces = view["workspaces"]
        if repository_id is not None:
            spaces = [w for w in spaces if w["repository_id"] == repository_id]
        if len(spaces) != 1:
            return None
        workspace = dict(spaces[0])
        # 목록이 아니라 하나를 볼 때도 격리 한계 문구는 같은 곳에서 온다.
        workspace["isolation"] = view["isolation"]
        workspace["isolation_note"] = view["isolation_note"]
        return workspace

    def project_repository_id(self, project_id: str) -> str:
        """Project 의 등록 저장소 하나. 단일 저장소 시험이 대상을 밝힐 때 쓴다."""
        view = self.client.get(f"/api/projects/{project_id}/repositories").json()
        return view["repositories"][0]["id"]

    def register_repository(
        self, project_id: str, name: str, repo_path: str
    ) -> dict[str, Any]:
        response = self.client.post(
            f"/api/projects/{project_id}/repositories",
            json={"name": name, "repo_path": repo_path},
        )
        assert response.status_code == 201, response.text
        return response.json()

    def select_repository(
        self,
        case_id: str,
        repository_id: str,
        code_write_allowed: bool = True,
        publish_allowed: bool = False,
        selection_source: str = "explicit",
    ):
        return self.client.put(
            f"/api/cases/{case_id}/repositories",
            json={
                "repository_id": repository_id,
                "selection_source": selection_source,
                "code_write_allowed": code_write_allowed,
                "publish_allowed": publish_allowed,
                "selected_by": "owner",
            },
        )

    def run_commands(self, run_id: str) -> list[dict[str, Any]]:
        return self.client.get(f"/api/runs/{run_id}").json()["commands"]

    # ------------------------------------------------------ UI-01 도우미

    def create_conversation(self, project_id: str, title: str = "새 대화") -> dict[str, Any]:
        """준비 단계 대화(= Case). 목표·Profile 없이 시작한다."""
        response = self.client.post(
            f"/api/projects/{project_id}/conversations", json={"title": title}
        )
        assert response.status_code == 201, response.text
        return response.json()

    def conversation(self, case_id: str) -> dict[str, Any]:
        response = self.client.get(f"/api/cases/{case_id}/conversation")
        assert response.status_code == 200, response.text
        return response.json()

    def post_message(
        self,
        case_id: str,
        content: str,
        client_message_id: str,
        kind: str = "general",
        summary: str | None = None,
        **extra: Any,
    ):
        """메시지를 보낸다. **응답만 돌려준다** — 접수(Runner 저장)는 하지 않는다."""
        body: dict[str, Any] = {
            "client_message_id": client_message_id,
            "kind": kind,
            "content": content,
            # 요약은 본문에서 잘라 내지 않는 표시 문구다(제어부에 남는다).
            "summary": summary or f"메시지 {client_message_id}",
            "target_runner_id": RUNNER_ID,
        }
        body.update(extra)
        return self.client.post(f"/api/cases/{case_id}/messages", json=body)

    def send_message(
        self,
        case_id: str,
        content: str,
        client_message_id: str,
        kind: str = "general",
        **extra: Any,
    ) -> dict[str, Any]:
        """메시지를 보내고 **Runner 가 저장할 때까지** 진행한다(접수 완료)."""
        response = self.post_message(case_id, content, client_message_id, kind, **extra)
        assert response.status_code == 202, response.text
        self.agent.persist_pending_intakes()
        found = self.client.get(
            f"/api/cases/{case_id}/messages/by-client-id/{client_message_id}"
        ).json()
        assert found["receipt"] == "stored", found
        return {**response.json(), "message": found["message"], "receipt": found["receipt"]}

    def discussion_reply(
        self,
        case_id: str,
        request_id: str,
        run_id: str,
        execute: bool = True,
        instruction: dict[str, Any] | None = None,
    ):
        """그 요청에 대한 **논의 응답** 실행. 지시는 요청을 연 메시지 원문이다."""
        request = self.client.get(f"/api/cases/{case_id}/conversation").json()
        opening_id = next(
            r["opened_by_message_id"] for r in request["requests"] if r["id"] == request_id
        )
        opening = next(m for m in request["messages"] if m["id"] == opening_id)
        target = instruction or opening
        response = self.client.post(
            f"/api/cases/{case_id}/runs",
            json={
                "run_id": run_id,
                "instruction_artifact_id": target["artifact_id"],
                "instruction_artifact_rev": target["artifact_rev"],
                "purpose": "discussion_reply",
                "role": "author",
                "tool_id": FAKE_TOOL_ID,
                "mode": FAKE_TOOL_MODE,
                "permission": "read_only",
                "request_id": request_id,
            },
        )
        if execute and response.status_code == 201:
            self.agent.poll_once()
        return response

    def settle(
        self, case_id: str, request_id: str, outcome: str = "completed", note: str | None = None
    ):
        body: dict[str, Any] = {"outcome": outcome, "actor": "system"}
        if note is not None:
            body["note"] = note
        return self.client.post(
            f"/api/cases/{case_id}/requests/{request_id}/settle", json=body
        )

    def start_work(
        self,
        case_id: str,
        request_message_id: str,
        profile: str = "feature",
        decided_by: str = "person",
        interpretation_run_id: str | None = None,
        summary: str = "이 범위로 구현 요청",
    ):
        body: dict[str, Any] = {
            "profile": profile,
            "request_message_id": request_message_id,
            "decided_by": decided_by,
            "actor": "owner",
            "summary": summary,
        }
        if interpretation_run_id is not None:
            body["interpretation_run_id"] = interpretation_run_id
        return self.client.post(f"/api/cases/{case_id}/work-start", json=body)

    def age_heartbeat(self, seconds: float, runner_id: str = RUNNER_ID) -> None:
        """UI-02. 그 Runner 의 마지막 heartbeat 를 `seconds` 초 전으로 옮긴다(PC 미연결 재현)."""
        import sqlite3
        from datetime import datetime, timedelta, timezone

        past = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(
            timespec="microseconds"
        )
        conn = sqlite3.connect(self.controller_config.db_path)
        try:
            conn.execute("UPDATE runner SET last_heartbeat_at = ? WHERE id = ?", (past, runner_id))
            conn.commit()
        finally:
            conn.close()

    def intake_count(self) -> int:
        """제어부에 있는 접수 행의 수. 거부된 전송이 고아 원문을 남기지 않았는지 본다."""
        import sqlite3

        conn = sqlite3.connect(self.controller_config.db_path)
        try:
            return conn.execute("SELECT COUNT(*) FROM intake").fetchone()[0]
        finally:
            conn.close()


#: UI-02. 시험 하네스의 PC 미연결 기준(초). 하네스의 Runner 는 `poll_once` 를 부를 때만
#: heartbeat 를 보내므로 기본값(15초)이면 느린 시험이 우연히 "PC 미연결"에 걸린다. 미연결을
#: 보는 시험은 heartbeat 시각을 직접 옮겨 결정적으로 만든다(`Harness.age_heartbeat`).
HARNESS_RUNNER_STALE_SECONDS = 3600.0


@pytest.fixture
def harness(tmp_path: Path):
    controller_config = ControllerConfig(
        data_root=tmp_path / "controller",
        web_dist=None,
        runner_stale_seconds=HARNESS_RUNNER_STALE_SECONDS,
    )
    app = create_app(controller_config)
    with TestClient(app) as client:
        runner_config = RunnerConfig(
            runner_id=RUNNER_ID,
            controller_url="http://testserver",
            data_root=tmp_path / "runner",
            host_name="test-host",
        )
        agent = RunnerAgent(
            runner_config,
            ControllerClient("http://testserver", client=client),
            # 실제 코딩 CLI를 부르지 않는다. 능력 보고도 이 PC 조회가 아니라
            # 가짜 값이라 시험이 설치 상태에 좌우되지 않는다.
            cli_executor=FakeCliExecutor(runner_config.effects_dir),
            capabilities=fake_capabilities(),
        )
        agent.register()
        yield Harness(client, agent, controller_config, runner_config, tmp_path)
