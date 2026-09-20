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
