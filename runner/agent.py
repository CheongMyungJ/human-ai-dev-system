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

목적이 요구하는 산출물을 만들지 못했으면 **CLI가 정상 종료했어도 완료가 아니다.**
`_produce_for_purpose()` 가 그 판정을 한다(FR-28: 종료 코드만으로 완료를 선언하지
않는다).
"""

from __future__ import annotations

import base64
import time
from typing import Any

from pathlib import Path

from domain import ids, intent_doc
from domain.models import (
    ArtifactKind,
    AuthoringMode,
    CapabilityState,
    Permission,
    RunOutcome,
    RunPurpose,
)
from runner import cli_adapter, prompts
from runner.client import ControllerClient
from runner.config import RunnerConfig
from runner.executor import TOOL_ID, TOOL_VERSION, LocalEchoExecutor
from runner.ledger import STATE_FINISHED, ExecutionLedger
from runner.store import ArtifactStore, content_hash


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
        purpose = assignment.get("purpose") or RunPurpose.LIMITED_ANALYSIS.value

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

        result_payload = {
            "outcome": output.outcome.value,
            "exit_code": output.exit_code,
            "output_artifact_id": output_artifact_id,
            "output_artifact_rev": 1,
            "usage": output.usage,
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
        """
        prompt = prompts.build(purpose, instruction)
        output = self.cli_executor.execute(
            run_id=assignment["run_id"],
            case_id=assignment["case_id"],
            prompt=prompt,
            tool_id=assignment["tool_id"],
            mode=assignment["mode"],
            permission=Permission(assignment["permission"]),
            workspace=Path(assignment["repo_path"]),
            raw_dir=self.config.raw_dir,
        )
        produced = self._produce_for_purpose(assignment, purpose, output)
        return output, produced

    def _produce_for_purpose(
        self, assignment: dict[str, Any], purpose: str, output: Any
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
                produced.update(self._produce_intent_draft(assignment, output))
            elif purpose == RunPurpose.INTENT_GATE_REVIEW.value:
                target = assignment.get("target_intent_version_id")
                if not target:
                    raise ValueError("검토할 의도 버전을 배정에서 찾지 못했다")
                produced["gate_findings"] = prompts.parse_gate_review(output.final_message)
                produced["intent_version_id"] = target
                produced["produced"] = "gate_review"
        except (ValueError, KeyError) as exc:
            output.outcome = RunOutcome.FAILED
            produced["produced"] = "none"
            produced["failure"] = f"{type(exc).__name__}: {exc}"
            produced.pop("gate_findings", None)
        return produced

    def _produce_intent_draft(self, assignment: dict[str, Any], output: Any) -> dict[str, Any]:
        """AI가 쓴 초안을 정규 문서로 저장하고 **의도 버전을 만든다.**

        P2-02의 경로와 방향이 반대다. 거기서는 사람이 화면에 입력한 항목이 제어부
        메모리를 지나 이 Runner로 왔다. 여기서는 초안이 이 Runner에서 태어나므로
        제어부에는 참조와 구조만 올라간다 — **본문은 올라가지 않는다.**
        """
        fields, questions, criteria = prompts.parse_intent_draft(output.final_message)
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
        }

    # -------------------------------------------------------------- 루프 한 회

    def poll_once(self) -> dict[str, Any]:
        self.client.heartbeat(self.config.runner_id)
        stored = self.persist_pending_intakes()
        served = self.serve_read_requests()
        actions = []
        for assignment in self.client.claim_assignments(self.config.runner_id):
            actions.append(self.handle_assignment(assignment))
        return {"stored_intakes": stored, "served_reads": served, "assignments": actions}

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
