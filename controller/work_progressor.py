"""업무 단계 진행기 (P4-05).

UI-03 의 요청 처리기는 저장된 요청마다 읽기 전용 논의 응답 하나를 만들고 업무화까지 했다. 그 뒤의
흐름(의도 초안 → QG-01 → repair → 질문·동의 → 준비 → 작업 그래프 → 구현·검증 → 완료)은 관리 화면의
버튼과 라이브 하네스가 이어 왔다. 이 모듈이 그 자리를 **제품 안에서** 채운다 — 사용자 결정
(2026-09-23)으로 P4-05 에 들어왔다.

**하는 일은 하나다.** 지금 상태에서 **다음 걸음 하나**를 정해(`domain.work_flow.next_step`) 실행
하나(또는 작업공간 요청·기록 하나)를 만들고 돌아온다. 사람이 필요한 곳에서 멈추고 요청을 끝내
전송을 연다(D-70). 사람의 결정이 오면 진행 요청을 열어 다시 잇는다.

**하지 않는 일:**

    진입 검사 우회            여기서 만든 실행도 `admit_and_create_run` 을 그대로 지난다. 거부되면
                              그 사유로 멈춘다(사람 사유 → 사람 대기, 환경 사유 → 막힘)
    사람의 결정               동의·확인·인수·예외는 사람 경로에서만 기록된다. 진행기는 "필요하다"를
                              값으로 낼 뿐이다
    통과할 때까지 반복        재작성·재시도 상한을 넘으면 사람에게 넘긴다
    진행 행이 없는 Case       업무화 때 행을 만든 Case 만 잇는다. 관리 화면·API 로 만든 Case 는 그대로
                              사람·하네스가 진행한다

**이벤트로 돈다**(처리기와 같다). 업무화 직후, 실행 결과 보고 뒤, 사람 입력 뒤, 작업공간 보고 뒤,
제어부 기동(복구)에서 부른다. 별도 스레드를 두지 않는다.
"""

from __future__ import annotations

from typing import Any

from controller.repository import ConflictError, ConversationRefused, NotFoundError, Repository
from domain import work_flow as workflow
from domain.models import (
    CaseStatus,
    GateId,
    RequestSettleOutcome,
    RequestState,
    RunPurpose,
    RunStatus,
)

#: 한 번의 `advance` 가 실행 없는 걸음(기록·후보)을 이어 가는 상한. 무한 반복을 막는다.
MAX_STEPS_PER_ADVANCE = 8

#: 진행기가 만든 실행 식별자의 접두사. 걸음·시도 번호를 넣어 같은 걸음의 두 번째 호출이 두 번째
#: 실행을 만들지 않게 한다(`admit_and_create_run` 의 멱등).
RUN_PREFIX = "wp"


def progress_run_id(case_id: str, code: str, attempt: int) -> str:
    tail = case_id.split("-")[-1][-12:]
    code_part = "".join(ch if ch.isalnum() else "-" for ch in code)[:24]
    return f"{RUN_PREFIX}-{tail}-{code_part}-{attempt}"[:64]


class WorkProgressor:
    """업무화된 Case 의 다음 걸음을 만든다. 판정은 `domain.work_flow` 에 있다."""

    def __init__(self, repo: Repository, *, enabled: bool) -> None:
        self.repo = repo
        self.enabled = enabled

    # ------------------------------------------------------------- 진입점

    def on_work_started(self, case_id: str, request_id: str | None) -> dict[str, Any] | None:
        """업무화 직후. 진행 행을 만들고, 요청에 끝나지 않은 실행이 없으면 첫 걸음을 만든다."""
        if not self.enabled:
            return None
        self.repo.start_progress(case_id, request_id)
        self.repo.record_progress_event(
            case_id, "work_started", "started", request_id=request_id, detail="업무화됐다"
        )
        if request_id is not None and any(
            r["status"] != RunStatus.FINISHED.value for r in self.repo.request_runs(request_id)
        ):
            return None  # 응답 실행이 아직 돌고 있다. 끝나면 `continue_request` 가 본다
        return self.advance(case_id, request_id)

    def continue_request(self, request_id: str) -> bool:
        """요청의 실행이 전부 끝났다. 다음 걸음을 만들면 `True`(요청은 처리 중으로 남는다).

        만들지 않았으면(사람 대기·완료·막힘·조건 그대로) 진행기가 요청을 끝냈거나 끝낼 것이 없다 —
        호출자(처리기)가 `False` 를 받아 자기 종료 기록을 적는다.
        """
        if not self.enabled:
            return False
        request = self.repo.get_request(request_id)
        if self.repo.progress_state(request["case_id"]) is None:
            return False
        result = self.advance(request["case_id"], request_id)
        return bool(result and (result.get("run_created") or result.get("keep_request")))

    def on_run_finished(self, run: dict[str, Any]) -> dict[str, Any] | None:
        """실행 결과 보고 뒤. 기준 보고를 적용하고, 요청이 없는 실행이면 다음 걸음을 본다."""
        if not self.enabled:
            return None
        case_id = run["case_id"]
        if self.repo.progress_state(case_id) is None:
            return None
        if self.repo.case_is_cancelled(case_id):
            # P4-09(e). 취소 뒤 도착한 결과 — 저장은 됐고(보고 경로) 기준 판정·재시도·다음 걸음은 없다.
            return None
        applied = self._apply_criteria(run)
        if run.get("request_id"):
            # 요청에 묶인 실행은 처리기가 `continue_request` 로 넘긴다(요청 종료와 한 자리).
            return {"criteria": applied}
        return self.advance(case_id, None)

    def on_human_input(self, case_id: str, *, origin_ref: str) -> dict[str, Any] | None:
        """사람의 결정·답변 뒤. 활성 요청이 없으면 다음 걸음을 만든다(필요하면 진행 요청을 연다)."""
        if not self.enabled:
            return None
        progress = self.repo.progress_state(case_id)
        if progress is None:
            return None
        if progress["state"] == workflow.ProgressState.PAUSED:
            return None  # 사람이 멈춘 진행은 사람이 계속 진행을 눌러야 이어 간다
        active = self.repo.active_request(case_id)
        if active is not None:
            # 사용자 요청이 처리 중이다 — 그 응답이 끝날 때 처리기가 넘긴다. 진행 요청이면 그 실행이
            # 끝날 때 본다.
            return None
        return self.advance(case_id, None, origin="human_decision", origin_ref=origin_ref)

    def on_gate_reviewed(self, case_id: str) -> dict[str, Any] | None:
        """QG-01 독립 검토 결과가 붙은 뒤(결과 보고 **뒤에** 온다). 그 판정으로 다음 걸음을 본다."""
        return self.on_workspace_reported(case_id)

    def on_workspace_reported(self, case_id: str) -> dict[str, Any] | None:
        if not self.enabled or self.repo.progress_state(case_id) is None:
            return None
        active = self.repo.active_request(case_id)
        return self.advance(case_id, active["id"] if active else None)

    def on_start_basis_decided(self, case_id: str, *, actor: str, basis: str) -> dict[str, Any] | None:
        """UI-04d(D-77). 사람이 시작 기준을 골랐다 — 작업공간은 `requested` 로 돌아갔고 Runner 가 다음
        회차에 만든다. 대기(`workspace_start_basis`)는 끝났으므로 진행을 다시 `running` 으로 두고 한 걸음
        본다(준비 보고가 오면 구현이 이어진다). 선택은 권한·동의가 아니다."""
        if not self.enabled:
            return None
        progress = self.repo.progress_state(case_id)
        if progress is None:
            return None
        self.repo.record_progress_event(
            case_id, "workspace_start_basis", "decided", detail=f"{basis} by {actor}",
        )
        if progress["state"] == workflow.ProgressState.WAITING_HUMAN and any(
            w.get("code") == workflow.WaitReason.WORKSPACE_START_BASIS for w in progress.get("wait") or []
        ):
            self.repo.update_progress(
                case_id,
                state=workflow.ProgressState.RUNNING,
                step="workspace_pending",
                detail="시작 기준을 정했다 — 작업공간 준비를 기다린다",
                keep_request=True,
            )
            self.repo.set_progress_case_status(case_id, CaseStatus.IN_PROGRESS)
        return self.on_workspace_reported(case_id)

    def resume(self, case_id: str, *, actor: str) -> dict[str, Any] | None:
        """사람이 멈춘·막힌·실패한 진행을 다시 잇는다(D-76·D-79)."""
        if not self.enabled:
            raise ConflictError("the work progressor is off (HADS_AUTO_PROCESS_REQUESTS=0)")
        progress = self.repo.progress_state(case_id)
        if progress is None:
            raise ConflictError("this case is not progressed by the product")
        self.repo.update_progress(
            case_id,
            state=workflow.ProgressState.RUNNING,
            step="resumed",
            detail=f"{actor} 가 계속 진행을 요청했다",
            keep_request=True,
        )
        self.repo.record_progress_event(case_id, "resumed", "resumed", detail=f"by {actor}")
        active = self.repo.active_request(case_id)
        if active is not None and active.get("origin") == "user_message":
            return {"action": "deferred", "detail": "사용자 요청 처리가 끝나면 이어 간다"}
        return self.advance(
            case_id, active["id"] if active else None, origin="system_resume", origin_ref=actor
        )

    def recover(self) -> dict[str, int]:
        """제어부 기동 때. 진행 중이던 Case 의 빠진 걸음을 잇는다."""
        counts = {"advanced": 0, "paused": 0}
        if not self.enabled:
            return counts
        for row in self.repo.progress_rows_for_recovery():
            case_id = row["case_id"]
            active = self.repo.active_request(case_id)
            if row["state"] == workflow.ProgressState.RUNNING:
                if active is None:
                    # 진행 중이었는데 요청이 끝나 있다(중단·불명 뒤 제어부가 끝냈다). 스스로 재개하지
                    # 않는다 — 사람이 상태를 보고 계속 진행을 누른다(D-76).
                    self._pause(case_id, "controller", "재시작 때 진행 요청이 이미 끝나 있었다")
                    counts["paused"] += 1
                    continue
                if any(
                    r["status"] != RunStatus.FINISHED.value
                    for r in self.repo.request_runs(active["id"])
                ):
                    continue  # 실행이 돌고 있다. 결과가 오면 본다
                if self.advance(case_id, active["id"]):
                    counts["advanced"] += 1
        return counts

    # ------------------------------------------------------------- 한 걸음

    def advance(
        self,
        case_id: str,
        request_id: str | None,
        *,
        origin: str = "human_decision",
        origin_ref: str | None = None,
    ) -> dict[str, Any] | None:
        """다음 걸음을 하나 만든다. 실행 없는 걸음(기록·후보)은 이어서 본다(상한 있음)."""
        if not self.enabled or self.repo.progress_state(case_id) is None:
            return None
        if self.repo.case_is_cancelled(case_id):
            # P4-09(e). 취소된 Case 에서는 아무 걸음도 만들지 않는다(늦은 결과·결정 무반응).
            return None
        outcome: dict[str, Any] = {"run_created": False, "steps": []}
        for _ in range(MAX_STEPS_PER_ADVANCE):
            state = self.repo.flow_state(case_id)
            step = workflow.next_step(state)
            # UI-05a(D-94). 명시로 켠 품질 게이트가 이 걸음을 막으면 진행기가 검토·수정을 먼저 돌린다.
            if step.kind == "run" and step.purpose in workflow.GATED_PURPOSES:
                gates = self.repo.quality_gate_progress(
                    case_id, step.purpose, step.task_id if step.task_id != "conversation" else ""
                )
                step = workflow.quality_gate_step(step, gates, state) or step
            # P4-10(이슈 #8, D-95). 같은 목적·작업이 같은 제한으로 시간 초과를 되풀이하려 하면 사람에게(제한을 늘린다).
            if step.kind == "run":
                step = workflow.run_timeout_step(step, state) or step
            outcome["steps"].append(step.to_dict())
            if step.kind == "busy":
                # 결과 보고 **뒤에** 오는 보고(독립 검토)를 기다리는 자리다. 요청을 끝내지 않는다 — 그
                # 보고가 오면 이어 가거나 사람 대기로 끝낸다.
                outcome["keep_request"] = step.code in ("gate_review_pending", "quality_gate_review_pending")
                return outcome
            if step.kind == "idle":
                return outcome
            if step.kind == "done":
                self._finish(case_id, request_id, step)
                return outcome
            if step.kind == "wait":
                self._wait(case_id, request_id, step)
                return outcome
            if step.kind == "blocked":
                self._block(case_id, request_id, step)
                return outcome
            if step.kind == "light_check":
                latest = state.intent["latest_intent_version"]
                try:
                    self.repo.record_light_conformance_check(latest["id"])
                    self.repo.record_progress_event(
                        case_id, step.code, "recorded", request_id=request_id,
                        detail="가벼운 정합성 확인을 기록했다(실행 없음)",
                    )
                except (ConflictError, NotFoundError) as exc:
                    self._wait(
                        case_id,
                        request_id,
                        workflow._wait(
                            workflow.WaitReason.GATE_REPAIR_EXHAUSTED,
                            detail=f"가벼운 확인을 기록하지 못했다: {exc}"[:200],
                        ),
                    )
                    return outcome
                continue
            if step.kind == "candidate":
                try:
                    candidate, created = self.repo.build_completion_candidate(case_id)
                    self.repo.record_progress_event(
                        case_id, step.code, "candidate", request_id=request_id,
                        detail=f"종료 후보 rev={candidate['revision']}"
                        + (" 을 만들었다" if created else " 그대로"),
                    )
                except (ConflictError, NotFoundError) as exc:
                    self._wait(
                        case_id,
                        request_id,
                        workflow._wait(
                            workflow.WaitReason.CRITERIA_UNRESOLVED,
                            detail=f"종료 후보를 만들지 못했다: {exc}"[:200],
                        ),
                    )
                    return outcome
                continue
            if step.kind == "remediation":
                # P4-10(이슈 #9). 검증 미충족의 수정 사이클 — 작업 그래프 새 리비전(출처 `progressor_remediation`)에
                # 수정 구현·재검증 작업을 더하고 다음 걸음(그 수정 작업)을 본다. 사람의 결정이 아니다.
                plan = step.remediation or {}
                try:
                    graph = self.repo.open_remediation_cycle(
                        case_id, plan, (state.remediation or {}).get("graph_revision")
                    )
                except (ConflictError, NotFoundError) as exc:
                    self._wait(
                        case_id,
                        request_id,
                        workflow._wait(
                            workflow.WaitReason.CRITERIA_UNRESOLVED,
                            detail=f"수정 사이클을 열지 못했다: {exc}"[:200],
                        ),
                    )
                    return outcome
                if graph is not None:
                    self.repo.record_progress_event(
                        case_id, step.code, "remediation_opened", request_id=request_id,
                        detail=(
                            f"r{graph['revision']} · {plan.get('cycle')}차 · 작업 "
                            + ", ".join([*plan.get("fix_tasks", []), plan.get("verify_task", "")])
                            + f" · 기준 {', '.join(plan.get('criteria', []))}"
                        )[:200],
                        codes=list(plan.get("criteria", [])),
                    )
                continue
            if step.kind == "workspace":
                request_id = self._ensure_request(case_id, request_id, origin, origin_ref)
                if request_id is None:
                    return outcome
                try:
                    self.repo.request_workspace(case_id, step.repository_id)
                except (ConflictError, NotFoundError) as exc:
                    self._wait(
                        case_id,
                        request_id,
                        workflow._wait(
                            workflow.WaitReason.REPOSITORY_SELECTION,
                            detail=f"작업공간을 요청하지 못했다: {exc}"[:200],
                        ),
                    )
                    return outcome
                self.repo.record_progress_event(
                    case_id, step.code, "workspace_requested", request_id=request_id,
                    detail=step.detail,
                )
                self.repo.update_progress(
                    case_id,
                    state=workflow.ProgressState.RUNNING,
                    step=step.code,
                    detail=step.detail,
                    request_id=request_id,
                )
                self.repo.set_progress_case_status(case_id, CaseStatus.IN_PROGRESS)
                outcome["run_created"] = True  # 요청은 열린 채 준비 보고를 기다린다
                return outcome
            if step.kind == "run":
                request_id = self._ensure_request(case_id, request_id, origin, origin_ref)
                if request_id is None:
                    return outcome
                made = self._create_run(case_id, request_id, state, step)
                outcome["run_created"] = made
                return outcome
            return outcome
        return outcome

    # ------------------------------------------------------------- 실행 만들기

    def _ensure_request(
        self, case_id: str, request_id: str | None, origin: str, origin_ref: str | None
    ) -> str | None:
        """실행을 붙일 요청. 없으면 진행 요청을 연다 — 잠금은 실행 사이에 풀리지 않는다(D-70)."""
        if request_id is not None:
            request = self.repo.get_request(request_id)
            if request["state"] == RequestState.PROCESSING.value and not request.get(
                "stop_requested_at"
            ):
                return request_id
            request_id = None
        active = self.repo.active_request(case_id)
        if active is not None:
            if active["state"] != RequestState.PROCESSING.value or active.get("stop_requested_at"):
                return None  # 잠긴·중단 중인 요청. 확인된 뒤 다시 본다
            if active.get("origin") == "user_message":
                return None  # 사용자 요청 처리 중 — 그 끝에서 처리기가 넘긴다
            return active["id"]
        opened = self.repo.open_progress_request(case_id, origin, origin_ref)
        if opened is None:
            return None
        self.repo.record_progress_event(
            case_id, "request", "request_opened", request_id=opened["id"],
            detail=f"진행 요청을 열었다({origin}: {origin_ref or '-'})",
        )
        self.repo.update_progress(
            case_id,
            state=workflow.ProgressState.RUNNING,
            step="request_opened",
            detail="사람의 결정 뒤 이어 간다",
            request_id=opened["id"],
        )
        return opened["id"]

    def _create_run(
        self, case_id: str, request_id: str, state: workflow.FlowState, step: workflow.Step
    ) -> bool:
        inputs = self.repo.progress_run_inputs(case_id)
        tool = inputs["tool"]
        if tool is None:
            self._block(
                case_id,
                request_id,
                workflow._blocked(
                    workflow.BlockReason.TOOL_UNAVAILABLE,
                    detail=f"{inputs['default_tool_id']} 가 {inputs['runner_id'] or '알 수 없는 PC'}"
                    " 에서 코딩 CLI 로 확인되지 않았다",
                ),
            )
            return False
        if step.instruction == "latest_intent":
            latest = state.intent["latest_intent_version"]
            instruction = (latest["artifact_id"], latest["artifact_rev"])
        else:
            instruction = inputs["work_request"]
        attempt = self.repo.bump_attempt(case_id, step.attempt_key) if step.attempt_key else 1
        run_id = progress_run_id(case_id, step.code, attempt)
        try:
            run, created, admission, _check = self.repo.admit_and_create_run(
                case_id=case_id,
                run_id=run_id,
                task_id=step.task_id,
                purpose=step.purpose,
                role=step.role,
                tool_id=tool["tool_id"],
                mode=tool["mode"],
                permission=step.permission,
                instruction_artifact_id=instruction[0],
                instruction_artifact_rev=instruction[1],
                repository_id=step.repository_id,
                request_id=request_id,
            )
        except (ConflictError, NotFoundError) as exc:
            self._block(
                case_id,
                request_id,
                workflow._blocked(workflow.BlockReason.RUN_NOT_CREATED, detail=str(exc)[:200]),
            )
            return False
        if admission is not None and not admission.admitted:
            codes = [r.value for r in admission.refusals]
            kind, picked = workflow.classify_refusals(codes)
            self.repo.record_progress_event(
                case_id, step.code, "admission_refused", request_id=request_id,
                detail=f"{step.purpose.value} 거부: {', '.join(codes)}"[:200], codes=codes,
            )
            if kind == "done":
                self._finish(case_id, request_id, workflow.Step("done", "closed", "종료된 업무다"))
            elif kind == "human":
                self._wait(
                    case_id,
                    request_id,
                    workflow._wait(
                        workflow.wait_reason_for(picked),
                        detail="; ".join(admission.reasons.get(c, c) for c in picked)[:200],
                        refusals=codes,
                    ),
                )
            elif kind == "transient":
                # 곧 달라질 상태(쓰기 직렬화·작업공간 준비 중). 요청은 열어 두고 다음 사건을 기다린다.
                self.repo.update_progress(
                    case_id,
                    state=workflow.ProgressState.RUNNING,
                    step=step.code,
                    detail="잠시 뒤 다시 본다: " + ", ".join(picked),
                    request_id=request_id,
                )
            else:
                self._block(
                    case_id,
                    request_id,
                    workflow._blocked(
                        workflow.block_reason_for(picked),
                        detail="; ".join(admission.reasons.get(c, c) for c in picked)[:200],
                        refusals=codes,
                    ),
                )
            return False
        self.repo.record_progress_event(
            case_id, step.code, "run_created" if created else "run_exists",
            run_id=run["run_id"], request_id=request_id, detail=step.detail,
        )
        if created and step.gate:
            self._link_gate(case_id, run["run_id"], step)
        self.repo.update_progress(
            case_id,
            state=workflow.ProgressState.RUNNING,
            step=step.code,
            detail=step.detail,
            request_id=request_id,
            last_run_id=run["run_id"],
        )
        self.repo.set_progress_case_status(case_id, CaseStatus.IN_PROGRESS)
        return True

    def _link_gate(self, case_id: str, run_id: str, step: workflow.Step) -> None:
        """UI-05a(D-94). 검토 실행이면 검증 1회를 열고, repair 실행이면 수정 차수를 예약한다.

        실패해도 실행은 그대로 돈다 — 열지 못한 검증은 기록되지 않고 다음 걸음이 다시 보며, 예약하지 못한
        차수는 한도 계산에서 빠질 뿐이다(사유는 진행 이력에 남긴다).
        """
        gate = step.gate or {}
        try:
            gate_id = GateId(gate["gate"])
            if gate.get("action") == "review":
                opened = self.repo.open_gate_review(case_id, gate_id, gate.get("task_key") or "", run_id)
                detail = f"{gate_id.value} 검증 1회를 열었다" if opened else f"{gate_id.value} 검증을 열지 못했다"
            else:
                self.repo.start_remediation_attempt(
                    case_id, gate_id, gate["subject_key"], kind="product_repair",
                    task_key=gate.get("task_key") or "", author_run_id=run_id,
                )
                detail = f"{gate_id.value} 수정 차수를 예약했다"
        except (ConflictError, NotFoundError, KeyError, ValueError) as exc:
            detail = f"게이트 기록 연결 실패: {exc}"[:200]
        self.repo.record_progress_event(case_id, step.code, "recorded", run_id=run_id, detail=detail)

    # ------------------------------------------------------------- 멈춤

    def _settle(self, case_id: str, request_id: str | None, outcome: RequestSettleOutcome, note: str) -> None:
        if request_id is None:
            return
        try:
            request = self.repo.get_request(request_id)
        except NotFoundError:
            return
        if request["state"] != RequestState.PROCESSING.value:
            return
        # 사용자 요청도 여기서 끝낸다 — 처리기는 응답이 붙은 뒤 진행기에 넘겼고, 그 요청의 마지막
        # 걸음이 사람 대기·완료·막힘이면 그 사유가 요청에 남아야 한다. 처리기의 뒤이은 종료 기록은
        # 같은 결과의 재전송으로 흡수된다.
        try:
            self.repo.settle_request(
                case_id, request_id, outcome, self.repo.WORK_PROGRESSOR_ACTOR, note
            )
        except ConversationRefused:
            return  # 실행이 남았거나 중단 중이다 — 그쪽 판정이 끝낸다

    def _wait(self, case_id: str, request_id: str | None, step: workflow.Step) -> None:
        current = self.repo.progress_state(case_id) or {}
        same = (
            current.get("state") == workflow.ProgressState.WAITING_HUMAN
            and current.get("step") == step.code
            and current.get("wait") == list(step.reasons)
        )
        if same:
            # 같은 대기를 다시 적지 않는다 — 사람 입력·업무 단계 대화마다 이력이 늘지 않게. 사용자
            # 요청이면 처리기가 그 응답으로 끝낸다(진행은 조건 그대로다).
            if request_id is not None and self.repo.get_request(request_id).get("origin") != "user_message":
                self._settle(case_id, request_id, RequestSettleOutcome.COMPLETED, workflow.settle_note(step))
            return
        self.repo.record_progress_event(
            case_id, step.code, "waiting_human", request_id=request_id, detail=step.detail,
            codes=[step.code],
        )
        self.repo.update_progress(
            case_id,
            state=workflow.ProgressState.WAITING_HUMAN,
            step=step.code,
            detail=step.detail,
            wait=list(step.reasons),
            request_id=None,
        )
        self.repo.set_progress_case_status(case_id, CaseStatus.WAITING_HUMAN)
        self._settle(case_id, request_id, RequestSettleOutcome.COMPLETED, workflow.settle_note(step))

    def _block(self, case_id: str, request_id: str | None, step: workflow.Step) -> None:
        self.repo.record_progress_event(
            case_id, step.code, "blocked", request_id=request_id, detail=step.detail,
            codes=[step.code],
        )
        self.repo.update_progress(
            case_id,
            state=workflow.ProgressState.BLOCKED,
            step=step.code,
            detail=step.detail,
            wait=list(step.reasons),
            request_id=None,
        )
        self.repo.set_progress_case_status(case_id, CaseStatus.WAITING_ENVIRONMENT)
        self._settle(case_id, request_id, RequestSettleOutcome.FAILED, workflow.settle_note(step))

    def _finish(self, case_id: str, request_id: str | None, step: workflow.Step) -> None:
        self.repo.record_progress_event(
            case_id, step.code, "done", request_id=request_id, detail=step.detail
        )
        self.repo.update_progress(
            case_id,
            state=workflow.ProgressState.DONE,
            step=step.code,
            detail=step.detail,
            request_id=None,
        )
        self._settle(case_id, request_id, RequestSettleOutcome.COMPLETED, workflow.settle_note(step))

    def _pause(self, case_id: str, by: str, detail: str) -> None:
        self.repo.record_progress_event(case_id, "paused", "paused", detail=detail)
        self.repo.update_progress(
            case_id,
            state=workflow.ProgressState.PAUSED,
            step="paused",
            detail=detail,
            request_id=None,
            paused_by=by,
        )

    def check_request(self, request_id: str) -> None:
        """요청이 중단·불명으로 끝났으면 진행을 멈춤으로 표시한다(결과 보고·중단 뒤에 부른다)."""
        if not self.enabled:
            return
        try:
            request = self.repo.get_request(request_id)
        except NotFoundError:
            return
        if request["state"] in (RequestState.INTERRUPTED.value, RequestState.UNKNOWN.value):
            self.on_request_interrupted(request)

    def on_request_interrupted(self, request: dict[str, Any]) -> None:
        """진행 요청이 중단·불명으로 끝났다(UI-02 의 제어부 판정). 스스로 재개하지 않는다(D-76)."""
        if not self.enabled or request.get("origin") == "user_message":
            return
        progress = self.repo.progress_state(request["case_id"])
        if progress is None or progress.get("request_id") != request["id"]:
            return
        if progress["state"] in (workflow.ProgressState.RUNNING,):
            self._pause(
                request["case_id"],
                request.get("stop_requested_by") or "controller",
                f"진행 요청 {request['id']} 가 {request['state']} 로 끝났다. 계속 진행은 사람이 누른다",
            )

    # ------------------------------------------------------------- 기준 보고

    def _apply_criteria(self, run: dict[str, Any]) -> list[dict[str, Any]]:
        if run.get("purpose") not in (
            RunPurpose.VERIFICATION_RUN.value,
            RunPurpose.LIMITED_ANALYSIS.value,
            RunPurpose.LOCAL_EXPERIMENT.value,
        ):
            return []
        try:
            applied = self.repo.apply_criteria_report(run["run_id"])
        except (ConflictError, NotFoundError) as exc:
            self.repo.record_progress_event(
                run["case_id"], "criteria", "criteria_refused", run_id=run["run_id"],
                detail=str(exc)[:200],
            )
            return []
        if applied:
            recorded = [a["key"] for a in applied if a["recorded"]]
            skipped = [f"{a['key']}:{a['reason']}" for a in applied if not a["recorded"]]
            self.repo.record_progress_event(
                run["case_id"], "criteria", "criteria_recorded", run_id=run["run_id"],
                detail=(
                    f"기록 {', '.join(recorded) or '없음'}"
                    + (f" · 적지 않음 {', '.join(skipped)}" if skipped else "")
                )[:200],
                codes=recorded,
            )
        return applied
