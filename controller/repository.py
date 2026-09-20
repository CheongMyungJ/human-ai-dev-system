"""제어부 상태 DB 접근.

이 계층은 SQL만 다루고 HTTP를 모른다. 정책 판단은 최소한으로 두되
아래 두 가지는 여기서 지킨다.

  - 원문 본문을 저장하지 않는다. 본문을 받는 인자가 없다.
  - 같은 `run_id` 는 두 번 만들어지지 않는다.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable

from controller import gate as gatemod
from controller.admission import AdmissionRequest, AdmissionResult
from controller.admission import evaluate as evaluate_admission
from controller.db import transaction, utc_now
from domain import ids
from domain.models import (
    AdmissionOutcome,
    ArtifactKind,
    AuthoringMode,
    Availability,
    CapabilityState,
    CaseKind,
    CaseStatus,
    ConfirmationState,
    ContentOrigin,
    DecideAt,
    DecisionKind,
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
    QuestionState,
    ReadRequestState,
    RunOutcome,
    RunPurpose,
    RunRole,
    RunStatus,
)

MAX_SUMMARY = 200


class ConflictError(Exception):
    """요청이 현재 상태와 맞지 않는다. HTTP 409로 돌려준다."""


class NotFoundError(Exception):
    """대상 기록이 없다. HTTP 404로 돌려준다."""


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

        request = AdmissionRequest(
            case_id=case_id,
            case_kind=CaseKind(case["kind"]),
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
        check = self.record_admission(
            case_id, run_id, task_id, purpose, role, permission, tool_id, result, run["run_id"]
        )
        return run, created, result, check
