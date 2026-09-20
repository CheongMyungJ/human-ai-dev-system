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

from controller.db import transaction, utc_now
from domain import ids
from domain.models import (
    ArtifactKind,
    Availability,
    CapabilityState,
    CaseKind,
    CaseStatus,
    DecisionKind,
    IntentStatus,
    Permission,
    RunOutcome,
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
        self, case_id: str, artifact_id: str, artifact_rev: int
    ) -> dict[str, Any]:
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
                " status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (intent_id, case_id, revision, artifact_id, artifact_rev, IntentStatus.DRAFT.value, now),
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
        """사람의 결정을 기록한다.

        P2-01은 기록만 한다. 이 결정이 실행을 열어 주는지의 검사(FR-29 진입 조건)는
        P2-03에서 붙인다. 지금 통과 처리를 넣어 두지 않는다.
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
            if kind is DecisionKind.INTENT_AGREEMENT and subject_type == "intent_version":
                # 동의는 그 버전에만 붙는다. 이후 버전으로 자동 승계되지 않는다(FR-23).
                self.conn.execute(
                    "UPDATE intent_version SET status = ? WHERE id = ? AND revision = ?",
                    (IntentStatus.AGREED.value, subject_id, subject_revision),
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
    ) -> tuple[dict[str, Any], bool]:
        """Run을 만든다. 같은 `run_id` 의 재전송은 기존 Run을 그대로 돌려준다.

        반환값의 두 번째 항목이 True면 이번 호출이 실제로 만든 것이다.
        이것이 중복 실행 방지의 첫 번째 층이다(P1 이월 항목).
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
                    " assignment_generation, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
        return [self.get_run(rid) for rid in claimed]

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
