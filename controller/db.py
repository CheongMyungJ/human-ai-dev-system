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

from domain import ids

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
SCHEMA_VERSION = 8


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

    # v7: 작업공간·명령 기록도 **새 표만** 더한다. 기존 표의 컬럼을 바꾸지 않으므로
    #     위 executescript 의 `CREATE TABLE IF NOT EXISTS` 로 이행이 끝난다.
    #     기존 Case 에는 `case_workspace` 행이 없고, 그것은 "작업공간이 필요 없다"가
    #     아니라 **아직 준비되지 않았다**는 뜻이다 — 그 Case 의 쓰기 요청은
    #     `workspace_not_ready` 로 거부된다. 없음을 통과로 읽지 않는 것이 중요하다.
    #
    #     `run.workspace_effect_json` 은 v1부터 있던 컬럼이며 이번에 처음 채운다.
    #     옛 행은 NULL 로 남고 그것은 "변경이 없었다"가 아니라 **관측하지 않았다**는
    #     뜻이다. 지금 와서 값을 지어내지 않는다.

    # v8: 정책·Profile·저장소·예산. **새 표와 컬럼 세 개**다.
    #
    #     `case.profile`        여섯 Profile 중 무엇인가. 기존 행은 NULL 이며 그것은
    #                           "기능 개발"이 아니라 **기록되지 않음**이다. `kind` 에서
    #                           유도해 채우지 않는다 — 유도는 사람의 선택이 아니고,
    #                           지금 채우면 그 Case 의 의도 버전이 갑자기 Profile 필수
    #                           항목을 빠뜨린 문서가 된다.
    #     `case.profile_version` 어느 정의판으로 기록됐는가. 새 정의를 기존 Case 에
    #                           소급하지 않기 위해 필요하다(D-62).
    #     `project.journal_repository_id` 기록 이슈를 만들 저장소. **코드 대상이
    #                           아니다**(D-17·D-34·FR-30). 기본값은 NULL(미지정)이며
    #                           미지정을 "기록하지 않는다"로 읽지 않는다 — 게시 자체가
    #                           P5 범위다.
    _add_column_if_missing(conn, "case", "profile", "TEXT")
    _add_column_if_missing(conn, "case", "profile_version", "TEXT")
    _add_column_if_missing(conn, "case", "profile_source", "TEXT")
    _add_column_if_missing(conn, "project", "journal_repository_id", "TEXT")

    _migrate_v8_existing_rows(conn)

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


def _migrate_v8_existing_rows(conn: sqlite3.Connection) -> None:
    """R1 이전에 만들어진 Project·Case 를 v8 모델로 **이행한다.**

    두 가지를 한다. 둘 다 "없던 결정을 지어내지 않는다"는 같은 규칙을 따른다.

    1. **등록 저장소.** Project 의 `repo_path` 를 `project_repository` 한 건으로
       옮긴다. 같은 값이고 출처는 `migrated_from_project` 다. `repo_path` 컬럼은
       지우지 않는다 — 기존 배정·작업공간이 그 값을 쓴다.

    2. **정책 미기록 표시.** 기존 Case 에 `case_policy` 행을 **명시로** 넣되
       `autonomy` 는 NULL 이다. 여기서 `ask_on_decision` 을 적으면 v0.6에서 사람이
       검토·인수하기로 하고 진행한 업무가 조용히 자동 진행 대상이 된다. 가장 가까운
       값인 `controlled` 로 적는 것도 안 된다 — v0.6에는 controlled 의 시작·결과
       확인 체크포인트가 없었고, 있지도 않은 사람의 확인을 기록하는 일이 된다.
       `policy_version` 은 당시 규칙판인 `"0.6"` 으로 남는다.

    **Case 의 저장소 선택은 만들지 않는다.** 선택했다는 기록은 사람 또는 R2 의 자동
    추가가 만드는 것이고, 이행 시점에 "이 Case 는 그 저장소를 선택했다"고 적을 근거가
    없다. 조회는 그 상태를 `implicit_single_repository` 로 따로 표시한다.

    이 함수는 **여러 번 불려도 같은 결과**다(`migrate()` 는 매 연결마다 돈다).
    이미 있는 행은 건드리지 않는다.
    """
    now = utc_now()

    projects = conn.execute(
        "SELECT p.id, p.name, p.repo_path FROM project p"
        " WHERE NOT EXISTS (SELECT 1 FROM project_repository r WHERE r.project_id = p.id)"
    ).fetchall()
    for project in projects:
        conn.execute(
            "INSERT INTO project_repository"
            " (id, project_id, name, repo_path, source, registered_by, registered_at)"
            " VALUES (?, ?, ?, ?, 'migrated_from_project', 'migration', ?)",
            (
                ids.new_id("repo"),
                project["id"],
                "primary",
                project["repo_path"],
                now,
            ),
        )

    cases = conn.execute(
        'SELECT c.id FROM "case" c'
        " WHERE NOT EXISTS (SELECT 1 FROM case_policy p WHERE p.case_id = c.id)"
    ).fetchall()
    for case in cases:
        conn.execute(
            "INSERT INTO case_policy"
            " (id, case_id, revision, autonomy, autonomy_source, policy_version, set_by,"
            "  reason_summary, state, created_at)"
            " VALUES (?, ?, 1, NULL, 'migrated_unknown', '0.6', 'migration', ?, 'current', ?)",
            (
                ids.new_id("pol"),
                case["id"],
                "R1 이전 Case. Autonomy 가 기록되지 않았다",
                now,
            ),
        )
