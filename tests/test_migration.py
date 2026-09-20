"""스키마 v1 DB를 v2로 올려도 기록을 잃지 않는지.

`CREATE TABLE IF NOT EXISTS` 만으로는 기존 표의 컬럼이 늘어나지 않는다. 그래서 v2는
`decision.subject_content_hash` 를 별도로 더하는데, 이 경로가 기존 행을 건드리면
사람의 과거 결정 기록이 사라진다. NFR-01은 저장 완료로 응답한 결정이 남아 있기를
요구하므로 여기서 실제 v1 DB를 만들어 확인한다.

**v1 스키마는 커밋된 것을 그대로 꺼내 쓴다.** 시험 안에 v1 스키마를 베껴 두면
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
