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
from domain import ids, intent_doc
from domain.models import (
    AgreementRefusal,
    ArtifactKind,
    AuthoringMode,
    Availability,
    CaseKind,
    ConfirmationState,
    ContentOrigin,
    DecideAt,
    DecisionKind,
    Permission,
    ReadRequestState,
    RunOutcome,
    RunPurpose,
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
    case["admission_checks"] = repo.list_admission_checks(case_id)
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
        body = intent_doc.compose(
            fields={k: v.model_dump() for k, v in payload.fields.items()},
            questions=[q.model_dump() for q in payload.questions],
            case_id=case_id,
            authored_by=payload.authored_by,
        )
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
            payload.intent_version_id, payload.fields, payload.questions
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
