"""옛 스키마의 DB를 올려도 기록을 잃지도, 없던 값을 지어내지도 않는지.

`CREATE TABLE IF NOT EXISTS` 만으로는 기존 표의 컬럼이 늘어나지 않는다. 그래서 v2는
`decision.subject_content_hash` 를 별도로 더하는데, 이 경로가 기존 행을 건드리면
사람의 과거 결정 기록이 사라진다. NFR-01은 저장 완료로 응답한 결정이 남아 있기를
요구하므로 여기서 실제 v1 DB를 만들어 확인한다.

v3도 같은 문제를 갖는다. `run.purpose` 와 `intent_version.authoring_mode` 는
옛 행에 존재하지 않던 개념이므로 NULL 로 남아야 한다.

**옛 스키마는 커밋된 것을 그대로 꺼내 쓴다.** 시험 안에 스키마를 베껴 두면
그 사본이 실제 과거와 달라져도 시험이 통과해 버린다.
"""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

from controller import db
from controller.db import utc_now
from controller.repository import Repository
from domain.models import ConformanceMethod

REPO_ROOT = Path(__file__).resolve().parent.parent


def _committed_schema(ref: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{ref}:controller/schema.sql"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if result.returncode != 0:
        pytest.skip(f"git 에서 {ref} 의 스키마를 꺼낼 수 없다")
    return result.stdout.decode("utf-8")


def _v1_schema() -> str:
    """v2 표가 없는 가장 최근 커밋 스키마를 찾는다."""
    log = subprocess.run(
        ["git", "log", "--format=%H", "-20", "--", "controller/schema.sql"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if log.returncode != 0:
        pytest.skip("git 이력을 읽을 수 없다")
    for commit in log.stdout.decode("utf-8").split():
        schema = _committed_schema(commit)
        if "intent_field" not in schema and "CREATE TABLE IF NOT EXISTS decision" in schema:
            return schema
    pytest.skip("v1 스키마를 가진 커밋을 찾지 못했다")


def test_a_v1_database_upgrades_without_losing_records(tmp_path):
    schema = _v1_schema()
    path = tmp_path / "controller.sqlite3"

    # --- 실제 v1 DB를 만들고 기록을 넣는다 ---
    old = sqlite3.connect(path)
    old.row_factory = sqlite3.Row
    old.executescript(schema)
    now = utc_now()
    old.execute("INSERT INTO schema_version (version, applied_at) VALUES (1, ?)", (now,))
    old.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    old.execute("INSERT INTO project VALUES ('prj-1','own-1','old','C:/tmp','codex',?)", (now,))
    old.execute(
        'INSERT INTO "case" VALUES (?,?,?,?,?,?,?)',
        ("case-1", "prj-1", "v1 시절 Case", "feature", "received", now, now),
    )
    old.execute(
        "INSERT INTO decision (id, case_id, kind, subject_type, subject_id, subject_revision,"
        " actor, decided_at) VALUES ('dec-1','case-1','design_review','case','case-1',1,"
        " 'owner', ?)",
        (now,),
    )
    old.commit()
    assert "subject_content_hash" not in {
        r["name"] for r in old.execute("PRAGMA table_info(decision)")
    }
    old.close()

    # --- 새 코드로 연다 ---
    conn = db.connect(path)
    db.migrate(conn)

    assert conn.execute('SELECT title FROM "case"').fetchone()["title"] == "v1 시절 Case"
    assert conn.execute("SELECT COUNT(*) c FROM decision").fetchone()["c"] == 1
    assert "subject_content_hash" in {
        r["name"] for r in conn.execute("PRAGMA table_info(decision)")
    }

    new_tables = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN"
            " ('intent_field','intent_question','feedback','intent_view','artifact_read_request')"
        )
    }
    assert len(new_tables) == 5, new_tables

    # v1 시절 결정의 새 컬럼은 NULL 이다. 과거 기록을 지어내지 않는다.
    assert conn.execute("SELECT subject_content_hash FROM decision").fetchone()[0] is None

    # 다시 돌려도 아무 것도 바뀌지 않는다.
    versions = conn.execute("SELECT COUNT(*) c FROM schema_version").fetchone()["c"]
    db.migrate(conn)
    assert conn.execute("SELECT COUNT(*) c FROM schema_version").fetchone()["c"] == versions
    assert conn.execute("SELECT COUNT(*) c FROM decision").fetchone()["c"] == 1
    conn.close()


def _v2_schema() -> str:
    """v3 표가 없는 가장 최근 커밋 스키마를 찾는다."""
    log = subprocess.run(
        ["git", "log", "--format=%H", "-20", "--", "controller/schema.sql"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if log.returncode != 0:
        pytest.skip("git 이력을 읽을 수 없다")
    for commit in log.stdout.decode("utf-8").split():
        schema = _committed_schema(commit)
        if "gate_result" not in schema and "intent_field" in schema:
            return schema
    pytest.skip("v2 스키마를 가진 커밋을 찾지 못했다")


def test_a_v2_database_upgrades_without_inventing_the_new_columns(tmp_path):
    """v2 → v3. **옛 행의 새 컬럼을 지어내지 않는다.**

    v2 시절에는 실행의 '목적'도, 의도 초안의 '작성 주체'도 개념이 없었다. 그 행에
    지금 와서 `limited_analysis` 나 `human_typed` 를 적으면 기록되지 않은 것을
    확인된 것으로 바꾸는 셈이다. NULL 로 남겨 구별한다(FR-04).
    """
    schema = _v2_schema()
    path = tmp_path / "controller.sqlite3"

    old = sqlite3.connect(path)
    old.row_factory = sqlite3.Row
    old.executescript(schema)
    now = utc_now()
    old.execute("INSERT INTO schema_version (version, applied_at) VALUES (2, ?)", (now,))
    old.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    old.execute("INSERT INTO project VALUES ('prj-1','own-1','old','C:/tmp','codex',?)", (now,))
    old.execute(
        'INSERT INTO "case" VALUES (?,?,?,?,?,?,?)',
        ("case-1", "prj-1", "v2 시절 Case", "feature", "received", now, now),
    )
    old.execute("INSERT INTO runner VALUES ('run-1','r','h','registered',?,?)", (now, now))
    old.execute(
        "INSERT INTO artifact_ref VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("art-1", 1, "case-1", "intent", "sha256:x", 10, "run-1", "available", "요약", now),
    )
    old.execute(
        "INSERT INTO intent_version (id, case_id, revision, artifact_id, artifact_rev,"
        " status, created_at) VALUES ('iv-1','case-1',1,'art-1',1,'draft',?)",
        (now,),
    )
    old.execute(
        "INSERT INTO run (run_id, case_id, task_id, role, tool_id, mode, permission,"
        " instruction_artifact_id, instruction_artifact_rev, status, assignment_generation,"
        " created_at) VALUES ('r-1','case-1','t-1','author','local-echo','p2-01-local',"
        " 'read_only','art-1',1,'finished',1,?)",
        (now,),
    )
    old.commit()
    old.close()

    conn = db.connect(path)
    db.migrate(conn)

    # 기존 기록은 그대로다.
    assert conn.execute('SELECT title FROM "case"').fetchone()["title"] == "v2 시절 Case"
    assert conn.execute("SELECT COUNT(*) c FROM run").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM intent_version").fetchone()["c"] == 1

    # 새 표가 생겼다. v3 의 게이트·진입 표, v4 의 결과·완료 표, v5 의 수준·준비 표가
    # 모두 있어야 한다.
    expected = {
        "gate_result",
        "gate_finding",
        "admission_check",
        "success_criterion",
        "criterion_result",
        "completion_policy",
        "completion_candidate",
        "candidate_criterion",
        "final_acceptance",
        "exception_decision",
        "closure_record",
        "case_relation",
        "sizing_assessment",
        "sizing_axis",
        "preparation_artifact",
        "preparation_section",
        "stage_review_setting",
        "stage_review",
        "run_context_ref",
        # v6 의 작업 그래프 표.
        "work_graph_revision",
        "task",
        "task_dependency",
        "task_criterion",
        "task_question_block",
        "task_block_unresolved",
        "question_block_ref",
        # v7 의 작업공간·명령 표.
        "case_workspace",
        "run_command",
    }
    placeholders = ",".join("?" for _ in expected)
    new_tables = {
        r["name"]
        for r in conn.execute(
            f"SELECT name FROM sqlite_master WHERE type='table' AND name IN ({placeholders})",
            sorted(expected),
        )
    }
    assert new_tables == expected, sorted(expected - new_tables)

    # **완료 정책 행은 생기지 않는다.** 행이 없는 것이 기본값(사람 최종 확인)이며,
    # 옛 Case 를 자동 완료로 바꾸지 않는다(D-31).
    assert conn.execute("SELECT COUNT(*) c FROM completion_policy").fetchone()["c"] == 0

    # **단계 검토 설정 행도 생기지 않는다**(P3-01 AC-1·AC-14). 행이 없는 것이
    # 기본값(설계·계획 모두 사람 검토)이며, 옛 Case 를 자동 진행으로 바꾸지 않는다.
    # 같은 이유로 수준 판단 행도 만들지 않는다 — 옛 Case 는 수준 미결정이고
    # "간소"가 아니다.
    assert conn.execute("SELECT COUNT(*) c FROM stage_review_setting").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM sizing_assessment").fetchone()["c"] == 0

    # **작업 그래프 행도 생기지 않는다**(P3-02 AC-15). 행이 없다는 것은 "Task 가
    # 필요 없다"가 아니라 그래프가 아직 없다는 뜻이고, 그 Case 의 기능 구현은
    # `work_graph_missing` 으로 막힌다. 없음을 통과로 읽지 않는 것이 핵심이다.
    assert conn.execute("SELECT COUNT(*) c FROM work_graph_revision").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM task").fetchone()["c"] == 0

    # 옛 `run.task_id` 도 그대로다. P3-02가 그 값을 `task_key` 로 해석하게 됐을 뿐
    # 옛 행의 값을 바꾸지 않는다.
    assert conn.execute("SELECT task_id FROM run").fetchone()["task_id"] == "t-1"

    # **작업공간 행도 생기지 않는다**(P3-03 AC-14). 행이 없다는 것은 "작업공간이
    # 필요 없다"가 아니라 아직 준비되지 않았다는 뜻이고, 그 Case 의 쓰기는
    # `workspace_not_ready` 로 막힌다.
    assert conn.execute("SELECT COUNT(*) c FROM case_workspace").fetchone()["c"] == 0

    # 옛 실행의 `workspace_effect_json` 은 NULL 로 남는다. 그것은 "변경이 없었다"가
    # 아니라 **관측하지 않았다**는 뜻이며, 지금 와서 값을 지어내지 않는다(FR-04).
    assert conn.execute("SELECT workspace_effect_json e FROM run").fetchone()["e"] is None
    assert conn.execute("SELECT COUNT(*) c FROM run_command").fetchone()["c"] == 0

    # 옛 질문 행의 새 컬럼도 NULL 이다. P3-01 전에는 의도 단계 말고 다른 단계가
    # 없었으므로 NULL 은 "의도 단계에서 제기됨"과 일치한다.
    columns = {r["name"] for r in conn.execute('PRAGMA table_info("intent_question")')}
    assert {"raised_in_stage", "preparation_id"} <= columns

    # 옛 행의 새 컬럼은 NULL 이다. 기록되지 않은 것과 확인된 것을 구별한다.
    assert conn.execute("SELECT purpose FROM run").fetchone()[0] is None
    row = conn.execute(
        "SELECT authoring_mode, author_run_id FROM intent_version"
    ).fetchone()
    assert row["authoring_mode"] is None
    assert row["author_run_id"] is None

    # 현재 스키마 버전까지 올라간다. 숫자를 여기 박아 두면 스키마가 오를 때마다
    # 시험이 거짓으로 깨지므로 코드의 상수와 대조한다.
    assert (
        conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()["v"]
        == db.SCHEMA_VERSION
    )

    # 다시 돌려도 아무 것도 바뀌지 않는다.
    versions = conn.execute("SELECT COUNT(*) c FROM schema_version").fetchone()["c"]
    db.migrate(conn)
    assert conn.execute("SELECT COUNT(*) c FROM schema_version").fetchone()["c"] == versions
    conn.close()


def _v7_schema() -> str:
    """v8 표가 없는 가장 최근 커밋 스키마를 찾는다(P3-R1).

    **커밋된 것을 그대로 꺼내 쓴다.** 시험 안에 스키마를 베껴 두면 그 사본이 실제
    과거와 달라져도 시험이 통과해 버린다.
    """
    log = subprocess.run(
        ["git", "log", "--format=%H", "-30", "--", "controller/schema.sql"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if log.returncode != 0:
        pytest.skip("git 이력을 읽을 수 없다")
    for commit in log.stdout.decode("utf-8").split():
        schema = _committed_schema(commit)
        if "case_policy" not in schema and "case_workspace" in schema:
            return schema
    pytest.skip("v7 스키마를 가진 커밋을 찾지 못했다")


def test_a_v7_database_keeps_its_records_and_marks_the_policy_as_unrecorded(tmp_path):
    """v7 → v8 (P3-R1 AC-5·AC-8·AC-13).

    **이 시험이 R1의 가장 중요한 경계를 지킨다.** v0.6에서 사람이 설계·계획을
    검토하고 결과를 인수하기로 하고 진행한 Case 에 "기본 ask-on-decision"을 적용하면,
    새 정책이 기존 승인·동의·권한에 소급 적용된다(DEVELOPMENT.md 3절).

    그래서 이행은 두 가지만 한다.

        Project 의 `repo_path` 를 등록 저장소 한 건으로 옮긴다(같은 값)
        기존 Case 에 **미기록** 정책 행을 명시로 넣는다(`autonomy` 는 NULL)

    그리고 **하지 않는 것**을 함께 확인한다. Profile 을 `kind` 에서 유도해 채우지
    않고, Case 의 저장소 선택을 만들지 않고, 예산·확인 지점을 만들지 않는다.
    """
    schema = _v7_schema()
    path = tmp_path / "controller.sqlite3"

    old = sqlite3.connect(path)
    old.row_factory = sqlite3.Row
    old.executescript(schema)
    now = utc_now()
    old.execute("INSERT INTO schema_version (version, applied_at) VALUES (7, ?)", (now,))
    old.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    old.execute(
        "INSERT INTO project VALUES ('prj-1','own-1','old','C:/tmp/old-repo','codex',?)",
        (now,),
    )
    old.execute(
        'INSERT INTO "case" VALUES (?,?,?,?,?,?,?)',
        ("case-1", "prj-1", "v7 시절 Case", "feature", "in_progress", now, now),
    )
    # v0.6에서 사람이 실제로 한 결정들. 이행이 이 기록을 건드리면 안 된다.
    old.execute(
        "INSERT INTO decision (id, case_id, kind, subject_type, subject_id,"
        " subject_revision, actor, decided_at) VALUES ('dec-1','case-1',"
        " 'intent_agreement','intent_version','iv-1',1,'owner',?)",
        (now,),
    )
    old.execute(
        "INSERT INTO completion_policy (case_id, mode, set_by, set_at)"
        " VALUES ('case-1','human_acceptance','owner',?)",
        (now,),
    )
    old.execute(
        "INSERT INTO stage_review_setting (case_id, stage, mode, set_by,"
        " reason_summary, set_at) VALUES ('case-1','design','human_review','owner',"
        " '사람이 검토하기로 했다',?)",
        (now,),
    )
    old.commit()
    old.close()

    conn = db.connect(path)
    db.migrate(conn)

    # --- 기존 기록은 그대로다 ------------------------------------------
    assert conn.execute('SELECT title FROM "case"').fetchone()["title"] == "v7 시절 Case"
    assert conn.execute("SELECT COUNT(*) c FROM decision").fetchone()["c"] == 1
    assert (
        conn.execute("SELECT mode FROM completion_policy").fetchone()["mode"]
        == "human_acceptance"
    )
    assert (
        conn.execute("SELECT mode FROM stage_review_setting").fetchone()["mode"]
        == "human_review"
    )

    # --- Profile 은 기록되지 않은 채 남는다 -----------------------------
    case = conn.execute('SELECT * FROM "case"').fetchone()
    assert case["profile"] is None, "kind 에서 유도해 채우면 새 규칙의 소급 적용이다"
    assert case["profile_version"] is None
    assert case["kind"] == "feature", "기존 유형 기록은 보존한다"

    # --- 정책은 **미기록**이다. 기본값으로 읽지 않는다 ------------------
    policy = conn.execute("SELECT * FROM case_policy WHERE case_id = 'case-1'").fetchone()
    assert policy is not None, "이행은 미기록을 명시로 남긴다"
    assert policy["autonomy"] is None
    assert policy["autonomy_source"] == "migrated_unknown"
    assert policy["policy_version"] == "0.6", "당시 규칙판을 남긴다"
    assert policy["set_by"] == "migration", "사람이 결정한 것으로 적지 않는다"

    # --- 등록 저장소는 같은 값으로 옮겨진다 -----------------------------
    repo = conn.execute("SELECT * FROM project_repository").fetchone()
    assert repo["repo_path"] == "C:/tmp/old-repo"
    assert repo["source"] == "migrated_from_project"
    assert repo["registered_by"] == "migration"
    # 기존 컬럼은 지우지 않는다. 배정·작업공간 경로가 그 값을 쓴다.
    assert (
        conn.execute("SELECT repo_path FROM project").fetchone()["repo_path"]
        == "C:/tmp/old-repo"
    )
    # 기록 저장소는 **미지정**이다. 하나뿐인 저장소를 기록용으로 만들지 않는다.
    assert conn.execute("SELECT journal_repository_id FROM project").fetchone()[0] is None

    # --- 만들지 않는 것 -------------------------------------------------
    for table in ("case_repository", "budget_setting", "controlled_checkpoint",
                  "delegation_basis"):
        count = conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
        assert count == 0, f"{table} 에 이행이 만든 행이 있다"

    assert (
        conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()["v"]
        == db.SCHEMA_VERSION
    )

    # 다시 돌려도 행이 늘지 않는다. `migrate()` 는 연결마다 돈다.
    db.migrate(conn)
    assert conn.execute("SELECT COUNT(*) c FROM project_repository").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM case_policy").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM decision").fetchone()["c"] == 1
    conn.close()


def _v8_schema() -> str:
    """v9 표가 없는 가장 최근 커밋 스키마를 찾는다(P3-R2).

    **커밋된 것을 그대로 꺼내 쓴다.** 시험 안에 스키마를 베껴 두면 그 사본이 실제
    과거와 달라져도 시험이 통과해 버린다.
    """
    log = subprocess.run(
        ["git", "log", "--format=%H", "-30", "--", "controller/schema.sql"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if log.returncode != 0:
        pytest.skip("git 이력을 읽을 수 없다")
    for commit in log.stdout.decode("utf-8").split():
        schema = _committed_schema(commit)
        if "code_composition" not in schema and "case_policy" in schema:
            return schema
    pytest.skip("v8 스키마를 가진 커밋을 찾지 못했다")


def test_a_v8_workspace_keeps_its_branch_base_commit_and_worktree(tmp_path):
    """v8 → v9 (P3-R2 AC-1).

    **이 시험이 R2의 가장 위험한 지점을 지킨다.** `case_workspace` 는 기본 키가
    `case_id` 였고 이미 준비된 작업공간 행이 거기 있다. SQLite 에서 기본 키를
    바꾸려면 표를 다시 만들어 옮겨야 하는데, 그 과정에서

        행을 잃으면 "어떤 코드 위에서 시작했는가"의 답이 사라지고,
        worktree 경로를 새 규칙으로 바꾸면 이미 한 작업이 떨어져 나가며,
        어느 저장소인지 지어내면 기록이 거짓이 된다.

    셋을 모두 확인한다. 허용 출처가 `implicit_single_repository` 인 것도 함께 본다 —
    이행이 "이 Case 가 그 저장소를 선택했다"는 결정을 새로 만들지 않기 때문이다.
    """
    schema = _v8_schema()
    path = tmp_path / "controller.sqlite3"

    old = sqlite3.connect(path)
    old.row_factory = sqlite3.Row
    old.executescript(schema)
    now = utc_now()
    old.execute("INSERT INTO schema_version (version, applied_at) VALUES (8, ?)", (now,))
    old.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    old.execute(
        "INSERT INTO project (id, owner_id, name, repo_path, default_tool_id, created_at)"
        " VALUES ('prj-1','own-1','old','C:/tmp/old-repo','codex',?)",
        (now,),
    )
    old.execute(
        'INSERT INTO "case" (id, project_id, title, kind, status, created_at, updated_at)'
        " VALUES ('case-1','prj-1','v8 시절 Case','feature','in_progress',?,?)",
        (now, now),
    )
    old.execute(
        "INSERT INTO project_repository"
        " (id, project_id, name, repo_path, source, registered_by, registered_at)"
        " VALUES ('repo-1','prj-1','primary','C:/tmp/old-repo','migrated_from_project',"
        " 'migration',?)",
        (now,),
    )
    old.execute(
        "INSERT INTO runner (id, name, host, status, registered_at)"
        " VALUES ('runner-1','pc','host-1','registered',?)",
        (now,),
    )
    # 실제로 준비돼 있던 작업공간. 사용자의 미커밋 변경 관측까지 들어 있다.
    old.execute(
        "INSERT INTO case_workspace (case_id, project_id, state, branch, runner_id,"
        " repo_path, worktree_path, base_commit, base_ref, user_tree_dirty,"
        " user_tree_entries, failure_reason, requested_at, ready_at)"
        " VALUES ('case-1','prj-1','ready','hads/case-1','runner-1','C:/tmp/old-repo',"
        " 'C:/tmp/worktrees/case-1','abc1234def5678','HEAD',1,3,'',?,?)",
        (now, now),
    )
    old.commit()
    old.close()

    conn = db.connect(path)
    db.migrate(conn)

    workspace = conn.execute("SELECT * FROM case_workspace").fetchone()
    assert workspace is not None, "이행이 작업공간 행을 잃었다"
    # --- 무엇으로 시작했는가는 그대로다 ---------------------------------
    assert workspace["branch"] == "hads/case-1"
    assert workspace["base_commit"] == "abc1234def5678"
    assert workspace["base_ref"] == "HEAD"
    assert workspace["state"] == "ready"
    assert workspace["runner_id"] == "runner-1"
    # --- **경로를 옮기지 않는다.** 옮기면 이미 한 작업이 떨어져 나간다 ---
    assert workspace["worktree_path"] == "C:/tmp/worktrees/case-1"
    assert workspace["repo_path"] == "C:/tmp/old-repo"
    # --- 사용자 트리 관측도 남는다 ---------------------------------------
    assert workspace["user_tree_dirty"] == 1
    assert workspace["user_tree_entries"] == 3
    # --- 어느 저장소인지는 **등록된 것 하나**로 확인해서 연결한다 --------
    assert workspace["repository_id"] == "repo-1"
    # --- 허용 출처: 선택 기록을 지어내지 않았다 --------------------------
    assert workspace["allowance_source"] == "implicit_single_repository"
    assert conn.execute("SELECT COUNT(*) c FROM case_repository").fetchone()["c"] == 0

    # --- 새 축은 **미기록**이다 -------------------------------------------
    assert conn.execute("SELECT repository_id FROM run").fetchall() == []
    assert conn.execute("SELECT COUNT(*) c FROM code_composition").fetchone()["c"] == 0

    assert (
        conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()["v"]
        == db.SCHEMA_VERSION
    )

    # 다시 돌려도 행이 늘거나 다시 옮겨지지 않는다. `migrate()` 는 연결마다 돈다.
    db.migrate(conn)
    assert conn.execute("SELECT COUNT(*) c FROM case_workspace").fetchone()["c"] == 1
    assert (
        conn.execute("SELECT worktree_path FROM case_workspace").fetchone()["worktree_path"]
        == "C:/tmp/worktrees/case-1"
    )
    conn.close()


def _v9_schema() -> str:
    """v10 표가 없는 가장 최근 커밋 스키마를 찾는다(P3-R3).

    **커밋된 것을 그대로 꺼내 쓴다.** 시험 안에 스키마를 베껴 두면 그 사본이 실제
    과거와 달라져도 시험이 통과해 버린다.
    """
    log = subprocess.run(
        ["git", "log", "--format=%H", "-30", "--", "controller/schema.sql"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if log.returncode != 0:
        pytest.skip("git 이력을 읽을 수 없다")
    for commit in log.stdout.decode("utf-8").split():
        schema = _committed_schema(commit)
        if "budget_reservation" not in schema and "code_composition" in schema:
            return schema
    pytest.skip("v9 스키마를 가진 커밋을 찾지 못했다")


def test_a_v9_database_keeps_the_consumption_that_already_happened(tmp_path):
    """v9 → v10 (P3-R3 AC-17).

    **이 시험이 R3의 두 번째로 위험한 지점을 지킨다.** 집계의 출처를 새 표 하나로
    만들면서 R3 이전에 실제로 돈 실행에 행을 만들지 않으면, **스키마를 올리는 것만으로
    그 Case 의 소비가 0 이 된다.** "세션·Task 분할로 초기화하지 않는다"(D-61)는
    이행에도 그대로 적용된다.

    함께 보는 것이 하나 더 있다. 토큰을 보고하지 않은 옛 실행을 **0 으로 적지 않는
    것**이다 — 0 으로 적으면 한도가 영원히 남아 있는 것처럼 보인다.
    """
    schema = _v9_schema()
    path = tmp_path / "controller.sqlite3"

    old = sqlite3.connect(path)
    old.row_factory = sqlite3.Row
    old.executescript(schema)
    now = utc_now()
    old.execute("INSERT INTO schema_version (version, applied_at) VALUES (9, ?)", (now,))
    old.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    old.execute(
        "INSERT INTO project (id, owner_id, name, repo_path, default_tool_id, created_at)"
        " VALUES ('prj-1','own-1','old','C:/tmp/old-repo','codex',?)",
        (now,),
    )
    old.execute(
        'INSERT INTO "case" (id, project_id, title, kind, status, created_at, updated_at)'
        " VALUES ('case-1','prj-1','v9 시절 Case','analysis','in_progress',?,?)",
        (now, now),
    )
    old.execute(
        "INSERT INTO runner (id, name, host, status, registered_at)"
        " VALUES ('runner-1','pc','host-1','registered',?)",
        (now,),
    )
    old.execute(
        "INSERT INTO artifact_ref (artifact_id, revision, case_id, kind, content_hash,"
        " byte_size, owner_runner_id, availability, summary, created_at)"
        " VALUES ('art-1',1,'case-1','instruction','h'*1,1200,'runner-1','available',"
        " '지시',?)",
        (now,),
    )
    # 실제 v9 DB 는 `run.purpose`·`run.repository_id` 를 갖는다. 그 둘은
    # schema.sql 이 아니라 `_add_column_if_missing` 이 더하므로 여기서 같은 모양을
    # 만든다 — 커밋된 schema.sql 만으로는 v9 의 실제 표가 되지 않는다.
    old.execute("ALTER TABLE run ADD COLUMN purpose TEXT")
    old.execute("ALTER TABLE run ADD COLUMN repository_id TEXT")

    # 실제로 돈 실행 셋. 작성 둘(하나는 결과 불명) + 검토 하나.
    for run_id, role, outcome, status, usage in (
        ("run-1", "author", "completed", "finished", '{"tokens": {"input_tokens": 900,'
         ' "output_tokens": 120}, "cost_usd": 0.4}'),
        ("run-2", "reviewer", "completed", "finished", '"not_reported"'),
        ("run-3", "author", None, "assigned", '"not_reported"'),
    ):
        old.execute(
            "INSERT INTO run (run_id, case_id, task_id, role, tool_id, mode, permission,"
            " instruction_artifact_id, instruction_artifact_rev, status,"
            " assignment_generation, outcome, usage_json, residual_activity, created_at,"
            " assigned_at, finished_at, purpose)"
            " VALUES (?, 'case-1','task-1',?, 'codex','cli','read_only','art-1',1,?,1,?,"
            " ?, 'none', ?, ?, ?, 'limited_analysis')",
            (
                run_id,
                role,
                status,
                outcome,
                usage,
                now,
                "2026-09-21T00:00:00.000000+00:00",
                "2026-09-21T00:00:30.000000+00:00" if status == "finished" else None,
            ),
        )
    old.commit()
    old.close()

    conn = db.connect(path)
    db.migrate(conn)

    rows = {
        (r["run_id"], r["metric"]): r
        for r in conn.execute("SELECT * FROM budget_reservation")
    }
    assert rows, "이행이 기존 실행의 소비를 집계에 넣지 않았다"

    # --- 이미 있던 소비가 남는다 -----------------------------------------
    assert rows[("run-1", "run_count")]["actual_value"] == 1.0
    assert rows[("run-1", "run_count")]["state"] == "settled"
    assert rows[("run-1", "run_count")]["source"] == "migrated_from_run"
    # 지시 원문의 크기가 컨텍스트 패키지로 잡힌다.
    assert rows[("run-1", "context_bytes")]["actual_value"] == 1200.0
    # 시계에서 도출한 실행 시간.
    assert rows[("run-1", "execution_seconds")]["actual_value"] == 30.0

    # --- 검토 실행만 검토 축에 잡힌다 -------------------------------------
    assert ("run-2", "review_run_count") in rows
    assert ("run-1", "review_run_count") not in rows
    # 그리고 검토도 전체 실행 수에는 그대로 들어간다(중복 차감하지 않는다).
    assert rows[("run-2", "run_count")]["actual_value"] == 1.0

    # --- **미보고를 0 으로 적지 않는다** -----------------------------------
    unreported = rows[("run-2", "input_tokens")]
    assert unreported["actual_value"] is None
    assert unreported["measurement"] == "unavailable"
    assert unreported["state"] == "unresolved"
    assert unreported["settle_source"] == "adapter_not_reported"
    # 보고한 실행은 값이 남는다.
    assert rows[("run-1", "input_tokens")]["actual_value"] == 900.0
    assert rows[("run-1", "estimated_cost")]["actual_value"] == 0.4

    # --- 진행 중 실행은 **끝난 것으로 바뀌지 않는다** ---------------------
    assert rows[("run-3", "run_count")]["state"] == "held"
    assert rows[("run-3", "run_count")]["actual_value"] is None

    assert (
        conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()["v"]
        == db.SCHEMA_VERSION
    )

    # 다시 돌려도 행이 늘지 않는다. `migrate()` 는 연결마다 돈다.
    before = conn.execute("SELECT COUNT(*) c FROM budget_reservation").fetchone()["c"]
    db.migrate(conn)
    assert conn.execute("SELECT COUNT(*) c FROM budget_reservation").fetchone()["c"] == before
    conn.close()


# ===================================================== v10 → v11 (P3-R4)


def _v10_schema() -> str:
    """v11 표가 없는 가장 최근 커밋 스키마를 찾는다(P3-R4).

    `_v9_schema` 와 같은 방식이다 — **커밋된 것을 그대로 꺼내 쓴다.** 시험 안에
    스키마를 베껴 두면 그 사본이 실제 과거와 달라져도 시험이 통과해 버린다.
    """
    log = subprocess.run(
        ["git", "log", "--format=%H", "-30", "--", "controller/schema.sql"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if log.returncode != 0:
        pytest.skip("git 이력을 읽을 수 없다")
    for commit in log.stdout.decode("utf-8").split():
        schema = _committed_schema(commit)
        if "material_delta" not in schema and "budget_reservation" in schema:
            return schema
    pytest.skip("v10 스키마를 가진 커밋을 찾지 못했다")


def test_a_v10_database_keeps_its_completion_and_review_defaults(tmp_path):
    """v10 → v11 (P3-R4 AC-29·AC-29b).

    **이 시험이 R4의 세 번째 위험을 지킨다.** v0.6 기본값(사람 검토·사람 인수)으로
    진행하던 Case 에 새 기본값을 얹으면, 사람이 확인하기로 하고 시작한 업무가 조용히
    자동 완료 대상이 된다. 이행은 그 반대를 보장해야 한다.

    네 가지를 본다.

        명시 설정       `migrated_explicit` 로 남고 도출값이 덮지 않는다
        단계 검토       Autonomy 미기록 Case 는 v0.6 기본값(사람 검토)을 유지한다
        Autonomy        `NULL`·`migrated_unknown` 그대로이며 controlled 로 적히지 않는다
        옛 게이트 통과  실제로 독립 검토를 거쳤으므로 `independent` 로 옮겨진다
    """
    schema = _v10_schema()
    path = tmp_path / "controller.sqlite3"

    old = sqlite3.connect(path)
    old.row_factory = sqlite3.Row
    old.executescript(schema)
    now = utc_now()
    old.execute("INSERT INTO schema_version (version, applied_at) VALUES (10, ?)", (now,))
    old.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    old.execute(
        "INSERT INTO project (id, owner_id, name, repo_path, default_tool_id, created_at)"
        " VALUES ('prj-1','own-1','old','C:/tmp/old-repo','codex',?)",
        (now,),
    )
    for case_id, title in (("case-1", "명시 설정이 있던 Case"), ("case-2", "설정이 없던 Case")):
        old.execute(
            'INSERT INTO "case" (id, project_id, title, kind, status, created_at, updated_at)'
            " VALUES (?, 'prj-1', ?, 'feature','in_progress',?,?)",
            (case_id, title, now, now),
        )
    # **사람이 자동 완료를 명시로 고른 Case.** 도출값이 이 설정을 덮으면 안 된다.
    old.execute(
        "INSERT INTO completion_policy (case_id, mode, set_by, set_at)"
        " VALUES ('case-1','auto_on_conditions','owner',?)",
        (now,),
    )
    # 실제로 AI 의미 검토를 거쳐 통과한 게이트.
    old.execute(
        "INSERT INTO runner (id, name, host, status, registered_at)"
        " VALUES ('runner-1','pc','host-1','registered',?)",
        (now,),
    )
    old.execute(
        "INSERT INTO artifact_ref (artifact_id, revision, case_id, kind, content_hash,"
        " byte_size, owner_runner_id, availability, summary, created_at)"
        " VALUES ('art-1',1,'case-1','intent','hash-1',100,'runner-1','available','의도',?)",
        (now,),
    )
    old.execute(
        "INSERT INTO intent_version (id, case_id, revision, artifact_id, artifact_rev,"
        " status, created_at) VALUES ('iv-1','case-1',1,'art-1',1,'agreed',?)",
        (now,),
    )
    old.execute(
        "INSERT INTO run (run_id, case_id, task_id, role, tool_id, mode, permission,"
        " instruction_artifact_id, instruction_artifact_rev, status,"
        " assignment_generation, outcome, created_at)"
        " VALUES ('run-review','case-1','task-1','reviewer','codex','cli','read_only',"
        " 'art-1',1,'finished',1,'completed',?)",
        (now,),
    )
    old.execute(
        "INSERT INTO gate_result (id, case_id, gate, intent_version_id,"
        " subject_content_hash, verdict, rule_verdict, ai_verdict, ai_run_id,"
        " evaluated_at, reviewed_at)"
        " VALUES ('gate-1','case-1','QG-01','iv-1','hash-1','pass','pass','pass',"
        " 'run-review',?,?)",
        (now, now),
    )
    old.commit()
    old.close()

    conn = db.connect(path)
    db.migrate(conn)
    repo = Repository(conn)

    # --- 1. 명시 설정은 명시 설정으로 남는다 ------------------------------
    state = repo.completion_mode_state("case-1")
    assert state["mode"] == "auto_on_conditions"
    assert state["source"] == "migrated_explicit"

    # --- 2. Autonomy 는 **미기록** 그대로다 --------------------------------
    policy = repo.effective_policy("case-2")
    assert policy["autonomy"] is None
    assert policy["autonomy_recorded"] is False
    assert policy["autonomy_source"] == "migrated_unknown"
    # 취급만 controlled 다. 그 사실이 출처로 구별된다.
    assert policy["effective_autonomy"] == "controlled"
    assert policy["effective_source"] == "migrated_unknown_treated_as_controlled"
    assert policy["is_treatment"] is True

    # --- 3. 단계 검토 기본값은 v0.6 그대로다 -------------------------------
    prep = repo.preparation_state("case-2")
    assert prep["design"]["mode"] == "human_review"
    assert prep["plan"]["mode"] == "human_review"
    assert prep["design"]["mode_source"] == "migrated_default"

    # --- 4. 설정이 없던 Case 의 완료도 사람 확인이다 -----------------------
    # controlled 취급이므로 도출값이 사람 인수다. 자동 완료로 바뀌지 않는다.
    assert repo.completion_mode_state("case-2")["mode"] == "human_acceptance"
    assert repo.completion_mode_state("case-2")["source"] == "autonomy_derived"

    # --- 5. 옛 게이트 통과는 **독립 검토**로 옮겨진다 ----------------------
    # 지어내는 것이 아니다. R4 이전의 `pass` 는 AI 검토 없이는 나올 수 없는 값이었다.
    check = repo.get_conformance_check("iv-1", ConformanceMethod.INDEPENDENT)
    assert check is not None
    assert check["method"] == "independent"
    assert check["run_id"] == "run-review"
    assert check["verdict"] == "pass"
    # 가벼운 확인 행은 만들어지지 않는다.
    assert repo.get_conformance_check("iv-1", ConformanceMethod.LIGHT) is None

    # --- 6. 새 컬럼은 **비어 있다** ----------------------------------------
    columns = {r["name"] for r in conn.execute('PRAGMA table_info("criterion_result")')}
    assert {"satisfaction", "recheck_source"} <= columns

    assert (
        conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()["v"]
        == db.SCHEMA_VERSION
    )

    # 다시 돌려도 정합성 확인 행이 늘지 않는다. `migrate()` 는 연결마다 돈다.
    before = conn.execute("SELECT COUNT(*) c FROM conformance_check").fetchone()["c"]
    db.migrate(conn)
    assert conn.execute("SELECT COUNT(*) c FROM conformance_check").fetchone()["c"] == before
    conn.close()


# ===================================================================== v12
#
# P3-04. Task × Repository.


def _v11_schema() -> str:
    """`task.repository_id` 가 없는 가장 최근 커밋 스키마를 찾는다(P3-04).

    `_v10_schema` 와 같은 방식이다 — **커밋된 것을 그대로 꺼내 쓴다.** 새 컬럼은
    `schema.sql` 이 아니라 `db.py` 가 더하므로, v12 를 커밋한 뒤에도 이 함수는
    v11 시절의 `schema.sql` 을 그대로 찾는다. 그래서 판별 문자열은 스키마 파일에
    실제로 들어간 v12 표식(`스키마 v12`)을 쓴다.
    """
    log = subprocess.run(
        ["git", "log", "--format=%H", "-30", "--", "controller/schema.sql"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if log.returncode != 0:
        pytest.skip("git 이력을 읽을 수 없다")
    for commit in log.stdout.decode("utf-8").split():
        schema = _committed_schema(commit)
        if "스키마 v12" not in schema and "conformance_check" in schema:
            return schema
    pytest.skip("v11 스키마를 가진 커밋을 찾지 못했다")


def test_a_v11_database_keeps_its_tasks_without_inventing_a_repository(tmp_path):
    """v11 → v12 (P3-04 AC-20).

    **이 시험이 P3-04의 소급 위험을 지킨다.** 새 컬럼을 더하면서 기존 Task 에
    작업공간이나 등록 저장소로 값을 채우면, 계획이 하지 않은 판단을 이행이 만든
    것이 된다(D-62 "유도해 채우지 않는다"). 그리고 저장소가 하나뿐인 옛 Case 의
    실행은 **그대로 배정돼야 한다** — 미기록을 모든 Case 에서 막으면 진행 중이던
    업무가 멈춘다.
    """
    schema = _v11_schema()
    path = tmp_path / "controller.sqlite3"

    old = sqlite3.connect(path)
    old.row_factory = sqlite3.Row
    old.executescript(schema)
    now = utc_now()
    old.execute("INSERT INTO schema_version (version, applied_at) VALUES (11, ?)", (now,))
    old.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    old.execute(
        "INSERT INTO project (id, owner_id, name, repo_path, default_tool_id, created_at)"
        " VALUES ('prj-1','own-1','old','C:/tmp/old-repo','codex',?)",
        (now,),
    )
    old.execute(
        "INSERT INTO project_repository (id, project_id, name, repo_path, source,"
        " registered_by, registered_at)"
        " VALUES ('repo-1','prj-1','primary','C:/tmp/old-repo','registered','owner',?)",
        (now,),
    )
    old.execute(
        'INSERT INTO "case" (id, project_id, title, kind, status, created_at, updated_at)'
        " VALUES ('case-1','prj-1','옛 Case','feature','in_progress',?,?)",
        (now, now),
    )
    old.execute(
        "INSERT INTO runner (id, name, host, status, registered_at)"
        " VALUES ('runner-1','pc','host-1','registered',?)",
        (now,),
    )
    old.execute(
        "INSERT INTO artifact_ref (artifact_id, revision, case_id, kind, content_hash,"
        " byte_size, owner_runner_id, availability, summary, created_at)"
        " VALUES ('art-1',1,'case-1','intent','hash-1',100,'runner-1','available','의도',?)",
        (now,),
    )
    old.execute(
        "INSERT INTO intent_version (id, case_id, revision, artifact_id, artifact_rev,"
        " status, created_at) VALUES ('iv-1','case-1',1,'art-1',1,'agreed',?)",
        (now,),
    )
    old.execute(
        "INSERT INTO preparation_artifact (id, case_id, stage, revision, intent_version_id,"
        " level, artifact_id, artifact_rev, author_run_id, authoring_mode, summary,"
        " state, created_at)"
        " VALUES ('prep-1','case-1','plan',1,'iv-1','simple','art-1',1,"
        " 'run-plan','ai_drafted','옛 계획','current',?)",
        (now,),
    )
    old.execute(
        "INSERT INTO work_graph_revision (id, case_id, revision, intent_version_id,"
        " plan_preparation_id, source, reason_summary, actor, state, created_at)"
        " VALUES ('wg-1','case-1',1,'iv-1','prep-1','plan_artifact','계획이 정의',"
        " 'policy:plan_artifact','current',?)",
        (now,),
    )
    old.execute(
        "INSERT INTO task (id, case_id, graph_revision_id, task_key, kind, relates_to,"
        " summary, deliverable_summary, completion_summary, order_index, origin,"
        " cancelled, cancel_reason, created_at)"
        " VALUES ('task-1','case-1','wg-1','T1','implementation','goal','옛 작업',"
        " '산출물','완료 조건',1,'ai_proposal',0,'',?)",
        (now,),
    )
    old.commit()
    old.close()

    conn = db.connect(path)
    db.migrate(conn)
    repo = Repository(conn)

    # --- 1. 옛 Task 는 **미기록 그대로다** ---------------------------------
    row = conn.execute("SELECT * FROM task WHERE id = 'task-1'").fetchone()
    assert row["repository_id"] is None
    assert row["repository_ref"] == ""

    # --- 2. 그 미기록이 **이 Case 에서는 아무 것도 막지 않는다** -----------
    # 고를 수 있는 저장소가 하나뿐이면 모호하지 않다.
    state = repo.task_repository_state("case-1", "T1")
    assert state["present"] is True
    assert state["repository_id"] is None
    assert state["choice_count"] <= 1

    # --- 3. 화면이 보는 값에도 미기록이 그대로 드러난다 --------------------
    graph = repo.work_graph_state("case-1")
    task = next(t for t in graph["tasks"] if t["task_key"] == "T1")
    assert task["repository_id"] is None
    assert task["repository_name"] is None

    assert (
        conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()["v"]
        == db.SCHEMA_VERSION
    )

    # 다시 돌려도 Task 가 늘지 않고 값이 채워지지 않는다.
    db.migrate(conn)
    assert conn.execute("SELECT COUNT(*) c FROM task").fetchone()["c"] == 1
    assert conn.execute("SELECT repository_id FROM task").fetchone()["repository_id"] is None
    conn.close()


# ===================================================================== v13


def _v12_schema() -> str:
    """P4-01 표가 없고 v12 표식이 있는 마지막 커밋 스키마."""
    log = subprocess.run(
        ["git", "log", "--format=%H", "-30", "--", "controller/schema.sql"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if log.returncode != 0:
        pytest.skip("git 이력을 읽을 수 없다")
    for commit in log.stdout.decode("utf-8").split():
        schema = _committed_schema(commit)
        if "스키마 v12" in schema and "스키마 v13" not in schema:
            return schema
    pytest.skip("v12 스키마를 가진 커밋을 찾지 못했다")


def test_a_v12_database_keeps_qg01_and_invents_no_gate_pass_or_repair(tmp_path):
    """v12 → v13: 기존 QG-01은 보존하고 새 판정·repair를 지어내지 않는다."""
    path = tmp_path / "controller.sqlite3"
    old = sqlite3.connect(path)
    old.row_factory = sqlite3.Row
    old.executescript(_v12_schema())
    now = utc_now()
    old.execute("INSERT INTO schema_version (version, applied_at) VALUES (12, ?)", (now,))
    old.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    old.execute(
        "INSERT INTO project (id, owner_id, name, repo_path, default_tool_id, created_at)"
        " VALUES ('prj-1','own-1','old','C:/tmp/old','codex',?)", (now,)
    )
    old.execute(
        'INSERT INTO "case" (id, project_id, title, kind, status, created_at, updated_at)'
        " VALUES ('case-1','prj-1','v12 Case','feature','in_progress',?,?)", (now, now)
    )
    old.execute(
        "INSERT INTO runner (id, name, host, status, registered_at)"
        " VALUES ('runner-1','pc','host-1','registered',?)", (now,)
    )
    old.execute(
        "INSERT INTO artifact_ref (artifact_id, revision, case_id, kind, content_hash,"
        " byte_size, owner_runner_id, availability, summary, created_at)"
        " VALUES ('art-1',1,'case-1','intent','hash-1',100,'runner-1','available','의도',?)",
        (now,),
    )
    old.execute(
        "INSERT INTO intent_version (id, case_id, revision, artifact_id, artifact_rev,"
        " status, created_at) VALUES ('iv-1','case-1',1,'art-1',1,'agreed',?)", (now,)
    )
    old.execute(
        "INSERT INTO gate_result (id, case_id, gate, intent_version_id, subject_content_hash,"
        " verdict, rule_verdict, ai_verdict, evaluated_at)"
        " VALUES ('gate-1','case-1','QG-01','iv-1','hash-1','fail','pass','fail',?)",
        (now,),
    )
    old.commit()
    old.close()

    conn = db.connect(path)
    db.migrate(conn)
    assert conn.execute("SELECT verdict FROM gate_result WHERE id='gate-1'").fetchone()[0] == "fail"
    for table in (
        "quality_gate_policy", "quality_gate_run", "quality_gate_finding",
        "remediation_cycle", "remediation_attempt",
    ):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    # **현재 스키마까지 올라간다.** 고정 숫자를 쓰지 않는 이유는 이 시험이 묻는
    # 것이 "13이 됐는가"가 아니라 "v12 기록이 지금 스키마에서 보존되는가"이기
    # 때문이다. v13→v14 자체는 아래 전용 시험이 본다.
    assert (
        conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        == db.SCHEMA_VERSION
    )

    db.migrate(conn)
    assert conn.execute("SELECT COUNT(*) FROM gate_result").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM remediation_cycle").fetchone()[0] == 0
    conn.close()


# ===================================================================== v14
#
# P4-02. 정책 행에 **요청 시각과 적용 시각**이 생겼다. v13 까지는 예약 경로가
# 아예 없었으므로 기록된 모든 정책은 만들어진 순간 적용된 것이고, 이행은 그
# 사실만 적는다. 없던 예약·취소·재검증을 지어내지 않는다.


def _v13_schema() -> str:
    """P4-02 표가 없고 v13 표식이 있는 마지막 커밋 스키마."""
    log = subprocess.run(
        ["git", "log", "--format=%H", "-30", "--", "controller/schema.sql"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if log.returncode != 0:
        pytest.skip("git 이력을 읽을 수 없다")
    for commit in log.stdout.decode("utf-8").split():
        schema = _committed_schema(commit)
        if "스키마 v13" in schema and "스키마 v14" not in schema:
            return schema
    pytest.skip("v13 스키마를 가진 커밋을 찾지 못했다")


def _v13_database(path) -> str:
    """정책 한 줄과 통과 한 줄이 있는 v13 DB 를 만든다."""
    old = sqlite3.connect(path)
    old.row_factory = sqlite3.Row
    old.executescript(_v13_schema())
    now = utc_now()
    old.execute("INSERT INTO schema_version (version, applied_at) VALUES (13, ?)", (now,))
    old.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    old.execute(
        "INSERT INTO project (id, owner_id, name, repo_path, default_tool_id, created_at)"
        " VALUES ('prj-1','own-1','old','C:/tmp/old','codex',?)", (now,)
    )
    old.execute(
        'INSERT INTO "case" (id, project_id, title, kind, status, created_at, updated_at)'
        " VALUES ('case-1','prj-1','v13 Case','feature','in_progress',?,?)", (now, now)
    )
    old.execute(
        "INSERT INTO quality_gate_policy (id, case_id, task_key, gate, revision, setting,"
        " inspection, repair_limit, source, set_by, reason_summary, state, created_at)"
        " VALUES ('qpol-1','case-1','','QG-06',1,'on',NULL,3,'case_explicit','owner',"
        "'한도를 올린다','current',?)", (now,)
    )
    old.execute(
        "INSERT INTO quality_gate_run (id, case_id, task_key, gate, subject_key, input_hash,"
        " policy_fingerprint, inspection_required, inspection_used, status, verdict, validity,"
        " context_refs_json, criteria_refs_json, evidence_refs_json, created_at, completed_at)"
        " VALUES ('qrun-1','case-1','','QG-06','case','hash-1','fp-1','rule','rule',"
        "'completed','fail','current','[\"request@1\"]','[\"criterion-1\"]','[]',?,?)",
        (now, now),
    )
    old.execute(
        "INSERT INTO remediation_cycle (id, case_id, gate, subject_key, task_key,"
        " initial_gate_run_id, repair_limit, used_attempts, reserved_attempts, state,"
        " created_at, updated_at)"
        " VALUES ('rc-1','case-1','QG-06','case','','qrun-1',3,1,0,'active',?,?)",
        (now, now),
    )
    old.commit()
    old.close()
    return now


def test_a_v13_database_gets_an_application_time_and_invents_no_reservation(tmp_path):
    """v13 → v14: 적용 시각만 채우고 예약·취소·재검증을 만들지 않는다."""
    path = tmp_path / "controller.sqlite3"
    created_at = _v13_database(path)

    conn = db.connect(path)
    db.migrate(conn)

    policy = conn.execute(
        "SELECT * FROM quality_gate_policy WHERE id = 'qpol-1'"
    ).fetchone()
    # v13 까지는 예약 경로가 없었다. 그래서 만들어진 순간이 적용 순간이다.
    assert policy["state"] == "current"
    assert policy["applied_at"] == created_at
    assert policy["requested_at"] == created_at
    assert policy["apply_boundary"] == "immediate"
    assert policy["cancelled_at"] is None

    run = conn.execute("SELECT * FROM quality_gate_run WHERE id = 'qrun-1'").fetchone()
    # **0 이 아니라 NULL 이다.** 그때는 시작 시점에 고정한 리비전이 없었고, 지금
    # 값을 적으면 "그 검사가 이 정책으로 돌았다"는 없는 사실이 생긴다.
    assert run["started_policy_revision"] is None
    assert run["late_result"] == 0
    assert run["stop_requested_at"] is None
    assert run["verdict"] == "fail"
    assert run["validity"] == "current"

    # 기존 repair 누적은 그대로다.
    cycle = conn.execute("SELECT * FROM remediation_cycle WHERE id = 'rc-1'").fetchone()
    assert cycle["used_attempts"] == 1
    assert cycle["repair_limit"] == 3

    # 새 기록을 지어내지 않는다.
    for table in ("quality_change_event", "quality_revalidation"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM quality_gate_policy WHERE state IN ('pending','cancelled')"
    ).fetchone()[0] == 0
    assert (
        conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        == db.SCHEMA_VERSION
    )

    # 반복 이행이 멱등이다.
    db.migrate(conn)
    again = conn.execute(
        "SELECT applied_at, requested_at FROM quality_gate_policy WHERE id = 'qpol-1'"
    ).fetchone()
    assert again["applied_at"] == created_at
    assert again["requested_at"] == created_at
    assert conn.execute("SELECT COUNT(*) FROM quality_gate_policy").fetchone()[0] == 1
    conn.close()


# ===================================================================== P4-03


def _v14_schema() -> str:
    """P4-03 표식이 없고 v14 표식이 있는 마지막 커밋 스키마.

    v15 의 새 컬럼은 `schema.sql` 이 아니라 `db.py` 가 더한다. 그래서 판별 문자열은
    스키마 파일에 실제로 들어간 표식(`스키마 v15`)을 쓴다 — `_v11_schema` 와 같은 방식.
    """
    log = subprocess.run(
        ["git", "log", "--format=%H", "-30", "--", "controller/schema.sql"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if log.returncode != 0:
        pytest.skip("git 이력을 읽을 수 없다")
    for commit in log.stdout.decode("utf-8").split():
        schema = _committed_schema(commit)
        if "스키마 v14" in schema and "스키마 v15" not in schema:
            return schema
    pytest.skip("v14 스키마를 가진 커밋을 찾지 못했다")


def test_a_v14_database_keeps_its_criteria_and_invents_no_obligation(tmp_path):
    """v14 → v15 (P4-03 AC-19).

    **이 시험이 P4-03 의 소급 위험을 지킨다.** 옛 기준에 연결 항목에서 의무를 도출해
    채우면, v1 Profile 로 시작한 Case 가 갑자기 "방식 없는 met 은 받지 않는다"·"목적마다
    기준이 있어야 한다"를 받는다. 이행은 컬럼만 더하고 값은 NULL 로 둬야 한다.
    """
    path = tmp_path / "controller.sqlite3"
    old = sqlite3.connect(path)
    old.row_factory = sqlite3.Row
    old.executescript(_v14_schema())
    # 실제 v14 DB 에는 v8 이행이 붙인 Profile 컬럼이 있다. 커밋된 `schema.sql` 에는
    # 없으므로(컬럼은 `db.py` 가 더한다) 그 모습을 그대로 만든다.
    for column in ("profile", "profile_version", "profile_source"):
        old.execute(f'ALTER TABLE "case" ADD COLUMN {column} TEXT')
    now = utc_now()
    old.execute("INSERT INTO schema_version (version, applied_at) VALUES (14, ?)", (now,))
    old.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    old.execute(
        "INSERT INTO project (id, owner_id, name, repo_path, default_tool_id, created_at)"
        " VALUES ('prj-1','own-1','old','C:/tmp/old','codex',?)", (now,)
    )
    # v14 의 Case 는 정의판 "1" 이다. **이행이 올리지 않는다.**
    old.execute(
        'INSERT INTO "case" (id, project_id, title, kind, status, created_at, updated_at,'
        " profile, profile_version, profile_source)"
        " VALUES ('case-1','prj-1','v14 Case','bug','in_progress',?,?,"
        " 'defect_fix','1','explicit')", (now, now)
    )
    old.execute(
        "INSERT INTO runner (id, name, host, status, registered_at)"
        " VALUES ('runner-1','old','old-host','registered',?)", (now,)
    )
    old.execute(
        "INSERT INTO artifact_ref (artifact_id, revision, case_id, kind, owner_runner_id,"
        " content_hash, byte_size, summary, availability, created_at)"
        " VALUES ('art-1',1,'case-1','intent','runner-1','h',10,'의도','available',?)",
        (now,),
    )
    old.execute(
        "INSERT INTO intent_version (id, case_id, revision, artifact_id, artifact_rev,"
        " status, created_at)"
        " VALUES ('iv-1','case-1',1,'art-1',1,'agreed',?)", (now,)
    )
    old.execute(
        "INSERT INTO success_criterion (id, case_id, intent_version_id, criterion_key,"
        " summary, method_summary, relates_to, state, created_at)"
        " VALUES ('crit-1','case-1','iv-1','C-01','저장 뒤 값이 보인다','화면 확인',"
        " 'expected_behavior','user_confirmed',?)", (now,)
    )
    old.execute(
        "INSERT INTO criterion_result (id, criterion_id, case_id, verdict, evidence_kind,"
        " summary, recorded_by, recorded_at)"
        " VALUES ('res-1','crit-1','case-1','met','human_judgement','확인함','owner',?)",
        (now,),
    )
    old.commit()
    old.close()

    conn = db.connect(path)
    db.migrate(conn)

    case = conn.execute('SELECT * FROM "case" WHERE id = ?', ("case-1",)).fetchone()
    assert case["profile_version"] == "1"
    crit = conn.execute("SELECT * FROM success_criterion WHERE id = 'crit-1'").fetchone()
    # **의무를 지어내지 않는다.** `expected_behavior` 는 v2 대응표에서 restoration 이지만
    # 이 기준은 v1 으로 만들어졌다.
    assert crit["obligation"] is None
    assert crit["obligation_source"] is None
    assert crit["conclusion_rule"] is None
    result = conn.execute("SELECT * FROM criterion_result WHERE id = 'res-1'").fetchone()
    assert result["verdict"] == "met"
    assert result["conclusion"] is None
    assert result["satisfaction"] is None
    intent = conn.execute("SELECT * FROM intent_version WHERE id = 'iv-1'").fetchone()
    assert intent["objectives_json"] is None

    repo = Repository(conn)
    # v1 Case 에는 완료 계약이 없다 — 조회가 그렇게 말한다.
    assert repo.completion_contract("case-1") is None
    assert repo.completion_meaning("case-1")["contract"] is None
    # 이 시험의 뜻은 "v14 DB 가 **현재 판**으로 이행되고 그 사이 v15 규칙이 적용된다"다.
    # P4-03 시점에는 현재 판이 15 였다. UI-01(v16)부터는 v16 까지 이어서 가며, v16 자체의
    # 고정은 `test_a_v15_database_gets_no_conversation_it_never_had` 가 맡는다.
    assert (
        conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        == db.SCHEMA_VERSION
    )
    assert db.SCHEMA_VERSION >= 15

    # 새 컬럼의 값 제약. 본문이나 모르는 이름을 넣을 수 없다.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE success_criterion SET obligation = 'whatever' WHERE id = 'crit-1'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE criterion_result SET conclusion = 'probably' WHERE id = 'res-1'")

    # 반복 이행이 멱등이다.
    db.migrate(conn)
    again = conn.execute("SELECT * FROM success_criterion WHERE id = 'crit-1'").fetchone()
    assert again["obligation"] is None
    assert conn.execute("SELECT COUNT(*) FROM success_criterion").fetchone()[0] == 1
    conn.close()


# ===================================================================== UI-01


def _v15_schema() -> str:
    """UI-01 표식이 없고 v15 표식이 있는 마지막 커밋 스키마."""
    log = subprocess.run(
        ["git", "log", "--format=%H", "-30", "--", "controller/schema.sql"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if log.returncode != 0:
        pytest.skip("git 이력을 읽을 수 없다")
    for commit in log.stdout.decode("utf-8").split():
        schema = _committed_schema(commit)
        if "스키마 v15" in schema and "스키마 v16" not in schema:
            return schema
    pytest.skip("v15 스키마를 가진 커밋을 찾지 못했다")


def test_a_v15_database_gets_no_conversation_it_never_had(tmp_path):
    """v15 → v16 (UI-01 AC-16).

    **이 시험이 UI-01 의 소급 위험을 지킨다.** 옛 Case 에 단계·메시지·요청을 채우면
    그 Case 가 "대화에서 업무화됐다"로 읽히고, 없던 위임 근거·잠금이 생긴다. 이행은
    컬럼과 표만 더하고 값은 NULL 로 둬야 하며, 옛 Case 는 **업무 단계로 도출**된다.
    """
    path = tmp_path / "controller.sqlite3"
    old = sqlite3.connect(path)
    old.row_factory = sqlite3.Row
    old.executescript(_v15_schema())
    # 실제 v15 DB 에는 v8 이행이 붙인 Profile 컬럼이 있다(커밋된 `schema.sql` 에는 없다).
    for column in ("profile", "profile_version", "profile_source"):
        old.execute(f'ALTER TABLE "case" ADD COLUMN {column} TEXT')
    now = utc_now()
    old.execute("INSERT INTO schema_version (version, applied_at) VALUES (15, ?)", (now,))
    old.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    old.execute(
        "INSERT INTO project (id, owner_id, name, repo_path, default_tool_id, created_at)"
        " VALUES ('prj-1','own-1','old','C:/tmp/old','codex',?)", (now,)
    )
    # 정의판 1·2 Case 와 R1 이전 Case. **이행이 어느 것도 바꾸지 않는다.**
    for case_id, kind, profile, version in (
        ("case-v1", "bug", "defect_fix", "1"),
        ("case-v2", "feature", "feature", "2"),
        ("case-pre", "analysis", None, None),
    ):
        old.execute(
            'INSERT INTO "case" (id, project_id, title, kind, status, created_at, updated_at,'
            " profile, profile_version, profile_source)"
            " VALUES (?, 'prj-1', ?, ?, 'received', ?, ?, ?, ?, ?)",
            (case_id, case_id, kind, now, now, profile, version,
             "explicit" if profile else None),
        )
    old.execute(
        "INSERT INTO runner (id, name, host, status, registered_at)"
        " VALUES ('runner-1','old','old-host','registered',?)", (now,)
    )
    old.execute(
        "INSERT INTO artifact_ref (artifact_id, revision, case_id, kind, owner_runner_id,"
        " content_hash, byte_size, summary, availability, created_at)"
        " VALUES ('art-1',1,'case-v2','instruction','runner-1','h',10,'지시','available',?)",
        (now,),
    )
    old.execute(
        "INSERT INTO run (run_id, case_id, task_id, role, tool_id, mode, permission,"
        " instruction_artifact_id, instruction_artifact_rev, status, assignment_generation,"
        " created_at) VALUES ('run-1','case-v2','task-1','author','codex','exec','read_only',"
        " 'art-1',1,'finished',1,?)",
        (now,),
    )
    old.commit()
    old.close()

    conn = db.connect(path)
    db.migrate(conn)

    rows = {
        r["id"]: r for r in conn.execute('SELECT * FROM "case"').fetchall()
    }
    # **단계를 채워 넣지 않는다.** NULL 이 "UI-01 이전 Case" 다.
    assert all(rows[c]["stage"] is None for c in rows)
    assert rows["case-v1"]["profile_version"] == "1"
    assert rows["case-v2"]["profile_version"] == "2"
    assert rows["case-pre"]["profile"] is None
    assert rows["case-v1"]["kind"] == "bug"
    run = conn.execute("SELECT request_id FROM run WHERE run_id = 'run-1'").fetchone()
    assert run["request_id"] is None
    for table in (
        "conversation_message",
        "conversation_request",
        "conversation_message_ref",
        "case_work_start",
        "case_visibility_event",
    ):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    assert conn.execute("SELECT COUNT(*) FROM delegation_basis").fetchone()[0] == 0

    repo = Repository(conn)
    for case_id in rows:
        view = repo.conversation_view(case_id)
        # 옛 Case 는 업무 단계로 **도출**되며 그 출처가 드러난다.
        assert view["stage"] == "work"
        assert view["stage_source"] == "created_before_stage"
        assert view["messages"] == [] and view["requests"] == []
        assert view["send"]["general"]["allowed"] is True
        assert view["visibility"]["archived"] is False
    # **현재 판까지 이행됐는가**를 본다. v16 을 고정하던 것을 P4-04 에서 `>= 16` 으로
    # 바꿨다 — 이 시험의 뜻은 "v15 DB 가 지금 판으로 열린다"이고, v17 고정은 아래
    # v16→v17 시험이 맡는다(UI-01 이 v14 시험에 한 것과 같은 판단이다).
    assert (
        conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        == db.SCHEMA_VERSION
    )
    assert db.SCHEMA_VERSION >= 16

    # 새 값의 제약. 모르는 단계·상태를 넣을 수 없다.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE \"case\" SET stage = 'chatting' WHERE id = 'case-v1'")

    # 반복 이행이 멱등이다.
    db.migrate(conn)
    again = conn.execute('SELECT stage FROM "case" WHERE id = ?', ("case-v2",)).fetchone()
    assert again["stage"] is None
    assert conn.execute("SELECT COUNT(*) FROM conversation_request").fetchone()[0] == 0
    conn.close()


def _v16_schema() -> str:
    """P4-04 표식이 없고 v16 표식이 있는 마지막 커밋 스키마."""
    log = subprocess.run(
        ["git", "log", "--format=%H", "-30", "--", "controller/schema.sql"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if log.returncode != 0:
        pytest.skip("git 이력을 읽을 수 없다")
    for commit in log.stdout.decode("utf-8").split():
        schema = _committed_schema(commit)
        if "스키마 v16" in schema and "스키마 v17" not in schema:
            return schema
    pytest.skip("v16 스키마를 가진 커밋을 찾지 못했다")


def test_a_v16_database_gets_no_receipt_or_freshness_it_never_had(tmp_path):
    """v16 → v17 (P4-04 AC-17).

    **이 시험이 P4-04 의 소급 위험을 지킨다.** 옛 실행에 영수증을 채우면 "그 실행은 요청
    원문을 읽었다"가 근거 없이 생기고, 등급·인라인을 채우면 그때 없던 한도 판단이 있었던
    것처럼 보인다. 이행은 컬럼과 표만 더하고 값은 NULL 로 둬야 하며, 옛 실행은
    `not_reported`·"기록 전"으로 **도출**된다.
    """
    path = tmp_path / "controller.sqlite3"
    old = sqlite3.connect(path)
    old.row_factory = sqlite3.Row
    old.executescript(_v16_schema())
    # 실제 v16 DB 에는 db.py 이행이 붙인 컬럼이 있다(커밋된 `schema.sql` 에는 없다).
    for column in ("profile", "profile_version", "profile_source", "stage"):
        old.execute(f'ALTER TABLE "case" ADD COLUMN {column} TEXT')
    old.execute("ALTER TABLE run ADD COLUMN request_id TEXT")
    now = utc_now()
    old.execute("INSERT INTO schema_version (version, applied_at) VALUES (16, ?)", (now,))
    old.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    old.execute(
        "INSERT INTO project (id, owner_id, name, repo_path, default_tool_id, created_at)"
        " VALUES ('prj-1','own-1','old','C:/tmp/old','codex',?)", (now,)
    )
    old.execute(
        'INSERT INTO "case" (id, project_id, title, kind, status, created_at, updated_at,'
        " profile, profile_version, profile_source)"
        " VALUES ('case-1', 'prj-1', 'old', 'feature', 'received', ?, ?, 'feature', '2',"
        " 'explicit')",
        (now, now),
    )
    old.execute(
        "INSERT INTO runner (id, name, host, status, registered_at)"
        " VALUES ('runner-1','old','old-host','registered',?)", (now,)
    )
    for artifact_id, kind in (("art-inst", "instruction"), ("art-msg", "run_output")):
        old.execute(
            "INSERT INTO artifact_ref (artifact_id, revision, case_id, kind, owner_runner_id,"
            " content_hash, byte_size, summary, availability, created_at)"
            " VALUES (?,1,'case-1',?,'runner-1','h',10,'s','available',?)",
            (artifact_id, kind, now),
        )
    old.execute(
        "INSERT INTO run (run_id, case_id, task_id, role, tool_id, mode, permission,"
        " instruction_artifact_id, instruction_artifact_rev, status, assignment_generation,"
        " created_at, outcome) VALUES ('run-1','case-1','task-1','author','codex',"
        " 'exec','read_only','art-inst',1,'finished',1,?,'completed')",
        (now,),
    )
    old.execute(
        "INSERT INTO run_context_ref (run_id, seq, role, artifact_id, revision)"
        " VALUES ('run-1', 1, 'conversation_assistant_message', 'art-msg', 1)"
    )
    old.commit()
    old.close()

    conn = db.connect(path)
    db.migrate(conn)

    ref = conn.execute("SELECT * FROM run_context_ref WHERE run_id = 'run-1'").fetchone()
    # **채워 넣지 않는다.** NULL 이 "P4-04 이전 참조" 다.
    assert (ref["tier"], ref["inclusion"], ref["byte_size"]) == (None, None, None)
    run = conn.execute("SELECT * FROM run WHERE run_id = 'run-1'").fetchone()
    assert run["context_inline_limit"] is None
    assert run["not_started_reason"] is None
    assert run["context_freshness_json"] is None
    assert run["outcome"] == "completed"
    assert conn.execute("SELECT COUNT(*) FROM run_context_receipt").fetchone()[0] == 0

    repo = Repository(conn)
    view = repo.run_context_view("run-1")
    assert view["state"] == "not_reported"
    assert view["freshness"] is None and view["limit"] is None
    listed = repo.list_context_refs("run-1")
    # 등급은 역할에서 **도출**해 보이되 기록되지 않았다고 적는다. 그때는 전부 인라인이었다.
    assert [(r["tier"], r["tier_recorded"], r["inclusion"], r["inclusion_recorded"],
             r["receipt_status"]) for r in listed] == [
        ("supporting", False, "inline", False, None)
    ]
    assert (
        conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        == db.SCHEMA_VERSION
        == 17
    )

    # 새 값의 제약. 모르는 등급·상태·사유를 넣을 수 없다.
    for statement in (
        "UPDATE run_context_ref SET tier = 'vital' WHERE run_id = 'run-1'",
        "UPDATE run_context_ref SET inclusion = 'trimmed' WHERE run_id = 'run-1'",
        "UPDATE run SET not_started_reason = 'felt_like_it' WHERE run_id = 'run-1'",
        "INSERT INTO run_context_receipt (run_id, generation, seq, role, status, runner_id,"
        " reported_at) VALUES ('run-1', 1, 0, 'instruction', 'probably', 'runner-1', 't')",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(statement)

    # 반복 이행이 멱등이다.
    db.migrate(conn)
    again = conn.execute("SELECT tier FROM run_context_ref WHERE run_id = 'run-1'").fetchone()
    assert again["tier"] is None
    assert conn.execute("SELECT COUNT(*) FROM run_context_receipt").fetchone()[0] == 0
    conn.close()
