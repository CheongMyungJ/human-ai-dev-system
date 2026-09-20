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
from controller.repository import ConflictError, NotFoundError, Repository
from domain import ids
from domain.models import (
    ArtifactKind,
    Availability,
    CaseKind,
    DecisionKind,
    Permission,
    RunOutcome,
    RunRole,
)

router = APIRouter()


def _repo(request: Request) -> Repository:
    return Repository(request.app.state.conn)


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    raise exc


# --------------------------------------------------------------------- models


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    repo_path: str = Field(min_length=1)
    default_tool_id: str = Field(default="codex")


class CaseIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    kind: CaseKind = CaseKind.FEATURE


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
    run_id: str | None = None
    task_id: str = "task-1"
    role: RunRole = RunRole.AUTHOR
    tool_id: str = "local-echo"
    mode: str = "p2-01-local"
    permission: Permission = Permission.READ_ONLY
    instruction_artifact_id: str
    instruction_artifact_rev: int = 1


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

    def produce():
        try:
            return repo.create_case(project_id, payload.title, payload.kind), 201
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
    case["intent_versions"] = repo.list_intent_versions(case_id)
    case["decisions"] = repo.list_decisions(case_id)
    case["runs"] = repo.list_runs(case_id)
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
    """Run 생성. `run_id` 가 멱등 키다.

    같은 `run_id` 로 다시 호출하면 새 Run도 새 배정도 만들지 않고 기존 Run을 돌려준다.
    그 경우 상태 코드는 **200**이다. 만들지 않은 것을 201 Created 로 보고하지 않는다.
    응답의 `created` 로도 구별할 수 있다.
    """
    repo = _repo(request)
    run_id = payload.run_id or ids.new_run_id()
    try:
        run, created = repo.create_run(
            run_id=run_id,
            case_id=case_id,
            task_id=payload.task_id,
            role=payload.role,
            tool_id=payload.tool_id,
            mode=payload.mode,
            permission=payload.permission,
            instruction_artifact_id=payload.instruction_artifact_id,
            instruction_artifact_rev=payload.instruction_artifact_rev,
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle(exc)
    if not created:
        response.status_code = 200
    return {"run": run, "created": created}


@router.get("/api/runs/{run_id}")
def get_run(request: Request, run_id: str) -> dict[str, Any]:
    repo = _repo(request)
    try:
        run = repo.get_run(run_id)
    except NotFoundError as exc:
        raise _handle(exc)
    run["events"] = repo.list_events(run_id)
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
        out.append(
            {
                "intake_id": intake["id"],
                "case_id": intake["case_id"],
                "kind": intake["kind"],
                "artifact_id": intake["artifact_id"],
                "revision": intake["revision"],
                "expected_hash": intake["expected_hash"],
                "content_b64": base64.b64encode(body).decode("ascii"),
            }
        )
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
