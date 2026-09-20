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
SCHEMA_VERSION = 6


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


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, ddl: str
) -> bool:
    """기존 표에 컬럼을 더한다. 이미 있으면 아무 것도 하지 않는다.

    `CREATE TABLE IF NOT EXISTS` 로는 기존 표의 컬럼이 추가되지 않기 때문에 필요하다.
    기존 행의 새 컬럼은 NULL로 남는다. 그 값을 나중에 지어내지 않고
    "기록되지 않음"으로 표시한다.
    """
    existing = {r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')}
    if column in existing:
        return False
    conn.execute(f'ALTER TABLE "{table}" ADD COLUMN {column} {ddl}')
    return True


def migrate(conn: sqlite3.Connection) -> None:
    """스키마를 적용한다. 이미 적용돼 있으면 아무 것도 바꾸지 않는다."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    # v2: 동의가 어떤 원문에 붙은 것인지 기록한다(FR-23 "승인 후 대상이 바뀌면").
    _add_column_if_missing(conn, "decision", "subject_content_hash", "TEXT")

    # v3: 실행의 목적. 진입 조건이 목적마다 다르기 때문에 Run에 남긴다(FR-29).
    #     v2 이전에 만든 행은 NULL 로 남는다 — 그 시절엔 목적 개념이 없었으므로
    #     지금 값을 지어내지 않고 "기록되지 않음"으로 둔다.
    _add_column_if_missing(conn, "run", "purpose", "TEXT")

    # v3: 의도 버전을 **누가 썼는가.** P2-02까지는 사람만 쓸 수 있었으므로 옛 행은
    #     NULL 로 남는다. 그 행에 지금 와서 "사람이 썼다"고 적지 않는다 —
    #     기록되지 않은 것과 확인된 것을 구별한다(FR-04).
    _add_column_if_missing(conn, "intent_version", "authoring_mode", "TEXT")
    _add_column_if_missing(conn, "intent_version", "author_run_id", "TEXT")

    # v4: 결과·완료 기록은 **새 표만** 더한다. 기존 표의 컬럼을 바꾸지 않으므로
    #     위 executescript 의 `CREATE TABLE IF NOT EXISTS` 로 이행이 끝난다.
    #     기존 Case 에는 완료 정책 행이 없고, 그것은 "정책이 기록되지 않음"이 아니라
    #     기본값(사람 최종 확인)을 뜻한다 — D-31의 기본값이기 때문이다.
    #     행이 없는 상태를 자동 완료로 해석하지 않는 것이 중요하다.

    # v5: 수준·설계·계획도 **새 표만** 더한다. 기존 표의 컬럼을 바꾸지 않으므로
    #     위 executescript 의 `CREATE TABLE IF NOT EXISTS` 로 이행이 끝난다.
    #     기존 Case 에는 `stage_review_setting` 행이 없고, 그것은 "설정이 기록되지
    #     않음"이 아니라 기본값(설계·계획 모두 사람 검토)을 뜻한다 — D-14의
    #     기본값이기 때문이다. 행이 없는 상태를 자동 진행으로 해석하지 않는 것이
    #     중요하다. 마찬가지로 수준 판단 행이 없는 Case 는 `sizing_not_decided` 이며
    #     "간소"로 읽지 않는다.

    # v5: 미정 질문이 **어느 단계에서 제기됐는가.** 설계·계획 산출물도 질문을
    #     낳으므로 그 출처를 남긴다. 기존 행은 NULL 이며 그것은 의도 단계에서
    #     제기됐다는 사실과 일치한다 — P3-01 전에는 다른 단계가 없었다.
    _add_column_if_missing(conn, "intent_question", "raised_in_stage", "TEXT")
    _add_column_if_missing(conn, "intent_question", "preparation_id", "TEXT")

    # v6: 작업 그래프도 **새 표만** 더한다. 기존 표의 컬럼을 바꾸지 않으므로 위
    #     executescript 의 `CREATE TABLE IF NOT EXISTS` 로 이행이 끝난다.
    #     기존 Case 에는 `work_graph_revision` 행이 없고, 그것은 "Task 가 필요
    #     없다"가 아니라 **그래프가 아직 없다**는 뜻이다. 그래프가 없는 Case 는
    #     P3-01의 Case 수준 차단(이월 질문이 하나라도 열려 있으면 전부 막는다)을
    #     그대로 받는다 — 없음을 통과로 읽지 않는 것이 중요하다.
    #
    #     `run.task_id` 의 의미도 바뀌지 않는다. 그래프가 생기면 그 값이
    #     `task_key` 로 해석될 뿐이고, 옛 행의 "task-1" 은 그대로 남는다.

    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    current = row["v"] if row is not None else None
    if current is None or current < SCHEMA_VERSION:
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
