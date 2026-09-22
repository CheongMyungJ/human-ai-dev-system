"""제어부 HTTP API.

두 묶음으로 나뉜다.

  `/api/...`         웹 UI가 쓰는 업무 API
  `/api/runner/...`  Runner가 **먼저 연결해서** 쓰는 계약
                     (implementation-baseline 2절: PC 수신 포트를 필수로 열지 않는다)

원문 본문이 지나가는 곳은 `POST /api/cases/{case_id}/artifacts` 하나뿐이고,
그 본문은 메모리 중계 버퍼에만 들어간다. 응답·로그·DB에는 넣지 않는다.
"""

from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from controller.relay import content_hash
from controller.repository import (
    AcceptanceRefused,
    ConflictError,
    NotFoundError,
    PolicyRefused,
    Repository,
)
from domain import ids, intent_doc
from domain import profiles as case_profiles
from domain.models import (
    Satisfaction,
    AcceptanceMode,
    AcceptanceRefusal,
    AgreementRefusal,
    ArtifactKind,
    AuthoringMode,
    Autonomy,
    Availability,
    AxisWeight,
    BudgetMetric,
    BudgetThreshold,
    CaseKind,
    CaseProfile,
    CompletionMode,
    ControlledCheckpoint,
    ConfirmationState,
    ContentOrigin,
    CriterionVerdict,
    DecideAt,
    DecisionKind,
    DelegationBasisKind,
    EvidenceKind,
    GateId,
    IntentField,
    Permission,
    PreparationStage,
    ReadRequestState,
    RepositorySelectionSource,
    ReviewMode,
    RunOutcome,
    RunPurpose,
    RunRole,
    SizingAxis,
    TaskKind,
    WorkLevel,
)

router = APIRouter()


def _repo(request: Request) -> Repository:
    return Repository(request.app.state.conn)


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, AcceptanceRefused):
        # 사유 코드를 구조로 돌려준다. 화면과 직접 API 호출이 같은 코드를 받아야
        # "왜 종료가 확정되지 않았는가"를 같은 근거로 설명할 수 있다.
        return HTTPException(
            status_code=409,
            detail={
                "refusals": [r.value for r in exc.refusals],
                "message": str(exc),
            },
        )
    if isinstance(exc, PolicyRefused):
        # 정책 거절도 구조로 돌려준다(P3-R1). 화면과 직접 호출이 같은 코드를 받아야
        # "왜 이 설정을 받지 않았는가"를 같은 근거로 설명할 수 있다.
        return HTTPException(
            status_code=409,
            detail={
                "refusals": [r.value for r in exc.refusals],
                "message": str(exc),
            },
        )
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    raise exc


# --------------------------------------------------------------------- models


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    repo_path: str = Field(min_length=1)
    default_tool_id: str = Field(default="codex")


class CaseIn(BaseModel):
    """Case 생성 입력.

    **P3-R1: `profile` 이 대표 목적의 축이다**(D-62). 주면 그 값이 기록되고
    `kind` 는 유도된다. 주지 않으면 `kind` 에서 Profile 을 유도하며 그 사실이
    `profile_source = derived_from_kind` 로 남는다 — 사람의 선택이 아니기 때문이다.

    둘을 함께 주고 서로 맞지 않으면 **거부한다.** 한쪽을 조용히 이기게 만들면
    기록된 목적과 요청한 목적이 달라진다.
    """

    title: str = Field(min_length=1, max_length=200)
    kind: CaseKind | None = None
    profile: CaseProfile | None = None


class ArtifactIn(BaseModel):
    """원문 제출.

    `content` 는 서버에 저장되지 않는다. 중계 버퍼를 거쳐 Runner로 간다.
    `summary` 는 호출자가 주는 짧은 표시용 문구이며 본문에서 뽑지 않는다.
    """

    kind: ArtifactKind
    content: str = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=200)
    target_runner_id: str


class IntentVersionIn(BaseModel):
    artifact_id: str
    revision: int = 1


class DecisionIn(BaseModel):
    kind: DecisionKind
    subject_type: str
    subject_id: str
    subject_revision: int
    actor: str = "owner"
    evidence_ref: str | None = None


class RunIn(BaseModel):
    """실행 요청.

    `purpose` 를 기본값 없이 두지 않는 이유는 기존 호출(P2-01·P2-02 시험)이
    목적 없이 Run을 만들었기 때문이다. 기본값은 가장 좁은 목적인
    `limited_analysis` 이며, 그 목적이 가장 많은 조건을 받는다 — 기본값을 택해서
    조건을 덜 받는 일이 없게 한다.
    """

    run_id: str | None = None
    task_id: str = "task-1"
    purpose: RunPurpose = RunPurpose.LIMITED_ANALYSIS
    role: RunRole = RunRole.AUTHOR
    tool_id: str = "local-echo"
    mode: str = "p2-01-local"
    permission: Permission = Permission.READ_ONLY
    instruction_artifact_id: str
    instruction_artifact_rev: int = 1
    #: `new` 만 허용한다. 세션을 이어받는 검토는 별도 세션 요구를 어긴다(FR-29).
    session: str = "new"
    #: **어느 저장소의 작업공간에서 도는가**(P3-R2·D-39). 작업공간이 하나뿐이면
    #: 생략할 수 있다. 둘 이상인데 생략하면 `workspace_target_not_recorded` 로
    #: 거부된다 — 어느 저장소를 고칠지 모르는 채로 쓰기를 열지 않는다.
    repository_id: str | None = None


class RunnerRegisterIn(BaseModel):
    runner_id: str
    name: str
    host: str
    capabilities: list[dict[str, Any]] = Field(default_factory=list)


class RunnerArtifactIn(BaseModel):
    """Runner가 이미 저장한 산출물의 참조 등록. 본문은 보내지 않는다."""

    runner_id: str
    case_id: str
    kind: ArtifactKind
    artifact_id: str
    revision: int = 1
    content_hash: str
    byte_size: int
    summary: str = Field(min_length=1, max_length=200)


class StoredIn(BaseModel):
    runner_id: str
    content_hash: str


class EventIn(BaseModel):
    seq: int
    ts: str
    type: str
    native_type: str | None = None
    raw_ref: str | None = None


class EventsIn(BaseModel):
    runner_id: str
    generation: int
    events: list[EventIn]


class ResultIn(BaseModel):
    runner_id: str
    generation: int
    outcome: RunOutcome
    exit_code: int | None = None
    output_artifact_id: str | None = None
    output_artifact_rev: int | None = None
    session_ref: str | None = None
    usage: Any = "not_reported"
    workspace_effect: dict[str, Any] | None = None
    residual_activity: str = "unknown"
    observed_tool_version: str | None = None


# ---------------------------------------------------------------- idempotency


def _idempotent(
    request: Request, key: str | None, endpoint: str, produce
) -> tuple[Any, int, bool]:
    """같은 요청 키의 재전송에 저장된 응답을 그대로 돌려준다.

    반환: (응답 본문, 상태 코드, 이번에 실제로 수행했는지)
    """
    repo = _repo(request)
    if key:
        cached = repo.cached_response(key)
        if cached is not None:
            return cached["body"], cached["status_code"], False
    body, status = produce()
    if key:
        repo.store_response(key, endpoint, status, body)
    return body, status, True


# -------------------------------------------------------------- web-facing


@router.get("/api/health")
def health(request: Request) -> dict[str, Any]:
    return {
        "status": "ok",
        "schema_version": request.app.state.conn.execute(
            "SELECT MAX(version) AS v FROM schema_version"
        ).fetchone()["v"],
        "relay_buffered": len(request.app.state.relay),
    }


@router.post("/api/projects", status_code=201)
def create_project(
    request: Request, payload: ProjectIn, idempotency_key: str | None = Header(default=None)
) -> Any:
    repo = _repo(request)

    def produce():
        try:
            return repo.create_project(payload.name, payload.repo_path, payload.default_tool_id), 201
        except (NotFoundError, ConflictError) as exc:
            raise _handle(exc)

    body, _status, _created = _idempotent(request, idempotency_key, "create_project", produce)
    return body


@router.get("/api/projects")
def list_projects(request: Request) -> list[dict[str, Any]]:
    return _repo(request).list_projects()


@router.get("/api/projects/{project_id}")
def get_project(request: Request, project_id: str) -> dict[str, Any]:
    try:
        return _repo(request).get_project(project_id)
    except NotFoundError as exc:
        raise _handle(exc)


@router.post("/api/projects/{project_id}/cases", status_code=201)
def create_case(
    request: Request,
    project_id: str,
    payload: CaseIn,
    idempotency_key: str | None = Header(default=None),
) -> Any:
    repo = _repo(request)

    if payload.profile is not None and payload.kind is not None:
        expected = case_profiles.KIND_FOR_PROFILE[payload.profile]
        if expected is not payload.kind:
            raise HTTPException(
                status_code=409,
                detail=f"profile {payload.profile.value} implies kind {expected.value},"
                f" not {payload.kind.value}",
            )
    # 둘 다 없으면 P2-01부터의 기본값(`feature`)을 그대로 쓴다. 기본값이 붙었다는
    # 사실은 `profile_source = derived_from_kind` 로 남는다.
    kind = payload.kind or (None if payload.profile else CaseKind.FEATURE)

    def produce():
        try:
            return repo.create_case(project_id, payload.title, kind, payload.profile), 201
        except (NotFoundError, ConflictError) as exc:
            raise _handle(exc)

    body, _status, _created = _idempotent(request, idempotency_key, "create_case", produce)
    return body


@router.get("/api/projects/{project_id}/cases")
def list_cases(request: Request, project_id: str) -> list[dict[str, Any]]:
    try:
        return _repo(request).list_cases(project_id)
    except NotFoundError as exc:
        raise _handle(exc)


@router.get("/api/cases/{case_id}")
def get_case(request: Request, case_id: str) -> dict[str, Any]:
    repo = _repo(request)
    try:
        case = repo.get_case(case_id)
    except NotFoundError as exc:
        raise _handle(exc)
    case["artifacts"] = repo.list_artifact_refs(case_id)
    # 의도 버전은 항목별 상태·질문까지 함께 보낸다. 화면이 "여섯 항목 중 무엇이
    # 미정인가"를 전체 대화를 다시 읽지 않고 알 수 있어야 한다(FR-14).
    case["intent_versions"] = [
        repo.get_intent_detail(iv["id"]) for iv in repo.list_intent_versions(case_id)
    ]
    case["decisions"] = repo.list_decisions(case_id)
    case["feedback"] = repo.list_feedback(case_id)
    case["intent_state"] = repo.intent_state(case_id)
    case["runs"] = repo.list_runs(case_id)
    # 게이트 판정과 진입 검사 기록을 함께 준다. 사람이 "왜 실행이 시작되지
    # 않았는가"를 다른 화면을 찾아다니지 않고 알 수 있어야 한다(FR-14).
    case["gate"] = repo.gate_state(case_id)
    case["quality_gates"] = repo.quality_gate_state(case_id)
    case["admission_checks"] = repo.list_admission_checks(case_id)
    # 수준·설계·계획·검토 상태도 같은 응답에 담는다(P3-01). 화면이 "지금 무엇이
    # 빠져 있어 구현이 열리지 않는가"를 한 화면에서 알 수 있어야 한다(FR-14).
    case["preparation"] = repo.preparation_state(case_id)
    # 결과·완료 상태도 같은 응답에 담는다. "현재 무엇을 기다리는가"를 알기 위해
    # 다른 화면을 찾아다니게 하지 않는다(FR-14).
    case["result"] = repo.result_view(case_id)
    # 작업공간 상태도 같은 응답에 담는다(P3-03). "어떤 코드 위에서 어디에 만들고
    # 있는가"와 "왜 쓰기가 아직 열리지 않는가"를 한 화면에서 본다(FR-14).
    case["workspace"] = repo.workspace_view(case_id)
    # 정책·Profile·예산·저장소도 같은 응답에 담는다(P3-R1). "지금 어떤 확인 경계와
    # 한도로 진행하는가"와 "그 값이 실제로 강제되는가"를 한 화면에서 본다(FR-14).
    case["policy"] = repo.effective_policy(case_id)
    return case


@router.post("/api/cases/{case_id}/artifacts", status_code=202)
def submit_artifact(request: Request, case_id: str, payload: ArtifactIn) -> dict[str, Any]:
    """원문을 접수한다. **저장 완료가 아니다.**

    202를 돌려주는 이유가 여기 있다. 소유 Runner가 영속 저장을 보고해야
    `availability` 가 `available` 이 되고 그때가 저장 완료다(NFR-01, D-51).
    """
    repo = _repo(request)
    body = payload.content.encode("utf-8")
    digest = content_hash(body)
    try:
        intake = repo.open_intake(
            case_id=case_id,
            kind=payload.kind,
            target_runner_id=payload.target_runner_id,
            expected_hash=digest,
            byte_size=len(body),
            summary=payload.summary,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)
    request.app.state.relay.put(intake["id"], body)
    return {
        "intake_id": intake["id"],
        "artifact_id": intake["artifact_id"],
        "revision": intake["revision"],
        "state": intake["state"],
        "availability": Availability.PENDING.value,
        "content_hash": digest,
        "note": "relayed to the owning runner; not stored on the controller",
    }


@router.get("/api/intakes/{intake_id}")
def get_intake(request: Request, intake_id: str) -> dict[str, Any]:
    try:
        return _repo(request).get_intake(intake_id)
    except NotFoundError as exc:
        raise _handle(exc)


@router.post("/api/cases/{case_id}/intent-versions", status_code=201)
def create_intent_version(
    request: Request,
    case_id: str,
    payload: IntentVersionIn,
    idempotency_key: str | None = Header(default=None),
) -> Any:
    repo = _repo(request)

    def produce():
        try:
            return repo.create_intent_version(case_id, payload.artifact_id, payload.revision), 201
        except (NotFoundError, ConflictError) as exc:
            raise _handle(exc)

    body, _status, _created = _idempotent(request, idempotency_key, "create_intent_version", produce)
    return body


@router.post("/api/cases/{case_id}/decisions", status_code=201)
def record_decision(
    request: Request,
    case_id: str,
    payload: DecisionIn,
    idempotency_key: str | None = Header(default=None),
) -> Any:
    repo = _repo(request)

    # 의도 동의는 이 일반 경로로 기록하지 않는다. 전용 경로가 최신 버전·원문 확인·
    # 열람 기록·미해결 질문을 검사하는데, 여기로 들어오면 그 검사를 통째로 건너뛴다.
    # 화면에서 버튼을 없애는 것만으로는 부족하다 — API 직접 호출도 같은 규칙을 받는다.
    if payload.kind is DecisionKind.INTENT_AGREEMENT:
        raise HTTPException(
            status_code=409,
            detail=(
                "record an intent agreement through"
                " POST /api/cases/{case_id}/intent-versions/{intent_id}/agreement;"
                " that path checks the latest version, the readable original and open questions"
            ),
        )

    def produce():
        try:
            return (
                repo.record_decision(
                    case_id=case_id,
                    kind=payload.kind,
                    subject_type=payload.subject_type,
                    subject_id=payload.subject_id,
                    subject_revision=payload.subject_revision,
                    actor=payload.actor,
                    evidence_ref=payload.evidence_ref,
                ),
                201,
            )
        except (NotFoundError, ConflictError) as exc:
            raise _handle(exc)

    body, _status, _created = _idempotent(request, idempotency_key, "record_decision", produce)
    return body


@router.post("/api/cases/{case_id}/runs", status_code=201)
def create_run(
    request: Request, case_id: str, payload: RunIn, response: Response
) -> dict[str, Any]:
    """Run 생성. `run_id` 가 멱등 키이고 **진입 조건 검사를 통과해야 만들어진다.**

    같은 `run_id` 로 다시 호출하면 새 Run도 새 배정도 만들지 않고 기존 Run을 돌려준다.
    그 경우 상태 코드는 **200**이다. 만들지 않은 것을 201 Created 로 보고하지 않는다.

    조건을 갖추지 못하면 **409**와 함께 사유 코드를 돌려준다. 이 검사는 화면과
    무관하게 여기서 이뤄지므로 버튼을 우회한 직접 호출도 같은 답을 받는다(FR-29).
    """
    repo = _repo(request)
    run_id = payload.run_id or ids.new_run_id()
    try:
        run, created, admission, check = repo.admit_and_create_run(
            case_id=case_id,
            run_id=run_id,
            task_id=payload.task_id,
            purpose=payload.purpose,
            role=payload.role,
            tool_id=payload.tool_id,
            mode=payload.mode,
            permission=payload.permission,
            instruction_artifact_id=payload.instruction_artifact_id,
            instruction_artifact_rev=payload.instruction_artifact_rev,
            session=payload.session,
            repository_id=payload.repository_id,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)

    if admission is not None and not admission.admitted:
        raise HTTPException(
            status_code=409,
            detail={
                "admission": admission.to_dict(),
                "admission_check_id": (check or {}).get("id"),
                "message": "entry conditions are not met; the run was not created",
            },
        )
    if not created:
        response.status_code = 200
    return {
        "run": run,
        "created": created,
        # 재전송이면 검사하지 않았다는 사실을 그대로 돌려준다. 하지 않은 검사를
        # 통과로 적지 않는다.
        "admission": admission.to_dict() if admission is not None else None,
    }


@router.get("/api/runs/{run_id}")
def get_run(request: Request, run_id: str) -> dict[str, Any]:
    repo = _repo(request)
    try:
        run = repo.get_run(run_id)
    except NotFoundError as exc:
        raise _handle(exc)
    run["events"] = repo.list_events(run_id)
    # 무엇을 실제로 실행했는가(P3-03). 원문은 Runner 의 산출물에 있다.
    run["commands"] = repo.list_run_commands(run_id)
    return run


@router.post("/api/runs/{run_id}/reassign")
def reassign(request: Request, run_id: str) -> dict[str, Any]:
    """배정 세대를 올린다.

    이 호출은 "이전 실행자가 멈췄다"를 뜻하지 않는다. 오래된 실행자의 보고를
    거부하기 위한 fencing 일 뿐이다.
    """
    try:
        return _repo(request).bump_generation(run_id)
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.get("/api/runners")
def list_runners(request: Request) -> list[dict[str, Any]]:
    return _repo(request).list_runners()


# ------------------------------------------------------------ runner-facing


@router.post("/api/runner/register")
def runner_register(request: Request, payload: RunnerRegisterIn) -> dict[str, Any]:
    return _repo(request).register_runner(
        payload.runner_id, payload.name, payload.host, payload.capabilities
    )


@router.post("/api/runner/{runner_id}/heartbeat")
def runner_heartbeat(request: Request, runner_id: str) -> dict[str, str]:
    try:
        _repo(request).heartbeat(runner_id)
    except NotFoundError as exc:
        raise _handle(exc)
    return {"status": "ok"}


@router.get("/api/runner/{runner_id}/intakes")
def runner_intakes(request: Request, runner_id: str) -> list[dict[str, Any]]:
    """이 Runner가 영속 저장해야 할 원문을 가져간다.

    중계 버퍼에 본문이 없으면(대표 사례: 제어부 재시작) 그 접수는
    `lost_before_persist` 로 표시하고 내려주지 않는다. 빈 본문으로 채우지 않는다.
    """
    repo = _repo(request)
    relay = request.app.state.relay
    out: list[dict[str, Any]] = []
    for intake in repo.list_pending_intakes(runner_id):
        body = relay.get(intake["id"])
        if body is None:
            repo.mark_intake_lost(intake["id"])
            continue
        item = {
            "intake_id": intake["id"],
            "case_id": intake["case_id"],
            "kind": intake["kind"],
            "artifact_id": intake["artifact_id"],
            "revision": intake["revision"],
            "expected_hash": intake["expected_hash"],
            "content_b64": base64.b64encode(body).decode("ascii"),
        }
        if intake["kind"] == ArtifactKind.INTENT.value:
            # 제어부는 본문을 모르지만 **어느 원문과 비교해야 하는지**는 알려 줄 수 있다.
            # 버전 차이는 두 원문을 모두 가진 Runner가 계산한다(P2-02 설계 선택 나).
            item["intent"] = repo.intent_intake_context(
                intake["artifact_id"], intake["revision"]
            )
        out.append(item)
    return out


@router.post("/api/runner/intakes/{intake_id}/stored")
def runner_intake_stored(request: Request, intake_id: str, payload: StoredIn) -> dict[str, Any]:
    """Runner가 영속 저장을 보고한다. 이 시점이 저장 완료다."""
    repo = _repo(request)
    try:
        intake = repo.mark_intake_stored(intake_id, payload.runner_id, payload.content_hash)
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)
    request.app.state.relay.drop(intake_id)  # 중계 본문은 즉시 버린다
    return intake


@router.post("/api/runner/artifacts", status_code=201)
def runner_register_artifact(request: Request, payload: RunnerArtifactIn) -> dict[str, Any]:
    try:
        return _repo(request).register_runner_artifact(
            case_id=payload.case_id,
            kind=payload.kind,
            artifact_id=payload.artifact_id,
            revision=payload.revision,
            owner_runner_id=payload.runner_id,
            content_hash=payload.content_hash,
            byte_size=payload.byte_size,
            summary=payload.summary,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.post("/api/runner/{runner_id}/assignments")
def runner_assignments(request: Request, runner_id: str) -> list[dict[str, Any]]:
    try:
        return _repo(request).claim_assignments(runner_id)
    except NotFoundError as exc:
        raise _handle(exc)


@router.post("/api/runner/runs/{run_id}/events")
def runner_events(request: Request, run_id: str, payload: EventsIn) -> dict[str, int]:
    try:
        return _repo(request).append_events(
            run_id, payload.generation, [e.model_dump() for e in payload.events]
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.post("/api/runner/runs/{run_id}/result")
def runner_result(request: Request, run_id: str, payload: ResultIn) -> dict[str, Any]:
    try:
        return _repo(request).report_result(
            run_id=run_id,
            generation=payload.generation,
            outcome=payload.outcome,
            exit_code=payload.exit_code,
            output_artifact_id=payload.output_artifact_id,
            output_artifact_rev=payload.output_artifact_rev,
            session_ref=payload.session_ref,
            usage=payload.usage,
            workspace_effect=payload.workspace_effect,
            residual_activity=payload.residual_activity,
            observed_tool_version=payload.observed_tool_version,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


# ===================================================================== P2-02
#
# 의도 초안 · 피드백 · 질문 · 열람 · 명시 동의.
#
# 본문이 지나가는 경로는 여전히 **중계뿐**이다. 초안·피드백·답변 본문은 정규 문서
# 바이트로 만들어져 메모리 버퍼를 지나 소유 Runner로 가고, 열람은 그 반대 방향으로
# 한 번 지나간다. 어느 쪽도 제어부 DB·로그에 남지 않는다.


class IntentFieldIn(BaseModel):
    """의도 초안의 한 항목.

    본문이 비어 있으면 상태·출처를 추정하지 않는다. `domain.intent_doc.compose` 가
    `undecided`/`none` 으로 남긴다. 여기서 기본값을 채워 넣지 않는 이유다.
    """

    text: str = ""
    state: ConfirmationState | None = None
    origin: ContentOrigin | None = None


class IntentQuestionIn(BaseModel):
    """미정 질문.

    `summary` 를 따로 받는 이유는 이것만 제어부에 남기 때문이다. 본문에서 잘라 내면
    질문 본문의 앞부분이 제어부 DB에 그대로 남는다 — 다른 요약과 같은 규칙으로
    작성자가 쓴 짧은 문구를 요구한다.
    """

    key: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=200)
    decide_at: DecideAt = DecideAt.INTENT
    blocks: list[str] = Field(default_factory=list)


class IntentCriterionIn(BaseModel):
    """성공 기준(P2-04).

    기준의 본문(기대값·확인 방법)은 의도 문서 안으로 들어가고 제어부에는 짧은
    요약만 남는다. `method` 를 필수로 받는 이유는 확인 방법이 없는 기준이 곧
    QG-01의 `unverifiable_success_criteria` 이기 때문이다 — 빈 값으로 통과시키면
    게이트가 볼 것이 없어진다.
    """

    key: str = Field(min_length=1, max_length=64)
    #: **P3-R1: 공통 여섯 항목 또는 그 Profile 의 의미 항목**이다. 열거형을 여섯
    #: 항목으로 못박아 두면 `improvement_target` 에 걸린 기준이 입력 계약에서
    #: 거부된다 — 라이브에서 실제로 그렇게 막혔다. 이름의 유효성은 문서 형식
    #: (`intent_doc.compose`)과 저장 계층(`_field_name`)이 검사한다.
    relates_to: str = Field(default=IntentField.EXPECTED_OUTCOME.value, max_length=64)
    text: str = Field(min_length=1)
    method: str = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=200)
    method_summary: str = Field(min_length=1, max_length=200)


class SizingAxisIn(BaseModel):
    """수준 판단의 한 축(P3-01).

    `weight` 만 받지 않는 이유는 그것이 곧 숫자 점수이기 때문이다. 축마다
    `현재 판단`을 요구해 근거 없는 영향 표시를 막는다(sizing-and-review-ux 1절).
    `evidence` 는 의도 원문 안에 남고 제어부에는 오지 않는다.
    """

    axis: SizingAxis
    weight: AxisWeight
    evidence: str = ""
    judgement: str = Field(min_length=1, max_length=200)
    unconfirmed: str = ""


class SizingIn(BaseModel):
    """의도 초안에 실리는 작업 수준 판단.

    비워 두면(None) 수준 미결정이다. **`simple` 로 기본값을 두지 않는다** —
    판단하지 않은 것을 가장 얕은 준비로 읽으면 준비 없이 구현이 열린다.
    """

    recommended_level: WorkLevel
    axes: list[SizingAxisIn] = Field(default_factory=list)


class IntentDraftIn(BaseModel):
    """의도 초안 제출.

    `fields` 의 본문은 서버에 저장되지 않는다. 정규 문서로 묶여 Runner로 간다.
    `summary` 는 목록 표시용 짧은 문구이며 본문에서 뽑지 않는다.
    """

    summary: str = Field(min_length=1, max_length=200)
    target_runner_id: str
    authored_by: str = "owner"
    fields: dict[str, IntentFieldIn] = Field(default_factory=dict)
    questions: list[IntentQuestionIn] = Field(default_factory=list)
    #: 합의할 성공 기준. 비워 두면 기준 0건이며 시스템이 채우지 않는다.
    criteria: list[IntentCriterionIn] = Field(default_factory=list)
    #: 작업 수준 판단. 비워 두면 수준 미결정으로 남는다(P3-01).
    sizing: SizingIn | None = None
    #: 이 버전이 반영한 피드백. 반영/미반영을 이유와 함께 닫는다.
    reflects_feedback: list[str] = Field(default_factory=list)
    not_reflected: dict[str, str] = Field(default_factory=dict)


class FeedbackIn(BaseModel):
    target_intent_version_id: str
    content: str = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=200)
    target_runner_id: str
    author: str = "owner"


class AnswerIn(BaseModel):
    content: str = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=200)
    target_runner_id: str
    actor: str = "owner"


class AgreementIn(BaseModel):
    """명시 동의 요청.

    `agree` 와 `statement` 를 모두 요구하는 이유는 FR-03의 "질문 답변·수정 요청·
    무응답·시간 경과·AI 평가를 전체 의도 동의로 확대하지 않는다" 때문이다.
    `content_hash` 는 사람이 실제로 읽은 원문의 해시이며, 그 사이 대상이 바뀌면
    이전 동의로 진행하지 않는다(FR-23).
    """

    agree: bool = False
    statement: str = ""
    content_hash: str = Field(min_length=1)
    actor: str = "owner"
    evidence_ref: str | None = None


class ReadRequestIn(BaseModel):
    requested_by: str = "owner"


class ReadContentIn(BaseModel):
    runner_id: str
    content_b64: str
    content_hash: str


class IntentStructureIn(BaseModel):
    """Runner가 보고하는 의도 구조. **본문 필드가 없다.**"""

    runner_id: str
    intent_version_id: str
    fields: list[dict[str, Any]]
    questions: list[dict[str, Any]] = Field(default_factory=list)
    # 성공 기준도 같은 보고로 온다(P2-04). 기준의 본문은 의도 원문 안에 있고
    # 여기에는 짧은 요약·확인 방법 요약·연결된 의도 항목만 온다.
    # `None` 은 "기준을 보고하지 않음"이고 `[]` 는 "기준이 0건"이다 — 다르다.
    criteria: list[dict[str, Any]] | None = None
    # 작업 수준 판단도 같은 보고로 온다(P3-01). 축별 근거의 서술은 의도 원문 안에
    # 있고 여기에는 영향·짧은 판단 한 줄만 온다.
    # `None` 은 "판단하지 않음"이며 `{"axes": []}` 와 같은 뜻이 아니다.
    sizing: dict[str, Any] | None = None


def _refuse(reason: AgreementRefusal, detail: str) -> HTTPException:
    """동의를 기록할 수 없는 이유를 구별해 돌려준다.

    **이것은 FR-29 진입 조건 검사가 아니다.** 실행 배정을 여는 검사는 P2-03이며
    여기서는 "사람의 동의를 기록할 수 있는가"만 판단한다.
    """
    return HTTPException(
        status_code=400 if reason is AgreementRefusal.NOT_EXPLICIT else 409,
        detail={"refusal": reason.value, "message": detail},
    )


# --------------------------------------------------------------- 의도 초안


@router.post("/api/cases/{case_id}/intent-drafts", status_code=202)
def submit_intent_draft(request: Request, case_id: str, payload: IntentDraftIn) -> dict[str, Any]:
    """여섯 항목 초안을 접수한다. **저장 완료가 아니다.**

    제어부가 하는 일은 정규 문서로 묶어 중계하는 것과, 의도 버전이라는 자리를
    만드는 것뿐이다. 항목별 상태·질문은 소유 Runner가 원문을 저장한 뒤 보고한다
    (그래서 이 응답 시점에는 `fields` 가 비어 있다).
    """
    repo = _repo(request)
    try:
        # **P3-R1: 문서 형식은 Case 의 Profile 이 정한다.** 사람이 직접 입력한
        # 초안도 같은 항목 집합을 쓴다 — 경로에 따라 항목이 달라지면 같은 Case 의
        # 의도 버전들이 서로 다른 형식이 된다.
        case = repo.get_case(case_id)
        body = intent_doc.compose(
            fields={k: v.model_dump() for k, v in payload.fields.items()},
            questions=[q.model_dump() for q in payload.questions],
            case_id=case_id,
            authored_by=payload.authored_by,
            criteria=[c.model_dump(mode="json") for c in payload.criteria],
            sizing=(payload.sizing.model_dump(mode="json") if payload.sizing else None),
            profile=case.get("profile"),
            profile_version=case.get("profile_version"),
        )
    except NotFoundError as exc:
        raise _handle(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    digest = content_hash(body)
    try:
        intake = repo.open_intake(
            case_id=case_id,
            kind=ArtifactKind.INTENT,
            target_runner_id=payload.target_runner_id,
            expected_hash=digest,
            byte_size=len(body),
            summary=payload.summary,
        )
        intent = repo.create_intent_version(case_id, intake["artifact_id"], intake["revision"])
        if payload.reflects_feedback or payload.not_reflected:
            repo.resolve_feedback(
                payload.reflects_feedback, intent["id"], payload.not_reflected
            )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)

    request.app.state.relay.put(intake["id"], body)
    return {
        "intake_id": intake["id"],
        "artifact_id": intake["artifact_id"],
        "revision": intake["revision"],
        "content_hash": digest,
        "intent_version": intent,
        "availability": Availability.PENDING.value,
        "note": (
            "relayed to the owning runner; the six-field structure appears once the"
            " runner reports it back"
        ),
    }


@router.get("/api/cases/{case_id}/intent-state")
def intent_state(request: Request, case_id: str) -> dict[str, Any]:
    try:
        return _repo(request).intent_state(case_id)
    except NotFoundError as exc:
        raise _handle(exc)


@router.get("/api/cases/{case_id}/intent-versions/{intent_id}/diff")
def intent_diff(request: Request, case_id: str, intent_id: str) -> dict[str, Any]:
    repo = _repo(request)
    try:
        intent = repo.get_intent_version(intent_id)
        if intent["case_id"] != case_id:
            raise NotFoundError(f"intent version not in case {case_id}: {intent_id}")
        return repo.intent_diff(intent_id)
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.post("/api/cases/{case_id}/intent-versions/{intent_id}/agreement", status_code=201)
def agree_to_intent(
    request: Request, case_id: str, intent_id: str, payload: AgreementIn
) -> dict[str, Any]:
    """최신 의도 버전에 대한 사람의 명시적 동의(FR-03).

    네 가지 경우에는 동의를 기록하지 않고 이유를 구별해 돌려준다.
    거절은 "지금 이 동의를 기록할 수 없다"는 뜻이며, 과거의 유효한 동의를
    폐기하지도 실행 권한을 만들지도 않는다.
    """
    repo = _repo(request)
    try:
        intent = repo.get_intent_version(intent_id)
        if intent["case_id"] != case_id:
            raise NotFoundError(f"intent version not in case {case_id}: {intent_id}")
        detail = repo.get_intent_detail(intent_id)
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)

    # 1. 명시 표시가 없으면 동의가 아니다. 무응답·조회·질문 답변과 같은 취급이다.
    if not payload.agree or not payload.statement.strip():
        raise _refuse(
            AgreementRefusal.NOT_EXPLICIT,
            "agreement needs an explicit flag and a statement from the person",
        )

    # 2. 오래된 버전에 새로 동의하게 두지 않는다.
    latest = repo.latest_intent_version(case_id)
    if latest is None or latest["id"] != intent_id:
        raise _refuse(
            AgreementRefusal.NOT_LATEST_VERSION,
            f"revision {intent['revision']} is not the latest intent version",
        )

    # 3. 원문을 지금 확인할 수 없으면 대기한다. 요약으로 대신 동의하지 않는다.
    if detail["availability"] != Availability.AVAILABLE.value:
        raise _refuse(
            AgreementRefusal.ORIGINAL_NOT_AVAILABLE,
            f"the original is {detail['availability']}; the owning runner must be reachable",
        )

    # 4. 사람이 읽은 원문과 현재 원문이 다르면 이전 확인으로 진행하지 않는다.
    if payload.content_hash != detail["content_hash"]:
        raise _refuse(
            AgreementRefusal.CONTENT_CHANGED,
            "the original changed since it was read; read it again before agreeing",
        )

    # 5. 의도 단계에서 결정해야 할 질문이 남아 있으면 동의를 받지 않는다.
    #    원문 열람보다 먼저 검사한다 — 읽기 전에도 알려 줄 수 있는 사실이다.
    #    설계·계획으로 이월한 질문은 여기 걸리지 않는다.
    open_questions = repo.open_intent_stage_questions(intent_id)
    if open_questions:
        raise _refuse(
            AgreementRefusal.OPEN_INTENT_QUESTIONS,
            "intent-stage questions are still open: "
            + ", ".join(q["question_key"] for q in open_questions),
        )

    # 6. 요약만 보고 동의하지 않는다. 이 사람에게 **이 원문이 실제로 전달된** 기록이
    #    있어야 한다. 그 기록은 전달 시점에만 생기므로 호출자가 지어낼 수 없다
    #    (intent-artifacts 5절, data-boundary-review 3절).
    if not repo.has_read_the_original(intent_id, payload.actor, payload.content_hash):
        raise _refuse(
            AgreementRefusal.ORIGINAL_NOT_READ,
            "this person has not received this original; read it before agreeing",
        )

    decision = repo.record_intent_agreement(
        case_id=case_id,
        intent_version_id=intent_id,
        actor=payload.actor,
        content_hash=payload.content_hash,
        evidence_ref=payload.evidence_ref,
    )
    return {"decision": decision, "intent_state": repo.intent_state(case_id)}


# ------------------------------------------------------------ 피드백·질문


@router.post("/api/cases/{case_id}/feedback", status_code=202)
def submit_feedback(request: Request, case_id: str, payload: FeedbackIn) -> dict[str, Any]:
    """피드백 원문을 접수한다. **동의가 아니다.**

    본문은 다른 원문과 같은 경로로 Runner에 저장되고 제어부에는 참조와
    짧은 요약만 남는다.
    """
    repo = _repo(request)
    body = payload.content.encode("utf-8")
    digest = content_hash(body)
    try:
        intake = repo.open_intake(
            case_id=case_id,
            kind=ArtifactKind.FEEDBACK,
            target_runner_id=payload.target_runner_id,
            expected_hash=digest,
            byte_size=len(body),
            summary=payload.summary,
        )
        feedback = repo.record_feedback(
            case_id=case_id,
            target_intent_version_id=payload.target_intent_version_id,
            artifact_id=intake["artifact_id"],
            artifact_rev=intake["revision"],
            author=payload.author,
            summary=payload.summary,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)
    request.app.state.relay.put(intake["id"], body)
    return {
        "intake_id": intake["id"],
        "feedback": feedback,
        "availability": Availability.PENDING.value,
        "note": "feedback is recorded as feedback; it does not agree to the draft",
    }


@router.get("/api/cases/{case_id}/feedback")
def list_feedback(request: Request, case_id: str) -> list[dict[str, Any]]:
    try:
        _repo(request).get_case(case_id)
    except NotFoundError as exc:
        raise _handle(exc)
    return _repo(request).list_feedback(case_id)


class FeedbackDispositionIn(BaseModel):
    """피드백의 처리 결과를 **사람이** 정한다(P2-04).

    AI가 새 버전을 쓴 뒤 스스로 "반영했다"고 선언하게 두지 않는다. 반영 여부는
    피드백을 준 사람이 새 버전을 보고 판단하는 것이며, 미반영은 이유와 함께
    남는다(intent-artifacts 3절). 이 판단이 없으면 결과 인수가
    `unresolved_feedback` 로 거부된다 — 조용히 닫히지 않는다.
    """

    reflected: bool
    #: 반영으로 닫을 때 그것을 반영한 의도 버전. 미반영이면 비운다.
    reflected_in_version_id: str | None = None
    #: 미반영으로 닫을 때의 이유. 짧은 요약이며 원문이 아니다.
    reason: str | None = Field(default=None, max_length=200)


@router.post("/api/cases/{case_id}/feedback/{feedback_id}/disposition")
def resolve_feedback(
    request: Request, case_id: str, feedback_id: str, payload: FeedbackDispositionIn
) -> dict[str, Any]:
    """피드백을 반영됨 또는 미반영으로 닫는다. **미반영은 이유가 필요하다.**"""
    repo = _repo(request)
    try:
        repo.guard_open_case(case_id)
        feedback = repo.get_feedback(feedback_id)
        if feedback["case_id"] != case_id:
            raise ConflictError("feedback belongs to another case")
        if feedback["state"] != "received":
            raise ConflictError(f"feedback is already {feedback['state']}")
        if payload.reflected:
            version_id = payload.reflected_in_version_id
            if version_id is None:
                latest = repo.latest_intent_version(case_id)
                if latest is None:
                    raise ConflictError("no intent version to attribute the reflection to")
                version_id = latest["id"]
            repo.get_intent_version(version_id)
            resolved = repo.resolve_feedback([feedback_id], version_id)
        else:
            if not (payload.reason or "").strip():
                raise ConflictError(
                    "a feedback left unreflected needs a reason; it is not closed silently"
                )
            resolved = repo.resolve_feedback([], None, {feedback_id: payload.reason or ""})
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)
    return resolved[0]


@router.post("/api/cases/{case_id}/questions/{question_id}/answer", status_code=202)
def answer_question(
    request: Request, case_id: str, question_id: str, payload: AnswerIn
) -> dict[str, Any]:
    """미정 질문에 답한다. **동의가 아니다.**

    답변 원문도 Runner에 저장되고 제어부에는 참조만 남는다.
    """
    repo = _repo(request)
    body = payload.content.encode("utf-8")
    digest = content_hash(body)
    try:
        question = repo.get_question(question_id)
        if question["case_id"] != case_id:
            raise NotFoundError(f"question not in case {case_id}: {question_id}")
        intake = repo.open_intake(
            case_id=case_id,
            kind=ArtifactKind.FEEDBACK,
            target_runner_id=payload.target_runner_id,
            expected_hash=digest,
            byte_size=len(body),
            summary=payload.summary,
        )
        answered = repo.answer_question(question_id, payload.actor, intake["artifact_id"])
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)
    request.app.state.relay.put(intake["id"], body)
    return {
        "question": answered,
        "intake_id": intake["id"],
        "note": "answering a question does not agree to the intent draft",
    }


# ------------------------------------------------------- 원문 열람(일시중계)


@router.post("/api/artifacts/{artifact_id}/{revision}/read-requests", status_code=201)
def open_read_request(
    request: Request, artifact_id: str, revision: int, payload: ReadRequestIn
) -> dict[str, Any]:
    """원문 열람을 요청한다.

    제어부는 Runner로 접속하지 않는다. 요청을 남겨 두면 소유 Runner가
    자기 요청을 가져가 본문을 올린다.
    """
    try:
        read_request = _repo(request).open_read_request(artifact_id, revision, payload.requested_by)
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)
    return read_request


@router.get("/api/read-requests/{request_id}")
def get_read_content(request: Request, request_id: str) -> dict[str, Any]:
    """열람 결과를 **한 번** 받아 간다.

    본문을 돌려주는 즉시 중계 버퍼에서 버린다. 다시 필요하면 새로 요청한다.
    제어부가 재시작해 버퍼가 비었으면 `expired` 로 표시하고 빈 문서로 채우지 않는다.
    """
    repo = _repo(request)
    try:
        read_request = repo.get_read_request(request_id)
    except NotFoundError as exc:
        raise _handle(exc)

    if read_request["state"] != ReadRequestState.RELAYED.value:
        return {"request": read_request, "content": None}

    body = request.app.state.relay.get(request_id)
    if body is None:
        return {"request": repo.mark_read_expired(request_id), "content": None}

    request.app.state.relay.drop(request_id)
    delivered = repo.mark_read_delivered(request_id)

    # 원문이 실제로 전달된 순간에만 열람 기록을 남긴다. 이것이 "사람이 원문을
    # 확인했다"의 유일한 근거이며 동의의 선행 조건으로 쓰인다.
    # 열람은 동의가 아니다 — decision 행은 여기서 만들어지지 않는다.
    intent = repo.intent_version_for_artifact(
        read_request["artifact_id"], read_request["revision"]
    )
    if intent is not None:
        repo.record_intent_view(
            intent["id"], read_request["requested_by"], read_request["content_hash"]
        )

    return {
        "request": delivered,
        "content": body.decode("utf-8"),
        "note": "relayed through controller memory only; not stored on the controller",
    }


# ------------------------------------------------------ runner-facing (P2-02)


@router.get("/api/runner/{runner_id}/read-requests")
def runner_read_requests(request: Request, runner_id: str) -> list[dict[str, Any]]:
    return _repo(request).list_pending_read_requests(runner_id)


@router.post("/api/runner/read-requests/{request_id}/content")
def runner_read_content(
    request: Request, request_id: str, payload: ReadContentIn
) -> dict[str, Any]:
    """Runner가 고정 버전의 원문을 올린다. 본문은 메모리 버퍼에만 들어간다."""
    repo = _repo(request)
    body = base64.b64decode(payload.content_b64)
    if content_hash(body) != payload.content_hash:
        raise HTTPException(status_code=409, detail="relayed content does not match its hash")
    try:
        relayed = repo.mark_read_relayed(
            request_id, payload.runner_id, payload.content_hash, len(body)
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)
    request.app.state.relay.put(request_id, body)
    return relayed


@router.post("/api/runner/intent-structure")
def runner_intent_structure(request: Request, payload: IntentStructureIn) -> dict[str, Any]:
    """Runner가 계산한 의도 구조를 받는다. 본문은 오지 않는다."""
    try:
        return _repo(request).apply_intent_structure(
            payload.intent_version_id,
            payload.fields,
            payload.questions,
            payload.criteria,
            payload.sizing,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


# ===================================================================== P2-03
#
# QG-01 게이트 · FR-29 진입 조건 검사 · AI 작성 경로.
#
# **본문은 여전히 여기를 지나가지 않는다.** AI가 쓴 초안 본문은 Runner에서 태어나
# Runner에 남고, 게이트 검토 결과도 짧은 요약만 올라온다.


class RunnerIntentVersionIn(BaseModel):
    """Runner가 작성한 초안을 의도 버전으로 등록한다. **본문 필드가 없다.**"""

    runner_id: str
    case_id: str
    artifact_id: str
    revision: int = 1
    authoring_mode: AuthoringMode = AuthoringMode.AI_DRAFTED
    author_run_id: str | None = None


class GateReviewIn(BaseModel):
    """AI 의미 검토 보고.

    **판정값을 받지 않는다.** 실행자가 스스로 통과를 선언하게 두지 않기 위해서이며,
    제어부가 발견 사항에서 판정을 다시 계산한다(controller/gate.py).
    """

    runner_id: str
    run_id: str
    intent_version_id: str
    findings: list[dict[str, Any]] = Field(default_factory=list)


class QualityGatePolicyIn(BaseModel):
    task_key: str = Field(default="", max_length=120)
    setting: str = "inherit"
    inspection: str | None = None
    repair_limit: int | None = Field(default=None, ge=0)
    actor: str = Field(min_length=1, max_length=120)
    reason_summary: str = Field(min_length=1, max_length=200)


class QualityGateRunIn(BaseModel):
    task_key: str = Field(default="", max_length=120)
    gate: GateId
    subject_key: str = Field(min_length=1, max_length=160)
    input_hash: str = Field(min_length=1, max_length=128)
    inspection_used: str
    context_refs: list[str] = Field(default_factory=list)
    criteria_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    author_run_id: str | None = None
    reviewer_run_id: str | None = None
    blocked: bool = False


class RemediationAttemptIn(BaseModel):
    kind: str
    task_key: str = Field(default="", max_length=120)
    session_ref: str | None = Field(default=None, max_length=200)
    author_run_id: str | None = None


class RemediationCompleteIn(BaseModel):
    outcome: str = Field(min_length=1, max_length=80)
    verification_run_id: str | None = None


@router.get("/api/cases/{case_id}/gate")
def get_gate(request: Request, case_id: str) -> dict[str, Any]:
    """최신 의도 버전에 대한 QG-01 상태."""
    try:
        return _repo(request).gate_state(case_id)
    except NotFoundError as exc:
        raise _handle(exc)


@router.get("/api/cases/{case_id}/gate-results")
def list_gate_results(request: Request, case_id: str) -> list[dict[str, Any]]:
    """이 Case의 모든 게이트 판정. 대체된 판정도 남아 있다."""
    try:
        _repo(request).get_case(case_id)
    except NotFoundError as exc:
        raise _handle(exc)
    return _repo(request).list_gate_results(case_id)


@router.post("/api/cases/{case_id}/intent-versions/{intent_id}/gate-rules")
def run_gate_rules(request: Request, case_id: str, intent_id: str) -> dict[str, Any]:
    """규칙 검사를 다시 돌린다.

    구조가 보고될 때 자동으로 한 번 돌지만, 원문 상태가 바뀐 뒤(예: Runner 복귀)
    다시 확인할 수 있어야 한다. **AI 검토 결과는 그대로 둔다.**
    """
    repo = _repo(request)
    try:
        intent = repo.get_intent_version(intent_id)
        if intent["case_id"] != case_id:
            raise NotFoundError(f"intent version not in case {case_id}: {intent_id}")
        return repo.evaluate_gate_rules(intent_id)
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.get("/api/cases/{case_id}/quality-gates")
def get_quality_gates(
    request: Request, case_id: str, task_key: str = ""
) -> dict[str, Any]:
    try:
        return _repo(request).quality_gate_state(case_id, task_key)
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.put("/api/cases/{case_id}/quality-gates/{gate}/policy")
def put_quality_gate_policy(
    request: Request, case_id: str, gate: GateId, payload: QualityGatePolicyIn
) -> dict[str, Any]:
    try:
        return _repo(request).set_quality_gate_policy(
            case_id,
            gate,
            task_key=payload.task_key,
            setting=payload.setting,
            inspection=payload.inspection,
            repair_limit=payload.repair_limit,
            actor=payload.actor,
            reason_summary=payload.reason_summary,
        )
    except (NotFoundError, ConflictError, ValueError) as exc:
        raise _handle(ConflictError(str(exc)) if isinstance(exc, ValueError) else exc)


@router.post("/api/cases/{case_id}/quality-gate-runs", status_code=201)
def create_quality_gate_run(
    request: Request, case_id: str, payload: QualityGateRunIn
) -> dict[str, Any]:
    try:
        return _repo(request).record_quality_gate_run(
            case_id,
            payload.gate,
            subject_key=payload.subject_key,
            input_hash=payload.input_hash,
            inspection_used=payload.inspection_used,
            context_refs=payload.context_refs,
            criteria_refs=payload.criteria_refs,
            evidence_refs=payload.evidence_refs,
            findings=payload.findings,
            task_key=payload.task_key,
            author_run_id=payload.author_run_id,
            reviewer_run_id=payload.reviewer_run_id,
            blocked=payload.blocked,
        )
    except (NotFoundError, ConflictError, ValueError) as exc:
        raise _handle(ConflictError(str(exc)) if isinstance(exc, ValueError) else exc)


@router.get("/api/cases/{case_id}/quality-gates/{gate}/remediation/{subject_key}")
def get_remediation(
    request: Request, case_id: str, gate: GateId, subject_key: str
) -> dict[str, Any]:
    try:
        return _repo(request).remediation_state(case_id, gate, subject_key)
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.post(
    "/api/cases/{case_id}/quality-gates/{gate}/remediation/{subject_key}/attempts",
    status_code=201,
)
def start_remediation(
    request: Request,
    case_id: str,
    gate: GateId,
    subject_key: str,
    payload: RemediationAttemptIn,
) -> dict[str, Any]:
    try:
        return _repo(request).start_remediation_attempt(
            case_id,
            gate,
            subject_key,
            kind=payload.kind,
            task_key=payload.task_key,
            session_ref=payload.session_ref,
            author_run_id=payload.author_run_id,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.post("/api/remediation-attempts/{attempt_id}/complete")
def complete_remediation(
    request: Request, attempt_id: str, payload: RemediationCompleteIn
) -> dict[str, Any]:
    try:
        return _repo(request).complete_remediation_attempt(
            attempt_id,
            outcome=payload.outcome,
            verification_run_id=payload.verification_run_id,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.get("/api/cases/{case_id}/admission-checks")
def list_admission_checks(request: Request, case_id: str) -> list[dict[str, Any]]:
    """진입 검사 기록. **거부도 남아 있다.**"""
    try:
        _repo(request).get_case(case_id)
    except NotFoundError as exc:
        raise _handle(exc)
    return _repo(request).list_admission_checks(case_id)


@router.post("/api/runner/intent-versions", status_code=201)
def runner_create_intent_version(
    request: Request, payload: RunnerIntentVersionIn
) -> dict[str, Any]:
    """AI가 작성한 초안을 의도 버전으로 만든다.

    P2-02의 `POST /api/cases/{id}/intent-drafts` 와 **방향이 반대다.** 저쪽은
    브라우저가 보낸 항목을 제어부가 문서로 묶어 내려보냈고, 이쪽은 이미 Runner에
    저장된 원문을 가리키기만 한다. 두 경로가 같은 표·같은 문서 형식을 쓴다.
    """
    repo = _repo(request)
    try:
        ref = repo.get_artifact_ref(payload.artifact_id, payload.revision)
        if ref["owner_runner_id"] != payload.runner_id:
            raise ConflictError("only the owning runner can turn its artifact into a version")
        intent = repo.create_intent_version(
            payload.case_id,
            payload.artifact_id,
            payload.revision,
            authoring_mode=payload.authoring_mode,
            author_run_id=payload.author_run_id,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)
    return {
        "intent_version": intent,
        # 구조 보고에 필요한 비교 대상. 본문이 아니라 참조다.
        "intent_context": repo.intent_intake_context(payload.artifact_id, payload.revision),
    }


@router.post("/api/runner/gate-reviews")
def runner_gate_review(request: Request, payload: GateReviewIn) -> dict[str, Any]:
    """AI 의미 검토 결과를 게이트에 붙인다."""
    repo = _repo(request)
    try:
        return repo.apply_gate_review(
            intent_version_id=payload.intent_version_id,
            run_id=payload.run_id,
            raw_findings=payload.findings,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


# ===================================================================== P2-04
#
# 결과·근거 열람과 사람 최종 확인.
#
# **본문은 여기도 지나가지 않는다.** 기준의 본문은 의도 원문 안에, 근거의 서술은
# 실행 결과 원문 안에 있고, 둘 다 기존 일시중계 경로(`read-requests`)로만 읽는다.
# 인수·예외의 문구도 참조로만 받는다.
#
# 인수 거절은 `AcceptanceRefused` 로 올라가 사유 코드 목록과 함께 409가 된다.
# **P2-02의 동의 거절, P2-03의 진입 거부와 별개 목록이다**(FR-23).


class CriterionResultIn(BaseModel):
    """기준별 판정 기록. **본문 필드가 없다.**

    `summary` 는 목록에 보일 짧은 요약이며 근거 원문을 대체하지 않는다.
    """

    verdict: CriterionVerdict
    summary: str = Field(min_length=1, max_length=200)
    recorded_by: str = Field(min_length=1, max_length=120)
    evidence_kind: EvidenceKind = EvidenceKind.NONE
    evidence_run_id: str | None = None
    evidence_artifact_id: str | None = None
    evidence_artifact_rev: int | None = None
    #: **이 근거가 나온 코드 조합**(P3-R2). 움직이는 브랜치 이름이 아니라 고정된
    #: 조합으로 대상을 묶어야 나중에 그 근거가 아직 유효한지 답할 수 있다.
    composition_id: str | None = None
    #: **어떻게 충족했는가**(P3-R4). `not_reproduced` 는 `met` 이 될 수 없고,
    #: `already_satisfied` 는 검증 실행의 증거를 요구한다(case-profiles 4절).
    satisfaction: Satisfaction | None = None


class CompletionPolicyIn(BaseModel):
    mode: CompletionMode
    set_by: str = Field(min_length=1, max_length=120)


class AcceptanceIn(BaseModel):
    """최종 인수. 대상이 분명한 행동이어야 한다(FR-03/FR-23의 같은 원칙).

    `statement` 는 사용자가 직접 쓴 인수 문구이며 **저장하지 않는다.**
    제어부는 그 문구가 인수를 뜻하는지만 보고 본문은 버린다.
    """

    actor: str = Field(min_length=1, max_length=120)
    statement: str = Field(min_length=1, max_length=400)
    statement_artifact_id: str | None = None


class ExceptionIn(BaseModel):
    """표시된 미충족·미검증의 수용. 원래 판정을 바꾸지 않는다."""

    actor: str = Field(min_length=1, max_length=120)
    criterion_id: str
    scope_summary: str = Field(min_length=1, max_length=200)


class SuccessorCaseIn(BaseModel):
    """완료 후 수정 요청. 기존 Case 재개가 아니라 연결된 새 Case 다(D-33).

    **P3-R1: Profile 도 승계하지 않는다.** 원래 Case 의 목적이 새 Case 의 목적이라고
    가정하지 않는다 — 완료한 기능의 수정 요청이 결함 수정일 수도, 유지보수일 수도
    있다. 주지 않으면 `kind` 에서 유도되고 그 사실이 출처에 남는다.
    """

    title: str = Field(min_length=1, max_length=200)
    kind: CaseKind | None = None
    profile: CaseProfile | None = None
    reason_summary: str = Field(min_length=1, max_length=200)


#: 인수로 인정하는 문구. 대상이 분명한 행동만 받는다.
#: "좋아 보인다", "고맙다" 같은 반응을 인수로 확대하지 않는다(FR-23).
_ACCEPTANCE_PHRASES = ("이 결과를 인수", "결과 인수", "최종 인수", "accept this result")


@router.get("/api/cases/{case_id}/result")
def get_result_view(request: Request, case_id: str) -> dict[str, Any]:
    """기준별 결과·근거·미정리 실행·종료 후보를 한 묶음으로 돌려준다(FR-17).

    총점 하나를 만들지 않는다. 기준마다 판정과 근거를 그대로 둔다.
    """
    try:
        return _repo(request).result_view(case_id)
    except NotFoundError as exc:
        raise _handle(exc)


@router.post("/api/cases/{case_id}/criteria/{criterion_id}/result")
def record_criterion_result(
    request: Request, case_id: str, criterion_id: str, payload: CriterionResultIn
) -> dict[str, Any]:
    """기준별 판정을 기록한다.

    **실행이 끝났다는 사실이 판정을 만들지 않는다.** `met` 은 근거 Run 의 outcome 이
    `completed` 일 때만 받는다. `unknown` 을 근거로 한 `met` 은 409로 거부된다.
    """
    repo = _repo(request)
    try:
        criterion = repo.get_success_criterion(criterion_id)
        if criterion["case_id"] != case_id:
            raise ConflictError("criterion belongs to another case")
        return repo.record_criterion_result(
            criterion_id=criterion_id,
            verdict=payload.verdict,
            summary=payload.summary,
            recorded_by=payload.recorded_by,
            evidence_kind=payload.evidence_kind,
            evidence_run_id=payload.evidence_run_id,
            evidence_artifact_id=payload.evidence_artifact_id,
            evidence_artifact_rev=payload.evidence_artifact_rev,
            composition_id=payload.composition_id,
            satisfaction=payload.satisfaction,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.put("/api/cases/{case_id}/completion-policy")
def set_completion_policy(
    request: Request, case_id: str, payload: CompletionPolicyIn
) -> dict[str, Any]:
    """Case 의 완료 정책(D-31). 기본은 사람 최종 확인이다."""
    try:
        return _repo(request).set_completion_mode(case_id, payload.mode, payload.set_by)
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.post("/api/cases/{case_id}/completion-candidates", status_code=201)
def build_candidate(request: Request, case_id: str) -> dict[str, Any]:
    """종료 후보를 만든다. 내용이 그대로면 기존 후보를 그대로 돌려준다."""
    try:
        candidate, created = _repo(request).build_completion_candidate(case_id)
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)
    return {"created": created, "candidate": candidate}


@router.get("/api/cases/{case_id}/completion-candidates")
def list_candidates(request: Request, case_id: str) -> list[dict[str, Any]]:
    try:
        return _repo(request).list_completion_candidates(case_id)
    except NotFoundError as exc:
        raise _handle(exc)


@router.post("/api/cases/{case_id}/completion-candidates/{candidate_id}/exceptions",
             status_code=201)
def accept_exception(
    request: Request, case_id: str, candidate_id: str, payload: ExceptionIn
) -> dict[str, Any]:
    """표시된 미충족·미검증을 수용한다. **원래 판정은 보존된다.**"""
    repo = _repo(request)
    try:
        candidate = repo.get_completion_candidate(candidate_id)
        if candidate["case_id"] != case_id:
            raise ConflictError("candidate belongs to another case")
        return repo.record_exception_decision(
            candidate_id=candidate_id,
            target_id=payload.criterion_id,
            scope_summary=payload.scope_summary,
            actor=payload.actor,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.post("/api/cases/{case_id}/completion-candidates/{candidate_id}/acceptance",
             status_code=201)
def accept_result(
    request: Request, case_id: str, candidate_id: str, payload: AcceptanceIn
) -> dict[str, Any]:
    """최종 인수를 기록한다.

    **인수가 곧 종료는 아니다.** 결과를 확정할 수 없는 실행이 남아 있으면 인수는
    기록하고 종료 기록은 만들지 않는다(completion-lifecycle 5절).
    """
    repo = _repo(request)
    try:
        candidate = repo.get_completion_candidate(candidate_id)
    except NotFoundError as exc:
        raise _handle(exc)
    if candidate["case_id"] != case_id:
        raise _handle(ConflictError("candidate belongs to another case"))

    statement = payload.statement.strip()
    if not any(phrase in statement for phrase in _ACCEPTANCE_PHRASES):
        # 모호한 반응을 인수로 확대하지 않는다. 대상이 분명한 행동만 받는다.
        raise HTTPException(
            status_code=400,
            detail={
                "refusals": [AcceptanceRefusal.NOT_EXPLICIT.value],
                "message": (
                    "인수 문구에 대상이 분명한 표현이 없다."
                    f" 다음 중 하나를 포함해야 한다: {', '.join(_ACCEPTANCE_PHRASES)}"
                ),
            },
        )
    try:
        acceptance = repo.record_final_acceptance(
            candidate_id=candidate_id,
            actor=payload.actor,
            mode=AcceptanceMode.HUMAN,
            statement_artifact_id=payload.statement_artifact_id,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)
    return {
        "acceptance": acceptance,
        "closure": repo.get_closure(case_id),
        "candidate": repo.get_completion_candidate(candidate_id),
    }


@router.post("/api/cases/{case_id}/auto-complete")
def auto_complete(request: Request, case_id: str) -> dict[str, Any]:
    """자동 완료 정책을 적용한다.

    **자동 완료를 사람 인수로 표시하지 않는다.** 정책이 사람 확인이면 아무 것도
    하지 않고, 조건을 못 갖추면 사유를 돌려주며 예외를 스스로 수용하지 않는다.
    """
    repo = _repo(request)
    try:
        result = repo.auto_complete_if_allowed(case_id)
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)
    result["closure"] = repo.get_closure(case_id)
    return result


@router.post("/api/cases/{case_id}/successor", status_code=201)
def create_successor(
    request: Request, case_id: str, payload: SuccessorCaseIn
) -> dict[str, Any]:
    """완료 후 수정을 위한 연결된 새 Case 를 만든다.

    **이전 동의를 승계하지 않는다.** 새 Case 는 의도 버전 0개로 시작한다.
    """
    try:
        return _repo(request).create_successor_case(
            from_case_id=case_id,
            title=payload.title,
            kind=payload.kind or (None if payload.profile else CaseKind.FEATURE),
            reason_summary=payload.reason_summary,
            profile=payload.profile,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


# ===================================================================== P3-01
#
# 작업 수준 · 설계안 · 개발계획 · 단계별 사람 검토.
#
# **본문은 여기도 지나가지 않는다.** 축별 근거의 서술은 의도 원문 안에, 설계·계획의
# 본문은 Runner에 저장된 준비 산출물 원문 안에 있다. 둘 다 기존 일시중계 경로
# (`read-requests`)로만 읽는다. 아래 모델에는 본문 필드가 없다.
#
# 진입 조건 검사는 여전히 `POST /api/cases/{id}/runs` 한 곳이다. 여기에 조건을
# 다시 구현하지 않는다 — 두 곳에 두면 한쪽만 고치는 실수가 생긴다.


class SizingAdjustmentIn(BaseModel):
    """사람의 수준 상향·하향.

    `reason` 과 `residual_risk` 를 **둘 다** 필수로 받는다. sizing-and-review-ux
    1절: "조정 이유와 남는 위험을 기록하며, 상세도 조정이 의도 동의·합의한 검증·
    권한을 해제하지 않게 한다." 이유 없는 조정은 기록으로서 쓸모가 없다.
    """

    level: WorkLevel
    reason: str = Field(min_length=1, max_length=200)
    residual_risk: str = Field(min_length=1, max_length=200)
    actor: str = "owner"


class StageReviewModeIn(BaseModel):
    """단계별 검토 방식 설정. **두 단계는 각각 설정한다.**"""

    mode: ReviewMode
    reason: str = ""
    set_by: str = "owner"


class StageReviewIn(BaseModel):
    """사람의 단계 검토 기록.

    `reviewed` 를 명시로 받는 이유는 의도 동의와 같다 — 열람·질문·시간 경과가
    검토가 되지 않는다(FR-23은 검토를 의도 동의·최종 인수와 구별해 기록하라고
    요구한다).
    """

    reviewed: bool = False
    note: str = ""
    actor: str = "owner"


class RunnerPreparationIn(BaseModel):
    """Runner가 만든 설계·계획 산출물의 등록. **본문 필드가 없다.**"""

    runner_id: str
    case_id: str
    stage: PreparationStage
    artifact_id: str
    revision: int = 1
    level: WorkLevel
    authoring_mode: AuthoringMode = AuthoringMode.AI_DRAFTED
    author_run_id: str | None = None
    summary: str = Field(min_length=1, max_length=200)


class PreparationStructureIn(BaseModel):
    """Runner가 보고하는 산출물 구조. **본문 필드가 없다.**"""

    runner_id: str
    preparation_id: str
    sections: list[dict[str, Any]]
    questions: list[dict[str, Any]] = Field(default_factory=list)
    #: 개발계획이 정의한 Task(P3-02). 설계 보고에는 비어 있다.
    #: **기본값이 빈 목록인 것은 v1 계획 문서 때문이다** — Task 0건은
    #: "Task 가 필요 없다"가 아니라 그래프가 없다는 뜻이고,
    #: 기능 구현은 `work_graph_missing` 으로 막힌다.
    tasks: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/api/cases/{case_id}/preparation")
def get_preparation_state(request: Request, case_id: str) -> dict[str, Any]:
    """수준·설계·계획·검토를 한 번에 본 상태.

    화면과 진입 검사가 **같은 값**을 본다. 화면이 따로 계산하면 버튼은 눌리는데
    서버가 거부하는(또는 그 반대의) 상태가 생긴다.
    """
    try:
        return _repo(request).preparation_state(case_id)
    except NotFoundError as exc:
        raise _handle(exc)


@router.post("/api/cases/{case_id}/sizing-adjustment", status_code=201)
def adjust_sizing(request: Request, case_id: str, payload: SizingAdjustmentIn) -> dict[str, Any]:
    """사람이 작업 수준을 조정한다.

    **이 경로는 검토 모드·성공 기준·의도 동의를 건드리지 않는다.** 수준을 낮추는
    것이 합의한 검증이나 필수 동의를 없애지 않는다는 규칙을 코드 구조로 지킨다.
    """
    repo = _repo(request)
    try:
        return repo.adjust_sizing(
            case_id=case_id,
            level=payload.level,
            actor=payload.actor,
            reason_summary=payload.reason,
            residual_risk_summary=payload.residual_risk,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.get("/api/cases/{case_id}/preparation-artifacts")
def list_preparation_artifacts(
    request: Request, case_id: str, stage: PreparationStage | None = None
) -> list[dict[str, Any]]:
    """설계·개발계획 산출물 목록.

    `stage` 로 **각각 조회한다**(intent-artifacts 2절 "두 산출물은 각각 조회할 수
    있어야 한다"). 검토 설정과 무관하게 조회할 수 있어야 하므로 자동 진행 단계의
    산출물도 같은 경로로 나온다.
    """
    try:
        return _repo(request).list_preparation_artifacts(case_id, stage)
    except NotFoundError as exc:
        raise _handle(exc)


@router.get("/api/preparation-artifacts/{prep_id}")
def get_preparation_artifact(request: Request, prep_id: str) -> dict[str, Any]:
    try:
        return _repo(request).get_preparation_artifact(prep_id)
    except NotFoundError as exc:
        raise _handle(exc)


@router.put("/api/cases/{case_id}/stage-review-settings/{stage}")
def set_stage_review_mode(
    request: Request, case_id: str, stage: PreparationStage, payload: StageReviewModeIn
) -> dict[str, Any]:
    """단계별 검토 방식을 정한다. 기본값은 두 단계 모두 사람 검토다."""
    repo = _repo(request)
    try:
        return repo.set_stage_review_mode(
            case_id=case_id,
            stage=stage,
            mode=payload.mode,
            set_by=payload.set_by,
            reason_summary=payload.reason,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.post("/api/cases/{case_id}/stage-reviews/{stage}", status_code=201)
def record_stage_review(
    request: Request, case_id: str, stage: PreparationStage, payload: StageReviewIn
) -> dict[str, Any]:
    """사람이 이 단계의 산출물을 검토했다고 기록한다.

    `reviewed` 가 false 면 기록하지 않는다. 화면을 열어 본 것이 검토가 아니다.
    """
    repo = _repo(request)
    try:
        current = repo.current_preparation(case_id, stage)
        if current is None:
            raise ConflictError(f"there is no current {stage.value} artifact to review")
        return repo.record_stage_review(
            case_id=case_id,
            stage=stage,
            prep_id=current["id"],
            actor=payload.actor,
            note_summary=payload.note,
            explicit=payload.reviewed,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.post("/api/cases/{case_id}/stage-auto-proceed/{stage}", status_code=201)
def record_auto_proceed(
    request: Request, case_id: str, stage: PreparationStage
) -> dict[str, Any]:
    """자동 진행 조건이 충족됐다고 기록한다. **사람 승인이 아니다.**

    `decision` 표에 행을 만들지 않고 주체도 정책 식별자다. 사람 검토 모드에서
    이 경로를 부르면 거부된다 — 자동 진행이 사람을 대신하지 않는다.
    """
    repo = _repo(request)
    try:
        current = repo.current_preparation(case_id, stage)
        if current is None:
            raise ConflictError(f"there is no current {stage.value} artifact")
        return repo.record_auto_proceed(case_id, stage, current["id"])
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.get("/api/runs/{run_id}/context-refs")
def list_run_context_refs(request: Request, run_id: str) -> list[dict[str, Any]]:
    """이 실행에 고정한 참조 목록.

    "그 실행이 무엇을 보고 썼는가"의 답이다. P2-04에서 재작성이 이전 버전을 보지
    못해 초안이 퇴화했고, 그것이 기록으로 드러나지 않았다.
    """
    repo = _repo(request)
    try:
        repo.get_run(run_id)
        return repo.list_context_refs(run_id)
    except NotFoundError as exc:
        raise _handle(exc)


@router.post("/api/runner/preparation-artifacts", status_code=201)
def runner_create_preparation_artifact(
    request: Request, payload: RunnerPreparationIn
) -> dict[str, Any]:
    """Runner가 작성한 설계·계획을 산출물로 등록한다.

    AI 의도 초안 등록과 같은 방향이다 — 원문은 이미 Runner에 있고 제어부는
    가리키기만 한다. **어느 의도 버전 위에 세웠는지는 제어부가 정한다**(지금의 최신
    버전). Runner가 정하게 두면 옛 의도 위의 산출물을 최신이라고 주장할 수 있다.
    """
    repo = _repo(request)
    try:
        ref = repo.get_artifact_ref(payload.artifact_id, payload.revision)
        if ref["owner_runner_id"] != payload.runner_id:
            raise ConflictError("only the owning runner can register its artifact")
        prep = repo.create_preparation_artifact(
            case_id=payload.case_id,
            stage=payload.stage,
            artifact_id=payload.artifact_id,
            artifact_rev=payload.revision,
            level=payload.level,
            authoring_mode=payload.authoring_mode,
            author_run_id=payload.author_run_id,
            summary=payload.summary,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)
    return {"preparation_artifact": prep}


@router.post("/api/runner/preparation-structure")
def runner_preparation_structure(
    request: Request, payload: PreparationStructureIn
) -> dict[str, Any]:
    """Runner가 계산한 산출물 구조를 받는다. 본문은 오지 않는다."""
    repo = _repo(request)
    try:
        prep = repo.get_preparation_artifact(payload.preparation_id)
        if prep["owner_runner_id"] != payload.runner_id:
            raise ConflictError("only the owning runner can report this structure")
        return repo.apply_preparation_structure(
            payload.preparation_id, payload.sections, payload.questions, payload.tasks
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


# ===================================================================== P3-02
#
# 작업 그래프. **조회는 준비 상태와 따로 둔다** — 설계·계획이 각각 조회되는 것과
# 같은 이유다. 한 응답에 다 넣으면 화면이 무엇을 보고 있는지가 흐려진다.


class TaskIn(BaseModel):
    """사람이 더하는 Task. **본문 필드가 없다.**

    목적·산출물·완료 조건의 **짧은 요약**만 받는다. 서술을 받으면 제어부에 본문이
    남고, 그것은 개발계획 원문의 자리다.
    """

    key: str = Field(min_length=1, max_length=64)
    kind: TaskKind = TaskKind.IMPLEMENTATION
    summary: str = Field(min_length=1, max_length=200)
    deliverable_summary: str = Field(default="", max_length=200)
    completion_summary: str = Field(default="", max_length=200)
    relates_to: str = Field(default="", max_length=64)
    #: **어느 저장소를 바꾸는 작업인가**(P3-04). 이름 또는 등록 id 이며 이 Case 가
    #: 고른 저장소 안에서만 해석된다. 비우면 미기록이고, 저장소가 둘 이상인 Case
    #: 에서는 그 Task 로 구현·검증이 열리지 않는다.
    repository: str = Field(default="", max_length=100)
    depends_on: list[str] = Field(default_factory=list)
    criteria: list[dict[str, str]] = Field(default_factory=list)


class AddTaskIn(BaseModel):
    """Task 추가 요청.

    `reason` 이 필수다. 계획이 **왜** 바뀌었는지 없이 그래프만 바뀌면 나중에
    "무효 전제의 결과를 확인 없이 채택"했는지 알 수 없다(FR-07 수용 기준).
    """

    task: TaskIn
    reason: str = Field(min_length=1, max_length=200)
    actor: str = Field(min_length=1, max_length=64)


class CancelTaskIn(BaseModel):
    reason: str = Field(min_length=1, max_length=200)
    actor: str = Field(min_length=1, max_length=64)


class QuestionBlocksIn(BaseModel):
    """이 결정을 기다리는 Task 를 사람이 고친다.

    **질문에 답하는 것이 아니다.** 연결을 고쳐도 질문은 여전히 `open` 이고 연결된
    Task 는 계속 막힌다 — 연결은 "누가 기다리는가"이지 "결정됐는가"가 아니다.
    """

    task_keys: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=200)
    actor: str = Field(min_length=1, max_length=64)


@router.get("/api/cases/{case_id}/work-graph")
def get_work_graph(request: Request, case_id: str) -> dict[str, Any]:
    """현재 작업 그래프와 Task 별 실행 가능 여부.

    **진입 검사와 같은 값을 본다.** 화면이 따로 계산하면 버튼은 눌리는데 서버가
    거부하는(또는 그 반대의) 상태가 생긴다.
    """
    try:
        return _repo(request).work_graph_state(case_id)
    except NotFoundError as exc:
        raise _handle(exc)


@router.get("/api/cases/{case_id}/work-graph-revisions")
def list_work_graph_revisions(request: Request, case_id: str) -> list[dict[str, Any]]:
    """리비전 이력. **이전 계획은 지워지지 않는다**(FR-07)."""
    try:
        return _repo(request).list_work_graph_revisions(case_id)
    except NotFoundError as exc:
        raise _handle(exc)


@router.get("/api/cases/{case_id}/tasks/{task_key}/runs")
def list_task_runs(request: Request, case_id: str, task_key: str) -> list[dict[str, Any]]:
    """그 Task 키의 실행 이력. **리비전을 가로지른다.**

    재분할이 실패 이력을 초기화하지 않는다는 것을 여기서 확인할 수 있다(FR-07).
    """
    try:
        return _repo(request).task_run_history(case_id, task_key)
    except NotFoundError as exc:
        raise _handle(exc)


@router.post("/api/cases/{case_id}/work-graph/tasks", status_code=201)
def add_task(request: Request, case_id: str, payload: AddTaskIn) -> dict[str, Any]:
    """사람이 Task 를 더한다. **새 리비전이 만들어진다.**"""
    repo = _repo(request)
    try:
        return repo.add_task(
            case_id,
            payload.task.model_dump(mode="json"),
            payload.reason,
            payload.actor,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.post("/api/cases/{case_id}/work-graph/tasks/{task_key}/cancel", status_code=201)
def cancel_task(
    request: Request, case_id: str, task_key: str, payload: CancelTaskIn
) -> dict[str, Any]:
    """사람이 Task 를 취소한다. **행을 지우지 않고** 새 리비전에 취소로 남긴다."""
    repo = _repo(request)
    try:
        return repo.cancel_task(case_id, task_key, payload.reason, payload.actor)
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.put("/api/cases/{case_id}/questions/{question_id}/blocks", status_code=201)
def set_question_blocks(
    request: Request, case_id: str, question_id: str, payload: QuestionBlocksIn
) -> dict[str, Any]:
    """어떤 Task 가 이 결정을 기다리는지 고친다.

    AI가 적은 `blocks` 가 비어 있거나 틀렸을 때 사람이 고칠 수단이 없으면
    **연결 없는 질문 하나가 영원히 전부 막는다.**
    """
    repo = _repo(request)
    try:
        return repo.set_question_blocks(
            case_id, question_id, payload.task_keys, payload.reason, payload.actor
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


# ===================================================================== P3-03
#
# 작업공간과 실행 효과.
#
# **실제 git 작업은 여기에 없다.** 저장소와 파일은 Runner 호스트에 있고(D-43·FR-27)
# 제어부가 직접 git 을 부르면 단일 호스트에서만 동작한다. 이 절의 경로는 "필요하다"를
# 기록하고 Runner 가 보고한 결과를 받는 것뿐이다.
#
# 올라오는 값은 전부 **식별자와 수**다 — 브랜치 이름, 경로, 커밋 SHA, 변경 파일 수,
# 삽입·삭제 줄 수, 명령의 짧은 요약과 종료 코드. diff·파일 경로·명령 원문·빌드
# 로그는 Runner 의 산출물에 있다.


class WorkspaceRequestIn(BaseModel):
    """작업공간 준비 요청.

    `base_ref` 는 **기준 커밋을 고르는 근거**다. 기본값 `HEAD` 는 저장소의 현재
    커밋을 뜻하며 사용자의 미커밋 변경은 포함하지 않는다 — 포함 여부는 별도
    입력이고 기본값을 "포함"으로 두면 선택되지 않은 변경을 조용히 복사하게 된다
    (execution-workspace-review 2절).
    """

    base_ref: str = Field(default="HEAD", min_length=1, max_length=200)
    #: **어느 저장소의 작업공간인가**(P3-R2·D-39). 주지 않으면 모호하지 않은 경우에만
    #: 해석한다 — 쓰기 허용 저장소가 하나뿐이거나, 선택 기록이 없고 등록 저장소가
    #: 하나뿐일 때다. 그 밖에는 `repository_selection_required` 로 거부한다.
    repository_id: str | None = None


class WorkspaceReadyIn(BaseModel):
    runner_id: str
    #: 어느 저장소의 결과인가. 작업공간이 하나뿐이면 생략할 수 있다.
    repository_id: str | None = None
    repo_path: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    #: **기준 커밋 SHA.** 비어 있으면 받지 않는다 — 어떤 코드 위에서 시작했는지
    #: 모르면 나중에 무엇이 바뀌었는지도 말할 수 없다.
    base_commit: str = Field(min_length=7)
    base_ref: str = ""
    #: 준비 시점에 관측한 사용자의 원래 작업 트리. 파일 경로는 올라오지 않는다.
    user_tree_dirty: bool = False
    user_tree_entries: int = 0


class WorkspaceFailedIn(BaseModel):
    runner_id: str
    repository_id: str | None = None
    reason: str = Field(min_length=1, max_length=200)


class RunCommandIn(BaseModel):
    """그 실행이 실제로 실행한 명령 하나.

    `command_summary` 는 짧은 요약이며 원문 대체가 아니다. `exit_code` 가 `None`
    인 것은 **끝을 확인하지 못했다**이며 실패가 아니다.
    """

    seq: int = Field(ge=1)
    command_summary: str = Field(min_length=1, max_length=200)
    exit_code: int | None = None
    duration_ms: int | None = None
    started_at: str | None = None


class RunCommandsIn(BaseModel):
    generation: int
    commands: list[RunCommandIn]


@router.post("/api/cases/{case_id}/workspace", status_code=201)
def request_workspace(
    request: Request, case_id: str, payload: WorkspaceRequestIn
) -> dict[str, Any]:
    """이 업무에 전용 브랜치·worktree 가 필요하다고 기록한다.

    **이 응답은 준비 완료가 아니다.** 상태는 `requested` 이고, Runner 가 실제로
    만든 뒤에야 `ready` 가 된다. 그 전까지 쓰기 요청은 `workspace_not_ready` 로
    거부된다 — 요청을 준비됨으로 읽으면 CLI 가 사용자의 원래 저장소를 직접
    고치게 된다(FR-08·FR-26).

    **선택·쓰기 허용을 여기서 실제로 검사한다**(P3-R2). 선택하지 않은 저장소,
    명시 제외한 저장소, 쓰기를 허용하지 않은 저장소, 기록 저장소에는 작업공간이
    만들어지지 않는다 — 각각 다른 사유 코드로 거부한다.
    """
    try:
        return _repo(request).request_workspace(
            case_id, payload.repository_id, payload.base_ref
        )
    except (NotFoundError, ConflictError, PolicyRefused) as exc:
        raise _handle(exc)


@router.get("/api/cases/{case_id}/workspace")
def get_workspace(request: Request, case_id: str) -> dict[str, Any] | None:
    """작업공간과 그 위에서 일어난 실행 효과.

    **격리 한계를 값으로 함께 보낸다.** 화면이 그 문장을 지어내면 언젠가
    "격리됨"으로 바뀐다(D-44).
    """
    return _repo(request).workspace_view(case_id)


@router.post("/api/runner/{runner_id}/workspace-requests")
def runner_workspace_requests(request: Request, runner_id: str) -> list[dict[str, Any]]:
    """Runner 가 맡을 작업공간 준비 요청을 가져간다.

    **내려보내는 것이 준비 완료로 표시하는 것은 아니다.** 상태는 결과 보고로만
    바뀐다 — 그렇지 않으면 "요청을 받았다"가 "만들었다"가 된다.
    """
    try:
        return _repo(request).claim_workspace_requests(runner_id)
    except NotFoundError as exc:
        raise _handle(exc)


@router.post("/api/runner/workspaces/{case_id}/ready")
def runner_workspace_ready(
    request: Request, case_id: str, payload: WorkspaceReadyIn
) -> dict[str, Any]:
    try:
        return _repo(request).report_workspace_ready(
            case_id=case_id,
            runner_id=payload.runner_id,
            repo_path=payload.repo_path,
            worktree_path=payload.worktree_path,
            branch=payload.branch,
            base_commit=payload.base_commit,
            base_ref=payload.base_ref,
            user_tree_dirty=payload.user_tree_dirty,
            user_tree_entries=payload.user_tree_entries,
            repository_id=payload.repository_id,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.post("/api/runner/workspaces/{case_id}/failed")
def runner_workspace_failed(
    request: Request, case_id: str, payload: WorkspaceFailedIn
) -> dict[str, Any]:
    """만들지 못했다. **실패를 준비됨으로 바꾸지 않는다.**"""
    try:
        return _repo(request).report_workspace_failed(
            case_id, payload.runner_id, payload.reason, payload.repository_id
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.post("/api/runner/runs/{run_id}/commands")
def runner_commands(request: Request, run_id: str, payload: RunCommandsIn) -> dict[str, int]:
    """그 실행이 실제로 실행한 명령을 기록한다(FR-08).

    결과 보고 **전에** 올린다. 검증 실행의 완료 판정이 이 기록의 존재를 보기
    때문이다 — 명령이 하나도 없는 검증은 완료가 아니다.
    """
    try:
        stored = _repo(request).record_run_commands(
            run_id, payload.generation, [c.model_dump() for c in payload.commands]
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)
    return {"stored": stored}


@router.get("/api/runners/{runner_id}/write-slot")
def write_slot(request: Request, runner_id: str) -> dict[str, Any]:
    """그 Runner 가 지금 쓰기를 맡을 수 있는가(FR-26 "동일 Runner 쓰기 기본 1개").

    **거부가 아니라 미룸이다.** 자리가 없으면 그 실행은 `pending` 으로 남았다가
    앞의 쓰기가 끝나면 그대로 배정된다. 화면이 "왜 아직 시작되지 않는가"를
    답할 수 있도록 상태로 내보낸다.
    """
    try:
        return _repo(request).write_slot_state(runner_id)
    except NotFoundError as exc:
        raise _handle(exc)


# =============================================================== P3-R1 정책
#
# **화면을 거치지 않아도 같은 검사를 받는다.** 아래 경로는 모두 `Repository` 의
# 같은 함수를 부르며, 거절 사유는 `PolicyRefusal` 코드로 나간다(FR-29 "직접 실행으로
# 우회하지 않는다").
#
# 어떤 경로도 **실행을 열지 않는다.** 정책을 기록하고 조회할 뿐이며, 각 응답은
# `enforcement` 로 "이 값을 지금 누가 강제하는가"를 함께 말한다.


class AutonomyIn(BaseModel):
    autonomy: Autonomy
    set_by: str = Field(min_length=1, max_length=100)
    reason_summary: str | None = Field(default=None, max_length=200)


class DelegationBasisIn(BaseModel):
    basis_kind: DelegationBasisKind
    summary: str = Field(min_length=1, max_length=200)
    artifact_id: str | None = None
    artifact_rev: int | None = Field(default=None, ge=1)
    decision_id: str | None = None


class CheckpointConfirmIn(BaseModel):
    """controlled 확인 기록.

    `explicit` 를 받는 이유는 P2-02의 동의와 같다 — "진행하라"가 아닌 것을 확인으로
    적지 않는다(D-14·FR-03). 대상과 그 해시를 함께 받는 이유는 확인이 **그 내용에**
    붙기 때문이다(FR-23).
    """

    confirmed_by: str = Field(min_length=1, max_length=100)
    explicit: bool = False
    subject_type: str = Field(min_length=1, max_length=40)
    subject_id: str = Field(min_length=1, max_length=64)
    subject_hash: str | None = Field(default=None, max_length=128)
    note_summary: str | None = Field(default=None, max_length=200)


class CheckpointSupersedeIn(BaseModel):
    reason_summary: str = Field(min_length=1, max_length=200)


class BudgetLimitIn(BaseModel):
    metric: BudgetMetric
    threshold_kind: BudgetThreshold
    limit_value: float = Field(gt=0)
    set_by: str = Field(min_length=1, max_length=100)
    reason_summary: str | None = Field(default=None, max_length=200)


class RepositoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    repo_path: str = Field(min_length=1)
    registered_by: str = Field(default="owner", max_length=100)


class JournalRepositoryIn(BaseModel):
    repository_id: str = Field(min_length=1)


class CaseRepositoryIn(BaseModel):
    """Case 의 저장소 선택과 허용 범위.

    **기본값이 없다.** 쓰기·게시 허용은 호출자가 명시해야 한다. 기본값을 참으로
    두면 선택하는 행동이 곧 권한 부여가 되고, 기본값을 참에서 거짓으로 바꾸는 실수
    하나로 D-64("쓰기 허용은 게시 허용이 아니다")가 깨진다.
    """

    repository_id: str = Field(min_length=1)
    selection_source: RepositorySelectionSource = RepositorySelectionSource.EXPLICIT
    code_write_allowed: bool
    publish_allowed: bool
    selected_by: str = Field(min_length=1, max_length=100)
    reason_summary: str | None = Field(default=None, max_length=200)


class AutoRepositoryIn(BaseModel):
    """허용 **안의** 저장소를 자동으로 추가한다(D-38·D-63, P3-R2).

    `publish_allowed` 가 없다. 게시 허용은 이 경로로 줄 수 없고, 요청에 실어 보내면
    `auto_add_cannot_grant_publish` 로 거절된다 — 쓰기 허용 저장소 추가는 게시 허용
    확대가 아니다(D-64).
    """

    repository_id: str = Field(min_length=1)
    code_write_allowed: bool = True
    selected_by: str = Field(min_length=1, max_length=100)
    reason_summary: str | None = Field(default=None, max_length=200)


@router.get("/api/profiles")
def list_profiles(request: Request) -> dict[str, Any]:
    """여섯 Profile 의 현재 정의(D-62).

    화면·지시문·시험이 같은 정의를 보게 한다. 버전을 함께 내보내는 이유는 Case 가
    자기 버전을 기록하고 그 버전으로 조회하기 때문이다.
    """
    return {
        "current_version": case_profiles.CURRENT_PROFILE_VERSION,
        "profiles": case_profiles.catalog(),
        "note": "정의는 의미 계약이며 고정 pipeline 이 아니다. 공개한 버전은 고치지 않고"
        " 새 버전을 더한다",
    }


@router.get("/api/cases/{case_id}/policy")
def get_case_policy(request: Request, case_id: str) -> dict[str, Any]:
    try:
        return _repo(request).effective_policy(case_id)
    except NotFoundError as exc:
        raise _handle(exc)


@router.put("/api/cases/{case_id}/autonomy")
def set_autonomy(request: Request, case_id: str, payload: AutonomyIn) -> dict[str, Any]:
    """Autonomy 를 명시로 설정한다(D-59).

    **이 설정이 실행 경로를 바꾸지 않는다**(P3-R1). 값과 그 출처가 기록되고,
    controlled 면 확인 지점이 생긴다. 목적별 진입 조건은 R4 에서 이 값을 읽는다.
    """
    try:
        return _repo(request).set_autonomy(
            case_id, payload.autonomy, payload.set_by, payload.reason_summary
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.get("/api/cases/{case_id}/policy-revisions")
def list_policy_revisions(request: Request, case_id: str) -> list[dict[str, Any]]:
    try:
        _repo(request).get_case(case_id)
    except NotFoundError as exc:
        raise _handle(exc)
    return _repo(request).list_policy_revisions(case_id)


@router.post("/api/cases/{case_id}/delegation-basis", status_code=201)
def record_delegation_basis(
    request: Request, case_id: str, payload: DelegationBasisIn
) -> dict[str, Any]:
    try:
        return _repo(request).record_delegation_basis(
            case_id,
            payload.basis_kind,
            payload.summary,
            payload.artifact_id,
            payload.artifact_rev,
            payload.decision_id,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.get("/api/cases/{case_id}/controlled-checkpoints")
def list_checkpoints(request: Request, case_id: str) -> list[dict[str, Any]]:
    try:
        _repo(request).get_case(case_id)
    except NotFoundError as exc:
        raise _handle(exc)
    return _repo(request).list_checkpoints(case_id)


@router.post(
    "/api/cases/{case_id}/controlled-checkpoints/{checkpoint}/confirmation", status_code=201
)
def confirm_checkpoint(
    request: Request,
    case_id: str,
    checkpoint: ControlledCheckpoint,
    payload: CheckpointConfirmIn,
) -> list[dict[str, Any]]:
    """사람이 그 확인 지점을 실제로 확인했다(D-65).

    **이 기록이 권한을 만들지 않는다.** push·게시 허용은 `decisions`, 최종 인수는
    `acceptance` 의 별도 기록이며 이 응답에는 어느 쪽도 들어 있지 않다.
    """
    try:
        return _repo(request).confirm_checkpoint(
            case_id,
            checkpoint,
            payload.confirmed_by,
            payload.explicit,
            payload.subject_type,
            payload.subject_id,
            payload.subject_hash,
            payload.note_summary,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.post(
    "/api/cases/{case_id}/controlled-checkpoints/{checkpoint}/supersede", status_code=201
)
def supersede_checkpoint(
    request: Request,
    case_id: str,
    checkpoint: ControlledCheckpoint,
    payload: CheckpointSupersedeIn,
) -> list[dict[str, Any]]:
    """확인한 대상이 바뀌었다. 확인 기록을 남기고 새 요구를 만든다(D-65)."""
    try:
        return _repo(request).supersede_checkpoint(
            case_id, checkpoint, payload.reason_summary
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


# ===================================================== P3-R4 자동 진행·정합성


class LightConformanceIn(BaseModel):
    intent_version_id: str = Field(min_length=1, max_length=100)


class DeltaAssessmentIn(BaseModel):
    assessment: str = Field(min_length=1, max_length=200)


class DeltaConfirmIn(BaseModel):
    actor: str = Field(min_length=1, max_length=100)
    explicit: bool = False
    note_summary: str | None = Field(default=None, max_length=200)


@router.get("/api/cases/{case_id}/conformance")
def get_conformance(request: Request, case_id: str) -> dict[str, Any]:
    """요청 정합성 확인의 **방식과 남은 불확실성**(D-25).

    가벼운 확인과 독립 의미 검토를 같은 `pass` 로 보이지 않게 하는 조회다.
    `method` 가 무엇을 실제로 했는지이고 `unverified_scope` 가 보지 않은 것이다.
    """
    try:
        _repo(request).get_case(case_id)
    except NotFoundError as exc:
        raise _handle(exc)
    return _repo(request).conformance_state(case_id)


@router.post("/api/cases/{case_id}/conformance-checks/light", status_code=201)
def record_light_conformance(
    request: Request, case_id: str, payload: LightConformanceIn
) -> dict[str, Any]:
    """가벼운 요청 정합성 확인을 기록한다.

    **독립 검토 완료로 표시되지 않는다.** 규칙이 독립 검토를 요구하면 이 기록이
    있어도 게이트는 통과하지 않으며, 응답의 `required_method` 가 그 사실을 말한다.
    """
    repo = _repo(request)
    try:
        intent = repo.get_intent_version(payload.intent_version_id)
        if intent["case_id"] != case_id:
            raise ConflictError("intent version belongs to another case")
        return repo.record_light_conformance_check(payload.intent_version_id)
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


class ConformancePolicyIn(BaseModel):
    required: bool
    set_by: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=200)


@router.put("/api/cases/{case_id}/conformance-policy")
def set_conformance_policy(
    request: Request, case_id: str, payload: ConformancePolicyIn
) -> dict[str, Any]:
    """이 Case 에 독립 의미 검토를 요구한다(D-25).

    **올리는 방향으로만 작용한다.** 끄더라도 수준·근거 부족·미확인 변경이 독립
    검토를 요구하면 그대로 요구된다 — 응답의 `required_method` 가 그 사실을 말한다.
    """
    try:
        return _repo(request).require_independent_review(
            case_id, payload.required, payload.set_by, payload.reason
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.get("/api/cases/{case_id}/material-deltas")
def get_material_deltas(request: Request, case_id: str) -> dict[str, Any]:
    """마지막 유효 위임 기준 대비 **누적 변경**과 그것이 막는 작업(D-60)."""
    try:
        _repo(request).get_case(case_id)
    except NotFoundError as exc:
        raise _handle(exc)
    return _repo(request).material_delta_state(case_id)


@router.post("/api/cases/{case_id}/material-deltas/{delta_id}/assessment")
def assess_material_delta(
    request: Request, case_id: str, delta_id: str, payload: DeltaAssessmentIn
) -> dict[str, Any]:
    """AI 의 의미 평가를 기록한다. **상태는 바뀌지 않는다.**

    "'의미가 같음'이라는 주장만으로 새 의미를 승인하지 않는다"(D-60). 이 경로에
    해소 분기가 없는 것이 계약이다.
    """
    try:
        return _repo(request).record_delta_assessment(delta_id, payload.assessment)
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.post("/api/cases/{case_id}/material-deltas/{delta_id}/confirmation", status_code=201)
def confirm_material_delta(
    request: Request, case_id: str, delta_id: str, payload: DeltaConfirmIn
) -> dict[str, Any]:
    """사람이 그 변경 한 건을 확인한다. 남은 변경은 그대로 남는다."""
    try:
        return _repo(request).confirm_material_delta(
            delta_id, payload.actor, payload.explicit, payload.note_summary
        )
    except (NotFoundError, ConflictError, PolicyRefused) as exc:
        raise _handle(exc)


@router.get("/api/cases/{case_id}/budget")
def get_budget(request: Request, case_id: str) -> dict[str, Any]:
    try:
        _repo(request).get_case(case_id)
    except NotFoundError as exc:
        raise _handle(exc)
    return _repo(request).budget_state(case_id)


@router.put("/api/cases/{case_id}/budget", status_code=201)
def set_budget(request: Request, case_id: str, payload: BudgetLimitIn) -> dict[str, Any]:
    """예산 한도를 설정한다(D-56·D-61).

    **강제할 수 없는 정확한 hard 한도는 거부한다.** 저장해 두면 설정한 사람은 상한이
    있다고 믿는데 시스템은 그것을 지킬 방법이 없다.
    """
    try:
        return _repo(request).set_budget_limit(
            case_id,
            payload.metric,
            payload.threshold_kind,
            payload.limit_value,
            payload.set_by,
            payload.reason_summary,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.delete("/api/cases/{case_id}/budget/{metric}/{threshold_kind}")
def clear_budget(
    request: Request, case_id: str, metric: BudgetMetric, threshold_kind: BudgetThreshold
) -> dict[str, Any]:
    try:
        return _repo(request).clear_budget_limit(case_id, metric, threshold_kind)
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.get("/api/projects/{project_id}/repositories")
def list_project_repositories(request: Request, project_id: str) -> dict[str, Any]:
    try:
        return _repo(request).project_repository_view(project_id)
    except NotFoundError as exc:
        raise _handle(exc)


@router.post("/api/projects/{project_id}/repositories", status_code=201)
def register_repository(
    request: Request, project_id: str, payload: RepositoryIn
) -> dict[str, Any]:
    """Project 에 저장소를 등록한다(D-38).

    등록은 선택도 허용도 아니다. 어떤 Case 도 이 등록만으로 그 저장소를 쓰지 않는다.
    """
    try:
        return _repo(request).register_project_repository(
            project_id, payload.name, payload.repo_path, payload.registered_by
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.put("/api/projects/{project_id}/journal-repository")
def set_journal_repository(
    request: Request, project_id: str, payload: JournalRepositoryIn
) -> dict[str, Any]:
    """기록 이슈를 만들 저장소를 지정한다(D-17·D-34·FR-30).

    **코드 대상이 아니다.** 이 저장소를 코드 쓰기 대상으로 선택하려는 요청은
    거부된다.
    """
    try:
        return _repo(request).set_journal_repository(project_id, payload.repository_id)
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.get("/api/cases/{case_id}/repositories")
def list_case_repositories(request: Request, case_id: str) -> dict[str, Any]:
    try:
        return _repo(request).case_repository_state(case_id)
    except NotFoundError as exc:
        raise _handle(exc)


@router.put("/api/cases/{case_id}/repositories", status_code=201)
def select_case_repository(
    request: Request, case_id: str, payload: CaseRepositoryIn
) -> dict[str, Any]:
    """Case 의 저장소 선택과 허용 범위를 기록한다(D-63·D-64).

    **작업공간을 만들지 않는다.** Case×Repo worktree 준비는 R2 이며, 이 기록만으로
    쓰기 실행이 열리지도 않는다 — 진입 검사는 여전히 P3-03의 단일 작업공간을 본다.
    """
    try:
        return _repo(request).select_case_repository(
            case_id,
            payload.repository_id,
            payload.selection_source,
            payload.code_write_allowed,
            payload.publish_allowed,
            payload.selected_by,
            payload.reason_summary,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.post("/api/cases/{case_id}/repositories/auto", status_code=201)
def auto_select_case_repository(
    request: Request, case_id: str, payload: AutoRepositoryIn
) -> dict[str, Any]:
    """허용 **안의** 저장소를 자동으로 추가한다(D-38·D-63, P3-R2).

    D-38의 "기존 허용 쓰기 범위와 목표 안의 추가 저장소는 자동 선택한다"가 여기다.
    같은 문장의 뒷부분 — "명시적 제외·새 권한·제품/데이터 영향은 재판단한다" — 은
    거절로 구현된다. 거절 응답은 사유 코드와 함께 `requires_human_confirmation` 을
    실어 화면이 무엇을 물어야 하는지 말한다.

    **질문을 자동으로 만들지 않는다.** 질문 생성과 누적 material delta 판단은 R4다.
    """
    try:
        return _repo(request).auto_select_repository(
            case_id,
            payload.repository_id,
            payload.selected_by,
            payload.code_write_allowed,
            False,
            payload.reason_summary,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)


@router.get("/api/cases/{case_id}/composition")
def get_code_composition(request: Request, case_id: str) -> dict[str, Any] | None:
    """이 업무의 현재 코드 조합(execution-workspace-review 2.1절).

    **조회가 새 조합을 만들지 않는다.** 기록된 조합과 지금 상태가 같은지는
    `matches_current_state` 가 말하며, 다르다고 여기서 조용히 갱신하면 근거가
    가리키는 조합이 손 없이 바뀐다.
    """
    try:
        return _repo(request).code_composition_view(case_id)
    except NotFoundError as exc:
        raise _handle(exc)


@router.post("/api/cases/{case_id}/composition", status_code=201)
def build_code_composition(request: Request, case_id: str) -> dict[str, Any] | None:
    """지금 상태로 코드 조합을 **고정한다.**

    같은 상태에서 다시 부르면 새 revision 을 만들지 않고 현재 조합을 돌려준다.
    준비된 작업공간이 하나도 없으면 `null` 이다 — 빈 조합을 만들지 않는다.
    """
    try:
        return _repo(request).build_code_composition(case_id)
    except NotFoundError as exc:
        raise _handle(exc)


@router.get("/api/cases/{case_id}/compositions/{composition_id}")
def get_one_code_composition(
    request: Request, case_id: str, composition_id: str
) -> dict[str, Any]:
    """특정 조합과 그것이 **아직 유효한가**(P3-R2).

    유효성은 저장하지 않고 도출한다. 핵심은 **저장소별로** 본다는 것이다 — 이
    조합에 들어 있지 않은 저장소가 바뀐 것은 이 조합과 무관하며, 그것으로 증거를
    폐기하면 무관한 Repo 변경이 모든 근거를 쓸어버린다
    (execution-workspace-review 2.1절).
    """
    repo = _repo(request)
    try:
        composition = repo.get_code_composition(composition_id)
        if composition["case_id"] != case_id:
            raise NotFoundError(f"code composition not found in case: {composition_id}")
        composition["validity"] = repo.composition_validity(case_id, composition_id)
        return composition
    except NotFoundError as exc:
        raise _handle(exc)
