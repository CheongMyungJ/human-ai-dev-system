"""SQLite 연결과 스키마 적용.

NFR-01은 "저장 완료로 응답한 기록은 프로세스 재시작 후 복원되어야 한다"를 요구한다.
그래서 WAL + `synchronous=FULL` 을 쓴다. WAL 의 기본값인 NORMAL 은 전원/프로세스 강제
종료에서 마지막 트랜잭션을 잃을 수 있어 이 요구에 맞지 않는다.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
SCHEMA_VERSION = 1


def utc_now() -> str:
    """기록용 UTC 시각 문자열."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    # 저장 완료 응답의 내구성을 위해 NORMAL 이 아니라 FULL 로 둔다.
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """스키마를 적용한다. 이미 적용돼 있으면 아무 것도 바꾸지 않는다."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    if row is None or row["v"] is None:
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, utc_now()),
        )


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """하나의 쓰기 트랜잭션. 예외가 나면 되돌린다.

    상태 전이와 그에 딸린 기록(배정, 이벤트, 참조)을 한 트랜잭션에 묶기 위해 쓴다.
    다만 DB와 Runner 파일·GitHub를 하나의 원자적 트랜잭션으로 가정하지는 않는다
    (design-draft.md "데이터 모델과 인터페이스 초안").
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
