"""시험 공통 설비.

각 시험은 자기만의 임시 데이터 경로를 쓴다. 개발용 `var/` 를 건드리지 않는다.
"""

from __future__ import annotations

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
    stage: str, sections: dict[str, str], questions: list[dict[str, Any]] | None = None
) -> str:
    import json as _json

    body = {
        "sections": {k: {"text": v, "origin": "ai_proposal"} for k, v in sections.items()},
        "questions": questions or [],
    }
    return f"{stage} 산출물입니다.\n\n```json\n{_json.dumps(body, ensure_ascii=False)}\n```\n"


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

#: 심층 수준까지 필수 항목을 모두 채운 계획 응답.
FAKE_PLAN_FULL = fake_preparation_response(
    "계획",
    {
        "tasks": "T1 필터 함수 구현(완료 조건: 단위 시험 통과), T2 진입점 연결",
        "verification": "표본 파일 시험 1건과 기존 회귀 시험을 돌린다",
        "dependencies": "T2 는 T1 을 기다린다",
        "integration_order": "T1 → T2 → 회귀 확인",
        "human_decision_points": "대소문자 구분 여부가 정해지면 기대값을 확정한다",
        "environment_prerequisites": "Python 3.12 와 저장소 checkout 만 필요하다",
        "experiments": "실험은 필요하지 않다. 표본 파일로 직접 확인한다",
        "failure_response": "시험이 실패하면 T1 로 돌아가고 통과를 주장하지 않는다",
    },
)


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
        self.design_response = FAKE_DESIGN_FULL
        self.plan_response = FAKE_PLAN_FULL
        self.outcome = RunOutcome.COMPLETED
        #: 세션 식별자를 고정하면 "작성과 검토가 같은 세션"을 만들 수 있다.
        self.fixed_session_ref: str | None = None
        self.calls: list[dict[str, Any]] = []

    def _session_ref(self, run_id: str) -> str:
        return self.fixed_session_ref or f"fake-session-{run_id}"

    def _final_message(self, prompt: str) -> str:
        from runner import prompts as prompt_templates

        if prompt.startswith(prompt_templates.INTENT_AUTHORING_PROMPT[:40]):
            return self.draft_response
        if prompt.startswith(prompt_templates.GATE_REVIEW_PROMPT[:40]):
            return self.review_response
        if prompt.startswith(prompt_templates.DESIGN_AUTHORING_PROMPT[:40]):
            return self.design_response
        if prompt.startswith(prompt_templates.PLAN_AUTHORING_PROMPT[:40]):
            return self.plan_response
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
    ) -> ExecutionOutput:
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
        final = self._final_message(prompt)
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
            outcome=self.outcome,
            exit_code=0,
            usage="not_reported",
            residual_activity="unknown",
            session_ref=self._session_ref(run_id),
            observed_tool_version=f"{tool_id}/fake-for-tests",
            final_message=final,
        )


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


@dataclass
class Harness:
    """제어부(TestClient)와 Runner를 한 프로세스에서 연결한 시험 환경."""

    client: TestClient
    agent: RunnerAgent
    controller_config: ControllerConfig
    runner_config: RunnerConfig

    # ------------------------------------------------------------ 준비 도우미

    def create_project(self, name: str = "demo") -> dict[str, Any]:
        response = self.client.post(
            "/api/projects",
            json={"name": name, "repo_path": "C:/tmp/demo", "default_tool_id": "codex"},
        )
        assert response.status_code == 201, response.text
        return response.json()

    def create_case(
        self, project_id: str, title: str = "첫 Case", kind: str = "feature"
    ) -> dict[str, Any]:
        """Case를 만든다.

        `kind` 를 인자로 받는 이유는 P2-03에서 **유형에 따라 진입 조건이 다르기**
        때문이다(FR-29: 비기능 조사에 기능 개발 문서 전체를 일괄 요구하지 않는다).
        실행 배관 자체를 보는 시험은 기능 Case가 아닌 유형을 쓰고, 기능 Case의
        진입 조건은 `test_admission.py` 가 따로 본다.
        """
        response = self.client.post(
            f"/api/projects/{project_id}/cases", json={"title": title, "kind": kind}
        )
        assert response.status_code == 201, response.text
        return response.json()

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
    ) -> dict[str, Any]:
        response = self.client.post(
            f"/api/cases/{case_id}/runs",
            json={
                "run_id": run_id,
                "instruction_artifact_id": artifact_id,
                "purpose": purpose,
                "role": role,
                "tool_id": tool_id,
                "mode": mode,
                "permission": permission,
            },
        )
        # 201 = 새로 만듦, 200 = 같은 run_id 의 재전송(만들지 않음)
        assert response.status_code in (200, 201), response.text
        return response.json()

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
    ):
        return self.client.post(
            f"/api/cases/{case_id}/criteria/{criterion_id}/result",
            json={
                "verdict": verdict,
                "summary": summary,
                "recorded_by": recorded_by,
                "evidence_kind": evidence_kind,
                "evidence_run_id": evidence_run_id,
                "evidence_artifact_id": evidence_artifact_id,
                "evidence_artifact_rev": evidence_artifact_rev,
            },
        )

    def mark_all_criteria_met(self, case_id: str, run_id: str | None = None) -> None:
        """모든 기준을 충족으로 기록한다. 근거는 사람 판단 또는 실행 결과다."""
        for crit in self.criteria(case_id):
            response = self.record_result(
                case_id,
                crit["id"],
                "met",
                evidence_kind="run_output" if run_id else "human_judgement",
                evidence_run_id=run_id,
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
    ) -> dict[str, Any]:
        """의도 초안을 제출하고(기본으로) Runner가 저장·구조 보고까지 하게 한다.

        `persist=False` 는 "아직 Runner가 저장하지 않은" 상태를 만들기 위한 것이다.
        """
        response = self.client.post(
            f"/api/cases/{case_id}/intent-drafts",
            json={
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
    ) -> Any:
        """AI에게 설계 또는 개발계획을 작성시킨다.

        `ai_draft` 와 같은 구조다 — 요청 원문 접수 → 목적별 Run → Runner가 실행하고
        산출물을 만들어 등록한다. 진입 조건이 막으면 그 응답을 그대로 돌려준다.
        """
        instruction = self.submit_artifact(
            case_id, request_text, kind="instruction", summary=f"{stage} 작성 요청"
        )
        response = self.client.post(
            f"/api/cases/{case_id}/runs",
            json={
                "run_id": run_id or f"run-{stage}-1",
                "instruction_artifact_id": instruction["artifact_id"],
                "purpose": f"{stage}_authoring",
                "role": "author",
                "tool_id": FAKE_TOOL_ID,
                "mode": FAKE_TOOL_MODE,
                "permission": "read_only",
            },
        )
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
        self, case_id: str, run_id: str = "run-impl-1", permission: str = "read_only"
    ):
        """기능 구현 실행을 요청한다. 허용/거부 응답을 그대로 돌려준다."""
        instruction = self.submit_artifact(
            case_id, "계획대로 구현해 주세요.", kind="instruction", summary="구현 요청"
        )
        return self.client.post(
            f"/api/cases/{case_id}/runs",
            json={
                "run_id": run_id,
                "instruction_artifact_id": instruction["artifact_id"],
                "purpose": "feature_implementation",
                "role": "author",
                "tool_id": FAKE_TOOL_ID,
                "mode": FAKE_TOOL_MODE,
                "permission": permission,
            },
        )

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


@pytest.fixture
def harness(tmp_path: Path):
    controller_config = ControllerConfig(data_root=tmp_path / "controller", web_dist=None)
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
        yield Harness(client, agent, controller_config, runner_config)
