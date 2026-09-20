-- 제어부 상태 DB 스키마 v1 (P2-01)
--
-- 저장 경계 규칙 (data-boundary-review.md 1절, D-51, NFR-12):
--   이 DB에는 업무 상태 · 짧은 요약 · 원문 참조만 둔다.
--   의도 · 피드백 · 지시 · 실행 출력의 **본문을 담는 컬럼은 없다.**
--   본문은 소유 Runner의 로컬 저장소에 있고 여기에는
--   (artifact_id, revision, content_hash, owner_runner_id, availability) 만 남는다.
--   나중에 끄는 설정이 아니라 스키마 수준의 제약이다.
--   tests/test_data_boundary.py 가 이 규칙을 파일 바이트 수준에서 확인한다.
--
--   `summary` 컬럼은 사람이 목록에서 구별하기 위한 짧은 제목·요약이며
--   원문을 대체하지 않는다. 길이 상한을 두고 본문을 밀어 넣지 못하게 한다.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    applied_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS owner (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project (
    id              TEXT PRIMARY KEY,
    owner_id        TEXT NOT NULL REFERENCES owner(id),
    name            TEXT NOT NULL,
    repo_path       TEXT NOT NULL,           -- Runner 호스트에서 해석하는 저장소 경로
    default_tool_id TEXT NOT NULL,           -- 프로젝트 기본 CLI (D-45)
    created_at      TEXT NOT NULL,
    UNIQUE (owner_id, name)
);

CREATE TABLE IF NOT EXISTS runner (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    host              TEXT NOT NULL,
    status            TEXT NOT NULL,          -- registered | offline
    registered_at     TEXT NOT NULL,
    last_heartbeat_at TEXT
);

CREATE TABLE IF NOT EXISTS runner_capability (
    runner_id   TEXT NOT NULL REFERENCES runner(id),
    tool_id     TEXT NOT NULL,
    mode        TEXT NOT NULL,
    capability  TEXT NOT NULL,
    state       TEXT NOT NULL,                -- doc_only | verified | unsupported | unknown
    source      TEXT NOT NULL,                -- 이 상태의 근거 (문서·실측 위치)
    observed_at TEXT NOT NULL,
    PRIMARY KEY (runner_id, tool_id, mode, capability)
);

CREATE TABLE IF NOT EXISTS "case" (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES project(id),
    title       TEXT NOT NULL,                -- 목록 표시용 제목. 원문이 아니다
    kind        TEXT NOT NULL,                -- feature | bug | analysis | research
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- 원문 참조. 본문 컬럼 없음.
CREATE TABLE IF NOT EXISTS artifact_ref (
    artifact_id     TEXT NOT NULL,
    revision        INTEGER NOT NULL,
    case_id         TEXT NOT NULL REFERENCES "case"(id),
    kind            TEXT NOT NULL,            -- intent | feedback | instruction | run_output
    content_hash    TEXT NOT NULL,
    byte_size       INTEGER NOT NULL,
    owner_runner_id TEXT NOT NULL REFERENCES runner(id),
    availability    TEXT NOT NULL,            -- pending | available | runner_offline | lost_before_persist
    summary         TEXT NOT NULL,            -- 짧은 요약. 원문 대체 아님
    created_at      TEXT NOT NULL,
    PRIMARY KEY (artifact_id, revision),
    CHECK (length(summary) <= 200)
);

CREATE TABLE IF NOT EXISTS intent_version (
    id              TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES "case"(id),
    revision        INTEGER NOT NULL,
    artifact_id     TEXT NOT NULL,
    artifact_rev    INTEGER NOT NULL,
    status          TEXT NOT NULL,            -- draft | agreed | superseded
    created_at      TEXT NOT NULL,
    superseded_by   TEXT REFERENCES intent_version(id),
    UNIQUE (case_id, revision),
    FOREIGN KEY (artifact_id, artifact_rev) REFERENCES artifact_ref(artifact_id, revision)
);

-- 사람의 결정. 종류를 구별해 기록한다(FR-23). 하나가 다른 하나를 만들지 않는다.
CREATE TABLE IF NOT EXISTS decision (
    id               TEXT PRIMARY KEY,
    case_id          TEXT NOT NULL REFERENCES "case"(id),
    kind             TEXT NOT NULL,
    subject_type     TEXT NOT NULL,           -- intent_version | run | ...
    subject_id       TEXT NOT NULL,
    subject_revision INTEGER NOT NULL,        -- 결정 대상의 버전. 이후 버전에 자동 적용되지 않는다
    actor            TEXT NOT NULL,           -- 결정한 주체
    decided_at       TEXT NOT NULL,
    evidence_ref     TEXT,                    -- 근거 메시지의 artifact_id (원문은 Runner에)
    revoked_at       TEXT
);

CREATE TABLE IF NOT EXISTS run (
    run_id                  TEXT PRIMARY KEY,
    case_id                 TEXT NOT NULL REFERENCES "case"(id),
    task_id                 TEXT NOT NULL,
    role                    TEXT NOT NULL,     -- author | reviewer
    tool_id                 TEXT NOT NULL,
    mode                    TEXT NOT NULL,
    permission              TEXT NOT NULL,
    instruction_artifact_id TEXT NOT NULL,
    instruction_artifact_rev INTEGER NOT NULL,
    status                  TEXT NOT NULL,     -- pending | assigned | running | finished
    assignment_generation   INTEGER NOT NULL,  -- fencing. 오래된 실행자의 보고를 막는다
    assigned_runner_id      TEXT REFERENCES runner(id),
    outcome                 TEXT,              -- completed | failed | cancelled | unknown
    exit_code               INTEGER,
    output_artifact_id      TEXT,
    output_artifact_rev     INTEGER,
    session_ref             TEXT,
    usage_json              TEXT NOT NULL DEFAULT '"not_reported"',
    workspace_effect_json   TEXT,
    residual_activity       TEXT NOT NULL DEFAULT 'unknown',
    observed_tool_version   TEXT,
    created_at              TEXT NOT NULL,
    assigned_at             TEXT,
    finished_at             TEXT,
    FOREIGN KEY (instruction_artifact_id, instruction_artifact_rev)
        REFERENCES artifact_ref(artifact_id, revision)
);

-- 정규화 이벤트. (run_id, seq) 를 기본 키로 두어 같은 이벤트의 재전송이
-- 행을 늘리지 않게 한다(NFR-02의 중복 이벤트 대조).
CREATE TABLE IF NOT EXISTS run_event (
    run_id      TEXT NOT NULL REFERENCES run(run_id),
    seq         INTEGER NOT NULL,
    ts          TEXT NOT NULL,
    type        TEXT NOT NULL,
    native_type TEXT,
    raw_ref     TEXT,                          -- Runner 로컬 원문 위치 참조
    received_at TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);

-- 원문 중계 접수 기록. **본문 컬럼 없음.**
-- 본문은 제어부 메모리에만 잠시 있고, Runner가 영속 저장을 보고해야 저장 완료가 된다.
-- 제어부가 그 전에 재시작하면 본문은 사라지고 이 행은 lost_before_persist 로 남는다.
CREATE TABLE IF NOT EXISTS intake (
    id           TEXT PRIMARY KEY,
    case_id      TEXT NOT NULL REFERENCES "case"(id),
    kind         TEXT NOT NULL,
    artifact_id  TEXT NOT NULL,
    revision     INTEGER NOT NULL,
    target_runner_id TEXT NOT NULL REFERENCES runner(id),
    state        TEXT NOT NULL,                -- pending | stored | lost_before_persist
    expected_hash TEXT NOT NULL,               -- 제어부가 중계 중 계산한 해시
    byte_size    INTEGER NOT NULL,
    summary      TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    stored_at    TEXT,
    CHECK (length(summary) <= 200)
);

-- 같은 요청의 재전송을 같은 응답으로 돌려준다(NFR-02, P1 이월 항목).
CREATE TABLE IF NOT EXISTS request_log (
    request_key   TEXT PRIMARY KEY,
    endpoint      TEXT NOT NULL,
    response_json TEXT NOT NULL,
    status_code   INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_case_project ON "case"(project_id);
CREATE INDEX IF NOT EXISTS idx_run_case ON run(case_id);
CREATE INDEX IF NOT EXISTS idx_run_pending ON run(status, assigned_runner_id);
CREATE INDEX IF NOT EXISTS idx_intake_pending ON intake(state, target_runner_id);
CREATE INDEX IF NOT EXISTS idx_artifact_case ON artifact_ref(case_id);
CREATE INDEX IF NOT EXISTS idx_decision_case ON decision(case_id, kind);

-- ===================================================================
-- 스키마 v2 (P2-02 의도·피드백)
--
-- 같은 저장 경계 규칙이 그대로 적용된다. 아래 표에도 **본문 컬럼은 없다.**
-- 의도 여섯 필드의 본문, 피드백 원문, 질문의 대상·근거·선택·영향,
-- 열람으로 오간 원문은 모두 소유 Runner에 있고 여기에는 상태·참조·짧은 요약만 남는다.
-- tests/test_data_boundary.py 가 이 규칙을 파일 바이트 수준에서 확인한다.
-- ===================================================================

-- 의도 초안의 여섯 필드. 버전마다 여섯 행이 모두 존재한다.
-- 정보가 없으면 행을 지우는 것이 아니라 state='undecided' 로 남긴다
-- (intent-artifacts 1절: "정보가 없으면 항목을 삭제하거나 AI가 채우지 않고 미정으로 남긴다").
CREATE TABLE IF NOT EXISTS intent_field (
    intent_version_id TEXT NOT NULL REFERENCES intent_version(id),
    field             TEXT NOT NULL,   -- goal|expected_outcome|scope|exclusions|constraints|open_questions
    state             TEXT NOT NULL,   -- undecided|proposed|user_confirmed|needs_recheck|superseded
    origin            TEXT NOT NULL,   -- none|user_requirement|project_rule|observation|ai_proposal|ai_assumption
    change_from_prev  TEXT NOT NULL,   -- initial|unchanged|changed
    PRIMARY KEY (intent_version_id, field)
);

-- 미정 질문. 본문(대상·근거·선택·영향)은 의도 원문 안에 있다.
-- 여기에는 목록에 보일 짧은 요약과 결정 시점·상태만 둔다(FR-13, intent-artifacts 2·3절).
CREATE TABLE IF NOT EXISTS intent_question (
    id                TEXT PRIMARY KEY,
    case_id           TEXT NOT NULL REFERENCES "case"(id),
    intent_version_id TEXT NOT NULL REFERENCES intent_version(id),
    question_key      TEXT NOT NULL,   -- 버전이 바뀌어도 같은 질문을 잇는 키
    summary           TEXT NOT NULL,   -- 짧은 요약. 원문 대체 아님
    decide_at         TEXT NOT NULL,   -- intent | design | plan  (이월 시점)
    state             TEXT NOT NULL,   -- open | answered | withdrawn
    answered_by       TEXT,
    answered_at       TEXT,
    answer_artifact_id TEXT,           -- 답변 원문 참조. 본문은 Runner에
    created_at        TEXT NOT NULL,
    UNIQUE (intent_version_id, question_key),
    CHECK (length(summary) <= 200)
);

-- 피드백. 원문은 Runner에 있고 여기에는 대상 버전·상태·짧은 요약만 남는다.
CREATE TABLE IF NOT EXISTS feedback (
    id                      TEXT PRIMARY KEY,
    case_id                 TEXT NOT NULL REFERENCES "case"(id),
    target_intent_version_id TEXT NOT NULL REFERENCES intent_version(id),
    target_intent_revision  INTEGER NOT NULL,
    artifact_id             TEXT NOT NULL,
    artifact_rev            INTEGER NOT NULL,
    author                  TEXT NOT NULL,
    summary                 TEXT NOT NULL,
    state                   TEXT NOT NULL,   -- received | reflected | not_reflected
    reflected_in_version_id TEXT REFERENCES intent_version(id),
    disposition_note        TEXT,            -- 미반영 이유의 짧은 요약
    created_at              TEXT NOT NULL,
    resolved_at             TEXT,
    CHECK (length(summary) <= 200),
    CHECK (disposition_note IS NULL OR length(disposition_note) <= 200)
);

-- 초안 열람 기록. **조회는 동의가 아니다.**
-- decision 과 별개 표로 두어 "요약만 읽은 상태를 원문 확인으로 기록하지 않는다"를
-- 검사 가능하게 만든다(intent-artifacts 5절).
CREATE TABLE IF NOT EXISTS intent_view (
    id                TEXT PRIMARY KEY,
    case_id           TEXT NOT NULL REFERENCES "case"(id),
    intent_version_id TEXT NOT NULL REFERENCES intent_version(id),
    actor             TEXT NOT NULL,
    content_hash      TEXT NOT NULL,   -- 실제로 본 원문의 해시
    viewed_at         TEXT NOT NULL
);

-- 원문 열람 요청(일시중계). **본문 컬럼 없음.**
-- 본문은 소유 Runner가 올려 제어부 메모리 버퍼에만 잠시 있다가 브라우저가
-- 한 번 받아 가면 버려진다. 제어부가 그 사이 재시작하면 요청은 expired 가 된다
-- (data-boundary-review 3절: 임시 메모리 중계와 영구 보관의 분리).
CREATE TABLE IF NOT EXISTS artifact_read_request (
    id              TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES "case"(id),
    artifact_id     TEXT NOT NULL,
    revision        INTEGER NOT NULL,
    owner_runner_id TEXT NOT NULL REFERENCES runner(id),
    requested_by    TEXT NOT NULL,
    state           TEXT NOT NULL,   -- pending | relayed | delivered | expired
    content_hash    TEXT,            -- Runner가 실제로 읽은 원문의 해시
    byte_size       INTEGER,
    requested_at    TEXT NOT NULL,
    relayed_at      TEXT,
    delivered_at    TEXT,
    FOREIGN KEY (artifact_id, revision) REFERENCES artifact_ref(artifact_id, revision)
);

CREATE INDEX IF NOT EXISTS idx_question_case ON intent_question(case_id, state);
CREATE INDEX IF NOT EXISTS idx_feedback_case ON feedback(case_id, state);
CREATE INDEX IF NOT EXISTS idx_read_request_pending
    ON artifact_read_request(state, owner_runner_id);

-- ===================================================================
-- 스키마 v3 (P2-03 진입 제어·제한 실행)
--
-- 같은 저장 경계 규칙이 그대로 적용된다. 아래 표에도 **본문 컬럼은 없다.**
-- 게이트 검토에 들어간 지시, AI 검토가 낸 서술, 진입 검사가 본 원문은 모두
-- 소유 Runner에 있고 여기에는 판정·사유 코드·참조·짧은 요약만 남는다.
-- ===================================================================

-- 품질 게이트 판정. 이번 단계는 QG-01만 만든다.
--
-- 판정은 **대상 의도 버전과 그 시점의 원문 해시에 묶인다.** 새 버전이 생기면
-- 이전 판정을 승계하지 않고 `needs_recheck` 로 바꾼다(quality-gates 2절
-- "다시 켤 때는 유효한 증거를 재사용", 3절 "변경으로 재검토 필요").
--
-- `rule_verdict` 와 `ai_verdict` 를 따로 두는 이유는 두 검사의 성격이 다르기
-- 때문이다(quality-gates 4절 A~D). 규칙만 통과한 상태는 게이트 통과가 아니다.
CREATE TABLE IF NOT EXISTS gate_result (
    id                   TEXT PRIMARY KEY,
    case_id              TEXT NOT NULL REFERENCES "case"(id),
    gate                 TEXT NOT NULL,          -- QG-01
    intent_version_id    TEXT NOT NULL REFERENCES intent_version(id),
    subject_content_hash TEXT NOT NULL,          -- 판정 대상 원문의 해시
    verdict              TEXT NOT NULL,          -- pass|fail|hold|not_run|needs_recheck|blocked
    rule_verdict         TEXT NOT NULL,
    ai_verdict           TEXT NOT NULL,
    ai_run_id            TEXT REFERENCES run(run_id),
    ai_session_ref       TEXT,                   -- 검토 세션 식별자(실제 CLI가 준 값)
    author_session_ref   TEXT,                   -- 작성 세션 식별자. 같으면 별도 세션이 아니다
    evaluated_at         TEXT NOT NULL,
    reviewed_at          TEXT,
    superseded_at        TEXT,
    UNIQUE (intent_version_id, gate)
);

-- 개별 발견 사항. 점수로 합산하지 않고 기준·필수/권고·차단 효과를 각각 남긴다
-- (quality-gates 3절 "점수 대신 근거와 판정의 분리").
CREATE TABLE IF NOT EXISTS gate_finding (
    id                   TEXT PRIMARY KEY,
    gate_result_id       TEXT NOT NULL REFERENCES gate_result(id),
    source               TEXT NOT NULL,          -- rule | ai
    criterion            TEXT NOT NULL,          -- 어떤 기준을 위반하는지
    severity             TEXT NOT NULL,          -- required | advisory
    blocking             INTEGER NOT NULL,       -- 이 발견이 진행을 막는가
    certainty            TEXT NOT NULL,          -- confirmed | suspected
    target               TEXT NOT NULL,          -- 대상(항목 이름 등)
    summary              TEXT NOT NULL,          -- 짧은 요약. 원문 대체 아님
    evidence_artifact_id TEXT,                   -- 근거 원문 참조. 본문은 Runner에
    created_at           TEXT NOT NULL,
    CHECK (length(summary) <= 200)
);

-- 진입 조건 검사 기록. **통과도 거부도 남긴다.**
-- 거부는 화면 밖(직접 API 호출)에서도 같은 근거로 재현돼야 하므로 결정에 쓴
-- 상태값을 함께 적는다(FR-29 수용 기준).
CREATE TABLE IF NOT EXISTS admission_check (
    id                     TEXT PRIMARY KEY,
    case_id                TEXT NOT NULL REFERENCES "case"(id),
    run_id                 TEXT,                 -- 허용된 경우의 Run. 거부면 NULL
    requested_run_id       TEXT NOT NULL,
    requested_purpose      TEXT NOT NULL,
    requested_role         TEXT NOT NULL,
    requested_permission   TEXT NOT NULL,
    requested_task_id      TEXT NOT NULL,
    requested_tool_id      TEXT NOT NULL,
    profile                TEXT NOT NULL,        -- feature_intent | non_feature_minimal | intent_production
    outcome                TEXT NOT NULL,        -- admitted | refused
    refusals_json          TEXT NOT NULL,        -- 사유 코드 목록(본문 없음)
    intent_version_id      TEXT,
    intent_agreement_state TEXT,
    gate_verdict           TEXT,
    checked_at             TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gate_result_case ON gate_result(case_id, gate);
CREATE INDEX IF NOT EXISTS idx_gate_finding_result ON gate_finding(gate_result_id);
CREATE INDEX IF NOT EXISTS idx_admission_case ON admission_check(case_id, checked_at);
