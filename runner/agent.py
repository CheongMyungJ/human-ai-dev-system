"""Runner 루프.

한 번의 `poll_once()` 가 하는 일:

  1. 생존 보고
  2. 맡을 원문을 가져와 로컬에 영속 저장하고 "저장했다"고 보고 → 그때가 저장 완료
  3. 배정을 받아 실행하고 이벤트·결과를 보고

중복 실행 방지는 3에서 실행 원장(`runner.ledger`)이 맡는다. 같은 `run_id` 가
다시 배정돼도 executor를 부르지 않는다. 자세한 이유는 `runner/ledger.py` 참조.
"""

from __future__ import annotations

import base64
import time
from typing import Any

from domain import ids
from domain.models import CapabilityState, RunOutcome
from runner.client import ControllerClient
from runner.config import RunnerConfig
from runner.executor import TOOL_ID, TOOL_VERSION, LocalEchoExecutor
from runner.ledger import STATE_FINISHED, ExecutionLedger
from runner.store import ArtifactStore, content_hash


def default_capabilities() -> list[dict[str, Any]]:
    """이 Runner가 지금 실제로 무엇을 할 수 있는지.

    P2-01의 실행기는 코딩 CLI가 아니므로 CLI 능력을 `verified` 로 올리지 않는다.
    Codex·Claude 의 실측 능력은 p1-environment-contract.md 8절에 있고,
    제품 어댑터가 붙는 P2-03에서 그 값을 보고한다.
    """
    source = "P2-01 local executor (not a coding CLI)"
    return [
        {
            "tool_id": TOOL_ID,
            "mode": "p2-01-local",
            "capability": capability,
            "state": state.value,
            "source": source,
        }
        for capability, state in (
            ("structured_events", CapabilityState.VERIFIED),
            ("session_identity", CapabilityState.UNSUPPORTED),
            ("tool_boundary_observed", CapabilityState.UNSUPPORTED),
            ("usage_reporting", CapabilityState.UNSUPPORTED),
            ("safe_stop_next_call", CapabilityState.UNSUPPORTED),
        )
    ]


class RunnerAgent:
    def __init__(
        self,
        config: RunnerConfig,
        client: ControllerClient,
        executor: LocalEchoExecutor | None = None,
    ) -> None:
        config.ensure_dirs()
        self.config = config
        self.client = client
        self.store = ArtifactStore(config.artifacts_dir)
        self.ledger = ExecutionLedger(config.ledger_dir)
        self.executor = executor or LocalEchoExecutor(config.effects_dir)

    # ------------------------------------------------------------------ 등록

    def register(self) -> Any:
        return self.client.register(
            self.config.runner_id,
            name=self.config.runner_id,
            host=self.config.host_name,
            capabilities=default_capabilities(),
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
        return stored

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
        output = self.executor.execute(run_id, case_id, instruction)

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
            "observed_tool_version": f"{TOOL_ID}/{TOOL_VERSION}",
        }
        # 결과를 **보고하기 전에** 원장에 확정한다. 보고가 유실돼도
        # 같은 run_id 가 다시 오면 재실행하지 않고 이 결과를 다시 보낸다.
        self.ledger.finish(run_id, result_payload)

        send_payload = dict(result_payload)
        send_payload["runner_id"] = self.config.runner_id
        send_payload["generation"] = generation
        self.client.send_result(run_id, send_payload)
        return {"run_id": run_id, "action": "executed"}

    # -------------------------------------------------------------- 루프 한 회

    def poll_once(self) -> dict[str, Any]:
        self.client.heartbeat(self.config.runner_id)
        stored = self.persist_pending_intakes()
        actions = []
        for assignment in self.client.claim_assignments(self.config.runner_id):
            actions.append(self.handle_assignment(assignment))
        return {"stored_intakes": stored, "assignments": actions}

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
