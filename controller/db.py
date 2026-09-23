"""SQLite 연결과 스키마 적용.

NFR-01은 "저장 완료로 응답한 기록은 프로세스 재시작 후 복원되어야 한다"를 요구한다.
그래서 WAL + `synchronous=FULL` 을 쓴다. WAL 의 기본값인 NORMAL 은 전원/프로세스 강제
종료에서 마지막 트랜잭션을 잃을 수 있어 이 요구에 맞지 않는다.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from domain import ids
from domain.models import NOT_STARTED_REASONS, REQUEST_OUTCOME_REASONS, REQUEST_STATES

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
SCHEMA_VERSION = 20


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

    # v9: Case × Repository 작업공간과 코드 조합.
    #
    #     `run.repository_id`  이 실행이 **어느 저장소**의 작업공간에서 도는가.
    #                          옛 행은 NULL 이며 그것은 "주 저장소"가 아니라
    #                          **기록되지 않음**이다. 준비된 작업공간이 하나뿐이면
    #                          모호하지 않아 그것으로 해석하고, 둘 이상이면
    #                          `workspace_target_not_recorded` 로 거부한다 —
    #                          어느 저장소를 고칠지 모르는 채로 쓰기를 열지 않는다.
    #     `*.composition_id`   그 근거·후보가 **어느 코드 조합 위에서** 나왔는가.
    #                          옛 행은 NULL 이고 그것은 "조합이 하나였다"가 아니라
    #                          조합 개념이 없던 시절의 기록이라는 뜻이다.
    _add_column_if_missing(conn, "run", "repository_id", "TEXT")
    _add_column_if_missing(conn, "criterion_result", "composition_id", "TEXT")
    _add_column_if_missing(conn, "completion_candidate", "composition_id", "TEXT")

    _migrate_v9_case_workspace(conn)

    # v10: 예산 예약. **새 표 하나뿐이고 기존 컬럼은 바뀌지 않는다.**
    #
    #      다만 표가 비어 있으면 안 된다. 집계의 출처가 이 표 하나이므로, R3 이전에
    #      실제로 돈 실행에 행이 없으면 스키마를 올리는 것만으로 그 Case 의 소비가
    #      0 이 된다 — "세션·Task 분할로 초기화하지 않는다"(D-61)가 이행에서 깨진다.
    _migrate_v10_budget_reservations(conn)

    # v11: 자동 실행·진입·완료. **새 표 둘과 새 컬럼 다섯**이며 기존 컬럼의 뜻은
    #      바뀌지 않는다.
    #
    #      `run.is_experiment`   이 실행이 허용된 로컬 실험인가(D-66). 옛 행은 0 이고
    #                            그것은 정확하다 — R4 이전에는 실험 목적이 없었다.
    #      `criterion_result.satisfaction`  **어떻게** 충족했는가. 옛 행은 NULL 이며
    #                            그것은 "바꾸고 확인했다"가 아니라 **그때는 묻지
    #                            않았다**는 뜻이다. `changed_and_verified` 로 채우지
    #                            않는다 — 없는 관측을 지어내는 일이다.
    #      `criterion_result.recheck_source` 어떤 피드백이 재검토를 만들었는가.
    #      `completion_policy.source`  그 행이 사람의 명시 설정인가. R4 이전 행은
    #                            **전부 명시 설정이었다**(도출 경로가 없었다). 그래서
    #                            이행이 `migrated_explicit` 로 적고, 도출값이 그 행을
    #                            덮지 않는다.
    _add_column_if_missing(conn, "run", "is_experiment", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "criterion_result", "satisfaction", "TEXT")
    _add_column_if_missing(conn, "criterion_result", "recheck_source", "TEXT")
    _add_column_if_missing(conn, "completion_policy", "source", "TEXT")

    _migrate_v11_progression(conn)

    # v12: Task 가 **어느 저장소를 바꾸는가**(P3-04). 설계가 처음부터 요구한 것이고
    #      (execution-workspace-review 19행 "Task·Run이 사용하는 Repo와 작업공간을
    #      명시한다") R2 가 실행 쪽만 채운 채 남겨 둔 자리다.
    #
    #      `task.repository_id`   해석된 저장소. 옛 행은 NULL 이며 그것은 "주
    #                             저장소"가 아니라 **미기록**이다. 작업공간에서
    #                             유도해 채우지 않는다 — 저장소가 하나뿐이라는
    #                             이유로 그 값을 적으면 나중에 저장소가 늘었을 때
    #                             "계획이 그렇게 정했다"는 기록이 된다(D-62).
    #      `task.repository_ref`  계획이 **적은 그대로**의 문자열. 해석되지 않은
    #                             참조를 조용히 버리지 않기 위해 남긴다 —
    #                             `task_block_unresolved` 와 같은 이유다. 버리면
    #                             "저장소를 말하지 않은 계획"과 "선택 밖 저장소를
    #                             가리킨 계획"이 화면에서 같아진다.
    #
    #      **데이터 이행 함수가 없다.** 옛 행의 올바른 값이 NULL·'' 이기 때문이며,
    #      채울 것이 있는데 비워 둔 것이 아니다. 진입 검사 쪽에서 그 미기록이
    #      **저장소가 둘 이상인 Case 의 새 그래프에서만** 막도록 좁힌다 — 넓히면
    #      단일 저장소 Case 와 R2 이전 Case 의 진행 중 업무가 멈춘다.
    _add_column_if_missing(conn, "task", "repository_id", "TEXT")
    _add_column_if_missing(conn, "task", "repository_ref", "TEXT NOT NULL DEFAULT ''")

    # v13: QG-02~07과 repair. 새 표만 추가하며 기존 QG-01 판정이나 실패를
    # 일반 게이트/repair로 추정해 복제하지 않는다. schema.sql의 CREATE IF NOT
    # EXISTS가 빈 모델을 만들고, 실제 정책은 현재 사실에서 도출한다(P4-01).

    # v14: 설정 변경의 **예약**과 변경 영향(P4-02). 새 표 둘은 schema.sql 이 만들고
    #      여기서는 기존 두 표에 시간축을 더한다.
    #
    #      `quality_gate_policy.requested_at`  요청한 시각.
    #      `quality_gate_policy.applied_at`    실제 반영된 시각. **둘을 나누는 것이
    #                            이 작업의 핵심이다** — 예약 행은 요청 시각만 갖는다.
    #      `quality_gate_policy.apply_after_run_id` 어느 검증 1회가 끝나면 반영되는가.
    #      `quality_gate_policy.apply_boundary` immediate | verification_end.
    #      `quality_gate_policy.cancelled_*`   예약 취소의 주체·이유·시각.
    #      `quality_gate_run.started_policy_revision` 시작 시점에 **고정한** 정책
    #                            리비전. v13 이전 행은 NULL 이며 그것은 0 이 아니라
    #                            **미기록**이다 — 그때는 시작 경계가 없었다.
    #      `quality_gate_run.late_result`  늦게 도착해 원래 실행에만 귀속된 결과인가.
    #                            옛 행은 0 이고 그것은 정확하다.
    #      `quality_gate_run.stop_requested_*` 취소 **요청**의 시각·이유. 실제 종료
    #                            확인과 다른 값이다.
    #
    #      기존 `current` 정책에는 `applied_at = created_at`, `apply_boundary =
    #      'immediate'` 를 채운다. v13 까지는 예약 경로가 없어 **모든 적용이 즉시**
    #      였기 때문이며, 없는 관측을 지어내는 것이 아니다. 예약·취소·재검증 행은
    #      만들지 않는다.
    _add_column_if_missing(conn, "quality_gate_policy", "requested_at", "TEXT")
    _add_column_if_missing(conn, "quality_gate_policy", "applied_at", "TEXT")
    _add_column_if_missing(conn, "quality_gate_policy", "apply_after_run_id", "TEXT")
    _add_column_if_missing(conn, "quality_gate_policy", "apply_boundary", "TEXT")
    _add_column_if_missing(conn, "quality_gate_policy", "cancelled_at", "TEXT")
    _add_column_if_missing(conn, "quality_gate_policy", "cancelled_by", "TEXT")
    _add_column_if_missing(conn, "quality_gate_policy", "cancel_reason", "TEXT")
    _add_column_if_missing(conn, "quality_gate_run", "started_policy_revision", "INTEGER")
    _add_column_if_missing(
        conn, "quality_gate_run", "late_result", "INTEGER NOT NULL DEFAULT 0"
    )
    # 취소 **요청**이다. 실제 종료 확인이 아니며 그래서 별도 컬럼이다 —
    # 요청 뒤 도착한 결과도 원래 실행에 저장한다(gate-operations 5절).
    _add_column_if_missing(conn, "quality_gate_run", "stop_requested_at", "TEXT")
    _add_column_if_missing(conn, "quality_gate_run", "stop_reason", "TEXT")
    _add_column_if_missing(conn, "quality_gate_run", "stop_requested_by", "TEXT")
    _migrate_v14_policy_application(conn)

    # v15: 여섯 Profile 의 **완료 의미**(P4-03). 새 컬럼 여섯이며 새 표는 없다.
    #
    #      `success_criterion.obligation`   그 기준이 **무엇을 입증하는가**(목적 의무).
    #      `success_criterion.obligation_source` 원문이 적었는가, 연결 항목에서 정의로
    #                            도출했는가.
    #      `success_criterion.conclusion_rule`  원인·조사 기준이 판단 불가를 정상 결과로
    #                            허용하는가. NULL 은 **확정 필수로 취급**한다.
    #      `criterion_result.conclusion`    결론이 확정인가 판단 불가인가.
    #      `intent_version.objectives_json` 요청이 명시한 목적 의무 목록.
    #      `completion_candidate.meaning_json` 후보가 본 목적별 충족 현황.
    #
    #      **데이터 이행 함수가 없다.** 옛 행은 전부 NULL 이 맞다 — 그 기준은 Profile
    #      정의 v1 으로 만들어졌고 v1 에는 완료 계약이 없다. 연결 항목에서 의무를
    #      도출해 채우면 기존 Case 에 새 완료 규칙이 소급된다(D-62). `case.profile_version`
    #      도 올리지 않는다 — 새 정의판은 **새 Case** 에만 붙는다.
    _add_column_if_missing(
        conn,
        "success_criterion",
        "obligation",
        "TEXT CHECK (obligation IS NULL OR obligation IN ('behavior', 'restoration',"
        " 'cause', 'answer', 'improvement', 'preservation', 'target_state'))",
    )
    _add_column_if_missing(
        conn,
        "success_criterion",
        "obligation_source",
        "TEXT CHECK (obligation_source IS NULL OR obligation_source IN"
        " ('reported', 'derived_from_field'))",
    )
    _add_column_if_missing(
        conn,
        "success_criterion",
        "conclusion_rule",
        "TEXT CHECK (conclusion_rule IS NULL OR conclusion_rule IN"
        " ('definitive_required', 'bounded_report_allowed'))",
    )
    _add_column_if_missing(
        conn,
        "criterion_result",
        "conclusion",
        "TEXT CHECK (conclusion IS NULL OR conclusion IN ('determined', 'inconclusive'))",
    )
    # 목적 의무 이름 일곱 개의 JSON 목록이 넉넉히 들어가는 크기다. 본문 자리가 아니다.
    _add_column_if_missing(
        conn,
        "intent_version",
        "objectives_json",
        "TEXT CHECK (objectives_json IS NULL OR length(objectives_json) <= 200)",
    )
    # 의무별 기준 키·수·상태와 잔여 실험 id 뿐이다. 기준 키 64자 × 수백 건을 넘지 않는다.
    _add_column_if_missing(
        conn,
        "completion_candidate",
        "meaning_json",
        "TEXT CHECK (meaning_json IS NULL OR length(meaning_json) <= 20000)",
    )

    # v16: 대화·요청 기반(UI-01). 새 표 다섯은 schema.sql 이 만들고 여기서는 기존 두
    #      표에 컬럼을 더한다.
    #
    #      `case.stage`     준비(`discussion`) 인가 업무(`work`) 인가. **옛 행은 NULL 이며
    #                       그것은 "UI-01 이전에 만든 Case" 다.** 그때는 목적 없이 Case 를
    #                       만들 경로가 없었으므로 업무 단계로 도출하되(`domain.
    #                       conversation.derive_stage`) 값을 채워 넣지 않는다 — 출처가
    #                       `created_before_stage` 로 드러난다.
    #      `run.request_id` 이 실행이 **어느 사용자 요청을 처리했는가.** 옛 행은 NULL 이며
    #                       그것은 요청 개념이 없던 시절의 실행이라는 뜻이다.
    #
    #      **데이터 이행 함수가 없다.** 옛 Case 에 메시지·요청·보관 이력을 만들지 않는다.
    #      없던 대화를 지어내면 그 Case 가 "대화에서 업무화됐다"로 읽힌다.
    _add_column_if_missing(
        conn,
        "case",
        "stage",
        "TEXT CHECK (stage IS NULL OR stage IN ('discussion', 'work'))",
    )
    _add_column_if_missing(
        conn, "run", "request_id", "TEXT REFERENCES conversation_request(id)"
    )

    # v17: 문맥·재개(P4-04). 영수증 표는 schema.sql 이 만들고 여기서는 기존 두 표에
    #      컬럼을 더한다.
    #
    #      `run_context_ref.tier`       핵심/보조. **옛 행은 NULL 이며 기록되지 않았다.**
    #                                   조회는 역할에서 도출해 보이되 기록 전이라고 적는다.
    #      `run_context_ref.inclusion`  지시문에 넣었는가. 옛 행은 NULL 이며 그때는 생략
    #                                   경로가 없었으므로 **전부 인라인이었다.**
    #      `run_context_ref.byte_size`  고정 시점의 크기. 옛 행은 NULL.
    #      `run.context_inline_limit`   생성 때 적용한 한도. 옛 행은 NULL = 한도 없음.
    #      `run.not_started_reason`     Runner 가 CLI 를 부르기 전에 멈춘 이유.
    #      `run.context_freshness_json` 결과 보고 시점의 최신성(고정 뒤 새로 생긴 입력).
    #
    #      **데이터 이행 함수가 없다.** 옛 실행에 영수증·최신성·등급을 만들지 않는다.
    #      없던 확인을 지어내면 "그 실행은 요청 원문을 읽었다"가 근거 없이 생긴다.
    _add_column_if_missing(
        conn,
        "run_context_ref",
        "tier",
        "TEXT CHECK (tier IS NULL OR tier IN ('core', 'supporting'))",
    )
    _add_column_if_missing(
        conn,
        "run_context_ref",
        "inclusion",
        "TEXT CHECK (inclusion IS NULL OR inclusion IN ('inline', 'omitted_size_limit'))",
    )
    _add_column_if_missing(conn, "run_context_ref", "byte_size", "INTEGER")
    _add_column_if_missing(conn, "run", "context_inline_limit", "INTEGER")
    # UI-02(v18) 가 허용값을 늘렸다. 새 DB 는 여기서 새 목록을 받고, 이미 이 컬럼이 있는
    # DB 는 아래 v18 이행이 표를 다시 만들어 목록을 바꾼다.
    _add_column_if_missing(
        conn,
        "run",
        "not_started_reason",
        "TEXT CHECK (not_started_reason IS NULL OR not_started_reason IN"
        f" ({_sql_list(NOT_STARTED_REASONS)}))",
    )
    # 역할·참조 id·버전의 목록이다. 본문 자리가 아니다.
    _add_column_if_missing(
        conn,
        "run",
        "context_freshness_json",
        "TEXT CHECK (context_freshness_json IS NULL OR length(context_freshness_json) <= 20000)",
    )

    # v18: 입력·실행 제어(UI-02). 잔류 관측 표는 schema.sql 이 만들고 여기서는 컬럼을
    #      더하고 **두 표의 허용값 목록을 넓힌다.**
    #
    #      `run.stop_requested_at`·`_by` 이 실행에 중단이 요청된 시각·주체. 옛 행은 NULL —
    #                                 중단 경로가 없었다.
    #      `run.stop_delivered_at`    Runner 가 중단을 받았다고 확인한 시각. 받았다는 뜻이지
    #                                 끝났다는 뜻이 아니다.
    #      `run.liveness_at`          Runner 가 "지금 실행 중"이라고 마지막으로 알린 시각.
    #      `run.residual_check_requested_at` 끝난 실행의 잔류 재확인을 요청한 시각.
    #      `conversation_request.stop_requested_*` 요청 중단의 시각·주체·짧은 이유.
    #
    #      `run.not_started_reason` 과 요청 상태·이유의 CHECK 는 **표를 다시 만들어** 바꾼다
    #      (`_widen_check`). 행·색인은 그대로 옮기고 값을 지어내지 않는다. 옛 `unknown`
    #      요청은 그대로 잠겨 있다 — 그 실행의 잔류는 확인 근거가 생길 때만 풀린다.
    for column in (
        "stop_requested_at",
        "stop_requested_by",
        "stop_delivered_at",
        "liveness_at",
        "residual_check_requested_at",
    ):
        _add_column_if_missing(conn, "run", column, "TEXT")
    _add_column_if_missing(conn, "conversation_request", "stop_requested_at", "TEXT")
    _add_column_if_missing(conn, "conversation_request", "stop_requested_by", "TEXT")
    _add_column_if_missing(
        conn,
        "conversation_request",
        "stop_reason_summary",
        "TEXT CHECK (stop_reason_summary IS NULL OR length(stop_reason_summary) <= 200)",
    )
    _widen_check(conn, "run", "not_started_reason", NOT_STARTED_REASONS)
    _widen_check(conn, "conversation_request", "state", REQUEST_STATES)
    _widen_check(conn, "conversation_request", "outcome_reason", REQUEST_OUTCOME_REASONS)

    # v19: 기본 대화 화면(UI-03). 해석 표(`conversation_interpretation`)는 schema.sql 이 만든다.
    #      **기존 표를 바꾸지 않는다.** 요청 처리기가 끝낸 요청은 `settled_by` 의 주체 값으로
    #      구별하고, 옛 요청·실행에는 해석 행을 만들지 않는다.

    # v20: 업무 단계 자동 진행·완료·예외·후속(P4-05). 진행 표 둘(`case_progress`·
    #      `case_progress_event`)은 schema.sql 이 만들고 여기서는 기존 세 표를 바꾼다.
    #
    #      `conversation_request.origin`·`origin_ref`  누가 열었는가. 옛 행은 전부 `user_message`.
    #      `conversation_request.opened_by_message_id`  **NULL 허용으로 바꾼다** — 사람의 결정 뒤
    #                                 시스템이 여는 진행 요청은 여는 메시지가 없다. SQLite 는
    #                                 NOT NULL 을 푸는 ALTER 가 없어 표를 다시 만든다
    #                                 (`_drop_not_null`, v18 의 재구성과 같은 절차). 행·색인은
    #                                 그대로 옮기고 값을 지어내지 않는다.
    #      `run.criteria_report_json`  검증·분석 실행이 보고한 기준별 판정(키·판정·결론·짧은
    #                                 요약). 옛 실행은 NULL — 보고하지 않았다.
    #      `closure_record.snapshot_json` 종료 시점의 소비·한도. 옛 종료는 NULL — 그때의
    #                                 값을 지금 지어내지 않는다(D-87 의 "종료 시점 소비"는
    #                                 v20 부터의 종료에만 있다).
    #
    #      **데이터 이행 함수가 없다.** 옛 Case 에 진행 행을 만들지 않는다 — 진행기는 업무화
    #      때 행을 만든 Case 만 잇고, 관리 화면·API 로 만든 Case 는 사람·하네스가 진행한다.
    _add_column_if_missing(
        conn,
        "conversation_request",
        "origin",
        "TEXT NOT NULL DEFAULT 'user_message'"
        " CHECK (origin IN ('user_message', 'human_decision', 'system_resume'))",
    )
    _add_column_if_missing(
        conn,
        "conversation_request",
        "origin_ref",
        "TEXT CHECK (origin_ref IS NULL OR length(origin_ref) <= 120)",
    )
    _drop_not_null(conn, "conversation_request", "opened_by_message_id")
    _add_column_if_missing(
        conn,
        "run",
        "criteria_report_json",
        "TEXT CHECK (criteria_report_json IS NULL OR length(criteria_report_json) <= 8000)",
    )
    _add_column_if_missing(
        conn,
        "closure_record",
        "snapshot_json",
        "TEXT CHECK (snapshot_json IS NULL OR length(snapshot_json) <= 4000)",
    )

    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    current = row["v"] if row is not None else None
    if current is None or current < SCHEMA_VERSION:
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, utc_now()),
        )


def _sql_list(values: Iterable[str]) -> str:
    """CHECK 의 허용값 목록. 값은 열거형에서 오며 따옴표를 담지 않는다."""
    return ", ".join(f"'{v}'" for v in values)


def _widen_check(
    conn: sqlite3.Connection, table: str, column: str, values: Iterable[str]
) -> bool:
    """표의 `{column} IN (...)` CHECK 허용값 목록을 `values` 로 바꾼다(UI-02, v18).

    **이미 같은 값 목록이면 아무 것도 하지 않는다**(값으로 비교한다 — 줄바꿈이 다른 같은
    목록 때문에 새 DB 를 다시 만들지 않는다).

    SQLite 에는 CHECK 를 바꾸는 ALTER 가 없어 표를 다시 만든다. 새 DDL 은 **저장된 DDL 에서
    그 목록만 바꾼 것**이다 — 손으로 다시 적으면 여러 판에 걸쳐 붙은 컬럼·기본값·제약 하나를
    빠뜨리기 쉽다. 순서는 SQLite 의 일반 절차를 따른다: 외래 키 검사를 끄고, 새 표를 만들어
    행을 그대로 옮기고, 옛 표를 지운 뒤 새 표의 이름을 바꾸고, 색인을 다시 만들고,
    `foreign_key_check` 가 비어 있음을 확인한다. 다른 표의 외래 키는 이름으로 이 표를
    가리키므로 이름을 바꾼 뒤 그대로 새 표를 가리킨다.
    """
    wanted = list(values)
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if row is None:
        return False
    ddl = row["sql"]
    match = re.search(r"\b" + re.escape(column) + r"\s+IN\s*\(([^)]*)\)", ddl)
    if match is None:
        return False
    if re.findall(r"'([^']*)'", match.group(1)) == wanted:
        return False
    new_ddl = ddl[: match.start()] + f"{column} IN ({_sql_list(wanted)})" + ddl[match.end():]
    _rebuild_table(conn, table, new_ddl, "v18 이행")
    return True


def _drop_not_null(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """표의 한 컬럼에서 `NOT NULL` 을 푼다(P4-05, v20). 이미 풀려 있으면 아무 것도 하지 않는다.

    `_widen_check` 와 같은 재구성이다 — 저장된 DDL 에서 그 컬럼 선언의 `NOT NULL` 만 지운 DDL 로
    표를 다시 만들고 행·색인을 그대로 옮긴다.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if row is None:
        return False
    ddl = row["sql"]
    match = re.search(r"\b" + re.escape(column) + r"\s+(\w+)\s+NOT\s+NULL\b", ddl)
    if match is None:
        return False
    new_ddl = ddl[: match.start()] + f"{column} {match.group(1)}" + ddl[match.end():]
    _rebuild_table(conn, table, new_ddl, "v20 이행")
    return True


def _rebuild_table(
    conn: sqlite3.Connection, table: str, new_ddl: str, label: str
) -> None:
    """표를 `new_ddl` 로 다시 만들고 행·색인을 옮긴다(SQLite 의 일반 절차).

    외래 키 검사를 끄고, 새 표를 만들어 행을 그대로 옮기고, 옛 표를 지운 뒤 새 표의 이름을
    바꾸고, 색인을 다시 만들고, `foreign_key_check` 가 비어 있음을 확인한다. 다른 표의 외래
    키는 이름으로 이 표를 가리키므로 이름을 바꾼 뒤 그대로 새 표를 가리킨다.
    """
    temp = f"{table}__rebuild"
    header = re.compile(r'^CREATE TABLE\s+(IF NOT EXISTS\s+)?"?' + re.escape(table) + r'"?', re.I)
    if not header.search(new_ddl):
        raise RuntimeError(f"{label}: {table} 의 DDL 머리를 해석하지 못했다")
    create_temp = header.sub(f'CREATE TABLE "{temp}"', new_ddl, count=1)
    indexes = [
        r["sql"]
        for r in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ?"
            " AND sql IS NOT NULL",
            (table,),
        ).fetchall()
    ]
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        with transaction(conn):
            conn.execute(f'DROP TABLE IF EXISTS "{temp}"')
            conn.execute(create_temp)
            conn.execute(f'INSERT INTO "{temp}" SELECT * FROM "{table}"')
            conn.execute(f'DROP TABLE "{table}"')
            conn.execute(f'ALTER TABLE "{temp}" RENAME TO "{table}"')
            for index_sql in indexes:
                conn.execute(index_sql)
            broken = conn.execute("PRAGMA foreign_key_check").fetchall()
            if broken:
                raise RuntimeError(
                    f"{label}: {table} 을 다시 만든 뒤 외래 키가 맞지 않는다: "
                    + ", ".join(str(tuple(b)) for b in broken[:5])
                )
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


#: 쓰기 트랜잭션을 **연결 단위로 직렬화한다**(P3-04).
#:
#: 제어부는 연결 하나를 `check_same_thread=False` 로 만들어 모든 요청이 공유한다.
#: 그런데 FastAPI 는 동기 엔드포인트를 **스레드풀**에서 돌리므로 요청 둘이 같은
#: 연결에 동시에 `BEGIN IMMEDIATE` 를 보낼 수 있고, 그때 SQLite 가
#: `cannot start a transaction within a transaction` 으로 죽는다.
#:
#: **P3-R3 이 `BEGIN IMMEDIATE` 를 도입하면서 생긴 자리다.** 그 전에는 자동 커밋
#: 모드라 이 충돌이 없었다. 라이브에서 실제로 났다 — Runner 가 실행 결과를 보고하는
#: 동안 다음 실행을 만들자 500 이 떴다. 한 요청이 다른 요청 때문에 죽는 것은
#: 어느 진입 검사로도 설명되지 않는 실패다.
#:
#: 재진입(`RLock`)인 이유는 같은 스레드가 트랜잭션 안에서 다른 트랜잭션 함수를
#: 부르는 경로가 있을 수 있기 때문이다 — 그 경우는 SQLite 가 여전히 막지만, 그
#: 실패는 **설계 문제**로 드러나야지 스레드 경합으로 가려지면 안 된다.
_WRITE_LOCK = threading.RLock()


class _Rows:
    """문장 하나의 결과를 **잠금 안에서 다 읽어 둔** 것. 커서처럼 쓴다."""

    def __init__(self, rows: list[Any], rowcount: int, lastrowid: int | None, description: Any):
        self._rows = rows
        self._index = 0
        self.rowcount = rowcount
        self.lastrowid = lastrowid
        self.description = description

    def fetchone(self) -> Any:
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    def fetchall(self) -> list[Any]:
        rest = self._rows[self._index :]
        self._index = len(self._rows)
        return rest

    def __iter__(self) -> Iterator[Any]:
        return iter(self.fetchall())


class SerializedConnection:
    """요청 스레드들이 **공유하는** 연결(UI-03).

    제어부는 연결 하나를 스레드 풀의 요청들이 함께 쓴다(`check_same_thread=False`). 쓰기
    트랜잭션은 `transaction()` 이 이미 직렬화했지만 **잠금 밖의 문장**(조회·자동 커밋 쓰기)은
    그렇지 않았다. 같은 SQL 을 두 스레드가 동시에 실행하면 파이썬 sqlite3 의 **준비된 문장
    캐시를 함께 써서** 한쪽의 매개변수가 다른 쪽 실행을 덮는다 — 방금 커밋한 행이 "없다"로
    읽히거나 `InterfaceError: bad parameter or other API misuse` 가 난다. 또 남의 열린 쓰기
    트랜잭션 안에서 실행된 조회는 커밋 전 행을 본다.

    UI-03 의 기본 화면이 조회를 여러 개 겹쳐 보내자 실제로 드러났다(`web_shell` 브라우저 시험·
    부하 재현). 그래서 **문장 하나(실행과 결과 읽기)를 쓰기 트랜잭션과 같은 잠금 안에서
    끝낸다.** 트랜잭션이 열려 있으면 다른 스레드의 문장은 그 트랜잭션이 끝날 때까지 기다린다.
    잠금은 이 프로세스 안에서만이다(여러 제어부는 P6-03).
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def raw(self) -> sqlite3.Connection:
        return self._conn

    def execute(self, sql: str, parameters: Any = ()) -> _Rows:
        with _WRITE_LOCK:
            cursor = self._conn.execute(sql, parameters)
            rows = cursor.fetchall() if cursor.description is not None else []
            return _Rows(rows, cursor.rowcount, cursor.lastrowid, cursor.description)

    def executemany(self, sql: str, seq: Iterable[Any]) -> _Rows:
        with _WRITE_LOCK:
            cursor = self._conn.executemany(sql, seq)
            return _Rows([], cursor.rowcount, cursor.lastrowid, None)

    def executescript(self, script: str) -> None:
        with _WRITE_LOCK:
            self._conn.executescript(script)

    def close(self) -> None:
        with _WRITE_LOCK:
            self._conn.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """하나의 쓰기 트랜잭션. 예외가 나면 되돌린다.

    상태 전이와 그에 딸린 기록(배정, 이벤트, 참조)을 한 트랜잭션에 묶기 위해 쓴다.
    다만 DB와 Runner 파일·GitHub를 하나의 원자적 트랜잭션으로 가정하지는 않는다
    (design-draft.md "데이터 모델과 인터페이스 초안").

    **연결을 공유하는 요청들 사이에서 직렬화된다**(P3-04). 공유 연결에 동시에
    `BEGIN IMMEDIATE` 가 들어가면 SQLite 가 거부하며, 그것은 이 요청의 조건과
    아무 상관 없는 실패다. 잠금은 **이 프로세스 안에서만** 보장하며, 여러 제어부
    프로세스의 조정은 P6-03 이다.
    """
    with _WRITE_LOCK:
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


def _migrate_v9_case_workspace(conn: sqlite3.Connection) -> None:
    """`case_workspace` 를 `(case_id, repository_id)` 키로 **다시 만든다**(P3-R2).

    SQLite 에서는 기본 키를 바꿀 수 없어 표를 새로 만들고 옮겨야 한다. 이 이행이
    지키는 것 둘.

    1. **기존 행을 잃지 않는다.** 브랜치·기준 커밋·worktree 경로·사용자 트리 관측은
       그대로 옮긴다. 경로를 새 규칙(`{case}/{repo}`)으로 바꾸지 않는다 — 옮기면
       이미 그 worktree 에서 한 작업이 떨어져 나가고, 그 자리의 브랜치는 다음 준비
       때 `FOREIGN` 으로 보여 거부된다.

    2. **어느 저장소인지 지어내지 않는다.** 옛 행은 Project 의 등록 저장소가 정확히
       하나일 때만 그 저장소에 연결한다. 둘 이상이면 그 Case 가 어느 것을 썼는지
       기록이 없으므로 `repo_path` 가 같은 저장소를 찾고, 그것도 없으면 이행을
       멈춘다 — 틀린 연결은 "어떤 코드 위에서 시작했는가"의 답을 거짓으로 만든다.

    허용 출처는 `implicit_single_repository` 다. 이 Case 들은 선택 기록 없이 실제로
    그 저장소에서 작업했고, 이행이 "선택했다"는 결정을 새로 만들지 않는다.

    `migrate()` 는 매 연결마다 도므로 **옛 모양일 때만** 수행하고 여러 번 불려도
    같은 결과여야 한다.
    """
    columns = {r["name"] for r in conn.execute('PRAGMA table_info("case_workspace")')}
    if not columns or "repository_id" in columns:
        return

    rows = conn.execute("SELECT * FROM case_workspace").fetchall()
    resolved: list[tuple[Any, ...]] = []
    for row in rows:
        repos = conn.execute(
            "SELECT id, repo_path FROM project_repository WHERE project_id = ?"
            " ORDER BY registered_at",
            (row["project_id"],),
        ).fetchall()
        repository_id: str | None = None
        if len(repos) == 1:
            repository_id = repos[0]["id"]
        else:
            # 여러 개면 **경로가 일치하는 것만** 쓴다. Runner 가 보고한 저장소 경로는
            # 그 작업공간이 실제로 어디에 있었는지에 대한 유일한 증거다.
            for repo in repos:
                if row["repo_path"] and repo["repo_path"] == row["repo_path"]:
                    repository_id = repo["id"]
                    break
        if repository_id is None:
            raise RuntimeError(
                "v9 이행: 작업공간이 어느 저장소의 것인지 확인할 수 없다"
                f" (case={row['case_id']}). 반쯤 옮긴 상태로 두지 않는다"
            )
        resolved.append(
            (
                row["case_id"],
                repository_id,
                row["project_id"],
                row["state"],
                row["branch"],
                "implicit_single_repository",
                row["runner_id"],
                row["repo_path"],
                row["worktree_path"],
                row["base_commit"],
                row["base_ref"],
                row["user_tree_dirty"],
                row["user_tree_entries"],
                row["failure_reason"],
                row["requested_at"],
                row["ready_at"],
            )
        )

    conn.execute("DROP INDEX IF EXISTS idx_case_workspace_project")
    conn.execute('ALTER TABLE case_workspace RENAME TO case_workspace_v8')
    conn.executescript(
        """
        CREATE TABLE case_workspace (
            case_id           TEXT NOT NULL REFERENCES "case"(id),
            repository_id     TEXT NOT NULL REFERENCES project_repository(id),
            project_id        TEXT NOT NULL REFERENCES project(id),
            state             TEXT NOT NULL,
            branch            TEXT NOT NULL,
            allowance_source  TEXT NOT NULL DEFAULT '',
            runner_id         TEXT REFERENCES runner(id),
            repo_path         TEXT NOT NULL DEFAULT '',
            worktree_path     TEXT NOT NULL DEFAULT '',
            base_commit       TEXT NOT NULL DEFAULT '',
            base_ref          TEXT NOT NULL DEFAULT '',
            user_tree_dirty   INTEGER NOT NULL DEFAULT 0,
            user_tree_entries INTEGER NOT NULL DEFAULT 0,
            failure_reason    TEXT NOT NULL DEFAULT '',
            requested_at      TEXT NOT NULL,
            ready_at          TEXT,
            PRIMARY KEY (case_id, repository_id),
            CHECK (length(failure_reason) <= 200)
        );
        """
    )
    conn.executemany(
        "INSERT INTO case_workspace (case_id, repository_id, project_id, state, branch,"
        " allowance_source, runner_id, repo_path, worktree_path, base_commit, base_ref,"
        " user_tree_dirty, user_tree_entries, failure_reason, requested_at, ready_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        resolved,
    )
    conn.execute("DROP TABLE case_workspace_v8")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_case_workspace_project"
        " ON case_workspace(project_id, state)"
    )


def parse_ts(value: str | None) -> datetime | None:
    """기록된 시각 문자열 → `datetime`. 읽을 수 없으면 `None`(=모름)이다.

    **깨진 값을 현재 시각으로 대신하지 않는다.** 대신하면 읽을 수 없는 기록이 0초
    실행으로 보이고, 그 0이 예산 잔여량을 늘린다.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def elapsed_seconds(start: str | None, end: str | None) -> float | None:
    """두 기록 시각의 차이. 어느 한쪽이 없으면 `None`(=모름)이다."""
    a, b = parse_ts(start), parse_ts(end)
    if a is None or b is None:
        return None
    return max(0.0, (b - a).total_seconds())


def context_package_bytes(
    conn: sqlite3.Connection,
    instruction_artifact_id: str,
    instruction_artifact_rev: int,
    context_refs: Iterable[tuple[str, int]] = (),
) -> int:
    """제어부가 **만들어 전달하는** 입력 패키지의 크기(P3-R3).

    지시 원문과 고정 컨텍스트 참조가 가리키는 원문들의 `byte_size` 합이다.

    **CLI 가 내부에서 더 읽은 자료는 여기 없다.** 그것을 측정했다고 주장하지 않는
    것이 측정 계약이며(autonomy-budget-policy 7절), 그래서 이 값의 이름은
    `context_bytes` 이지 "실행이 본 전체 입력"이 아니다.

    크기를 알 수 없는 참조는 **건너뛰지 않고 0 으로도 세지 않는다** — 참조는 언제나
    `artifact_ref` 에 있고 그 표의 `byte_size` 는 NOT NULL 이므로 알 수 없는 경우가
    없다. 없는 참조는 애초에 외래 키로 막힌다.
    """
    total = 0
    refs = [(instruction_artifact_id, instruction_artifact_rev), *context_refs]
    for artifact_id, revision in refs:
        row = conn.execute(
            "SELECT byte_size FROM artifact_ref WHERE artifact_id = ? AND revision = ?",
            (artifact_id, revision),
        ).fetchone()
        if row is not None:
            total += int(row["byte_size"])
    return total


def _migrate_v10_budget_reservations(conn: sqlite3.Connection) -> None:
    """R3 이전에 만들어진 Run 에 예약 행을 만든다.

    **없던 소비를 지어내는 것이 아니라 이미 있던 소비를 집계에 넣는 것이다.**
    각 값은 `run` 표가 실제로 아는 것만 담는다.

        run_count          실행이 존재한다 = 호출이 1 번 있었다. 확정값이다
        review_run_count   `role = reviewer` 인 실행만
        context_bytes      지시 원문 + 고정 컨텍스트 참조의 `byte_size` 합
        execution_seconds  `assigned_at → finished_at`. 둘 중 하나가 없으면 **모름**
        토큰·비용           `usage_json` 이 준 것만. 주지 않았으면 **`unavailable`**

    마지막 줄이 중요하다. 미보고를 0 으로 적으면 한도가 영원히 남아 있는 것처럼
    보인다(D-61). 그래서 그 행은 `actual_value = NULL`·`state = unresolved` 다.

    아직 끝나지 않은 실행은 `held` 로 둔다. 이행이 진행 중 실행을 끝난 것으로
    바꾸지 않는다.

    `migrate()` 는 매 연결마다 도므로 **이미 행이 있는 Run 은 건드리지 않는다.**
    과거의 재배정은 복원할 수 없으므로 현재 세대 하나에 대해서만 만든다 — 없는
    세대를 지어내지 않는다.
    """
    from domain import ids
    from domain.budget import (
        RESERVATION_KIND,
        ReservationKind,
        ReservationSource,
        ReservationState,
        SettleSource,
        normalize_usage,
    )
    from domain.models import (
        BUDGET_MEASUREMENT,
        BudgetMeasurement,
        BudgetMetric,
        RunOutcome,
        RunRole,
        RunStatus,
    )

    import json

    runs = conn.execute(
        "SELECT r.* FROM run r WHERE NOT EXISTS"
        " (SELECT 1 FROM budget_reservation b WHERE b.run_id = r.run_id)"
    ).fetchall()
    if not runs:
        return

    rows: list[tuple[Any, ...]] = []
    for run in runs:
        finished = run["status"] == RunStatus.FINISHED.value
        outcome = run["outcome"]
        role = run["role"]
        refs = [
            (r["artifact_id"], r["revision"])
            for r in conn.execute(
                "SELECT artifact_id, revision FROM run_context_ref WHERE run_id = ?"
                " ORDER BY seq",
                (run["run_id"],),
            ).fetchall()
        ]
        context_bytes = context_package_bytes(
            conn,
            run["instruction_artifact_id"],
            run["instruction_artifact_rev"],
            refs,
        )
        seconds = elapsed_seconds(run["assigned_at"], run["finished_at"])
        try:
            usage = json.loads(run["usage_json"])
        except (TypeError, ValueError):
            usage = "not_reported"
        reported = normalize_usage(usage)

        planned: dict[BudgetMetric, tuple[float | None, float | None, str]] = {
            # (예약값, 정산값, 정산 출처)
            BudgetMetric.RUN_COUNT: (1.0, 1.0 if finished else None, SettleSource.RESERVED_EXACT.value),
            BudgetMetric.CONTEXT_BYTES: (
                float(context_bytes),
                float(context_bytes) if finished else None,
                SettleSource.RESERVED_EXACT.value,
            ),
            BudgetMetric.EXECUTION_SECONDS: (
                None,
                seconds if finished else None,
                SettleSource.OBSERVED_CLOCK.value
                if seconds is not None
                else SettleSource.CLOCK_UNAVAILABLE.value,
            ),
        }
        if role == RunRole.REVIEWER.value:
            planned[BudgetMetric.REVIEW_RUN_COUNT] = (
                1.0,
                1.0 if finished else None,
                SettleSource.RESERVED_EXACT.value,
            )
        if finished:
            for metric in (
                BudgetMetric.INPUT_TOKENS,
                BudgetMetric.OUTPUT_TOKENS,
                BudgetMetric.ESTIMATED_COST,
            ):
                value = reported.get(metric)
                planned[metric] = (
                    None,
                    value,
                    SettleSource.ADAPTER_REPORTED.value
                    if value is not None
                    else SettleSource.ADAPTER_NOT_REPORTED.value,
                )

        for metric, (reserved, actual, settle_source) in planned.items():
            kind = RESERVATION_KIND[metric]
            if not finished:
                state = ReservationState.HELD.value
            elif actual is None:
                # **모르는 값을 0 으로 적지 않는다.** 노출에 남긴다.
                state = ReservationState.UNRESOLVED.value
            elif kind is ReservationKind.OPEN_ENDED_PER_RUN and (
                outcome == RunOutcome.UNKNOWN.value
            ):
                # 실행 시간만 결과 불명의 영향을 받는다 — 프로세스가 남아 있으면
                # 더 늘 수 있다. 실행 수·컨텍스트 크기는 더 커지지 않고, 어댑터가
                # 이미 보고한 토큰은 관측이지 추측이 아니다(라이브 결함, 9절).
                state = ReservationState.UNRESOLVED.value
            else:
                state = ReservationState.SETTLED.value
            measurement = (
                BUDGET_MEASUREMENT[metric].value
                if actual is not None
                else BudgetMeasurement.UNAVAILABLE.value
            )
            if (
                state == ReservationState.UNRESOLVED.value
                and actual is not None
                and outcome == RunOutcome.UNKNOWN.value
            ):
                settle_source = SettleSource.OUTCOME_UNKNOWN.value
            rows.append(
                (
                    ids.new_id("budres"),
                    run["case_id"],
                    run["run_id"],
                    run["assignment_generation"],
                    metric.value,
                    reserved,
                    actual,
                    measurement,
                    RESERVATION_KIND[metric].value,
                    role,
                    run["purpose"] or "",
                    state,
                    ReservationSource.MIGRATED_FROM_RUN.value,
                    settle_source if finished else None,
                    run["created_at"],
                    run["finished_at"] if finished else None,
                )
            )

    conn.executemany(
        "INSERT OR IGNORE INTO budget_reservation"
        " (id, case_id, run_id, generation, metric, reserved_value, actual_value,"
        "  measurement, reservation_kind, role, purpose, state, source, settle_source,"
        "  reserved_at, settled_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )



def _migrate_v14_policy_application(conn: sqlite3.Connection) -> None:
    """v13 까지의 정책 행에 적용 시각과 적용 경계를 채운다(P4-02).

    **되돌아보며 추정하는 값이 아니다.** v13 까지는 예약 경로 자체가 없었으므로
    기록된 모든 정책 행은 만들어진 순간에 적용됐다. 그래서 `applied_at` 은
    `created_at` 이고 경계는 `immediate` 다. 반대로 `started_policy_revision` 은
    채우지 않는다 — 그때는 시작 시점에 고정한 리비전이라는 것이 없었고, 지금
    현재 리비전을 적으면 "그 검사가 이 정책으로 돌았다"는 없는 사실이 생긴다.

    예약·취소 행이나 재검증 판정도 만들지 않는다. 이행은 멱등이다.
    """
    conn.execute(
        "UPDATE quality_gate_policy SET requested_at = created_at"
        " WHERE requested_at IS NULL"
    )
    conn.execute(
        "UPDATE quality_gate_policy SET applied_at = created_at,"
        " apply_boundary = 'immediate'"
        " WHERE applied_at IS NULL AND state IN ('current', 'superseded')"
    )


def _migrate_v11_progression(conn: sqlite3.Connection) -> None:
    """R4 이전에 만들어진 기록의 뜻을 **고정한다.**

    두 가지뿐이다. 둘 다 "지금 와서 값을 지어내지 않는다"의 구현이다.

    1. **기존 `completion_policy` 행은 전부 명시 설정이었다.** R4 이전에는 Autonomy
       에서 완료 모드를 도출하는 경로가 없었으므로, 행이 있다는 것은 누군가
       `set_completion_mode()` 를 불렀다는 뜻이다. `source = migrated_explicit` 로
       적어 두면 도출값이 그 행을 덮지 않는다 — "사용자 명시 설정을 조용히
       덮어쓰지 않는다"(autonomy-budget-policy 5절).

    2. **기존 게이트 통과는 독립 검토를 실제로 거쳤다.** R4 이전의 `pass` 는
       `combine_verdicts` 가 AI 판정 없이는 내주지 않는 값이었다(`not_run` 을
       `pass` 로 올리지 않는다). 그래서 `conformance_check` 행을
       `method = independent` 로 만든다. 지어내는 것이 아니라 **이미 있었던 사실을
       새 표에 옮기는 것**이다. AI 검토가 없었던 행에는 만들지 않는다.

    `criterion_result.satisfaction` 은 **비워 둔다.** 옛 판정이 어떻게 충족됐는지는
    그때 묻지 않았고, `changed_and_verified` 로 채우면 없는 관측을 지어내는 일이다.
    미재현으로 `met` 이 된 행이 섞여 있어도 지금은 알 수 없다 — 모르는 것을 모른다고
    두는 편이 정확하다.
    """
    from domain import ids
    from domain.models import ConformanceMethod, GateVerdict

    now = utc_now()

    conn.execute(
        "UPDATE completion_policy SET source = 'migrated_explicit' WHERE source IS NULL"
    )

    rows = conn.execute(
        "SELECT g.* FROM gate_result g"
        " WHERE g.ai_run_id IS NOT NULL"
        "   AND NOT EXISTS (SELECT 1 FROM conformance_check c"
        "                   WHERE c.intent_version_id = g.intent_version_id"
        "                     AND c.method = ?)",
        (ConformanceMethod.INDEPENDENT.value,),
    ).fetchall()
    for row in rows:
        conn.execute(
            "INSERT INTO conformance_check"
            " (id, case_id, intent_version_id, method, required_method, verdict,"
            "  run_id, subject_content_hash, unverified_scope, reasons_json, recorded_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, '[]', ?)",
            (
                ids.new_id("conf"),
                row["case_id"],
                row["intent_version_id"],
                ConformanceMethod.INDEPENDENT.value,
                ConformanceMethod.INDEPENDENT.value,
                row["ai_verdict"] or GateVerdict.NOT_RUN.value,
                row["ai_run_id"],
                row["subject_content_hash"],
                row["reviewed_at"] or now,
            ),
        )
