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
from controller.admission import AdmissionRequest, AdmissionResult
from controller.admission import evaluate as evaluate_admission
from controller.db import transaction, utc_now
from domain import ids, prep_doc
from domain.models import (
    AcceptanceMode,
    AcceptanceRefusal,
    AdmissionOutcome,
    ArtifactKind,
    AuthoringMode,
    Availability,
    AxisWeight,
    CapabilityState,
    CandidateState,
    CaseKind,
    CaseRelationKind,
    CaseStatus,
    ClosureKind,
    CompletionMode,
    ConfirmationState,
    ContentOrigin,
    ContextRefRole,
    CriterionState,
    CriterionVerdict,
    DecideAt,
    DecisionKind,
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
    Permission,
    PreparationStage,
    PreparationState,
    QuestionState,
    ReadRequestState,
    ReviewMode,
    RunOutcome,
    RunPurpose,
    RunRole,
    RunStatus,
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
)

MAX_SUMMARY = 200


class ConflictError(Exception):
    """요청이 현재 상태와 맞지 않는다. HTTP 409로 돌려준다."""


class NotFoundError(Exception):
    """대상 기록이 없다. HTTP 404로 돌려준다."""


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

    def create_case(self, project_id: str, title: str, kind: CaseKind) -> dict[str, Any]:
        self.get_project(project_id)
        case_id = ids.new_case_id()
        now = utc_now()
        with transaction(self.conn):
            self.conn.execute(
                'INSERT INTO "case" (id, project_id, title, kind, status, created_at, updated_at)'
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (case_id, project_id, _summary(title), kind.value, CaseStatus.RECEIVED.value, now, now),
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
                self.conn.execute(
                    "UPDATE criterion_result SET verdict = ?, recorded_at = ?"
                    " WHERE criterion_id IN ("
                    "   SELECT id FROM success_criterion"
                    "   WHERE case_id = ? AND intent_version_id != ?"
                    " ) AND verdict != ?",
                    (
                        CriterionVerdict.NEEDS_RECHECK.value,
                        now,
                        case_id,
                        intent_id,
                        CriterionVerdict.NEEDS_RECHECK.value,
                    ),
                )
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
    ) -> tuple[dict[str, Any], bool]:
        """Run을 만든다. 같은 `run_id` 의 재전송은 기존 Run을 그대로 돌려준다.

        반환값의 두 번째 항목이 True면 이번 호출이 실제로 만든 것이다.
        이것이 중복 실행 방지의 첫 번째 층이다(P1 이월 항목).

        **진입 조건 검사는 여기서 하지 않는다.** `admit_and_create_run()` 이 검사한
        뒤에 이 메서드를 부른다. 두 가지를 한 함수에 섞으면 "검사를 건너뛰는 생성
        경로"가 생기기 때문에 호출 순서를 그 한 곳으로 모은다.
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
        try:
            with transaction(self.conn):
                self.conn.execute(
                    "INSERT INTO run (run_id, case_id, task_id, role, tool_id, mode, permission,"
                    " instruction_artifact_id, instruction_artifact_rev, status,"
                    " assignment_generation, created_at, purpose)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    ),
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
        return [self.get_run(r["run_id"]) for r in rows]

    def claim_assignments(self, runner_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """대기 중인 Run을 이 Runner에 배정한다.

        배정은 세대(`assignment_generation`)와 함께 내려간다. Runner는 보고할 때
        같은 세대를 제시해야 하며 오래된 세대의 보고는 거부된다(NFR-03).
        """
        self.get_runner(runner_id)
        claimed: list[dict[str, Any]] = []
        with transaction(self.conn):
            rows = self.conn.execute(
                "SELECT run_id FROM run WHERE status = ? ORDER BY created_at LIMIT ?",
                (RunStatus.PENDING.value, limit),
            ).fetchall()
            for row in rows:
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
        run["repo_path"] = project["repo_path"]
        run["case_title"] = case["title"]
        run["case_kind"] = case["kind"]
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
        latest_intent = self.latest_intent_version(run["case_id"])
        run["current_intent_version_id"] = latest_intent["id"] if latest_intent else None
        return run

    def bump_generation(self, run_id: str) -> dict[str, Any]:
        """재배정. 세대를 올리고 다시 대기 상태로 돌린다.

        **이것은 "이전 실행자가 멈췄다"는 증거가 아니다.** 세대는 오래된 실행자의 보고가
        최신 상태를 덮어쓰지 못하게 막을 뿐이다. 실제 정지 확인은 별도 문제다
        (NFR-01: "단절만으로 다른 Runner에 동일 쓰기를 재배정하지 않는다").
        """
        run = self.get_run(run_id)
        if run["status"] == RunStatus.FINISHED.value:
            raise ConflictError("run already finished")
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE run SET assignment_generation = assignment_generation + 1,"
                " status = ?, assigned_runner_id = NULL, assigned_at = NULL WHERE run_id = ?",
                (RunStatus.PENDING.value, run_id),
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
                return run  # 같은 결과의 재전송. 덮어쓰지 않는다
            raise ConflictError(
                f"run already finished with outcome {run['outcome']}; refusing to overwrite"
            )
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
                    utc_now(),
                    run_id,
                ),
            )
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
    ) -> dict[str, Any]:
        """Runner가 계산한 의도 구조를 반영한다.

        여섯 항목이 모두 와야 한다. 하나라도 빠지면 거부한다 —
        "정보가 없으면 항목을 삭제한다"가 아니라 `undecided` 로 남기는 것이 규칙이다.
        """
        intent = self.get_intent_version(intent_version_id)
        rows = list(fields)
        given = {row["field"] for row in rows}
        required = {f.value for f in IntentField}
        if given != required:
            missing = sorted(required - given)
            extra = sorted(given - required)
            raise ConflictError(
                f"intent structure must carry all six fields; missing={missing} extra={extra}"
            )

        now = utc_now()
        with transaction(self.conn):
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
                        IntentField(row["field"]).value,
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
        # 작업 수준 판단도 같은 보고로 들어온다(P3-01). 같은 이유다 — 축별 근거를
        # 따로 입력받는 본문 API 를 만들면 제어부가 그 서술을 갖게 된다.
        # `None` 이면 아무 것도 만들지 않는다. **수준 미결정은 미결정으로 남는다.**
        self.apply_sizing_report(intent_version_id, sizing)
        # 구조가 보고된 순간이 규칙 검사가 가능해진 순간이다. 여기서 한 번 돌려
        # 게이트 상태를 항상 최신 구조에 맞춰 둔다. **AI 검토는 건드리지 않는다** —
        # 규칙만 통과한 상태는 여전히 `not_run` 이다.
        self.evaluate_gate_rules(intent_version_id)
        return self.get_intent_detail(intent_version_id)

    def list_intent_fields(self, intent_version_id: str) -> list[dict[str, Any]]:
        order = {f.value: i for i, f in enumerate(IntentField)}
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
                ai_verdict = GateVerdict(existing["ai_verdict"])
                self.conn.execute(
                    "UPDATE gate_result SET rule_verdict = ?, verdict = ?, evaluated_at = ?,"
                    " subject_content_hash = ? WHERE id = ?",
                    (
                        rule_verdict.value,
                        gatemod.combine_verdicts(rule_verdict, ai_verdict).value,
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
            self.conn.execute(
                "UPDATE gate_result SET ai_verdict = ?, verdict = ?, ai_run_id = ?,"
                " ai_session_ref = ?, author_session_ref = ?, reviewed_at = ? WHERE id = ?",
                (
                    ai_verdict.value,
                    gatemod.combine_verdicts(rule_verdict, ai_verdict).value,
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

    # ------------------------------------------------------ FR-29 진입 조건 검사

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
        )
        if not result.admitted:
            check = self.record_admission(
                case_id, run_id, task_id, purpose, role, permission, tool_id, result, None
            )
            return None, False, result, check

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
        )
        if created:
            # **고정 컨텍스트를 여기서 정한다.** 배정 시점이 아니라 생성 시점에
            # 고정하는 이유는 "실행이 무엇을 보고 썼는가"가 재배정으로 달라지면
            # 안 되기 때문이다(review-context-contract 2절 "버전이 고정된 참조 목록").
            self.record_context_refs(run["run_id"], self.compose_context_refs(case_id, purpose))
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
        now = utc_now()
        with transaction(self.conn):
            for row in rows:
                self.conn.execute(
                    "INSERT INTO success_criterion"
                    " (id, case_id, intent_version_id, criterion_key, summary,"
                    "  method_summary, relates_to, state, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(intent_version_id, criterion_key) DO UPDATE SET"
                    "   summary = excluded.summary,"
                    "   method_summary = excluded.method_summary,"
                    "   relates_to = excluded.relates_to",
                    (
                        ids.new_id("crit"),
                        intent["case_id"],
                        intent_version_id,
                        str(row["key"]),
                        _summary(row["summary"]),
                        _summary(row.get("method_summary", "")),
                        IntentField(row["relates_to"]).value,
                        CriterionState.PROPOSED.value,
                        now,
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

    def list_success_criteria(self, intent_version_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT c.*, r.verdict, r.evidence_kind, r.evidence_run_id,"
            "       r.evidence_artifact_id, r.evidence_artifact_rev,"
            "       r.summary AS result_summary, r.recorded_by, r.recorded_at"
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
    ) -> dict[str, Any]:
        """기준별 판정을 기록한다.

        **여기가 "실행 불명이 성공이 되지 않는다"를 강제하는 지점이다.**

        `met` 을 받으려면 근거 Run 의 `outcome` 이 `completed` 여야 한다.
        `unknown`·`failed`·`cancelled` 를 근거로 한 `met` 은 거부한다. 종료 코드나
        "실행이 끝났다"는 사실로 충족을 적지 않는다(FR-28, completion-lifecycle 5절).

        `needs_recheck` 는 사람이 직접 적는 값이 아니다 — 대상이 바뀌었을 때
        시스템이 전이시키는 값이므로 여기서는 거부한다.
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

        now = utc_now()
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE criterion_result SET verdict = ?, evidence_kind = ?,"
                " evidence_run_id = ?, evidence_artifact_id = ?, evidence_artifact_rev = ?,"
                " summary = ?, recorded_by = ?, recorded_at = ? WHERE criterion_id = ?",
                (
                    verdict.value,
                    evidence_kind.value,
                    evidence_run_id,
                    evidence_artifact_id,
                    evidence_artifact_rev,
                    _summary(summary),
                    recorded_by,
                    now,
                    criterion_id,
                ),
            )
        return self.get_criterion_result(criterion_id)

    def get_criterion_result(self, criterion_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM criterion_result WHERE criterion_id = ?", (criterion_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"criterion result not found: {criterion_id}")
        return dict(row)

    # ----------------------------------------------------------- 완료 정책

    def completion_mode(self, case_id: str) -> CompletionMode:
        """Case 의 완료 정책. **행이 없으면 기본값(사람 최종 확인)이다**(D-31)."""
        row = self.conn.execute(
            "SELECT mode FROM completion_policy WHERE case_id = ?", (case_id,)
        ).fetchone()
        if row is None:
            return CompletionMode.HUMAN_ACCEPTANCE
        return CompletionMode(row["mode"])

    def set_completion_mode(
        self, case_id: str, mode: CompletionMode, set_by: str
    ) -> dict[str, Any]:
        self.get_case(case_id)
        self.guard_open_case(case_id)
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO completion_policy (case_id, mode, set_by, set_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(case_id) DO UPDATE SET"
                "   mode = excluded.mode, set_by = excluded.set_by, set_at = excluded.set_at",
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
                "  unsettled_runs_json, snapshot_hash, state, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
        if self.completion_mode(candidate["case_id"]) is CompletionMode.AUTO_ON_CONDITIONS:
            # 자동 완료 모드가 예외를 수용하지 않는다는 규칙은 요청 경로에서도
            # 막아야 한다. 정책을 사람 확인으로 되돌린 뒤에 수용해야 한다.
            raise ConflictError(
                f"{AcceptanceRefusal.AUTO_POLICY_CANNOT_ACCEPT_EXCEPTION.value}:"
                " switch the case back to human acceptance to decide an exception"
            )
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
        self, from_case_id: str, title: str, kind: CaseKind, reason_summary: str
    ) -> dict[str, Any]:
        """종료된 업무의 후속 수정을 위한 새 Case를 만들고 출처로 연결한다.

        **이전 동의를 승계하지 않는다.** 새 Case는 의도 버전이 0개로 시작하므로
        기능 개발이면 새 초안·새 동의·새 게이트를 다시 거친다(D-33,
        completion-lifecycle 6절 "이전 인수나 의도 동의를 포괄 허용으로 쓰지 않는다").
        """
        origin = self.get_case(from_case_id)
        new_case = self.create_case(origin["project_id"], title, kind)
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
        if stage is PreparationStage.PLAN and task_rows:
            self.create_work_graph_revision(
                case_id=prep["case_id"],
                plan_preparation_id=prep_id,
                tasks=task_rows,
                source=WorkGraphSource.PLAN_ARTIFACT,
                reason_summary=f"개발계획 v{prep['revision']} 이 정의한 작업",
                actor=self.PLAN_GRAPH_ACTOR,
            )
        return self.get_preparation_artifact(prep_id)

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
        """이 단계의 검토 방식. **행이 없으면 사람 검토다**(D-14 프로젝트 기본값).

        없음을 자동 진행으로 읽으면 기본값이 조용히 뒤집힌다. 그래서 기본값을
        이 한 곳에서만 해석한다.
        """
        row = self.conn.execute(
            "SELECT mode FROM stage_review_setting WHERE case_id = ? AND stage = ?",
            (case_id, PreparationStage(stage).value),
        ).fetchone()
        return ReviewMode(row["mode"]) if row else ReviewMode.HUMAN_REVIEW

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
            return existing
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
            "mode_source": "project_default" if setting is None else "case_setting",
            "mode_reason": (setting["reason_summary"] if setting else "프로젝트 기본값"),
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
            "deferred_open_questions": self.deferred_open_questions(case_id),
            # P3-02. 준비 조건 **위에 얹히는** 상태다. 계획 검토가 끝났다는 사실과
            # 무엇을 어떤 순서로 만들지가 정해졌다는 사실은 다른 것이다.
            "work_graph": self.work_graph_state(case_id),
        }

    # ------------------------------------------------- P3-01 고정 컨텍스트

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

        latest = self.latest_intent_version(case_id)
        if purpose is RunPurpose.INTENT_AUTHORING:
            if latest is not None:
                add(ContextRefRole.PREVIOUS_INTENT, latest["artifact_id"], latest["artifact_rev"])
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
                if plan is not None:
                    add(ContextRefRole.PREVIOUS_PLAN, plan["artifact_id"], plan["artifact_rev"])
        return refs

    def record_context_refs(self, run_id: str, refs: list[dict[str, Any]]) -> None:
        with transaction(self.conn):
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
        return {
            "case_id": case_id,
            "completion_mode": self.completion_mode(case_id).value,
            "criteria": self.current_criteria(case_id),
            "unsettled_runs": self.unsettled_runs(case_id),
            "candidate": self.current_completion_candidate(case_id),
            "closure": self.get_closure(case_id),
            "relations": self.list_case_relations(case_id),
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
        rows = self.conn.execute(
            "SELECT * FROM task WHERE graph_revision_id = ? ORDER BY order_index",
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
        if PreparationStage(prep["stage"]) is not PreparationStage.PLAN:
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
                self.conn.execute(
                    "INSERT INTO task (id, case_id, graph_revision_id, task_key, kind,"
                    " relates_to, summary, deliverable_summary, completion_summary,"
                    " order_index, origin, cancelled, cancel_reason, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
