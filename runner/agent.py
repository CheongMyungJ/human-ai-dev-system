"""Runner 루프.

한 번의 `poll_once()` 가 하는 일:

  1. 생존 보고
  2. 맡을 원문을 가져와 로컬에 영속 저장하고 "저장했다"고 보고 → 그때가 저장 완료
  3. 배정을 받아 실행하고 이벤트·결과를 보고

중복 실행 방지는 3에서 실행 원장(`runner.ledger`)이 맡는다. 같은 `run_id` 가
다시 배정돼도 executor를 부르지 않는다. 자세한 이유는 `runner/ledger.py` 참조.

**P2-03: 실행에는 목적이 있다.** 배정에 실린 `purpose` 에 따라 이 Runner가
지시문을 조립하고(프롬프트는 본문이므로 제어부에 두지 않는다), 실행 뒤에 할 일도
달라진다.

    intent_authoring    AI가 쓴 초안을 정규 문서로 묶어 저장하고 **의도 버전을 만든다.**
                        P2-02와 방향이 반대다 — 초안이 Runner에서 태어난다
    intent_gate_review  작성과 **다른 세션**에서 초안을 검토하고 발견 사항을 올린다
    limited_analysis    동의된 의도에 따른 읽기 전용 작업
    design_authoring    동의된 의도 위에 **설계안**을 쓴다(P3-01)
    plan_authoring      검토를 마친 설계 위에 **개발계획**을 쓴다(P3-01)

**P3-01: 작성 실행은 고정 컨텍스트를 받는다.** 배정에 실린 `context_refs` 의 원문을
이 Runner의 저장소에서 읽어 지시문에 붙인다. 읽지 못한 참조는 "읽지 못함"으로 적고
산출물에도 그 사실을 남긴다 — 이전 버전을 보지 못한 채 쓴 산출물이 그 사실을 숨기면
사람은 왜 내용이 퇴화했는지 알 수 없다(P2-04 위험 1).

목적이 요구하는 산출물을 만들지 못했으면 **CLI가 정상 종료했어도 완료가 아니다.**
`_produce_for_purpose()` 가 그 판정을 한다(FR-28: 종료 코드만으로 완료를 선언하지
않는다).
"""

from __future__ import annotations

import base64
import subprocess
import time
from typing import Any

from pathlib import Path

from domain import ids, intent_doc, prep_doc
from domain.models import (
    ArtifactKind,
    AuthoringMode,
    CapabilityState,
    Permission,
    PreparationStage,
    RunOutcome,
    RunPurpose,
    WorkLevel,
)
from runner import cli_adapter, prompts, workspace
from runner.client import ControllerClient
from runner.config import RunnerConfig
from runner.executor import TOOL_ID, TOOL_VERSION, LocalEchoExecutor
from runner.ledger import STATE_FINISHED, ExecutionLedger
from runner.store import ArtifactStore, content_hash


#: 작업공간을 바꿀 수 있는 권한. `controller/admission.py` 의 같은 이름과 맞춘다.
WRITE_PERMISSIONS = frozenset({Permission.WORKSPACE_WRITE, Permission.EXPLICIT_ESCALATED})


class WorkspaceBusy(RuntimeError):
    """같은 worktree 에 다른 쓰기 실행의 권고 잠금이 있다.

    **실행하지 않고 올라간다.** 실행한 뒤에 겹침을 발견하면 두 실행의 변경이
    이미 섞여 있고, 그러면 실행 전후 대조가 무엇도 답하지 못한다.
    """


def local_executor_capabilities() -> list[dict[str, Any]]:
    """P2-01의 최소 실행기가 할 수 있는 것.

    **이것은 코딩 CLI가 아니다.** 골격 시험용 실행기이며 CLI 능력을 `verified` 로
    올리지 않는다. 남겨 두는 이유는 시험과 화면 골격이 이 경로를 계속 쓰기 때문이다.
    """
    source = "P2-01 local executor (not a coding CLI)"
    rows = [
        {
            "tool_id": TOOL_ID,
            "mode": "p2-01-local",
            "capability": capability,
            "state": state.value,
            "source": source,
        }
        for capability, state in (
            ("installed", CapabilityState.VERIFIED),
            # **이것은 코딩 CLI가 아니다.** 실행은 되지만 AI가 글을 쓰지 않는다.
            # 의도 초안 작성·의미 검토에 배정되지 않도록 사실대로 보고한다.
            ("coding_cli", CapabilityState.UNSUPPORTED),
            (f"permission:{Permission.READ_ONLY.value}", CapabilityState.VERIFIED),
            ("structured_events", CapabilityState.VERIFIED),
            ("session_identity", CapabilityState.UNSUPPORTED),
            ("tool_boundary_observed", CapabilityState.UNSUPPORTED),
            ("usage_reporting", CapabilityState.UNSUPPORTED),
            ("safe_stop_next_call", CapabilityState.UNSUPPORTED),
        )
    ]
    return rows


def default_capabilities() -> list[dict[str, Any]]:
    """이 Runner가 **지금 이 PC에서** 실제로 무엇을 할 수 있는지.

    코딩 CLI 능력은 `runner.cli_adapter.capabilities_for()` 가 만든다. 설치 여부는
    기동 시점에 직접 확인하고, 실행 능력은 P1에서 실측한 값을 근거 위치와 함께
    올린다. 확인하지 않은 것을 `verified` 로 올리지 않는다.
    """
    rows = local_executor_capabilities()
    for tool_id in cli_adapter.SUPPORTED_TOOLS:
        rows.extend(cli_adapter.capabilities_for(tool_id))
    return rows


class RunnerAgent:
    def __init__(
        self,
        config: RunnerConfig,
        client: ControllerClient,
        executor: LocalEchoExecutor | None = None,
        cli_executor: Any | None = None,
        capabilities: list[dict[str, Any]] | None = None,
    ) -> None:
        config.ensure_dirs()
        self.config = config
        self.client = client
        self.store = ArtifactStore(config.artifacts_dir)
        self.ledger = ExecutionLedger(config.ledger_dir)
        self.executor = executor or LocalEchoExecutor(config.effects_dir)
        # 실제 CLI 실행기. 시험은 여기에 가짜를 넣어 CLI를 부르지 않는다 —
        # 자동 시험과 실제 CLI 실증을 섞지 않는다는 P1-02의 구분을 유지한다.
        self.cli_executor = cli_executor or cli_adapter.CliExecutor(config.effects_dir)
        # 보고할 능력. 기본값은 이 PC를 실제로 조회한 결과다. 시험은 가짜 실행기에
        # 맞는 값을 넣어 **설치된 CLI 유무에 시험이 좌우되지 않게** 한다.
        self._capabilities = capabilities

    # ------------------------------------------------------------------ 등록

    def register(self) -> Any:
        return self.client.register(
            self.config.runner_id,
            name=self.config.runner_id,
            host=self.config.host_name,
            capabilities=(
                self._capabilities if self._capabilities is not None else default_capabilities()
            ),
        )

    # ------------------------------------------------------------------ 원문

    def persist_pending_intakes(self) -> list[str]:
        """제어부가 중계 중인 원문을 받아 로컬에 저장하고 보고한다."""
        stored: list[str] = []
        for intake in self.client.pending_intakes(self.config.runner_id):
            body = base64.b64decode(intake["content_b64"])
            digest = content_hash(body)
            if digest != intake["expected_hash"]:
                # 받은 본문이 제어부가 계산한 해시와 다르면 저장하지 않는다.
                continue
            self.store.put(intake["artifact_id"], intake["revision"], body)
            self.client.report_stored(intake["intake_id"], self.config.runner_id, digest)
            stored.append(intake["intake_id"])
            if intake["kind"] == ArtifactKind.INTENT.value and intake.get("intent"):
                self.report_intent_structure(body, intake["intent"])
        return stored

    def report_intent_structure(self, body: bytes, context: dict[str, Any]) -> dict[str, Any]:
        """방금 저장한 의도 원문에서 구조를 뽑아 제어부에 보고한다.

        **여기가 본문을 읽는 유일한 쪽이다.** 제어부는 어느 원문과 비교할지만 알려
        주고, 이전 버전의 본문도 이 Runner의 저장소에서 읽는다. 올라가는 것은
        항목별 상태·출처·변화 여부와 질문의 짧은 요약뿐이다.
        """
        previous: bytes | None = None
        prev_id = context.get("prev_artifact_id")
        if prev_id:
            try:
                previous = self.store.get(prev_id, context["prev_artifact_rev"])
            except FileNotFoundError:
                # 이전 버전 원문이 이 Runner에 없다. 비교하지 않은 사실을 그대로 둔다 —
                # 없는 비교 결과를 "변화 없음"으로 지어내지 않는다.
                previous = None
        structure = intent_doc.structure(body, previous)
        payload = {
            "runner_id": self.config.runner_id,
            "intent_version_id": context["intent_version_id"],
            "fields": structure["fields"],
            "questions": structure["questions"],
            # 성공 기준의 요약도 같은 보고로 올라간다(P2-04). 기대값과 확인 방법의
            # 본문은 이 Runner의 원문 안에 남는다.
            "criteria": structure["criteria"],
            # 작업 수준 판단도 같이 올라간다(P3-01). 축별 근거의 서술은 이 Runner의
            # 원문 안에 남고 영향·짧은 판단 한 줄만 올라간다.
            # `None` 이면 "판단하지 않음"이며 제어부가 수준을 만들지 않는다.
            "sizing": structure["sizing"],
        }
        return self.client.send_intent_structure(payload)

    # ------------------------------------------------------------- 원문 열람

    def serve_read_requests(self) -> list[str]:
        """사람이 요청한 원문을 제어부로 올린다.

        고정 버전 `(artifact_id, revision)` 만 읽는다. 경로를 받지 않으므로
        임의 파일 조회가 되지 않는다(data-boundary-review 3절).
        """
        served: list[str] = []
        for request in self.client.pending_read_requests(self.config.runner_id):
            try:
                body = self.store.get(request["artifact_id"], request["revision"])
            except FileNotFoundError:
                # 이 Runner에 원문이 없다. 빈 본문을 올리지 않고 요청을 그대로 둔다.
                continue
            self.client.send_read_content(
                request["id"],
                self.config.runner_id,
                base64.b64encode(body).decode("ascii"),
                content_hash(body),
            )
            served.append(request["id"])
        return served

    # ------------------------------------------------------------------ 실행

    def handle_assignment(self, assignment: dict[str, Any]) -> dict[str, Any]:
        run_id = assignment["run_id"]
        generation = assignment["assignment_generation"]
        case_id = assignment["case_id"]
        purpose = assignment.get("purpose") or RunPurpose.LIMITED_ANALYSIS.value

        # **이 Runner 가 실행할 수 없는 목적인가.** 진입 조건과 실행 경로는 서로 다른
        # 것이어서 한쪽만 먼저 열릴 수 있다 — P3-01에서 `feature_implementation` 의
        # 배정 조건은 열렸지만 실행기는 P3-03이다. 그 배정을 받으면 **실행하지 않고
        # 실패로 보고한다.** 예외로 죽으면 실행이 `assigned` 로 멈춘 채 남고 사람은
        # 왜 아무 일도 일어나지 않는지 알 수 없다(라이브에서 실제로 났던 일).
        #
        # 원장을 잡기 전에 본다. 아무 것도 실행하지 않았으므로 중복 실행을 막을
        # 대상이 없다.
        if assignment["tool_id"] != TOOL_ID and not prompts.has_prompt(purpose):
            self.client.send_result(
                run_id,
                {
                    "runner_id": self.config.runner_id,
                    "generation": generation,
                    "outcome": RunOutcome.FAILED.value,
                    "residual_activity": "none",
                    "observed_tool_version": None,
                },
            )
            return {
                "run_id": run_id,
                "action": "refused_no_execution_path",
                "purpose": purpose,
            }

        # **같은 worktree 에 다른 쓰기 실행의 잠금이 있는가.** 원장을 잡기 전에
        # 본다 — 실행하지 않았으므로 중복 실행을 막을 대상이 없고, 여기서 사유와
        # 함께 끝내야 실행이 `assigned` 로 멈춘 채 남지 않는다. 제어부는 같은 Case
        # 의 쓰기를 직렬화하지만 **같은 호스트의 다른 Runner 프로세스는 모른다.**
        space = assignment.get("workspace")
        if space is not None and Permission(assignment["permission"]) in WRITE_PERMISSIONS:
            work_dir = Path(assignment.get("workspace_path") or assignment["repo_path"])
            holder = workspace.lock_holder(workspace.lock_path_for(work_dir))
            if holder is not None:
                self.client.send_result(
                    run_id,
                    {
                        "runner_id": self.config.runner_id,
                        "generation": generation,
                        "outcome": RunOutcome.FAILED.value,
                        "residual_activity": "none",
                        "observed_tool_version": None,
                    },
                )
                return {
                    "run_id": run_id,
                    "action": "refused_workspace_busy",
                    "holder": holder,
                }

        should_execute, existing = self.ledger.claim(run_id, generation)

        if not should_execute:
            # 이미 이 run_id 를 맡은 적이 있다. 다시 실행하지 않는다.
            if existing and existing.get("state") == STATE_FINISHED:
                payload = dict(existing["result"])
                payload["generation"] = generation
                payload["runner_id"] = self.config.runner_id
                self.client.send_result(run_id, payload)
                return {"run_id": run_id, "action": "replayed_stored_result"}
            # 착수는 했는데 결과가 없다. 결과를 모르는 상태이며 성공으로 바꾸지 않는다.
            self.client.send_result(
                run_id,
                {
                    "runner_id": self.config.runner_id,
                    "generation": generation,
                    "outcome": RunOutcome.UNKNOWN.value,
                    "residual_activity": "unknown",
                    "observed_tool_version": f"{TOOL_ID}/{TOOL_VERSION}",
                },
            )
            return {"run_id": run_id, "action": "reported_unknown_without_reexecution"}

        instruction = self.store.get(
            assignment["instruction_artifact_id"], assignment["instruction_artifact_rev"]
        )

        if assignment["tool_id"] == TOOL_ID:
            # P2-01 골격 실행기. 코딩 CLI가 아니며 목적별 산출물을 만들지 않는다.
            output = self.executor.execute(run_id, case_id, instruction)
            produced: dict[str, Any] = {"purpose": purpose, "produced": "none"}
        else:
            output, produced = self._execute_with_cli(assignment, instruction, purpose)

        output_artifact_id = ids.new_artifact_id()
        stored = self.store.put(output_artifact_id, 1, output.output_body)
        self.client.register_artifact(
            {
                "runner_id": self.config.runner_id,
                "case_id": case_id,
                "kind": "run_output",
                "artifact_id": output_artifact_id,
                "revision": 1,
                "content_hash": stored.content_hash,
                "byte_size": stored.byte_size,
                "summary": f"run output for {run_id}",
            }
        )

        self.client.send_events(run_id, self.config.runner_id, generation, output.events)

        # **명령 기록은 결과보다 먼저 올린다.** 검증 실행의 완료 판정이 이 기록의
        # 존재를 보기 때문이고, 결과가 먼저 들어가면 "명령 없는 완료"가 잠깐이라도
        # 보이게 된다(P3-03).
        if produced.get("commands"):
            self.client.send_commands(
                run_id, self.config.runner_id, generation, produced["commands"]
            )

        result_payload = {
            "outcome": output.outcome.value,
            "exit_code": output.exit_code,
            "output_artifact_id": output_artifact_id,
            "output_artifact_rev": 1,
            "usage": output.usage,
            # 실행 전후 대조의 결과. **수와 SHA 뿐이다** — 어느 파일이 어떻게
            # 바뀌었는지는 이 Runner 에 남는다(D-43). 관측하지 않았으면 `None` 이고
            # 그것은 "변경 없음"이 아니라 **모른다**이다.
            "workspace_effect": getattr(output, "workspace_effect", None),
            "residual_activity": output.residual_activity,
            "session_ref": getattr(output, "session_ref", None),
            "observed_tool_version": getattr(output, "observed_tool_version", None)
            or f"{TOOL_ID}/{TOOL_VERSION}",
        }
        # 결과를 **보고하기 전에** 원장에 확정한다. 보고가 유실돼도
        # 같은 run_id 가 다시 오면 재실행하지 않고 이 결과를 다시 보낸다.
        self.ledger.finish(run_id, result_payload)

        send_payload = dict(result_payload)
        send_payload["runner_id"] = self.config.runner_id
        send_payload["generation"] = generation
        self.client.send_result(run_id, send_payload)

        # 게이트 검토 결과는 결과 보고 **뒤에** 올린다. 제어부가 "작성 세션과 검토
        # 세션이 달랐는가"를 판단하려면 이 실행의 session_ref 가 먼저 기록돼 있어야
        # 한다(FR-29 별도 세션 요구).
        if produced.get("gate_findings") is not None:
            self.client.send_gate_review(
                {
                    "runner_id": self.config.runner_id,
                    "run_id": run_id,
                    "intent_version_id": produced["intent_version_id"],
                    "findings": produced["gate_findings"],
                }
            )
            produced["gate_review_sent"] = True

        return {"run_id": run_id, "action": "executed", "purpose": purpose, "produced": produced}

    # ------------------------------------------------------- 목적별 실행·산출물

    def _execute_with_cli(
        self, assignment: dict[str, Any], instruction: bytes, purpose: str
    ) -> tuple[Any, dict[str, Any]]:
        """실제 코딩 CLI로 실행하고 목적이 요구하는 산출물을 만든다.

        지시문 조립이 여기 있는 이유는 지시문이 **본문**이기 때문이다. 제어부는
        목적과 원문 참조만 내려보내고, 원문을 가진 쪽이 둘을 합친다.

        **P3-03: 쓰기 실행은 관측 안에서 돈다.** 실행 전후의 작업공간과 원래
        저장소를 대조해 무엇이 실제로 바뀌었는지를 남기고, 같은 worktree 에 두
        실행이 겹치지 않도록 권고 잠금을 잡는다. 그 대조가 "완료라고 보고됐는데
        아무 것도 바뀌지 않은" 실행을 걸러내는 유일한 증거다.
        """
        context = self.load_context(assignment)
        prompt = prompts.build(
            purpose,
            instruction,
            context=context,
            level=assignment.get("work_level"),
            profile=assignment.get("case_profile"),
            profile_version=assignment.get("case_profile_version"),
            # **제어부가 정한 단계**(P3-R4). Fast Lane 의 계획 작성은 결합 기록을 쓴다.
            stage_hint=assignment.get("preparation_stage"),
            # **제어부가 준 저장소 목록**(P3-04). 계획이 Task 마다 저장소를 적어야
            # 하므로 고를 수 있는 이름을 함께 준다. Runner 가 찾아 나서지 않는다 —
            # 이 Case 가 고르지 않은 저장소를 계획에 적으면 허용을 넓히는 요구가 된다.
            repositories=assignment.get("case_repositories"),
        )
        permission = Permission(assignment["permission"])
        work_dir = Path(assignment.get("workspace_path") or assignment["repo_path"])
        space = assignment.get("workspace")
        watching = space is not None and permission in WRITE_PERMISSIONS

        lock: workspace.AdvisoryLock | None = None
        before = after = None
        repo_before = repo_after = None
        repo_dir = Path(space["repo_path"]) if space else None
        if watching:
            # 권고 잠금. **OS 잠금이 아니다** — 이 규약을 지키는 Runner 에만
            # 효과가 있다. 제어부의 배정 직렬화와 함께 두는 이유는 각각 다른
            # 경우를 놓치기 때문이다(제어부는 같은 호스트의 두 프로세스를 모르고
            # 이 파일은 다른 호스트를 모른다).
            lock = workspace.AdvisoryLock(workspace.lock_path_for(work_dir))
            if not lock.acquire(f"{self.config.runner_id}:{assignment['run_id']}"):
                raise WorkspaceBusy(
                    f"{work_dir} 에 다른 쓰기 실행의 잠금이 있다: {lock.holder}"
                )
            before = workspace.observe(work_dir)
            if repo_dir is not None:
                # 원래 저장소도 본다. 경계 밖 변경은 **막지 못하고 감지만 한다**(D-44).
                repo_before = workspace.observe(repo_dir)

        try:
            output = self.cli_executor.execute(
                run_id=assignment["run_id"],
                case_id=assignment["case_id"],
                prompt=prompt,
                tool_id=assignment["tool_id"],
                mode=assignment["mode"],
                permission=permission,
                workspace=work_dir,
                raw_dir=self.config.raw_dir,
            )
        finally:
            if lock is not None:
                lock.release()

        if watching:
            after = workspace.observe(work_dir)
            if repo_dir is not None:
                repo_after = workspace.observe(repo_dir)
            output.workspace_effect = workspace.compose_effect(
                before=before,
                after=after,
                base_commit=space["base_commit"],
                numbers=workspace.diff_numbers(work_dir, space["base_commit"]),
                repo_before=repo_before,
                repo_after=repo_after,
            )

        produced = self._produce_for_purpose(assignment, purpose, output, context)
        return output, produced

    def load_context(self, assignment: dict[str, Any]) -> list[dict[str, Any]]:
        """배정에 실린 고정 참조의 원문을 이 Runner의 저장소에서 읽는다.

        **없는 원문을 빈 내용으로 바꾸지 않는다.** `body` 가 `None` 이면 읽지 못한
        것이고 지시문에도 그렇게 적힌다. 참조를 조용히 빼면 AI는 그런 자료가 없었다고
        생각하고 처음부터 다시 쓴다 — P2-04에서 초안이 퇴화한 경로가 그것이다.
        """
        context: list[dict[str, Any]] = []
        for ref in assignment.get("context_refs") or []:
            try:
                body: bytes | None = self.store.get(ref["artifact_id"], ref["revision"])
            except FileNotFoundError:
                body = None
            context.append(
                {
                    "role": ref["role"],
                    "artifact_id": ref["artifact_id"],
                    "revision": ref["revision"],
                    "body": body,
                }
            )
        return context

    def _produce_for_purpose(
        self,
        assignment: dict[str, Any],
        purpose: str,
        output: Any,
        context: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """실행 결과에서 목적이 요구하는 산출물을 만든다.

        **산출물을 만들지 못하면 실행은 완료가 아니다.** CLI가 정상 종료해도
        의도 초안이 없거나 검토 결과가 형식에 맞지 않으면 `outcome` 을 `failed` 로
        내린다. 형식을 못 맞춘 응답을 추측으로 고쳐 진행하지 않는다 — 지어낸 의도에
        사람이 동의하게 만들지 않기 위해서다.
        """
        produced: dict[str, Any] = {"purpose": purpose, "produced": "none"}
        if output.outcome is not RunOutcome.COMPLETED:
            return produced

        try:
            if purpose == RunPurpose.INTENT_AUTHORING.value:
                produced.update(self._produce_intent_draft(assignment, output, context or []))
            elif purpose in (
                RunPurpose.DESIGN_AUTHORING.value,
                RunPurpose.PLAN_AUTHORING.value,
            ):
                # **단계는 제어부가 정한다**(P3-R4). 배정에 없으면 목적에서 읽는다 —
                # R4 이전에 배정된 실행에는 이 값이 없다.
                hinted = assignment.get("preparation_stage")
                stage = (
                    PreparationStage(hinted)
                    if hinted
                    else (
                        PreparationStage.DESIGN
                        if purpose == RunPurpose.DESIGN_AUTHORING.value
                        else PreparationStage.PLAN
                    )
                )
                produced.update(
                    self._produce_preparation(assignment, output, stage, context or [])
                )
            elif purpose == RunPurpose.FEATURE_IMPLEMENTATION.value:
                produced.update(self._produce_implementation(output))
            elif purpose == RunPurpose.VERIFICATION_RUN.value:
                produced.update(self._produce_verification(output))
            elif purpose == RunPurpose.LOCAL_EXPERIMENT.value:
                produced.update(self._produce_experiment(output))
            elif purpose == RunPurpose.INTENT_GATE_REVIEW.value:
                target = assignment.get("target_intent_version_id")
                if not target:
                    raise ValueError("검토할 의도 버전을 배정에서 찾지 못했다")
                produced["gate_findings"] = prompts.parse_gate_review(output.final_message)
                produced["intent_version_id"] = target
                produced["produced"] = "gate_review"
            elif purpose == RunPurpose.QUALITY_GATE_REVIEW.value:
                # 일반 게이트의 대상·기준 연결은 제어부가 별도 API에서 검증한다.
                # Runner는 원문을 가진 채 발견만 구조화하며 스스로 통과를 선언하지 않는다.
                produced["quality_gate_findings"] = prompts.parse_gate_review(
                    output.final_message
                )
                produced["produced"] = "quality_gate_review"
        except (ValueError, KeyError) as exc:
            output.outcome = RunOutcome.FAILED
            produced["produced"] = "none"
            produced["failure"] = f"{type(exc).__name__}: {exc}"
            produced.pop("gate_findings", None)
            produced.pop("quality_gate_findings", None)
        return produced

    def _produce_implementation(self, output: Any) -> dict[str, Any]:
        """구현 실행의 산출물은 **작업공간의 실제 변화**다.

        CLI 가 정상 종료하고 "고쳤다"고 적어도, 기준 커밋과 대조해 바뀐 것이
        없으면 완료가 아니다(FR-09 "실제 실행 증거를 작성자의 완료 주장으로
        대체하지 않는다"). 이 규칙이 없으면 P3-02가 연 의존 해제가 위험해진다 —
        아무 것도 바뀌지 않은 실행 하나로 후속 Task 가 전부 열린다.

        **관측하지 못한 경우를 변경 없음으로 읽지 않는다.** 작업공간 없이 돈
        구현 실행은 `workspace_effect` 가 없고, 그것은 "안 바뀌었다"가 아니라
        **모른다**이므로 완료로 올리지 않는다.
        """
        parsed = prompts.parse_implementation(output.final_message)
        effect = getattr(output, "workspace_effect", None)
        produced: dict[str, Any] = {
            "produced": "implementation",
            "changed_summary": parsed["changed_summary"],
            "workspace_effect": effect,
        }
        if parsed["blocked"]:
            output.outcome = RunOutcome.FAILED
            produced["produced"] = "none"
            produced["failure"] = "blocked: " + (parsed["blocked_reason"] or "이유 없음")
            return produced
        if effect is None:
            output.outcome = RunOutcome.FAILED
            produced["produced"] = "none"
            produced["failure"] = "no_workspace_observation"
            return produced
        if not effect.get("changed"):
            output.outcome = RunOutcome.FAILED
            produced["produced"] = "none"
            produced["failure"] = "no_workspace_change"
        return produced

    def _produce_verification(self, output: Any) -> dict[str, Any]:
        """검증 실행의 산출물은 **실제로 실행된 명령**이다.

        파일 변경을 요구하지 않는 이유는 빌드·테스트가 코드를 바꾸지 않기
        때문이고, 대신 명령 기록을 요구한다. 명령이 하나도 없으면 무엇을
        확인했는지 말할 수 없으므로 완료가 아니다.

        **종료 코드가 0이 아니어도 실행은 완료다.** "테스트가 실패했다"와
        "검증을 수행하지 못했다"는 다른 것이고, 전자는 기준 판정의 입력이다.
        """
        parsed = prompts.parse_verification(output.final_message)
        produced: dict[str, Any] = {
            "produced": "verification",
            "commands": parsed["commands"],
            "result_summary": parsed["result_summary"],
            "workspace_effect": getattr(output, "workspace_effect", None),
        }
        if not parsed["commands"]:
            output.outcome = RunOutcome.FAILED
            produced["produced"] = "none"
            produced["failure"] = "no_command_executed"
        return produced

    def _produce_experiment(self, output: Any) -> dict[str, Any]:
        """실험 실행의 산출물은 **실제로 실행된 명령과 임시 변경의 구분**이다(D-66).

        검증과 두 가지가 다르다.

            작업공간 변화  실험은 고쳐도 된다. 그것이 실험의 수단이다
            임시 변경 기록  무엇을 임시로 고쳤는지가 결론의 근거와 **구별되어야** 한다

        둘째가 이 함수가 따로 있는 이유다. "증거와 임시 변경을 구분한다"(D-66)를
        지키려면 그 구분이 실행 보고 안에 있어야 하고, 검증 보고 형식에는 그 자리가
        없다.

        **명령이 하나도 없으면 완료가 아니다.** 아무 것도 돌려 보지 않은 실험은
        관측을 만들지 못했고, 그 실행을 완료로 올리면 "실험했다"는 기록만 남는다.
        """
        parsed = prompts.parse_experiment(output.final_message)
        produced: dict[str, Any] = {
            "produced": "experiment",
            "commands": parsed["commands"],
            "result_summary": parsed["result_summary"],
            "temporary_changes": parsed["temporary_changes"],
            "workspace_effect": getattr(output, "workspace_effect", None),
        }
        if not parsed["commands"]:
            output.outcome = RunOutcome.FAILED
            produced["produced"] = "none"
            produced["failure"] = "no_command_executed"
        return produced

    def _produce_intent_draft(
        self, assignment: dict[str, Any], output: Any, context: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """AI가 쓴 초안을 정규 문서로 저장하고 **의도 버전을 만든다.**

        P2-02의 경로와 방향이 반대다. 거기서는 사람이 화면에 입력한 항목이 제어부
        메모리를 지나 이 Runner로 왔다. 여기서는 초안이 이 Runner에서 태어나므로
        제어부에는 참조와 구조만 올라간다 — **본문은 올라가지 않는다.**
        """
        fields, questions, criteria, sizing = prompts.parse_intent_draft(
            output.final_message,
            profile=assignment.get("case_profile"),
            profile_version=assignment.get("case_profile_version"),
        )
        case_id = assignment["case_id"]
        run_id = assignment["run_id"]
        body = intent_doc.compose(
            fields=fields,
            questions=questions,
            case_id=case_id,
            authored_by=f"{assignment['tool_id']}/{assignment['mode']}",
            authoring_mode=AuthoringMode.AI_DRAFTED,
            author_run_id=run_id,
            criteria=criteria,
            sizing=sizing,
            # **P3-R1: 배정이 알려 준 Profile 로 문서를 만든다.** Runner 가 스스로
            # 현재 정의를 고르지 않는다 — 제어부가 기록한 Case 의 버전이 정본이다.
            profile=assignment.get("case_profile"),
            profile_version=assignment.get("case_profile_version"),
        )
        artifact_id = ids.new_artifact_id()
        stored = self.store.put(artifact_id, 1, body)
        self.client.register_artifact(
            {
                "runner_id": self.config.runner_id,
                "case_id": case_id,
                "kind": ArtifactKind.INTENT.value,
                "artifact_id": artifact_id,
                "revision": 1,
                "content_hash": stored.content_hash,
                "byte_size": stored.byte_size,
                # 요약은 본문 발췌가 아니라 이 경로가 만든 짧은 설명이다.
                "summary": f"AI 작성 의도 초안 ({assignment['tool_id']}, run {run_id})",
            }
        )
        created = self.client.create_intent_version(
            {
                "runner_id": self.config.runner_id,
                "case_id": case_id,
                "artifact_id": artifact_id,
                "revision": 1,
                "authoring_mode": AuthoringMode.AI_DRAFTED.value,
                "author_run_id": run_id,
            }
        )
        self.report_intent_structure(body, created["intent_context"])
        return {
            "produced": "intent_version",
            "intent_version_id": created["intent_version"]["id"],
            "artifact_id": artifact_id,
            # 무엇을 읽고 썼는지. 읽지 못한 참조가 있으면 여기에 남는다.
            "context_read": [c["role"] for c in context if c["body"] is not None],
            "context_unread": [c["role"] for c in context if c["body"] is None],
        }

    def _produce_preparation(
        self,
        assignment: dict[str, Any],
        output: Any,
        stage: PreparationStage,
        context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """AI가 쓴 설계·계획을 정규 문서로 저장하고 **준비 산출물로 등록한다.**

        의도 초안 작성과 같은 방향이다 — 산출물이 이 Runner에서 태어나므로 제어부에는
        참조와 구조만 올라간다. **본문은 올라가지 않는다.**

        수준은 배정이 알려 준 값을 쓴다. 여기서 기본값을 지어내면 어떤 항목이 필수인지가
        제어부의 판단과 어긋난다.
        """
        level = assignment.get("work_level")
        if not level:
            raise ValueError(f"{stage.value} 작성에는 작업 수준이 필요하다")
        intent_version_id = assignment.get("current_intent_version_id")
        if not intent_version_id:
            raise ValueError("어느 의도 버전 위에 세울지 배정에서 찾지 못했다")
        sections, questions, tasks = prompts.parse_preparation(output.final_message, stage)
        case_id = assignment["case_id"]
        run_id = assignment["run_id"]
        body = prep_doc.compose(
            stage=stage,
            level=WorkLevel(level),
            sections=sections,
            questions=questions,
            tasks=tasks,
            case_id=case_id,
            intent_version_id=intent_version_id,
            authored_by=f"{assignment['tool_id']}/{assignment['mode']}",
            authoring_mode=AuthoringMode.AI_DRAFTED,
            author_run_id=run_id,
            # 이 실행이 실제로 읽은 참조. 읽지 못한 것도 그대로 적는다.
            context_notes=[
                {
                    "role": c["role"],
                    "artifact_id": c["artifact_id"],
                    "revision": c["revision"],
                    "read": c["body"] is not None,
                }
                for c in context
            ],
        )
        artifact_id = ids.new_artifact_id()
        stored = self.store.put(artifact_id, 1, body)
        kind = (
            ArtifactKind.DESIGN if stage is PreparationStage.DESIGN else ArtifactKind.DEV_PLAN
        )
        self.client.register_artifact(
            {
                "runner_id": self.config.runner_id,
                "case_id": case_id,
                "kind": kind.value,
                "artifact_id": artifact_id,
                "revision": 1,
                "content_hash": stored.content_hash,
                "byte_size": stored.byte_size,
                # 요약은 본문 발췌가 아니라 이 경로가 만든 짧은 설명이다.
                "summary": f"AI 작성 {stage.value} ({assignment['tool_id']}, run {run_id})",
            }
        )
        created = self.client.create_preparation_artifact(
            {
                "runner_id": self.config.runner_id,
                "case_id": case_id,
                "stage": stage.value,
                "artifact_id": artifact_id,
                "revision": 1,
                "level": WorkLevel(level).value,
                "authoring_mode": AuthoringMode.AI_DRAFTED.value,
                "author_run_id": run_id,
                "summary": f"{stage.value} (run {run_id})",
            }
        )
        prep = created["preparation_artifact"]
        self.report_preparation_structure(prep["id"], body)
        return {
            "produced": f"{stage.value}_artifact",
            "preparation_id": prep["id"],
            "artifact_id": artifact_id,
            "context_read": [c["role"] for c in context if c["body"] is not None],
            "context_unread": [c["role"] for c in context if c["body"] is None],
        }

    def report_preparation_structure(self, prep_id: str, body: bytes) -> dict[str, Any]:
        """방금 저장한 설계·계획 원문에서 구조를 뽑아 제어부에 보고한다.

        의도 구조 보고와 같다 — **본문을 읽는 쪽은 원문을 가진 이쪽이고**, 올라가는
        것은 항목별 상태·출처와 질문의 짧은 요약뿐이다.
        """
        structure = prep_doc.structure(body)
        return self.client.send_preparation_structure(
            {
                "runner_id": self.config.runner_id,
                "preparation_id": prep_id,
                "sections": structure["sections"],
                "questions": structure["questions"],
                # Task 도 **구조**다. 목적·산출물·완료 조건의 짧은 요약만
                # 올라가고 서술은 계획 원문에 남는다(P3-02).
                "tasks": structure["tasks"],
            }
        )

    # ------------------------------------------------------------ 작업공간

    @staticmethod
    def _safe_name(value: str) -> str:
        return value.replace("/", "_").replace("\\", "_")

    def worktree_for(self, case_id: str, repository_id: str | None = None) -> Path:
        """이 Runner 가 이 (Case, 저장소)의 worktree 를 두는 자리.

        **저장소 안이 아니다.** 저장소 안에 두면 그 파일들이 원래 작업 트리의
        미추적 파일로 보이고, 사용자가 자기 변경과 구별할 수 없게 된다.

        **저장소마다 다른 자리다**(P3-R2·D-39). 한 Case 가 두 저장소를 고치면 두
        worktree 가 필요하고, 같은 경로를 쓰면 두 번째 준비가 첫 번째를 남의 것으로
        보고 거부한다. `repository_id` 가 없으면 P3-03의 자리를 그대로 쓴다 — 이미
        만들어진 작업공간이 거기 있다.
        """
        base = self.config.worktrees_dir / self._safe_name(case_id)
        if repository_id is None:
            return base
        return base / self._safe_name(repository_id)

    def prepare_workspaces(self) -> list[dict[str, Any]]:
        """맡은 작업공간 준비 요청을 처리한다.

        **실패를 준비됨으로 바꾸지 않는다.** 저장소가 이 호스트에 없거나 브랜치·
        경로가 남의 것이면 그대로 실패를 보고한다 — 빈 디렉터리를 만들어 주면
        "코드가 여기 없다"는 사실이 가려진다.
        """
        results: list[dict[str, Any]] = []
        for request in self.client.pending_workspace_requests(self.config.runner_id):
            case_id = request["case_id"]
            repository_id = request.get("repository_id")
            # **이미 기록된 자리가 있으면 그 자리를 다시 쓴다.** 준비가 실패한 뒤
            # 다시 요청했을 때 새 규칙으로 경로를 옮기면, 그 worktree 에서 이미 한
            # 작업이 떨어져 나가고 남은 브랜치는 다음 준비에서 남의 것으로 보인다.
            recorded = (request.get("worktree_path") or "").strip()
            worktree_path = (
                Path(recorded) if recorded else self.worktree_for(case_id, repository_id)
            )
            try:
                prepared = workspace.prepare(
                    repo_path=Path(request["repo_path"]),
                    worktree_path=worktree_path,
                    branch=request["branch"],
                    base_ref=request.get("base_ref") or "HEAD",
                    known_base_commit=request.get("base_commit") or "",
                )
            except (workspace.WorkspaceError, OSError, subprocess.SubprocessError) as exc:
                self.client.report_workspace_failed(
                    case_id,
                    {
                        "runner_id": self.config.runner_id,
                        "repository_id": repository_id,
                        "reason": f"{type(exc).__name__}: {exc}"[:200],
                    },
                )
                results.append(
                    {
                        "case_id": case_id,
                        "repository_id": repository_id,
                        "action": "failed",
                        "reason": str(exc),
                    }
                )
                continue
            user_tree = prepared.user_tree
            self.client.report_workspace_ready(
                case_id,
                {
                    "runner_id": self.config.runner_id,
                    "repository_id": repository_id,
                    "repo_path": prepared.repo_path,
                    "worktree_path": prepared.worktree_path,
                    "branch": prepared.branch,
                    "base_commit": prepared.base_commit,
                    "base_ref": prepared.base_ref,
                    # **사용자의 원래 작업 트리를 건드리지 않았다는 기록이다.**
                    # 경로는 올라가지 않고 수만 올라간다(D-43).
                    "user_tree_dirty": bool(user_tree and user_tree.dirty),
                    "user_tree_entries": len(user_tree.entries) if user_tree else 0,
                },
            )
            results.append(
                {
                    "case_id": case_id,
                    "repository_id": repository_id,
                    "action": "reused" if prepared.reused else "created",
                    "branch": prepared.branch,
                    "base_commit": prepared.base_commit,
                }
            )
        return results

    # -------------------------------------------------------------- 루프 한 회

    def poll_once(self) -> dict[str, Any]:
        self.client.heartbeat(self.config.runner_id)
        stored = self.persist_pending_intakes()
        served = self.serve_read_requests()
        # **배정보다 먼저 작업공간을 준비한다.** 같은 회차에 준비되면 그 다음
        # 회차의 쓰기 배정이 곧바로 열린다. 반대 순서면 항상 한 회차씩 늦는다.
        workspaces = self.prepare_workspaces()
        actions = []
        for assignment in self.client.claim_assignments(self.config.runner_id):
            # **한 배정의 실패가 다른 배정을 건너뛰게 만들지 않는다.** 이 루프가
            # 통째로 죽으면 이미 맡은 다른 실행의 결과 보고까지 멈춘다.
            try:
                actions.append(self.handle_assignment(assignment))
            except Exception as exc:  # noqa: BLE001
                actions.append(
                    {
                        "run_id": assignment.get("run_id"),
                        "action": "failed_in_runner",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                print(
                    f"[runner] assignment {assignment.get('run_id')} failed: {exc!r}",
                    flush=True,
                )
        return {
            "stored_intakes": stored,
            "served_reads": served,
            "workspaces": workspaces,
            "assignments": actions,
        }

    def run_forever(self, interval: float = 1.0) -> None:
        self.register()
        while True:
            try:
                self.poll_once()
            except Exception as exc:  # noqa: BLE001 - 루프를 죽이지 않는다
                print(f"[runner] poll failed: {exc!r}", flush=True)
            time.sleep(interval)


def main() -> None:
    from runner.config import load_config

    config = load_config()
    client = ControllerClient(config.controller_url)
    agent = RunnerAgent(config, client)
    print(
        f"[runner] id={config.runner_id} controller={config.controller_url}"
        f" data={config.data_root}",
        flush=True,
    )
    agent.run_forever()


if __name__ == "__main__":
    main()
