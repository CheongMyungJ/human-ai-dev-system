"""제어부 상태 DB 접근.

이 계층은 SQL만 다루고 HTTP를 모른다. 정책 판단은 최소한으로 두되
아래 두 가지는 여기서 지킨다.

  - 원문 본문을 저장하지 않는다. 본문을 받는 인자가 없다.
  - 같은 `run_id` 는 두 번 만들어지지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Iterable

from controller import gate as gatemod
from controller import sizing as sizingmod
from controller import work_graph as workgraph
from controller.admission import AdmissionRequest, AdmissionResult, budget_refusal_reason
from controller.admission import evaluate as evaluate_admission
from controller.db import (
    context_package_bytes,
    elapsed_seconds,
    parse_ts,
    transaction,
    utc_now,
)
from domain import completion_meaning as meaningmod
from domain import ids, prep_doc, profiles, quality
from domain import progression
from domain.progression import (
    LIGHT_UNVERIFIED_SCOPE,
    NEEDS_CONTROLLED_START,
    SATISFACTION_NEEDING_RUN_EVIDENCE,
    assess_fast_lane,
    classify_change,
    conformance_satisfies,
    derived_completion_mode,
    derived_review_mode,
    effective_autonomy,
    experiment_allowed,
    purpose_outside_objective,
    required_conformance_method,
    required_stages,
)
from domain.budget import (
    RESERVATION_KIND,
    BudgetGuarantee,
    ReservationKind,
    ReservationSource,
    ReservationState,
    SettleSource,
    guarantee_for,
    measurement_for_settlement,
    normalize_usage,
    planned_reservation,
    reservation_contract,
)
from domain.models import (
    BUDGET_MEASUREMENT,
    BUDGET_UNIT,
    POLICY_VERSION,
    AcceptanceMode,
    AcceptanceRefusal,
    AdmissionOutcome,
    AdmissionRefusal,
    ArtifactKind,
    AuthoringMode,
    Autonomy,
    AutonomySource,
    Availability,
    AxisWeight,
    BudgetEnforcement,
    BudgetMeasurement,
    BudgetMetric,
    BudgetThreshold,
    CapabilityState,
    CandidateState,
    ClaimDeferral,
    CaseKind,
    CaseProfile,
    CaseRelationKind,
    CaseStatus,
    CheckpointState,
    ClosureKind,
    CompletionMode,
    CompositionEntrySource,
    Conclusion,
    ConclusionRule,
    ConfirmationState,
    ConformanceMethod,
    ContentOrigin,
    ContextRefRole,
    ControlledCheckpoint,
    CriterionObligation,
    CriterionState,
    CriterionVerdict,
    DecideAt,
    DecisionKind,
    DelegationBasisKind,
    DeltaChangeClass,
    DeltaState,
    EffectiveAutonomySource,
    EvidenceKind,
    FeedbackState,
    FieldChange,
    FindingCertainty,
    FindingSeverity,
    FindingSource,
    GateId,
    GateVerdict,
    IntentAgreementState,
    IntentField,
    IntentStatus,
    Materiality,
    Permission,
    PolicyRefusal,
    PolicyState,
    PreparationStage,
    PreparationState,
    ProfileSource,
    QuestionState,
    ReadRequestState,
    RepositorySelectionSource,
    RepositorySource,
    ReviewMode,
    RunOutcome,
    RunPurpose,
    RunRole,
    RunStatus,
    Satisfaction,
    SizingAxis,
    SizingSource,
    SizingState,
    StageReviewState,
    TaskKind,
    TaskRelation,
    TaskState,
    WorkGraphSource,
    WorkGraphState,
    WorkLevel,
    WorkspaceAllowanceSource,
    WorkspaceState,
)

MAX_SUMMARY = 200

#: 읽기 전용이 아닌 권한. 이 권한의 실행은 같은 Case 안에서 직렬화한다(FR-26).
WRITE_PERMISSIONS = (
    Permission.WORKSPACE_WRITE.value,
    Permission.EXPLICIT_ESCALATED.value,
)

#: 같은 Runner 가 동시에 맡는 쓰기 실행의 기본 수(FR-26·D-55).
RUNNER_WRITE_LIMIT = 1

#: 보장 범위 → `budget_setting.enforcement` 에 적는 값(P3-R3).
#:
#: 표를 따로 두는 이유는 `domain.budget` 이 "무엇을 약속할 수 있는가"만 알고
#: 저장 표현을 모르게 하기 위해서다. 계약과 컬럼 값이 한 곳에 섞이면 컬럼을 바꿀 때
#: 계약이 조용히 따라 바뀐다.
_ENFORCEMENT_FOR_GUARANTEE: dict[BudgetGuarantee, BudgetEnforcement] = {
    BudgetGuarantee.ABSOLUTE: BudgetEnforcement.ENFORCED_ABSOLUTE,
    BudgetGuarantee.NO_ABSOLUTE_CAP: BudgetEnforcement.ENFORCED_NO_ABSOLUTE_CAP,
    BudgetGuarantee.DISPLAY_ONLY: BudgetEnforcement.DISPLAY_ONLY,
    BudgetGuarantee.NOT_ENFORCEABLE: BudgetEnforcement.NOT_ENFORCEABLE,
}


class ConflictError(Exception):
    """요청이 현재 상태와 맞지 않는다. HTTP 409로 돌려준다."""


class NotFoundError(Exception):
    """대상 기록이 없다. HTTP 404로 돌려준다."""


class PolicyRefused(ConflictError):
    """정책·Profile·저장소·예산 설정을 받을 수 없다(P3-R1).

    **네 번째 독립 거절 목록이다**(`PolicyRefusal`). 동의를 기록할 수 있는가,
    실행을 배정해도 되는가, 종료로 확정해도 되는가와 합치지 않는다 — 이쪽은
    "이 설정을 받아도 되는가"이며 그 판단 근거가 다르다(FR-23).
    """

    def __init__(self, refusals: list[PolicyRefusal]) -> None:
        self.refusals = refusals
        super().__init__("policy refused: " + ", ".join(r.value for r in refusals))


class BudgetExhausted(ConflictError):
    """설정된 hard 예산이 이 실행을 허용하지 않는다(P3-R3).

    **진입 거부(`AdmissionRefusal.BUDGET_HARD_LIMIT_REACHED`)와 짝이지 같은 것이
    아니다.** 진입 검사는 "왜 실행이 열리지 않았는가"를 사람에게 남기고, 이 예외는
    Run 생성 트랜잭션 **안에서** 마지막 한 칸의 경쟁을 막는다. 둘 중 하나만 두면
    앞의 것만으로는 동시 요청이 함께 통과하고, 뒤의 것만으로는 거부 사유가 기록되지
    않는다(autonomy-budget-policy 8절).
    """

    def __init__(self, breaches: list[dict[str, Any]]) -> None:
        self.breaches = breaches
        super().__init__(
            "budget hard limit reached: "
            + ", ".join(str(b.get("metric")) for b in breaches)
        )


class AcceptanceRefused(ConflictError):
    """최종 인수·예외 수용을 기록할 수 없다.

    **사유 코드를 들고 다니는 것이 핵심이다.** 화면과 API 직접 호출이 같은 코드를
    받아야 "왜 종료가 확정되지 않았는가"를 같은 근거로 설명할 수 있다.
    P2-02의 동의 거절, P2-03의 진입 거부와 **별개 목록**이다(FR-23).
    """

    def __init__(self, refusals: list[AcceptanceRefusal]) -> None:
        self.refusals = refusals
        super().__init__("acceptance refused: " + ", ".join(r.value for r in refusals))


def _snapshot_hash(payload: str) -> str:
    """종료 후보 내용의 지문. 사용자가 본 후보가 지금 것과 같은지 대조한다."""
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _summary(text: str) -> str:
    """목록 표시용 짧은 요약. 원문을 대체하지 않는다.

    상한을 넘기면 자른다. 본문을 요약 컬럼에 밀어 넣는 우회를 막는 것이 목적이다.
    """
    one_line = " ".join(text.split())
    if len(one_line) <= MAX_SUMMARY:
        return one_line
    return one_line[: MAX_SUMMARY - 1] + "…"


def _quality_ref(value: Any, *, field: str, maximum: int = 160) -> str:
    """P4 게이트 표에 본문 대신 들어가는 짧은 식별 참조를 검증한다."""
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or "\n" in value
        or "\r" in value
    ):
        raise ConflictError(f"{field} must be a short reference identifier, not a body")
    return value


def _field_name(field: str) -> str:
    """의도 항목 이름을 검증한다 — 공통 여섯 항목 또는 Profile 의미 항목(P3-R1).

    `IntentField(...)` 하나로 검증하던 자리다. 모르는 이름을 그대로 저장하지 않는
    이유는 그대로다: 오타가 새 항목이 되면 필수 항목 검사가 무의미해진다.
    """
    try:
        return IntentField(field).value
    except ValueError:
        pass
    try:
        return profiles.ProfileField(field).value
    except ValueError as exc:
        # 거절 사유를 예외로 남긴다. 조용히 통과시키면 오타가 새 항목이 되고,
        # 그대로 죽으면 화면이 "무엇이 잘못됐는가"를 말할 수 없다.
        raise ConflictError(f"unknown intent field: {field}") from exc


def _criterion_fingerprint(criterion: Any) -> str:
    """성공 기준 한 건의 **내용 지문**(P3-R4).

    요약·확인 방법·연결 항목을 함께 해시한다. 기준의 본문은 Runner 에 있고 제어부가
    가진 것은 이 셋뿐이므로, 여기서 같으면 제어부가 관측할 수 있는 범위에서 같다.
    **그것이 전부라고 주장하지 않는다** — 요약이 같은데 본문이 달라졌을 수 있고,
    그 경우는 의미 검토가 본다.
    """
    parts = [
        str(criterion["summary"]),
        str(criterion["method_summary"]),
        str(criterion["relates_to"]),
    ]
    # **P4-03: 목적 의무와 결론 요구도 기준의 내용이다.** 결론 요구를 확정 필수에서
    # 판단 불가 허용으로 바꾸는 것이 완료를 쉽게 만드는 가장 조용한 변경이며, 지문이
    # 그것을 보지 않으면 material delta 가 되지 않는다(D-60 "기준 약화도 감지 대상").
    #
    # **값이 있을 때만 더한다.** v1 기준(둘 다 NULL)의 지문은 P4-03 이전과 같아야
    # 한다 — 달라지면 이미 기록된 누적 변경의 해시와 어긋나고 이어 가던 판정이 끊긴다.
    for name in ("obligation", "conclusion_rule"):
        value = _row_get(criterion, name)
        if value is not None:
            parts.append(f"{name}={value}")
    return _snapshot_hash("\x00".join(parts))


def _row_get(row: Any, name: str) -> Any:
    """`sqlite3.Row` 와 dict 를 같은 방식으로 읽는다. 컬럼이 없으면 `None`."""
    try:
        return row[name]
    except (IndexError, KeyError):
        return None


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class Repository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ------------------------------------------------------------------ owner

    def ensure_owner(self, name: str = "local-owner") -> str:
        row = self.conn.execute("SELECT id FROM owner WHERE name = ?", (name,)).fetchone()
        if row:
            return row["id"]
        owner_id = ids.new_owner_id()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO owner (id, name, created_at) VALUES (?, ?, ?)",
                (owner_id, name, utc_now()),
            )
        return owner_id

    # ---------------------------------------------------------------- project

    def create_project(self, name: str, repo_path: str, default_tool_id: str) -> dict[str, Any]:
        """Project 를 만든다.

        **P3-R1: 만들면서 등록 저장소 한 건을 함께 넣는다**(D-38). `repo_path` 컬럼은
        그대로 유지한다 — 기존 배정·작업공간 경로가 그 값을 쓰고, 컬럼을 지우면 이
        단계의 범위(모델과 이행)를 넘어 실행 경로까지 바꾸게 된다. 두 곳의 값은
        같으며 `project_repository` 가 정본이 되는 시점은 R2 다.
        """
        owner_id = self.ensure_owner()
        project_id = ids.new_project_id()
        now = utc_now()
        try:
            with transaction(self.conn):
                self.conn.execute(
                    "INSERT INTO project (id, owner_id, name, repo_path, default_tool_id, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (project_id, owner_id, name, repo_path, default_tool_id, now),
                )
                self.conn.execute(
                    "INSERT INTO project_repository"
                    " (id, project_id, name, repo_path, source, registered_by, registered_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        ids.new_id("repo"),
                        project_id,
                        "primary",
                        repo_path,
                        RepositorySource.REGISTERED.value,
                        "owner",
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"project name already used: {name}") from exc
        return self.get_project(project_id)

    def list_projects(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM project ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    def get_project(self, project_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM project WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"project not found: {project_id}")
        return dict(row)

    # ----------------------------------------------------------------- runner

    def register_runner(
        self,
        runner_id: str,
        name: str,
        host: str,
        capabilities: Iterable[dict[str, Any]] = (),
    ) -> dict[str, Any]:
        """등록은 멱등이다. 같은 runner_id 의 재등록은 능력 보고만 갱신한다."""
        now = utc_now()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO runner (id, name, host, status, registered_at, last_heartbeat_at)"
                " VALUES (?, ?, ?, 'registered', ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET"
                "   name = excluded.name, host = excluded.host,"
                "   status = 'registered', last_heartbeat_at = excluded.last_heartbeat_at",
                (runner_id, name, host, now, now),
            )
            for cap in capabilities:
                state = CapabilityState(cap["state"]).value
                self.conn.execute(
                    "INSERT INTO runner_capability"
                    " (runner_id, tool_id, mode, capability, state, source, observed_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(runner_id, tool_id, mode, capability) DO UPDATE SET"
                    "   state = excluded.state, source = excluded.source,"
                    "   observed_at = excluded.observed_at",
                    (
                        runner_id,
                        cap["tool_id"],
                        cap["mode"],
                        cap["capability"],
                        state,
                        cap.get("source", "unspecified"),
                        now,
                    ),
                )
        return self.get_runner(runner_id)

    def get_runner(self, runner_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM runner WHERE id = ?", (runner_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"runner not found: {runner_id}")
        runner = dict(row)
        caps = self.conn.execute(
            "SELECT tool_id, mode, capability, state, source, observed_at"
            " FROM runner_capability WHERE runner_id = ? ORDER BY tool_id, mode, capability",
            (runner_id,),
        ).fetchall()
        runner["capabilities"] = [dict(c) for c in caps]
        return runner

    def list_runners(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT id FROM runner ORDER BY registered_at").fetchall()
        return [self.get_runner(r["id"]) for r in rows]

    def heartbeat(self, runner_id: str) -> None:
        with transaction(self.conn):
            cur = self.conn.execute(
                "UPDATE runner SET last_heartbeat_at = ?, status = 'registered' WHERE id = ?",
                (utc_now(), runner_id),
            )
        if cur.rowcount == 0:
            raise NotFoundError(f"runner not found: {runner_id}")

    # ------------------------------------------------------------------- case

    def create_case(
        self,
        project_id: str,
        title: str,
        kind: CaseKind | None = None,
        profile: CaseProfile | None = None,
    ) -> dict[str, Any]:
        """Case 를 만든다.

        **P3-R1: Profile 과 기본 Autonomy 가 여기서 기록된다.**

        Profile 과 `kind` 는 한쪽에서 다른 쪽을 유도한다. 요청에 Profile 이 있으면
        `kind` 를 유도하고 출처는 `explicit` 이다. `kind` 만 있으면 Profile 을
        유도하고 출처는 `derived_from_kind` — **사람의 선택이 아니라는 사실을 남긴다**
        (FR-04). 둘 다 없으면 거부한다. 기본값을 지어내면 그 Case 의 목적이 시스템이
        고른 것이 된다.

        기본 Autonomy 는 `ask_on_decision` 이며 출처는 `system_default` 다(D-11·D-21).
        **행을 만들어 두는 이유**는 "행이 없음"이 R1 이전 Case 의 미기록을 뜻해야
        하기 때문이다 — 두 상태가 같은 모습이면 마이그레이션이 구별을 잃는다.
        """
        self.get_project(project_id)
        if profile is None and kind is None:
            raise ConflictError("case needs a profile or a kind")
        if profile is not None:
            resolved_profile = CaseProfile(profile)
            resolved_kind = profiles.KIND_FOR_PROFILE[resolved_profile]
            source = ProfileSource.EXPLICIT
        else:
            resolved_kind = CaseKind(kind)
            resolved_profile = profiles.PROFILE_FOR_KIND[resolved_kind]
            source = ProfileSource.DERIVED_FROM_KIND
        case_id = ids.new_case_id()
        now = utc_now()
        with transaction(self.conn):
            self.conn.execute(
                'INSERT INTO "case" (id, project_id, title, kind, status, created_at,'
                " updated_at, profile, profile_version, profile_source)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    case_id,
                    project_id,
                    _summary(title),
                    resolved_kind.value,
                    CaseStatus.RECEIVED.value,
                    now,
                    now,
                    resolved_profile.value,
                    profiles.CURRENT_PROFILE_VERSION,
                    source.value,
                ),
            )
            self.conn.execute(
                "INSERT INTO case_policy"
                " (id, case_id, revision, autonomy, autonomy_source, policy_version,"
                "  set_by, reason_summary, state, created_at)"
                " VALUES (?, ?, 1, ?, ?, ?, 'system', NULL, ?, ?)",
                (
                    ids.new_id("pol"),
                    case_id,
                    Autonomy.ASK_ON_DECISION.value,
                    AutonomySource.SYSTEM_DEFAULT.value,
                    POLICY_VERSION,
                    PolicyState.CURRENT.value,
                    now,
                ),
            )
        return self.get_case(case_id)

    def list_cases(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            'SELECT * FROM "case" WHERE project_id = ? ORDER BY created_at DESC', (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_case(self, case_id: str) -> dict[str, Any]:
        row = self.conn.execute('SELECT * FROM "case" WHERE id = ?', (case_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"case not found: {case_id}")
        return dict(row)

    def set_case_status(self, case_id: str, status: CaseStatus) -> None:
        with transaction(self.conn):
            self.conn.execute(
                'UPDATE "case" SET status = ?, updated_at = ? WHERE id = ?',
                (status.value, utc_now(), case_id),
            )

    # --------------------------------------------------------------- artifact

    def get_artifact_ref(self, artifact_id: str, revision: int) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM artifact_ref WHERE artifact_id = ? AND revision = ?",
            (artifact_id, revision),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"artifact not found: {artifact_id}@{revision}")
        return dict(row)

    def register_runner_artifact(
        self,
        case_id: str,
        kind: ArtifactKind,
        artifact_id: str,
        revision: int,
        owner_runner_id: str,
        content_hash: str,
        byte_size: int,
        summary: str,
    ) -> dict[str, Any]:
        """Runner가 이미 영속 저장한 산출물의 참조를 등록한다.

        본문은 오지 않는다. Runner가 소유하고 있으므로 처음부터 `available` 이다.
        중계(intake)와 방향이 반대다: 실행 출력은 Runner에서 생긴다.
        """
        self.get_case(case_id)
        self.get_runner(owner_runner_id)
        existing = self.conn.execute(
            "SELECT * FROM artifact_ref WHERE artifact_id = ? AND revision = ?",
            (artifact_id, revision),
        ).fetchone()
        if existing is not None:
            if existing["content_hash"] != content_hash:
                raise ConflictError("artifact revision already registered with a different hash")
            return dict(existing)
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO artifact_ref (artifact_id, revision, case_id, kind, content_hash,"
                " byte_size, owner_runner_id, availability, summary, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    artifact_id,
                    revision,
                    case_id,
                    kind.value,
                    content_hash,
                    byte_size,
                    owner_runner_id,
                    Availability.AVAILABLE.value,
                    _summary(summary),
                    utc_now(),
                ),
            )
        return self.get_artifact_ref(artifact_id, revision)

    def list_artifact_refs(self, case_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM artifact_ref WHERE case_id = ? ORDER BY created_at",
            (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ----------------------------------------------------------------- intake

    def open_intake(
        self,
        case_id: str,
        kind: ArtifactKind,
        target_runner_id: str,
        expected_hash: str,
        byte_size: int,
        summary: str,
        artifact_id: str | None = None,
        revision: int = 1,
    ) -> dict[str, Any]:
        """원문 접수를 연다. **본문은 받지 않는다.**

        참조를 `pending` 으로 만들고, Runner가 영속 저장을 보고해야 `available` 이 된다.
        그 전까지는 저장 완료가 아니다(NFR-01, D-51).
        """
        self.get_case(case_id)
        self.guard_open_case(case_id)
        self.get_runner(target_runner_id)
        artifact_id = artifact_id or ids.new_artifact_id()
        intake_id = ids.new_intake_id()
        now = utc_now()
        short = _summary(summary)
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO artifact_ref (artifact_id, revision, case_id, kind, content_hash,"
                " byte_size, owner_runner_id, availability, summary, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    artifact_id,
                    revision,
                    case_id,
                    kind.value,
                    expected_hash,
                    byte_size,
                    target_runner_id,
                    Availability.PENDING.value,
                    short,
                    now,
                ),
            )
            self.conn.execute(
                "INSERT INTO intake (id, case_id, kind, artifact_id, revision, target_runner_id,"
                " state, expected_hash, byte_size, summary, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)",
                (
                    intake_id,
                    case_id,
                    kind.value,
                    artifact_id,
                    revision,
                    target_runner_id,
                    expected_hash,
                    byte_size,
                    short,
                    now,
                ),
            )
        return self.get_intake(intake_id)

    def get_intake(self, intake_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM intake WHERE id = ?", (intake_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"intake not found: {intake_id}")
        return dict(row)

    def list_pending_intakes(self, runner_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM intake WHERE state = 'pending' AND target_runner_id = ?"
            " ORDER BY created_at",
            (runner_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_intake_stored(self, intake_id: str, runner_id: str, content_hash: str) -> dict[str, Any]:
        intake = self.get_intake(intake_id)
        if intake["target_runner_id"] != runner_id:
            raise ConflictError("intake belongs to another runner")
        if intake["state"] == "stored":
            return intake  # 멱등: 같은 보고를 다시 받아도 상태를 바꾸지 않는다
        if intake["state"] != "pending":
            raise ConflictError(f"intake is {intake['state']}")
        if intake["expected_hash"] != content_hash:
            raise ConflictError("stored content hash does not match the relayed content")
        now = utc_now()
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE intake SET state = 'stored', stored_at = ? WHERE id = ?", (now, intake_id)
            )
            self.conn.execute(
                "UPDATE artifact_ref SET availability = ? WHERE artifact_id = ? AND revision = ?",
                (Availability.AVAILABLE.value, intake["artifact_id"], intake["revision"]),
            )
        return self.get_intake(intake_id)

    def mark_intake_lost(self, intake_id: str) -> dict[str, Any]:
        """중계 중이던 본문이 영속 저장 전에 사라진 경우.

        제어부 재시작이 대표 사례다. 빈 문서나 삭제로 표시하지 않고 상태로 드러낸다.
        """
        intake = self.get_intake(intake_id)
        if intake["state"] != "pending":
            return intake
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE intake SET state = 'lost_before_persist' WHERE id = ?", (intake_id,)
            )
            self.conn.execute(
                "UPDATE artifact_ref SET availability = ? WHERE artifact_id = ? AND revision = ?",
                (Availability.LOST_BEFORE_PERSIST.value, intake["artifact_id"], intake["revision"]),
            )
        return self.get_intake(intake_id)

    # --------------------------------------------------------- intent/decision

    def create_intent_version(
        self,
        case_id: str,
        artifact_id: str,
        artifact_rev: int,
        authoring_mode: AuthoringMode = AuthoringMode.HUMAN_TYPED,
        author_run_id: str | None = None,
    ) -> dict[str, Any]:
        """의도 버전을 만든다.

        `authoring_mode` 는 **실제로 누가 썼는가**다. 사람이 화면에서 입력한 초안과
        AI가 작성한 초안은 같은 형식·같은 표를 쓰지만 작성 주체는 다르고, 그 차이를
        지우지 않는다(FR-04). AI가 썼으면 그 실행(`author_run_id`)도 함께 남겨
        검토 세션이 작성 세션과 달랐는지 확인할 수 있게 한다(FR-29).
        """
        self.get_case(case_id)
        self.guard_open_case(case_id)
        ref = self.get_artifact_ref(artifact_id, artifact_rev)
        if ref["kind"] != ArtifactKind.INTENT.value:
            raise ConflictError("artifact is not an intent artifact")
        row = self.conn.execute(
            "SELECT MAX(revision) AS r FROM intent_version WHERE case_id = ?", (case_id,)
        ).fetchone()
        revision = (row["r"] or 0) + 1
        intent_id = ids.new_id("intent")
        now = utc_now()
        with transaction(self.conn):
            # 새 행을 먼저 넣는다. 이전 버전의 superseded_by 가 이 행을 가리키기 때문이다.
            self.conn.execute(
                "INSERT INTO intent_version (id, case_id, revision, artifact_id, artifact_rev,"
                " status, created_at, authoring_mode, author_run_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    intent_id,
                    case_id,
                    revision,
                    artifact_id,
                    artifact_rev,
                    IntentStatus.DRAFT.value,
                    now,
                    authoring_mode.value,
                    author_run_id,
                ),
            )
            if revision > 1:
                # 이전 버전은 대체됨으로 바꾼다. 그 버전에 붙은 동의 기록은 지우지 않는다.
                self.conn.execute(
                    "UPDATE intent_version SET status = ?, superseded_by = ?"
                    " WHERE case_id = ? AND id != ? AND status != ?",
                    (
                        IntentStatus.SUPERSEDED.value,
                        intent_id,
                        case_id,
                        intent_id,
                        IntentStatus.SUPERSEDED.value,
                    ),
                )
                # 이전 버전의 게이트 판정을 새 버전으로 승계하지 않는다.
                # 대상이 바뀌었으므로 **재검토 필요**다(quality-gates 3절).
                self.conn.execute(
                    "UPDATE gate_result SET verdict = ?, superseded_at = ?"
                    " WHERE case_id = ? AND intent_version_id != ? AND superseded_at IS NULL",
                    (GateVerdict.NEEDS_RECHECK.value, now, case_id, intent_id),
                )
                # 성공 기준도 같은 규칙이다. 이전 버전의 기준과 그 결과를 새 버전이
                # 승계하지 않는다 — 승계하면 바뀐 의도에 옛 기준과 옛 판정이 그대로
                # 붙는다(intent-artifacts 3절 "의도가 바뀌면 연결된 성공 기준을
                # 재검토한다"). 기준 자체는 지우지 않고 대체됨으로 남긴다.
                self.conn.execute(
                    "UPDATE success_criterion SET state = ?"
                    " WHERE case_id = ? AND intent_version_id != ? AND state != ?",
                    (
                        CriterionState.SUPERSEDED.value,
                        case_id,
                        intent_id,
                        CriterionState.SUPERSEDED.value,
                    ),
                )
                # **판정의 재검토 표시는 여기서 하지 않는다**(P3-R4).
                #
                # R4 이전에는 새 버전이 생기는 순간 이전 판정을 전부
                # `needs_recheck` 로 내렸다. 그 규칙은 "의도가 바뀌면 연결된 성공
                # 기준을 재검토한다"를 지키지만, **한 항목을 고친 피드백 하나가 모든
                # 검증을 무효로 만든다.** intent-artifacts 69행은 그 뒤에 "영향이
                # 없는 기록은 유지한다"를 함께 요구한다.
                #
                # 무엇이 영향을 받았는지는 **새 버전의 구조가 보고돼야** 알 수 있다.
                # 그래서 판단을 `_carry_unaffected_results` 로 옮겼다 — 이어지는
                # 판정은 그대로 남고, 이어지지 않는 판정이 그때 `needs_recheck` 가
                # 된다. 구조가 끝내 보고되지 않으면 이전 판정이 그대로 남지만, 그
                # 기준들은 이미 `superseded` 라 현재 판정에 쓰이지 않는다
                # (`current_criteria` 와 `record_criterion_result` 가 막는다).
                # 작업 수준 판단도 같은 규칙이다(P3-01). 축별 근거는 **이 의도 버전을
                # 보고 쓴 것**이므로 의도가 바뀌면 그 판단도 대체된다. 승계하면
                # 바뀐 의도에 옛 근거가 그대로 붙고, 사람이 조정한 수준이 새 범위에
                # 조용히 확대된다. 행은 지우지 않고 대체됨으로 남긴다.
                self.conn.execute(
                    "UPDATE sizing_assessment SET state = ?, superseded_at = ?"
                    " WHERE case_id = ? AND state = ?"
                    "   AND (intent_version_id IS NULL OR intent_version_id != ?)",
                    (
                        SizingState.SUPERSEDED.value,
                        now,
                        case_id,
                        SizingState.CURRENT.value,
                        intent_id,
                    ),
                )
        return self.get_intent_version(intent_id)

    def get_intent_version(self, intent_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM intent_version WHERE id = ?", (intent_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"intent version not found: {intent_id}")
        return dict(row)

    def list_intent_versions(self, case_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM intent_version WHERE case_id = ? ORDER BY revision DESC", (case_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def record_decision(
        self,
        case_id: str,
        kind: DecisionKind,
        subject_type: str,
        subject_id: str,
        subject_revision: int,
        actor: str,
        evidence_ref: str | None = None,
    ) -> dict[str, Any]:
        """사람의 결정을 기록한다(의도 동의 **제외**).

        의도 동의는 `record_intent_agreement` 한 곳에서만 만들어진다. 여기서도 만들 수
        있으면 최신 버전·원문 확인·열람 기록 검사를 우회하는 두 번째 입구가 생긴다.

        이 결정이 실행을 열어 주는지의 검사(FR-29 진입 조건)는 P2-03에서 붙인다.
        지금 통과 처리를 넣어 두지 않는다.
        """
        self.get_case(case_id)
        decision_id = ids.new_decision_id()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO decision (id, case_id, kind, subject_type, subject_id,"
                " subject_revision, actor, decided_at, evidence_ref)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    decision_id,
                    case_id,
                    kind.value,
                    subject_type,
                    subject_id,
                    subject_revision,
                    actor,
                    utc_now(),
                    evidence_ref,
                ),
            )
        row = self.conn.execute("SELECT * FROM decision WHERE id = ?", (decision_id,)).fetchone()
        return dict(row)

    def list_decisions(self, case_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM decision WHERE case_id = ? ORDER BY decided_at DESC", (case_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------- run

    def create_run(
        self,
        run_id: str,
        case_id: str,
        task_id: str,
        role: RunRole,
        tool_id: str,
        mode: str,
        permission: Permission,
        instruction_artifact_id: str,
        instruction_artifact_rev: int,
        purpose: RunPurpose = RunPurpose.LIMITED_ANALYSIS,
        repository_id: str | None = None,
        context_refs: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Run을 만든다. 같은 `run_id` 의 재전송은 기존 Run을 그대로 돌려준다.

        반환값의 두 번째 항목이 True면 이번 호출이 실제로 만든 것이다.
        이것이 중복 실행 방지의 첫 번째 층이다(P1 이월 항목).

        **진입 조건 검사는 여기서 하지 않는다.** `admit_and_create_run()` 이 검사한
        뒤에 이 메서드를 부른다. 두 가지를 한 함수에 섞으면 "검사를 건너뛰는 생성
        경로"가 생기기 때문에 호출 순서를 그 한 곳으로 모은다.

        **P3-R3: 예산 검사와 예약만은 여기서 한다.** 진입 검사에도 같은 판정이
        있지만(그래야 거부 사유가 기록된다) 그것만으로는 마지막 한 칸을 두 요청이
        함께 통과한다. 검사·Run 생성·예약이 **한 트랜잭션**이어야 하고, 그 트랜잭션은
        여기에 있다. 넘으면 `BudgetExhausted` 를 던진다.

        고정 컨텍스트 참조도 같은 트랜잭션에서 넣는다. 예약한 `context_bytes` 가
        실제로 들어간 참조와 어긋나지 않게 하기 위해서다.
        """
        existing = self.conn.execute("SELECT * FROM run WHERE run_id = ?", (run_id,)).fetchone()
        if existing is not None:
            return dict(existing), False

        self.get_case(case_id)
        ref = self.get_artifact_ref(instruction_artifact_id, instruction_artifact_rev)
        if ref["availability"] != Availability.AVAILABLE.value:
            # 지시 원문을 Runner가 읽을 수 없는 상태면 배정하지 않는다.
            raise ConflictError(
                f"instruction artifact is {ref['availability']}, not available for execution"
            )
        now = utc_now()
        refs = list(context_refs or [])
        want = planned_reservation(
            role,
            context_package_bytes(
                self.conn,
                instruction_artifact_id,
                instruction_artifact_rev,
                [(r["artifact_id"], r["revision"]) for r in refs],
            ),
        )
        try:
            with transaction(self.conn):
                # **BEGIN IMMEDIATE 안이다.** 읽고 → 판단하고 → 넣는 사이에 다른
                # 연결이 끼어들 수 없다. 이 검사를 트랜잭션 밖으로 옮기면 동시
                # 요청 둘이 같은 잔여량을 보고 함께 통과한다(D-61).
                breaches = self._budget_breaches(case_id, want, now)
                if breaches:
                    raise BudgetExhausted(breaches)
                self.conn.execute(
                    "INSERT INTO run (run_id, case_id, task_id, role, tool_id, mode, permission,"
                    " instruction_artifact_id, instruction_artifact_rev, status,"
                    " assignment_generation, created_at, purpose, repository_id,"
                    " is_experiment)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        case_id,
                        task_id,
                        role.value,
                        tool_id,
                        mode,
                        permission.value,
                        instruction_artifact_id,
                        instruction_artifact_rev,
                        RunStatus.PENDING.value,
                        1,
                        now,
                        purpose.value,
                        # **어느 저장소의 작업공간에서 도는가.** NULL 은 "주 저장소"가
                        # 아니라 기록되지 않음이다(P3-R2).
                        repository_id,
                        # **허용된 로컬 실험인가**(P3-R4·D-66). 목적에서 도출하며
                        # 요청이 스스로 주장하지 못한다 — 실험 표시는 결과 후보에서
                        # 제품 변경과 구별되는 근거이고, 요청이 그 구별을 정하면
                        # 임시 변경을 실험으로 적어 검증을 건너뛸 수 있다.
                        1 if purpose is RunPurpose.LOCAL_EXPERIMENT else 0,
                    ),
                )
                self._insert_context_refs(run_id, refs)
                self._reserve_budget(
                    case_id, run_id, 1, role, purpose, want, now
                )
        except sqlite3.IntegrityError:
            # 동시에 같은 run_id 가 들어온 경우에도 새 실행을 만들지 않는다.
            row = self.conn.execute("SELECT * FROM run WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                raise
            return dict(row), False
        return self.get_run(run_id), True

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM run WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"run not found: {run_id}")
        run = dict(row)
        run["usage"] = json.loads(run.pop("usage_json"))
        effect = run.pop("workspace_effect_json")
        run["workspace_effect"] = json.loads(effect) if effect else None
        return run

    def list_runs(self, case_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT run_id FROM run WHERE case_id = ? ORDER BY created_at DESC", (case_id,)
        ).fetchall()
        runs = []
        for row in rows:
            run = self.get_run(row["run_id"])
            # 무엇을 실제로 실행했는가(P3-03). 화면이 실행 목록에서 바로 보려면
            # 여기 있어야 한다 — 실행마다 따로 조회하게 하지 않는다(FR-14).
            run["commands"] = self.list_run_commands(row["run_id"])
            runs.append(run)
        return runs

    def claim_assignments(self, runner_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """대기 중인 Run을 이 Runner에 배정한다.

        배정은 세대(`assignment_generation`)와 함께 내려간다. Runner는 보고할 때
        같은 세대를 제시해야 하며 오래된 세대의 보고는 거부된다(NFR-03).
        """
        self.get_runner(runner_id)
        claimed: list[dict[str, Any]] = []
        # **쓰기 자리는 기본 1개다**(FR-26 "동일 Runner 쓰기 실행은 기본 1개").
        # 자리가 없으면 그 실행을 **거부하지 않고 `pending` 으로 남긴다** — 앞의
        # 쓰기가 끝나면 그대로 배정된다. 거부로 만들면 사람이 고칠 조건이 없는
        # 사유를 보게 된다(`ClaimDeferral`).
        write_slots = RUNNER_WRITE_LIMIT - len(self.unfinished_write_runs(runner_id=runner_id))
        with transaction(self.conn):
            rows = self.conn.execute(
                "SELECT run_id, permission FROM run WHERE status = ? ORDER BY created_at LIMIT ?",
                (RunStatus.PENDING.value, limit),
            ).fetchall()
            for row in rows:
                if row["permission"] in WRITE_PERMISSIONS:
                    if write_slots <= 0:
                        continue
                    write_slots -= 1
                self.conn.execute(
                    "UPDATE run SET status = ?, assigned_runner_id = ?, assigned_at = ?"
                    " WHERE run_id = ? AND status = ?",
                    (
                        RunStatus.ASSIGNED.value,
                        runner_id,
                        utc_now(),
                        row["run_id"],
                        RunStatus.PENDING.value,
                    ),
                )
                claimed.append(row["run_id"])
        return [self.assignment_payload(rid) for rid in claimed]

    def assignment_payload(self, run_id: str) -> dict[str, Any]:
        """Runner가 실행에 필요한 것만 담은 배정 내용.

        **본문은 들어가지 않는다.** 지시 원문은 참조로만 주고 Runner가 자기 저장소에서
        읽는다. `repo_path` 는 Runner 호스트에서 해석할 작업공간이고, `purpose` 는
        Runner가 어떤 지시문으로 CLI를 부를지 정하는 데 쓴다(프롬프트 조립은 Runner가
        한다 — 목적별 지시문을 제어부에 두면 본문이 제어부에 남는다).
        """
        run = self.get_run(run_id)
        case = self.get_case(run["case_id"])
        project = self.get_project(case["project_id"])
        # **Case × Repository 작업공간이 준비돼 있으면 그 안에서 실행한다**
        # (D-39·FR-08). 읽기 전용 실행도 같은 worktree 를 쓴다 — 그래야 검토·조사가
        # 이 Case 가 실제로 만들고 있는 코드를 본다.
        #
        # 어느 저장소인지는 `run.repository_id` 가 말한다. 기록되지 않은 실행
        # (P3-R2 이전)은 작업공간이 하나뿐일 때만 그것으로 해석하고, 둘 이상이면
        # 진입 검사가 이미 `workspace_target_not_recorded` 로 막았다.
        workspace = self.get_workspace(run["case_id"], run.get("repository_id"))
        if workspace is not None and workspace["state"] == WorkspaceState.READY.value:
            run["repo_path"] = workspace["repo_path"] or project["repo_path"]
            run["workspace"] = {
                "repository_id": workspace["repository_id"],
                "branch": workspace["branch"],
                "worktree_path": workspace["worktree_path"],
                "repo_path": workspace["repo_path"],
                "base_commit": workspace["base_commit"],
            }
            run["workspace_path"] = workspace["worktree_path"]
        else:
            # 준비된 작업공간이 없다. 저장소 경로는 **정본인 `project_repository`**
            # 에서 찾고, 찾지 못하면 v1의 `project.repo_path` 로 떨어진다(P3-R2).
            # 이 상태에서는 진입 검사가 쓰기를 이미 막았다.
            repo_path = project["repo_path"]
            if run.get("repository_id"):
                try:
                    repo_path = self.get_project_repository(run["repository_id"])["repo_path"]
                except NotFoundError:
                    pass
            run["repo_path"] = repo_path
            run["workspace"] = None
            run["workspace_path"] = repo_path
        run["case_title"] = case["title"]
        run["case_kind"] = case["kind"]
        # **P3-R1: Profile 과 그 정의판을 함께 준다.** Runner 가 초안 항목을 그
        # Profile 로 만든다. `None` 이면 R1 이전 Case 이고 공통 여섯 항목이다 —
        # Runner 가 현재 정의로 채우지 않는다(D-62).
        run["case_profile"] = case.get("profile")
        run["case_profile_version"] = case.get("profile_version")
        # 의미 검토의 대상 의도 버전은 지시 원문에서 끌어낸다. 별도 컬럼을 두면
        # 지시와 대상이 어긋날 수 있다.
        target = self.intent_version_for_artifact(
            run["instruction_artifact_id"], run["instruction_artifact_rev"]
        )
        run["target_intent_version_id"] = target["id"] if target else None
        # 고정 컨텍스트 참조. **본문은 없다** — Runner가 이 참조로 자기 저장소에서
        # 읽는다. 읽지 못한 참조는 지시문에 "읽지 못함"으로 적힌다(P3-01).
        run["context_refs"] = self.list_context_refs(run_id)
        # 준비 산출물을 만드는 실행은 어느 수준으로 쓸지 알아야 한다. 수준이 없으면
        # `None` 이고 그 경우 진입 검사가 이미 막았다 — 여기서 기본값을 지어내지 않는다.
        level = self.current_level(run["case_id"])
        run["work_level"] = level.value if level else None
        # **어느 단계의 산출물을 쓸 것인가**(P3-R4). Fast Lane 의 계획 작성 실행은
        # 설계·계획 두 건 대신 **결합 기록 한 건**을 쓴다(D-60).
        #
        # 이 판단을 Runner 에 두지 않는 이유는 그것이 진입 조건과 같은 판단이기
        # 때문이다. 두 곳에서 각각 계산하면 "Runner 는 결합 기록을 썼는데 진입
        # 검사는 계획을 요구하는" 상태가 조용히 생긴다(R2 가 실제로 한 실수다).
        run["preparation_stage"] = self._authoring_stage(
            run["case_id"], run.get("purpose")
        )
        latest_intent = self.latest_intent_version(run["case_id"])
        run["current_intent_version_id"] = latest_intent["id"] if latest_intent else None
        # **이 Case 가 코드를 바꿔도 되는 저장소들**(P3-04). 계획이 Task 마다 저장소를
        # 말해야 하는데(v12) 계획을 쓰는 실행이 그 목록을 모르면 이름을 지어내게
        # 되고, 지어낸 이름은 해석되지 않아 그 Task 가 막힌다. 실제로 라이브에서
        # 그렇게 됐다 — 등록 이름("primary")과 사람이 부르는 이름("repo-core")이
        # 달랐고 계획은 후자를 적었다.
        #
        # **이름과 식별자뿐이다.** 경로도 본문도 들어가지 않는다 — 한 실행은
        # 자기 작업공간 하나만 보며(D-39) 이 목록이 다른 저장소를 열어 주지 않는다.
        run["case_repositories"] = [
            {"repository_id": r["id"], "name": r["name"]}
            for r in self.code_repository_choices(run["case_id"])
        ]
        return run

    def code_repository_choices(self, case_id: str) -> list[dict[str, Any]]:
        """계획이 Task 의 저장소로 고를 수 있는 것들. 이름 순이 아니라 선택 순이다."""
        ids_ = self._code_repository_ids(case_id)
        if not ids_:
            return []
        rows = self.conn.execute(
            "SELECT id, name FROM project_repository WHERE id IN"
            f" ({','.join('?' * len(ids_))}) ORDER BY registered_at",
            tuple(sorted(ids_)),
        ).fetchall()
        return [dict(r) for r in rows]

    def _authoring_stage(self, case_id: str, purpose: str | None) -> str | None:
        """이 작성 실행이 만들 준비 산출물의 단계.

        `design_authoring` 은 언제나 설계다. `plan_authoring` 은 **Fast Lane 이고
        아직 설계가 없을 때만** 결합 기록이 된다 — 설계가 이미 있으면 그 위의 계획을
        쓰는 것이 맞고, 결합 기록으로 바꾸면 있는 설계가 버려진다.
        """
        if purpose == RunPurpose.DESIGN_AUTHORING.value:
            return PreparationStage.DESIGN.value
        if purpose != RunPurpose.PLAN_AUTHORING.value:
            return None
        if self.current_preparation(case_id, PreparationStage.DESIGN) is not None:
            return PreparationStage.PLAN.value
        if self.fast_lane_state(case_id)["eligible"]:
            return PreparationStage.COMBINED.value
        return PreparationStage.PLAN.value

    def bump_generation(self, run_id: str) -> dict[str, Any]:
        """재배정. 세대를 올리고 다시 대기 상태로 돌린다.

        **이것은 "이전 실행자가 멈췄다"는 증거가 아니다.** 세대는 오래된 실행자의 보고가
        최신 상태를 덮어쓰지 못하게 막을 뿐이다. 실제 정지 확인은 별도 문제다
        (NFR-01: "단절만으로 다른 Runner에 동일 쓰기를 재배정하지 않는다").
        """
        run = self.get_run(run_id)
        if run["status"] == RunStatus.FINISHED.value:
            raise ConflictError("run already finished")
        now = utc_now()
        # **재배정은 새 소비다.** 다시 배정하면 CLI 가 다시 불리고 그것은 새 호출이다
        # (autonomy-budget-policy 7절 "재시작된 실제 AI 호출은 새 소비"). 같은
        # `run_id` 라는 이유로 두 번째 호출을 공짜로 두면 한도가 재배정 횟수만큼
        # 늘어난다. 예산이 없으면 재배정하지 않는다.
        refs = [
            (r["artifact_id"], r["revision"]) for r in self.list_context_refs(run_id)
        ]
        want = planned_reservation(
            RunRole(run["role"]),
            context_package_bytes(
                self.conn,
                run["instruction_artifact_id"],
                run["instruction_artifact_rev"],
                refs,
            ),
        )
        with transaction(self.conn):
            breaches = self._budget_breaches(run["case_id"], want, now)
            if breaches:
                raise BudgetExhausted(breaches)
            self.conn.execute(
                "UPDATE run SET assignment_generation = assignment_generation + 1,"
                " status = ?, assigned_runner_id = NULL, assigned_at = NULL WHERE run_id = ?",
                (RunStatus.PENDING.value, run_id),
            )
            self._reserve_budget(
                run["case_id"],
                run_id,
                run["assignment_generation"] + 1,
                RunRole(run["role"]),
                RunPurpose(run["purpose"]) if run.get("purpose") else RunPurpose.LIMITED_ANALYSIS,
                want,
                now,
            )
        return self.get_run(run_id)

    def _check_generation(self, run_id: str, generation: int) -> dict[str, Any]:
        run = self.get_run(run_id)
        if generation != run["assignment_generation"]:
            raise ConflictError(
                f"stale assignment generation {generation};"
                f" current is {run['assignment_generation']}"
            )
        return run

    def append_events(
        self, run_id: str, generation: int, events: Iterable[dict[str, Any]]
    ) -> dict[str, int]:
        """정규화 이벤트를 기록한다. 같은 `(run_id, seq)` 재전송은 새 행을 만들지 않는다."""
        self._check_generation(run_id, generation)
        stored = 0
        duplicate = 0
        now = utc_now()
        with transaction(self.conn):
            for event in events:
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO run_event"
                    " (run_id, seq, ts, type, native_type, raw_ref, received_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        int(event["seq"]),
                        event["ts"],
                        event["type"],
                        event.get("native_type"),
                        event.get("raw_ref"),
                        now,
                    ),
                )
                if cur.rowcount == 1:
                    stored += 1
                else:
                    duplicate += 1
            self.conn.execute(
                "UPDATE run SET status = ? WHERE run_id = ? AND status = ?",
                (RunStatus.RUNNING.value, run_id, RunStatus.ASSIGNED.value),
            )
        return {"stored": stored, "duplicate": duplicate}

    def list_events(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM run_event WHERE run_id = ? ORDER BY seq", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def report_result(
        self,
        run_id: str,
        generation: int,
        outcome: RunOutcome,
        exit_code: int | None = None,
        output_artifact_id: str | None = None,
        output_artifact_rev: int | None = None,
        session_ref: str | None = None,
        usage: Any = "not_reported",
        workspace_effect: dict[str, Any] | None = None,
        residual_activity: str = "unknown",
        observed_tool_version: str | None = None,
    ) -> dict[str, Any]:
        """실행 결과를 기록한다.

        같은 세대의 같은 결과를 다시 받아도 상태를 바꾸지 않는다(멱등).
        오래된 세대의 보고는 거부한다.
        """
        run = self._check_generation(run_id, generation)
        if run["status"] == RunStatus.FINISHED.value:
            if run["outcome"] == outcome.value:
                # **중복 청구가 생기지 않는 자리가 여기다.** 정산은 이 가드 뒤에
                # 있으므로 같은 결과를 다시 보내도 예약이 두 번 정산되지 않는다.
                return run  # 같은 결과의 재전송. 덮어쓰지 않는다
            raise ConflictError(
                f"run already finished with outcome {run['outcome']}; refusing to overwrite"
            )
        finished_at = utc_now()
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE run SET status = ?, outcome = ?, exit_code = ?, output_artifact_id = ?,"
                " output_artifact_rev = ?, session_ref = ?, usage_json = ?,"
                " workspace_effect_json = ?, residual_activity = ?, observed_tool_version = ?,"
                " finished_at = ? WHERE run_id = ?",
                (
                    RunStatus.FINISHED.value,
                    outcome.value,
                    exit_code,
                    output_artifact_id,
                    output_artifact_rev,
                    session_ref,
                    json.dumps(usage),
                    json.dumps(workspace_effect) if workspace_effect else None,
                    residual_activity,
                    observed_tool_version,
                    finished_at,
                    run_id,
                ),
            )
            # **같은 트랜잭션에서 정산한다.** 결과는 기록됐는데 예약이 잡힌 채로
            # 남으면 그 Case 는 영원히 소진 상태가 된다.
            self._settle_budget(
                {
                    **run,
                    "outcome": outcome.value,
                    "residual_activity": residual_activity,
                    "finished_at": finished_at,
                },
                usage,
                finished_at,
            )
        # **실행이 끝나는 것도 마지막 조건일 수 있다**(P3-R4). 미정리 실행이 남아
        # 있으면 자동 완료가 보류되므로(completion-lifecycle 5절), 그 실행이 끝난
        # 순간이 조건이 갖춰지는 시점이다. 조건을 못 갖추면 아무 것도 하지 않는다.
        self.maybe_auto_complete(run["case_id"])
        return self.get_run(run_id)

    # ------------------------------------------------------------ request log

    def cached_response(self, request_key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM request_log WHERE request_key = ?", (request_key,)
        ).fetchone()
        if row is None:
            return None
        return {"status_code": row["status_code"], "body": json.loads(row["response_json"])}

    def store_response(
        self, request_key: str, endpoint: str, status_code: int, body: Any
    ) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "INSERT OR IGNORE INTO request_log"
                " (request_key, endpoint, response_json, status_code, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (request_key, endpoint, json.dumps(body), status_code, utc_now()),
            )

    # =================================================================== P2-02
    #
    # 아래 접근자에는 본문을 받는 인자가 없다. 의도 여섯 항목의 본문, 피드백 원문,
    # 질문의 대상·근거·선택·영향, 열람으로 오간 원문은 전부 Runner에 있고
    # 여기에는 상태·참조·짧은 요약만 들어온다.

    # ------------------------------------------------------- 의도 구조·질문

    def apply_intent_structure(
        self,
        intent_version_id: str,
        fields: Iterable[dict[str, Any]],
        questions: Iterable[dict[str, Any]],
        criteria: Iterable[dict[str, Any]] | None = None,
        sizing: dict[str, Any] | None = None,
        objectives: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """Runner가 계산한 의도 구조를 반영한다.

        필수 항목이 모두 와야 한다. 하나라도 빠지면 거부한다 —
        "정보가 없으면 항목을 삭제한다"가 아니라 `undecided` 로 남기는 것이 규칙이다.

        **P3-R1: 필수 항목은 Case 의 Profile 이 정한다.** 공통 여섯 항목 위에 그
        목적의 의미 항목이 붙는다(D-62). Profile 이 기록되지 않은 Case(R1 이전)는
        여섯 항목 그대로다 — 지금의 의미 항목을 요구하면 그 Case 의 기존 의도 버전이
        갑자기 불완전한 문서가 된다.
        """
        intent = self.get_intent_version(intent_version_id)
        rows = list(fields)
        given = {row["field"] for row in rows}
        required = set(self.required_intent_fields(intent["case_id"]))
        if given != required:
            missing = sorted(required - given)
            extra = sorted(given - required)
            raise ConflictError(
                "intent structure must carry exactly the required fields;"
                f" missing={missing} extra={extra}"
            )
        # **P4-03: 요청이 명시한 목적 의무.** 완료 계약이 있는 Case 만 받는다 — 계약이
        # 없는 Case 에 목적을 기록하면 그 Case 의 완료 판정에 없던 조건이 생긴다.
        # `None` 은 "선언 없음"이며 빈 목록(`[]`, "대표 목적 외에 없음")과 다르다.
        objectives_json: str | None = None
        if objectives is not None:
            if self.completion_contract(intent["case_id"]) is None:
                raise ConflictError(
                    "objectives need a profile with a completion contract (definition v2);"
                    " this case follows definition v1"
                )
            declared: list[str] = []
            for raw in objectives:
                try:
                    value = CriterionObligation(str(raw)).value
                except ValueError as exc:
                    raise ConflictError(f"unknown objective: {raw}") from exc
                if value not in declared:
                    declared.append(value)
            objectives_json = json.dumps(declared)

        now = utc_now()
        with transaction(self.conn):
            if objectives_json is not None:
                self.conn.execute(
                    "UPDATE intent_version SET objectives_json = ? WHERE id = ?",
                    (objectives_json, intent_version_id),
                )
            for row in rows:
                self.conn.execute(
                    "INSERT INTO intent_field"
                    " (intent_version_id, field, state, origin, change_from_prev)"
                    " VALUES (?, ?, ?, ?, ?)"
                    " ON CONFLICT(intent_version_id, field) DO UPDATE SET"
                    "   state = excluded.state, origin = excluded.origin,"
                    "   change_from_prev = excluded.change_from_prev",
                    (
                        intent_version_id,
                        _field_name(row["field"]),
                        ConfirmationState(row["state"]).value,
                        ContentOrigin(row["origin"]).value,
                        FieldChange(row["change_from_prev"]).value,
                    ),
                )
            for question in questions:
                self.conn.execute(
                    "INSERT INTO intent_question"
                    " (id, case_id, intent_version_id, question_key, summary, decide_at,"
                    "  state, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(intent_version_id, question_key) DO UPDATE SET"
                    "   summary = excluded.summary, decide_at = excluded.decide_at",
                    (
                        ids.new_question_id(),
                        intent["case_id"],
                        intent_version_id,
                        str(question["key"]),
                        _summary(question["summary"]),
                        DecideAt(question["decide_at"]).value,
                        QuestionState.OPEN.value,
                        now,
                    ),
                )
        # 성공 기준도 같은 보고로 들어온다. 기준을 따로 입력받는 본문 API 를 만들면
        # 제어부가 기준 본문을 갖게 되므로 경계가 뚫린다(data-boundary-review 1절).
        # 기준이 0건이면 0건으로 남긴다 — 없는 기준을 시스템이 채우지 않는다.
        if criteria is not None:
            self.apply_success_criteria(intent_version_id, criteria)
        # **영향받지 않은 판정은 유지한다**(P3-R4·intent-artifacts 69행).
        #
        # `apply_success_criteria` 안이 아니라 여기서 부르는 이유는, 기준을 하나도
        # 보고하지 않은 버전에서도 이전 판정의 재검토 표시가 필요하기 때문이다.
        # 저쪽에 두면 `criteria is None` 인 보고에서 옛 판정이 그대로 남는다.
        self._carry_unaffected_results(intent_version_id)
        # 작업 수준 판단도 같은 보고로 들어온다(P3-01). 같은 이유다 — 축별 근거를
        # 따로 입력받는 본문 API 를 만들면 제어부가 그 서술을 갖게 된다.
        # `None` 이면 아무 것도 만들지 않는다. **수준 미결정은 미결정으로 남는다.**
        self.apply_sizing_report(intent_version_id, sizing)
        # 구조가 보고된 순간이 규칙 검사가 가능해진 순간이다. 여기서 한 번 돌려
        # 게이트 상태를 항상 최신 구조에 맞춰 둔다. **AI 검토는 건드리지 않는다** —
        # 규칙만 통과한 상태는 여전히 `not_run` 이다.
        self.evaluate_gate_rules(intent_version_id)
        # **마지막 유효 위임과 대조한다**(P3-R4·D-60). 구조가 보고된 지금이 비교할
        # 수 있는 첫 순간이다 — 버전을 만드는 시점에는 항목도 기준도 아직 없다.
        self.detect_material_deltas(intent_version_id)
        return self.get_intent_detail(intent_version_id)

    def detect_material_deltas(self, intent_version_id: str) -> list[dict[str, Any]]:
        """이 버전이 **마지막으로 동의된 의도**와 무엇이 달라졌는지 기록한다(D-60).

        **비교 대상이 AI 의 직전 초안이 아니다.** 초안끼리 비교하면 작은 변경을
        연속 채택해 원래 요청과 다른 결과로 이동할 수 있다(autonomy-budget-policy
        3절). 그래서 기준은 **동의된 버전**이고, 확인되지 않은 변경은 그 다음 동의가
        생길 때까지 `pending` 으로 **쌓인다.**

        동의된 버전이 없으면 아무 것도 기록하지 않는다. 아직 위임 자체가 없으므로
        "위임과 달라졌다"를 말할 수 없다 — 그 상태는 초안 작업이다.

        제어부는 본문을 읽지 않으므로 **구조화된 사실만으로** 판단한다.

            항목      Runner 가 보고한 `change_from_prev` 와 `origin`
            기준      기준 키의 추가·삭제와 요약 해시의 변화
            사용자 지시  이 버전이 반영한 피드백이 있는가

        마지막 줄이 정상 흐름을 여는 경로다. 사용자의 답변·수정 요청에서 온 변경은
        **위임 기준을 갱신**하고 막지 않는다(D-60 "실제 답한 항목과 명시한 범위의
        위임 기준만 갱신").
        """
        intent = self.get_intent_version(intent_version_id)
        case_id = intent["case_id"]
        baseline = self._last_agreed_intent_version(case_id, before=intent["revision"])
        if baseline is None:
            return []

        # 이 버전이 사용자의 피드백을 반영했는가. 반영한 항목이 무엇인지는 원문에
        # 있고 제어부는 **그런 지시가 있었다는 사실**만 안다.
        reflected = self.conn.execute(
            "SELECT COUNT(*) AS n FROM feedback WHERE reflected_in_version_id = ?",
            (intent_version_id,),
        ).fetchone()["n"]
        user_directed = bool(reflected)

        baseline_fields = {
            f["field"]: f for f in self.list_intent_fields(baseline["id"])
        }
        detected: list[str] = []
        with transaction(self.conn):
            for field in self.list_intent_fields(intent_version_id):
                if field["change_from_prev"] != FieldChange.CHANGED.value:
                    continue
                before = baseline_fields.get(field["field"])
                # 동의된 버전에 없던 항목은 그 버전의 위임 대상이 아니다.
                agreed_item = before is not None and before["state"] in (
                    ConfirmationState.USER_CONFIRMED.value,
                    ConfirmationState.PROPOSED.value,
                )
                self._record_delta(
                    case_id,
                    change_class=DeltaChangeClass.INTENT_FIELD,
                    target_type="intent_field",
                    target_id=None,
                    target_key=field["field"],
                    from_hash=baseline["id"],
                    to_hash=intent_version_id,
                    origin=field["origin"],
                    target_agreed=agreed_item,
                    user_directed=user_directed
                    and field["origin"]
                    in (
                        ContentOrigin.USER_REQUIREMENT.value,
                        ContentOrigin.PROJECT_RULE.value,
                    ),
                )
                detected.append(field["field"])

            base_criteria = {
                c["criterion_key"]: c
                for c in self.conn.execute(
                    "SELECT * FROM success_criterion WHERE intent_version_id = ?",
                    (baseline["id"],),
                ).fetchall()
            }
            now_criteria = {
                c["criterion_key"]: c
                for c in self.conn.execute(
                    "SELECT * FROM success_criterion WHERE intent_version_id = ?",
                    (intent_version_id,),
                ).fetchall()
            }
            for key, before in base_criteria.items():
                after = now_criteria.get(key)
                if after is not None and _criterion_fingerprint(
                    after
                ) == _criterion_fingerprint(before):
                    continue
                # **삭제와 변경을 같은 사유로 본다.** 기준이 사라진 것과 내용이
                # 바뀐 것은 둘 다 "합의한 기준이 그대로가 아니다"이며, 완료 판정을
                # 쉽게 만드는 방향의 변경이 정확히 여기서 일어난다(D-60).
                self._record_delta(
                    case_id,
                    change_class=DeltaChangeClass.SUCCESS_CRITERION,
                    target_type="success_criterion",
                    target_id=(after or before)["id"],
                    target_key=key,
                    from_hash=_criterion_fingerprint(before),
                    to_hash=_criterion_fingerprint(after) if after else None,
                    # 기준에는 출처 컬럼이 없다. **없는 값을 지어내지 않는다** —
                    # `origin = None` 은 분류에서 보수적인 쪽(material)으로 읽힌다.
                    origin=None,
                    target_agreed=True,
                    user_directed=user_directed,
                )
                detected.append(key)
            for key, after in now_criteria.items():
                if key in base_criteria:
                    continue
                self._record_delta(
                    case_id,
                    change_class=DeltaChangeClass.SUCCESS_CRITERION,
                    target_type="success_criterion",
                    target_id=after["id"],
                    target_key=key,
                    from_hash=None,
                    to_hash=_criterion_fingerprint(after),
                    origin=None,
                    # 동의된 버전에 없던 기준이다. 범위 추가이므로 확인 대상이지만
                    # 사용자 지시에서 왔다면 위임 기준이 갱신된다.
                    target_agreed=True,
                    user_directed=user_directed,
                )
                detected.append(key)
        return self.list_material_deltas(case_id)

    def _last_agreed_intent_version(
        self, case_id: str, before: int
    ) -> dict[str, Any] | None:
        """이 버전 **이전에** 사람이 동의한 가장 최근 의도 버전.

        `before` 를 받는 이유는 자기 자신을 기준으로 삼지 않기 위해서다. 새 버전에
        동의가 붙는 것은 나중 일이고, 붙고 나면 그 버전이 다음 비교의 기준이 된다.
        """
        row = self.conn.execute(
            "SELECT iv.* FROM decision d"
            " JOIN intent_version iv ON iv.id = d.subject_id"
            " WHERE d.kind = ? AND d.subject_type = 'intent_version' AND d.case_id = ?"
            "   AND d.revoked_at IS NULL AND iv.revision < ?"
            " ORDER BY iv.revision DESC LIMIT 1",
            (DecisionKind.INTENT_AGREEMENT.value, case_id, before),
        ).fetchone()
        return _row_to_dict(row)

    def list_intent_fields(self, intent_version_id: str) -> list[dict[str, Any]]:
        """항목 목록. **Profile 이 정한 순서**로 돌려준다.

        순서를 고정하는 이유는 화면·문서·지시문이 같은 순서를 보여야 사람이 버전
        사이의 차이를 눈으로 볼 수 있기 때문이다. 목록에 없는 항목(옛 기록 등)은
        뒤로 보내고 지우지 않는다.
        """
        intent = self.get_intent_version(intent_version_id)
        case = self.get_case(intent["case_id"])
        order = {
            name: index
            for index, name in enumerate(
                profiles.field_order(case.get("profile"), case.get("profile_version"))
            )
        }
        rows = self.conn.execute(
            "SELECT * FROM intent_field WHERE intent_version_id = ?", (intent_version_id,)
        ).fetchall()
        return sorted((dict(r) for r in rows), key=lambda r: order.get(r["field"], 99))

    def list_questions(
        self, intent_version_id: str, state: QuestionState | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM intent_question WHERE intent_version_id = ?"
        args: list[Any] = [intent_version_id]
        if state is not None:
            sql += " AND state = ?"
            args.append(state.value)
        rows = self.conn.execute(sql + " ORDER BY created_at, question_key", args).fetchall()
        return [dict(r) for r in rows]

    def get_question(self, question_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM intent_question WHERE id = ?", (question_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"question not found: {question_id}")
        return dict(row)

    def answer_question(
        self, question_id: str, actor: str, answer_artifact_id: str | None
    ) -> dict[str, Any]:
        """질문에 답한다. **이것은 의도 동의가 아니다.**

        FR-03: "질문 답변·수정 요청·무응답·시간 경과·AI 평가를 전체 의도 동의로
        확대하지 않는다." 그래서 이 메서드는 decision 표를 건드리지 않는다.
        """
        question = self.get_question(question_id)
        self.guard_open_case(question["case_id"])
        if question["state"] != QuestionState.OPEN.value:
            raise ConflictError(f"question is {question['state']}")
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE intent_question SET state = ?, answered_by = ?, answered_at = ?,"
                " answer_artifact_id = ? WHERE id = ?",
                (
                    QuestionState.ANSWERED.value,
                    actor,
                    utc_now(),
                    answer_artifact_id,
                    question_id,
                ),
            )
        return self.get_question(question_id)

    def open_intent_stage_questions(self, intent_version_id: str) -> list[dict[str, Any]]:
        """의도 단계에서 결정해야 하는데 아직 열려 있는 질문.

        설계·계획으로 이월한 질문은 여기 들어오지 않는다. 이월한 질문이
        의도 동의를 막지는 않으며, 해당 단계의 작업 전에 해결한다(FR-03 질문 처리).
        """
        rows = self.conn.execute(
            "SELECT * FROM intent_question WHERE intent_version_id = ?"
            " AND state = ? AND decide_at = ? ORDER BY created_at",
            (intent_version_id, QuestionState.OPEN.value, DecideAt.INTENT.value),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_intent_detail(self, intent_version_id: str) -> dict[str, Any]:
        intent = self.get_intent_version(intent_version_id)
        ref = self.get_artifact_ref(intent["artifact_id"], intent["artifact_rev"])
        intent["fields"] = self.list_intent_fields(intent_version_id)
        intent["questions"] = self.list_questions(intent_version_id)
        # 성공 기준은 의도에서 분리되지 않게 같은 묶음으로 돌려준다
        # (intent-artifacts 1절). 화면이 기준을 다른 곳에서 찾게 하지 않는다.
        intent["criteria"] = self.list_success_criteria(intent_version_id)
        intent["content_hash"] = ref["content_hash"]
        intent["availability"] = ref["availability"]
        intent["summary"] = ref["summary"]
        # **P3-R1: 필수 항목 집합을 함께 실어 준다.** 게이트 규칙이 이 목록으로
        # 검사한다 — 규칙이 스스로 Profile 을 조회하면 제어부의 두 곳이 같은 판단을
        # 따로 하게 되고, 한쪽만 고치는 실수가 생긴다.
        case = self.get_case(intent["case_id"])
        intent["profile"] = case.get("profile")
        intent["profile_version"] = case.get("profile_version")
        intent["required_fields"] = list(
            profiles.field_order(case.get("profile"), case.get("profile_version"))
        )
        return intent

    def latest_intent_version(self, case_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM intent_version WHERE case_id = ? ORDER BY revision DESC LIMIT 1",
            (case_id,),
        ).fetchone()
        return self.get_intent_detail(row["id"]) if row else None

    # --------------------------------------------------------------- 피드백

    def record_feedback(
        self,
        case_id: str,
        target_intent_version_id: str,
        artifact_id: str,
        artifact_rev: int,
        author: str,
        summary: str,
    ) -> dict[str, Any]:
        """피드백을 접수한다. **이것은 의도 동의가 아니다.**

        피드백을 줬다는 사실이 초안 전체에 동의했다는 뜻이 되지 않게
        decision 표와 완전히 분리해 둔다(FR-03 수용 기준).
        """
        self.guard_open_case(case_id)
        intent = self.get_intent_version(target_intent_version_id)
        if intent["case_id"] != case_id:
            raise ConflictError("intent version belongs to another case")
        feedback_id = ids.new_feedback_id()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO feedback (id, case_id, target_intent_version_id,"
                " target_intent_revision, artifact_id, artifact_rev, author, summary,"
                " state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    feedback_id,
                    case_id,
                    target_intent_version_id,
                    intent["revision"],
                    artifact_id,
                    artifact_rev,
                    author,
                    _summary(summary),
                    FeedbackState.RECEIVED.value,
                    utc_now(),
                ),
            )
        return self.get_feedback(feedback_id)

    def get_feedback(self, feedback_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"feedback not found: {feedback_id}")
        return dict(row)

    def list_feedback(self, case_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM feedback WHERE case_id = ? ORDER BY created_at", (case_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def resolve_feedback(
        self,
        feedback_ids: Iterable[str],
        reflected_in_version_id: str | None,
        not_reflected: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """피드백의 처리 결과를 기록한다.

        미반영은 이유와 함께 남긴다. 반영하지 않은 피드백을 조용히 닫지 않는다
        (intent-artifacts 3절: "반영 내용과 상태, 남은 질문").
        """
        not_reflected = not_reflected or {}
        now = utc_now()
        touched: list[str] = []
        with transaction(self.conn):
            for feedback_id in feedback_ids:
                self.conn.execute(
                    "UPDATE feedback SET state = ?, reflected_in_version_id = ?, resolved_at = ?"
                    " WHERE id = ? AND state = ?",
                    (
                        FeedbackState.REFLECTED.value,
                        reflected_in_version_id,
                        now,
                        feedback_id,
                        FeedbackState.RECEIVED.value,
                    ),
                )
                touched.append(feedback_id)
            for feedback_id, reason in not_reflected.items():
                self.conn.execute(
                    "UPDATE feedback SET state = ?, disposition_note = ?, resolved_at = ?"
                    " WHERE id = ? AND state = ?",
                    (
                        FeedbackState.NOT_REFLECTED.value,
                        _summary(reason),
                        now,
                        feedback_id,
                        FeedbackState.RECEIVED.value,
                    ),
                )
                touched.append(feedback_id)
        return [self.get_feedback(fid) for fid in touched]

    # ----------------------------------------------------------- 열람·동의

    def record_intent_view(
        self, intent_version_id: str, actor: str, content_hash: str
    ) -> dict[str, Any]:
        """초안을 열람했다는 사실을 남긴다. **이것은 동의가 아니다.**

        별도 표에 두는 이유는 "요약만 읽은 상태를 상세 원문에 대한 확인으로
        기록하지 않는다"(intent-artifacts 5절)를 검사 가능하게 만들기 위해서다.

        **호출자가 직접 부르는 경로가 없다.** 이 기록은 원문이 실제로 전달된
        순간에만 생긴다(controller/api.py 의 열람 수령). 화면이나 호출자가
        "읽었다"고 주장해서 만들 수 있으면 동의의 선행 조건으로 쓸 수 없다.
        """
        intent = self.get_intent_version(intent_version_id)
        view_id = ids.new_view_id()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO intent_view (id, case_id, intent_version_id, actor,"
                " content_hash, viewed_at) VALUES (?, ?, ?, ?, ?, ?)",
                (view_id, intent["case_id"], intent_version_id, actor, content_hash, utc_now()),
            )
        row = self.conn.execute("SELECT * FROM intent_view WHERE id = ?", (view_id,)).fetchone()
        return dict(row)

    def list_intent_views(self, intent_version_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM intent_view WHERE intent_version_id = ? ORDER BY viewed_at",
            (intent_version_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def intent_version_for_artifact(
        self, artifact_id: str, revision: int
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM intent_version WHERE artifact_id = ? AND artifact_rev = ?",
            (artifact_id, revision),
        ).fetchone()
        return dict(row) if row else None

    def has_read_the_original(
        self, intent_version_id: str, actor: str, content_hash: str
    ) -> bool:
        """이 사람이 **이 원문 그대로**를 실제로 받아 본 적이 있는가."""
        row = self.conn.execute(
            "SELECT 1 FROM intent_view WHERE intent_version_id = ? AND actor = ?"
            " AND content_hash = ? LIMIT 1",
            (intent_version_id, actor, content_hash),
        ).fetchone()
        return row is not None

    def agreement_for(self, intent_version_id: str) -> dict[str, Any] | None:
        """이 의도 버전에 붙은, 취소되지 않은 동의 기록."""
        row = self.conn.execute(
            "SELECT * FROM decision WHERE kind = ? AND subject_type = 'intent_version'"
            " AND subject_id = ? AND revoked_at IS NULL ORDER BY decided_at DESC LIMIT 1",
            (DecisionKind.INTENT_AGREEMENT.value, intent_version_id),
        ).fetchone()
        return dict(row) if row else None

    def record_intent_agreement(
        self,
        case_id: str,
        intent_version_id: str,
        actor: str,
        content_hash: str,
        evidence_ref: str | None = None,
    ) -> dict[str, Any]:
        """명시 동의를 기록한다. 동의는 **그 버전 그 원문**에만 붙는다."""
        self.guard_open_case(case_id)
        intent = self.get_intent_version(intent_version_id)
        decision_id = ids.new_decision_id()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO decision (id, case_id, kind, subject_type, subject_id,"
                " subject_revision, actor, decided_at, evidence_ref, subject_content_hash)"
                " VALUES (?, ?, ?, 'intent_version', ?, ?, ?, ?, ?, ?)",
                (
                    decision_id,
                    case_id,
                    DecisionKind.INTENT_AGREEMENT.value,
                    intent_version_id,
                    intent["revision"],
                    actor,
                    utc_now(),
                    evidence_ref,
                    content_hash,
                ),
            )
            self.conn.execute(
                "UPDATE intent_version SET status = ? WHERE id = ?",
                (IntentStatus.AGREED.value, intent_version_id),
            )
            # 동의한 버전에서 내용이 있는 항목은 '사용자 확인됨'이 된다.
            # 내용이 없는 항목은 확인할 대상이 없으므로 미정 그대로 둔다 —
            # 빈 항목을 사람이 확인한 것으로 올리지 않는다.
            self.conn.execute(
                "UPDATE intent_field SET state = ? WHERE intent_version_id = ? AND state != ?",
                (
                    ConfirmationState.USER_CONFIRMED.value,
                    intent_version_id,
                    ConfirmationState.UNDECIDED.value,
                ),
            )
            # 그 버전의 **성공 기준**도 여기서 제안에서 확인으로 올라간다.
            # 사람이 원문을 읽고 그 버전에 명시 동의한 것이 곧 그 문서 안 기준에
            # 대한 확인이기 때문이다(intent-artifacts 1절 "초안 단계의 기준은 제안이며
            # 사용자가 확인한 기준과 구별한다"). 동의 없이 기준만 확인하는 경로는
            # 만들지 않는다 — 그러면 기준이 의도에서 분리된다.
            self.conn.execute(
                "UPDATE success_criterion SET state = ?"
                " WHERE intent_version_id = ? AND state = ?",
                (
                    CriterionState.USER_CONFIRMED.value,
                    intent_version_id,
                    CriterionState.PROPOSED.value,
                ),
            )
        row = self.conn.execute("SELECT * FROM decision WHERE id = ?", (decision_id,)).fetchone()
        return dict(row)

    def intent_state(self, case_id: str) -> dict[str, Any]:
        """Case 수준의 의도·동의 상태.

        **오래된 동의를 최신 동의로 승격시키지 않는 곳이 여기다.** 최신 버전에 붙은
        동의가 없으면 과거 동의가 있어도 `stale_agreement` 이며, 그 사실과
        어느 버전에 동의했는지를 함께 돌려준다(FR-23, FR-14).
        """
        self.get_case(case_id)
        latest = self.latest_intent_version(case_id)
        if latest is None:
            return {
                "case_id": case_id,
                "latest_intent_version": None,
                "agreement_state": IntentAgreementState.NO_INTENT.value,
                "agreed_version": None,
                "open_intent_questions": [],
                "unresolved_feedback": [],
                "views": [],
            }

        current_agreement = self.agreement_for(latest["id"])
        prior = self.conn.execute(
            "SELECT d.*, iv.revision AS intent_revision FROM decision d"
            " JOIN intent_version iv ON iv.id = d.subject_id"
            " WHERE d.kind = ? AND d.subject_type = 'intent_version' AND d.case_id = ?"
            "   AND d.revoked_at IS NULL"
            " ORDER BY iv.revision DESC LIMIT 1",
            (DecisionKind.INTENT_AGREEMENT.value, case_id),
        ).fetchone()

        if current_agreement is not None:
            state = IntentAgreementState.AGREED_CURRENT
            agreed: dict[str, Any] | None = dict(current_agreement)
        elif prior is not None:
            state = IntentAgreementState.STALE_AGREEMENT
            agreed = dict(prior)
        else:
            state = IntentAgreementState.NEVER_AGREED
            agreed = None

        unresolved = [
            f for f in self.list_feedback(case_id) if f["state"] == FeedbackState.RECEIVED.value
        ]
        return {
            "case_id": case_id,
            "latest_intent_version": latest,
            "agreement_state": state.value,
            "agreed_version": agreed,
            "open_intent_questions": self.open_intent_stage_questions(latest["id"]),
            "unresolved_feedback": unresolved,
            "views": self.list_intent_views(latest["id"]),
        }

    # ------------------------------------------------------ 원문 열람 요청

    def open_read_request(
        self, artifact_id: str, revision: int, requested_by: str
    ) -> dict[str, Any]:
        """원문 열람을 요청한다. 대상은 Case에 속한 (artifact_id, revision) 뿐이다.

        경로를 받지 않는다 — 임의 파일 다운로드 API로 만들지 않기 위해서다
        (data-boundary-review 3절).
        """
        ref = self.get_artifact_ref(artifact_id, revision)
        if ref["availability"] == Availability.LOST_BEFORE_PERSIST.value:
            raise ConflictError("original was lost before it was persisted; nothing to read")
        request_id = ids.new_read_request_id()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO artifact_read_request (id, case_id, artifact_id, revision,"
                " owner_runner_id, requested_by, state, requested_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request_id,
                    ref["case_id"],
                    artifact_id,
                    revision,
                    ref["owner_runner_id"],
                    requested_by,
                    ReadRequestState.PENDING.value,
                    utc_now(),
                ),
            )
        return self.get_read_request(request_id)

    def get_read_request(self, request_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM artifact_read_request WHERE id = ?", (request_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"read request not found: {request_id}")
        return dict(row)

    def list_pending_read_requests(self, runner_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM artifact_read_request WHERE state = ? AND owner_runner_id = ?"
            " ORDER BY requested_at",
            (ReadRequestState.PENDING.value, runner_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_read_relayed(
        self, request_id: str, runner_id: str, content_hash: str, byte_size: int
    ) -> dict[str, Any]:
        request = self.get_read_request(request_id)
        if request["owner_runner_id"] != runner_id:
            raise ConflictError("read request belongs to another runner")
        if request["state"] != ReadRequestState.PENDING.value:
            raise ConflictError(f"read request is {request['state']}")
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE artifact_read_request SET state = ?, content_hash = ?, byte_size = ?,"
                " relayed_at = ? WHERE id = ?",
                (ReadRequestState.RELAYED.value, content_hash, byte_size, utc_now(), request_id),
            )
        return self.get_read_request(request_id)

    def mark_read_delivered(self, request_id: str) -> dict[str, Any]:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE artifact_read_request SET state = ?, delivered_at = ? WHERE id = ?",
                (ReadRequestState.DELIVERED.value, utc_now(), request_id),
            )
        return self.get_read_request(request_id)

    def mark_read_expired(self, request_id: str) -> dict[str, Any]:
        """중계 중이던 본문이 사라졌다. 대표 사례는 제어부 재시작이다.

        내용이 없는 상태를 빈 문서나 삭제로 표시하지 않는다(data-boundary 3절).
        """
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE artifact_read_request SET state = ? WHERE id = ? AND state IN (?, ?)",
                (
                    ReadRequestState.EXPIRED.value,
                    request_id,
                    ReadRequestState.PENDING.value,
                    ReadRequestState.RELAYED.value,
                ),
            )
        return self.get_read_request(request_id)

    def list_unfinished_read_requests(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM artifact_read_request WHERE state IN (?, ?)",
            (ReadRequestState.PENDING.value, ReadRequestState.RELAYED.value),
        ).fetchall()
        return [dict(r) for r in rows]

    def intent_intake_context(self, artifact_id: str, revision: int) -> dict[str, Any] | None:
        """이 원문이 어떤 의도 버전의 것인지, 그리고 직전 버전의 원문은 무엇인지.

        Runner가 버전 차이를 계산하려면 직전 버전의 원문이 필요하다. 제어부는
        본문을 모르지만 **어느 원문과 비교해야 하는지**는 참조로 알려 줄 수 있다.
        """
        row = self.conn.execute(
            "SELECT * FROM intent_version WHERE artifact_id = ? AND artifact_rev = ?",
            (artifact_id, revision),
        ).fetchone()
        if row is None:
            return None
        previous = self.conn.execute(
            "SELECT artifact_id, artifact_rev FROM intent_version"
            " WHERE case_id = ? AND revision < ? ORDER BY revision DESC LIMIT 1",
            (row["case_id"], row["revision"]),
        ).fetchone()
        return {
            "intent_version_id": row["id"],
            "intent_revision": row["revision"],
            "prev_artifact_id": previous["artifact_id"] if previous else None,
            "prev_artifact_rev": previous["artifact_rev"] if previous else None,
        }

    def intent_diff(self, intent_version_id: str) -> dict[str, Any]:
        """이전 버전과의 차이. **항목 단위 변화와 질문의 추가·해소만** 돌려준다.

        전체 본문 차이는 여기서 만들지 않는다. 두 버전의 원문을 각각 열람해
        비교하며, 그 원문은 Runner에 있다(data-boundary 1절).
        """
        intent = self.get_intent_version(intent_version_id)
        previous = self.conn.execute(
            "SELECT * FROM intent_version WHERE case_id = ? AND revision < ?"
            " ORDER BY revision DESC LIMIT 1",
            (intent["case_id"], intent["revision"]),
        ).fetchone()

        fields = self.list_intent_fields(intent_version_id)
        changed = [f["field"] for f in fields if f["change_from_prev"] == FieldChange.CHANGED.value]

        current_q = {q["question_key"]: q for q in self.list_questions(intent_version_id)}
        prev_q = {q["question_key"]: q for q in self.list_questions(previous["id"])} if previous else {}

        reflected = self.conn.execute(
            "SELECT * FROM feedback WHERE reflected_in_version_id = ? ORDER BY created_at",
            (intent_version_id,),
        ).fetchall()

        return {
            "intent_version_id": intent_version_id,
            "revision": intent["revision"],
            "compared_with_revision": previous["revision"] if previous else None,
            "fields": fields,
            "changed_fields": changed,
            "questions_added": sorted(set(current_q) - set(prev_q)),
            "questions_removed": sorted(set(prev_q) - set(current_q)),
            "open_questions": [
                q for q in current_q.values() if q["state"] == QuestionState.OPEN.value
            ],
            "reflected_feedback": [dict(r) for r in reflected],
            "full_text_diff": "not_on_controller",
            "note": (
                "항목 단위 변화만 제어부에 있다. 전체 본문 차이는 두 버전의 원문을"
                " 각각 열람해 비교한다 — 원문은 소유 Runner에 있다."
            ),
        }

    # ===================================================================== P2-03
    #
    # QG-01 게이트 판정과 FR-29 진입 조건 검사.
    #
    # 두 기능 모두 **본문을 다루지 않는다.** 게이트는 보고된 항목 구조와 AI 검토가
    # 올린 짧은 요약만 보고, 진입 검사는 상태값만 본다.

    # ------------------------------------------------------------- CLI 능력 조회

    def tool_capability(self, tool_id: str, capability: str) -> str | None:
        """등록된 Runner들이 보고한 이 능력의 상태 중 가장 강한 값.

        `verified` 가 하나라도 있으면 `verified` 다. 아무도 보고하지 않았으면
        `None` 이며 이것은 `unsupported` 와 다르다 — 확인하지 않은 것이다.
        """
        rows = self.conn.execute(
            "SELECT DISTINCT state FROM runner_capability WHERE tool_id = ? AND capability = ?",
            (tool_id, capability),
        ).fetchall()
        states = {r["state"] for r in rows}
        for candidate in (
            CapabilityState.VERIFIED.value,
            CapabilityState.DOC_ONLY.value,
            CapabilityState.UNKNOWN.value,
            CapabilityState.UNSUPPORTED.value,
        ):
            if candidate in states:
                return candidate
        return None

    def tool_installed(self, tool_id: str) -> bool:
        """실제로 실행할 수 있다고 **관측된** 도구인가.

        `doc_only` 는 사용 가능이 아니다. 미설치·미인증을 사용 가능으로 표시하지
        않는다(FR-28 수용 기준).
        """
        return self.tool_capability(tool_id, "installed") == CapabilityState.VERIFIED.value

    def permission_mapped(self, tool_id: str, permission: Permission) -> bool:
        """추상 권한을 이 도구의 실제 인자로 옮길 수 있는가.

        매핑이 없으면 더 넓은 권한으로 대체하지 않고 실행을 거부한다(P1 계약 6절).
        """
        state = self.tool_capability(tool_id, f"permission:{permission.value}")
        return state == CapabilityState.VERIFIED.value

    # --------------------------------------------------------------- QG-01 게이트

    def _gate_row(self, intent_version_id: str, gate: GateId = GateId.QG_01):
        return self.conn.execute(
            "SELECT * FROM gate_result WHERE intent_version_id = ? AND gate = ?",
            (intent_version_id, gate.value),
        ).fetchone()

    def get_gate_result(self, gate_result_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM gate_result WHERE id = ?", (gate_result_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"gate result not found: {gate_result_id}")
        result = dict(row)
        result["findings"] = self.list_gate_findings(gate_result_id)
        return result

    def list_gate_findings(self, gate_result_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM gate_finding WHERE gate_result_id = ? ORDER BY source, criterion",
            (gate_result_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _replace_findings(
        self, gate_result_id: str, source: str, findings: Iterable[gatemod.Finding]
    ) -> None:
        """한 출처의 발견 사항을 통째로 다시 쓴다.

        규칙과 AI를 따로 지우는 이유는 한쪽을 다시 돌려도 다른 쪽 결과가 사라지면
        안 되기 때문이다. 재검사가 이전 발견을 조용히 없애는 경로를 막는다.
        """
        now = utc_now()
        self.conn.execute(
            "DELETE FROM gate_finding WHERE gate_result_id = ? AND source = ?",
            (gate_result_id, source),
        )
        for finding in findings:
            row = finding.to_row()
            self.conn.execute(
                "INSERT INTO gate_finding (id, gate_result_id, source, criterion, severity,"
                " blocking, certainty, target, summary, evidence_artifact_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ids.new_id("finding"),
                    gate_result_id,
                    row["source"],
                    row["criterion"],
                    row["severity"],
                    row["blocking"],
                    row["certainty"],
                    row["target"],
                    row["summary"],
                    row["evidence_artifact_id"],
                    now,
                ),
            )

    def evaluate_gate_rules(
        self, intent_version_id: str, gate: GateId = GateId.QG_01
    ) -> dict[str, Any]:
        """규칙 검사를 수행하고 판정을 갱신한다.

        **AI 검토 결과는 건드리지 않는다.** 이미 이 버전을 검토한 기록이 있으면
        그대로 두고, 없으면 `not_run` 으로 남는다. 규칙만 통과한 상태를 게이트
        통과로 만들지 않기 위해 두 판정을 따로 저장한다.
        """
        detail = self.get_intent_detail(intent_version_id)
        latest = self.latest_intent_version(detail["case_id"])
        is_latest = latest is not None and latest["id"] == intent_version_id
        rule_verdict, findings = gatemod.rule_check(detail, is_latest)

        existing = self._gate_row(intent_version_id, gate)
        now = utc_now()
        with transaction(self.conn):
            if existing is None:
                gate_result_id = ids.new_id("gate")
                self.conn.execute(
                    "INSERT INTO gate_result (id, case_id, gate, intent_version_id,"
                    " subject_content_hash, verdict, rule_verdict, ai_verdict, evaluated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        gate_result_id,
                        detail["case_id"],
                        gate.value,
                        intent_version_id,
                        detail["content_hash"],
                        gatemod.combine_verdicts(rule_verdict, GateVerdict.NOT_RUN).value,
                        rule_verdict.value,
                        GateVerdict.NOT_RUN.value,
                        now,
                    ),
                )
            else:
                gate_result_id = existing["id"]
                # **AI 판정을 그대로 합치지 않는다**(P3-R4). 합칠 대상은 "요구를
                # 충족하는 정합성 확인"이며, 가벼운 확인이 요구를 충족하면 그쪽이
                # 쓰인다. 독립 검토 결과는 `ai_verdict` 에 그대로 남는다.
                _, conformance_verdict = self._conformance_for_gate(
                    intent_version_id, detail["case_id"]
                )
                self.conn.execute(
                    "UPDATE gate_result SET rule_verdict = ?, verdict = ?, evaluated_at = ?,"
                    " subject_content_hash = ? WHERE id = ?",
                    (
                        rule_verdict.value,
                        gatemod.combine_verdicts(
                            rule_verdict, conformance_verdict
                        ).value,
                        now,
                        detail["content_hash"],
                        gate_result_id,
                    ),
                )
            self._replace_findings(gate_result_id, "rule", findings)
        return self.get_gate_result(gate_result_id)

    def apply_gate_review(
        self,
        intent_version_id: str,
        run_id: str,
        raw_findings: list[dict[str, Any]],
        gate: GateId = GateId.QG_01,
    ) -> dict[str, Any]:
        """AI 의미 검토 결과를 게이트에 붙인다.

        **판정은 발견 사항에서 다시 계산한다.** 실행자가 스스로 "통과"를 선언하게
        두지 않는다. 검토한 run 의 세션과 이 초안을 작성한 세션이 같으면 별도 세션
        요구가 깨진 것이므로 통과로 반영하지 않고 판단 보류로 남긴다(FR-29).
        """
        detail = self.get_intent_detail(intent_version_id)
        run = self.get_run(run_id)
        if run["case_id"] != detail["case_id"]:
            raise ConflictError("review run belongs to another case")
        if run["role"] != RunRole.REVIEWER.value:
            raise ConflictError("gate review must run in the reviewer role")

        findings = gatemod.normalize_ai_findings(raw_findings)
        ai_verdict = gatemod.ai_verdict_from(findings)

        author_session = self.author_session_ref(intent_version_id)
        review_session = run["session_ref"]
        if (
            author_session is not None
            and review_session is not None
            and author_session == review_session
        ):
            ai_verdict = GateVerdict.HOLD
            findings.append(
                gatemod.Finding(
                    source=FindingSource.AI,
                    criterion="review_session_not_separate",
                    severity=FindingSeverity.REQUIRED,
                    blocking=False,
                    certainty=FindingCertainty.CONFIRMED,
                    target="session",
                    summary="검토 세션이 작성 세션과 같다. 별도 세션 요구를 충족하지 않는다",
                )
            )

        existing = self._gate_row(intent_version_id, gate)
        if existing is None:
            self.evaluate_gate_rules(intent_version_id, gate)
            existing = self._gate_row(intent_version_id, gate)
        # 대상 원문이 그 사이 바뀌었으면 이 검토는 다른 것을 본 결과다.
        if existing["subject_content_hash"] != detail["content_hash"]:
            raise ConflictError("the reviewed original is not the current one")

        rule_verdict = GateVerdict(existing["rule_verdict"])
        now = utc_now()
        with transaction(self.conn):
            # **독립 검토도 정합성 확인 한 건으로 기록한다**(P3-R4). 게이트 판정은
            # 그 기록에서 나오며, 가벼운 확인과 **같은 표에 다른 방식으로** 남는다.
            # 두 방식을 한 컬럼으로 합치면 무엇을 실제로 했는지가 사라진다.
            self._upsert_conformance_check(
                case_id=detail["case_id"],
                intent_version_id=intent_version_id,
                method=ConformanceMethod.INDEPENDENT,
                verdict=ai_verdict,
                run_id=run_id,
                subject_content_hash=detail["content_hash"],
                unverified_scope=None,
                reasons=[],
                now=now,
            )
            _, conformance_verdict = self._conformance_for_gate(
                intent_version_id, detail["case_id"]
            )
            self.conn.execute(
                "UPDATE gate_result SET ai_verdict = ?, verdict = ?, ai_run_id = ?,"
                " ai_session_ref = ?, author_session_ref = ?, reviewed_at = ? WHERE id = ?",
                (
                    ai_verdict.value,
                    gatemod.combine_verdicts(rule_verdict, conformance_verdict).value,
                    run_id,
                    review_session,
                    author_session,
                    now,
                    existing["id"],
                ),
            )
            self._replace_findings(existing["id"], "ai", findings)
        return self.get_gate_result(existing["id"])

    def author_session_ref(self, intent_version_id: str) -> str | None:
        """이 의도 버전을 작성한 실행의 세션 식별자.

        사람이 직접 쓴 초안에는 작성 실행이 없으므로 `None` 이다. 그 경우
        "같은 세션인가"라는 질문 자체가 성립하지 않는다.
        """
        intent = self.get_intent_version(intent_version_id)
        run_id = intent.get("author_run_id")
        if not run_id:
            return None
        row = self.conn.execute(
            "SELECT session_ref FROM run WHERE run_id = ?", (run_id,)
        ).fetchone()
        return row["session_ref"] if row else None

    def gate_state(self, case_id: str, gate: GateId = GateId.QG_01) -> dict[str, Any]:
        """Case 의 **최신 의도 버전**에 대한 게이트 상태.

        최신 버전에 판정이 없으면 `not_run` 이다. 이전 버전의 통과를 끌어오지 않는다.
        """
        self.get_case(case_id)
        latest = self.latest_intent_version(case_id)
        if latest is None:
            return {
                "gate": gate.value,
                "intent_version_id": None,
                "verdict": GateVerdict.NOT_APPLICABLE.value,
                "rule_verdict": GateVerdict.NOT_APPLICABLE.value,
                "ai_verdict": GateVerdict.NOT_APPLICABLE.value,
                "findings": [],
            }
        row = self._gate_row(latest["id"], gate)
        if row is None:
            return {
                "gate": gate.value,
                "intent_version_id": latest["id"],
                "verdict": GateVerdict.NOT_RUN.value,
                "rule_verdict": GateVerdict.NOT_RUN.value,
                "ai_verdict": GateVerdict.NOT_RUN.value,
                "findings": [],
            }
        return self.get_gate_result(row["id"])

    def list_gate_results(self, case_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id FROM gate_result WHERE case_id = ? ORDER BY evaluated_at DESC",
            (case_id,),
        ).fetchall()
        return [self.get_gate_result(r["id"]) for r in rows]

    # ------------------------------------------------------ P4-01 일반 게이트·repair

    def _quality_policy_rows(
        self, case_id: str, gate: GateId, task_key: str = ""
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        case_row = self.conn.execute(
            "SELECT * FROM quality_gate_policy WHERE case_id = ? AND task_key = ''"
            " AND gate = ? AND state = 'current'",
            (case_id, gate.value),
        ).fetchone()
        task_row = None
        if task_key:
            task_row = self.conn.execute(
                "SELECT * FROM quality_gate_policy WHERE case_id = ? AND task_key = ?"
                " AND gate = ? AND state = 'current'",
                (case_id, task_key, gate.value),
            ).fetchone()
        return (
            dict(case_row) if case_row else None,
            dict(task_row) if task_row else None,
        )

    def _reserved_quality_policy_rows(
        self, case_id: str, gate: GateId, task_key: str = ""
    ) -> list[dict[str, Any]]:
        """아직 반영되지 않은 예약 설정(P4-02).

        **유효 정책에 섞지 않는다.** 이 행들은 "요청됐다"이고 현재 적용된 것은
        여전히 `current` 행이다. 둘을 합치면 예약만으로 진행 중 검사가 무효화된
        것처럼 보인다(D-30).
        """
        scopes = [""] if not task_key else [task_key, ""]
        rows: list[dict[str, Any]] = []
        for scope in scopes:
            rows.extend(
                dict(r)
                for r in self.conn.execute(
                    "SELECT * FROM quality_gate_policy WHERE case_id = ? AND task_key = ?"
                    " AND gate = ? AND state = 'pending' ORDER BY revision",
                    (case_id, scope, gate.value),
                )
            )
        return rows

    def _running_quality_gate_run(
        self, case_id: str, gate: GateId, task_key: str = "", subject_key: str | None = None
    ) -> dict[str, Any] | None:
        """이 범위에서 **진행 중인 검증 1회**.

        범위 겹침이 중요하다. Case 전체 설정 변경(`task_key = ''`)은 그 게이트의
        **어느 Task 검증이든** 돌고 있으면 기다린다. Task 범위 변경은 그 Task 의
        검증만 기다린다. 넓은 변경이 좁은 검증을 못 본 척하면 진행 중 검사가 시작
        당시 정책을 유지한다는 약속이 깨진다.
        """
        sql = (
            "SELECT * FROM quality_gate_run WHERE case_id = ? AND gate = ?"
            " AND status = 'running'"
        )
        args: tuple[Any, ...] = (case_id, gate.value)
        if task_key:
            sql += " AND task_key = ?"
            args += (task_key,)
        if subject_key is not None:
            sql += " AND subject_key = ?"
            args += (subject_key,)
        sql += " ORDER BY created_at LIMIT 1"
        row = self.conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def _current_quality_task(self, case_id: str, task_key: str) -> dict[str, Any] | None:
        if not task_key:
            return None
        graph = self.current_work_graph_row(case_id)
        if graph is None:
            return None
        row = self.conn.execute(
            "SELECT * FROM task WHERE graph_revision_id = ? AND task_key = ?",
            (graph["id"], task_key),
        ).fetchone()
        return dict(row) if row else None

    def effective_quality_gate_policy(
        self, case_id: str, gate: GateId, task_key: str = ""
    ) -> dict[str, Any]:
        """추천과 Case/Task 명시 설정을 합친 현재 정책.

        설정과 판정을 합치지 않는다. 이 응답이 `off`라고 해서 마지막 실패나 성공
        기준이 사라지지 않으며, 최신 실행은 별도 필드로 붙는다.
        """
        case = self.get_case(case_id)
        task = self._current_quality_task(case_id, task_key)
        if task_key and task is None:
            raise NotFoundError(f"task not found in the current work graph: {task_key}")

        repo_state = self.case_repository_state(case_id)
        repository_count = len(repo_state["selected"])
        if repository_count == 0 and repo_state["implicit_single_repository"]:
            repository_count = 1
        level = self.current_level(case_id)
        qg01_requirement = self.conformance_requirement(case_id)
        base = quality.recommended_policy(
            gate,
            profile=case.get("profile"),
            level=level.value if level else None,
            task_kind=task.get("kind") if task else None,
            repository_count=repository_count,
            risk_requires_independent=self.case_requires_independent_review(case_id),
            qg01_independent=(
                qg01_requirement["required_method"]
                == ConformanceMethod.INDEPENDENT.value
            ),
        )
        case_row, task_row = self._quality_policy_rows(case_id, gate, task_key)
        rows = [r for r in (task_row, case_row) if r is not None]

        setting = base.setting
        inspection = base.inspection
        source = base.source.value
        reason = base.reason
        repair_limit = base.repair_limit
        applied_row: dict[str, Any] | None = None
        for row in rows:
            if row["setting"] != "inherit":
                setting = quality.GateSetting.ON if row["setting"] == "on" else quality.GateSetting.OFF
                source = row["source"]
                reason = row["reason_summary"]
                applied_row = applied_row or row
                break
        for row in rows:
            if row["inspection"]:
                requested = quality.InspectionMethod(row["inspection"])
                # 명시 설정은 검사를 강화할 수 있지만 위험/깊이가 요구한 방식을
                # 낮추지 못한다. OFF는 검사 자체를 생략하는 별도 선택이다.
                if quality.inspection_satisfies(inspection, requested):
                    inspection = requested
                    applied_row = applied_row or row
                break
        for row in rows:
            if row["repair_limit"] is not None:
                repair_limit = int(row["repair_limit"])
                applied_row = applied_row or row
                break

        if gate is GateId.QG_01:
            setting = quality.GateSetting.REQUIRED
            source = quality.GatePolicySource.SYSTEM_REQUIRED.value

        latest_run = self.conn.execute(
            "SELECT * FROM quality_gate_run WHERE case_id = ? AND gate = ?"
            " AND task_key = ? ORDER BY created_at DESC LIMIT 1",
            (case_id, gate.value, task_key),
        ).fetchone()
        cycle = None
        if latest_run:
            cycle = self.conn.execute(
                "SELECT * FROM remediation_cycle WHERE case_id = ? AND gate = ?"
                " AND subject_key = ?",
                (case_id, gate.value, latest_run["subject_key"]),
            ).fetchone()
        return {
            "gate": gate.value,
            "label": quality.GATE_LABELS[gate],
            "task_key": task_key or None,
            "setting": setting.value,
            "applied": setting in (quality.GateSetting.REQUIRED, quality.GateSetting.ON),
            "inspection_required": inspection.value,
            "source": source,
            "reason": reason,
            "repair_limit": repair_limit,
            "policy_revision": applied_row["revision"] if applied_row else 0,
            # **요청 시각과 적용 시각을 나눠 준다**(P4-02). 즉시 적용된 행은 둘이
            # 같고, 예약을 거쳐 반영된 행은 다르다. 추천만 적용 중이면 둘 다 없다 —
            # 사람이 설정한 적이 없다는 뜻이며 `0` 으로 적지 않는다.
            "requested_at": applied_row["requested_at"] if applied_row else None,
            "applied_at": applied_row["applied_at"] if applied_row else None,
            "apply_boundary": applied_row["apply_boundary"] if applied_row else None,
            "reserved": [
                {
                    "policy_id": row["id"],
                    "revision": row["revision"],
                    "task_key": row["task_key"] or None,
                    "setting": row["setting"],
                    "inspection": row["inspection"],
                    "repair_limit": row["repair_limit"],
                    "requested_at": row["requested_at"],
                    "requested_by": row["set_by"],
                    "reason": row["reason_summary"],
                    "apply_after_run_id": row["apply_after_run_id"],
                    "apply_boundary": row["apply_boundary"],
                }
                for row in self._reserved_quality_policy_rows(case_id, gate, task_key)
            ],
            "running_gate_run_id": (
                (self._running_quality_gate_run(case_id, gate, task_key) or {}).get("id")
            ),
            "latest_run": self._quality_gate_run_dict(dict(latest_run)) if latest_run else None,
            "remediation": dict(cycle) if cycle else None,
        }

    def quality_gate_state(self, case_id: str, task_key: str = "") -> dict[str, Any]:
        policies = [
            self.effective_quality_gate_policy(case_id, gate, task_key)
            for gate in GateId
        ]
        # QG-01은 기존 실제 판정과 검사 방식을 연결한다. 일반 표로 복제하지 않는다.
        qg01 = next(p for p in policies if p["gate"] == GateId.QG_01.value)
        qg01["latest_run"] = {
            "legacy_qg01": True,
            **self.gate_state(case_id),
            "conformance": self.conformance_state(case_id),
        }
        return {"case_id": case_id, "task_key": task_key or None, "gates": policies}

    def quality_gate_blockers_for_run(
        self, case_id: str, purpose: RunPurpose, task_key: str
    ) -> list[dict[str, str]]:
        """현재 실행이 의존하는 **명시 ON** 게이트의 미통과 목록.

        Profile 추천 QG-02/03의 기본 조건은 기존 preparation/work-graph 판정이 이미
        강제한다. 여기서는 사용자가 Case/Task에 별도 게이트를 명시했을 때 그것을
        기록만 하고 무시하는 구멍을 닫는다. QG-04 이후의 종료 경계 연결은 P4-02~05의
        부분 재검증·완료 작업에서 확장한다.
        """
        requirements: list[tuple[GateId, str]] = []
        if purpose is RunPurpose.PLAN_AUTHORING:
            requirements = [(GateId.QG_02, "")]
        elif purpose is RunPurpose.FEATURE_IMPLEMENTATION:
            requirements = [(GateId.QG_02, ""), (GateId.QG_03, task_key)]
        elif purpose is RunPurpose.VERIFICATION_RUN:
            requirements = [(GateId.QG_04, task_key)]

        blockers: list[dict[str, str]] = []
        for gate, scoped_task in requirements:
            # 그래프/Task가 아직 없거나 요청한 Task가 그래프 밖이면 기존
            # `_check_work_graph`가 정확한 거부 사유를 낸다. 여기서 Task 정책을
            # 조회해 404로 바꾸면 진입 검사의 구조화된 거부 기록이 사라진다.
            if scoped_task and self._current_quality_task(case_id, scoped_task) is None:
                continue
            policy = self.effective_quality_gate_policy(case_id, gate, scoped_task)
            # revision 0은 추천/기존 조건이고 기존 준비 판정이 담당한다. 명시 정책만
            # 일반 게이트 실행을 추가 조건으로 만든다.
            if policy["policy_revision"] == 0 or not policy["applied"]:
                continue
            latest = policy["latest_run"]
            if not latest or latest.get("verdict") != GateVerdict.PASS.value or latest.get(
                "validity"
            ) != quality.GateValidity.CURRENT.value:
                blockers.append(
                    {
                        "gate": gate.value,
                        "verdict": (latest or {}).get("verdict", GateVerdict.NOT_RUN.value),
                    }
                )
        return blockers

    def set_quality_gate_policy(
        self,
        case_id: str,
        gate: GateId,
        *,
        task_key: str = "",
        setting: str = "inherit",
        inspection: str | None = None,
        repair_limit: int | None = None,
        actor: str,
        reason_summary: str,
    ) -> dict[str, Any]:
        self.get_case(case_id)
        self.guard_open_case(case_id)
        if task_key and self._current_quality_task(case_id, task_key) is None:
            raise NotFoundError(f"task not found in the current work graph: {task_key}")
        if setting not in {"on", "off", "inherit"}:
            raise ConflictError("quality gate setting must be on, off, or inherit")
        if gate is GateId.QG_01 and setting == "off":
            raise ConflictError("QG-01 is required and cannot be turned off")
        requested_inspection = quality.InspectionMethod(inspection) if inspection else None
        current = self.effective_quality_gate_policy(case_id, gate, task_key)
        if requested_inspection and not quality.inspection_satisfies(
            quality.InspectionMethod(current["inspection_required"]), requested_inspection
        ):
            raise ConflictError("a quality gate setting cannot lower the required inspection")
        if repair_limit is not None and repair_limit < 0:
            raise ConflictError("repair limit must be zero or greater")
        if repair_limit is not None:
            scope_sql = " AND task_key = ?" if task_key else ""
            params: tuple[Any, ...] = (
                (case_id, gate.value, task_key)
                if task_key
                else (case_id, gate.value)
            )
            consumed = self.conn.execute(
                "SELECT MAX(used_attempts + reserved_attempts) AS n"
                " FROM remediation_cycle WHERE case_id = ? AND gate = ?" + scope_sql,
                params,
            ).fetchone()
            if int((consumed or {})["n"] or 0) > repair_limit:
                raise ConflictError("repair limit cannot be lower than attempts already used or reserved")
        reason = _summary(reason_summary)
        if not reason.strip():
            raise ConflictError("a quality gate policy change needs a reason")

        row = self.conn.execute(
            "SELECT MAX(revision) AS r FROM quality_gate_policy"
            " WHERE case_id = ? AND task_key = ? AND gate = ?",
            (case_id, task_key, gate.value),
        ).fetchone()
        revision = int(row["r"] or 0) + 1
        now = utc_now()
        # **여기가 P4-02의 갈림길이다.** 그 범위에 진행 중인 검증 1회가 있으면
        # 변경을 적용하지 않고 예약한다(D-30). 예약은 취소 명령이 아니다 — 돌고
        # 있는 검사는 시작 당시 정책 그대로 끝나고, 반영은 그 뒤다.
        running = self._running_quality_gate_run(case_id, gate, task_key)
        previous_inspection = current["inspection_required"]
        with transaction(self.conn):
            if running is not None:
                self.conn.execute(
                    "INSERT INTO quality_gate_policy"
                    " (id, case_id, task_key, gate, revision, setting, inspection, repair_limit,"
                    " source, set_by, reason_summary, state, created_at, requested_at,"
                    " apply_after_run_id, apply_boundary)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)",
                    (
                        ids.new_id("qpol"), case_id, task_key, gate.value, revision, setting,
                        requested_inspection.value if requested_inspection else None,
                        repair_limit,
                        "task_explicit" if task_key else "case_explicit",
                        actor, reason, now, now, running["id"],
                        quality.PolicyApplyBoundary.VERIFICATION_END.value,
                    ),
                )
            else:
                self.conn.execute(
                    "UPDATE quality_gate_policy SET state = 'superseded', superseded_at = ?"
                    " WHERE case_id = ? AND task_key = ? AND gate = ? AND state = 'current'",
                    (now, case_id, task_key, gate.value),
                )
                self.conn.execute(
                    "INSERT INTO quality_gate_policy"
                    " (id, case_id, task_key, gate, revision, setting, inspection, repair_limit,"
                    " source, set_by, reason_summary, state, created_at, requested_at,"
                    " applied_at, apply_boundary)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'current', ?, ?, ?, ?)",
                    (
                        ids.new_id("qpol"), case_id, task_key, gate.value, revision, setting,
                        requested_inspection.value if requested_inspection else None,
                        repair_limit,
                        "task_explicit" if task_key else "case_explicit",
                        actor, reason, now, now, now,
                        quality.PolicyApplyBoundary.IMMEDIATE.value,
                    ),
                )
                self._apply_quality_policy_effects(
                    case_id,
                    gate,
                    task_key,
                    previous_inspection=previous_inspection,
                    repair_limit=repair_limit,
                    now=now,
                )
        return self.effective_quality_gate_policy(case_id, gate, task_key)

    def _apply_quality_policy_effects(
        self,
        case_id: str,
        gate: GateId,
        task_key: str,
        *,
        previous_inspection: str,
        repair_limit: int | None,
        now: str,
    ) -> None:
        """설정이 **실제로 반영될 때** 기존 판정·repair 한도에 미치는 효과.

        `needs_recheck` 를 만드는 것은 **검사 강도 변경 하나**다(P4-02). ON/OFF
        토글은 그 게이트를 쓸지 말지를 정할 뿐 이미 끝난 검사가 무엇을 보았는지
        바꾸지 않으므로, 토글만으로 같은 테스트를 다시 돌릴 이유가 없다
        (gate-operations 5절). repair 한도는 다음 차수의 허용량이라 마찬가지다.

        반대로 한도 변경은 **이미 쓴 차수를 보존**한다. 소진 상태였던 주기는 여유가
        생긴 만큼만 다시 열리며 사용량이 0으로 돌아가지 않는다.
        """
        try:
            new_inspection = self.effective_quality_gate_policy(case_id, gate, task_key)[
                "inspection_required"
            ]
        except NotFoundError:
            # 그 사이 Task 가 현재 그래프에서 빠졌다. 정책 행은 그대로 남기고
            # 강도 효과만 계산하지 않는다 — 없는 Task 의 판정을 지어내지 않는다.
            new_inspection = previous_inspection
        if quality.policy_change_invalidates_verdict(
            previous_inspection=previous_inspection, new_inspection=new_inspection
        ):
            sql = (
                "UPDATE quality_gate_run SET validity = 'needs_recheck'"
                " WHERE case_id = ? AND gate = ? AND validity = 'current'"
                " AND status <> 'running'"
            )
            args: tuple[Any, ...] = (case_id, gate.value)
            if task_key:
                sql += " AND task_key = ?"
                args += (task_key,)
            self.conn.execute(sql, args)
        if repair_limit is not None:
            sql = (
                "UPDATE remediation_cycle SET repair_limit = ?,"
                " state = CASE WHEN state = 'exhausted' AND used_attempts + reserved_attempts < ?"
                " THEN 'active' ELSE state END, updated_at = ?"
                " WHERE case_id = ? AND gate = ? AND state <> 'passed'"
            )
            args = (repair_limit, repair_limit, now, case_id, gate.value)
            if task_key:
                sql += " AND task_key = ?"
                args += (task_key,)
            self.conn.execute(sql, args)

    def _release_reserved_quality_policies(
        self, case_id: str, gate_run_id: str, now: str
    ) -> list[str]:
        """검증 1회가 끝났다. 그 실행을 기다리던 예약을 요청 순서대로 반영한다.

        순서가 계약이다 — `현재 결과 보존 → 예약 적용 → 재평가`(gate-operations
        5절). 호출자가 판정을 **먼저** 저장하므로 여기서는 2·3 만 한다. 판정이
        실패여도 반영한다. 통과만 기다리면 OFF 요청이 영원히 걸린다.
        """
        rows = [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM quality_gate_policy WHERE apply_after_run_id = ?"
                " AND state = 'pending' ORDER BY revision",
                (gate_run_id,),
            )
        ]
        applied: list[str] = []
        for row in rows:
            gate = GateId(row["gate"])
            scope = row["task_key"]
            try:
                previous_inspection = self.effective_quality_gate_policy(
                    case_id, gate, scope
                )["inspection_required"]
            except NotFoundError:
                previous_inspection = row["inspection"] or ""
            self.conn.execute(
                "UPDATE quality_gate_policy SET state = 'superseded', superseded_at = ?"
                " WHERE case_id = ? AND task_key = ? AND gate = ? AND state = 'current'",
                (now, case_id, scope, row["gate"]),
            )
            self.conn.execute(
                "UPDATE quality_gate_policy SET state = 'current', applied_at = ?"
                " WHERE id = ?",
                (now, row["id"]),
            )
            self._apply_quality_policy_effects(
                case_id,
                gate,
                scope,
                previous_inspection=previous_inspection,
                repair_limit=row["repair_limit"],
                now=now,
            )
            applied.append(row["id"])
        return applied

    def cancel_reserved_quality_gate_policy(
        self,
        case_id: str,
        gate: GateId,
        *,
        task_key: str = "",
        actor: str,
        reason_summary: str,
    ) -> dict[str, Any]:
        """예약을 취소한다. **이미 적용된 것은 되돌리지 않는다.**

        취소는 "반영하지 말라"이고 롤백은 "반영한 것을 없던 일로 하라"다. 뒤쪽은
        하지 않는다 — 이미 그 정책으로 판정·배정이 일어났을 수 있다.
        """
        self.get_case(case_id)
        reason = _summary(reason_summary)
        if not reason.strip():
            raise ConflictError("a reservation cancel needs a reason")
        rows = self.conn.execute(
            "SELECT id FROM quality_gate_policy WHERE case_id = ? AND task_key = ?"
            " AND gate = ? AND state = 'pending'",
            (case_id, task_key, gate.value),
        ).fetchall()
        if not rows:
            raise NotFoundError("no reserved quality gate policy in this scope")
        now = utc_now()
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE quality_gate_policy SET state = 'cancelled', cancelled_at = ?,"
                " cancelled_by = ?, cancel_reason = ?"
                " WHERE case_id = ? AND task_key = ? AND gate = ? AND state = 'pending'",
                (now, actor, reason, case_id, task_key, gate.value),
            )
        return self.effective_quality_gate_policy(case_id, gate, task_key)

    def _quality_gate_run_dict(self, row: dict[str, Any]) -> dict[str, Any]:
        for field in ("context_refs_json", "criteria_refs_json", "evidence_refs_json"):
            row[field.removesuffix("_json")] = json.loads(row.pop(field))
        findings = self.conn.execute(
            "SELECT * FROM quality_gate_finding WHERE gate_run_id = ? ORDER BY created_at",
            (row["id"],),
        ).fetchall()
        row["findings"] = [dict(f) for f in findings]
        row["late_result"] = bool(row.get("late_result"))
        row["revalidations"] = [
            dict(r)
            for r in self.conn.execute(
                "SELECT v.*, e.kind, e.change_ref FROM quality_revalidation v"
                " JOIN quality_change_event e ON e.id = v.change_event_id"
                " WHERE v.gate_run_id = ? ORDER BY v.created_at",
                (row["id"],),
            )
        ]
        return row

    def get_quality_gate_run(self, gate_run_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM quality_gate_run WHERE id = ?", (gate_run_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"quality gate run not found: {gate_run_id}")
        return self._quality_gate_run_dict(dict(row))

    # ------------------------------------------------ 검증 1회: 입력 고정과 판정

    def _validate_quality_run_inputs(
        self,
        *,
        subject_key: str,
        input_hash: str,
        context_refs: list[str],
        criteria_refs: list[str],
        evidence_refs: list[str],
    ) -> None:
        if not subject_key.strip() or not input_hash.strip():
            raise ConflictError("a quality gate run needs a subject key and input hash")
        _quality_ref(input_hash, field="input_hash", maximum=128)
        if not context_refs or not criteria_refs:
            raise ConflictError("a quality gate review needs request/context and criterion references")
        for collection in (context_refs, criteria_refs, evidence_refs):
            if len(collection) > 100:
                raise ConflictError("a quality gate reference list is too large")
            if any(
                not isinstance(ref, str)
                or not ref.strip()
                or len(ref) > 160
                or "\n" in ref
                or "\r" in ref
                for ref in collection
            ):
                raise ConflictError(
                    "quality gate inputs store short reference identifiers, not bodies"
                )

    def _quality_policy_fingerprint(self, gate: GateId, policy: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "gate": gate.value,
                    "setting": policy["setting"],
                    "inspection": policy["inspection_required"],
                    "revision": policy["policy_revision"],
                    "repair_limit": policy["repair_limit"],
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    def _resolve_quality_sessions(
        self,
        case_id: str,
        *,
        used: quality.InspectionMethod,
        author_run_id: str | None,
        reviewer_run_id: str | None,
        evidence_refs: list[str],
    ) -> tuple[str | None, str | None]:
        author_session = None
        if author_run_id:
            author = self.get_run(author_run_id)
            if author["case_id"] != case_id:
                raise ConflictError("author run belongs to another case")
            if author["status"] != RunStatus.FINISHED.value or author.get(
                "outcome"
            ) != RunOutcome.COMPLETED.value:
                raise ConflictError("the referenced author run is not successfully completed")
            author_session = author.get("session_ref")
        reviewer_session = None
        if used is quality.InspectionMethod.INDEPENDENT:
            if not reviewer_run_id:
                raise ConflictError("an independent gate review needs a reviewer run")
            reviewer = self.get_run(reviewer_run_id)
            if reviewer["case_id"] != case_id:
                raise ConflictError("reviewer run belongs to another case")
            if reviewer["role"] != RunRole.REVIEWER.value:
                raise ConflictError("an independent gate review needs the reviewer role")
            if reviewer["purpose"] != RunPurpose.QUALITY_GATE_REVIEW.value:
                raise ConflictError("the run purpose is not quality_gate_review")
            if reviewer["status"] != RunStatus.FINISHED.value or reviewer.get(
                "outcome"
            ) != RunOutcome.COMPLETED.value:
                raise ConflictError("the reviewer run is not successfully completed")
            reviewer_session = reviewer.get("session_ref")
            if author_session and reviewer_session and author_session == reviewer_session:
                raise ConflictError("an independent review must use a separate session")
            if not evidence_refs:
                raise ConflictError("an independent gate review needs evidence references")
        return author_session, reviewer_session

    def _normalize_quality_findings(
        self, findings: list[dict[str, Any]], criteria_refs: list[str]
    ) -> tuple[list[dict[str, Any]], bool, bool]:
        normalized: list[dict[str, Any]] = []
        blocking = False
        hold = False
        allowed_criteria = set(criteria_refs)
        for index, raw in enumerate(findings, start=1):
            finding_key = _quality_ref(
                raw.get("finding_key") or f"finding-{index}", field="finding_key", maximum=120
            )
            criterion = _quality_ref(
                raw.get("criterion") or "unspecified", field="criterion", maximum=120
            )
            target = _quality_ref(
                raw.get("target") or "subject", field="target", maximum=120
            )
            evidence_artifact_id = raw.get("evidence_artifact_id")
            if evidence_artifact_id is not None:
                evidence_artifact_id = _quality_ref(
                    evidence_artifact_id, field="evidence_artifact_id"
                )
            requested_required = str(raw.get("severity") or "advisory") == "required"
            certainty = str(raw.get("certainty") or "suspected")
            # AI/검토자가 기존 필수 기준에 연결하지 못한 의견으로 새 필수 요구를
            # 만들지 못한다. 의견은 보존하되 advisory로 내린다.
            severity = "required" if requested_required and criterion in allowed_criteria else "advisory"
            item_blocks = severity == "required" and certainty == "confirmed"
            blocking = blocking or item_blocks
            hold = hold or (severity == "required" and certainty != "confirmed")
            normalized.append(
                {
                    "finding_key": finding_key,
                    "criterion": criterion,
                    "severity": severity,
                    "blocking": 1 if item_blocks else 0,
                    "certainty": certainty if certainty in {"confirmed", "suspected"} else "suspected",
                    "target": target,
                    "summary": _summary(raw.get("summary") or "(요약 없음)"),
                    "evidence_artifact_id": evidence_artifact_id,
                }
            )
        return normalized, blocking, hold

    def _insert_quality_findings(
        self, gate_run_id: str, normalized: list[dict[str, Any]], now: str
    ) -> None:
        for item in normalized:
            self.conn.execute(
                "INSERT INTO quality_gate_finding"
                " (id, gate_run_id, finding_key, criterion, severity, blocking, certainty,"
                " target, summary, evidence_artifact_id, state, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)",
                (
                    ids.new_id("qfind"), gate_run_id, item["finding_key"], item["criterion"],
                    item["severity"], item["blocking"], item["certainty"], item["target"],
                    item["summary"], item["evidence_artifact_id"], now,
                ),
            )

    def _settle_remediation_for_verdict(
        self,
        case_id: str,
        gate: GateId,
        *,
        subject_key: str,
        task_key: str,
        gate_run_id: str,
        verdict: str,
        repair_limit: int,
        now: str,
    ) -> None:
        if verdict == GateVerdict.FAIL.value:
            self.conn.execute(
                "INSERT OR IGNORE INTO remediation_cycle"
                " (id, case_id, gate, subject_key, task_key, initial_gate_run_id, repair_limit,"
                " used_attempts, reserved_attempts, state, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 'active', ?, ?)",
                (
                    ids.new_id("repair"), case_id, gate.value, subject_key, task_key, gate_run_id,
                    repair_limit, now, now,
                ),
            )
            self.conn.execute(
                "UPDATE remediation_cycle SET state = CASE"
                " WHEN used_attempts + reserved_attempts >= repair_limit"
                " THEN 'exhausted' ELSE 'active' END, updated_at = ?"
                " WHERE case_id = ? AND gate = ? AND subject_key = ?",
                (now, case_id, gate.value, subject_key),
            )
        elif verdict == GateVerdict.PASS.value:
            self.conn.execute(
                "UPDATE remediation_cycle SET state = 'passed', updated_at = ?"
                " WHERE case_id = ? AND gate = ? AND subject_key = ?",
                (now, case_id, gate.value, subject_key),
            )

    def record_quality_gate_run(
        self,
        case_id: str,
        gate: GateId,
        *,
        subject_key: str,
        input_hash: str,
        inspection_used: str,
        context_refs: list[str],
        criteria_refs: list[str],
        evidence_refs: list[str],
        findings: list[dict[str, Any]],
        task_key: str = "",
        author_run_id: str | None = None,
        reviewer_run_id: str | None = None,
        blocked: bool = False,
    ) -> dict[str, Any]:
        """QG-02~07의 한 평가를 **한 번에** 기록하고 판정을 발견에서 계산한다.

        규칙 검사처럼 시작과 끝이 같은 순간인 검증이 이 경로를 쓴다. 그때는 설정
        변경이 끼어들 틈이 없으므로 예약 경계가 생기지 않는다. 진행 중 상태가 필요한
        검증은 `start_quality_gate_run` + `complete_quality_gate_run` 을 쓴다(P4-02).
        """
        if gate is GateId.QG_01:
            raise ConflictError("QG-01 uses the intent gate and conformance records")
        policy = self.effective_quality_gate_policy(case_id, gate, task_key)
        if not policy["applied"]:
            raise ConflictError("an off or not-applicable gate cannot record a pass")
        used = quality.InspectionMethod(inspection_used)
        required = quality.InspectionMethod(policy["inspection_required"])
        if not quality.inspection_satisfies(required, used):
            raise ConflictError("the recorded inspection does not satisfy the gate policy")
        self._validate_quality_run_inputs(
            subject_key=subject_key,
            input_hash=input_hash,
            context_refs=context_refs,
            criteria_refs=criteria_refs,
            evidence_refs=evidence_refs,
        )
        author_session, reviewer_session = self._resolve_quality_sessions(
            case_id,
            used=used,
            author_run_id=author_run_id,
            reviewer_run_id=reviewer_run_id,
            evidence_refs=evidence_refs,
        )
        normalized, blocking, hold = self._normalize_quality_findings(findings, criteria_refs)
        verdict = (
            GateVerdict.BLOCKED.value if blocked else
            GateVerdict.FAIL.value if blocking else
            GateVerdict.HOLD.value if hold else
            GateVerdict.PASS.value
        )
        status = "blocked" if blocked else "completed"
        fingerprint = self._quality_policy_fingerprint(gate, policy)
        gate_run_id = ids.new_id("qrun")
        now = utc_now()
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE quality_gate_run SET validity = 'historical'"
                " WHERE case_id = ? AND gate = ? AND subject_key = ? AND validity = 'current'",
                (case_id, gate.value, subject_key),
            )
            self.conn.execute(
                "INSERT INTO quality_gate_run"
                " (id, case_id, task_key, gate, subject_key, input_hash, policy_fingerprint,"
                " inspection_required, inspection_used, status, verdict, validity,"
                " context_refs_json, criteria_refs_json, evidence_refs_json, author_run_id,"
                " reviewer_run_id, author_session_ref, reviewer_session_ref, created_at,"
                " completed_at, started_policy_revision, late_result)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'current', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (
                    gate_run_id, case_id, task_key, gate.value, subject_key, input_hash,
                    fingerprint, required.value, used.value, status, verdict,
                    json.dumps(context_refs), json.dumps(criteria_refs), json.dumps(evidence_refs),
                    author_run_id, reviewer_run_id, author_session, reviewer_session, now, now,
                    policy["policy_revision"],
                ),
            )
            self._insert_quality_findings(gate_run_id, normalized, now)
            self._settle_remediation_for_verdict(
                case_id,
                gate,
                subject_key=subject_key,
                task_key=task_key,
                gate_run_id=gate_run_id,
                verdict=verdict,
                repair_limit=policy["repair_limit"],
                now=now,
            )
        return self.get_quality_gate_run(gate_run_id)

    def start_quality_gate_run(
        self,
        case_id: str,
        gate: GateId,
        *,
        subject_key: str,
        input_hash: str,
        context_refs: list[str],
        criteria_refs: list[str],
        task_key: str = "",
        author_run_id: str | None = None,
    ) -> dict[str, Any]:
        """검증 1회를 **연다**(P4-02).

        시작 시점의 정책 리비전·검사 강도를 이 실행에 고정한다. 중간에 설정이
        바뀌어도 이 검사는 시작 당시 정책으로 끝나며, 그 변경은 예약으로 남는다.

        **이전 통과를 지금 지우지 않는다.** 시작만으로 `historical` 로 내리면 끝내지
        못한 검증 하나가 유효한 증거를 없애 버린다. 대체는 종료 시점에 한다.
        """
        if gate is GateId.QG_01:
            raise ConflictError("QG-01 uses the intent gate and conformance records")
        self.get_case(case_id)
        self.guard_open_case(case_id)
        policy = self.effective_quality_gate_policy(case_id, gate, task_key)
        if not policy["applied"]:
            raise ConflictError("an off or not-applicable gate cannot open a verification")
        self._validate_quality_run_inputs(
            subject_key=subject_key,
            input_hash=input_hash,
            context_refs=context_refs,
            criteria_refs=criteria_refs,
            evidence_refs=[],
        )
        if self._running_quality_gate_run(case_id, gate, task_key, subject_key) is not None:
            raise ConflictError("a verification for this subject is already running")
        author_session, _ = self._resolve_quality_sessions(
            case_id,
            used=quality.InspectionMethod.RULE,
            author_run_id=author_run_id,
            reviewer_run_id=None,
            evidence_refs=[],
        )
        gate_run_id = ids.new_id("qrun")
        now = utc_now()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO quality_gate_run"
                " (id, case_id, task_key, gate, subject_key, input_hash, policy_fingerprint,"
                " inspection_required, inspection_used, status, verdict, validity,"
                " context_refs_json, criteria_refs_json, evidence_refs_json, author_run_id,"
                " reviewer_run_id, author_session_ref, reviewer_session_ref, created_at,"
                " started_policy_revision, late_result)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, 'current', ?, ?, '[]', ?,"
                " NULL, ?, NULL, ?, ?, 0)",
                (
                    gate_run_id, case_id, task_key, gate.value, subject_key, input_hash,
                    self._quality_policy_fingerprint(gate, policy),
                    policy["inspection_required"], policy["inspection_required"],
                    GateVerdict.NOT_RUN.value,
                    json.dumps(context_refs), json.dumps(criteria_refs),
                    author_run_id, author_session, now, policy["policy_revision"],
                ),
            )
        return self.get_quality_gate_run(gate_run_id)

    def request_quality_gate_run_stop(
        self, gate_run_id: str, *, actor: str, reason_summary: str
    ) -> dict[str, Any]:
        """검증 1회의 **취소를 요청한다.** 종료 확인이 아니다.

        상태를 `completed` 로 바꾸지 않는 것이 핵심이다. CLI·도구의 취소 지원 능력은
        버전마다 다르고, 요청 뒤 늦게 도착한 결과도 원래 실행에 저장해야 한다
        (gate-operations 5절). 그래서 요청 사실만 적고 실제 종료는 결과가 말한다.
        """
        row = self.conn.execute(
            "SELECT * FROM quality_gate_run WHERE id = ?", (gate_run_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"quality gate run not found: {gate_run_id}")
        if row["status"] != "running":
            raise ConflictError("only a running verification can be asked to stop")
        reason = _summary(reason_summary)
        if not reason.strip():
            raise ConflictError("a stop request needs a reason")
        now = utc_now()
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE quality_gate_run SET stop_requested_at = ?, stop_requested_by = ?,"
                " stop_reason = ? WHERE id = ? AND stop_requested_at IS NULL",
                (now, actor, reason, gate_run_id),
            )
        return self.get_quality_gate_run(gate_run_id)

    def _late_gate_result_reason(self, row: dict[str, Any]) -> str:
        """이 결과가 **늦은 결과**인가. 이유 문자열, 아니면 빈 문자열.

        늦었다는 것은 "결과가 틀렸다"가 아니라 **그 사이 조건이 바뀌어 지금의 통과로
        쓸 수 없다**는 뜻이다. 결과는 그대로 보존하고 원래 실행에 귀속시킨다.
        """
        if row.get("stop_requested_at"):
            return "취소 요청 뒤 도착한 결과다"
        case_id = row["case_id"]
        gate = GateId(row["gate"])
        try:
            policy = self.effective_quality_gate_policy(case_id, gate, row["task_key"])
        except NotFoundError:
            return "검증 대상 Task 가 현재 작업 그래프에 없다"
        if not policy["applied"]:
            return "게이트가 적용되지 않는 상태로 바뀐 뒤 도착한 결과다"
        started = row.get("started_policy_revision")
        if started is not None and int(started) != int(policy["policy_revision"]):
            return "시작 당시 정책 리비전과 현재 정책이 다르다"
        newer = self.conn.execute(
            "SELECT 1 FROM quality_gate_run WHERE case_id = ? AND gate = ?"
            " AND subject_key = ? AND id <> ? AND validity = 'current'"
            " AND status <> 'running' AND created_at > ?",
            (case_id, gate.value, row["subject_key"], row["id"], row["created_at"]),
        ).fetchone()
        if newer is not None:
            return "같은 대상의 더 새로운 검증이 이미 현재 판정이다"
        return ""

    def complete_quality_gate_run(
        self,
        gate_run_id: str,
        *,
        inspection_used: str,
        evidence_refs: list[str],
        findings: list[dict[str, Any]],
        author_run_id: str | None = None,
        reviewer_run_id: str | None = None,
        blocked: bool = False,
    ) -> dict[str, Any]:
        """검증 1회를 닫는다. 그리고 **그 실행을 기다리던 예약을 반영한다**(P4-02).

        판정은 **시작 당시 고정한 검사 강도**로 검사한다. 중간에 바뀐 현재 정책으로
        다시 재는 것은 "예약만으로 진행 중 검사를 무효화하지 않는다"는 계약을 뒤에서
        깨는 일이다.

        순서는 `현재 결과 보존 → 예약 적용 → 재평가` 다(gate-operations 5절).
        판정이 실패여도 예약을 반영한다.
        """
        row = self.conn.execute(
            "SELECT * FROM quality_gate_run WHERE id = ?", (gate_run_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"quality gate run not found: {gate_run_id}")
        run = dict(row)
        if run["status"] != "running":
            raise ConflictError("this verification is not running")
        case_id = run["case_id"]
        gate = GateId(run["gate"])
        task_key = run["task_key"]
        context_refs = json.loads(run["context_refs_json"])
        criteria_refs = json.loads(run["criteria_refs_json"])
        used = quality.InspectionMethod(inspection_used)
        required = quality.InspectionMethod(run["inspection_required"])
        if not quality.inspection_satisfies(required, used):
            raise ConflictError("the recorded inspection does not satisfy the gate policy")
        self._validate_quality_run_inputs(
            subject_key=run["subject_key"],
            input_hash=run["input_hash"],
            context_refs=context_refs,
            criteria_refs=criteria_refs,
            evidence_refs=evidence_refs,
        )
        author_session, reviewer_session = self._resolve_quality_sessions(
            case_id,
            used=used,
            author_run_id=author_run_id or run["author_run_id"],
            reviewer_run_id=reviewer_run_id,
            evidence_refs=evidence_refs,
        )
        normalized, blocking, hold = self._normalize_quality_findings(findings, criteria_refs)
        verdict = (
            GateVerdict.BLOCKED.value if blocked else
            GateVerdict.FAIL.value if blocking else
            GateVerdict.HOLD.value if hold else
            GateVerdict.PASS.value
        )
        status = "blocked" if blocked else "completed"
        late_reason = self._late_gate_result_reason(run)
        now = utc_now()
        with transaction(self.conn):
            if not late_reason:
                self.conn.execute(
                    "UPDATE quality_gate_run SET validity = 'historical'"
                    " WHERE case_id = ? AND gate = ? AND subject_key = ? AND id <> ?"
                    " AND validity = 'current'",
                    (case_id, gate.value, run["subject_key"], gate_run_id),
                )
            self.conn.execute(
                "UPDATE quality_gate_run SET status = ?, verdict = ?, validity = ?,"
                " inspection_used = ?, evidence_refs_json = ?, author_run_id = ?,"
                " reviewer_run_id = ?, author_session_ref = ?, reviewer_session_ref = ?,"
                " completed_at = ?, late_result = ? WHERE id = ?",
                (
                    status, verdict,
                    "historical" if late_reason else "current",
                    used.value, json.dumps(evidence_refs),
                    author_run_id or run["author_run_id"], reviewer_run_id,
                    author_session, reviewer_session, now,
                    1 if late_reason else 0, gate_run_id,
                ),
            )
            self._insert_quality_findings(gate_run_id, normalized, now)
            if not late_reason:
                # 늦은 결과는 repair 주기를 만들지도 진행시키지도 않는다. 옛 조건의
                # 결과가 지금의 수정 차수를 예약하면 한도가 조용히 새어 나간다.
                policy = self.effective_quality_gate_policy(case_id, gate, task_key)
                self._settle_remediation_for_verdict(
                    case_id,
                    gate,
                    subject_key=run["subject_key"],
                    task_key=task_key,
                    gate_run_id=gate_run_id,
                    verdict=verdict,
                    repair_limit=policy["repair_limit"],
                    now=now,
                )
            # **검증 1회가 끝났다.** 늦은 결과여도 이 실행은 끝났으므로 그것을
            # 기다리던 예약은 반영한다 — 기다릴 대상이 사라지면 예약이 영원히 걸린다.
            self._release_reserved_quality_policies(case_id, gate_run_id, now)
        result = self.get_quality_gate_run(gate_run_id)
        result["late_reason"] = late_reason
        return result

    # ------------------------------------------------ P4-02 변경 영향과 부분 재검증

    def record_quality_change_event(
        self,
        case_id: str,
        *,
        kind: str,
        change_ref: str,
        changed_refs: list[str],
        summary: str,
        actor: str,
        scope_known: bool = True,
    ) -> dict[str, Any]:
        """요청·코드·권한이 바뀌었다. **영향받는 증거만** 다시 보게 만든다.

        전부 다시 돌리지도, 전부 그대로 두지도 않는다. 바뀐 참조를 입력으로 가진
        검사만 `needs_recheck` 가 되고 나머지는 **이유와 참조 버전을 적은 뒤**
        재사용된다(gate-operations 3절). 재사용도 판단이므로 기록을 남긴다.

        범위를 확인할 수 없으면 `unknown` 이며 재검증 대상이다. 확인하지 못한 것을
        "무관하다"로 적지 않는다.

        진행 중 검증은 다르게 다룬다 — 판정이 아직 없으므로 무효화할 것이 없고,
        대신 **취소를 요청**해 둔다. 그 결과가 나중에 도착하면 늦은 결과로 원래
        실행에 저장되고 지금 조건의 통과로 쓰이지 않는다.
        """
        self.get_case(case_id)
        # **종료된 Case 의 증거를 지금 와서 재검증 대상으로 만들지 않는다.** 완료 후
        # 수정은 연결된 새 Case 다(D-33). 여기서 열어 주면 종료 기록이 조용히
        # 바뀐다 — 예약과 달리 이 경로는 곧바로 판정의 유효성을 내린다.
        self.guard_open_case(case_id)
        try:
            change_kind = quality.ChangeKind(kind)
        except ValueError:
            raise ConflictError(f"unknown quality change kind: {kind}")
        _quality_ref(change_ref, field="change_ref")
        if len(changed_refs) > 100:
            raise ConflictError("a change reference list is too large")
        for ref in changed_refs:
            _quality_ref(ref, field="changed_ref")
        reason_summary = _summary(summary)
        if not reason_summary.strip():
            raise ConflictError("a quality change event needs a summary")

        event_id = ids.new_id("qchg")
        now = utc_now()
        rows = [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM quality_gate_run WHERE case_id = ?"
                " AND (validity = 'current' OR status = 'running')"
                " ORDER BY created_at",
                (case_id,),
            )
        ]
        decisions: list[dict[str, Any]] = []
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO quality_change_event"
                " (id, case_id, kind, change_ref, changed_refs_json, scope_known, summary,"
                " recorded_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id, case_id, change_kind.value, change_ref,
                    json.dumps(changed_refs), 1 if scope_known else 0,
                    reason_summary, actor, now,
                ),
            )
            for row in rows:
                impact = quality.change_impact(
                    change_kind,
                    changed_refs=changed_refs,
                    context_refs=json.loads(row["context_refs_json"]),
                    criteria_refs=json.loads(row["criteria_refs_json"]),
                    scope_known=scope_known,
                )
                self.conn.execute(
                    "INSERT INTO quality_revalidation"
                    " (id, change_event_id, gate_run_id, decision, reason_summary,"
                    " referenced_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        ids.new_id("qreval"), event_id, row["id"], impact.decision.value,
                        _summary(impact.reason), row["input_hash"], now,
                    ),
                )
                if impact.needs_recheck:
                    if row["status"] == "running":
                        self.conn.execute(
                            "UPDATE quality_gate_run SET stop_requested_at = ?,"
                            " stop_requested_by = ?, stop_reason = ?"
                            " WHERE id = ? AND stop_requested_at IS NULL",
                            (
                                now, actor,
                                _summary(f"입력이 바뀌었다: {impact.reason}"),
                                row["id"],
                            ),
                        )
                    else:
                        self.conn.execute(
                            "UPDATE quality_gate_run SET validity = 'needs_recheck'"
                            " WHERE id = ? AND validity = 'current'",
                            (row["id"],),
                        )
                decisions.append(
                    {
                        "gate_run_id": row["id"],
                        "gate": row["gate"],
                        "task_key": row["task_key"] or None,
                        "subject_key": row["subject_key"],
                        "status": row["status"],
                        "decision": impact.decision.value,
                        "reason": impact.reason,
                        "referenced_version": row["input_hash"],
                    }
                )
        return {
            "event": self.get_quality_change_event(event_id),
            "decisions": decisions,
        }

    def get_quality_change_event(self, event_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM quality_change_event WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"quality change event not found: {event_id}")
        event = dict(row)
        event["changed_refs"] = json.loads(event.pop("changed_refs_json"))
        event["scope_known"] = bool(event["scope_known"])
        return event

    def list_quality_change_events(self, case_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id FROM quality_change_event WHERE case_id = ? ORDER BY created_at",
            (case_id,),
        ).fetchall()
        events = []
        for row in rows:
            event = self.get_quality_change_event(row["id"])
            event["decisions"] = [
                dict(r)
                for r in self.conn.execute(
                    "SELECT * FROM quality_revalidation WHERE change_event_id = ?"
                    " ORDER BY created_at",
                    (row["id"],),
                )
            ]
            events.append(event)
        return events

    def quality_gate_policy_drift(
        self, case_id: str, expected: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        """배정 요청이 기대한 정책과 **지금의** 정책이 다른가(P4-02).

        저장과 배정 사이에 정책이 바뀌면 옛 배정 요청으로 실행을 시작하지 않는다
        (gate-operations 3절 7항). 예약만 있는 상태는 현재 정책을 바꾸지 않으므로
        여기에 걸리지 않는다 — 예약은 차단이 아니다.

        `expected` 는 `{"QG-04": {"revision": 2, "task_key": "T1"}}` 또는
        `{"QG-04": 2}` 형태다. 기대를 적지 않은 요청은 이 검사를 만들지 않는다.
        """
        if not expected:
            return []
        drift: list[dict[str, Any]] = []
        for raw_gate, raw_value in expected.items():
            try:
                gate = GateId(raw_gate)
            except ValueError:
                raise ConflictError(f"unknown quality gate: {raw_gate}")
            if isinstance(raw_value, dict):
                revision = raw_value.get("revision")
                task_key = str(raw_value.get("task_key") or "")
            else:
                revision = raw_value
                task_key = ""
            if revision is None:
                continue
            try:
                policy = self.effective_quality_gate_policy(case_id, gate, task_key)
            except NotFoundError:
                drift.append(
                    {
                        "gate": gate.value,
                        "expected_revision": int(revision),
                        "current_revision": None,
                        "reason": "기대한 Task 가 현재 작업 그래프에 없다",
                    }
                )
                continue
            if int(policy["policy_revision"]) != int(revision):
                drift.append(
                    {
                        "gate": gate.value,
                        "expected_revision": int(revision),
                        "current_revision": int(policy["policy_revision"]),
                        "reason": "저장과 배정 사이에 게이트 정책이 바뀌었다",
                    }
                )
        return drift

    def remediation_state(self, case_id: str, gate: GateId, subject_key: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM remediation_cycle WHERE case_id = ? AND gate = ? AND subject_key = ?",
            (case_id, gate.value, subject_key),
        ).fetchone()
        if row is None:
            raise NotFoundError("remediation cycle not found")
        out = dict(row)
        attempts = self.conn.execute(
            "SELECT * FROM remediation_attempt WHERE cycle_id = ? ORDER BY sequence_no",
            (out["id"],),
        ).fetchall()
        out["attempts"] = [dict(a) for a in attempts]
        return out

    def start_remediation_attempt(
        self,
        case_id: str,
        gate: GateId,
        subject_key: str,
        *,
        kind: str,
        task_key: str = "",
        session_ref: str | None = None,
        author_run_id: str | None = None,
    ) -> dict[str, Any]:
        if kind not in {"product_repair", "environment_recovery"}:
            raise ConflictError("unknown remediation attempt kind")
        if session_ref is not None:
            _quality_ref(session_ref, field="session_ref", maximum=200)
        consumes = kind == "product_repair"
        # **OFF 가 반영되면 그 게이트만을 위한 새 수정 차수를 배정하지 않는다**(P4-02).
        # 주기·사용량·발견·실패 판정은 그대로 남는다 — 끄는 것은 "이 게이트로 더
        # 막지 않는다"이고 "관찰한 결함이 사라졌다"가 아니다(gate-operations 5절).
        # 환경 복구는 게이트 전용 작업이 아니고 차수를 소비하지도 않으므로 막지 않는다.
        if consumes:
            cycle_scope = self.conn.execute(
                "SELECT task_key FROM remediation_cycle WHERE case_id = ? AND gate = ?"
                " AND subject_key = ?",
                (case_id, gate.value, subject_key),
            ).fetchone()
            if cycle_scope is not None:
                try:
                    scoped = self.effective_quality_gate_policy(
                        case_id, gate, cycle_scope["task_key"]
                    )
                except NotFoundError:
                    scoped = self.effective_quality_gate_policy(case_id, gate)
                if not scoped["applied"]:
                    raise ConflictError(
                        "the gate is off; no new repair cycle is assigned for it."
                        " the recorded failure and used attempts are kept"
                    )
        if author_run_id:
            run = self.get_run(author_run_id)
            if run["case_id"] != case_id:
                raise ConflictError("repair run belongs to another case")
        attempt_id = ids.new_id("attempt")
        now = utc_now()
        limit_exhausted = False
        with transaction(self.conn):
            row = self.conn.execute(
                "SELECT * FROM remediation_cycle WHERE case_id = ? AND gate = ?"
                " AND subject_key = ?",
                (case_id, gate.value, subject_key),
            ).fetchone()
            if row is None:
                raise NotFoundError("remediation cycle not found")
            cycle = dict(row)
            if cycle["state"] == "passed":
                raise ConflictError("the remediation cycle already passed")
            if consumes and cycle["used_attempts"] + cycle["reserved_attempts"] >= cycle["repair_limit"]:
                self.conn.execute(
                    "UPDATE remediation_cycle SET state = 'exhausted', updated_at = ? WHERE id = ?",
                    (now, cycle["id"]),
                )
                limit_exhausted = True
            else:
                sequence_no = int(
                    self.conn.execute(
                        "SELECT COUNT(*) AS n FROM remediation_attempt WHERE cycle_id = ?",
                        (cycle["id"],),
                    ).fetchone()["n"]
                ) + 1
                repair_no = (
                    cycle["used_attempts"] + cycle["reserved_attempts"] + 1
                    if consumes
                    else None
                )
                if consumes:
                    self.conn.execute(
                        "UPDATE remediation_cycle SET reserved_attempts = reserved_attempts + 1,"
                        " state = 'active', updated_at = ? WHERE id = ?",
                        (now, cycle["id"]),
                    )
                self.conn.execute(
                    "INSERT INTO remediation_attempt"
                    " (id, cycle_id, sequence_no, repair_no, kind, task_key, session_ref, author_run_id,"
                    " state, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reserved', ?)",
                    (
                        attempt_id, cycle["id"], sequence_no, repair_no, kind, task_key,
                        session_ref, author_run_id, now,
                    ),
                )
        if limit_exhausted:
            raise ConflictError("repair limit exhausted")
        return self.remediation_state(case_id, gate, subject_key)

    def complete_remediation_attempt(
        self,
        attempt_id: str,
        *,
        outcome: str,
        verification_run_id: str | None = None,
    ) -> dict[str, Any]:
        attempt = self.conn.execute(
            "SELECT a.*, c.case_id, c.gate, c.subject_key, c.repair_limit"
            " FROM remediation_attempt a JOIN remediation_cycle c ON c.id = a.cycle_id"
            " WHERE a.id = ?",
            (attempt_id,),
        ).fetchone()
        if attempt is None:
            raise NotFoundError(f"remediation attempt not found: {attempt_id}")
        if verification_run_id:
            run = self.get_run(verification_run_id)
            if run["case_id"] != attempt["case_id"]:
                raise ConflictError("verification run belongs to another case")
        now = utc_now()
        consumes = attempt["kind"] == "product_repair"
        with transaction(self.conn):
            current = self.conn.execute(
                "SELECT state FROM remediation_attempt WHERE id = ?", (attempt_id,)
            ).fetchone()
            if current is None or current["state"] != "reserved":
                raise ConflictError("the remediation attempt is already settled")
            self.conn.execute(
                "UPDATE remediation_attempt SET state = 'completed', outcome = ?,"
                " verification_run_id = ?, completed_at = ? WHERE id = ?",
                (outcome[:80], verification_run_id, now, attempt_id),
            )
            if consumes:
                self.conn.execute(
                    "UPDATE remediation_cycle SET reserved_attempts = reserved_attempts - 1,"
                    " used_attempts = used_attempts + 1, updated_at = ? WHERE id = ?",
                    (now, attempt["cycle_id"]),
                )
            self.conn.execute(
                "UPDATE remediation_cycle SET state = 'exhausted', updated_at = ?"
                " WHERE id = ? AND used_attempts >= repair_limit AND state <> 'passed'",
                (now, attempt["cycle_id"]),
            )
        return self.remediation_state(
            attempt["case_id"], GateId(attempt["gate"]), attempt["subject_key"]
        )

    # ------------------------------------------------------ FR-29 진입 조건 검사

    def _planned_reservation_for(
        self,
        case_id: str,
        purpose: RunPurpose,
        role: RunRole,
        instruction_artifact_id: str,
        instruction_artifact_rev: int,
    ) -> dict[BudgetMetric, float | None]:
        """이 요청이 잡게 될 예산(P3-R3).

        **진입 검사와 생성이 같은 값을 봐야 한다.** 두 곳에서 따로 계산하면 한쪽만
        고쳐졌을 때 "검사는 통과했는데 생성이 막히는" 상태가 조용히 생긴다.
        """
        return planned_reservation(
            role,
            context_package_bytes(
                self.conn,
                instruction_artifact_id,
                instruction_artifact_rev,
                [
                    (r["artifact_id"], r["revision"])
                    for r in self.compose_context_refs(case_id, purpose)
                ],
            ),
        )

    def check_admission(
        self,
        case_id: str,
        run_id: str,
        task_id: str,
        purpose: RunPurpose,
        role: RunRole,
        permission: Permission,
        tool_id: str,
        instruction_artifact_id: str,
        instruction_artifact_rev: int,
        session: str = "new",
        target_intent_version_id: str | None = None,
        repository_id: str | None = None,
        expected_gate_policy: dict[str, Any] | None = None,
    ) -> AdmissionResult:
        """진입 조건을 검사한다. **판단 근거를 전부 DB에서 다시 읽는다.**

        메모리에 "이 Case는 통과했다"를 두지 않는 이유는 재시작으로 우회하지
        못하게 하기 위해서다(FR-29 수용 기준).
        """
        case = self.get_case(case_id)
        try:
            ref = self.get_artifact_ref(instruction_artifact_id, instruction_artifact_rev)
            availability = ref["availability"]
        except NotFoundError:
            availability = "missing"

        latest = self.latest_intent_version(case_id)
        author_sessions: list[str] = []
        if latest is not None:
            session_ref = self.author_session_ref(latest["id"])
            if session_ref:
                author_sessions.append(session_ref)

        # **실제 검토 대상은 지시 원문이 정한다.** 배정 내용과 같은 방식으로 여기서도
        # 끌어낸다. 이것을 최신 버전으로 가정하면, 옛 의도 원문을 지시로 준 요청이
        # 검사를 통과한 뒤 엉뚱한 버전을 검토하게 된다(라이브에서 실제로 났던 일).
        if target_intent_version_id is None:
            target = self.intent_version_for_artifact(
                instruction_artifact_id, instruction_artifact_rev
            )
            target_intent_version_id = target["id"] if target else None

        request = AdmissionRequest(
            case_id=case_id,
            case_kind=CaseKind(case["kind"]),
            case_closed=case["status"]
            in (CaseStatus.CLOSED.value, CaseStatus.CANCELLED.value),
            run_id=run_id,
            task_id=task_id,
            purpose=purpose,
            role=role,
            permission=permission,
            tool_id=tool_id,
            session=session,
            instruction_availability=availability,
            intent_state=self.intent_state(case_id),
            gate_state=self.gate_state(case_id),
            target_intent_version_id=target_intent_version_id,
            tool_installed=self.tool_installed(tool_id),
            permission_mapped=self.permission_mapped(tool_id, permission),
            tool_is_coding_cli=(
                self.tool_capability(tool_id, "coding_cli") == CapabilityState.VERIFIED.value
            ),
            author_session_refs=author_sessions,
            # 수준·설계·계획·검토 상태. **DB에서 지금 다시 읽는다** — 메모리에 통과
            # 상태를 두지 않는다는 규칙이 선행 조건에도 그대로 적용된다(FR-29).
            preparation_state=self.preparation_state(case_id),
            # 작업공간과 쓰기 경합도 같은 규칙으로 지금 읽는다(P3-03).
            # **어느 저장소의 작업공간인가**도 함께 본다(P3-R2). 대상을 주지 않았고
            # 작업공간이 둘 이상이면 고르지 않고 거부한다.
            workspace_state=self.workspace_state(case_id, repository_id),
            case_write_runs=self.unfinished_write_runs(case_id=case_id),
            # **예산도 지금 DB 에서 다시 읽는다**(P3-R3). 같은 규칙이다 — 메모리에
            # "이 Case 는 예산이 남았다"를 두면 재시작으로 우회된다.
            budget_breaches=self._budget_breaches(
                case_id, self._planned_reservation_for(case_id, purpose, role,
                                                       instruction_artifact_id,
                                                       instruction_artifact_rev)
            ),
            # **Autonomy·목적·누적 변경도 지금 DB 에서 다시 읽는다**(P3-R4). 같은
            # 규칙이다 — 메모리에 "이 Case 는 시작 확인을 받았다"를 두면 재시작으로
            # 우회된다(FR-29).
            checkpoint_state=self.checkpoint_state(case_id),
            case_profile=case.get("profile"),
            objective_widened=self.objective_widened(case_id),
            material_delta_state=self.material_delta_state(case_id),
            fast_lane=self.fast_lane_state(case_id),
            # **이 Task 가 어느 저장소의 작업인가**(P3-04). 위 `workspace_state` 는
            # "대상이 기록됐는가"이고 이것은 "그 대상이 맞는가"다. 저장소가 하나뿐인
            # Case 에서는 둘이 같은 질문이라 아무 것도 달라지지 않는다.
            task_repository=self.task_repository_state(case_id, task_id),
            run_repository_id=repository_id,
            quality_gate_blockers=self.quality_gate_blockers_for_run(
                case_id, purpose, task_id
            ),
            # **배정 직전 재확인**(P4-02). 요청이 기대한 정책을 적었을 때만 생긴다.
            quality_gate_policy_drift=self.quality_gate_policy_drift(
                case_id, expected_gate_policy
            ),
        )
        return evaluate_admission(request)

    def record_admission(
        self,
        case_id: str,
        run_id: str,
        task_id: str,
        purpose: RunPurpose,
        role: RunRole,
        permission: Permission,
        tool_id: str,
        result: AdmissionResult,
        created_run_id: str | None,
    ) -> dict[str, Any]:
        """검사 결과를 남긴다. **거부도 기록한다.**

        무엇을 거부했는지가 남지 않으면 사람은 왜 실행이 시작되지 않았는지 알 수 없고
        (FR-14), 우회 시도도 드러나지 않는다.
        """
        check_id = ids.new_id("admission")
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO admission_check (id, case_id, run_id, requested_run_id,"
                " requested_purpose, requested_role, requested_permission, requested_task_id,"
                " requested_tool_id, profile, outcome, refusals_json, intent_version_id,"
                " intent_agreement_state, gate_verdict, checked_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    check_id,
                    case_id,
                    created_run_id,
                    run_id,
                    purpose.value,
                    role.value,
                    permission.value,
                    task_id,
                    tool_id,
                    result.profile.value,
                    result.outcome.value,
                    json.dumps([r.value for r in result.refusals], ensure_ascii=False),
                    result.intent_version_id,
                    result.intent_agreement_state,
                    result.gate_verdict,
                    utc_now(),
                ),
            )
        return self.get_admission_check(check_id)

    def get_admission_check(self, check_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM admission_check WHERE id = ?", (check_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"admission check not found: {check_id}")
        check = dict(row)
        check["refusals"] = json.loads(check.pop("refusals_json"))
        return check

    def list_admission_checks(self, case_id: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id FROM admission_check WHERE case_id = ? ORDER BY checked_at DESC LIMIT ?",
            (case_id, limit),
        ).fetchall()
        return [self.get_admission_check(r["id"]) for r in rows]

    def admit_and_create_run(
        self,
        case_id: str,
        run_id: str,
        task_id: str,
        purpose: RunPurpose,
        role: RunRole,
        tool_id: str,
        mode: str,
        permission: Permission,
        instruction_artifact_id: str,
        instruction_artifact_rev: int,
        session: str = "new",
        repository_id: str | None = None,
        expected_gate_policy: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, bool, AdmissionResult | None, dict[str, Any] | None]:
        """**Run을 만드는 유일한 경로.** 진입 검사를 통과해야 만들어진다.

        반환: (Run 또는 None, 이번에 만들었는지, 검사 결과 또는 None, 검사 기록)

        같은 `run_id` 의 재전송은 검사보다 **먼저** 처리하고 검사 결과를 `None` 으로
        돌려준다. 이미 만들어진 실행에 대해서는 "만들어도 되는가"가 아니라 "무엇이
        만들어졌는가"가 답이고, 재전송이 두 번째 실행을 만들지 않는다는 보장
        (P1 이월 항목)이 여기에 걸려 있기 때문이다. 없는 검사를 했다고 적지도 않는다.
        """
        existing = self.conn.execute(
            "SELECT run_id FROM run WHERE run_id = ?", (run_id,)
        ).fetchone()
        if existing is not None:
            return self.get_run(run_id), False, None, None

        # 종료된 Case 도 **진입 검사를 거쳐** 거부된다(`case_already_closed`).
        # 앞단에서 예외로 던지면 "왜 실행이 열리지 않았는가"가 진입 검사 기록에
        # 남지 않는다. 허용도 거부도 같은 표에 남기는 것이 FR-29의 요구다.
        result = self.check_admission(
            case_id=case_id,
            run_id=run_id,
            task_id=task_id,
            purpose=purpose,
            role=role,
            permission=permission,
            tool_id=tool_id,
            instruction_artifact_id=instruction_artifact_id,
            instruction_artifact_rev=instruction_artifact_rev,
            session=session,
            repository_id=repository_id,
            expected_gate_policy=expected_gate_policy,
        )
        if not result.admitted:
            check = self.record_admission(
                case_id, run_id, task_id, purpose, role, permission, tool_id, result, None
            )
            return None, False, result, check

        try:
            run, created = self.create_run(
                run_id=run_id,
                case_id=case_id,
                task_id=task_id,
                role=role,
                tool_id=tool_id,
                mode=mode,
                permission=permission,
                instruction_artifact_id=instruction_artifact_id,
                instruction_artifact_rev=instruction_artifact_rev,
                purpose=purpose,
                repository_id=repository_id,
                # **고정 컨텍스트를 여기서 정한다.** 배정 시점이 아니라 생성 시점에
                # 고정하는 이유는 "실행이 무엇을 보고 썼는가"가 재배정으로 달라지면
                # 안 되기 때문이다(review-context-contract 2절). P3-R3 부터는 Run
                # 행·예약과 **같은 트랜잭션**에 들어간다 — 예약한 `context_bytes` 가
                # 실제 참조와 어긋나지 않게 하기 위해서다.
                context_refs=self.compose_context_refs(case_id, purpose),
            )
        except BudgetExhausted as exhausted:
            # 위의 진입 검사는 통과했는데 트랜잭션 안에서 막혔다 = **경쟁에서 졌다.**
            # 마지막 한 칸을 다른 요청이 먼저 가져갔다는 뜻이다. 이것도 거부로
            # 기록한다 — 기록되지 않으면 사람은 실행이 사라진 이유를 알 수 없다.
            result = AdmissionResult(
                outcome=AdmissionOutcome.REFUSED,
                profile=result.profile,
                refusals=[AdmissionRefusal.BUDGET_HARD_LIMIT_REACHED],
                reasons={
                    AdmissionRefusal.BUDGET_HARD_LIMIT_REACHED.value: budget_refusal_reason(
                        exhausted.breaches
                    )
                },
                intent_version_id=result.intent_version_id,
                intent_agreement_state=result.intent_agreement_state,
                gate_verdict=result.gate_verdict,
            )
            check = self.record_admission(
                case_id, run_id, task_id, purpose, role, permission, tool_id, result, None
            )
            return None, False, result, check
        check = self.record_admission(
            case_id, run_id, task_id, purpose, role, permission, tool_id, result, run["run_id"]
        )
        return run, created, result, check

    # =================================================================== P2-04
    #
    # 결과·완료 기록. 아래 접근자에도 본문을 받는 인자가 없다. 성공 기준의 본문
    # (관련 목표·확인 방법·기대값)은 의도 원문 안에 있고, 근거의 서술과 인수·예외의
    # 문구도 소유 Runner에 있다. 여기에는 판정·사유 코드·참조와 짧은 요약만 남는다.

    # ----------------------------------------------------------- 성공 기준

    def apply_success_criteria(
        self, intent_version_id: str, criteria: Iterable[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Runner가 의도 원문에서 읽어 낸 성공 기준을 반영한다.

        **기준은 의도 버전에 묶인다**(intent-artifacts 1절). 기준이 0건이면 0건으로
        남긴다 — 없는 기준을 시스템이 만들지 않는다. 기준 없는 초안은 QG-01의
        `unverifiable_success_criteria` 관점에서 AI 검토가 볼 문제이지, 제어부가
        빈 통과로 채울 자리가 아니다.
        """
        intent = self.get_intent_version(intent_version_id)
        rows = list(criteria)
        contract = self.completion_contract(intent["case_id"])
        # **P4-03: 기준마다 무엇을 입증하는가.** 계약이 있는 Case 만 정한다. 원문이
        # 적었으면 그것이고, 아니면 연결 항목에 정의의 대응표를 적용한다 — 본문 해석이
        # 아니라 공개된 정의의 적용이며, 출처를 따로 남긴다.
        obligations: list[tuple[str | None, str | None, str | None]] = []
        for row in rows:
            reported = row.get("obligation")
            rule = row.get("conclusion_rule")
            if contract is None:
                if reported or rule:
                    raise ConflictError(
                        f"criterion {row.get('key')} carries an obligation but this case"
                        " follows profile definition v1 (no completion contract)"
                    )
                obligations.append((None, None, None))
                continue
            try:
                obligation, source = meaningmod.derive_obligation(
                    contract, str(row["relates_to"]), reported
                )
                conclusion_rule = ConclusionRule(rule).value if rule else None
            except ValueError as exc:
                raise ConflictError(f"criterion {row.get('key')}: {exc}") from exc
            if conclusion_rule is not None and (
                obligation not in meaningmod.CONCLUSION_OBLIGATIONS
            ):
                raise ConflictError(
                    f"criterion {row.get('key')}: conclusion_rule belongs to cause/answer"
                    f" criteria, not {obligation.value if obligation else 'none'}"
                )
            obligations.append(
                (
                    obligation.value if obligation else None,
                    source.value if source else None,
                    conclusion_rule,
                )
            )
        now = utc_now()
        with transaction(self.conn):
            for row, (obligation_value, source_value, rule_value) in zip(rows, obligations):
                self.conn.execute(
                    "INSERT INTO success_criterion"
                    " (id, case_id, intent_version_id, criterion_key, summary,"
                    "  method_summary, relates_to, state, created_at,"
                    "  obligation, obligation_source, conclusion_rule)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(intent_version_id, criterion_key) DO UPDATE SET"
                    "   summary = excluded.summary,"
                    "   method_summary = excluded.method_summary,"
                    "   relates_to = excluded.relates_to,"
                    "   obligation = excluded.obligation,"
                    "   obligation_source = excluded.obligation_source,"
                    "   conclusion_rule = excluded.conclusion_rule",
                    (
                        ids.new_id("crit"),
                        intent["case_id"],
                        intent_version_id,
                        str(row["key"]),
                        _summary(row["summary"]),
                        _summary(row.get("method_summary", "")),
                        # **P3-R1: Profile 의미 항목도 기준의 대상이 된다.**
                        # `IntentField` 하나로 검증하면 `improvement_target` 같은
                        # 목적별 항목에 걸린 기준이 거부된다 — 라이브에서 실제로
                        # 그렇게 막혔다. 검증 자체는 유지한다(모르는 이름은 저장하지
                        # 않는다).
                        _field_name(row["relates_to"]),
                        CriterionState.PROPOSED.value,
                        now,
                        obligation_value,
                        source_value,
                        rule_value,
                    ),
                )
            # 기준이 생기는 순간 결과는 `unverified` 로 시작한다. 결과 행이 없는 것과
            # "아직 확인하지 않았다"를 구별하기 위해 행을 미리 만든다.
            for crit in self.conn.execute(
                "SELECT id, case_id FROM success_criterion WHERE intent_version_id = ?",
                (intent_version_id,),
            ).fetchall():
                self.conn.execute(
                    "INSERT OR IGNORE INTO criterion_result"
                    " (id, criterion_id, case_id, verdict, evidence_kind, summary,"
                    "  recorded_by, recorded_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        ids.new_id("critres"),
                        crit["id"],
                        crit["case_id"],
                        CriterionVerdict.UNVERIFIED.value,
                        EvidenceKind.NONE.value,
                        "아직 확인하지 않음",
                        "system",
                        now,
                    ),
                )
        return self.list_success_criteria(intent_version_id)

    def _carry_unaffected_results(self, intent_version_id: str) -> None:
        """이전 버전의 기준 판정 중 **내용이 그대로인 것**을 새 버전으로 잇는다.

        새 의도 버전이 생기면 이전 기준은 전부 `superseded` 가 되고 그 판정은
        `needs_recheck` 가 된다(`create_intent_version`). 그 규칙은 "의도가 바뀌면
        연결된 성공 기준을 재검토한다"를 지키지만, **한 항목만 고친 피드백 하나가
        모든 검증을 무효로 만든다.** intent-artifacts 69행은 반대를 요구한다 —
        "의도가 바뀌면 연결된 설계·계획·성공 기준을 재검토하고, **영향이 없는 기록은
        유지한다**".

        그래서 지문이 같은 기준만 판정을 잇는다. 요약·확인 방법·연결 항목이 하나라도
        다르면 잇지 않는다 — 제어부가 관측할 수 있는 범위에서 "같다"를 말할 수 없기
        때문이다.

        **잇는 것은 판정과 근거뿐이다.** 어느 버전에서 그 판정이 나왔는지는 근거
        실행·산출물 참조가 그대로 말한다. 이어진 판정에 `recheck_source` 를 남겨
        "이번 버전에서 다시 확인한 것이 아니다"를 드러낸다.
        """
        intent = self.get_intent_version(intent_version_id)
        previous = self.conn.execute(
            "SELECT * FROM intent_version WHERE case_id = ? AND revision < ?"
            " ORDER BY revision DESC LIMIT 1",
            (intent["case_id"], intent["revision"]),
        ).fetchone()
        if previous is None:
            return
        before = {
            c["criterion_key"]: c
            for c in self.conn.execute(
                "SELECT * FROM success_criterion WHERE intent_version_id = ?",
                (previous["id"],),
            ).fetchall()
        }
        if not before:
            return
        # 이 버전에서 **바뀐 의도 항목**. 그 항목을 가리키는 기준은 영향을 받는다.
        changed_fields = {
            f["field"]
            for f in self.list_intent_fields(intent_version_id)
            if f["change_from_prev"] == FieldChange.CHANGED.value
        }
        carried_keys: set[str] = set()
        for crit in self.conn.execute(
            "SELECT * FROM success_criterion WHERE intent_version_id = ?",
            (intent_version_id,),
        ).fetchall():
            old_crit = before.get(crit["criterion_key"])
            if old_crit is None:
                continue
            if _criterion_fingerprint(old_crit) != _criterion_fingerprint(crit):
                continue
            # **그 기준이 가리키는 의도 항목이 바뀌었으면 잇지 않는다.**
            #
            # 기준의 문구가 그대로여도 그것이 검증하는 의도가 바뀌었으면 옛 판정은
            # 다른 것을 확인한 결과다. 지문만 보면 "기대 결과가 바뀌었는데 기준
            # 문구는 그대로"인 경우에 옛 `met` 이 새 의도에 그대로 붙는다.
            if crit["relates_to"] in changed_fields:
                continue
            old_result = self.conn.execute(
                "SELECT * FROM criterion_result WHERE criterion_id = ?", (old_crit["id"],)
            ).fetchone()
            if old_result is None:
                continue
            # 이어 갈 값이 없는 판정은 잇지 않는다. `unverified`·`needs_recheck` 는
            # "아직 모른다"이며 그것을 옮겨 적을 이유가 없다.
            if old_result["verdict"] in (
                CriterionVerdict.UNVERIFIED.value,
                CriterionVerdict.NEEDS_RECHECK.value,
            ):
                continue
            carried_keys.add(crit["criterion_key"])
            self.conn.execute(
                "UPDATE criterion_result SET verdict = ?, evidence_kind = ?,"
                " evidence_run_id = ?, evidence_artifact_id = ?, evidence_artifact_rev = ?,"
                " summary = ?, recorded_by = ?, recorded_at = ?, composition_id = ?,"
                " satisfaction = ?, conclusion = ?, recheck_source = ?"
                " WHERE criterion_id = ?",
                (
                    old_result["verdict"],
                    old_result["evidence_kind"],
                    old_result["evidence_run_id"],
                    old_result["evidence_artifact_id"],
                    old_result["evidence_artifact_rev"],
                    old_result["summary"],
                    old_result["recorded_by"],
                    old_result["recorded_at"],
                    old_result["composition_id"],
                    old_result["satisfaction"],
                    # 결론도 판정의 일부다(P4-03). 지문이 같다는 것은 의무·결론 요구도
                    # 같다는 뜻이므로 옛 결론이 새 기준에서도 같은 뜻이다.
                    old_result["conclusion"],
                    f"carried_from:{old_crit['id']}",
                    crit["id"],
                ),
            )
        # **이어지지 않은 판정만 재검토로 내린다.** 이어진 판정을 함께 내리면
        # "영향이 없는 기록은 유지한다"가 다시 깨진다.
        now = utc_now()
        for key, old_crit in before.items():
            if key in carried_keys:
                continue
            self.conn.execute(
                "UPDATE criterion_result SET verdict = ?, recorded_at = ?"
                " WHERE criterion_id = ? AND verdict != ?",
                (
                    CriterionVerdict.NEEDS_RECHECK.value,
                    now,
                    old_crit["id"],
                    CriterionVerdict.NEEDS_RECHECK.value,
                ),
            )

    def list_success_criteria(self, intent_version_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT c.*, r.verdict, r.evidence_kind, r.evidence_run_id,"
            "       r.evidence_artifact_id, r.evidence_artifact_rev,"
            "       r.summary AS result_summary, r.recorded_by, r.recorded_at,"
            # **P3-R4: 어떻게 충족했는가와 그 판정이 이어진 것인가.** 화면이 "다시
            # 확인한 판정"과 "이어진 판정"을 구별해야 한다(intent-artifacts 69행).
            "       r.satisfaction, r.recheck_source,"
            # **P4-03: 결론.** 원인·조사 기준이 확정했는가 판단 불가인가.
            "       r.conclusion"
            " FROM success_criterion c"
            " LEFT JOIN criterion_result r ON r.criterion_id = c.id"
            " WHERE c.intent_version_id = ?"
            " ORDER BY c.created_at, c.criterion_key",
            (intent_version_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_success_criterion(self, criterion_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM success_criterion WHERE id = ?", (criterion_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"success criterion not found: {criterion_id}")
        return dict(row)

    def current_criteria(self, case_id: str) -> list[dict[str, Any]]:
        """**최신 의도 버전의** 기준과 결과. 대체된 버전의 기준은 돌려주지 않는다."""
        latest = self.latest_intent_version(case_id)
        if latest is None:
            return []
        return self.list_success_criteria(latest["id"])

    # ----------------------------------------------------------- 기준별 결과

    def record_criterion_result(
        self,
        criterion_id: str,
        verdict: CriterionVerdict,
        summary: str,
        recorded_by: str,
        evidence_kind: EvidenceKind,
        evidence_run_id: str | None = None,
        evidence_artifact_id: str | None = None,
        evidence_artifact_rev: int | None = None,
        composition_id: str | None = None,
        satisfaction: Satisfaction | None = None,
        conclusion: Conclusion | None = None,
    ) -> dict[str, Any]:
        """기준별 판정을 기록한다.

        **여기가 "실행 불명이 성공이 되지 않는다"를 강제하는 지점이다.**

        `met` 을 받으려면 근거 Run 의 `outcome` 이 `completed` 여야 한다.
        `unknown`·`failed`·`cancelled` 를 근거로 한 `met` 은 거부한다. 종료 코드나
        "실행이 끝났다"는 사실로 충족을 적지 않는다(FR-28, completion-lifecycle 5절).

        `needs_recheck` 는 사람이 직접 적는 값이 아니다 — 대상이 바뀌었을 때
        시스템이 전이시키는 값이므로 여기서는 거부한다.

        **`composition_id` 는 그 근거가 어느 코드 조합 위에서 나왔는지다**(P3-R2).
        움직이는 브랜치 이름이 아니라 고정된 조합으로 대상을 묶어야 나중에 그 근거가
        아직 유효한지 답할 수 있다(execution-workspace-review 2.1절). 조회는 그
        유효성을 **저장하지 않고 도출한다**.

        **`satisfaction` 은 어떻게 충족했는가다**(P3-R4·case-profiles 4절). 셋 중
        하나이며 둘은 `met` 이 될 수 있고 하나는 될 수 없다.

            changed_and_verified  바꾸고 확인했다
            already_satisfied     바꾸지 않았고 이미 목표 상태임을 **검증 실행이
                                  관측**했다. 코드 변경을 만들기 위해 불필요한 수정을
                                  강제하지 않는다
            not_reproduced        재현하지 못했다. **`met` 이 되지 않는다** —
                                  "미재현만으로 버그 해결을 선언하지 않는다"

        마지막 줄을 화면이 아니라 **여기서** 막는다. 문구로만 구별하면 API 직접
        호출로 우회된다.

        **P4-03: 완료 계약이 있는 기준(Profile 정의 v2)은 목적 의무의 규칙을 더
        받는다**(`domain/completion_meaning.check_result`). `met` 은 충족 방식이 필수이고
        — 생략이 미재현 차단의 우회로였다 — 의무마다 허용된 방식·근거 실행이 다르며,
        원인·조사 기준은 결론(`conclusion`)을 적는다. v1 기준은 이전 규칙 그대로다.
        """
        criterion = self.get_success_criterion(criterion_id)
        self.guard_open_case(criterion["case_id"])
        if criterion["state"] == CriterionState.SUPERSEDED.value:
            raise ConflictError(
                "criterion belongs to a superseded intent version;"
                " record the result on the current version instead"
            )
        if verdict is CriterionVerdict.NEEDS_RECHECK:
            raise ConflictError(
                "needs_recheck is set by the system when the subject changes,"
                " not recorded directly"
            )

        # 근거 없는 판정은 받지 않는다. `unverified` 로 되돌리는 것만 근거가 필요 없다.
        if verdict is not CriterionVerdict.UNVERIFIED and evidence_kind is EvidenceKind.NONE:
            raise ConflictError(f"verdict {verdict.value} requires evidence")

        run: dict[str, Any] | None = None
        if evidence_run_id is not None:
            run = self.get_run(evidence_run_id)
            if run["case_id"] != criterion["case_id"]:
                raise ConflictError("evidence run belongs to a different case")

        if verdict is CriterionVerdict.MET:
            if evidence_kind is EvidenceKind.RUN_OUTPUT:
                if run is None:
                    raise ConflictError("run_output evidence requires evidence_run_id")
                if run["status"] != RunStatus.FINISHED.value:
                    raise ConflictError(
                        f"cannot record 'met' from run {evidence_run_id}:"
                        f" the run is still {run['status']}"
                    )
                if run["outcome"] != RunOutcome.COMPLETED.value:
                    # 이 한 줄이 P2-04 성공 기준 "실행 불명 상태가 성공이 되지
                    # 않음"의 구체적 구현이다. unknown 을 실패로 바꾸지도 않는다.
                    raise ConflictError(
                        f"cannot record 'met' from run {evidence_run_id}:"
                        f" its outcome is '{run['outcome']}', not 'completed'"
                    )
            if evidence_artifact_id is not None and evidence_artifact_rev is not None:
                ref = self.get_artifact_ref(evidence_artifact_id, evidence_artifact_rev)
                if ref["availability"] == Availability.LOST_BEFORE_PERSIST.value:
                    raise ConflictError("evidence original was lost before persistence")

            # --- P3-R4: 어떻게 충족했는가 --------------------------------
            if satisfaction is not None:
                # 어느 의무에서든 미재현은 `met` 이 아니다. P4-03 의 새 방식
                # (`investigated`·`preserved`)은 아래 목적 의무 규칙이 받거나 거부한다.
                if satisfaction is Satisfaction.NOT_REPRODUCED:
                    raise ConflictError(
                        f"cannot record 'met' with satisfaction='{satisfaction.value}':"
                        " not reproducing a defect is not evidence that it is fixed"
                    )
                if satisfaction.value in SATISFACTION_NEEDING_RUN_EVIDENCE and (
                    evidence_kind is not EvidenceKind.RUN_OUTPUT
                ):
                    # 코드를 바꾸지 않고 "이미 목표 상태다"라고 말하려면 **그것을
                    # 관측한 실행**이 있어야 한다. 사람 판단만으로 적으면 미재현과
                    # 구별되지 않는다(case-profiles 4절 마지막 문단).
                    raise ConflictError(
                        "satisfaction='already_satisfied' needs run_output evidence:"
                        " a verification run must have observed the target state"
                    )
        elif satisfaction is Satisfaction.CHANGED_AND_VERIFIED:
            # 충족하지 않은 판정에 "바꾸고 확인했다"를 붙이지 않는다. 기록이
            # 판정과 어긋나면 나중에 어느 쪽이 사실인지 물을 수 없다.
            raise ConflictError(
                "satisfaction='changed_and_verified' does not fit a non-met verdict"
            )

        # --- P4-03: 목적 의무의 규칙 ------------------------------------------
        violations = meaningmod.check_result(
            contract_applies=self.completion_contract(criterion["case_id"]) is not None,
            obligation=criterion.get("obligation"),
            conclusion_rule=criterion.get("conclusion_rule"),
            verdict=verdict,
            satisfaction=satisfaction,
            conclusion=conclusion,
            evidence_kind=evidence_kind,
            evidence_run=run,
        )
        if violations:
            raise ConflictError("; ".join(str(v) for v in violations))

        if composition_id is not None:
            composition = self.get_code_composition(composition_id)
            if composition["case_id"] != criterion["case_id"]:
                raise ConflictError("code composition belongs to a different case")

        now = utc_now()
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE criterion_result SET verdict = ?, evidence_kind = ?,"
                " evidence_run_id = ?, evidence_artifact_id = ?, evidence_artifact_rev = ?,"
                " summary = ?, recorded_by = ?, recorded_at = ?, composition_id = ?,"
                " satisfaction = ?, conclusion = ?, recheck_source = NULL"
                " WHERE criterion_id = ?",
                (
                    verdict.value,
                    evidence_kind.value,
                    evidence_run_id,
                    evidence_artifact_id,
                    evidence_artifact_rev,
                    _summary(summary),
                    recorded_by,
                    now,
                    composition_id,
                    satisfaction.value if satisfaction is not None else None,
                    conclusion.value if conclusion is not None else None,
                    criterion_id,
                ),
            )
        # **기준 판정이 마지막 조건일 때가 많다.** 여기서 자동 완료를 시도하지 않으면
        # 기본 ask-on-decision 의 "조건 충족 시 자동 완료"(D-31)가 사람이 버튼을 눌러야
        # 일어나는 일이 되고, 그것은 자동 완료가 아니다.
        self.maybe_auto_complete(criterion["case_id"])
        return self.get_criterion_result(criterion_id)

    def get_criterion_result(self, criterion_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM criterion_result WHERE criterion_id = ?", (criterion_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"criterion result not found: {criterion_id}")
        result = dict(row)
        # **그 근거가 가리키는 조합이 아직 유효한가.** 저장하지 않고 도출한다 —
        # 컬럼으로 두면 "누가 그 값을 적었는가"가 새 문제가 된다(P3-03과 같은 이유).
        result["composition"] = self.composition_validity(
            result["case_id"], result.get("composition_id")
        )
        return result

    # ----------------------------------------------------------- 완료 정책

    def completion_mode(self, case_id: str) -> CompletionMode:
        """Case 의 완료 정책.

        **P3-R4에서 바뀌었다.** v0.6 에서는 행이 없으면 사람 최종 확인이었다. 이제
        행이 없으면 **Autonomy 에서 도출한다**(D-31) — 기본 ask-on-decision 은 조건을
        충족하면 자동 완료하고 controlled 는 결과 후보 확인 뒤 종료한다.

        **명시 설정은 그대로 이긴다.** 행이 있으면 도출하지 않는다
        (autonomy-budget-policy 5절 "사용자 명시 설정을 조용히 덮어쓰지 않는다").
        R4 이전에 설정된 행은 이행이 `source = migrated_explicit` 로 적어 두었고,
        그것도 명시 설정이다 — 그때는 도출 경로 자체가 없었다.
        """
        return CompletionMode(self.completion_mode_state(case_id)["mode"])

    def completion_mode_state(self, case_id: str) -> dict[str, Any]:
        """완료 모드와 **그 값이 어디서 왔는가.**

        출처를 함께 돌려주는 이유는 화면이 "사람이 정한 값"과 "Autonomy 에서 도출한
        값"을 구별해야 하기 때문이다. 둘을 같은 모양으로 보이면 사용자가 고르지 않은
        자동 완료가 사용자의 설정처럼 읽힌다.
        """
        row = self.conn.execute(
            "SELECT mode, source, set_by FROM completion_policy WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        if row is not None:
            return {
                "mode": row["mode"],
                "source": row["source"] or "case_explicit",
                "set_by": row["set_by"],
            }
        autonomy = self.effective_autonomy(case_id)
        return {
            "mode": derived_completion_mode(autonomy).value,
            "source": "autonomy_derived",
            "set_by": None,
            "effective_autonomy": autonomy.value.value,
        }

    def set_completion_mode(
        self, case_id: str, mode: CompletionMode, set_by: str
    ) -> dict[str, Any]:
        self.get_case(case_id)
        self.guard_open_case(case_id)
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO completion_policy (case_id, mode, set_by, set_at, source)"
                " VALUES (?, ?, ?, ?, 'case_explicit')"
                " ON CONFLICT(case_id) DO UPDATE SET"
                "   mode = excluded.mode, set_by = excluded.set_by,"
                "   set_at = excluded.set_at, source = 'case_explicit'",
                (case_id, mode.value, set_by, utc_now()),
            )
        return {"case_id": case_id, "mode": mode.value, "set_by": set_by}

    # ------------------------------------------------- 실행 정리 상태

    def unsettled_runs(self, case_id: str) -> list[dict[str, Any]]:
        """결과를 확정할 수 없는 실행.

        진행 중(`pending`/`assigned`/`running`)이거나 결과가 `unknown` 인 Run이다.
        **이들이 남아 있는 동안은 업무 종료를 확정하지 않는다**(completion-lifecycle
        5절). 인수 결정 자체는 보존하되 종료 기록을 만들지 않는다.
        """
        rows = self.conn.execute(
            "SELECT run_id, status, outcome, purpose, tool_id FROM run"
            " WHERE case_id = ? AND (status != ? OR outcome = ? OR outcome IS NULL)"
            " ORDER BY created_at",
            (case_id, RunStatus.FINISHED.value, RunOutcome.UNKNOWN.value),
        ).fetchall()
        return [dict(r) for r in rows]

    # ----------------------------------------------------- 최종 결과 후보

    def _candidate_snapshot(self, case_id: str) -> dict[str, Any]:
        """지금 시점의 종료 후보 내용. 저장하지 않고 계산만 한다."""
        case = self.get_case(case_id)
        state = self.intent_state(case_id)
        latest = state["latest_intent_version"]
        gate = self.gate_state(case_id)
        criteria = self.current_criteria(case_id)
        unsettled = self.unsettled_runs(case_id)

        unresolved: list[dict[str, Any]] = []
        for crit in criteria:
            if crit["verdict"] != CriterionVerdict.MET.value:
                unresolved.append(
                    {
                        "kind": "criterion",
                        "id": crit["id"],
                        "key": crit["criterion_key"],
                        "verdict": crit["verdict"],
                    }
                )
        for question in state["open_intent_questions"]:
            unresolved.append(
                {"kind": "open_intent_question", "id": question["id"], "verdict": "open"}
            )
        for item in state["unresolved_feedback"]:
            unresolved.append({"kind": "unresolved_feedback", "id": item["id"], "verdict": "open"})

        # **P4-03: 목적마다 기준이 있는가.** 요구된 목적 의무에 기준이 하나도 없으면
        # 그 목적은 확인할 수단 없이 끝난다 — "원인 확정과 수정" 중 원인 쪽 기준이
        # 없으면 수정 기준만으로 완료되던 자리다. 기준이 아니므로 예외 수용 대상도
        # 아니다.
        meaning_block: dict[str, Any] | None = None
        if self.completion_contract(case_id) is not None:
            meaning = self.completion_meaning(case_id)
            meaning_block = meaningmod.snapshot_block(meaning)
            for obligation in meaning["missing"]:
                unresolved.append(
                    {"kind": "objective_without_criteria", "id": obligation, "verdict": "missing"}
                )

        met = sum(1 for c in criteria if c["verdict"] == CriterionVerdict.MET.value)
        payload = {
            "case_id": case_id,
            "case_kind": case["kind"],
            "intent_version_id": latest["id"] if latest else None,
            "intent_agreement_state": state["agreement_state"],
            "gate_verdict": gate["verdict"],
            "criteria": [
                {"id": c["id"], "key": c["criterion_key"], "verdict": c["verdict"]}
                for c in criteria
            ],
            "criteria_total": len(criteria),
            "criteria_met": met,
            "unresolved": unresolved,
            "unsettled_runs": unsettled,
        }
        # **계약이 있는 Case 만 넣는다.** v1 Case 의 후보에 이 키가 생기면 해시가 바뀌어
        # controlled 의 결과 확인이 소급으로 낡는다.
        if meaning_block is not None:
            payload["meaning"] = meaning_block
        payload["snapshot_hash"] = _snapshot_hash(
            json.dumps(payload, sort_keys=True, ensure_ascii=False)
        )
        return payload

    def build_completion_candidate(self, case_id: str) -> tuple[dict[str, Any], bool]:
        """종료 후보를 만든다. 내용이 그대로면 새 후보를 만들지 않는다.

        반환: (후보, 이번에 만들었는지)

        내용이 바뀌면 **새 후보**가 생기고 이전 후보는 `superseded` 가 된다. 이전
        후보에 대한 인수는 새 후보의 인수가 되지 않는다(completion-lifecycle 3절
        "후보가 의미 있게 바뀌면 이전 확인을 새 결과의 인수로 사용하지 않는다").
        """
        # 종료된 Case 는 새 후보를 만들지 않는다. 만들면 인수된 후보를 대체해
        # "무엇을 인수했는가"가 흐려진다.
        self.guard_open_case(case_id)
        snapshot = self._candidate_snapshot(case_id)
        open_row = self.conn.execute(
            "SELECT * FROM completion_candidate WHERE case_id = ? AND state = ?"
            " ORDER BY revision DESC LIMIT 1",
            (case_id, CandidateState.OPEN.value),
        ).fetchone()
        if open_row is not None and open_row["snapshot_hash"] == snapshot["snapshot_hash"]:
            return self.get_completion_candidate(open_row["id"]), False

        now = utc_now()
        row = self.conn.execute(
            "SELECT MAX(revision) AS r FROM completion_candidate WHERE case_id = ?", (case_id,)
        ).fetchone()
        revision = (row["r"] or 0) + 1
        candidate_id = ids.new_id("cand")
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE completion_candidate SET state = ?, superseded_at = ?"
                " WHERE case_id = ? AND state = ?",
                (CandidateState.SUPERSEDED.value, now, case_id, CandidateState.OPEN.value),
            )
            self.conn.execute(
                "INSERT INTO completion_candidate"
                " (id, case_id, revision, intent_version_id, intent_agreement_state,"
                "  gate_verdict, criteria_total, criteria_met, unresolved_json,"
                "  unsettled_runs_json, snapshot_hash, state, created_at, meaning_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    candidate_id,
                    case_id,
                    revision,
                    snapshot["intent_version_id"],
                    snapshot["intent_agreement_state"],
                    snapshot["gate_verdict"],
                    snapshot["criteria_total"],
                    snapshot["criteria_met"],
                    json.dumps(snapshot["unresolved"], ensure_ascii=False),
                    json.dumps(snapshot["unsettled_runs"], ensure_ascii=False),
                    snapshot["snapshot_hash"],
                    CandidateState.OPEN.value,
                    now,
                    (
                        json.dumps(snapshot["meaning"], ensure_ascii=False)
                        if snapshot.get("meaning") is not None
                        else None
                    ),
                ),
            )
            for crit in snapshot["criteria"]:
                self.conn.execute(
                    "INSERT INTO candidate_criterion (candidate_id, criterion_id, verdict)"
                    " VALUES (?, ?, ?)",
                    (candidate_id, crit["id"], crit["verdict"]),
                )
            # 화면이 "무엇을 기다리는가"를 알 수 있도록 Case 상태를 옮긴다.
            # 종료가 아니라 **최종 확인 대기**다.
            self.conn.execute(
                'UPDATE "case" SET status = ?, updated_at = ? WHERE id = ? AND status NOT IN (?, ?)',
                (
                    CaseStatus.WAITING_FINAL_ACCEPTANCE.value,
                    now,
                    case_id,
                    CaseStatus.CLOSED.value,
                    CaseStatus.CANCELLED.value,
                ),
            )
        return self.get_completion_candidate(candidate_id), True

    def get_completion_candidate(self, candidate_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM completion_candidate WHERE id = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"completion candidate not found: {candidate_id}")
        candidate = dict(row)
        candidate["unresolved"] = json.loads(candidate.pop("unresolved_json"))
        candidate["unsettled_runs"] = json.loads(candidate.pop("unsettled_runs_json"))
        # P4-03. 계약이 없는 Case 의 후보는 `None` 이다 — "충족 현황이 비어 있다"가 아니다.
        meaning_raw = candidate.pop("meaning_json", None)
        candidate["meaning"] = json.loads(meaning_raw) if meaning_raw else None
        candidate["criteria"] = [
            dict(r)
            for r in self.conn.execute(
                "SELECT cc.criterion_id, cc.verdict, sc.criterion_key, sc.summary,"
                "       sc.method_summary, sc.relates_to, sc.state"
                " FROM candidate_criterion cc"
                " JOIN success_criterion sc ON sc.id = cc.criterion_id"
                " WHERE cc.candidate_id = ? ORDER BY sc.criterion_key",
                (candidate_id,),
            ).fetchall()
        ]
        candidate["exceptions"] = self.list_exception_decisions(candidate_id)
        candidate["acceptance"] = self.get_final_acceptance(candidate_id)
        return candidate

    def current_completion_candidate(self, case_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id FROM completion_candidate WHERE case_id = ? AND state = ?"
            " ORDER BY revision DESC LIMIT 1",
            (case_id, CandidateState.OPEN.value),
        ).fetchone()
        if row is None:
            return None
        return self.get_completion_candidate(row["id"])

    def list_completion_candidates(self, case_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id FROM completion_candidate WHERE case_id = ? ORDER BY revision",
            (case_id,),
        ).fetchall()
        return [self.get_completion_candidate(r["id"]) for r in rows]

    # --------------------------------------------- 인수·예외·종료 기록

    def get_final_acceptance(self, candidate_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM final_acceptance WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def list_exception_decisions(self, candidate_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM exception_decision WHERE candidate_id = ? ORDER BY decided_at",
            (candidate_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def record_exception_decision(
        self,
        candidate_id: str,
        target_id: str,
        scope_summary: str,
        actor: str,
    ) -> dict[str, Any]:
        """표시된 미충족·미검증을 사람이 수용한다.

        **원래 판정을 바꾸지 않는다.** 수용 시점의 판정을 `original_verdict` 로
        복사해 두고 `criterion_result` 는 건드리지 않는다. '10만 행 통과'로
        표시하지 않는다는 규칙의 구현이다(completion-lifecycle 4절).
        """
        candidate = self.get_completion_candidate(candidate_id)
        self.guard_open_case(candidate["case_id"])
        if candidate["state"] != CandidateState.OPEN.value:
            raise ConflictError(
                f"{AcceptanceRefusal.CANDIDATE_SUPERSEDED.value}:"
                " this candidate was replaced; review the current one"
            )
        # **P3-R4에서 걷어낸 거부.** 여기서는 완료 모드가 자동이면 사람의 예외 수용
        # 까지 거부하고 "사람 확인으로 되돌린 뒤 수용하라"고 답했다. v0.7 에서 자동이
        # **기본**이 되므로 그대로 두면 기본 Case 에서 사람이 예외를 수용할 수 없다 —
        # D-32 와 completion-lifecycle 4절에 어긋난다.
        #
        # 막아야 하는 것은 "자동 정책이 **스스로** 예외를 수용하는 것"이고, 그 검사는
        # `check_acceptance(AUTO_POLICY)` 에 그대로 있다. 두 문장은 다른 규칙이며
        # 여기서 합치면 사람의 결정 경로가 정책 설정에 묶인다.
        criterion = self.get_success_criterion(target_id)
        if criterion["case_id"] != candidate["case_id"]:
            raise ConflictError("exception target belongs to a different case")
        result = self.get_criterion_result(target_id)
        if result["verdict"] == CriterionVerdict.MET.value:
            raise ConflictError(
                f"{AcceptanceRefusal.EXCEPTION_TARGET_NOT_FAILING.value}:"
                " the criterion is already met; there is nothing to accept as an exception"
            )

        decision_id = ids.new_decision_id()
        exception_id = ids.new_id("exc")
        now = utc_now()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO decision (id, case_id, kind, subject_type, subject_id,"
                " subject_revision, actor, decided_at, subject_content_hash)"
                " VALUES (?, ?, ?, 'success_criterion', ?, ?, ?, ?, ?)",
                (
                    decision_id,
                    candidate["case_id"],
                    DecisionKind.EXCEPTION_CLOSURE.value,
                    target_id,
                    candidate["revision"],
                    actor,
                    now,
                    candidate["snapshot_hash"],
                ),
            )
            self.conn.execute(
                "INSERT INTO exception_decision"
                " (id, case_id, candidate_id, decision_id, target_type, target_id,"
                "  original_verdict, scope_summary, actor, decided_at)"
                " VALUES (?, ?, ?, ?, 'criterion', ?, ?, ?, ?, ?)",
                (
                    exception_id,
                    candidate["case_id"],
                    candidate_id,
                    decision_id,
                    target_id,
                    result["verdict"],
                    _summary(scope_summary),
                    actor,
                    now,
                ),
            )
        row = self.conn.execute(
            "SELECT * FROM exception_decision WHERE id = ?", (exception_id,)
        ).fetchone()
        return dict(row)

    def check_acceptance(
        self, candidate_id: str, mode: AcceptanceMode
    ) -> list[AcceptanceRefusal]:
        """이 후보를 인수해도 되는지 확인한다. 거절 사유 목록을 돌려준다.

        **P2-02의 동의 거절, P2-03의 진입 거부와 다른 검사다.** 세 목록을 합치지
        않는다. 여기서 보는 것은 "이 후보를 종료 후보로 확정해도 되는가"뿐이다.
        """
        candidate = self.get_completion_candidate(candidate_id)
        case = self.get_case(candidate["case_id"])
        refusals: list[AcceptanceRefusal] = []

        if case["status"] in (CaseStatus.CLOSED.value, CaseStatus.CANCELLED.value):
            refusals.append(AcceptanceRefusal.CASE_ALREADY_CLOSED)
        if candidate["state"] != CandidateState.OPEN.value:
            refusals.append(AcceptanceRefusal.CANDIDATE_SUPERSEDED)
        else:
            # 그 사이 내용이 바뀌었으면 사용자가 본 후보가 아니다.
            current = self._candidate_snapshot(candidate["case_id"])
            if current["snapshot_hash"] != candidate["snapshot_hash"]:
                refusals.append(AcceptanceRefusal.CANDIDATE_SUPERSEDED)

        # 기능 개발 Case는 최신 의도에 동의가 있어야 한다. 의도 버전이 하나라도
        # 있으면 유형과 무관하게 본다(P2-03의 우회 차단과 같은 기준).
        if candidate["intent_version_id"] is not None:
            if candidate["intent_agreement_state"] != IntentAgreementState.AGREED_CURRENT.value:
                refusals.append(AcceptanceRefusal.INTENT_NOT_AGREED)
            # **기준이 0건이면 인수할 수 없다.** 견줄 기준이 없으면 "미해결 0건"이
            # 되어 아무 것도 확인하지 않은 결과가 조용히 통과한다. 빈 통과를 만드는
            # 대신 거부로 드러낸다(FR-17 "기준별 증거로 판단한다").
            if candidate["criteria_total"] == 0:
                refusals.append(AcceptanceRefusal.NO_SUCCESS_CRITERIA)

        # 남은 항목을 **종류별로** 구별해 사유를 붙인다. 미해결 피드백을
        # "기준 미충족"이라고 적으면 사람이 엉뚱한 곳을 고치게 된다.
        excepted = {e["target_id"] for e in candidate["exceptions"]}
        by_kind = {
            "criterion": AcceptanceRefusal.UNRESOLVED_CRITERIA,
            "open_intent_question": AcceptanceRefusal.OPEN_INTENT_QUESTIONS,
            "unresolved_feedback": AcceptanceRefusal.UNRESOLVED_FEEDBACK,
            # P4-03. 기준이 없는 목적은 **사람도 인수할 수 없다.** 예외는 기준에만
            # 붙으므로 여기서 걸러 낼 경로가 없고, 그것이 의도한 모양이다.
            "objective_without_criteria": AcceptanceRefusal.OBJECTIVE_WITHOUT_CRITERIA,
        }
        for item in candidate["unresolved"]:
            if item["kind"] == "criterion" and item["id"] in excepted:
                continue  # 사람이 예외로 수용한 기준은 남은 항목이 아니다
            reason = by_kind.get(item["kind"], AcceptanceRefusal.UNRESOLVED_CRITERIA)
            if reason not in refusals:
                refusals.append(reason)

        # 미정리 실행은 인수를 막지 않는다 — 인수는 기록하고 **종료 확정만** 보류한다.
        # 다만 자동 완료는 미정리 실행이 있으면 아예 완료하지 않는다.
        if mode is AcceptanceMode.AUTO_POLICY and candidate["unsettled_runs"]:
            refusals.append(AcceptanceRefusal.UNSETTLED_RUNS_PRESENT)
        # 자동 모드는 예외를 스스로 수용하지 않는다. 예외가 걸린 후보는 사람만 닫는다.
        if mode is AcceptanceMode.AUTO_POLICY and candidate["exceptions"]:
            refusals.append(AcceptanceRefusal.AUTO_POLICY_CANNOT_ACCEPT_EXCEPTION)
        # P4-03. 정리되지 않은 실험의 임시 변경이 제품 결과에 섞였을 수 있다. 자동
        # 완료만 막는다 — 사람은 후보에 드러난 잔여를 보고 판단한다(미정리 실행과 같다).
        if mode is AcceptanceMode.AUTO_POLICY and (candidate.get("meaning") or {}).get(
            "residue_blocks_auto_completion"
        ):
            refusals.append(AcceptanceRefusal.EXPERIMENT_RESIDUE_UNRESOLVED)

        # --- P3-R4: controlled 의 확인 순서 --------------------------------
        #
        # D-65 의 순서에서 **종료 직전의 선행 조건**이다. 확인한 후보의 내용이
        # 달라졌으면 이전 확인을 새 후보에 쓰지 않고, 같은 내용의 재전송에는 재확인을
        # 요구하지 않는다 — 그 구별이 `subject_hash` 비교에 있다.
        refusals.extend(self._controlled_closure_refusals(candidate))

        # 확인되지 않은 누적 변경이 남은 채로 종료하지 않는다(D-60). 미확인 변경은
        # "이 결과가 무엇에 대한 것인가"를 흔드는 상태이며, 그대로 닫으면 사용자가
        # 위임하지 않은 의미의 결과를 완료로 받는다.
        if self.pending_material_deltas(candidate["case_id"]):
            refusals.append(AcceptanceRefusal.MATERIAL_DELTA_UNCONFIRMED)
        return refusals

    def _controlled_closure_refusals(
        self, candidate: dict[str, Any]
    ) -> list[AcceptanceRefusal]:
        """controlled 의 확인 지점이 이 후보의 종료를 허용하는가(P3-R4·D-65).

        세 가지를 나눠 보는 이유는 사람이 해야 할 일이 다르기 때문이다.

            시작 확인이 없다      시작 범위를 확인한다
            결과 확인이 없다      이 후보를 확인한다
            확인이 낡았다         바뀐 후보를 다시 본다

        **같은 내용의 재전송은 셋 중 어느 것도 아니다.** 후보 해시가 같으면 이전
        확인이 그대로 유효하며, 그 판단을 `subject_hash` 비교 하나로 한다.
        """
        state = self.checkpoint_state(candidate["case_id"])
        if not state["required"]:
            return []
        refusals: list[AcceptanceRefusal] = []
        if not state["start_confirmed"]:
            refusals.append(AcceptanceRefusal.CONTROLLED_START_NOT_CONFIRMED)
        if not state["result_confirmed"]:
            refusals.append(AcceptanceRefusal.CONTROLLED_RESULT_NOT_CONFIRMED)
        elif state["result_subject_hash"] != candidate["snapshot_hash"]:
            # 확인한 대상이 지금 후보가 아니다. **확인 기록은 남는다** — 무엇을 보고
            # 확인했는지가 사라지면 나중에 그 결정을 설명할 수 없다(FR-23).
            refusals.append(AcceptanceRefusal.CONTROLLED_CONFIRMATION_STALE)
        return refusals

    def record_final_acceptance(
        self,
        candidate_id: str,
        actor: str,
        mode: AcceptanceMode,
        statement_artifact_id: str | None = None,
    ) -> dict[str, Any]:
        """최종 인수를 기록하고, 가능하면 종료까지 확정한다.

        **인수와 종료는 다른 기록이다.** 결과를 확정할 수 없는 실행이 남아 있으면
        인수는 남기고 `closure_record` 는 만들지 않는다. 화면에는
        `인수됨 · 실행 상태 확인 필요` 로 두 상태를 함께 보인다
        (completion-lifecycle 5절).
        """
        candidate = self.get_completion_candidate(candidate_id)
        if candidate["acceptance"] is not None:
            return candidate["acceptance"]
        refusals = self.check_acceptance(candidate_id, mode)
        if refusals:
            raise AcceptanceRefused(refusals)

        decision_id = ids.new_decision_id()
        acceptance_id = ids.new_id("accept")
        now = utc_now()
        exceptions = candidate["exceptions"]
        unsettled = candidate["unsettled_runs"]
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO decision (id, case_id, kind, subject_type, subject_id,"
                " subject_revision, actor, decided_at, evidence_ref, subject_content_hash)"
                " VALUES (?, ?, ?, 'completion_candidate', ?, ?, ?, ?, ?, ?)",
                (
                    decision_id,
                    candidate["case_id"],
                    DecisionKind.FINAL_ACCEPTANCE.value,
                    candidate_id,
                    candidate["revision"],
                    actor,
                    now,
                    statement_artifact_id,
                    candidate["snapshot_hash"],
                ),
            )
            self.conn.execute(
                "INSERT INTO final_acceptance"
                " (id, case_id, candidate_id, decision_id, mode, actor,"
                "  statement_artifact_id, accepted_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    acceptance_id,
                    candidate["case_id"],
                    candidate_id,
                    decision_id,
                    mode.value,
                    actor,
                    statement_artifact_id,
                    now,
                ),
            )
            if not unsettled:
                kind = (
                    ClosureKind.CLOSED_WITH_EXCEPTIONS
                    if exceptions
                    else ClosureKind.COMPLETED
                )
                self.conn.execute(
                    "INSERT INTO closure_record"
                    " (id, case_id, candidate_id, final_acceptance_id, closure_kind,"
                    "  exception_count, confirmed_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        ids.new_id("closure"),
                        candidate["case_id"],
                        candidate_id,
                        acceptance_id,
                        kind.value,
                        len(exceptions),
                        now,
                    ),
                )
                self.conn.execute(
                    'UPDATE "case" SET status = ?, updated_at = ? WHERE id = ?',
                    (CaseStatus.CLOSED.value, now, candidate["case_id"]),
                )
        return self.get_final_acceptance(candidate_id)

    def get_closure(self, case_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM closure_record WHERE case_id = ?", (case_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def auto_complete_if_allowed(self, case_id: str) -> dict[str, Any]:
        """자동 완료 정책을 적용한다(D-31).

        **자동 완료를 사람 인수로 적지 않는다.** `mode=auto_policy` 이고 actor 는
        정책 식별자다. 자동 모드는 미충족·미검증을 스스로 예외 수용하지 않으며,
        조건을 못 갖추면 그대로 사람 확인 대기로 남는다.

        **판정 자체는 모드에 따라 달라지지 않는다** — 같은 후보를 기본 모드로 봐도
        기준 충족 여부는 같다(completion-lifecycle 9절 1).
        """
        mode = self.completion_mode(case_id)
        candidate, _ = self.build_completion_candidate(case_id)
        if mode is not CompletionMode.AUTO_ON_CONDITIONS:
            return {
                "applied": False,
                "reason": "policy_is_human_acceptance",
                "candidate": candidate,
            }
        refusals = self.check_acceptance(candidate["id"], AcceptanceMode.AUTO_POLICY)
        if refusals:
            return {
                "applied": False,
                "reason": "conditions_not_met",
                "refusals": [r.value for r in refusals],
                "candidate": candidate,
            }
        acceptance = self.record_final_acceptance(
            candidate["id"], actor="policy:auto_on_conditions", mode=AcceptanceMode.AUTO_POLICY
        )
        return {
            "applied": True,
            "acceptance": acceptance,
            "candidate": self.get_completion_candidate(candidate["id"]),
        }

    def maybe_auto_complete(self, case_id: str) -> dict[str, Any] | None:
        """조건이 갖춰졌으면 **시스템이** 자동 완료한다(P3-R4·D-31).

        `auto_complete_if_allowed()` 와 다른 점 하나: **후보를 먼저 만들지 않는다.**
        저쪽은 사람이 "지금 완료할 수 있는가"를 물은 것이므로 못 하는 이유를 보여
        주려고 후보를 만든다. 이쪽은 시스템이 실행 결과·기준 판정마다 부르는 자리라,
        조건이 갖춰지지 않았는데 후보를 만들면 아직 진행 중인 Case 가 매번
        `waiting_final_acceptance` 로 표시된다.

        그래서 **저장하지 않는 스냅샷으로 먼저 본다.** 남은 항목이나 결과를 확정할
        수 없는 실행이 있으면 아무 것도 하지 않는다.

        조용히 실패하지 않는다 — 판단은 `check_acceptance` 가 하고 여기서 예외를
        삼키지 않는다. 자동 완료가 실패하면 그 원인은 드러나야 한다.
        """
        if self.case_is_closed(case_id):
            return None
        if self.completion_mode(case_id) is not CompletionMode.AUTO_ON_CONDITIONS:
            return None
        snapshot = self._candidate_snapshot(case_id)
        if snapshot["unresolved"] or snapshot["unsettled_runs"]:
            return None
        if (snapshot.get("meaning") or {}).get("residue_blocks_auto_completion"):
            # 실험 잔여가 있으면 후보를 만들지 않는다. 만들면 아직 결과를 확정할 수
            # 없는 Case 가 `waiting_final_acceptance` 로 보인다.
            return None
        if snapshot["criteria_total"] == 0:
            # 견줄 기준이 없으면 "미해결 0건"이 되어 아무 것도 확인하지 않은 결과가
            # 조용히 통과한다. `check_acceptance` 가 같은 규칙을 갖고 있지만, 후보를
            # 만들기 전에 여기서도 멈춘다 — 빈 통과를 만들지 않는다(FR-17).
            return None
        if self.pending_material_deltas(case_id):
            return None
        return self.auto_complete_if_allowed(case_id)

    # ------------------------------------------------- 종료 후 새 Case

    def case_is_closed(self, case_id: str) -> bool:
        case = self.get_case(case_id)
        return case["status"] in (CaseStatus.CLOSED.value, CaseStatus.CANCELLED.value)

    def guard_open_case(self, case_id: str) -> None:
        """종료된 Case를 바꾸려는 시도를 막는다.

        완료 후 수정은 기존 Case 재개가 아니라 **연결된 새 Case** 다(D-33).
        되살리는 API 를 만들지 않는 편이 "완료 기록을 유지한다"를 지키기 쉽다.
        """
        if self.case_is_closed(case_id):
            raise ConflictError(
                f"{AcceptanceRefusal.CASE_ALREADY_CLOSED.value}: this case is closed;"
                " create a linked follow-up case instead of changing the closed one"
            )

    def create_successor_case(
        self,
        from_case_id: str,
        title: str,
        kind: CaseKind | None = None,
        reason_summary: str = "",
        profile: CaseProfile | None = None,
    ) -> dict[str, Any]:
        """종료된 업무의 후속 수정을 위한 새 Case를 만들고 출처로 연결한다.

        **이전 동의를 승계하지 않는다.** 새 Case는 의도 버전이 0개로 시작하므로
        기능 개발이면 새 초안·새 동의·새 게이트를 다시 거친다(D-33,
        completion-lifecycle 6절 "이전 인수나 의도 동의를 포괄 허용으로 쓰지 않는다").

        **P3-R1: Profile·정책도 승계하지 않는다.** 새 Case 의 Autonomy 는 새 Case 의
        기본값이고 Profile 은 요청이 지정하거나 `kind` 에서 유도한다. 원래 Case 가
        controlled 였다는 사실이 새 Case 의 확인 기록을 만들지 않는다.
        """
        origin = self.get_case(from_case_id)
        new_case = self.create_case(origin["project_id"], title, kind, profile)
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO case_relation"
                " (id, from_case_id, to_case_id, relation, reason_summary, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    ids.new_id("rel"),
                    from_case_id,
                    new_case["id"],
                    CaseRelationKind.FOLLOW_UP_CHANGE.value,
                    _summary(reason_summary),
                    utc_now(),
                ),
            )
        return new_case

    def list_case_relations(self, case_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM case_relation WHERE from_case_id = ? OR to_case_id = ?"
            " ORDER BY created_at",
            (case_id, case_id),
        ).fetchall()
        return [dict(r) for r in rows]

    # ----------------------------------------------------------- 결과 화면

    # ------------------------------------------------------------ P3-01 수준

    def _supersede_sizing(self, case_id: str, now: str) -> None:
        self.conn.execute(
            "UPDATE sizing_assessment SET state = ?, superseded_at = ?"
            " WHERE case_id = ? AND state = ?",
            (SizingState.SUPERSEDED.value, now, case_id, SizingState.CURRENT.value),
        )

    def _insert_sizing(
        self,
        case_id: str,
        intent_version_id: str | None,
        source: SizingSource,
        recommended_level: WorkLevel,
        axes: list[dict[str, Any]],
        actor: str,
        reason_summary: str,
        residual_risk_summary: str,
        adjusted_from: str | None = None,
    ) -> str:
        """수준 판단 행 하나를 만든다. 이전 판단은 대체됨으로 남긴다(지우지 않는다).

        효과 수준은 `controller.sizing` 이 정한다 — **문서가 제안한 수준이 도출값보다
        낮으면 낮은 쪽을 쓰지 않는다.** 두 값이 모두 이 행에 남아 조용한 하향이 드러난다.
        사람의 명시적 조정만 도출값 아래로 갈 수 있고 그때 이유와 남는 위험이 남는다.
        """
        outcome = sizingmod.assess(axes, recommended_level)
        row = self.conn.execute(
            "SELECT MAX(revision) AS r FROM sizing_assessment WHERE case_id = ?", (case_id,)
        ).fetchone()
        revision = (row["r"] or 0) + 1
        assessment_id = ids.new_id("sizing")
        now = utc_now()
        level = outcome.effective_level
        if source is SizingSource.HUMAN_ADJUSTMENT:
            # 사람의 조정은 도출값 아래로도 갈 수 있다. 그것이 조정권이다(FR-05).
            # 대신 이유와 남는 위험이 필수이고(호출부가 검사한다) 기록에 남는다.
            level = recommended_level
        self._supersede_sizing(case_id, now)
        self.conn.execute(
            "INSERT INTO sizing_assessment (id, case_id, revision, intent_version_id, source,"
            " recommended_level, derived_level, level, adjusted_from, evidence_gap,"
            " reason_summary, residual_risk_summary, actor, state, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                assessment_id,
                case_id,
                revision,
                intent_version_id,
                source.value,
                recommended_level.value,
                outcome.derived_level.value,
                level.value,
                adjusted_from,
                1 if outcome.evidence_gap else 0,
                _summary(reason_summary),
                _summary(residual_risk_summary),
                actor,
                SizingState.CURRENT.value,
                now,
            ),
        )
        for axis in axes:
            self.conn.execute(
                "INSERT INTO sizing_axis (assessment_id, axis, weight, judgement_summary,"
                " unconfirmed_summary) VALUES (?, ?, ?, ?, ?)",
                (
                    assessment_id,
                    SizingAxis(axis["axis"]).value,
                    AxisWeight(axis["weight"]).value,
                    _summary(axis.get("judgement_summary") or ""),
                    _summary(axis.get("unconfirmed_summary") or ""),
                ),
            )
        return assessment_id

    def apply_sizing_report(
        self, intent_version_id: str, sizing: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """의도 구조 보고에 실려 온 수준 판단을 반영한다.

        `None` 이면 아무 것도 만들지 않는다. **없는 판단을 간소로 채우지 않는다** —
        v1·v2 문서와 수준을 적지 않은 초안은 `sizing_not_decided` 로 남아야 한다.

        작성 주체는 의도 버전의 `authoring_mode` 에서 가져온다. AI가 쓴 초안의 판단을
        사람 판단으로 적지 않기 위해서다(FR-04).
        """
        if not sizing:
            return None
        intent = self.get_intent_version(intent_version_id)
        ai_drafted = intent.get("authoring_mode") == AuthoringMode.AI_DRAFTED.value
        source = (
            SizingSource.AI_RECOMMENDATION if ai_drafted else SizingSource.HUMAN_ASSESSMENT
        )
        actor = (intent.get("author_run_id") or "ai-intent-draft") if ai_drafted else "human-draft"
        axes = list(sizing.get("axes") or [])
        with transaction(self.conn):
            assessment_id = self._insert_sizing(
                case_id=intent["case_id"],
                intent_version_id=intent_version_id,
                source=source,
                recommended_level=WorkLevel(sizing["recommended_level"]),
                axes=axes,
                actor=actor,
                reason_summary="의도 초안에 적힌 수준 판단",
                residual_risk_summary="",
            )
        return self.get_sizing_assessment(assessment_id)

    def get_sizing_assessment(self, assessment_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM sizing_assessment WHERE id = ?", (assessment_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"sizing assessment not found: {assessment_id}")
        out = dict(row)
        out["axes"] = [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM sizing_axis WHERE assessment_id = ? ORDER BY axis",
                (assessment_id,),
            ).fetchall()
        ]
        out["evidence_gap"] = bool(out["evidence_gap"])
        return out

    def current_sizing(self, case_id: str) -> dict[str, Any] | None:
        """지금 적용되는 수준 판단. 없으면 `None` 이며 그것은 **미결정**이다."""
        row = self.conn.execute(
            "SELECT id FROM sizing_assessment WHERE case_id = ? AND state = ?",
            (case_id, SizingState.CURRENT.value),
        ).fetchone()
        return self.get_sizing_assessment(row["id"]) if row else None

    def list_sizing_assessments(self, case_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id FROM sizing_assessment WHERE case_id = ? ORDER BY revision DESC",
            (case_id,),
        ).fetchall()
        return [self.get_sizing_assessment(r["id"]) for r in rows]

    def current_level(self, case_id: str) -> WorkLevel | None:
        current = self.current_sizing(case_id)
        return WorkLevel(current["level"]) if current else None

    def adjust_sizing(
        self,
        case_id: str,
        level: WorkLevel,
        actor: str,
        reason_summary: str,
        residual_risk_summary: str,
    ) -> dict[str, Any]:
        """사람이 수준을 상향·하향한다.

        **이유와 남는 위험이 필수다.** sizing-and-review-ux 1절: "조정 이유와 남는
        위험을 기록하며, 상세도 조정이 의도 동의·합의한 검증·권한을 해제하지 않게
        한다." 그래서 이 메서드는 검토 모드·성공 기준·의도 동의를 **건드리지 않는다.**
        수준은 준비 깊이의 결정이고 의도의 내용이 아니므로 새 의도 버전도 만들지 않는다.

        기존 판단이 없으면 거부한다. 축별 근거 없이 수준만 정하는 경로를 만들면
        `근거 / 판단 / 미확인 / 영향`이 사라진다.
        """
        self.get_case(case_id)
        self.guard_open_case(case_id)
        if not str(reason_summary or "").strip():
            raise ConflictError("a sizing adjustment needs a reason")
        if not str(residual_risk_summary or "").strip():
            raise ConflictError("a sizing adjustment needs the remaining risk it leaves")
        current = self.current_sizing(case_id)
        if current is None:
            raise ConflictError(
                "there is no sizing assessment to adjust;"
                " the intent draft must carry the per-axis judgement first"
            )
        axes = [
            {
                "axis": a["axis"],
                "weight": a["weight"],
                "judgement_summary": a["judgement_summary"],
                "unconfirmed_summary": a["unconfirmed_summary"],
            }
            for a in current["axes"]
        ]
        with transaction(self.conn):
            assessment_id = self._insert_sizing(
                case_id=case_id,
                intent_version_id=current["intent_version_id"],
                source=SizingSource.HUMAN_ADJUSTMENT,
                recommended_level=WorkLevel(level),
                axes=axes,
                actor=actor,
                reason_summary=reason_summary,
                residual_risk_summary=residual_risk_summary,
                adjusted_from=current["level"],
            )
        return self.get_sizing_assessment(assessment_id)

    # -------------------------------------------------- P3-01 설계·개발계획

    #: 단계별 원문 종류. 설계 문서를 계획으로 등록하는 실수를 막는다.
    STAGE_ARTIFACT_KIND = {
        PreparationStage.DESIGN: ArtifactKind.DESIGN,
        PreparationStage.PLAN: ArtifactKind.DEV_PLAN,
        # P3-R4. 결합 기록은 **계획 산출물 종류를 그대로 쓴다.** 새 `ArtifactKind`
        # 를 만들지 않는 이유는 그 종류가 Runner 의 원문 보관·조회 경로에 쓰이고,
        # 값을 늘리면 옛 Runner 가 모르는 종류를 받기 때문이다. 결합 기록이 계획의
        # 자리를 대신한다는 사실은 `stage` 가 말한다.
        PreparationStage.COMBINED: ArtifactKind.DEV_PLAN,
    }

    def create_preparation_artifact(
        self,
        case_id: str,
        stage: PreparationStage,
        artifact_id: str,
        artifact_rev: int,
        level: WorkLevel,
        authoring_mode: AuthoringMode = AuthoringMode.AI_DRAFTED,
        author_run_id: str | None = None,
        summary: str = "",
    ) -> dict[str, Any]:
        """준비 산출물을 등록한다.

        **어느 의도 버전 위에 세웠는지**를 지금의 최신 의도 버전으로 고정한다.
        나중에 새 의도 버전이 생기면 이 산출물은 오래된 것이 되고 그 검토도
        재사용되지 않는다 — 오래된 승인을 막는 지점이 여기다(FR-23).

        계획은 **현재 설계 위에** 세운다. 설계가 없으면 거부한다. 의존 관계가
        `의도 → 설계 → 개발계획` 이므로 설계 없는 계획은 무엇을 구현할 계획인지
        말할 수 없다(intent-artifacts 2절).
        """
        stage = PreparationStage(stage)
        self.get_case(case_id)
        self.guard_open_case(case_id)
        ref = self.get_artifact_ref(artifact_id, artifact_rev)
        expected = self.STAGE_ARTIFACT_KIND[stage]
        if ref["kind"] != expected.value:
            raise ConflictError(f"artifact kind {ref['kind']} is not a {expected.value} artifact")
        latest = self.latest_intent_version(case_id)
        if latest is None:
            raise ConflictError("a preparation artifact needs an intent version to build on")

        based_on_design_id: str | None = None
        if stage is PreparationStage.PLAN:
            design = self.current_preparation(case_id, PreparationStage.DESIGN)
            if design is None:
                raise ConflictError("a development plan needs a current design to build on")
            based_on_design_id = design["id"]
        if stage is PreparationStage.COMBINED:
            # **결합 기록은 설계를 선행 조건으로 받지 않는다.** 그것이 Fast Lane 이
            # 줄이는 것이고(D-60), 대신 Fast Lane 조건 자체가 선행 조건이 된다 —
            # 조건이 아니면 진입 검사가 `fast_lane_left_needs_preparation` 으로
            # 거부한다. 여기서 막지 않는 이유는 **기록을 남기는 것은 언제나 허용**
            # 하기 때문이다. 막는 것은 그 기록으로 실행을 여는 일이다.
            pass

        row = self.conn.execute(
            "SELECT MAX(revision) AS r FROM preparation_artifact WHERE case_id = ? AND stage = ?",
            (case_id, stage.value),
        ).fetchone()
        revision = (row["r"] or 0) + 1
        prep_id = ids.new_id("prep")
        now = utc_now()
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE preparation_artifact SET state = ?, superseded_at = ?"
                " WHERE case_id = ? AND stage = ? AND state = ?",
                (
                    PreparationState.SUPERSEDED.value,
                    now,
                    case_id,
                    stage.value,
                    PreparationState.CURRENT.value,
                ),
            )
            self.conn.execute(
                "INSERT INTO preparation_artifact (id, case_id, stage, revision, artifact_id,"
                " artifact_rev, intent_version_id, based_on_design_id, level, authoring_mode,"
                " author_run_id, summary, state, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    prep_id,
                    case_id,
                    stage.value,
                    revision,
                    artifact_id,
                    artifact_rev,
                    latest["id"],
                    based_on_design_id,
                    WorkLevel(level).value,
                    AuthoringMode(authoring_mode).value,
                    author_run_id,
                    _summary(summary or f"{stage.value} v{revision}"),
                    PreparationState.CURRENT.value,
                    now,
                ),
            )
            if stage is PreparationStage.DESIGN:
                # 설계가 바뀌면 그 위에 세운 계획은 더 이상 현재 설계의 계획이 아니다.
                # 계획 행을 지우지 않고 대체됨으로 남긴다 — 무엇이 있었는지는 기록이다.
                self.conn.execute(
                    "UPDATE preparation_artifact SET state = ?, superseded_at = ?"
                    " WHERE case_id = ? AND stage = ? AND state = ?",
                    (
                        PreparationState.SUPERSEDED.value,
                        now,
                        case_id,
                        PreparationStage.PLAN.value,
                        PreparationState.CURRENT.value,
                    ),
                )
        return self.get_preparation_artifact(prep_id)

    def get_preparation_artifact(self, prep_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM preparation_artifact WHERE id = ?", (prep_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"preparation artifact not found: {prep_id}")
        out = dict(row)
        sections = [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM preparation_section WHERE preparation_id = ?", (prep_id,)
            ).fetchall()
        ]
        order = {s: i for i, s in enumerate(prep_doc.SECTION_ORDER[PreparationStage(out["stage"])])}
        sections.sort(key=lambda r: order.get(r["section"], 99))
        required_now = self.effective_required_sections(prep_id)
        for section in sections:
            # 보고 시점의 필수 여부는 기록으로 남기고, 화면과 진입 검사가 보는 것은
            # **지금** 요구되는지다. 사람이 수준을 올리면 여기가 함께 바뀐다.
            section["required_at_report"] = bool(section["required"])
            section["required"] = section["section"] in required_now
            section["label"] = prep_doc.SECTION_LABEL.get(section["section"], section["section"])
        out["sections"] = sections
        ref = self.get_artifact_ref(out["artifact_id"], out["artifact_rev"])
        out["availability"] = ref["availability"]
        out["content_hash"] = ref["content_hash"]
        out["owner_runner_id"] = ref["owner_runner_id"]
        out["review"] = self.get_stage_review(prep_id)
        out["missing_required_sections"] = self.missing_required_sections(prep_id)
        return out

    def list_preparation_artifacts(
        self, case_id: str, stage: PreparationStage | None = None
    ) -> list[dict[str, Any]]:
        """단계별 목록. **설계와 계획은 각각 조회된다**(intent-artifacts 2절)."""
        sql = "SELECT id FROM preparation_artifact WHERE case_id = ?"
        args: list[Any] = [case_id]
        if stage is not None:
            sql += " AND stage = ?"
            args.append(PreparationStage(stage).value)
        rows = self.conn.execute(sql + " ORDER BY stage, revision DESC", args).fetchall()
        return [self.get_preparation_artifact(r["id"]) for r in rows]

    def current_preparation(self, case_id: str, stage: PreparationStage) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id FROM preparation_artifact WHERE case_id = ? AND stage = ? AND state = ?",
            (case_id, PreparationStage(stage).value, PreparationState.CURRENT.value),
        ).fetchone()
        return self.get_preparation_artifact(row["id"]) if row else None

    def apply_preparation_structure(
        self,
        prep_id: str,
        sections: Iterable[dict[str, Any]],
        questions: Iterable[dict[str, Any]],
        tasks: Iterable[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Runner가 계산한 산출물 구조를 반영한다.

        단계의 항목이 모두 와야 한다. 하나라도 빠지면 거부한다 — 빠진 항목을
        여기서 만들어 채우면 필수 항목 검사가 통과해 버린다.

        이 산출물이 낳은 미정 질문도 함께 들어온다. 질문 표에 `raised_in_stage` 를
        남겨 의도 단계에서 나온 질문과 구별한다.

        **P3-02:** 개발계획이 Task 를 정의했으면 여기서 작업 그래프 리비전이
        태어난다. 그래프를 계획의 **검토 뒤**가 아니라 구조 보고 시점에 만드는
        이유는, 사람이 검토할 때 무엇을 어떤 순서로 만들 계획인지가 화면에 보여야
        하기 때문이다. 검토는 별개 기록으로 남고 진입 검사가 따로 확인한다 —
        그래프가 있다는 사실이 계획 검토를 대신하지 않는다.
        """
        prep = self.get_preparation_artifact(prep_id)
        stage = PreparationStage(prep["stage"])
        level = WorkLevel(prep["level"])
        required = prep_doc.required_sections(stage, level)
        rows = list(sections)
        given = {r["section"] for r in rows}
        expected = set(prep_doc.SECTION_ORDER[stage])
        if given != expected:
            missing = sorted(expected - given)
            extra = sorted(given - expected)
            raise ConflictError(
                f"{stage.value} structure must carry all sections;"
                f" missing={missing} extra={extra}"
            )
        now = utc_now()
        # `questions` 는 Iterable 이라 두 번 돌 수 없다. 아래에서 참조를 다시
        # 훑어야 하므로 여기서 고정한다.
        question_rows = list(questions)
        with transaction(self.conn):
            for row in rows:
                self.conn.execute(
                    "INSERT INTO preparation_section"
                    " (preparation_id, section, state, origin, required)"
                    " VALUES (?, ?, ?, ?, ?)"
                    " ON CONFLICT(preparation_id, section) DO UPDATE SET"
                    "   state = excluded.state, origin = excluded.origin,"
                    "   required = excluded.required",
                    (
                        prep_id,
                        str(row["section"]),
                        ConfirmationState(row["state"]).value,
                        ContentOrigin(row["origin"]).value,
                        # 필수 여부는 **제어부가 수준에서 정한다.** 문서가 스스로
                        # "이건 필수가 아니다"라고 주장해 검사를 벗어나지 못하게 한다.
                        1 if row["section"] in required else 0,
                    ),
                )
            for question in question_rows:
                self.conn.execute(
                    "INSERT INTO intent_question"
                    " (id, case_id, intent_version_id, question_key, summary, decide_at,"
                    "  state, created_at, raised_in_stage, preparation_id)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(intent_version_id, question_key) DO UPDATE SET"
                    "   summary = excluded.summary, decide_at = excluded.decide_at,"
                    "   raised_in_stage = excluded.raised_in_stage,"
                    "   preparation_id = excluded.preparation_id",
                    (
                        ids.new_question_id(),
                        prep["case_id"],
                        prep["intent_version_id"],
                        f"{stage.value}:{question['key']}",
                        _summary(question["summary"]),
                        DecideAt(question["decide_at"]).value,
                        QuestionState.OPEN.value,
                        now,
                        stage.value,
                        prep_id,
                    ),
                )

        # 질문이 **무엇을 막는다고 적혀 있는지**를 해석하지 않고 보관한다.
        # 설계 단계의 질문은 계획이 정의할 Task 를 가리키는데, 그 Task 는 질문이
        # 제기되는 시점에 아직 없다. 해석은 그래프를 만들 때 한다.
        for question in question_rows:
            row = self.conn.execute(
                "SELECT id FROM intent_question WHERE intent_version_id = ? AND question_key = ?",
                (prep["intent_version_id"], f"{stage.value}:{question['key']}"),
            ).fetchone()
            if row is None:
                continue
            # **더하지 않고 바꾼다.** 같은 질문을 다시 보고하면 이번 원문이 적은
            # 것이 그 질문의 차단 관계다. 쌓아 두면 없어진 Task 를 가리키는 옛
            # 참조가 살아남아 그 질문이 영원히 전부 막는다.
            #
            # 사람이 고쳐 둔 연결도 이때 대체된다. 새 산출물은 새 대상이고,
            # 옛 산출물에 대고 고친 연결을 새 계획에 그대로 옮기면 그것이야말로
            # "무효 전제의 결과를 확인 없이 채택"하는 것이다(FR-07).
            self.conn.execute(
                "DELETE FROM question_block_ref WHERE question_id = ?", (row["id"],)
            )
            self.record_question_block_refs(row["id"], question.get("blocks") or [])

        # 개발계획이 Task 를 정의했으면 작업 그래프 리비전이 태어난다.
        # **Task 0건이면 그래프를 만들지 않는다** — 빈 그래프를 만들어 두면
        # `work_graph_missing` 과 "Task 가 전부 취소된 그래프"를 구별할 수 없다.
        task_rows = list(tasks or [])
        if stage in (PreparationStage.PLAN, PreparationStage.COMBINED) and task_rows:
            self.create_work_graph_revision(
                case_id=prep["case_id"],
                plan_preparation_id=prep_id,
                tasks=task_rows,
                source=WorkGraphSource.PLAN_ARTIFACT,
                reason_summary=f"{stage.value} v{prep['revision']} 이 정의한 작업",
                actor=self.PLAN_GRAPH_ACTOR,
            )
        # **자동 진행 조건이 갖춰진 순간 기록한다**(P3-R4). 구조 보고가 필수 항목을
        # 채우는 시점이 그 순간이고, 사람이 버튼을 눌러야 기록된다면 "자동 진행"이
        # 아니다(D-16 "설계·계획의 사람 검토는 선택 사항").
        #
        # **생략이 아니다.** `record_auto_proceed()` 의 조건(산출물 존재·필수 항목·
        # 원문 가용)은 그대로이며, 못 갖추면 `awaiting_auto_conditions` 로 남는다.
        # 사람 검토로 설정된 단계에서는 아무 것도 하지 않는다.
        self._record_auto_proceed_if_ready(prep["case_id"], stage, prep_id)
        return self.get_preparation_artifact(prep_id)

    def _record_auto_proceed_if_ready(
        self, case_id: str, stage: PreparationStage, prep_id: str
    ) -> None:
        """조건이 갖춰졌으면 자동 진행을 기록한다. 아니면 조용히 둔다.

        **사람 승인으로 적지 않는다.** `record_auto_proceed()` 가 `decision` 행을
        만들지 않고 actor 를 정책 식별자로 두는 계약을 그대로 쓴다.
        """
        if self.stage_review_mode(case_id, stage) is not ReviewMode.AUTO_PROCEED:
            return
        try:
            self.record_auto_proceed(case_id, stage, prep_id)
        except ConflictError:
            # 필수 항목이 미정이거나 원문을 읽을 수 없다. 그것이 정상 상태이며
            # 화면이 `awaiting_auto_conditions` 로 보인다. 조건을 만들어 주지 않는다.
            return

    def effective_required_sections(self, prep_id: str) -> frozenset[str]:
        """이 산출물에 **지금** 요구되는 항목.

        **산출물이 작성된 시점의 수준이 아니라 Case 의 현재 수준으로 정한다.**
        사람이 수준을 올리면 이미 있는 산출물도 부족해져야 한다 — 그렇지 않으면
        조정이 겉치레가 되고, 얕게 쓴 산출물로 "준비 완료"가 된다
        (sizing-and-review-ux 1·3절: 조정의 영향을 받는 산출물을 보여 준다).
        라이브 검증에서 실제로 이 구멍이 드러났다.

        수준 판단이 없으면(새 의도 버전이 판단을 대체한 직후 등) 산출물이 작성된
        시점의 수준을 쓴다. 그 상태로는 기능 구현이 `sizing_not_decided` 로 막히므로
        여기서 판단을 지어낼 필요가 없다.
        """
        row = self.conn.execute(
            "SELECT case_id, stage, level FROM preparation_artifact WHERE id = ?", (prep_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"preparation artifact not found: {prep_id}")
        level = self.current_level(row["case_id"]) or WorkLevel(row["level"])
        return prep_doc.required_sections(PreparationStage(row["stage"]), level)

    def missing_required_sections(self, prep_id: str) -> list[str]:
        """지금 요구되는데 미정으로 비어 있는 항목.

        **구조 보고가 아직 없으면 모든 필수 항목이 빠진 것으로 본다.** 보고되지
        않은 것을 채워진 것으로 읽으면 빈 산출물이 선행 조건을 통과한다.
        """
        required = self.effective_required_sections(prep_id)
        reported = {
            r["section"]: r["state"]
            for r in self.conn.execute(
                "SELECT section, state FROM preparation_section WHERE preparation_id = ?",
                (prep_id,),
            ).fetchall()
        }
        return sorted(
            s
            for s in required
            if reported.get(s, ConfirmationState.UNDECIDED.value)
            == ConfirmationState.UNDECIDED.value
        )

    # ------------------------------------------------ P3-01 단계별 사람 검토

    def stage_review_mode(self, case_id: str, stage: PreparationStage) -> ReviewMode:
        """이 단계의 검토 방식.

        **P3-R4에서 바뀌었다.** v0.6 기본값은 사람 검토였다(D-14 시절). v0.7 에서
        설계·계획의 사람 검토는 **선택 사항**이고(D-16·D-21), controlled 에서도
        그렇다(D-65 "설계·계획의 사람 검토는 별도 선택"). 그래서 행이 없으면
        Autonomy 에서 도출한다.

        **Autonomy 가 기록되지 않은 Case 는 v0.6 기본값을 유지한다.** 사람이 검토하기로
        하고 진행하던 업무가 조용히 통과하는 일을 만들지 않는다 — 이 한 줄이 소급
        금지의 구현이고, `domain.progression.derived_review_mode` 가 그 판단을 갖는다.

        Case 명시 설정은 그대로 이긴다. 기본값 해석은 여전히 이 한 곳뿐이다.
        """
        row = self.conn.execute(
            "SELECT mode FROM stage_review_setting WHERE case_id = ? AND stage = ?",
            (case_id, PreparationStage(stage).value),
        ).fetchone()
        if row is not None:
            return ReviewMode(row["mode"])
        return derived_review_mode(self.effective_autonomy(case_id))

    def set_stage_review_mode(
        self,
        case_id: str,
        stage: PreparationStage,
        mode: ReviewMode,
        set_by: str,
        reason_summary: str,
    ) -> dict[str, Any]:
        """검토 방식을 바꾼다. **두 단계는 서로 독립이다.**

        설계를 자동 진행으로 바꿔도 계획의 설정은 그대로다(FR-05 검토:
        "Case에서 독립적으로 자동 진행을 선택한다").
        """
        self.get_case(case_id)
        self.guard_open_case(case_id)
        stage = PreparationStage(stage)
        mode = ReviewMode(mode)
        if mode is ReviewMode.AUTO_PROCEED and not str(reason_summary or "").strip():
            # 자동 진행은 사람이 고른 것이므로 왜 골랐는지가 남아야 한다.
            raise ConflictError("switching a stage to auto-proceed needs a reason")
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO stage_review_setting (case_id, stage, mode, set_by,"
                " reason_summary, set_at) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(case_id, stage) DO UPDATE SET mode = excluded.mode,"
                "   set_by = excluded.set_by, reason_summary = excluded.reason_summary,"
                "   set_at = excluded.set_at",
                (
                    case_id,
                    stage.value,
                    mode.value,
                    set_by,
                    _summary(reason_summary or "사람 검토로 되돌림"),
                    utc_now(),
                ),
            )
        return self.stage_state(case_id, stage)

    def get_stage_review(self, prep_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM stage_review WHERE preparation_id = ?", (prep_id,)
        ).fetchone()
        return dict(row) if row else None

    def record_stage_review(
        self,
        case_id: str,
        stage: PreparationStage,
        prep_id: str,
        actor: str,
        note_summary: str,
        explicit: bool = True,
    ) -> dict[str, Any]:
        """사람이 이 단계의 산출물을 검토했다고 기록한다.

        **`decision` 표에 행을 만드는 것은 이 경로뿐이다.** 자동 진행은 만들지 않는다
        (sizing-and-review-ux 2절 "자동 진행이 사람 승인 기록 생성으로 이어지면 안 된다").

        원문을 읽을 수 없는 상태에서는 기록하지 않는다. 요약만 보고 상세 산출물을
        검토한 것으로 적지 않는다(sizing-and-review-ux 7절).
        """
        stage = PreparationStage(stage)
        prep = self.get_preparation_artifact(prep_id)
        self.guard_open_case(case_id)
        if prep["case_id"] != case_id or prep["stage"] != stage.value:
            raise ConflictError("the preparation artifact does not belong to this case and stage")
        if prep["state"] != PreparationState.CURRENT.value:
            raise ConflictError("this preparation artifact has been superseded")
        if not explicit:
            raise ConflictError("a stage review must be an explicit action on this artifact")
        if prep["availability"] != Availability.AVAILABLE.value:
            raise ConflictError(
                f"the original is {prep['availability']}; a summary is not the artifact"
            )
        existing = self.get_stage_review(prep_id)
        if existing is not None:
            if existing["state"] == StageReviewState.HUMAN_REVIEWED.value:
                return existing
            # **자동 조건 충족 기록을 사람 검토로 올린다**(P3-R4).
            #
            # R4 이전에는 이 상태가 생길 수 없었다 — 자동 진행 기록은 사람이 따로
            # 요청해야 만들어졌고, 그런 Case 에서 사람 검토를 또 요청할 이유가
            # 없었다. 이제 조건이 갖춰지는 순간 시스템이 기록하므로, 그 뒤에 사람이
            # 실제로 검토하는 일이 생긴다.
            #
            # 그대로 돌려주면 **실제로 있었던 사람의 검토가 사라진다.** 그것이 이
            # 분기가 있는 이유다. 반대로 두 행을 함께 두는 것은 `UNIQUE
            # (preparation_id)` 가 막고, 그 제약은 "이 산출물의 검토 상태는 하나"라는
            # 사실을 지키므로 풀지 않는다.
            #
            # 사람 검토가 자동 조건 충족보다 **강한 사실**이므로 그쪽이 남는다.
            # 없는 사람의 검토를 만드는 방향이 아니라 있었던 검토를 적는 방향이다.
            self.conn.execute(
                "DELETE FROM stage_review WHERE id = ?", (existing["id"],)
            )
        kind = (
            DecisionKind.DESIGN_REVIEW
            if stage is PreparationStage.DESIGN
            else DecisionKind.PLAN_REVIEW
        )
        decision = self.record_decision(
            case_id=case_id,
            kind=kind,
            subject_type="preparation_artifact",
            subject_id=prep_id,
            subject_revision=prep["revision"],
            actor=actor,
        )
        review_id = ids.new_id("stagerev")
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE decision SET subject_content_hash = ? WHERE id = ?",
                (prep["content_hash"], decision["id"]),
            )
            self.conn.execute(
                "INSERT INTO stage_review (id, case_id, stage, preparation_id, mode, state,"
                " decision_id, actor, subject_content_hash, note_summary, recorded_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    review_id,
                    case_id,
                    stage.value,
                    prep_id,
                    ReviewMode.HUMAN_REVIEW.value,
                    StageReviewState.HUMAN_REVIEWED.value,
                    decision["id"],
                    actor,
                    prep["content_hash"],
                    _summary(note_summary or "사람이 원문을 검토했다"),
                    utc_now(),
                ),
            )
        return self.get_stage_review(prep_id)

    #: 자동 진행 기록의 주체. **사람 이름을 넣지 않는다.**
    AUTO_POLICY_ACTOR = "stage-auto-proceed-policy"

    def record_auto_proceed(
        self, case_id: str, stage: PreparationStage, prep_id: str
    ) -> dict[str, Any]:
        """자동 진행 조건이 충족됐다고 기록한다.

        **사람 승인이 아니다.** `decision` 행을 만들지 않고 `actor` 도 정책 식별자다.
        상태는 `auto_conditions_met` 이며 화면도 그렇게 표시한다.

        자동 진행이 **산출물의 생략을 뜻하지는 않는다**(intent-artifacts 2절). 그래서
        산출물이 없거나 수준이 요구하는 항목이 미정이면 거부한다 — 그것이 "자동 조건"의
        내용이다.
        """
        stage = PreparationStage(stage)
        prep = self.get_preparation_artifact(prep_id)
        self.guard_open_case(case_id)
        if prep["case_id"] != case_id or prep["stage"] != stage.value:
            raise ConflictError("the preparation artifact does not belong to this case and stage")
        if prep["state"] != PreparationState.CURRENT.value:
            raise ConflictError("this preparation artifact has been superseded")
        if self.stage_review_mode(case_id, stage) is not ReviewMode.AUTO_PROCEED:
            raise ConflictError(
                f"{stage.value} is set to human review;"
                " auto-proceed cannot stand in for a person"
            )
        missing = prep["missing_required_sections"]
        if missing:
            raise ConflictError(
                f"{stage.value} is missing sections required at level {prep['level']}: {missing}"
            )
        if prep["availability"] != Availability.AVAILABLE.value:
            raise ConflictError(f"the original is {prep['availability']}")
        existing = self.get_stage_review(prep_id)
        if existing is not None:
            return existing
        review_id = ids.new_id("stagerev")
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO stage_review (id, case_id, stage, preparation_id, mode, state,"
                " decision_id, actor, subject_content_hash, note_summary, recorded_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    review_id,
                    case_id,
                    stage.value,
                    prep_id,
                    ReviewMode.AUTO_PROCEED.value,
                    StageReviewState.AUTO_CONDITIONS_MET.value,
                    None,
                    self.AUTO_POLICY_ACTOR,
                    prep["content_hash"],
                    "자동 진행 조건 충족 (사람 승인 아님)",
                    utc_now(),
                ),
            )
        return self.get_stage_review(prep_id)

    def stage_state(self, case_id: str, stage: PreparationStage) -> dict[str, Any]:
        """단계 하나의 현재 상태. 화면과 진입 검사가 같은 값을 본다."""
        stage = PreparationStage(stage)
        mode = self.stage_review_mode(case_id, stage)
        setting = self.conn.execute(
            "SELECT * FROM stage_review_setting WHERE case_id = ? AND stage = ?",
            (case_id, stage.value),
        ).fetchone()
        current = self.current_preparation(case_id, stage)
        latest_intent = self.latest_intent_version(case_id)
        stale = False
        state = StageReviewState.NOT_READY
        review = None
        if current is not None:
            review = current["review"]
            stale = (
                latest_intent is not None
                and current["intent_version_id"] != latest_intent["id"]
            )
            if stale:
                # 새 의도 버전이 생겼다. 이전 검토를 재사용하지 않는다(FR-23).
                state = StageReviewState.NEEDS_RECHECK
            elif review is not None:
                state = StageReviewState(review["state"])
            elif mode is ReviewMode.AUTO_PROCEED:
                # 산출물은 있고 조건 충족 기록만 없다. `not_ready` 로 적으면 화면에
                # "산출물 준비 전"으로 보여 사람이 무엇을 해야 하는지 알 수 없다.
                state = StageReviewState.AWAITING_AUTO_CONDITIONS
            else:
                state = StageReviewState.AWAITING_HUMAN_REVIEW
        return {
            "stage": stage.value,
            "mode": mode.value,
            # 기본값으로 읽은 것인지 사람이 정한 것인지 구별한다.
            #
            # **P3-R4에서 기본값의 출처가 달라졌다.** 이제 Autonomy 에서 도출하므로
            # `project_default` 라고 적으면 사람이 없는 프로젝트 설정 화면을 찾게
            # 된다. 취급 중인 Case(R1 이전)는 v0.6 기본값을 그대로 쓰며 그 사실도
            # 값으로 구별한다.
            "mode_source": (
                "case_setting"
                if setting is not None
                else (
                    "migrated_default"
                    if self.effective_autonomy(case_id).is_treatment
                    else "autonomy_derived"
                )
            ),
            "mode_reason": (
                setting["reason_summary"]
                if setting
                else (
                    "Autonomy 가 기록되지 않아 v0.6 기본값(사람 검토)을 유지한다"
                    if self.effective_autonomy(case_id).is_treatment
                    else "Autonomy 에서 도출한 기본값. 설계·계획의 사람 검토는 선택"
                    " 사항이다(D-16·D-65)"
                )
            ),
            "artifact": current,
            "review": review,
            "state": state.value,
            "stale": stale,
            "missing_required_sections": (current["missing_required_sections"] if current else []),
        }

    def deferred_open_questions(self, case_id: str) -> list[dict[str, Any]]:
        """설계·계획으로 이월했는데 아직 열려 있는 질문.

        최신 의도 버전에 붙은 것만 본다. 대체된 버전의 질문은 기록으로 남지만
        지금의 진행 조건은 아니다.
        """
        latest = self.latest_intent_version(case_id)
        if latest is None:
            return []
        rows = self.conn.execute(
            "SELECT * FROM intent_question WHERE intent_version_id = ? AND state = ?"
            " AND decide_at IN (?, ?) ORDER BY created_at",
            (
                latest["id"],
                QuestionState.OPEN.value,
                DecideAt.DESIGN.value,
                DecideAt.PLAN.value,
            ),
        ).fetchall()
        return [dict(r) for r in rows]

    def preparation_state(self, case_id: str) -> dict[str, Any]:
        """수준·설계·계획·검토를 한 번에 본 상태. 진입 검사와 화면이 같은 값을 쓴다."""
        self.get_case(case_id)
        sizing = self.current_sizing(case_id)
        return {
            "case_id": case_id,
            "sizing": sizing,
            "level": sizing["level"] if sizing else None,
            "sizing_history": self.list_sizing_assessments(case_id),
            "design": self.stage_state(case_id, PreparationStage.DESIGN),
            "plan": self.stage_state(case_id, PreparationStage.PLAN),
            # P3-R4. Fast Lane 의 결합 기록. **없는 것이 정상이다** — 일반 경로는
            # 설계·계획 두 건이고, 이 항목이 비어 있다는 사실이 "Fast Lane 을 쓰지
            # 않았다"이지 "준비가 모자라다"가 아니다.
            "combined": self.stage_state(case_id, PreparationStage.COMBINED),
            # 그 결합 기록이 지금 선행 조건을 충족할 수 있는지는 Fast Lane 조건이
            # 정한다. 화면·진입 검사가 같은 판정을 본다.
            "fast_lane": self.fast_lane_state(case_id),
            "deferred_open_questions": self.deferred_open_questions(case_id),
            # P3-02. 준비 조건 **위에 얹히는** 상태다. 계획 검토가 끝났다는 사실과
            # 무엇을 어떤 순서로 만들지가 정해졌다는 사실은 다른 것이다.
            "work_graph": self.work_graph_state(case_id),
        }

    # ------------------------------------------------- P3-01 고정 컨텍스트

    #: 계획을 따라 **코드를 바꾸거나 그 위에서 확인하는** 목적(P3-04).
    #:
    #: 이 목적들은 산출물을 쓰지 않는다 — 계획이 이미 정한 것을 실행한다. 그래서
    #: 고정하는 것도 "이전 버전"이 아니라 **따라야 할 것**(동의된 의도와 계획)이다.
    WORKS_FROM_THE_PLAN: frozenset[RunPurpose] = frozenset(
        {
            RunPurpose.FEATURE_IMPLEMENTATION,
            RunPurpose.VERIFICATION_RUN,
            RunPurpose.LOCAL_EXPERIMENT,
        }
    )

    def compose_context_refs(self, case_id: str, purpose: RunPurpose) -> list[dict[str, Any]]:
        """이 목적의 작성 실행에 고정할 참조 목록.

        **본문은 담지 않는다.** `(role, artifact_id, revision)` 만 담고 Runner가
        자기 저장소에서 읽는다(review-context-contract 2절).

        이것이 P2-04가 남긴 위험 1의 해소다. 재작성 실행에 이전 버전을 주지 않으면
        AI가 산출물을 처음부터 다시 써서 퇴화한다 — 라이브에서 실제로 그렇게 됐다.
        """
        purpose = RunPurpose(purpose)
        refs: list[dict[str, Any]] = []

        def add(role: ContextRefRole, artifact_id: str | None, revision: int | None) -> None:
            if not artifact_id or revision is None:
                return
            refs.append({"role": role.value, "artifact_id": artifact_id, "revision": int(revision)})

        def add_unresolved_feedback() -> None:
            for item in self.list_feedback(case_id):
                if item["state"] == FeedbackState.RECEIVED.value:
                    add(ContextRefRole.FEEDBACK, item["artifact_id"], item["artifact_rev"])

        def add_question_answers(intent_version_id: str) -> None:
            """**사람이 답한 질문의 원문**을 고정한다(P3-04).

            답변은 `intent_question.answer_artifact_id` 에 기록돼 있었지만 어떤
            실행의 입력도 아니었다 — AI 가 묻고 사람이 답했는데 다시 쓰는 AI 가
            그 답을 볼 수 없었다. 그 상태에서는 "필요한 질문의 답변을 반영하면
            자동 진행한다"(intent-artifacts 104행)가 성립하지 않는다. 반영할 입력이
            없기 때문이다.

            **피드백과 합치지 않는다.** 피드백은 초안 전체에 대한 의견이고 이것은
            **그 질문에 대한 답**이다. 한 역할로 묶으면 지시문이 "무엇에 답한
            것인지"를 말할 수 없다.
            """
            for question in self.list_questions(intent_version_id):
                if question["state"] != QuestionState.ANSWERED.value:
                    continue
                add(ContextRefRole.QUESTION_ANSWER, question.get("answer_artifact_id"), 1)

        def add_original_request(intent: dict[str, Any]) -> None:
            """**그 초안이 따라야 했던 요청 원문**을 고정한다(P3-04).

            QG-01 은 "요청 정합성 확인"이다 — 의도가 원래 요청과 맞는가를 본다.
            그런데 의미 검토의 고정 컨텍스트가 비어 있어서 검토자는 초안만 받아
            각 항목이 요청에서 온 것인지 **추측해야 했다.** 라이브의 첫 검토자가
            그것을 그대로 말했다("원래 요청이 제공되지 않아 …검토할 수 없다").

            대조할 것을 주지 않고 대조를 요구하면 검토자는 **요청에 있는 내용을
            근거 없는 가정으로** 판정한다. 실제로 그렇게 됐다.

            무엇이 그 요청인가는 지어내지 않는다 — **이 Case 의 첫 초안을 쓴 실행이
            받은 지시**가 정확히 그것이다.

            **다시 쓴 버전의 지시가 아니다.** 재작성 실행이 받는 것은 "이 지적을
            고쳐라" 같은 후속 지시이고, 그것을 요청으로 주면 검토자가 다른 것을
            원래 요청으로 읽는다. 라이브의 검토자가 그 어긋남을 실제로 알아챘다 —
            "요청 원문 내용이 제공되지 않아 전체 대조를 수행할 수 없다".

            사람이 직접 입력한 초안(`author_run_id` 없음)에는 그런 실행이 없고,
            그때는 **참조를 만들지 않는다.** 없는 것을 아무 지시 원문으로 채우지
            않는다.
            """
            author_run_id = None
            for version in self.list_intent_versions(intent["case_id"]):
                if version.get("author_run_id"):
                    author_run_id = version["author_run_id"]
            if not author_run_id:
                return
            try:
                run = self.get_run(author_run_id)
            except NotFoundError:
                return
            add(
                ContextRefRole.ORIGINAL_REQUEST,
                run["instruction_artifact_id"],
                run["instruction_artifact_rev"],
            )

        latest = self.latest_intent_version(case_id)
        if purpose is RunPurpose.INTENT_AUTHORING:
            if latest is not None:
                add(ContextRefRole.PREVIOUS_INTENT, latest["artifact_id"], latest["artifact_rev"])
                add_question_answers(latest["id"])
            add_unresolved_feedback()
        elif purpose is RunPurpose.INTENT_GATE_REVIEW:
            # **검토자에게 대조할 것을 준다.** 초안은 지시 원문으로 이미 간다
            # (`assignment_payload` 가 그 원문에서 검토 대상 버전을 끌어낸다).
            # 여기서 더하는 것은 **무엇과 맞춰 보라는 것인가**다.
            if latest is not None:
                add_original_request(latest)
                add_question_answers(latest["id"])
            add_unresolved_feedback()
        elif purpose is RunPurpose.QUALITY_GATE_REVIEW:
            # QG-02~07 검토에는 작성자의 완료 주장만 주지 않는다. 지시 원문이
            # 검토 대상이고, 아래 고정 참조가 그것을 대조할 요청·기준·현재 산출물이다.
            if latest is not None:
                add_original_request(latest)
                add(ContextRefRole.AGREED_INTENT, latest["artifact_id"], latest["artifact_rev"])
            design = self.current_preparation(case_id, PreparationStage.DESIGN)
            plan = self.current_preparation(case_id, PreparationStage.PLAN)
            if plan is None:
                plan = self.current_preparation(case_id, PreparationStage.COMBINED)
            if design is not None:
                add(ContextRefRole.CURRENT_DESIGN, design["artifact_id"], design["artifact_rev"])
            if plan is not None:
                add(ContextRefRole.CURRENT_PLAN, plan["artifact_id"], plan["artifact_rev"])
            add_unresolved_feedback()
        elif purpose in (RunPurpose.DESIGN_AUTHORING, RunPurpose.PLAN_AUTHORING):
            if latest is not None:
                add(ContextRefRole.AGREED_INTENT, latest["artifact_id"], latest["artifact_rev"])
            design = self.current_preparation(case_id, PreparationStage.DESIGN)
            if purpose is RunPurpose.DESIGN_AUTHORING:
                if design is not None:
                    add(
                        ContextRefRole.PREVIOUS_DESIGN,
                        design["artifact_id"],
                        design["artifact_rev"],
                    )
                add_unresolved_feedback()
            else:
                if design is not None:
                    add(
                        ContextRefRole.CURRENT_DESIGN,
                        design["artifact_id"],
                        design["artifact_rev"],
                    )
                plan = self.current_preparation(case_id, PreparationStage.PLAN)
                if plan is None:
                    # **Fast Lane 의 이전 기록은 결합 기록이다**(P3-R4). 주지 않으면
                    # 다시 쓰는 실행이 앞선 내용을 보지 못해 처음부터 다시 쓴다 —
                    # P2-04가 라이브에서 실제로 겪은 퇴화다.
                    plan = self.current_preparation(case_id, PreparationStage.COMBINED)
                if plan is not None:
                    add(ContextRefRole.PREVIOUS_PLAN, plan["artifact_id"], plan["artifact_rev"])
        elif purpose in self.WORKS_FROM_THE_PLAN:
            # **코드를 바꾸는 실행에도 고정 컨텍스트를 준다**(P3-04).
            #
            # 여기가 비어 있었다. 구현·검증·실험 실행은 호출자가 지시 원문에 적은
            # 것만 보고 일했고, 그러면 "무엇을 보고 만들었는가"가 시스템의 기록이
            # 아니라 호출자가 넣은 문자열이 된다 — 고정 컨텍스트 계약이 가장 필요한
            # 단계에서 그 계약이 없던 셈이다(review-context-contract 2절).
            #
            # **동의된 의도와 계획 둘뿐이다.** 설계까지 넣지 않는 이유는 계획이 이미
            # 설계 위에 세워졌고, 구현이 따라야 하는 것은 계획이 정의한 Task 이기
            # 때문이다. 넣을수록 좋은 것이 아니라 **따라야 할 것**을 준다.
            if latest is not None:
                add(ContextRefRole.AGREED_INTENT, latest["artifact_id"], latest["artifact_rev"])
            plan = self.current_preparation(case_id, PreparationStage.PLAN)
            if plan is None:
                plan = self.current_preparation(case_id, PreparationStage.COMBINED)
            if plan is not None:
                add(ContextRefRole.CURRENT_PLAN, plan["artifact_id"], plan["artifact_rev"])
        return refs

    def _insert_context_refs(self, run_id: str, refs: list[dict[str, Any]]) -> None:
        """고정 컨텍스트 참조를 넣는다. **호출자의 트랜잭션 안에서 돈다**(P3-R3).

        여기서 트랜잭션을 열지 않는 이유는 Run 행·예약·참조가 한 트랜잭션이어야
        하기 때문이다 — 예약한 `context_bytes` 는 이 참조들의 크기 합이고, 둘이 다른
        트랜잭션이면 참조 없는 Run 에 크기만 잡힌 예약이 남을 수 있다.

        `ContextRefRole(...)` 로 이름을 검증한다. **모르는 역할 이름을 그대로 넣지
        않는다** — 넣으면 조회가 해석할 수 없는 참조가 생기고, 그 참조가 가리키는
        원문을 실행이 읽어야 하는지 아무도 답할 수 없다.
        """
        for seq, ref in enumerate(refs, start=1):
            self.conn.execute(
                "INSERT INTO run_context_ref (run_id, seq, role, artifact_id, revision)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(run_id, seq) DO NOTHING",
                (
                    run_id,
                    seq,
                    ContextRefRole(ref["role"]).value,
                    ref["artifact_id"],
                    int(ref["revision"]),
                ),
            )

    def list_context_refs(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM run_context_ref WHERE run_id = ? ORDER BY seq", (run_id,)
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            ref = self.get_artifact_ref(item["artifact_id"], item["revision"])
            # 참조가 지금 읽을 수 있는 상태인지 함께 알려 준다. Runner가 읽지 못하면
            # 지시문에 "읽지 못함"으로 적히고 산출물이 그 사실을 갖는다.
            item["availability"] = ref["availability"]
            item["content_hash"] = ref["content_hash"]
            out.append(item)
        return out

    def result_view(self, case_id: str) -> dict[str, Any]:
        """FR-17이 요구하는 "기준별 증거·미충족·미검증"의 한 묶음.

        총점 하나를 만들지 않는다. 기준마다 판정·근거 종류·근거 참조를 그대로 둔다
        (sizing-and-review-ux 6절 "총점 하나와 녹색 표시만 보여주지 않는다").
        """
        self.get_case(case_id)
        mode = self.completion_mode_state(case_id)
        criteria = self.current_criteria(case_id)
        for crit in criteria:
            # **적용되는** 결론 요구. 저장된 값이 NULL 이면 확정 필수로 취급한다는
            # 사실을 화면이 따로 계산하지 않게 여기서 붙인다(P4-03).
            crit["conclusion_rule_effective"] = (
                meaningmod.effective_conclusion_rule(crit.get("conclusion_rule")).value
                if crit.get("obligation") in {o.value for o in meaningmod.CONCLUSION_OBLIGATIONS}
                else None
            )
        return {
            "case_id": case_id,
            "completion_mode": mode["mode"],
            # **어디서 온 값인지 함께 말한다**(P3-R4). 사람이 고른 설정과 Autonomy 에서
            # 도출한 값을 같은 모양으로 보이면 고르지 않은 자동 완료가 사용자의
            # 설정처럼 읽힌다.
            "completion_mode_source": mode["source"],
            "criteria": criteria,
            # **P4-03: 목적별 완료 의미.** 요구된 목적마다 기준·충족 수, 기준이 없는
            # 목적, 실험의 정리 상태. 계약이 없는 Case 는 `contract = None` 이다.
            "completion_meaning": self.completion_meaning(case_id),
            "unsettled_runs": self.unsettled_runs(case_id),
            "candidate": self.current_completion_candidate(case_id),
            "closure": self.get_closure(case_id),
            "relations": self.list_case_relations(case_id),
            # controlled 의 확인 순서가 지금 무엇을 기다리는가. 화면이 "무엇을
            # 해야 하는가"를 말할 수 있어야 한다(FR-14).
            "controlled": self.checkpoint_state(case_id),
        }

    # ===================================================== P3-02 작업 그래프

    #: 사람의 재계획이 아닌, 계획 산출물에서 태어난 그래프의 행위자 표기.
    #: 사람 이름이 아니라 출처 식별자다 — P3-01의 `AUTO_POLICY_ACTOR` 와 같은 이유다.
    PLAN_GRAPH_ACTOR = "policy:plan_artifact"

    def record_question_block_refs(self, question_id: str, refs: Iterable[str]) -> None:
        """질문이 막는다고 적힌 참조를 **해석하지 않고** 보관한다.

        해석은 그래프를 만들 때 한다. 설계 단계의 질문은 계획이 정의할 Task 를
        가리키는데 그 Task 는 질문이 제기되는 시점에 아직 없기 때문이다.
        """
        for ref in refs:
            value = " ".join(str(ref).split())[:200]
            if not value:
                continue
            self.conn.execute(
                "INSERT OR IGNORE INTO question_block_ref (question_id, raw_ref) VALUES (?, ?)",
                (question_id, value),
            )

    def question_block_refs(self, question_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT raw_ref FROM question_block_ref WHERE question_id = ? ORDER BY raw_ref",
            (question_id,),
        ).fetchall()
        return [r["raw_ref"] for r in rows]

    def current_work_graph_row(self, case_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM work_graph_revision WHERE case_id = ? AND state = ?",
            (case_id, WorkGraphState.CURRENT.value),
        ).fetchone()
        return dict(row) if row else None

    def _graph_tasks(self, graph_id: str) -> list[dict[str, Any]]:
        # 저장소 이름을 함께 읽는다(P3-04). 화면이 id 만 보면 사람이 어느 저장소인지
        # 알 수 없고, 화면이 따로 조회하면 진입 검사와 다른 값을 볼 수 있다.
        rows = self.conn.execute(
            "SELECT t.*, pr.name AS repository_name FROM task t"
            " LEFT JOIN project_repository pr ON pr.id = t.repository_id"
            " WHERE t.graph_revision_id = ? ORDER BY t.order_index",
            (graph_id,),
        ).fetchall()
        tasks = [dict(r) for r in rows]
        deps: dict[str, list[str]] = {}
        for dep in self.conn.execute(
            "SELECT task_key, depends_on_key FROM task_dependency"
            " WHERE graph_revision_id = ? ORDER BY depends_on_key",
            (graph_id,),
        ).fetchall():
            deps.setdefault(dep["task_key"], []).append(dep["depends_on_key"])
        links: dict[str, list[dict[str, str]]] = {}
        for link in self.conn.execute(
            "SELECT task_key, criterion_id, relation FROM task_criterion"
            " WHERE graph_revision_id = ? ORDER BY criterion_id",
            (graph_id,),
        ).fetchall():
            links.setdefault(link["task_key"], []).append(
                {"criterion_id": link["criterion_id"], "relation": link["relation"]}
            )
        for task in tasks:
            task["cancelled"] = bool(task["cancelled"])
            task["depends_on"] = deps.get(task["task_key"], [])
            task["criteria"] = links.get(task["task_key"], [])
        return tasks

    def _graph_nodes(self, tasks: list[dict[str, Any]]) -> list[workgraph.TaskNode]:
        return [
            workgraph.TaskNode(
                key=t["task_key"],
                kind=t["kind"],
                depends_on=tuple(t["depends_on"]),
                cancelled=bool(t["cancelled"]),
            )
            for t in tasks
        ]

    def create_work_graph_revision(
        self,
        case_id: str,
        plan_preparation_id: str,
        tasks: list[dict[str, Any]],
        source: WorkGraphSource,
        reason_summary: str,
        actor: str,
    ) -> dict[str, Any]:
        """새 그래프 리비전을 만든다. **이전 리비전은 지우지 않고 대체됨으로 남긴다.**

        Task 행을 그 자리에서 고치지 않는 이유는 "그때 무엇이 유효했는가"를 답할 수
        있어야 하기 때문이다(FR-07). `task_key` 는 리비전을 가로질러 같으므로
        **재분할이 실행 이력을 초기화하지 않는다.**

        의존·기준 연결·질문 연결을 **전부 이 리비전 안에서 다시 해석한다.**
        이전 리비전에서 복사해 오지 않는 이유는, 없어진 Task 를 가리키는 연결이
        조용히 살아남으면 그 질문이 무엇을 막는지 알 수 없게 되기 때문이다.
        """
        self.get_case(case_id)
        self.guard_open_case(case_id)
        prep = self.get_preparation_artifact(plan_preparation_id)
        # **설계 위에는 그래프를 세우지 않는다.** 결합 기록은 계획의 자리를 대신하므로
        # 여기 포함된다(P3-R4) — 빼면 Fast Lane Case 는 Task 를 정의하고도 영원히
        # `work_graph_missing` 이 된다.
        if PreparationStage(prep["stage"]) not in (
            PreparationStage.PLAN,
            PreparationStage.COMBINED,
        ):
            raise ConflictError("a work graph is built on a development plan, not a design")
        latest = self.latest_intent_version(case_id)
        if latest is None:
            raise ConflictError("a work graph needs an intent version to build on")
        reason = _summary(reason_summary)
        if not reason.strip():
            raise ConflictError("a work graph revision needs a reason")

        nodes = [
            workgraph.TaskNode(
                key=str(t["key"]),
                kind=TaskKind(t.get("kind") or TaskKind.IMPLEMENTATION.value).value,
                depends_on=tuple(str(d) for d in (t.get("depends_on") or [])),
            )
            for t in tasks
        ]
        if len({n.key for n in nodes}) != len(nodes):
            raise ConflictError("task keys must be unique inside one work graph revision")
        # 순환·미지의 의존은 **받아 두지 않는다.** 잘못된 그래프를 저장하면 그 뒤의
        # 모든 차단 판정이 그 위에서 이루어진다.
        try:
            workgraph.validate_dependencies(nodes)
        except workgraph.WorkGraphError as exc:
            raise ConflictError(str(exc)) from exc

        keys = {n.key for n in nodes}
        # 기준 연결은 **현재 의도 버전의 기준만** 받는다. 성공 기준은 의도 버전에
        # 묶여 있고 새 버전은 기준을 승계하지 않으므로(스키마 v4), 옛 기준을 받아
        # 두면 대체된 기준이 새 그래프에 그대로 붙는다.
        criteria_by_key = {
            c["criterion_key"]: c for c in self.list_success_criteria(latest["id"])
        }

        row = self.conn.execute(
            "SELECT MAX(revision) AS r FROM work_graph_revision WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        revision = (row["r"] or 0) + 1
        graph_id = ids.new_id("wgraph")
        now = utc_now()

        with transaction(self.conn):
            self.conn.execute(
                "UPDATE work_graph_revision SET state = ?, superseded_at = ?"
                " WHERE case_id = ? AND state = ?",
                (WorkGraphState.SUPERSEDED.value, now, case_id, WorkGraphState.CURRENT.value),
            )
            self.conn.execute(
                "INSERT INTO work_graph_revision (id, case_id, revision, intent_version_id,"
                " plan_preparation_id, source, reason_summary, actor, state, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    graph_id,
                    case_id,
                    revision,
                    latest["id"],
                    plan_preparation_id,
                    WorkGraphSource(source).value,
                    reason,
                    actor,
                    WorkGraphState.CURRENT.value,
                    now,
                ),
            )
            for index, raw in enumerate(tasks, start=1):
                # **어느 저장소를 바꾸는 작업인가**(P3-04). 해석은 여기서 하고
                # 적힌 문자열은 그대로 남긴다 — 해석되지 않은 참조를 버리면
                # "저장소를 말하지 않은 계획"과 "선택 밖 저장소를 가리킨 계획"이
                # 같은 모양이 된다(`task_block_unresolved` 와 같은 규칙).
                repository_ref = " ".join(str(raw.get("repository") or "").split())[:100]
                repository_id = self.resolve_case_repository_ref(case_id, repository_ref)
                self.conn.execute(
                    "INSERT INTO task (id, case_id, graph_revision_id, task_key, kind,"
                    " relates_to, summary, deliverable_summary, completion_summary,"
                    " order_index, origin, cancelled, cancel_reason, created_at,"
                    " repository_id, repository_ref)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        ids.new_id("task"),
                        case_id,
                        graph_id,
                        str(raw["key"]),
                        TaskKind(raw.get("kind") or TaskKind.IMPLEMENTATION.value).value,
                        str(raw.get("relates_to") or ""),
                        _summary(raw.get("summary") or raw["key"]),
                        _summary(raw.get("deliverable_summary") or ""),
                        _summary(raw.get("completion_summary") or ""),
                        int(raw.get("order_index") or index),
                        ContentOrigin(raw.get("origin") or ContentOrigin.AI_PROPOSAL.value).value,
                        1 if raw.get("cancelled") else 0,
                        _summary(raw.get("cancel_reason") or ""),
                        now,
                        repository_id,
                        repository_ref,
                    ),
                )
            for raw in tasks:
                for dep in raw.get("depends_on") or []:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO task_dependency"
                        " (graph_revision_id, task_key, depends_on_key) VALUES (?, ?, ?)",
                        (graph_id, str(raw["key"]), str(dep)),
                    )
                for link in raw.get("criteria") or []:
                    criterion_key = str(link.get("key") or link.get("criterion_key") or "")
                    criterion = criteria_by_key.get(criterion_key)
                    if criterion is None:
                        # 없는 기준·대체된 기준을 가리키는 연결은 **거부한다.**
                        # 조용히 버리면 "연결했다"는 기록만 남고 실제 연결은 없다.
                        raise ConflictError(
                            f"task {raw['key']} links to criterion {criterion_key!r},"
                            " which is not a success criterion of the current intent version"
                        )
                    self.conn.execute(
                        "INSERT OR IGNORE INTO task_criterion"
                        " (graph_revision_id, task_key, criterion_id, relation)"
                        " VALUES (?, ?, ?, ?)",
                        (
                            graph_id,
                            str(raw["key"]),
                            criterion["id"],
                            TaskRelation(link.get("relation") or TaskRelation.IMPLEMENTS.value).value,
                        ),
                    )
            # 이월 질문의 `blocks` 를 이 리비전의 Task 키로 해석한다.
            # **해석되지 않은 참조는 버리지 않고 남긴다** — 버리면 그 질문이
            # "아무 것도 막지 않는" 질문이 되어 좁히기가 곧 우회가 된다.
            for question in self.deferred_open_questions(case_id):
                for ref in self.question_block_refs(question["id"]):
                    if ref in keys:
                        self.conn.execute(
                            "INSERT OR IGNORE INTO task_question_block"
                            " (graph_revision_id, question_id, task_key) VALUES (?, ?, ?)",
                            (graph_id, question["id"], ref),
                        )
                    else:
                        self.conn.execute(
                            "INSERT OR IGNORE INTO task_block_unresolved"
                            " (graph_revision_id, question_id, raw_ref) VALUES (?, ?, ?)",
                            (graph_id, question["id"], ref),
                        )
        return self.get_work_graph(graph_id)

    def get_work_graph(self, graph_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM work_graph_revision WHERE id = ?", (graph_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"work graph revision not found: {graph_id}")
        out = dict(row)
        out["tasks"] = self._graph_tasks(graph_id)
        return out

    def list_work_graph_revisions(self, case_id: str) -> list[dict[str, Any]]:
        """리비전 이력. **이전 계획은 지워지지 않는다**(FR-07)."""
        rows = self.conn.execute(
            "SELECT id FROM work_graph_revision WHERE case_id = ? ORDER BY revision DESC",
            (case_id,),
        ).fetchall()
        return [self.get_work_graph(r["id"]) for r in rows]

    def task_run_history(self, case_id: str, task_key: str) -> list[dict[str, Any]]:
        """그 `task_key` 의 실행 이력. **리비전을 가로지른다.**

        `run.task_id` 에 행 id 가 아니라 키가 들어가기 때문에, 그래프를 다시 짜도
        이력이 끊기지 않는다(FR-07 "재분할로 실패 이력·수정 한도를 초기화하지 않는다").
        """
        rows = self.conn.execute(
            "SELECT run_id FROM run WHERE case_id = ? AND task_id = ? ORDER BY created_at",
            (case_id, task_key),
        ).fetchall()
        return [self.get_run(r["run_id"]) for r in rows]

    def work_graph_state(self, case_id: str) -> dict[str, Any]:
        """그래프의 현재 상태. **진입 검사와 화면이 같은 값을 본다.**

        `present=False` 는 "Task 가 필요 없다"가 아니라 **그래프가 아직 없다**는
        뜻이다. 그 경우 진입 검사는 P3-01의 Case 수준 차단을 그대로 적용한다.
        """
        self.get_case(case_id)
        graph = self.current_work_graph_row(case_id)
        latest = self.latest_intent_version(case_id)
        open_questions = self.deferred_open_questions(case_id)
        if graph is None:
            return {
                "case_id": case_id,
                "present": False,
                "stale": False,
                "graph": None,
                "tasks": [],
                "readiness": {},
                "criteria_coverage": [],
                "deferred_open_questions": open_questions,
                "question_blocks": {},
                "unresolved_block_refs": [],
            }

        graph_id = graph["id"]
        tasks = self._graph_tasks(graph_id)
        nodes = self._graph_nodes(tasks)
        runs = self.list_runs(case_id)
        states = {n.key: workgraph.derive_task_state(n, runs) for n in nodes}

        blocks: dict[str, list[str]] = {}
        for row in self.conn.execute(
            "SELECT question_id, task_key FROM task_question_block"
            " WHERE graph_revision_id = ? ORDER BY task_key",
            (graph_id,),
        ).fetchall():
            blocks.setdefault(row["question_id"], []).append(row["task_key"])
        unresolved = [
            dict(r)
            for r in self.conn.execute(
                "SELECT question_id, raw_ref FROM task_block_unresolved"
                " WHERE graph_revision_id = ? ORDER BY raw_ref",
                (graph_id,),
            ).fetchall()
        ]

        stale = latest is not None and graph["intent_version_id"] != latest["id"]
        readiness = {
            node.key: workgraph.evaluate_task(
                task_key=node.key,
                tasks=nodes,
                task_states=states,
                open_questions=open_questions,
                question_blocks=blocks,
            ).to_dict()
            for node in nodes
        }
        for task in tasks:
            task["state"] = states.get(task["task_key"], TaskState.PLANNED.value)
            task["readiness"] = readiness.get(task["task_key"])

        links = [
            {"task_key": t["task_key"], **link} for t in tasks for link in t["criteria"]
        ]
        coverage = workgraph.criteria_coverage(self.current_criteria(case_id), links)

        graph_out = dict(graph)
        graph_out["tasks"] = tasks
        return {
            "case_id": case_id,
            "present": True,
            "stale": stale,
            "graph": graph_out,
            "tasks": tasks,
            "readiness": readiness,
            "criteria_coverage": coverage,
            "deferred_open_questions": open_questions,
            "question_blocks": blocks,
            "unresolved_block_refs": unresolved,
        }

    # ------------------------------------------------- P3-02 사람의 재계획

    def _replan(
        self, case_id: str, mutate: Any, reason_summary: str, actor: str
    ) -> dict[str, Any]:
        """현재 리비전을 바탕으로 **새 리비전**을 만든다.

        행을 그 자리에서 고치지 않는 이유는 위 `create_work_graph_revision` 과 같다.
        질문 연결은 원문의 참조에서 다시 해석되므로 여기서 옮기지 않는다.
        """
        graph = self.current_work_graph_row(case_id)
        if graph is None:
            raise ConflictError("this case has no work graph to replan")
        latest = self.latest_intent_version(case_id)
        if latest is not None and graph["intent_version_id"] != latest["id"]:
            # **오래된 그래프를 손보지 않는다.** 의도가 바뀌면 그 위의 계획은 이미
            # 대체됐고, 여기서 Task 를 더하면 옛 의도의 계획이 되살아난다.
            # 고칠 것은 계획이지 그래프가 아니다(FR-12 "오래된 증거를 새 요구의
            # 완료 근거로 쓰지 않는다").
            raise ConflictError(
                "this work graph was built on a superseded intent version;"
                " rewrite the development plan instead of editing the old graph"
            )
        tasks = self._graph_tasks(graph["id"])
        payload = [
            {
                "key": t["task_key"],
                "kind": t["kind"],
                "relates_to": t["relates_to"],
                "summary": t["summary"],
                "deliverable_summary": t["deliverable_summary"],
                "completion_summary": t["completion_summary"],
                "order_index": t["order_index"],
                "origin": t["origin"],
                "cancelled": t["cancelled"],
                "cancel_reason": t["cancel_reason"],
                # **재계획이 저장소 기록을 지우지 않는다**(P3-04). 새 리비전을
                # 만들 때 이 값을 빠뜨리면 사람이 Task 하나를 더한 것만으로
                # 기존 Task 들이 전부 저장소 미기록이 된다.
                "repository": t["repository_id"] or t["repository_ref"] or "",
                "depends_on": list(t["depends_on"]),
                "criteria": [
                    {
                        "key": self.get_success_criterion(link["criterion_id"])["criterion_key"],
                        "relation": link["relation"],
                    }
                    for link in t["criteria"]
                ],
            }
            for t in tasks
        ]
        mutate(payload)
        return self.create_work_graph_revision(
            case_id=case_id,
            plan_preparation_id=graph["plan_preparation_id"],
            tasks=payload,
            source=WorkGraphSource.HUMAN_REPLANNING,
            reason_summary=reason_summary,
            actor=actor,
        )

    def add_task(
        self, case_id: str, task: dict[str, Any], reason_summary: str, actor: str
    ) -> dict[str, Any]:
        """사람이 Task 를 더한다(FR-07 "추가·분할·취소·조정").

        **이유가 필수다.** 계획이 왜 바뀌었는지 없이 그래프만 바뀌면 나중에
        "무효 전제의 결과를 확인 없이 채택"했는지 알 수 없다.

        분할 전용 경로를 두지 않는다 — 추가 + 취소 + 의존 조정의 합성으로 같은
        결과가 되고, `task_key` 가 보존되므로 이력도 끊기지 않는다.
        """
        key = str(task.get("key") or "").strip()
        if not key:
            raise ConflictError("a task needs a key")

        def mutate(payload: list[dict[str, Any]]) -> None:
            if any(t["key"] == key for t in payload):
                raise ConflictError(f"task {key!r} already exists in this work graph")
            payload.append(
                {
                    "key": key,
                    "kind": TaskKind(task.get("kind") or TaskKind.IMPLEMENTATION.value).value,
                    "relates_to": str(task.get("relates_to") or ""),
                    "summary": task.get("summary") or key,
                    "deliverable_summary": task.get("deliverable_summary") or "",
                    "completion_summary": task.get("completion_summary") or "",
                    "order_index": len(payload) + 1,
                    # 사람이 더한 Task 의 출처는 **사람의 요구**다. AI 제안으로
                    # 적으면 누가 정한 것인지가 기록에서 사라진다.
                    "origin": ContentOrigin.USER_REQUIREMENT.value,
                    "cancelled": False,
                    "cancel_reason": "",
                    # 사람이 더하는 Task 도 저장소를 적는다(P3-04). 비우면 미기록이고,
                    # 저장소가 둘 이상인 Case 에서는 그 Task 로 구현이 열리지 않는다 —
                    # 여기서 하나를 골라 채우지 않는 이유는 그것이 사람의 판단이기
                    # 때문이다.
                    "repository": str(task.get("repository") or ""),
                    "depends_on": [str(d) for d in (task.get("depends_on") or [])],
                    "criteria": list(task.get("criteria") or []),
                }
            )

        return self._replan(case_id, mutate, reason_summary, actor)

    def cancel_task(
        self, case_id: str, task_key: str, reason_summary: str, actor: str
    ) -> dict[str, Any]:
        """사람이 Task 를 취소한다.

        **행을 지우지 않는다** — 무엇이 있었고 왜 빠졌는지가 남아야 한다. 취소된
        Task 는 배정되지 않고 의존도 충족시키지 않는다(완료가 아니기 때문이다).
        """

        def mutate(payload: list[dict[str, Any]]) -> None:
            for entry in payload:
                if entry["key"] == task_key:
                    if entry["cancelled"]:
                        raise ConflictError(f"task {task_key!r} is already cancelled")
                    entry["cancelled"] = True
                    entry["cancel_reason"] = _summary(reason_summary)
                    return
            raise NotFoundError(f"task not found in the current work graph: {task_key}")

        return self._replan(case_id, mutate, reason_summary, actor)

    def set_question_blocks(
        self,
        case_id: str,
        question_id: str,
        task_keys: list[str],
        reason_summary: str,
        actor: str,
    ) -> dict[str, Any]:
        """어떤 Task 가 이 결정을 기다리는지 사람이 고친다.

        AI가 적은 `blocks` 가 틀리거나 비어 있을 수 있고, 그때 사람이 고칠 수단이
        없으면 **연결 없는 질문 하나가 영원히 전부 막는다.** 고친 참조는 원문의
        참조 목록을 대체하고 다음 리비전에서도 그대로 해석된다.

        **이것이 질문에 답하는 것은 아니다.** 연결을 고쳐도 질문은 여전히 `open`
        이고 연결된 Task 는 계속 막힌다 — 연결은 "누가 기다리는가"이지 "결정됐는가"가
        아니다.
        """
        question = self.get_question(question_id)
        if question["case_id"] != case_id:
            raise ConflictError("that question belongs to another case")
        graph = self.current_work_graph_row(case_id)
        if graph is None:
            raise ConflictError("this case has no work graph to link questions to")
        known = {t["task_key"] for t in self._graph_tasks(graph["id"])}
        unknown = [k for k in task_keys if k not in known]
        if unknown:
            raise ConflictError(f"unknown task keys for this work graph: {sorted(unknown)}")
        with transaction(self.conn):
            self.conn.execute(
                "DELETE FROM question_block_ref WHERE question_id = ?", (question_id,)
            )
            self.record_question_block_refs(question_id, task_keys)

        def mutate(_payload: list[dict[str, Any]]) -> None:
            return None

        return self._replan(case_id, mutate, reason_summary, actor)

    # =================================================================== P3-03
    #
    # 작업공간과 실행 효과. 아래 접근자에도 본문을 받는 인자가 없다. diff·파일
    # 경로·명령 원문·빌드 로그는 Runner 의 산출물에 있고 여기에는 식별자(SHA·
    # 경로·브랜치)와 **수**, 짧은 요약만 온다(D-43·NFR-12).

    # --------------------------------------------------------- Case 작업공간

    @staticmethod
    def branch_for_case(case_id: str) -> str:
        """Case 전용 브랜치 이름.

        접두사를 두는 이유는 사람이 고른 이름과 섞이지 않게 하기 위해서다.
        **이름이 같다고 우리 것으로 간주하지는 않는다** — 소유는 기록된 worktree
        경로와 대조해 확인한다(execution-workspace-review 2절).
        """
        return f"hads/{case_id}"

    def resolve_code_repository(
        self, case_id: str, repository_id: str | None
    ) -> tuple[dict[str, Any], WorkspaceAllowanceSource]:
        """이 Case 가 **그 저장소에 코드 작업공간을 가질 수 있는가**(P3-R2).

        R1 은 선택·쓰기 허용·게시 허용을 기록만 했다. 여기서부터 앞의 둘이 실제로
        무엇을 막는다. 판정 순서는 [P3-PLAN-R2](../plans/P3-PLAN-R2.md) 5절이다.

        **가장 조심할 갈래는 "선택 기록이 없다"** 이다. P3-03까지의 Case 는 선택
        기록 없이 Project 의 단일 저장소에서 실제로 작업했고, 거기에 "선택 기록이
        없으니 쓰기 금지"를 적용하면 새 정책을 기존 권한에 소급하는 것이 된다
        (DEVELOPMENT.md 3절). 그래서 **허용하되 허용의 출처를 남긴다** — 없던
        선택을 기록으로 지어내지 않는다.

        반대로 선택 기록이 **하나라도** 있으면 그 Case 는 판단이 있었던 Case 이므로
        없던 가정을 씌우지 않는다. R1 의 `case_repository_state` 가 암묵적 단일
        저장소를 표시하는 규칙과 같다.
        """
        case = self.get_case(case_id)
        project = self.get_project(case["project_id"])
        registered = self.list_project_repositories(case["project_id"])
        by_id = {r["id"]: r for r in registered}

        rows = self.conn.execute(
            "SELECT * FROM case_repository WHERE case_id = ? AND state = ?",
            (case_id, PolicyState.CURRENT.value),
        ).fetchall()
        selections = {r["repository_id"]: dict(r) for r in rows}

        if repository_id is None:
            # 대상을 주지 않았다. **고르지 않는다** — 고르는 것은 사람 또는 허용 내
            # 자동 추가의 일이다. 모호하지 않은 두 경우에만 해석한다.
            writable = [
                repo_id
                for repo_id, sel in selections.items()
                if sel["selection_source"] != RepositorySelectionSource.EXCLUDED.value
                and sel["code_write_allowed"]
            ]
            if len(writable) == 1:
                repository_id = writable[0]
            elif not selections and len(registered) == 1:
                repository_id = registered[0]["id"]
            else:
                raise PolicyRefused([PolicyRefusal.REPOSITORY_SELECTION_REQUIRED])

        repo = by_id.get(repository_id)
        if repo is None:
            raise PolicyRefused([PolicyRefusal.REPOSITORY_NOT_IN_PROJECT])
        if project.get("journal_repository_id") == repository_id:
            # 기록 저장소는 **지정만으로** 어떤 Case 의 코드 대상에도 들어가지
            # 않는다(D-17·D-34·FR-30).
            raise PolicyRefused([PolicyRefusal.JOURNAL_REPOSITORY_NOT_A_CODE_TARGET])

        selection = selections.get(repository_id)
        if selection is not None:
            if selection["selection_source"] == RepositorySelectionSource.EXCLUDED.value:
                raise PolicyRefused([PolicyRefusal.REPOSITORY_EXPLICITLY_EXCLUDED])
            if not selection["code_write_allowed"]:
                raise PolicyRefused([PolicyRefusal.REPOSITORY_NOT_SELECTED_FOR_CODE])
            return repo, WorkspaceAllowanceSource.CASE_REPOSITORY

        if not selections and len(registered) == 1:
            return repo, WorkspaceAllowanceSource.IMPLICIT_SINGLE_REPOSITORY
        raise PolicyRefused([PolicyRefusal.REPOSITORY_SELECTION_REQUIRED])

    def request_workspace(
        self,
        case_id: str,
        repository_id: str | None = None,
        base_ref: str = "HEAD",
    ) -> dict[str, Any]:
        """이 Case 에 그 저장소의 전용 작업공간이 필요하다고 기록한다.

        **여기서 git 을 부르지 않는다.** 저장소와 파일은 Runner 호스트에 있고
        (D-43·FR-27) 제어부가 직접 만들면 단일 호스트에서만 동작한다. 이 행은
        요청이며 `requested` 상태는 **준비됨이 아니다.**

        이미 `ready` 인 (Case, 저장소)는 그대로 돌려준다. 같은 조합에 두 번째
        작업공간을 만들지 않는다 — 어느 쪽이 유효한지 알 수 없게 된다(D-39).
        **저장소가 다르면 다른 작업공간이다**(P3-R2). 그것이 D-39 가 요구하는
        `Case × Repository` 이며, 한 Case 가 두 저장소를 고치는 일은 각각의 브랜치·
        기준 커밋 위에서 일어난다.
        """
        case = self.get_case(case_id)
        repo, allowance = self.resolve_code_repository(case_id, repository_id)
        row = self.get_workspace(case_id, repo["id"])
        if row is not None and row["state"] == WorkspaceState.READY.value:
            return row
        now = utc_now()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO case_workspace"
                " (case_id, repository_id, project_id, state, branch, allowance_source,"
                "  base_ref, requested_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(case_id, repository_id) DO UPDATE SET"
                "  state = excluded.state, base_ref = excluded.base_ref,"
                "  allowance_source = excluded.allowance_source,"
                "  failure_reason = '', requested_at = excluded.requested_at,"
                "  ready_at = NULL",
                (
                    case_id,
                    repo["id"],
                    case["project_id"],
                    WorkspaceState.REQUESTED.value,
                    self.branch_for_case(case_id),
                    allowance.value,
                    base_ref,
                    now,
                ),
            )
        return self.get_workspace(case_id, repo["id"])

    def get_workspace(
        self, case_id: str, repository_id: str | None = None
    ) -> dict[str, Any] | None:
        """그 (Case, 저장소)의 작업공간 행.

        `repository_id` 를 주지 않으면 **행이 정확히 하나일 때만** 돌려준다. 둘 이상
        이면 어느 것인지 지어내지 않고 `None` 이며, 그 경우를 "작업공간 없음"으로
        읽지 않도록 호출자는 `list_workspaces` 나 `workspace_state` 를 쓴다.
        """
        if repository_id is not None:
            row = self.conn.execute(
                "SELECT * FROM case_workspace WHERE case_id = ? AND repository_id = ?",
                (case_id, repository_id),
            ).fetchone()
        else:
            rows = self.conn.execute(
                "SELECT * FROM case_workspace WHERE case_id = ?", (case_id,)
            ).fetchall()
            row = rows[0] if len(rows) == 1 else None
        if row is None:
            return None
        workspace = dict(row)
        workspace["user_tree_dirty"] = bool(workspace["user_tree_dirty"])
        return workspace

    def list_workspaces(self, case_id: str) -> list[dict[str, Any]]:
        """이 Case 의 저장소별 작업공간 전부. 실패한 것도 포함한다.

        **실패를 목록에서 빼지 않는다.** 빼면 "한 저장소는 준비되지 않았다"가
        화면에서 사라지고, 부분 준비 상태가 완전 준비로 보인다.
        """
        rows = self.conn.execute(
            "SELECT w.*, pr.name AS repository_name FROM case_workspace w"
            " JOIN project_repository pr ON pr.id = w.repository_id"
            " WHERE w.case_id = ? ORDER BY w.requested_at",
            (case_id,),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["user_tree_dirty"] = bool(item["user_tree_dirty"])
            items.append(item)
        return items

    def claim_workspace_requests(self, runner_id: str, limit: int = 5) -> list[dict[str, Any]]:
        """Runner 가 맡을 작업공간 준비 요청.

        아직 `requested` 인 것만 내려간다. **요청을 내려보내는 것이 준비 완료로
        표시하는 것은 아니다** — 상태는 Runner 가 실제 결과를 보고할 때 바뀐다.

        저장소 경로는 **`project_repository` 에서 온다**(P3-R2). `project.repo_path`
        는 남겨 두되 정본이 아니다 — 등록 저장소가 여럿이면 그 컬럼 하나로는 어느
        경로인지 말할 수 없다.

        이미 기록된 `worktree_path` 는 그대로 함께 내려보낸다. 준비가 실패한 뒤
        다시 요청했을 때 Runner 가 **그때 쓰던 자리를 다시 쓰게** 하기 위해서다 —
        새 규칙으로 경로를 옮기면 이미 그 worktree 에서 한 작업이 떨어져 나간다.
        """
        self.get_runner(runner_id)
        rows = self.conn.execute(
            "SELECT case_id, repository_id FROM case_workspace WHERE state = ?"
            " ORDER BY requested_at LIMIT ?",
            (WorkspaceState.REQUESTED.value, limit),
        ).fetchall()
        payloads = []
        for row in rows:
            workspace = self.get_workspace(row["case_id"], row["repository_id"])
            project = self.get_project(workspace["project_id"])
            repo = self.get_project_repository(workspace["repository_id"])
            workspace["repo_path"] = repo["repo_path"]
            workspace["repository_name"] = repo["name"]
            workspace["project_name"] = project["name"]
            payloads.append(workspace)
        return payloads

    def report_workspace_ready(
        self,
        case_id: str,
        runner_id: str,
        repo_path: str,
        worktree_path: str,
        branch: str,
        base_commit: str,
        base_ref: str,
        user_tree_dirty: bool,
        user_tree_entries: int,
        repository_id: str | None = None,
    ) -> dict[str, Any]:
        """Runner 가 실제로 만든 결과를 기록한다.

        **기준 커밋 SHA 가 없으면 받지 않는다.** "어떤 코드 위에서 시작했는가"를
        모르면 나중에 무엇이 바뀌었는지도 말할 수 없다(FR-08·FR-26).

        `user_tree_dirty` 는 준비 시점에 관측한 **사용자의 원래 작업 트리** 상태다.
        시스템이 그것을 정리하지 않았다는 사실을 남기기 위한 값이며, 파일 경로는
        올라오지 않고 수만 센다. **저장소마다 따로 센다** — 한 Case 가 두 저장소를
        쓰면 각 저장소의 사용자 변경은 서로 다른 것이다(P3-R2).
        """
        repository_id = self._workspace_target(case_id, repository_id)
        self.get_runner(runner_id)
        if not base_commit:
            raise ConflictError("a workspace cannot be ready without a base commit")
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE case_workspace SET state = ?, runner_id = ?, repo_path = ?,"
                " worktree_path = ?, branch = ?, base_commit = ?, base_ref = ?,"
                " user_tree_dirty = ?, user_tree_entries = ?, failure_reason = '',"
                " ready_at = ? WHERE case_id = ? AND repository_id = ?",
                (
                    WorkspaceState.READY.value,
                    runner_id,
                    repo_path,
                    worktree_path,
                    branch,
                    base_commit,
                    base_ref,
                    1 if user_tree_dirty else 0,
                    int(user_tree_entries),
                    utc_now(),
                    case_id,
                    repository_id,
                ),
            )
        return self.get_workspace(case_id, repository_id)

    def report_workspace_failed(
        self, case_id: str, runner_id: str, reason: str, repository_id: str | None = None
    ) -> dict[str, Any]:
        """만들 수 없었다. **실패를 준비됨으로 바꾸지 않는다.**

        사유를 남기는 이유는 사람이 무엇을 고쳐야 하는지 알아야 하기 때문이다 —
        저장소가 이 호스트에 없는 것과 브랜치가 이미 있는 것은 다른 조치를 부른다.

        **한 저장소의 실패가 다른 저장소의 준비를 되돌리지 않는다**(P3-R2). 이
        갱신은 그 한 행만 건드리며, 부분 준비 상태는 그대로 남아 화면에 드러난다.
        """
        repository_id = self._workspace_target(case_id, repository_id)
        self.get_runner(runner_id)
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE case_workspace SET state = ?, runner_id = ?, failure_reason = ?,"
                " ready_at = NULL WHERE case_id = ? AND repository_id = ?",
                (
                    WorkspaceState.FAILED.value,
                    runner_id,
                    reason[:MAX_SUMMARY],
                    case_id,
                    repository_id,
                ),
            )
        return self.get_workspace(case_id, repository_id)

    def _workspace_target(self, case_id: str, repository_id: str | None) -> str:
        """보고가 가리키는 작업공간 행을 정한다.

        저장소를 밝히지 않은 보고는 **행이 하나뿐일 때만** 해석한다. 둘 이상이면
        어느 저장소의 결과인지 지어내지 않는다 — 틀리게 짝지으면 한 저장소의 기준
        커밋이 다른 저장소의 것으로 기록된다.
        """
        if repository_id is not None:
            if self.get_workspace(case_id, repository_id) is None:
                raise NotFoundError(
                    f"workspace not requested for case: {case_id}/{repository_id}"
                )
            return repository_id
        rows = self.list_workspaces(case_id)
        if not rows:
            raise NotFoundError(f"workspace not requested for case: {case_id}")
        if len(rows) > 1:
            raise ConflictError(
                "this case has more than one workspace; the report must name a repository"
            )
        return rows[0]["repository_id"]

    def workspace_state(
        self, case_id: str, repository_id: str | None = None
    ) -> dict[str, Any]:
        """진입 검사가 보는 작업공간 상태. **없음을 준비됨으로 읽지 않는다.**

        `repository_id` 가 없고 작업공간이 **둘 이상**이면 어느 것인지 고르지 않고
        `target_recorded = False` 로 답한다. 진입 검사는 그것을
        `workspace_target_not_recorded` 로 거부한다 — 어느 저장소를 고칠지 모르는
        채로 쓰기를 여는 것이 이 단계에서 가장 비싼 실수다(P3-R2).
        """
        rows = self.list_workspaces(case_id)
        if repository_id is not None:
            rows = [r for r in rows if r["repository_id"] == repository_id]
        if not rows:
            return {"present": False, "state": None, "ready": False, "target_recorded": True}
        if len(rows) > 1:
            return {
                "present": True,
                "state": None,
                "ready": False,
                "target_recorded": False,
                "repository_count": len(rows),
            }
        workspace = rows[0]
        return {
            "present": True,
            "state": workspace["state"],
            "ready": workspace["state"] == WorkspaceState.READY.value,
            "target_recorded": True,
            "repository_id": workspace["repository_id"],
            "branch": workspace["branch"],
            "base_commit": workspace["base_commit"],
            "worktree_path": workspace["worktree_path"],
            "failure_reason": workspace["failure_reason"],
        }

    def task_repository_state(self, case_id: str, task_key: str) -> dict[str, Any]:
        """이 Task 가 **어느 저장소를 바꾸기로 했는가**(P3-04).

        진입 검사와 화면이 같은 값을 본다. `present = False` 는 그래프가 없거나 이
        Task 가 현재 그래프에 없다는 뜻이고, 그 상태는 `_check_work_graph` 가 이미
        본다 — 같은 사실로 두 번 거부하지 않는다.

        `choice_count` 가 **고를 것이 몇 개였는가**다. 하나면 계획이 말하지 않아도
        모호하지 않으므로 미기록을 묻지 않는다. 그것이 소급을 막는 조건이다 —
        저장소가 둘 이상인 Case 는 R2 이후에만 있다.
        """
        graph = self.current_work_graph_row(case_id)
        if graph is None:
            return {"present": False}
        row = self.conn.execute(
            "SELECT t.repository_id, t.repository_ref, t.cancelled,"
            " pr.name AS repository_name FROM task t"
            " LEFT JOIN project_repository pr ON pr.id = t.repository_id"
            " WHERE t.graph_revision_id = ? AND t.task_key = ?",
            (graph["id"], task_key),
        ).fetchone()
        if row is None:
            return {"present": False}
        return {
            "present": True,
            "repository_id": row["repository_id"],
            "repository_name": row["repository_name"],
            # 계획이 **적은 그대로**. 해석됐든 아니든 남긴다 — 버리면 "저장소를
            # 말하지 않은 계획"과 "선택 밖을 가리킨 계획"이 같은 모양이 된다.
            "repository_ref": row["repository_ref"],
            "choice_count": len(self._code_repository_ids(case_id)),
        }

    def workspace_view(self, case_id: str) -> dict[str, Any] | None:
        """작업공간과 그 위에서 일어난 실행 효과.

        **`unexpected_external_change` 는 저장하지 않고 도출한다.** 직전 실행이
        남긴 상태와 이번 실행이 시작할 때 본 상태를 비교할 뿐이며, 컬럼으로 두면
        "누가 그 값을 적었는가"라는 물음이 생긴다. Task 완료를 실행에서 도출하는
        것과 같은 이유다(P3-02 설계 선택 다).

        드러내기만 하고 **자동으로 되돌리거나 덮어쓰지 않는다.** 사용자가 직접
        worktree 를 고쳤을 수 있고, 그 변경을 보존하는 것이 FR-26의 요구다.
        """
        workspaces = self.list_workspaces(case_id)
        if not workspaces:
            return None
        by_repo = {w["repository_id"]: w for w in workspaces}
        for workspace in workspaces:
            workspace["run_effects"] = []

        rows = self.conn.execute(
            "SELECT run_id, task_id, purpose, permission, outcome, finished_at,"
            " repository_id, workspace_effect_json FROM run"
            " WHERE case_id = ? AND workspace_effect_json IS NOT NULL"
            " ORDER BY finished_at",
            (case_id,),
        ).fetchall()
        # **실행을 저장소별로 나눈다.** 한 Case 가 두 저장소를 고치면 "직전 실행이
        # 남긴 상태"도 저장소마다 다르다. 한 줄로 이어 붙이면 A 저장소 실행 뒤에 온
        # B 저장소 실행이 전부 `unexpected_external_change` 로 보인다.
        previous: dict[str, dict[str, Any]] = {}
        unattributed: list[dict[str, Any]] = []
        for row in rows:
            effect = json.loads(row["workspace_effect_json"])
            repository_id = row["repository_id"]
            # 대상이 기록되지 않은 실행(P3-R2 이전)은 작업공간이 하나뿐일 때만
            # 그 작업공간의 것으로 읽는다. 둘 이상이면 **어느 것인지 모른다** —
            # 아무 데나 붙이면 그 저장소의 이력이 거짓이 된다.
            if repository_id is None and len(workspaces) == 1:
                repository_id = workspaces[0]["repository_id"]
            item = {
                "run_id": row["run_id"],
                "task_id": row["task_id"],
                "purpose": row["purpose"],
                "permission": row["permission"],
                "outcome": row["outcome"],
                "finished_at": row["finished_at"],
                "repository_id": repository_id,
                "effect": effect,
                "unexpected_external_change": False,
            }
            if repository_id is None or repository_id not in by_repo:
                item["repository_recorded"] = False
                unattributed.append(item)
                continue
            item["repository_recorded"] = True
            last = previous.get(repository_id)
            if last is not None:
                # 직전 실행이 남긴 상태와 다른 자리에서 시작했다. 사람이 직접
                # 고쳤을 수 있으며 **되돌리지 않고 드러낸다**(FR-26).
                item["unexpected_external_change"] = (
                    last.get("head_after") != effect.get("head_before")
                    or last.get("entries_after") != effect.get("entries_before")
                )
            previous[repository_id] = effect
            by_repo[repository_id]["run_effects"].append(item)

        for workspace in workspaces:
            workspace["outside_workspace_changed"] = any(
                e["effect"].get("outside_workspace_changed")
                for e in workspace["run_effects"]
            )

        ready = [w for w in workspaces if w["state"] == WorkspaceState.READY.value]
        return {
            "case_id": case_id,
            "workspaces": workspaces,
            # 부분 준비를 완전 준비로 읽지 않는다. 하나라도 실패·대기면 이 값이 False 다.
            "all_ready": len(ready) == len(workspaces),
            "ready_count": len(ready),
            "repository_count": len(workspaces),
            # 대상 저장소가 기록되지 않은 실행. 숨기지 않고 따로 보인다.
            "unattributed_run_effects": unattributed,
            "composition": self.code_composition_view(case_id),
            "selection": self.case_repository_state(case_id),
            # 관측 한계를 값으로 남긴다. worktree 는 파일 배치의 분리이며 OS 격리가
            # 아니다(D-44). 화면이 이 문장을 그대로 보여 준다.
            "isolation": "worktree_file_layout_only",
            "isolation_note": (
                "worktree 는 파일 배치의 분리다. 다른 경로·자격증명 접근을 막는"
                " OS 격리가 아니며, 경계 밖 변경은 감지해 드러낼 뿐 막지 못한다"
            ),
        }

    # --------------------------------------------------------- 코드 조합 (P3-R2)
    #
    # `Repo ID → 정확한 스냅샷 참조` 의 벡터(execution-workspace-review 2.1절).
    #
    # **왜 필요한가.** 저장소가 여럿이면 "무엇을 검증했는가"를 브랜치 이름이나 파일
    # 경로로 말할 수 없다. 움직이는 이름이 아니라 고정된 조합으로 대상을 묶어야
    # 나중에 그 근거가 아직 유효한지 답할 수 있다.
    #
    # **관측을 새로 요구하지 않는다.** 조합은 이미 있는 기록 — 작업공간의 기준 커밋과
    # 실행이 보고한 효과 — 에서 만든다. 관측이 없는 저장소는 기준 커밋만 담고
    # `snapshot_incomplete` 로 표시한다. 기준 커밋만으로 실제 입력을 설명할 수 없다는
    # 사실을 빈칸이 아니라 **값으로** 남기는 것이다.

    def _compose_entries(self, case_id: str) -> list[dict[str, Any]]:
        """지금 이 Case 의 저장소별 스냅샷. 준비된 작업공간만 본다."""
        entries: list[dict[str, Any]] = []
        for workspace in self.list_workspaces(case_id):
            if workspace["state"] != WorkspaceState.READY.value:
                # 준비되지 않은 작업공간은 조합의 항목이 아니다. 기준 커밋조차 없다.
                continue
            row = self.conn.execute(
                "SELECT run_id, finished_at, workspace_effect_json FROM run"
                " WHERE case_id = ? AND repository_id = ?"
                " AND workspace_effect_json IS NOT NULL"
                " ORDER BY finished_at DESC LIMIT 1",
                (case_id, workspace["repository_id"]),
            ).fetchone()
            entry = {
                "repository_id": workspace["repository_id"],
                "repository_name": workspace["repository_name"],
                "base_commit": workspace["base_commit"],
                "head_commit": "",
                "dirty_entries": None,
                "tree_digest": "",
                "source": CompositionEntrySource.WORKSPACE_BASE.value,
                "observed_run_id": None,
                "observed_at": None,
            }
            if row is not None:
                effect = json.loads(row["workspace_effect_json"])
                entry.update(
                    {
                        "head_commit": effect.get("head_after") or "",
                        "dirty_entries": effect.get("entries_after"),
                        "tree_digest": effect.get("tree_digest_after") or "",
                        "source": CompositionEntrySource.RUN_EFFECT.value,
                        "observed_run_id": row["run_id"],
                        "observed_at": row["finished_at"],
                    }
                )
            entries.append(entry)
        entries.sort(key=lambda e: e["repository_id"])
        return entries

    @staticmethod
    def _composition_hash(entries: Iterable[dict[str, Any]]) -> str:
        """조합의 지문. 항목이 같으면 같은 값이다.

        **지문이지 본문이 아니다.** 들어가는 것은 식별자·SHA·수와 트리 지문뿐이며
        파일 경로도 diff 도 없다(D-43·NFR-12).
        """
        digest = hashlib.sha256()
        for entry in entries:
            digest.update(
                "|".join(
                    [
                        entry["repository_id"],
                        entry["base_commit"],
                        entry["head_commit"],
                        "" if entry["dirty_entries"] is None else str(entry["dirty_entries"]),
                        entry["tree_digest"],
                        entry["source"],
                    ]
                ).encode("utf-8")
            )
            digest.update(b"\x00")
        return digest.hexdigest()

    def resolve_case_repository_ref(self, case_id: str, ref: str) -> str | None:
        """계획이 적은 저장소 참조를 **이 Case 의 선택 안에서** 해석한다(P3-04).

        해석 범위가 선택된 저장소인 것이 핵심이다. Project 의 등록 저장소 전체에서
        찾으면 계획이 **선택 밖 저장소를 지목하는 것만으로** 허용이 넓어진 것처럼
        보인다 — R2 가 자동 추가의 세 경계로 막은 일이다(D-38·D-63·D-64). 선택 밖
        이름은 여기서 해석되지 않고 `repository_ref` 에 그대로 남아 사람이 무엇이
        어긋났는지 볼 수 있다.

        이름 비교는 대소문자를 구별하지 않는다. 등록 id 로 적어도 받는다.
        """
        value = " ".join(str(ref or "").split())
        if not value:
            return None
        rows = self.conn.execute(
            "SELECT r.repository_id, pr.name FROM case_repository r"
            " JOIN project_repository pr ON pr.id = r.repository_id"
            " WHERE r.case_id = ? AND r.state = ? AND r.selection_source <> ?",
            (case_id, PolicyState.CURRENT.value, RepositorySelectionSource.EXCLUDED.value),
        ).fetchall()
        candidates = [(r["repository_id"], r["name"]) for r in rows]
        if not candidates:
            # 선택 기록이 없는 이행된 Case 는 준비된 작업공간이 그 답이다
            # (`_code_repository_ids` 와 같은 규칙). 없던 선택을 지어내지 않는다.
            candidates = [
                (w["repository_id"], w["repository_name"])
                for w in self.list_workspaces(case_id)
            ]
        lowered = value.casefold()
        for repository_id, name in candidates:
            if repository_id == value or str(name).casefold() == lowered:
                return repository_id
        return None

    def _code_repository_ids(self, case_id: str) -> set[str]:
        """이 Case 가 코드를 바꿔도 되는 저장소들.

        선택 기록이 없는 이행된 Case 는 준비된 작업공간이 그 답이다 — 없던 선택을
        지어내지 않고 실제로 열린 작업공간을 센다.
        """
        rows = self.conn.execute(
            "SELECT repository_id FROM case_repository"
            " WHERE case_id = ? AND state = ? AND code_write_allowed = 1"
            " AND selection_source <> ?",
            (case_id, PolicyState.CURRENT.value, RepositorySelectionSource.EXCLUDED.value),
        ).fetchall()
        selected = {r["repository_id"] for r in rows}
        if selected:
            return selected
        return {
            w["repository_id"]
            for w in self.list_workspaces(case_id)
            if w["state"] == WorkspaceState.READY.value
        }

    def build_code_composition(self, case_id: str) -> dict[str, Any] | None:
        """지금 상태로 코드 조합을 **고정한다**. 없으면 `None`.

        같은 상태에서 다시 부르면 **새 revision 을 만들지 않고** 현재 조합을 그대로
        돌려준다. 상태가 달라졌으면 새 revision 이 생기고 이전 것은 `superseded` 가
        된다 — 지우지 않는 이유는 "그때 무엇을 검증했는가"가 남아야 하기 때문이다.
        """
        self.get_case(case_id)
        entries = self._compose_entries(case_id)
        if not entries:
            return None
        composition_hash = self._composition_hash(entries)
        current = self.conn.execute(
            "SELECT * FROM code_composition WHERE case_id = ? AND state = ?",
            (case_id, PolicyState.CURRENT.value),
        ).fetchone()
        covered = {e["repository_id"] for e in entries} >= self._code_repository_ids(case_id)
        # **같음의 기준에 통합 범위가 들어간다.** 항목이 그대로여도 이 Case 가 코드를
        # 바꿔도 되는 저장소가 늘면 이 조합은 더 이상 전부를 담지 않는다. 지문만
        # 비교하면 그때 옛 조합이 `integration_verified = true` 인 채로 살아남아,
        # 담지도 않은 저장소의 통합이 검증됐다고 말하게 된다(2.1절).
        if (
            current is not None
            and current["composition_hash"] == composition_hash
            and bool(current["covers_all_code_repositories"]) == covered
        ):
            return self.get_code_composition(current["id"])

        composition_id = ids.new_id("comp")
        now = utc_now()
        row = self.conn.execute(
            "SELECT MAX(revision) AS r FROM code_composition WHERE case_id = ?", (case_id,)
        ).fetchone()
        revision = (row["r"] or 0) + 1
        with transaction(self.conn):
            if current is not None:
                self.conn.execute(
                    "UPDATE code_composition SET state = ?, superseded_at = ? WHERE id = ?",
                    (PolicyState.SUPERSEDED.value, now, current["id"]),
                )
            self.conn.execute(
                "INSERT INTO code_composition"
                " (id, case_id, revision, composition_hash, covers_all_code_repositories,"
                "  state, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    composition_id,
                    case_id,
                    revision,
                    composition_hash,
                    1 if covered else 0,
                    PolicyState.CURRENT.value,
                    now,
                ),
            )
            for entry in entries:
                self.conn.execute(
                    "INSERT INTO code_composition_entry"
                    " (composition_id, repository_id, base_commit, head_commit,"
                    "  dirty_entries, tree_digest, source, observed_run_id, observed_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        composition_id,
                        entry["repository_id"],
                        entry["base_commit"],
                        entry["head_commit"],
                        entry["dirty_entries"],
                        entry["tree_digest"],
                        entry["source"],
                        entry["observed_run_id"],
                        entry["observed_at"],
                    ),
                )
        return self.get_code_composition(composition_id)

    def get_code_composition(self, composition_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM code_composition WHERE id = ?", (composition_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"code composition not found: {composition_id}")
        composition = dict(row)
        composition["covers_all_code_repositories"] = bool(
            composition["covers_all_code_repositories"]
        )
        rows = self.conn.execute(
            "SELECT e.*, pr.name AS repository_name FROM code_composition_entry e"
            " JOIN project_repository pr ON pr.id = e.repository_id"
            " WHERE e.composition_id = ? ORDER BY e.repository_id",
            (composition_id,),
        ).fetchall()
        entries = []
        for entry in rows:
            item = dict(entry)
            # **기준 커밋만으로는 실제 입력을 설명할 수 없다.** 그 사실을 빈칸이
            # 아니라 값으로 남긴다(execution-workspace-review 2.1절).
            item["snapshot_incomplete"] = (
                item["source"] == CompositionEntrySource.WORKSPACE_BASE.value
            )
            entries.append(item)
        composition["entries"] = entries
        composition["snapshot_complete"] = not any(e["snapshot_incomplete"] for e in entries)
        # **개별 저장소 통과를 통합 통과로 자동 승격하지 않는다**(2.1절). 조합이 이
        # Case 의 코드 대상을 전부 담지 않았다면 통합은 검증되지 않은 것이다.
        composition["integration_verified"] = composition["covers_all_code_repositories"]
        if not composition["integration_verified"]:
            composition["integration_detail"] = (
                "이 조합은 이 Case 의 코드 대상 저장소를 전부 담지 않았다."
                " 개별 저장소 검사가 통과해도 통합 조건을 충족했다고 보지 않는다"
            )
        return composition

    def code_composition_view(self, case_id: str) -> dict[str, Any] | None:
        """현재 조합과 그 이력. **조회가 새 조합을 만들지 않는다.**"""
        row = self.conn.execute(
            "SELECT id FROM code_composition WHERE case_id = ? AND state = ?",
            (case_id, PolicyState.CURRENT.value),
        ).fetchone()
        if row is None:
            return None
        composition = self.get_code_composition(row["id"])
        # 기록된 조합과 **지금** 상태가 같은가. 다르면 다시 고정해야 한다는 뜻이며,
        # 여기서 조용히 갱신하지 않는다 — 근거가 가리키는 조합이 손 없이 바뀌면
        # "그때 무엇을 검증했는가"의 답이 사라진다.
        composition["matches_current_state"] = composition["composition_hash"] == (
            self._composition_hash(self._compose_entries(case_id))
        )
        return composition

    def composition_validity(
        self, case_id: str, composition_id: str | None
    ) -> dict[str, Any]:
        """그 근거가 가리키는 조합이 **아직 유효한가**. 저장하지 않고 도출한다.

        핵심은 **저장소별로** 본다는 것이다. 조합에 들어 있지 않은 저장소가 바뀐 것은
        이 근거와 무관하며, 그것으로 증거를 폐기하면 "무관한 Repo 변경으로 모든
        증거를 폐기하지 않는다"(2.1절)가 깨진다. 실제 의존성이 바뀐 것만 재평가한다.
        """
        if composition_id is None:
            return {
                "composition_id": None,
                "linked": False,
                "detail": "이 근거는 코드 조합을 가리키지 않는다. 조합 개념이 없던"
                " 시절의 기록이거나 코드와 무관한 근거다",
            }
        composition = self.get_code_composition(composition_id)
        current = {e["repository_id"]: e for e in self._compose_entries(case_id)}
        changed: list[str] = []
        for entry in composition["entries"]:
            now = current.get(entry["repository_id"])
            if now is None:
                changed.append(entry["repository_id"])
                continue
            if (
                now["base_commit"] != entry["base_commit"]
                or now["head_commit"] != entry["head_commit"]
                or now["dirty_entries"] != entry["dirty_entries"]
                or now["tree_digest"] != entry["tree_digest"]
            ):
                changed.append(entry["repository_id"])
        return {
            "composition_id": composition_id,
            "linked": True,
            "composition_hash": composition["composition_hash"],
            "changed_repositories": changed,
            "stale": bool(changed),
            "integration_verified": composition["integration_verified"],
            "snapshot_complete": composition["snapshot_complete"],
            "detail": "이 조합에 든 저장소만 본다. 들어 있지 않은 저장소의 변경은"
            " 이 근거를 무효로 만들지 않는다",
        }

    # ------------------------------------------------------------ 쓰기 경합

    def unfinished_write_runs(
        self, case_id: str | None = None, runner_id: str | None = None
    ) -> list[dict[str, Any]]:
        """아직 끝나지 않은 쓰기 실행.

        **`finished` 가 아닌 모든 상태를 센다.** `pending` 도 포함하는 이유는,
        배정되기 전의 쓰기 요청이 이미 그 Case 의 다음 쓰기 자리를 잡고 있기
        때문이다. 이것을 빼면 두 요청이 동시에 통과한 뒤 둘 다 배정된다.
        """
        permissions = WRITE_PERMISSIONS
        clauses = [
            "status <> ?",
            "permission IN (" + ", ".join("?" for _ in permissions) + ")",
        ]
        params: list[Any] = [RunStatus.FINISHED.value, *permissions]
        if case_id is not None:
            clauses.append("case_id = ?")
            params.append(case_id)
        if runner_id is not None:
            clauses.append("assigned_runner_id = ?")
            params.append(runner_id)
        rows = self.conn.execute(
            "SELECT run_id, case_id, task_id, status, permission FROM run WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def write_slot_state(self, runner_id: str) -> dict[str, Any]:
        """그 Runner 가 지금 쓰기를 맡을 수 있는가(FR-26 "동일 Runner 쓰기 기본 1개").

        **이것은 진입 거부가 아니다.** 자리가 없으면 그 실행은 `pending` 으로
        남았다가 앞의 쓰기가 끝나면 그대로 배정된다. 화면이 "왜 아직 시작되지
        않는가"를 답할 수 있도록 상태로 내보낸다.
        """
        in_flight = self.unfinished_write_runs(runner_id=runner_id)
        return {
            "runner_id": runner_id,
            "limit": RUNNER_WRITE_LIMIT,
            "in_flight": in_flight,
            "available": len(in_flight) < RUNNER_WRITE_LIMIT,
            "deferral_reason": None if len(in_flight) < RUNNER_WRITE_LIMIT else ClaimDeferral.RUNNER_WRITE_SLOT_BUSY.value,
        }

    # ----------------------------------------------------------- 실행한 명령

    def record_run_commands(
        self, run_id: str, generation: int, commands: Iterable[dict[str, Any]]
    ) -> int:
        """그 실행이 실제로 실행한 명령. **원문은 올라오지 않는다.**

        같은 `(run_id, seq)` 재전송은 새 행을 만들지 않는다 — 이벤트와 같은 규칙이다.
        `exit_code` 가 `None` 인 것은 "끝을 확인하지 못했다"이며 실패가 아니다.
        """
        self._check_generation(run_id, generation)
        stored = 0
        with transaction(self.conn):
            for command in commands:
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO run_command"
                    " (run_id, seq, command_summary, exit_code, duration_ms, started_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        int(command["seq"]),
                        str(command.get("command_summary", ""))[:MAX_SUMMARY],
                        command.get("exit_code"),
                        command.get("duration_ms"),
                        command.get("started_at") or utc_now(),
                    ),
                )
                stored += cur.rowcount
        return stored

    def list_run_commands(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM run_command WHERE run_id = ? ORDER BY seq", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # =================================================== P3-R1 정책·Profile
    #
    # R1 이 만든 것은 **기록**이다. 그 위에 강제가 하나씩 붙었다 — R2 가 저장소
    # 선택·쓰기 허용을, R3 이 예산을 실제 판단으로 바꿨다. **Autonomy 에 따른 진입
    # 조건과 확인 지점은 아직 R4 이고 게시는 P5 다.** 어느 축이 지금 무엇을 하는지는
    # `ENFORCEMENT` 표가 말하며 조회에 그대로 실려 나간다.

    #: 각 정책 축을 **지금 누가 강제하는가.** 조회에 그대로 실려 나간다.
    #:
    #: 이 표가 필요한 이유는, 값이 저장된다는 사실과 값이 동작을 바꾼다는 사실이
    #: 다르기 때문이다. hard 예산을 설정한 사람이 "이제 초과하지 않는다"고 믿으면
    #: 그것은 우리가 지원하지 않는 보장을 표시한 것이다(DEVELOPMENT.md 3절).
    ENFORCEMENT: dict[str, dict[str, str]] = {
        # **P3-R4에서 바뀐 축.** Autonomy 가 진입 조건과 완료 경로를 실제로 정한다.
        # 다만 방향이 둘이다 — controlled 는 **막고** ask-on-decision 은 **연다**.
        # 둘을 한 문장으로 "강제한다"고 쓰면 기본 Case 에서 무엇이 달라졌는지가
        # 보이지 않는다.
        "autonomy": {
            "state": "enforced",
            "enforced_by": "P3-R4",
            "detail": "controlled 는 시작 확인 전에 설계·계획·구현·검증·실험을"
            " 배정하지 않는다. ask-on-decision 은 명확한 요청을 그 범위의 실행 위임으로"
            " 인정해 추가 승인 없이 진행하고 조건 충족 시 자동 완료한다. 단계 검토"
            " 기본값도 여기서 도출된다. 기록되지 않은 Autonomy(R1 이전)는 controlled"
            " 로 **취급**하되 값은 여전히 미기록이다",
        },
        "controlled_checkpoint": {
            "state": "enforced",
            "enforced_by": "P3-R4",
            "detail": "시작 확인은 작업 실행을, 결과 후보 확인은 종료를 막는다. 확인한"
            " 후보의 내용이 바뀌면 이전 확인을 새 후보에 쓰지 않으며, 같은 내용의"
            " 재전송에는 재확인을 요구하지 않는다. 확인이 push·게시 권한을 만들지는"
            " 않는다 — 실제 게시는 P5 다",
        },
        # **P3-R3에서 바뀐 축.** 한도가 실제로 배정을 정한다. 다만 지표마다 약속할
        # 수 있는 것이 달라서 한 문장으로 "강제한다"고 쓰지 않는다 — 실행 수·컨텍스트
        # 크기는 절대 상한이고 시간은 새 배정만 막는다(`reservation_contract`).
        "budget": {
            "state": "enforced",
            "enforced_by": "P3-R3",
            "detail": "예약·누적·정산이 동작하고 hard 도달은 그 한도를 소비하는 새 실행"
            "·재배정을 막는다. 보장 범위는 지표마다 다르다 — 실행 수·검토 수·컨텍스트"
            " 크기는 절대 상한이고, 시간 지표는 새 배정만 막으며 진행 중 실행의 초과"
            " 노출이 있을 수 있다. 토큰·비용의 hard 한도는 여전히 설정을 받지 않는다",
        },
        # **P3-R2에서 바뀐 축.** 선택과 쓰기 허용은 이제 작업공간을 만들 수 있는지를
        # 실제로 정한다. 게시 허용은 아래 `publish` 가 따로 말하며 여전히 기록일
        # 뿐이다 — 쓰기 허용이 게시 허용으로 번지지 않는다(D-64).
        "repository_selection": {
            "state": "enforced",
            "enforced_by": "P3-R2",
            "detail": "선택·쓰기 허용이 Case×Repo 작업공간을 정한다. 미선택·명시 제외·"
            "쓰기 미허용·기록 저장소는 작업공간이 만들어지지 않는다. 허용 내 자동 추가는"
            " 기록되고 허용 밖은 사람 확인으로 되돌린다",
        },
        "publish": {
            "state": "not_implemented",
            "enforced_by": "P5",
            "detail": "실제 push·PR·기록 이슈 게시는 구현되지 않았다",
        },
    }

    # ------------------------------------------------------------ Profile

    def case_profile(self, case_id: str) -> dict[str, Any]:
        """이 Case 의 Profile 기록과 그 정의.

        **기록되지 않은 Case 를 `kind` 에서 유도해 채우지 않는다.** 유도는 사람의
        선택이 아니고, 채우면 그 Case 의 기존 의도 버전이 갑자기 Profile 필수 항목을
        빠뜨린 문서가 된다(D-62).
        """
        case = self.get_case(case_id)
        profile = case.get("profile")
        version = case.get("profile_version")
        if profile is None or version is None:
            return {
                "profile": None,
                "version": None,
                "source": ProfileSource.NOT_RECORDED.value,
                "definition": None,
                "required_fields": sorted(profiles.required_fields(None, None)),
                "kind": case["kind"],
                "detail": "R1 이전에 만들어진 Case 다. Profile 이 기록되지 않았으며"
                " 의도 초안은 공통 여섯 항목을 쓴다",
            }
        definition = profiles.resolve(profile, version)
        return {
            "profile": profile,
            "version": version,
            "source": case.get("profile_source") or ProfileSource.EXPLICIT.value,
            "definition": definition.to_dict(),
            "required_fields": list(definition.required_fields),
            "kind": case["kind"],
            "detail": None,
        }

    def required_intent_fields(self, case_id: str) -> frozenset[str]:
        """그 Case 의 구조 보고가 가져야 하는 항목. 게이트와 구조 검사가 함께 쓴다."""
        case = self.get_case(case_id)
        return profiles.required_fields(case.get("profile"), case.get("profile_version"))

    # ------------------------------------------------ P4-03 완료 의미

    def completion_contract(self, case_id: str) -> profiles.CompletionContract | None:
        """그 Case 의 완료 계약. **기록된 정의판으로 조회한다.**

        v1 Case 와 Profile 미기록 Case 는 `None` 이다. 현재 정의판으로 대신 답하면
        기존 Case 에 새 완료 규칙이 조용히 소급된다(D-62).
        """
        case = self.get_case(case_id)
        return profiles.completion_contract(case.get("profile"), case.get("profile_version"))

    def _experiment_run_rows(self, case_id: str) -> list[dict[str, Any]]:
        """실험 정리 상태를 도출하는 데 필요한 실행 행. **시작 순**이다."""
        rows = self.conn.execute(
            "SELECT run_id, status, outcome, permission, is_experiment, repository_id,"
            " workspace_effect_json FROM run WHERE case_id = ?"
            " ORDER BY created_at, run_id",
            (case_id,),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            raw = item.pop("workspace_effect_json")
            item["workspace_effect"] = json.loads(raw) if raw else None
            result.append(item)
        return result

    def completion_meaning(self, case_id: str) -> dict[str, Any]:
        """이 Case 의 **완료 의미의 현재 상태**(P4-03). 저장하지 않고 도출한다.

        요구된 목적 의무마다 어떤 기준이 있고 몇 건이 충족됐는지, 기준이 하나도 없는
        목적, 실험의 정리 상태를 한 곳에서 계산한다. 조회·후보·완료 검사가 모두 이
        값을 본다 — 두 벌로 계산하면 한쪽만 고치는 실수가 생긴다.

        조건부 의무(maintenance 의 보존)는 **최신 의도 버전의 항목이 채워졌는가**로
        정한다. 항목 상태는 구조 보고의 값이며 본문을 읽은 것이 아니다.
        """
        case = self.get_case(case_id)
        contract = profiles.completion_contract(case.get("profile"), case.get("profile_version"))
        latest = self.latest_intent_version(case_id)
        declared: list[str] | None = None
        filled: list[str] = []
        if latest is not None:
            if latest.get("objectives_json"):
                declared = json.loads(latest["objectives_json"])
            filled = [
                f["field"]
                for f in self.list_intent_fields(latest["id"])
                if f["state"] != ConfirmationState.UNDECIDED.value
            ]
        return meaningmod.evaluate(
            profile=case.get("profile"),
            version=case.get("profile_version"),
            contract=contract,
            declared=declared,
            filled_fields=filled,
            criteria=self.current_criteria(case_id),
            runs=self._experiment_run_rows(case_id),
        )

    # ------------------------------------------------------------ Autonomy

    def _current_policy_row(self, case_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM case_policy WHERE case_id = ? AND state = ?"
            " ORDER BY revision DESC LIMIT 1",
            (case_id, PolicyState.CURRENT.value),
        ).fetchone()
        return _row_to_dict(row)

    def effective_policy(self, case_id: str) -> dict[str, Any]:
        """이 Case 에 **지금 적용되는** 정책과 그 출처.

        우선순위는 `Case 명시 → 시스템 기본값` 이다. Task·Project 단위 조정은 아직
        없으므로 출처 값으로도 만들지 않는다 — 조회에 "Project 기본값에서 왔다"가
        나타나면 사람이 없는 설정 화면을 찾게 된다(autonomy-budget-policy 5절).

        **`autonomy = None` 을 기본값으로 바꾸지 않는다.** R1 이전 Case 는 미기록이며
        그 상태로 표시된다.
        """
        case = self.get_case(case_id)
        row = self._current_policy_row(case_id)
        if row is None:
            # R1 이후에 만든 Case 는 생성 시점에 행을 받는다. 그래도 없을 수 있는
            # 경우(직접 SQL 삽입 등)를 기본값으로 답하되 출처를 시스템 기본값으로 둔다.
            autonomy: str | None = Autonomy.ASK_ON_DECISION.value
            source = AutonomySource.SYSTEM_DEFAULT.value
            policy_version = POLICY_VERSION
            revision = 0
            recorded = False
        else:
            autonomy = row["autonomy"]
            source = row["autonomy_source"]
            policy_version = row["policy_version"]
            revision = row["revision"]
            recorded = autonomy is not None
        effective = self.effective_autonomy(case_id)
        return {
            "case_id": case_id,
            "revision": revision,
            "autonomy": autonomy,
            "autonomy_source": source,
            "autonomy_recorded": recorded,
            "policy_version": policy_version,
            "default_autonomy": Autonomy.ASK_ON_DECISION.value,
            # WorkDepth 는 별도 축이며 수준 판단이 만든다(P3-01). 여기서 복제하지
            # 않고 참조만 한다 — 두 곳에 두면 한쪽만 바뀐다.
            "work_depth": (lambda level: level.value if level else None)(
                self.current_level(case_id)
            ),
            "work_depth_source": "sizing_assessment",
            "completion_mode": self.completion_mode(case_id).value,
            "completion_mode_source": self.completion_mode_state(case_id)["source"],
            # **적용되는 Autonomy 와 그 출처**(P3-R4). 저장된 값과 다를 수 있으며
            # 다른 경우가 정확히 하나다 — R1 이전 Case 의 controlled 취급.
            **effective.to_dict(),
            "fast_lane": self.fast_lane_state(case_id),
            "conformance": self.conformance_state(case_id),
            "material_delta": self.material_delta_state(case_id),
            "profile": self.case_profile(case_id),
            "checkpoints": self.list_checkpoints(case_id),
            "budget": self.budget_state(case_id),
            "delegation_basis": self.list_delegation_basis(case_id),
            "repositories": self.case_repository_state(case_id),
            "enforcement": self.ENFORCEMENT,
            "case_status": case["status"],
        }

    def set_autonomy(
        self,
        case_id: str,
        autonomy: Autonomy,
        set_by: str,
        reason_summary: str | None = None,
    ) -> dict[str, Any]:
        """Autonomy 를 명시로 설정한다. **이전 값은 지우지 않고 대체한다.**

        종료된 Case 는 거부한다. 종료 뒤 정책을 바꾸면 그 Case 의 종료 기록이 어떤
        규칙으로 확정됐는지 알 수 없게 된다(D-33).

        controlled 로 바꾸면 확인 지점이 `required` 로 생긴다. ask-on-decision 으로
        되돌리면 **이미 확인한 기록은 남고** 남은 `required` 만 정리한다 — 사람이
        실제로 확인한 사실은 설정 변경으로 없어지지 않는다.
        """
        self._guard_policy_change(case_id)
        now = utc_now()
        current = self._current_policy_row(case_id)
        revision = (current["revision"] + 1) if current else 1
        policy_id = ids.new_id("pol")
        with transaction(self.conn):
            if current is not None:
                self.conn.execute(
                    "UPDATE case_policy SET state = ?, superseded_at = ? WHERE id = ?",
                    (PolicyState.SUPERSEDED.value, now, current["id"]),
                )
            self.conn.execute(
                "INSERT INTO case_policy"
                " (id, case_id, revision, autonomy, autonomy_source, policy_version,"
                "  set_by, reason_summary, state, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    policy_id,
                    case_id,
                    revision,
                    autonomy.value,
                    AutonomySource.CASE_EXPLICIT.value,
                    POLICY_VERSION,
                    set_by,
                    _summary(reason_summary) if reason_summary else None,
                    PolicyState.CURRENT.value,
                    now,
                ),
            )
            if autonomy is Autonomy.CONTROLLED:
                for checkpoint in ControlledCheckpoint:
                    existing = self.conn.execute(
                        "SELECT id FROM controlled_checkpoint"
                        " WHERE case_id = ? AND checkpoint = ? AND state IN (?, ?)",
                        (
                            case_id,
                            checkpoint.value,
                            CheckpointState.REQUIRED.value,
                            CheckpointState.CONFIRMED.value,
                        ),
                    ).fetchone()
                    if existing is not None:
                        continue
                    self.conn.execute(
                        "INSERT INTO controlled_checkpoint"
                        " (id, case_id, policy_id, checkpoint, state, created_at)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            ids.new_id("chk"),
                            case_id,
                            policy_id,
                            checkpoint.value,
                            CheckpointState.REQUIRED.value,
                            now,
                        ),
                    )
            else:
                # 요구가 사라졌다. **확인한 기록은 건드리지 않는다.**
                self.conn.execute(
                    "DELETE FROM controlled_checkpoint WHERE case_id = ? AND state = ?",
                    (case_id, CheckpointState.REQUIRED.value),
                )
        return self.effective_policy(case_id)

    def list_policy_revisions(self, case_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM case_policy WHERE case_id = ? ORDER BY revision",
            (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _guard_policy_change(self, case_id: str) -> None:
        if self.case_is_closed(case_id):
            raise PolicyRefused([PolicyRefusal.CASE_ALREADY_CLOSED])

    # -------------------------------------------------------- 위임 근거

    def record_delegation_basis(
        self,
        case_id: str,
        basis_kind: DelegationBasisKind,
        summary: str,
        artifact_id: str | None = None,
        artifact_rev: int | None = None,
        decision_id: str | None = None,
    ) -> dict[str, Any]:
        """자동 진행의 근거를 기록한다(D-60).

        원문 참조를 주면 그 시점의 해시를 함께 남긴다. 나중에 원문이 바뀌면 근거가
        바뀐 것이고, 그 비교가 누적 material delta 판단의 입력이다(R4).

        이전 근거는 `superseded` 로 남는다. **지우지 않는 이유**는 "마지막 유효
        위임과 비교한다"가 D-60의 규칙이고, 그러려면 그 이전 값들이 있어야 한다.
        """
        self._guard_policy_change(case_id)
        self.get_case(case_id)
        content_hash: str | None = None
        if artifact_id is not None and artifact_rev is not None:
            ref = self.get_artifact_ref(artifact_id, artifact_rev)
            content_hash = ref["content_hash"]
        now = utc_now()
        row = self.conn.execute(
            "SELECT * FROM delegation_basis WHERE case_id = ? ORDER BY revision DESC LIMIT 1",
            (case_id,),
        ).fetchone()
        revision = (row["revision"] + 1) if row is not None else 1
        basis_id = ids.new_id("deleg")
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE delegation_basis SET state = ?, superseded_at = ?"
                " WHERE case_id = ? AND state = ?",
                (PolicyState.SUPERSEDED.value, now, case_id, PolicyState.CURRENT.value),
            )
            self.conn.execute(
                "INSERT INTO delegation_basis"
                " (id, case_id, revision, basis_kind, artifact_id, artifact_rev,"
                "  content_hash, decision_id, summary, state, recorded_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    basis_id,
                    case_id,
                    revision,
                    basis_kind.value,
                    artifact_id,
                    artifact_rev,
                    content_hash,
                    decision_id,
                    _summary(summary),
                    PolicyState.CURRENT.value,
                    now,
                ),
            )
        return self.list_delegation_basis(case_id)

    def list_delegation_basis(self, case_id: str) -> dict[str, Any]:
        rows = self.conn.execute(
            "SELECT * FROM delegation_basis WHERE case_id = ? ORDER BY revision",
            (case_id,),
        ).fetchall()
        items = [dict(r) for r in rows]
        current = [i for i in items if i["state"] == PolicyState.CURRENT.value]
        return {
            "current": current[-1] if current else None,
            "history": items,
            "detail": "AI 초안은 근거가 아니다. 누적 material delta 판단은 P3-R4 다",
        }

    # ------------------------------------------------ controlled 체크포인트

    def list_checkpoints(self, case_id: str) -> list[dict[str, Any]]:
        """확인 지점 목록.

        **취급 중인 Case 의 요구는 도출한다**(P3-R4). `autonomy = NULL` 인 Case 를
        controlled 로 취급하기로 했으므로 확인 지점이 요구되지만, 그 행을 조회할
        때마다 만들어 넣으면 읽기 경로가 쓰기가 된다. 그래서 **확인되기 전까지는
        도출하고**, 사람이 실제로 확인할 때 행을 만든다(`_ensure_treated_checkpoints`).

        도출된 항목은 `note_summary` 로 "사람이 고른 설정"과 구별된다.
        """
        rows = self.conn.execute(
            "SELECT * FROM controlled_checkpoint WHERE case_id = ? ORDER BY created_at",
            (case_id,),
        ).fetchall()
        points = [dict(r) for r in rows]
        autonomy = self.effective_autonomy(case_id)
        if not (autonomy.is_treatment and autonomy.controlled):
            return points
        live = {
            p["checkpoint"]
            for p in points
            if p["state"] != CheckpointState.SUPERSEDED.value
        }
        for checkpoint in ControlledCheckpoint:
            if checkpoint.value in live:
                continue
            points.append(
                {
                    "id": None,
                    "case_id": case_id,
                    "policy_id": None,
                    "checkpoint": checkpoint.value,
                    "state": CheckpointState.REQUIRED.value,
                    "subject_type": None,
                    "subject_id": None,
                    "subject_hash": None,
                    "decision_id": None,
                    "confirmed_by": None,
                    "confirmed_at": None,
                    "note_summary": self.TREATED_CHECKPOINT_NOTE,
                    "created_at": None,
                    "superseded_at": None,
                    "derived": True,
                }
            )
        return points

    def confirm_checkpoint(
        self,
        case_id: str,
        checkpoint: ControlledCheckpoint,
        confirmed_by: str,
        explicit: bool,
        subject_type: str,
        subject_id: str,
        subject_hash: str | None = None,
        note_summary: str | None = None,
    ) -> dict[str, Any]:
        """사람이 그 확인 지점을 **실제로** 확인했다고 기록한다(D-65).

        네 가지를 거부한다.

            종료된 Case                     설정과 같은 이유다
            명시적 확인이 아닌 요청         "진행하라"가 아닌 것을 확인으로 적지 않는다
            controlled 가 아닌 Case         요구되지 않은 확인을 만들지 않는다
            이미 확인한 대상과 다른 대상    새 대상은 새 확인이다(FR-23)

        **이 기록이 권한을 만들지 않는다.** push·게시 허용은 `decision`,
        최종 인수는 `final_acceptance` 의 별도 기록이다(D-32·D-65).
        """
        self._guard_policy_change(case_id)
        if not explicit:
            raise PolicyRefused([PolicyRefusal.NOT_EXPLICIT])
        now = utc_now()
        with transaction(self.conn):
            # 취급 중인 Case 는 요구가 도출돼 있을 뿐 행이 없다. 사람이 실제로
            # 확인하는 **이 시점에** 행을 만든다 — 조회가 쓰기를 하지 않게 하면서
            # 확인 기록은 정상 경로와 같은 표에 남는다.
            self._ensure_treated_checkpoints(case_id)
        row = self.conn.execute(
            "SELECT * FROM controlled_checkpoint"
            " WHERE case_id = ? AND checkpoint = ? AND state = ?",
            (case_id, checkpoint.value, CheckpointState.REQUIRED.value),
        ).fetchone()
        if row is None:
            raise PolicyRefused([PolicyRefusal.CHECKPOINT_NOT_REQUIRED])
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE controlled_checkpoint SET state = ?, subject_type = ?,"
                " subject_id = ?, subject_hash = ?, confirmed_by = ?, confirmed_at = ?,"
                " note_summary = ? WHERE id = ?",
                (
                    CheckpointState.CONFIRMED.value,
                    subject_type,
                    subject_id,
                    subject_hash,
                    confirmed_by,
                    now,
                    _summary(note_summary) if note_summary else None,
                    row["id"],
                ),
            )
        if checkpoint is ControlledCheckpoint.RESULT_CANDIDATE:
            # **확인 뒤에는 시스템이 종료를 확정한다**(D-65 "…필요 외부 CI → 시스템
            # 종료"). 사람이 또 한 번 "완료" 를 눌러야 하면 같은 내용의 확인을
            # 두 번 요구하는 것이다(completion-lifecycle 3절 "결과 확인 뒤 같은
            # 후보의 외부 조건이 충족되면 추가 인수 없이 완료한다").
            #
            # 남은 조건이 있으면 **확인만 기록되고 종료는 보류된다.** 확인을 되돌리지
            # 않는다 — 사람이 실제로 본 사실은 조건이 갖춰지지 않았다고 사라지지 않는다.
            self._close_after_controlled_confirmation(case_id, subject_id, confirmed_by)
        return self.list_checkpoints(case_id)

    def _close_after_controlled_confirmation(
        self, case_id: str, candidate_id: str, actor: str
    ) -> None:
        """결과 후보 확인 뒤의 종료 시도. **조건이 없으면 조용히 보류한다.**

        인수의 주체는 확인한 사람이고 모드는 `human` 이다. 정책 식별자로 적지
        않는다 — 여기에는 실제 사람의 확인이 있었다(FR-17 "자동 완료를 사람 확인으로
        적지 않는다"의 반대 방향도 같다).
        """
        try:
            candidate = self.get_completion_candidate(candidate_id)
        except NotFoundError:
            return
        if candidate["case_id"] != case_id or candidate["acceptance"] is not None:
            return
        if self.check_acceptance(candidate_id, AcceptanceMode.HUMAN):
            return
        self.record_final_acceptance(candidate_id, actor=actor, mode=AcceptanceMode.HUMAN)

    def supersede_checkpoint(
        self, case_id: str, checkpoint: ControlledCheckpoint, reason_summary: str
    ) -> list[dict[str, Any]]:
        """확인한 대상이 바뀌었다. 확인 기록을 남기고 새 요구를 만든다(D-65·FR-23).

        확인 기록을 지우고 다시 `required` 로 돌리지 않는 이유는 "무엇을 보고
        확인했는가"가 남아야 하기 때문이다. 같은 내용의 재전송에는 이 함수를 쓰지
        않는다 — 그 경우는 재확인을 요구하지 않는다.
        """
        self._guard_policy_change(case_id)
        policy = self._current_policy_row(case_id)
        # **취급 중인 Case 도 대상이다**(P3-R4). 저장된 값이 아니라 적용되는 값으로
        # 판단한다 — `autonomy = NULL` 인 Case 도 controlled 로 취급되므로 확인한
        # 대상이 바뀌면 같은 규칙으로 재확인을 요구해야 한다.
        if policy is None or not self.effective_autonomy(case_id).controlled:
            raise PolicyRefused([PolicyRefusal.CHECKPOINT_NOT_REQUIRED])
        now = utc_now()
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE controlled_checkpoint SET state = ?, superseded_at = ?"
                " WHERE case_id = ? AND checkpoint = ? AND state = ?",
                (
                    CheckpointState.SUPERSEDED.value,
                    now,
                    case_id,
                    checkpoint.value,
                    CheckpointState.CONFIRMED.value,
                ),
            )
            self.conn.execute(
                "INSERT INTO controlled_checkpoint"
                " (id, case_id, policy_id, checkpoint, state, note_summary, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    ids.new_id("chk"),
                    case_id,
                    policy["id"],
                    checkpoint.value,
                    CheckpointState.REQUIRED.value,
                    _summary(reason_summary),
                    now,
                ),
            )
        return self.list_checkpoints(case_id)

    # ============================================ P3-R4 자동 진행·진입·완료
    #
    # R1 이 기록만 하던 두 축(Autonomy·확인 지점)이 여기서 실제 배정과 종료를 정한다.
    # 판정 자체는 `domain/progression.py` 에 있고 여기서는 **DB 에서 사실을 읽어
    # 넘기고 결과를 기록**한다. 진입 검사·화면·시험이 모두 같은 함수를 보게 하기
    # 위해서다 — R2 가 두 벌로 쓴 탓에 강제 표시 시험이 갱신 없이 통과했다.

    def effective_autonomy(self, case_id: str) -> progression.EffectiveAutonomy:
        """이 Case 에 **적용되는** Autonomy.

        저장된 값과 다를 수 있는 경우가 하나 있다 — `autonomy = NULL` 인 R1 이전
        Case 는 `controlled` 로 **취급**한다(사용자 결정 2026-09-22). 그래도 저장된
        값은 그대로 `NULL`·`migrated_unknown` 이다. `controlled` 를 적어 넣으면 있지도
        않은 사람의 선택을 기록하는 일이 된다(D-14·FR-23).
        """
        row = self._current_policy_row(case_id)
        if row is None:
            # 정책 행 자체가 없다(직접 SQL 삽입 등). 기본값을 적용하되 기록으로
            # 취급하지 않는다 — `effective_policy` 가 `autonomy_recorded = False` 로
            # 같은 사실을 말한다.
            return effective_autonomy(Autonomy.ASK_ON_DECISION.value)
        return effective_autonomy(row["autonomy"])

    #: 취급으로 만들어진 확인 지점임을 남기는 문구. **사람이 고른 설정과 구별한다.**
    TREATED_CHECKPOINT_NOTE = "미기록 Autonomy 를 controlled 로 취급(이행 정책)"

    def _ensure_treated_checkpoints(self, case_id: str) -> None:
        """취급 중인 Case 의 확인 지점을 만든다.

        `set_autonomy()` 가 만드는 행과 **같은 표에 같은 모양으로** 들어간다. 다른
        점은 `note_summary` 하나다 — 그 한 줄이 "사람이 controlled 를 골랐다"와
        "기록이 없어 그렇게 취급한다"를 구별한다.

        **확인된 행이 있으면 건드리지 않는다.** 사람이 실제로 확인한 기록은 어떤
        경로로도 다시 쓰지 않는다.
        """
        autonomy = self.effective_autonomy(case_id)
        if not autonomy.is_treatment or not autonomy.controlled:
            return
        policy = self._current_policy_row(case_id)
        if policy is None:
            return
        now = utc_now()
        for checkpoint in ControlledCheckpoint:
            existing = self.conn.execute(
                "SELECT id FROM controlled_checkpoint"
                " WHERE case_id = ? AND checkpoint = ? AND state IN (?, ?)",
                (
                    case_id,
                    checkpoint.value,
                    CheckpointState.REQUIRED.value,
                    CheckpointState.CONFIRMED.value,
                ),
            ).fetchone()
            if existing is not None:
                continue
            self.conn.execute(
                "INSERT INTO controlled_checkpoint"
                " (id, case_id, policy_id, checkpoint, state, note_summary, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    ids.new_id("chk"),
                    case_id,
                    policy["id"],
                    checkpoint.value,
                    CheckpointState.REQUIRED.value,
                    self.TREATED_CHECKPOINT_NOTE,
                    now,
                ),
            )

    def objective_widened(self, case_id: str) -> bool:
        """사용자의 명시 결정으로 이 Case 의 목적이 넓어졌는가(D-66).

        근거는 `delegation_basis` 의 `user_decision` 행 하나다. **AI 의 판단이나
        Profile 변경은 근거가 아니다** — "분류 변경만으로 재승인·예산 초기화·기준
        삭제를 하지 않는다"(D-62)의 반대 방향도 같다. 분류를 바꿔 권한을 얻지 못한다.
        """
        row = self.conn.execute(
            "SELECT 1 FROM delegation_basis WHERE case_id = ? AND basis_kind = ?"
            " AND state = ? LIMIT 1",
            (case_id, DelegationBasisKind.USER_DECISION.value, PolicyState.CURRENT.value),
        ).fetchone()
        return row is not None

    def checkpoint_state(self, case_id: str) -> dict[str, Any]:
        """확인 지점의 현재 상태를 **판정에 쓰기 쉬운 모양으로** 돌려준다.

        진입 검사와 종료 검사가 같은 값을 본다. `confirmed_subject_hash` 가 있으면
        그것이 "무엇을 보고 확인했는가"이며, 지금 후보의 해시와 다르면 이전 확인을
        새 후보에 쓰지 않는다(D-65·FR-23).
        """
        autonomy = self.effective_autonomy(case_id)
        if not autonomy.controlled:
            return {
                "required": False,
                "effective_autonomy": autonomy.value.value,
                "is_treatment": autonomy.is_treatment,
                "start_confirmed": True,
                "result_confirmed": True,
                "result_subject_id": None,
                "result_subject_hash": None,
            }
        points = {
            p["checkpoint"]: p
            for p in self.list_checkpoints(case_id)
            if p["state"] != CheckpointState.SUPERSEDED.value
        }
        start = points.get(ControlledCheckpoint.START_SCOPE.value)
        result = points.get(ControlledCheckpoint.RESULT_CANDIDATE.value)
        return {
            "required": True,
            "effective_autonomy": autonomy.value.value,
            "is_treatment": autonomy.is_treatment,
            # **행이 없으면 확인되지 않은 것이다.** 없음을 통과로 읽지 않는다.
            "start_confirmed": bool(
                start is not None and start["state"] == CheckpointState.CONFIRMED.value
            ),
            "result_confirmed": bool(
                result is not None and result["state"] == CheckpointState.CONFIRMED.value
            ),
            "result_subject_id": (result or {}).get("subject_id"),
            "result_subject_hash": (result or {}).get("subject_hash"),
        }

    # ------------------------------------------------ Fast Lane 과 정합성 방식

    def fast_lane_state(self, case_id: str) -> dict[str, Any]:
        """Fast Lane 조건의 판정. **저장하지 않고 도출한다.**

        입력은 전부 이미 기록된 사실이다 — 수준 판단, 근거 부족 축, 열린 질문,
        미확인 누적 변경. 저장하면 조건이 바뀌었는데 값이 남아 있는 상태를 다시
        관리해야 하고 "누가 그 값을 적었는가"가 새 문제가 된다(R3 의 `stop` 과 같다).
        """
        sizing = self.current_sizing(case_id)
        state = self.intent_state(case_id)
        outcome = assess_fast_lane(
            level=(sizing or {}).get("level"),
            evidence_gap=bool((sizing or {}).get("evidence_gap")),
            open_intent_questions=len(state.get("open_intent_questions") or []),
            deferred_questions=len(self.deferred_open_questions(case_id)),
            pending_material_deltas=len(self.pending_material_deltas(case_id)),
        )
        return outcome.to_dict()

    def conformance_requirement(self, case_id: str) -> dict[str, Any]:
        """요청 정합성 확인을 **어떤 방식으로** 해야 하는가(D-25).

        QG-01 자체는 끌 수 없다. 달라지는 것은 방식뿐이며, Case 설정은 독립 검토를
        **요구하는 방향으로만** 작용한다 — 낮추는 인자가 없는 것이 계약이다
        (autonomy-budget-policy 5절).
        """
        sizing = self.current_sizing(case_id)
        requirement = required_conformance_method(
            level=(sizing or {}).get("level"),
            evidence_gap=bool((sizing or {}).get("evidence_gap")),
            pending_material_deltas=len(self.pending_material_deltas(case_id)),
            case_requires_independent=self.case_requires_independent_review(case_id),
        )
        return requirement.to_dict()

    #: 요청 정합성 확인 방식의 Case 설정을 담는 단계 이름.
    #:
    #: `stage_review_setting` 을 재사용하는 이유는 저장 구조가 정확히 같기 때문이다 —
    #: "이 단계는 사람이 본다"와 "이 의도는 독립 검토를 받는다"는 같은 모양의 선택이다.
    #: 새 표를 만들면 이력·이행·조회를 한 벌 더 써야 한다.
    CONFORMANCE_SETTING_STAGE = "intent"

    def case_requires_independent_review(self, case_id: str) -> bool:
        """Case 설정이 독립 의미 검토를 명시로 요구하는가.

        **올리는 방향으로만 쓰인다.** 이 값이 거짓이어도 규칙이 독립 검토를 요구하면
        그대로 요구된다 — 낮추는 경로가 없는 것이 계약이다(autonomy-budget-policy
        5절 "필수 요청 정합성 확인은 일반 preset 이나 AI 추천으로 완화할 수 없다").
        """
        row = self.conn.execute(
            "SELECT mode FROM stage_review_setting WHERE case_id = ? AND stage = ?",
            (case_id, self.CONFORMANCE_SETTING_STAGE),
        ).fetchone()
        return bool(row is not None and row["mode"] == ReviewMode.HUMAN_REVIEW.value)

    def require_independent_review(
        self, case_id: str, required: bool, set_by: str, reason_summary: str
    ) -> dict[str, Any]:
        """이 Case 의 요청 정합성 확인에 독립 의미 검토를 요구한다.

        **끄는 쪽은 규칙을 이기지 못한다.** `required = False` 는 "이 Case 의 추가
        요구를 거둔다"일 뿐이며, 수준·근거 부족·미확인 변경이 독립 검토를 요구하면
        그대로 요구된다. 그 판단은 `domain.progression.required_conformance_method`
        하나에 있고 이 설정은 그 입력 중 하나다.
        """
        self.get_case(case_id)
        self.guard_open_case(case_id)
        if not str(reason_summary or "").strip():
            raise ConflictError("a conformance policy change needs a reason")
        mode = ReviewMode.HUMAN_REVIEW if required else ReviewMode.AUTO_PROCEED
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO stage_review_setting (case_id, stage, mode, set_by,"
                " reason_summary, set_at) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(case_id, stage) DO UPDATE SET mode = excluded.mode,"
                "   set_by = excluded.set_by, reason_summary = excluded.reason_summary,"
                "   set_at = excluded.set_at",
                (
                    case_id,
                    self.CONFORMANCE_SETTING_STAGE,
                    mode.value,
                    set_by,
                    _summary(reason_summary),
                    utc_now(),
                ),
            )
        return self.conformance_state(case_id)

    def get_conformance_check(
        self, intent_version_id: str, method: ConformanceMethod
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM conformance_check WHERE intent_version_id = ? AND method = ?",
            (intent_version_id, method.value),
        ).fetchone()
        return _row_to_dict(row)

    def list_conformance_checks(self, case_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM conformance_check WHERE case_id = ? ORDER BY recorded_at",
            (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def record_light_conformance_check(
        self, intent_version_id: str, recorded_by: str = "policy:light_conformance"
    ) -> dict[str, Any]:
        """가벼운 확인을 기록한다(D-25 "명확한 저위험 요청에는 가벼운 확인").

        세 가지를 지킨다.

            방식을 적는다        `method = light`. 독립 검토로 표시하지 않는다
            요구와 대조한다      규칙이 독립 검토를 요구하면 그 사실도 함께 적는다.
                                 **충족했다고 적지 않는다**
            안 본 것을 적는다    `unverified_scope` 에 "원문의 의미 대응을 AI 가
                                 검토하지 않았다"가 값으로 남는다

        **규칙 검사가 통과하지 않았으면 기록하지 않는다.** 가벼운 확인은 규칙 검사
        **위에** 얹히는 것이지 그것을 대신하지 않는다.
        """
        detail = self.get_intent_detail(intent_version_id)
        case_id = detail["case_id"]
        self.guard_open_case(case_id)
        requirement = required_conformance_method(
            level=(self.current_sizing(case_id) or {}).get("level"),
            evidence_gap=bool((self.current_sizing(case_id) or {}).get("evidence_gap")),
            pending_material_deltas=len(self.pending_material_deltas(case_id)),
            case_requires_independent=self.case_requires_independent_review(case_id),
        )
        gate = self._gate_row(intent_version_id, GateId.QG_01)
        if gate is None:
            self.evaluate_gate_rules(intent_version_id, GateId.QG_01)
            gate = self._gate_row(intent_version_id, GateId.QG_01)
        rule_verdict = GateVerdict(gate["rule_verdict"])
        verdict = (
            GateVerdict.PASS if rule_verdict is GateVerdict.PASS else rule_verdict
        )

        now = utc_now()
        with transaction(self.conn):
            self._upsert_conformance_check(
                case_id=case_id,
                intent_version_id=intent_version_id,
                method=ConformanceMethod.LIGHT,
                verdict=verdict,
                run_id=None,
                subject_content_hash=detail["content_hash"],
                unverified_scope=LIGHT_UNVERIFIED_SCOPE,
                reasons=list(requirement.reasons),
                now=now,
            )
            self._refresh_gate_conformance(intent_version_id)
        return self.conformance_state(case_id)

    def _upsert_conformance_check(
        self,
        *,
        case_id: str,
        intent_version_id: str,
        method: ConformanceMethod,
        verdict: GateVerdict,
        run_id: str | None,
        subject_content_hash: str,
        unverified_scope: str | None,
        reasons: list[str],
        now: str,
    ) -> None:
        """정합성 확인 한 건을 쓴다. 두 방식이 **같은 함수**를 쓴다.

        갈라 두면 한쪽만 고치는 실수가 생기고, 그 실수의 결과는 "무엇을 실제로
        확인했는가"가 방식마다 다른 모양으로 남는 것이다.

        `required_method` 는 **쓰는 시점에 다시 계산한다.** 요구가 나중에 올라가면
        (수준 상향·근거 부족·새 누적 변경) 이미 기록된 가벼운 확인이 자동으로
        불충분해져야 하기 때문이다 — `_conformance_for_gate` 가 그 대조를 한다.
        """
        requirement = required_conformance_method(
            level=(self.current_sizing(case_id) or {}).get("level"),
            evidence_gap=bool((self.current_sizing(case_id) or {}).get("evidence_gap")),
            pending_material_deltas=len(self.pending_material_deltas(case_id)),
            case_requires_independent=self.case_requires_independent_review(case_id),
        )
        reasons_json = json.dumps(reasons, ensure_ascii=False)
        existing = self.get_conformance_check(intent_version_id, method)
        if existing is None:
            self.conn.execute(
                "INSERT INTO conformance_check"
                " (id, case_id, intent_version_id, method, required_method, verdict,"
                "  run_id, subject_content_hash, unverified_scope, reasons_json,"
                "  recorded_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ids.new_id("conf"),
                    case_id,
                    intent_version_id,
                    method.value,
                    requirement.required.value,
                    verdict.value,
                    run_id,
                    subject_content_hash,
                    unverified_scope,
                    reasons_json,
                    now,
                ),
            )
            return
        self.conn.execute(
            "UPDATE conformance_check SET required_method = ?, verdict = ?, run_id = ?,"
            " subject_content_hash = ?, unverified_scope = ?, reasons_json = ?,"
            " recorded_at = ? WHERE id = ?",
            (
                requirement.required.value,
                verdict.value,
                run_id,
                subject_content_hash,
                unverified_scope,
                reasons_json,
                now,
                existing["id"],
            ),
        )

    def _conformance_for_gate(
        self, intent_version_id: str, case_id: str
    ) -> tuple[ConformanceMethod | None, GateVerdict]:
        """이 의도 버전의 정합성 확인이 **요구를 충족하는가**와 그 판정.

        두 방식 중 요구를 충족하는 것을 고른다. 독립 검토는 가벼운 확인의 요구도
        충족하지만 **반대는 아니다** — 그 비대칭이 `conformance_satisfies` 에 있다.
        """
        requirement = required_conformance_method(
            level=(self.current_sizing(case_id) or {}).get("level"),
            evidence_gap=bool((self.current_sizing(case_id) or {}).get("evidence_gap")),
            pending_material_deltas=len(self.pending_material_deltas(case_id)),
            case_requires_independent=self.case_requires_independent_review(case_id),
        )
        detail_hash = self.get_intent_detail(intent_version_id)["content_hash"]
        for method in (ConformanceMethod.INDEPENDENT, ConformanceMethod.LIGHT):
            check = self.get_conformance_check(intent_version_id, method)
            if check is None:
                continue
            if not conformance_satisfies(requirement.required, method):
                continue
            # **확인한 원문이 지금 원문인가.** 내용이 바뀌었으면 그 확인은 다른
            # 것을 본 결과다. 여기서 보지 않으면 원문을 고친 뒤 옛 확인으로
            # 게이트가 통과한다(FR-23).
            if check["subject_content_hash"] != detail_hash:
                continue
            return method, GateVerdict(check["verdict"])
        return None, GateVerdict.NOT_RUN

    def _refresh_gate_conformance(self, intent_version_id: str) -> None:
        """정합성 확인 기록에서 게이트 판정을 다시 계산한다.

        **`ai_verdict` 컬럼을 건드리지 않는다.** 독립 검토의 결과는 거기 그대로
        남고, 여기서 바꾸는 것은 합쳐진 `verdict` 뿐이다 — 가벼운 확인을 AI 검토
        결과로 적으면 두 방식의 구별이 사라진다.
        """
        row = self._gate_row(intent_version_id, GateId.QG_01)
        if row is None:
            return
        method, conformance_verdict = self._conformance_for_gate(
            intent_version_id, row["case_id"]
        )
        rule_verdict = GateVerdict(row["rule_verdict"])
        self.conn.execute(
            "UPDATE gate_result SET verdict = ? WHERE id = ?",
            (
                gatemod.combine_verdicts(rule_verdict, conformance_verdict).value,
                row["id"],
            ),
        )

    def conformance_state(self, case_id: str) -> dict[str, Any]:
        """최신 의도 버전의 요청 정합성 확인 상태.

        **방식과 남은 불확실성을 함께 말한다.** 이 응답이 없으면 화면에서 가벼운
        확인과 독립 검토가 같은 `pass` 로 보이고, 그 순간 "미실행을 통과로 표시하지
        않는다"(D-25)가 깨진다.
        """
        requirement = self.conformance_requirement(case_id)
        latest = self.latest_intent_version(case_id)
        if latest is None:
            return {
                "intent_version_id": None,
                "method": None,
                "verdict": GateVerdict.NOT_APPLICABLE.value,
                "unverified_scope": None,
                "checks": [],
                **requirement,
            }
        method, verdict = self._conformance_for_gate(latest["id"], case_id)
        check = (
            self.get_conformance_check(latest["id"], method)
            if method is not None
            else None
        )
        return {
            "intent_version_id": latest["id"],
            "method": method.value if method is not None else None,
            "verdict": verdict.value,
            "unverified_scope": (check or {}).get("unverified_scope"),
            "checks": [
                c
                for c in self.list_conformance_checks(case_id)
                if c["intent_version_id"] == latest["id"]
            ],
            **requirement,
        }

    # -------------------------------------------------- 누적 material delta

    def pending_material_deltas(self, case_id: str) -> list[dict[str, Any]]:
        """확인되지 않은 **material** 변경. 이것이 쌓이는 것이 "누적"이다.

        `draft_work`·`user_directed` 는 여기 없다. 막지 않는 변경이기 때문이다.
        """
        rows = self.conn.execute(
            "SELECT * FROM material_delta WHERE case_id = ? AND state = ? AND materiality = ?"
            " ORDER BY detected_at",
            (case_id, DeltaState.PENDING.value, Materiality.MATERIAL.value),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_material_deltas(self, case_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM material_delta WHERE case_id = ? ORDER BY detected_at",
            (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def material_delta_state(self, case_id: str) -> dict[str, Any]:
        """누적 변경의 현재 상태와 **무엇을 막고 있는가.**

        기준은 마지막 유효 위임이다. AI 가 직전에 쓴 초안이 아니다(D-60).
        """
        basis = self.list_delegation_basis(case_id)["current"]
        pending = self.pending_material_deltas(case_id)
        blocked, block_all = progression.blocked_task_keys(
            pending, self._criterion_task_keys(case_id)
        )
        return {
            "basis": basis,
            "pending": pending,
            "all": self.list_material_deltas(case_id),
            "blocked_task_keys": sorted(blocked),
            "blocks_all_tasks": block_all,
            "detail": "비교 대상은 마지막 유효 위임 기준이다. AI 초안이 아니다(D-60)."
            " AI 의 의미 평가만으로는 해소되지 않는다",
        }

    def _criterion_task_keys(self, case_id: str) -> dict[str, list[str]]:
        """기준 → 그 기준에 붙은 Task 키. 차단 범위를 좁히는 입력이다."""
        revision = self.current_work_graph_row(case_id)
        if revision is None:
            return {}
        rows = self.conn.execute(
            "SELECT criterion_id, task_key FROM task_criterion WHERE graph_revision_id = ?",
            (revision["id"],),
        ).fetchall()
        mapping: dict[str, list[str]] = {}
        for row in rows:
            mapping.setdefault(row["criterion_id"], []).append(row["task_key"])
        return mapping

    def _record_delta(
        self,
        case_id: str,
        *,
        change_class: DeltaChangeClass,
        target_type: str,
        target_id: str | None,
        target_key: str,
        from_hash: str | None,
        to_hash: str | None,
        origin: str | None,
        target_agreed: bool,
        user_directed: bool,
    ) -> None:
        """변경 한 건을 분류해 기록한다. 같은 트랜잭션 안에서 불린다.

        `material` 이 아니면 `adopted` 로 들어간다 — 기록은 남기되 막지 않는다.
        "근거와 영향 평가를 기록하고 자동 진행"(autonomy-budget-policy 3절)의 구현이다.
        """
        classification = classify_change(
            origin=origin, target_agreed=target_agreed, user_directed=user_directed
        )
        basis = self.conn.execute(
            "SELECT id FROM delegation_basis WHERE case_id = ? AND state = ?"
            " ORDER BY revision DESC LIMIT 1",
            (case_id, PolicyState.CURRENT.value),
        ).fetchone()
        state = (
            DeltaState.PENDING
            if classification.materiality is Materiality.MATERIAL
            else DeltaState.ADOPTED
        )
        now = utc_now()
        self.conn.execute(
            "INSERT INTO material_delta"
            " (id, case_id, basis_id, change_class, target_type, target_id, target_key,"
            "  from_hash, to_hash, origin, materiality, state, detail, detected_at,"
            "  resolved_at, resolution_source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ids.new_id("delta"),
                case_id,
                basis["id"] if basis else None,
                change_class.value,
                target_type,
                target_id,
                target_key,
                from_hash,
                to_hash,
                origin,
                classification.materiality.value,
                state.value,
                _summary(classification.detail),
                now,
                None if state is DeltaState.PENDING else now,
                None
                if state is DeltaState.PENDING
                else (
                    "user_direction"
                    if classification.materiality is Materiality.USER_DIRECTED
                    else "draft_work"
                ),
            ),
        )

    def record_delta_assessment(
        self, delta_id: str, assessment: str
    ) -> dict[str, Any]:
        """AI 의 의미 평가를 기록한다. **상태는 바뀌지 않는다.**

        이 함수가 `state` 를 건드리지 않는 것이 계약이다. "'의미가 같음'이라는 주장만
        으로 새 의미를 승인하지 않는다"(autonomy-budget-policy 3절)를 코드로 지키는
        자리이며, 여기에 해소 분기를 하나라도 두면 AI 가 자기 평가로 차단을 푼다.
        """
        row = self.conn.execute(
            "SELECT * FROM material_delta WHERE id = ?", (delta_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"material delta not found: {delta_id}")
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE material_delta SET ai_assessment = ? WHERE id = ?",
                (_summary(assessment), delta_id),
            )
        return dict(
            self.conn.execute(
                "SELECT * FROM material_delta WHERE id = ?", (delta_id,)
            ).fetchone()
        )

    def confirm_material_delta(
        self, delta_id: str, actor: str, explicit: bool, note_summary: str | None = None
    ) -> dict[str, Any]:
        """사람이 그 변경을 확인한다.

        **명시적 확인이 아닌 요청은 확인으로 적지 않는다**(D-14). 확인은 그 변경
        한 건에만 적용되며 남은 `pending` 을 함께 풀지 않는다 — 한 번의 확인이
        누적 전체의 승인이 되면 누적을 세는 의미가 없다.
        """
        row = self.conn.execute(
            "SELECT * FROM material_delta WHERE id = ?", (delta_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"material delta not found: {delta_id}")
        if not explicit:
            raise PolicyRefused([PolicyRefusal.NOT_EXPLICIT])
        self._guard_policy_change(row["case_id"])
        if row["state"] != DeltaState.PENDING.value:
            return dict(row)
        decision_id = ids.new_decision_id()
        now = utc_now()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO decision (id, case_id, kind, subject_type, subject_id,"
                " subject_revision, actor, decided_at, subject_content_hash)"
                " VALUES (?, ?, ?, 'material_delta', ?, 1, ?, ?, ?)",
                (
                    decision_id,
                    row["case_id"],
                    DecisionKind.MATERIAL_DELTA_CONFIRMATION.value,
                    delta_id,
                    actor,
                    now,
                    row["to_hash"],
                ),
            )
            self.conn.execute(
                "UPDATE material_delta SET state = ?, decision_id = ?, resolved_at = ?,"
                " resolution_source = 'human_confirmation' WHERE id = ?",
                (DeltaState.CONFIRMED.value, decision_id, now, delta_id),
            )
        return self.material_delta_state(row["case_id"])

    # ---------------------------------------------------------------- 예산

    def set_budget_limit(
        self,
        case_id: str,
        metric: BudgetMetric,
        threshold_kind: BudgetThreshold,
        limit_value: float,
        set_by: str,
        reason_summary: str | None = None,
    ) -> dict[str, Any]:
        """예산 한도를 설정한다. **설정이 없으면 무제한이다**(D-56).

        **강제할 수 없는 정확한 hard 한도는 받지 않는다**(D-61 "정확한 hard 한도를
        요구했는데 보장할 수 없다면 해당 설정/실행을 허용하지 않는다"). 토큰·비용은
        어댑터가 사용량을 주지 않거나 사후에만 주므로 정확한 상한을 약속할 수 없다.
        거부하지 않고 저장하면, 설정한 사람은 상한이 있다고 믿는데 시스템은 그것을
        지킬 방법이 없는 상태가 된다.

        경고선(`warn`)은 추정 지표에도 받는다. 경고는 표시이며 보장이 아니다.

        **P3-R3: 받은 한도가 무엇을 약속하는지 행에 남긴다.** 실행 수·컨텍스트 크기는
        예약이 정확해 절대 상한을 지킬 수 있고, 시간 지표는 새 배정만 막을 수 있다 —
        돌고 있는 CLI 를 초 단위로 끊을 능력이 없기 때문이다(P1-03). 둘을 같은 값으로
        적으면 없는 보장을 표시한 것이 된다(`domain.budget.guarantee_for`).
        """
        self._guard_policy_change(case_id)
        self.get_case(case_id)
        refusals: list[PolicyRefusal] = []
        if limit_value <= 0:
            refusals.append(PolicyRefusal.LIMIT_NOT_POSITIVE)
        measurement = BUDGET_MEASUREMENT[metric]
        guarantee = guarantee_for(metric, threshold_kind)
        if guarantee is BudgetGuarantee.NOT_ENFORCEABLE:
            refusals.append(PolicyRefusal.HARD_LIMIT_NOT_ENFORCEABLE)
        if refusals:
            raise PolicyRefused(refusals)

        now = utc_now()
        row = self.conn.execute(
            "SELECT MAX(revision) AS r FROM budget_setting WHERE case_id = ?", (case_id,)
        ).fetchone()
        revision = (row["r"] or 0) + 1
        with transaction(self.conn):
            # 같은 지표·같은 경계의 이전 설정만 대체한다. 다른 지표의 한도는 그대로다.
            self.conn.execute(
                "UPDATE budget_setting SET state = ?, superseded_at = ?"
                " WHERE case_id = ? AND metric = ? AND threshold_kind = ? AND state = ?",
                (
                    PolicyState.SUPERSEDED.value,
                    now,
                    case_id,
                    metric.value,
                    threshold_kind.value,
                    PolicyState.CURRENT.value,
                ),
            )
            self.conn.execute(
                "INSERT INTO budget_setting"
                " (id, case_id, revision, metric, threshold_kind, limit_value, unit,"
                "  measurement, enforcement, enforced_by, policy_version, set_by,"
                "  reason_summary, state, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ids.new_id("budget"),
                    case_id,
                    revision,
                    metric.value,
                    threshold_kind.value,
                    float(limit_value),
                    BUDGET_UNIT[metric],
                    measurement.value,
                    _ENFORCEMENT_FOR_GUARANTEE[guarantee].value,
                    self.ENFORCEMENT["budget"]["enforced_by"],
                    POLICY_VERSION,
                    set_by,
                    _summary(reason_summary) if reason_summary else None,
                    PolicyState.CURRENT.value,
                    now,
                ),
            )
        return self.budget_state(case_id)

    def clear_budget_limit(
        self, case_id: str, metric: BudgetMetric, threshold_kind: BudgetThreshold
    ) -> dict[str, Any]:
        """한도를 해제한다. **이력은 남는다.**"""
        self._guard_policy_change(case_id)
        now = utc_now()
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE budget_setting SET state = ?, superseded_at = ?"
                " WHERE case_id = ? AND metric = ? AND threshold_kind = ? AND state = ?",
                (
                    PolicyState.SUPERSEDED.value,
                    now,
                    case_id,
                    metric.value,
                    threshold_kind.value,
                    PolicyState.CURRENT.value,
                ),
            )
        return self.budget_state(case_id)

    # ----------------------------------------------- 예약·집계·정지 (R3)
    #
    # **집계의 출처는 `budget_reservation` 하나다.** `run` 표에서 따로 세고 여기서도
    # 세면 두 수가 갈라지고, 갈라지면 어느 쪽이 한도인지 아무도 말할 수 없다.
    # R3 이전 실행은 v10 이행이 같은 표에 넣어 두었다.

    def _current_limits(
        self, case_id: str, threshold_kind: BudgetThreshold
    ) -> dict[BudgetMetric, dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM budget_setting WHERE case_id = ? AND state = ?"
            " AND threshold_kind = ?",
            (case_id, PolicyState.CURRENT.value, threshold_kind.value),
        ).fetchall()
        return {BudgetMetric(r["metric"]): dict(r) for r in rows}

    def _metric_exposure(
        self, case_id: str, now: str | None = None
    ) -> dict[str, dict[str, Any]]:
        """지표별 **확정 사용량과 노출.**

        셋을 구분한다.

            `settled`     실제 사용량이 확정됐다
            `held`        진행 중 실행이 잡고 있다. 시간은 지금까지 관측된 만큼
            `unresolved`  실행은 끝났는데 얼마인지 모른다. **해제하지 않는다** —
                          "확인 전에 잔여량을 낙관적으로 복구하지 않는다"(7절)

        `exposure` 는 셋의 합이며 **한도 판정에 쓰는 값**이다. `settled` 만 보고
        판정하면 진행 중 실행과 결과 불명이 공짜가 된다.

        `complete` 는 "이 수가 실제 소비 전부인가"이다. 어댑터가 토큰을 주지 않은
        실행이 하나라도 있으면 `False` 이고, 그때 **모자란 만큼을 0으로 채우지
        않는다**(D-61 "미제공을 0으로 기록하지 않는다").
        """
        now = now or utc_now()
        out: dict[str, dict[str, Any]] = {
            m.value: {
                "metric": m.value,
                "unit": BUDGET_UNIT[m],
                "settled": 0.0,
                "held": 0.0,
                "unresolved": 0.0,
                "exposure": 0.0,
                "reservation": RESERVATION_KIND[m].value,
                "measurement": BUDGET_MEASUREMENT[m].value,
                "runs_counted": 0,
                "runs_unknown": 0,
                "runs_in_flight": 0,
                "complete": True,
            }
            for m in BudgetMetric
        }

        # 벽시계는 예약 행이 없다. Case 시작 시각에서 도출한다 — 배정을 멈춰도
        # 줄지 않는 값을 예약으로 표현하면 거짓말이 된다.
        case = self.get_case(case_id)
        elapsed = elapsed_seconds(case["created_at"], now)
        clock = out[BudgetMetric.ELAPSED_SECONDS.value]
        clock["settled"] = elapsed if elapsed is not None else 0.0
        clock["complete"] = elapsed is not None
        clock["source"] = "case_created_at"

        rows = self.conn.execute(
            "SELECT b.*, r.assigned_at FROM budget_reservation b"
            " JOIN run r ON r.run_id = b.run_id WHERE b.case_id = ?",
            (case_id,),
        ).fetchall()
        for row in rows:
            bucket = out[row["metric"]]
            state = row["state"]
            actual = row["actual_value"]
            reserved = row["reserved_value"]
            if state == ReservationState.HELD.value:
                bucket["runs_in_flight"] += 1
                if reserved is not None:
                    value = float(reserved)
                elif row["reservation_kind"] == ReservationKind.OPEN_ENDED_PER_RUN.value:
                    # 진행 중 실행의 시간은 **지금까지 관측된 만큼**이다. 아직
                    # 배정되지 않았으면 0 이며 그것은 관측 사실이다.
                    observed = elapsed_seconds(row["assigned_at"], now)
                    value = observed if observed is not None else 0.0
                else:
                    value = 0.0
                bucket["held"] += value
            elif state == ReservationState.UNRESOLVED.value:
                bucket["runs_unknown"] += 1
                bucket["complete"] = False
                if actual is not None:
                    bucket["unresolved"] += float(actual)
                elif reserved is not None:
                    bucket["unresolved"] += float(reserved)
            else:
                bucket["runs_counted"] += 1
                if actual is not None:
                    bucket["settled"] += float(actual)

        for bucket in out.values():
            if bucket["runs_in_flight"]:
                bucket["complete"] = False
            bucket["exposure"] = round(
                bucket["settled"] + bucket["held"] + bucket["unresolved"], 6
            )
            for key in ("settled", "held", "unresolved"):
                bucket[key] = round(bucket[key], 6)
        return out

    def _budget_breaches(
        self,
        case_id: str,
        want: dict[BudgetMetric, float | None],
        now: str | None = None,
    ) -> list[dict[str, Any]]:
        """이 실행을 배정하면 넘는 hard 한도들.

        **검사 대상은 그 실행이 실제로 소비하는 지표뿐이다.** 검토 한도가 소진돼도
        작성 실행은 막히지 않는다 — hard 는 "해당 한도를 소비하는 새 실행"을 막는
        것이지 Case 전체를 잠그는 것이 아니다(autonomy-budget-policy 8절).

        벽시계(`elapsed_seconds`)만 예외로 모든 실행에 적용된다. 기한이 지난 뒤에
        시작하는 실행은 종류를 가리지 않고 그 기한을 넘기 때문이다.
        """
        limits = self._current_limits(case_id, BudgetThreshold.HARD)
        if not limits:
            return []
        exposure = self._metric_exposure(case_id, now)
        checked = set(want) | {BudgetMetric.ELAPSED_SECONDS}
        breaches: list[dict[str, Any]] = []
        for metric in sorted(checked, key=lambda m: m.value):
            limit = limits.get(metric)
            if limit is None:
                continue
            current = exposure[metric.value]["exposure"]
            adding = want.get(metric)
            if adding is None:
                # 얼마를 더할지 모르는 지표(시간). 남은 칸이 없을 때만 막는다 —
                # 이것이 `no_absolute_cap` 의 실제 내용이다.
                projected = current
                over = current >= float(limit["limit_value"])
            else:
                projected = current + float(adding)
                over = projected > float(limit["limit_value"])
            if over:
                breaches.append(
                    {
                        "metric": metric.value,
                        "limit_value": float(limit["limit_value"]),
                        "unit": limit["unit"],
                        "exposure": current,
                        "would_be": round(projected, 6),
                        "guarantee": guarantee_for(metric, BudgetThreshold.HARD).value,
                        "complete": exposure[metric.value]["complete"],
                    }
                )
        return breaches

    def _reserve_budget(
        self,
        case_id: str,
        run_id: str,
        generation: int,
        role: RunRole,
        purpose: RunPurpose,
        want: dict[BudgetMetric, float | None],
        now: str,
    ) -> None:
        """예약 행을 넣는다. **호출자의 트랜잭션 안에서 돈다.**

        여기서 따로 트랜잭션을 열지 않는 것이 핵심이다 — 검사와 Run 생성과 예약이
        한 트랜잭션이어야 마지막 한 칸을 두 요청이 함께 통과하지 못한다.
        """
        for metric, value in want.items():
            self.conn.execute(
                "INSERT OR IGNORE INTO budget_reservation"
                " (id, case_id, run_id, generation, metric, reserved_value, actual_value,"
                "  measurement, reservation_kind, role, purpose, state, source,"
                "  settle_source, reserved_at, settled_at)"
                " VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, NULL, ?, NULL)",
                (
                    ids.new_id("budres"),
                    case_id,
                    run_id,
                    generation,
                    metric.value,
                    None if value is None else float(value),
                    # 예약 시점에는 아직 잰 것이 없다. 지표의 정적 계약을 여기 적으면
                    # 받은 적 없는 값이 있는 것처럼 보인다.
                    BudgetMeasurement.UNAVAILABLE.value,
                    RESERVATION_KIND[metric].value,
                    role.value,
                    purpose.value,
                    ReservationState.HELD.value,
                    ReservationSource.RESERVED.value,
                    now,
                ),
            )

    def _settle_budget(self, run: dict[str, Any], usage: Any, now: str) -> None:
        """실행이 끝났다. 예약을 정산한다. **호출자의 트랜잭션 안에서 돈다.**

        **판단은 실행 단위가 아니라 지표 단위다.** 결과가 불명확하다는 사실이 모든
        지표를 똑같이 모르게 만들지는 않기 때문이다.

        1. `exact_per_run`(실행 수·검토 수·컨텍스트 크기) 은 **언제나 확정된다.**
           실패·취소·결과 불명이어도 호출은 실제로 있었고 전달한 패키지의 크기도
           이미 정해져 있다. 이 값들은 잔류 프로세스가 있어도 더 커지지 않는다.
        2. `open_ended_per_run`(실행 시간) 은 시계에서 도출하되
           (`assigned_at → finished_at`) **결과가 `unknown` 이거나 잔류 활동이
           `none` 이 아니면 `unresolved` 로 남긴다.** 프로세스가 남아 있으면 관측한
           값이 최종이라는 근거가 없다(autonomy-budget-policy 7절).
        3. `post_hoc_reported`(토큰·비용) 은 **어댑터가 준 값을 그대로 확정한다.**
           주지 않았으면 `unresolved`·`unavailable` 이다. 잔류 프로세스가 있다는
           사실이 이미 보고된 수를 모르게 만들지는 않는다 — 실제 어댑터는
           `residual_activity` 를 항상 `unknown` 으로 보고하므로(P1-03), 그것을
           확정 조건으로 쓰면 받은 관측을 전부 버리게 된다. 값이 `estimated` 라는
           사실은 `measurement` 가 따로 말한다.

        **셋을 실행 단위 하나로 묶으면 두 방향으로 틀린다.** 느슨하게 묶으면 잔류
        프로세스가 있는데 시간을 확정으로 적고, 엄격하게 묶으면 실제로 돈 실행 수마저
        "모른다"가 되어 집계가 아무 것도 말하지 못한다 — 지금 실제 CLI 어댑터는
        `residual_activity` 를 항상 `unknown` 으로 보고한다(P1-03).

        어댑터가 주지 않은 토큰·비용은 `unresolved`·`unavailable` 이며 **0 이
        아니다.** 0 으로 적으면 한도가 영원히 남아 있는 것처럼 보인다.
        """
        run_id = run["run_id"]
        generation = run["assignment_generation"]
        outcome = run.get("outcome")
        residual = run.get("residual_activity")
        confirmed = outcome != RunOutcome.UNKNOWN.value and residual == "none"
        unconfirmed_reason = (
            SettleSource.OUTCOME_UNKNOWN.value
            if outcome == RunOutcome.UNKNOWN.value
            else SettleSource.RESIDUAL_ACTIVITY.value
        )
        seconds = elapsed_seconds(run.get("assigned_at"), run.get("finished_at"))
        reported = normalize_usage(usage)

        held = self.conn.execute(
            "SELECT * FROM budget_reservation WHERE run_id = ? AND generation = ?"
            " AND state = ?",
            (run_id, generation, ReservationState.HELD.value),
        ).fetchall()
        for row in held:
            metric = BudgetMetric(row["metric"])
            kind = ReservationKind(row["reservation_kind"])
            if kind is ReservationKind.EXACT_PER_RUN:
                # **잔류 활동이 이 값을 더 키우지 않는다.** 호출은 이미 있었고
                # 전달한 패키지의 크기도 정해졌다. 여기서 `unresolved` 로 두면
                # "몇 번 실행했는지 모른다"가 되어 집계가 무의미해진다.
                actual: float | None = (
                    None if row["reserved_value"] is None else float(row["reserved_value"])
                )
                source = SettleSource.RESERVED_EXACT.value
                state = (
                    ReservationState.SETTLED.value
                    if actual is not None
                    else ReservationState.UNRESOLVED.value
                )
            else:
                actual = seconds
                source = (
                    SettleSource.OBSERVED_CLOCK.value
                    if seconds is not None
                    else SettleSource.CLOCK_UNAVAILABLE.value
                )
                if actual is None:
                    state = ReservationState.UNRESOLVED.value
                elif not confirmed:
                    # 값은 남기되 **최종이라고 적지 않는다.** 프로세스가 남아 있으면
                    # 더 늘 수 있고, 노출에는 관측한 만큼이 들어간다.
                    state = ReservationState.UNRESOLVED.value
                    source = unconfirmed_reason
                else:
                    state = ReservationState.SETTLED.value
            self.conn.execute(
                "UPDATE budget_reservation SET actual_value = ?, measurement = ?,"
                " state = ?, settle_source = ?, settled_at = ? WHERE id = ?",
                (
                    actual,
                    measurement_for_settlement(metric, actual).value,
                    state,
                    source,
                    now,
                    row["id"],
                ),
            )

        # 사후 보고 지표는 **정산 시점에 행이 생긴다.** 실행 전에는 잡을 근거가 전혀
        # 없고, 그렇다고 보고된 소비를 버리면 경고선이 아무 것도 보지 못한다.
        for metric in (
            BudgetMetric.INPUT_TOKENS,
            BudgetMetric.OUTPUT_TOKENS,
            BudgetMetric.ESTIMATED_COST,
        ):
            value = reported.get(metric)
            if value is not None:
                # **받은 수를 버리지 않는다.** 잔류 프로세스가 더 쓸 수 있다는 것은
                # 추측이고, 이 값은 관측이다. 추정값이라는 사실은 `measurement` 가
                # 따로 말한다.
                state = ReservationState.SETTLED.value
                source = SettleSource.ADAPTER_REPORTED.value
            elif outcome == RunOutcome.UNKNOWN.value:
                state = ReservationState.UNRESOLVED.value
                source = SettleSource.OUTCOME_UNKNOWN.value
            else:
                state = ReservationState.UNRESOLVED.value
                source = SettleSource.ADAPTER_NOT_REPORTED.value
            self.conn.execute(
                "INSERT OR IGNORE INTO budget_reservation"
                " (id, case_id, run_id, generation, metric, reserved_value, actual_value,"
                "  measurement, reservation_kind, role, purpose, state, source,"
                "  settle_source, reserved_at, settled_at)"
                " VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ids.new_id("budres"),
                    run["case_id"],
                    run_id,
                    generation,
                    metric.value,
                    value,
                    measurement_for_settlement(metric, value).value,
                    ReservationKind.POST_HOC_REPORTED.value,
                    run["role"],
                    run.get("purpose") or "",
                    state,
                    ReservationSource.RESERVED.value,
                    source,
                    now,
                    now,
                ),
            )

    def budget_stop(self, case_id: str, now: str | None = None) -> dict[str, Any]:
        """예산 때문에 **새 실행을 시작할 수 없는가.**

        **도출한다. 저장하지 않는다.** hard 도달은 완료도 취소도 아니고
        (autonomy-budget-policy 8절), 한도를 올리면 그 순간 다시 진행할 수 있어야
        한다 — 상태를 컬럼에 적어 두면 그것을 되돌리는 경로가 또 필요해지고, 그
        경로가 곧 `continue` 우회가 된다.

        막는 것은 **새 실행 생성과 재배정 하나뿐이다.** 결과 보고·이벤트 수신·산출물
        저장·기존 기록 조회는 계속 받는다. 정리라는 이름의 새 AI 실행도 막는다.
        """
        limits = self._current_limits(case_id, BudgetThreshold.HARD)
        if not limits:
            return {
                "stopped": False,
                "metrics": [],
                "detail": "설정된 hard 한도가 없다. 기본 무제한이다(D-56)",
                "resume": None,
            }
        exposure = self._metric_exposure(case_id, now)
        reached = []
        for metric, limit in sorted(limits.items(), key=lambda kv: kv[0].value):
            current = exposure[metric.value]["exposure"]
            if current >= float(limit["limit_value"]):
                reached.append(
                    {
                        "metric": metric.value,
                        "limit_value": float(limit["limit_value"]),
                        "unit": limit["unit"],
                        "exposure": current,
                        "guarantee": guarantee_for(metric, BudgetThreshold.HARD).value,
                        "complete": exposure[metric.value]["complete"],
                    }
                )
        return {
            "stopped": bool(reached),
            "metrics": reached,
            "detail": (
                "그 한도를 소비하는 새 실행을 배정하지 않는다. 진행 중 실행의 결과는"
                " 그대로 받고 남은 작업·미검증 상태는 보존된다"
                if reached
                else "설정된 hard 한도 안이다"
            ),
            "resume": (
                "한도를 바꾸거나 해제하면 다음 요청부터 다시 배정된다."
                " 한도를 그대로 둔 채 이어 가는 경로는 없다(D-61)"
                if reached
                else None
            ),
        }

    def budget_state(self, case_id: str) -> dict[str, Any]:
        """지금 걸려 있는 한도, 실제 소비, 그리고 그 한도가 **약속하는 것.**

        `unlimited` 를 따로 두는 이유는 "한도 0건"과 "한도 0"이 다르기 때문이다.

        **P3-R3: 사용량이 여기 들어온다.** 다만 모르는 값을 0 으로 적지 않는다 —
        각 지표의 `complete` 가 "이 수가 소비 전부인가"를 말하고, 어댑터가 주지 않은
        실행 수는 `runs_unknown` 으로 드러난다(D-61).
        """
        now = utc_now()
        rows = self.conn.execute(
            "SELECT * FROM budget_setting WHERE case_id = ? ORDER BY revision", (case_id,)
        ).fetchall()
        items = [dict(r) for r in rows]
        current = [i for i in items if i["state"] == PolicyState.CURRENT.value]
        for limit in current:
            # **지금 이 한도가 무엇을 약속하는가.** 행에 적힌 `enforcement` 는 설정
            # 시점의 값이고, R1 시절에 설정된 행은 `recorded_not_enforced` 로 남아
            # 있다. 그 행을 고쳐 쓰지 않고 현재 판정을 따로 얹는다.
            limit["guarantee"] = guarantee_for(
                BudgetMetric(limit["metric"]), BudgetThreshold(limit["threshold_kind"])
            ).value
        exposure = self._metric_exposure(case_id, now)

        warnings = []
        for metric, limit in sorted(
            self._current_limits(case_id, BudgetThreshold.WARN).items(),
            key=lambda kv: kv[0].value,
        ):
            used = exposure[metric.value]["exposure"]
            if used >= float(limit["limit_value"]):
                warnings.append(
                    {
                        "metric": metric.value,
                        "limit_value": float(limit["limit_value"]),
                        "unit": limit["unit"],
                        "exposure": used,
                        "complete": exposure[metric.value]["complete"],
                        "detail": "표시이며 실행을 막지 않는다. 경고 자체로 사람 응답을"
                        " 기다리지 않는다(autonomy-budget-policy 8절)",
                    }
                )

        return {
            "unlimited": not current,
            "limits": current,
            "history": items,
            "usage": exposure,
            "usage_detail": "`exposure = settled + held + unresolved` 가 한도 판정값이다."
            " 모르는 값을 0 으로 채우지 않으며 `complete = false` 로 드러낸다",
            "by_role": self._budget_by(case_id, "role"),
            "by_purpose": self._budget_by(case_id, "purpose"),
            "warnings": warnings,
            "stop": self.budget_stop(case_id, now),
            "reservations": self.list_budget_reservations(case_id),
            "measurement_contract": {
                m.value: BUDGET_MEASUREMENT[m].value for m in BudgetMetric
            },
            "reservation_contract": reservation_contract(),
            "repair_limit_note": "품질 수정 한도(D-29 기본 2회)는 P4-01의"
            " remediation_cycle에 별도로 누적한다. 이 예산 집계를 repair 횟수로"
            " 쓰거나 repair 여유를 예산으로 쓰지 않는다",
            "enforcement": self.ENFORCEMENT["budget"],
        }

    def _budget_by(self, case_id: str, column: str) -> dict[str, dict[str, Any]]:
        """역할별·목적별 집계(D-61 "전체 역할·재시도·추출을 누적").

        **나눈 값의 합이 Case 전체다.** 역할별 계산으로 Case 한도를 우회할 수 없게
        하려면 이 축이 표시용이어야 하고 판정은 언제나 Case 하나로 한다(8절).
        """
        rows = self.conn.execute(
            f"SELECT {column} AS axis, metric, state, SUM(actual_value) AS total,"
            " COUNT(*) AS n FROM budget_reservation WHERE case_id = ?"
            f" GROUP BY {column}, metric, state",
            (case_id,),
        ).fetchall()
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            axis = out.setdefault(row["axis"], {})
            bucket = axis.setdefault(
                row["metric"], {"settled": 0.0, "unknown_rows": 0, "rows": 0}
            )
            bucket["rows"] += row["n"]
            if row["state"] == ReservationState.SETTLED.value:
                bucket["settled"] = round(float(row["total"] or 0.0), 6)
            else:
                # **확정되지 않은 행을 0 으로 합치지 않는다.** 수로 드러낸다.
                bucket["unknown_rows"] += row["n"]
        return out

    def list_budget_reservations(self, case_id: str) -> list[dict[str, Any]]:
        """예약 한 건 한 건. **왜 모르는지가 `settle_source` 에 있다**(FR-14)."""
        rows = self.conn.execute(
            "SELECT * FROM budget_reservation WHERE case_id = ?"
            " ORDER BY reserved_at, run_id, metric",
            (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # --------------------------------------------------- Project 저장소

    def register_project_repository(
        self,
        project_id: str,
        name: str,
        repo_path: str,
        registered_by: str = "owner",
    ) -> dict[str, Any]:
        """Project 에 저장소를 등록한다(D-38·FR-01).

        등록은 **선택도 허용도 아니다.** Case 가 무엇을 선택했는지는
        `case_repository`, 쓰기·게시 허용도 그 표에 따로 있다.
        """
        self.get_project(project_id)
        repo_id = ids.new_id("repo")
        now = utc_now()
        try:
            with transaction(self.conn):
                self.conn.execute(
                    "INSERT INTO project_repository"
                    " (id, project_id, name, repo_path, source, registered_by, registered_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        repo_id,
                        project_id,
                        name[:100],
                        repo_path,
                        RepositorySource.REGISTERED.value,
                        registered_by,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"repository name already used in project: {name}") from exc
        return self.get_project_repository(repo_id)

    def get_project_repository(self, repository_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM project_repository WHERE id = ?", (repository_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"repository not found: {repository_id}")
        return dict(row)

    def list_project_repositories(self, project_id: str) -> list[dict[str, Any]]:
        self.get_project(project_id)
        rows = self.conn.execute(
            "SELECT * FROM project_repository WHERE project_id = ? ORDER BY registered_at",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def set_journal_repository(self, project_id: str, repository_id: str) -> dict[str, Any]:
        """Case 기록 이슈를 만들 저장소를 지정한다(D-17·D-34·FR-30).

        **코드 대상이 아니다.** 지정만으로 어떤 Case 의 코드 변경 집합에도 들어가지
        않으며, 코드 대상으로 선택하려는 요청은 거부한다(`select_case_repository`).
        """
        repo = self.get_project_repository(repository_id)
        if repo["project_id"] != project_id:
            raise PolicyRefused([PolicyRefusal.REPOSITORY_NOT_IN_PROJECT])
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE project SET journal_repository_id = ? WHERE id = ?",
                (repository_id, project_id),
            )
        return self.project_repository_view(project_id)

    def project_repository_view(self, project_id: str) -> dict[str, Any]:
        """Project 의 등록 저장소.

        **`project_repository` 가 경로의 정본이다**(P3-R2). `project.repo_path` 는
        지우지 않고 남기되 여기서 정본과 어긋나는지 함께 보인다 — 조용히 어긋난
        값을 남겨 두면 어느 경로에서 실제로 작업했는지 말할 수 없게 된다.
        """
        project = self.get_project(project_id)
        repositories = self.list_project_repositories(project_id)
        paths = {r["repo_path"] for r in repositories}
        return {
            "project_id": project_id,
            "repositories": repositories,
            "journal_repository_id": project.get("journal_repository_id"),
            "legacy_repo_path": project["repo_path"],
            "canonical_source": "project_repository",
            # v1의 컬럼이 등록 저장소 어느 것과도 맞지 않는다. 드러내되 고치지 않는다 —
            # 어느 쪽이 맞는지는 사람이 안다.
            "legacy_repo_path_matches_registry": project["repo_path"] in paths,
            "enforcement": {
                "selection": self.ENFORCEMENT["repository_selection"],
                "publish": self.ENFORCEMENT["publish"],
            },
        }

    # ----------------------------------------------------- Case 저장소 선택

    def select_case_repository(
        self,
        case_id: str,
        repository_id: str,
        selection_source: RepositorySelectionSource,
        code_write_allowed: bool,
        publish_allowed: bool,
        selected_by: str,
        reason_summary: str | None = None,
    ) -> dict[str, Any]:
        """Case 의 저장소 선택과 허용 범위를 기록한다(D-63·D-64).

        **세 집합을 분리한다.** 선택했다는 것, 코드를 바꿔도 된다는 것, 외부에 게시해도
        된다는 것. 호출자가 쓰기만 허용하면 게시는 허용되지 않는다 — 기본값으로
        따라오게 만들면 D-64("쓰기 허용 저장소 추가는 게시 허용 확대가 아니다")가
        코드 한 줄로 깨진다.

        기록 저장소를 코드 대상으로 선택하는 요청은 거부한다(D-17·FR-30).

        **`auto_in_allowance` 는 이 경로로 기록하지 않는다**(P3-R2). 허용 내 자동
        추가에는 "무엇이 이미 허용돼 있는가"를 보는 검사가 붙어 있고
        (`auto_select_repository`), 여기서 출처만 바꿔 쓸 수 있으면 그 검사를 우회해
        자동 추가가 새 권한을 만들어 낼 수 있다.
        """
        if selection_source is RepositorySelectionSource.AUTO_IN_ALLOWANCE:
            raise ConflictError(
                "auto_in_allowance is recorded by the allowance check, not by explicit selection"
            )
        self._guard_policy_change(case_id)
        case = self.get_case(case_id)
        repo = self.get_project_repository(repository_id)
        if repo["project_id"] != case["project_id"]:
            raise PolicyRefused([PolicyRefusal.REPOSITORY_NOT_IN_PROJECT])
        project = self.get_project(case["project_id"])
        if (
            code_write_allowed
            and project.get("journal_repository_id") == repository_id
        ):
            raise PolicyRefused([PolicyRefusal.JOURNAL_REPOSITORY_NOT_A_CODE_TARGET])
        if selection_source is RepositorySelectionSource.EXCLUDED and (
            code_write_allowed or publish_allowed
        ):
            raise ConflictError("excluded repository cannot carry write or publish allowance")
        now = utc_now()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO case_repository"
                " (case_id, repository_id, selection_source, code_write_allowed,"
                "  publish_allowed, selected_by, reason_summary, state, selected_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(case_id, repository_id) DO UPDATE SET"
                "   selection_source = excluded.selection_source,"
                "   code_write_allowed = excluded.code_write_allowed,"
                "   publish_allowed = excluded.publish_allowed,"
                "   selected_by = excluded.selected_by,"
                "   reason_summary = excluded.reason_summary,"
                "   state = excluded.state,"
                "   selected_at = excluded.selected_at,"
                "   superseded_at = NULL",
                (
                    case_id,
                    repository_id,
                    selection_source.value,
                    1 if code_write_allowed else 0,
                    1 if publish_allowed else 0,
                    selected_by,
                    _summary(reason_summary) if reason_summary else None,
                    PolicyState.CURRENT.value,
                    now,
                ),
            )
        return self.case_repository_state(case_id)

    def auto_select_repository(
        self,
        case_id: str,
        repository_id: str,
        selected_by: str,
        code_write_allowed: bool = True,
        publish_allowed: bool = False,
        reason_summary: str | None = None,
    ) -> dict[str, Any]:
        """**허용 안의** 저장소를 자동으로 추가한다(D-38·D-63, P3-R2).

        D-38은 "기존 허용 쓰기 범위와 목표 안의 추가 저장소는 자동 선택한다"이고
        같은 문장이 "명시적 제외·새 권한·제품/데이터 영향은 재판단한다"로 이어진다.
        그래서 이 경로가 성립하는 조건은 하나다 — **이미 가진 것을 넓히지 않을 때.**

        넓히는 세 경우는 각각 다른 사유로 거절한다. 거절은 **거절로 끝난다.** 질문을
        자동으로 만들지 않는다 — 질문 생성과 누적 material delta 판단은 R4의 몫이고,
        여기서 반쯤 만들면 R4가 붙일 자리가 이미 차 있게 된다. 대신 응답이
        `requires_human_confirmation` 과 사유를 실어 화면이 그대로 말한다.

        이미 `explicit` 로 선택된 저장소는 **바꾸지 않는다.** 사람의 선택을 자동
        기록으로 덮으면 그 선택이 누구 것이었는지 남지 않는다.
        """
        self._guard_policy_change(case_id)
        case = self.get_case(case_id)
        repo = self.get_project_repository(repository_id)
        if repo["project_id"] != case["project_id"]:
            raise PolicyRefused([PolicyRefusal.REPOSITORY_NOT_IN_PROJECT])
        project = self.get_project(case["project_id"])
        if project.get("journal_repository_id") == repository_id:
            raise PolicyRefused([PolicyRefusal.JOURNAL_REPOSITORY_NOT_A_CODE_TARGET])
        if publish_allowed:
            # **쓰기 허용 저장소 추가는 게시 허용 확대가 아니다**(D-64). 게시는
            # 언제나 사람이 따로 허용한다.
            raise PolicyRefused([PolicyRefusal.AUTO_ADD_CANNOT_GRANT_PUBLISH])

        existing = self.conn.execute(
            "SELECT * FROM case_repository WHERE case_id = ? AND repository_id = ?"
            " AND state = ?",
            (case_id, repository_id, PolicyState.CURRENT.value),
        ).fetchone()
        if existing is not None:
            if existing["selection_source"] == RepositorySelectionSource.EXCLUDED.value:
                # **자동 추가가 넘지 못하는 경계다.** 제외는 사람이 내린 판단이며
                # 행이 없는 것(아직 판단하지 않음)과 다르다(D-63).
                raise PolicyRefused([PolicyRefusal.REPOSITORY_EXPLICITLY_EXCLUDED])
            if existing["selection_source"] == RepositorySelectionSource.EXPLICIT.value:
                state = self.case_repository_state(case_id)
                state["auto_selection"] = {
                    "repository_id": repository_id,
                    "changed": False,
                    "detail": "이미 사람이 명시로 선택한 저장소다. 자동 기록으로 덮지 않는다",
                }
                return state

        if code_write_allowed and not self._case_has_write_allowance(case_id):
            # 쓰기 허용이 하나도 없는 Case 에 쓰기를 만들어 주는 것은 **새 권한**이다.
            raise PolicyRefused([PolicyRefusal.AUTO_ADD_NEEDS_NEW_PERMISSION])

        now = utc_now()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO case_repository"
                " (case_id, repository_id, selection_source, code_write_allowed,"
                "  publish_allowed, selected_by, reason_summary, state, selected_at)"
                " VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)"
                " ON CONFLICT(case_id, repository_id) DO UPDATE SET"
                "   selection_source = excluded.selection_source,"
                "   code_write_allowed = excluded.code_write_allowed,"
                "   selected_by = excluded.selected_by,"
                "   reason_summary = excluded.reason_summary,"
                "   state = excluded.state,"
                "   selected_at = excluded.selected_at,"
                "   superseded_at = NULL",
                (
                    case_id,
                    repository_id,
                    RepositorySelectionSource.AUTO_IN_ALLOWANCE.value,
                    1 if code_write_allowed else 0,
                    selected_by,
                    _summary(reason_summary) if reason_summary else None,
                    PolicyState.CURRENT.value,
                    now,
                ),
            )
        state = self.case_repository_state(case_id)
        state["auto_selection"] = {
            "repository_id": repository_id,
            "changed": True,
            "detail": "기존 허용 범위 안이라 자동으로 기록했다. 게시 허용은 따라오지 않는다",
        }
        return state

    def _case_has_write_allowance(self, case_id: str) -> bool:
        """이 Case 가 **이미** 코드 쓰기를 허용받은 저장소를 갖고 있는가.

        자동 추가가 넓히는 것인지 아닌지를 가르는 값이다. 제외된 저장소는 세지 않는다.
        """
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM case_repository"
            " WHERE case_id = ? AND state = ? AND code_write_allowed = 1"
            " AND selection_source <> ?",
            (case_id, PolicyState.CURRENT.value, RepositorySelectionSource.EXCLUDED.value),
        ).fetchone()
        return bool(row["n"])

    def case_repository_state(self, case_id: str) -> dict[str, Any]:
        """이 Case 의 저장소 선택·허용과 아직 없는 기능의 표시.

        선택 기록이 없을 때 **"저장소가 없다"고 답하지 않는다.** P3-03까지의 Case 는
        Project 의 단일 저장소에서 실제로 작업했고 그 사실이 작업공간 기록에 있다.
        다만 그것은 "선택했다"는 기록이 아니므로 `implicit_single_repository` 로
        따로 표시한다 — 이행이 만들지 않은 결정을 조회가 만들어 내지 않는다.
        """
        case = self.get_case(case_id)
        rows = self.conn.execute(
            "SELECT r.*, pr.name AS repository_name, pr.repo_path AS repo_path,"
            " pr.source AS repository_source"
            " FROM case_repository r JOIN project_repository pr ON pr.id = r.repository_id"
            " WHERE r.case_id = ? ORDER BY r.selected_at",
            (case_id,),
        ).fetchall()
        recorded = [dict(r) for r in rows]
        current = [r for r in recorded if r["state"] == PolicyState.CURRENT.value]
        excluded = [
            r
            for r in current
            if r["selection_source"] == RepositorySelectionSource.EXCLUDED.value
        ]
        # **제외된 저장소를 선택 목록에 넣지 않는다.** 한 목록에 함께 두면 화면이
        # 제외를 선택으로 보여 주고, R2 의 자동 추가가 제외 경계를 읽을 근거가 흐려진다.
        selected = [r for r in current if r not in excluded]
        project = self.get_project(case["project_id"])
        implicit: dict[str, Any] | None = None
        # **기록이 하나도 없을 때만** 암묵적 단일 저장소를 표시한다. 제외만 기록된
        # Case 는 판단이 있었던 Case 이므로 없던 가정을 씌우지 않는다.
        if not recorded:
            registered = self.list_project_repositories(case["project_id"])
            if len(registered) == 1:
                implicit = {
                    "repository_id": registered[0]["id"],
                    "repo_path": registered[0]["repo_path"],
                    "detail": "선택이 기록되지 않았다. 이 Case 는 Project 의 단일 저장소에서"
                    " 동작하며 그것은 이행된 가정이지 기록된 선택이 아니다",
                }
        return {
            "case_id": case_id,
            "selected": selected,
            "excluded": excluded,
            "implicit_single_repository": implicit,
            "journal_repository_id": project.get("journal_repository_id"),
            "write_allowance_implies_publish": False,
            "enforcement": {
                "selection": self.ENFORCEMENT["repository_selection"],
                "publish": self.ENFORCEMENT["publish"],
            },
        }
