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
