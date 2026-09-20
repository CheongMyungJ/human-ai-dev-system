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

    # 새 표가 생겼다. v3 의 게이트·진입 표와 v4 의 결과·완료 표가 모두 있어야 한다.
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
