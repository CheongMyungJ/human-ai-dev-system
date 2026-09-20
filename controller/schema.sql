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

-- ===================================================================
-- 스키마 v4 (P2-04 결과·재시작)
--
-- 같은 저장 경계 규칙이 그대로 적용된다. 아래 표에도 **본문 컬럼은 없다.**
-- 성공 기준의 본문(관련 목표·확인 방법·기대값)은 의도 원문 안에 있고, 근거의
-- 서술과 인수·예외의 문구도 소유 Runner에 있다. 여기에는 판정·사유 코드·참조와
-- 짧은 요약만 남는다.
--
-- **세 종류의 기록을 합치지 않는다**(completion-lifecycle 4·7절).
--   final_acceptance   사람 또는 정책이 이 후보를 인수했다
--   exception_decision 표시된 미충족·미검증을 사람이 수용했다
--   closure_record     업무가 실제로 종료로 확정됐다
-- 한 화면에서 결정해도 표는 분리한다. 인수가 예외를 만들지 않고, 인수만으로
-- 종료가 확정되지도 않는다(미정리 실행이 남으면 closure_record 가 생기지 않는다).
-- ===================================================================

-- 합의한 성공 기준. **의도 버전에 묶인다**(intent-artifacts 1절
-- "성공 기준은 의도에서 분리되지 않도록 연결한다").
--
-- 새 의도 버전은 기준을 승계하지 않는다. 게이트와 같은 규칙이며, 승계하면
-- 바뀐 의도에 옛 기준이 그대로 붙어 버린다.
CREATE TABLE IF NOT EXISTS success_criterion (
    id                TEXT PRIMARY KEY,
    case_id           TEXT NOT NULL REFERENCES "case"(id),
    intent_version_id TEXT NOT NULL REFERENCES intent_version(id),
    criterion_key     TEXT NOT NULL,   -- 버전이 바뀌어도 같은 기준을 잇는 키
    summary           TEXT NOT NULL,   -- 짧은 요약. 원문 대체 아님
    method_summary    TEXT NOT NULL,   -- 확인 방법의 짧은 요약. 원문 대체 아님
    relates_to        TEXT NOT NULL,   -- 연결된 의도 항목(goal|expected_outcome|...)
    state             TEXT NOT NULL,   -- proposed | user_confirmed | superseded
    created_at        TEXT NOT NULL,
    UNIQUE (intent_version_id, criterion_key),
    CHECK (length(summary) <= 200),
    CHECK (length(method_summary) <= 200)
);

-- 기준별 결과. **기본값은 `unverified` 다.**
--
-- 실행이 끝났다는 사실이 판정을 만들지 않는다. 판정을 기록하려면 근거 참조가
-- 있어야 하고, `met` 은 근거 Run 의 outcome 이 `completed` 일 때만 받는다.
-- outcome 이 `unknown` 인 Run을 근거로 한 `met` 은 거부된다 — 실행 불명이
-- 성공이 되지 않게 하는 지점이다(FR-28, completion-lifecycle 5절).
--
-- `unknown` 은 여기 판정값에 **없다.** 실행의 불명은 run.outcome 쪽 값이며
-- 기준 판정으로 옮기면 불명이 조용히 판정이 되어 버린다.
CREATE TABLE IF NOT EXISTS criterion_result (
    id                   TEXT PRIMARY KEY,
    criterion_id         TEXT NOT NULL REFERENCES success_criterion(id),
    case_id              TEXT NOT NULL REFERENCES "case"(id),
    verdict              TEXT NOT NULL,   -- unverified|met|not_met|blocked|needs_recheck
    evidence_kind        TEXT NOT NULL,   -- none|run_output|human_judgement
    evidence_run_id      TEXT REFERENCES run(run_id),
    evidence_artifact_id TEXT,            -- 근거 원문 참조. 본문은 Runner에
    evidence_artifact_rev INTEGER,
    summary              TEXT NOT NULL,   -- 짧은 요약. 원문 대체 아님
    recorded_by          TEXT NOT NULL,
    recorded_at          TEXT NOT NULL,
    UNIQUE (criterion_id),
    CHECK (length(summary) <= 200)
);

-- Case별 완료 정책(D-31). 기본은 사람 최종 확인이다.
CREATE TABLE IF NOT EXISTS completion_policy (
    case_id    TEXT PRIMARY KEY REFERENCES "case"(id),
    mode       TEXT NOT NULL,   -- human_acceptance | auto_on_conditions
    set_by     TEXT NOT NULL,
    set_at     TEXT NOT NULL
);

-- 최종 결과 후보. 종료 후보가 준비된 시점의 **스냅샷**이다.
--
-- `snapshot_hash` 는 이 후보가 무엇을 보여 줬는지를 고정한다. 그 사이 기준 판정·
-- 게이트·동의·실행 상태가 바뀌면 해시가 달라지고 새 후보가 생기며 이전 후보는
-- superseded 가 된다. 사용자가 본 것과 다른 것을 인수하지 않게 하기 위해서다
-- (completion-lifecycle 3절 "후보가 의미 있게 바뀌면 이전 확인을 재사용하지 않는다").
CREATE TABLE IF NOT EXISTS completion_candidate (
    id                     TEXT PRIMARY KEY,
    case_id                TEXT NOT NULL REFERENCES "case"(id),
    revision               INTEGER NOT NULL,
    intent_version_id      TEXT REFERENCES intent_version(id),
    intent_agreement_state TEXT NOT NULL,
    gate_verdict           TEXT NOT NULL,
    criteria_total         INTEGER NOT NULL,
    criteria_met           INTEGER NOT NULL,
    unresolved_json        TEXT NOT NULL,   -- 미해결 항목의 코드·참조 목록(본문 없음)
    unsettled_runs_json    TEXT NOT NULL,   -- 진행 중·결과 불명 Run 목록(본문 없음)
    snapshot_hash          TEXT NOT NULL,
    state                  TEXT NOT NULL,   -- open | superseded
    created_at             TEXT NOT NULL,
    superseded_at          TEXT,
    UNIQUE (case_id, revision)
);

-- 후보가 본 기준별 판정의 사본. 나중에 판정이 바뀌어도 "그때 무엇을 보고
-- 인수했는가"가 남아야 한다(FR-23 "사용자가 본 대상").
CREATE TABLE IF NOT EXISTS candidate_criterion (
    candidate_id  TEXT NOT NULL REFERENCES completion_candidate(id),
    criterion_id  TEXT NOT NULL REFERENCES success_criterion(id),
    verdict       TEXT NOT NULL,
    PRIMARY KEY (candidate_id, criterion_id)
);

-- 최종 인수. **자동 완료를 사람 인수로 적지 않는다**(FR-17, D-31).
-- `decision_id` 로 FR-23의 결정 목록과 이어 두되 표는 따로 둔다.
CREATE TABLE IF NOT EXISTS final_acceptance (
    id           TEXT PRIMARY KEY,
    case_id      TEXT NOT NULL REFERENCES "case"(id),
    candidate_id TEXT NOT NULL REFERENCES completion_candidate(id),
    decision_id  TEXT NOT NULL REFERENCES decision(id),
    mode         TEXT NOT NULL,   -- human | auto_policy
    actor        TEXT NOT NULL,
    statement_artifact_id TEXT,   -- 인수 문구의 원문 참조. 본문은 Runner에
    accepted_at  TEXT NOT NULL,
    UNIQUE (candidate_id)
);

-- 예외 결정. **원래 판정을 보존한다.**
-- `original_verdict` 를 복사해 두고 criterion_result 는 건드리지 않는다.
-- 예외 수용이 미충족을 충족으로 바꾸지 않는다(completion-lifecycle 4절).
CREATE TABLE IF NOT EXISTS exception_decision (
    id               TEXT PRIMARY KEY,
    case_id          TEXT NOT NULL REFERENCES "case"(id),
    candidate_id     TEXT NOT NULL REFERENCES completion_candidate(id),
    decision_id      TEXT NOT NULL REFERENCES decision(id),
    target_type      TEXT NOT NULL,   -- criterion
    target_id        TEXT NOT NULL,
    original_verdict TEXT NOT NULL,   -- 수용 시점의 판정. 바꾸지 않는다
    scope_summary    TEXT NOT NULL,   -- 이 예외가 적용되는 범위의 짧은 요약
    actor            TEXT NOT NULL,
    decided_at       TEXT NOT NULL,
    UNIQUE (candidate_id, target_type, target_id),
    CHECK (length(scope_summary) <= 200)
);

-- 종료 확정 기록. **인수만으로 만들어지지 않는다.**
-- 미정리 실행(진행 중이거나 결과 불명)이 남아 있으면 인수 기록은 남기되 이 행을
-- 만들지 않는다(completion-lifecycle 5절).
CREATE TABLE IF NOT EXISTS closure_record (
    id                  TEXT PRIMARY KEY,
    case_id             TEXT NOT NULL REFERENCES "case"(id),
    candidate_id        TEXT NOT NULL REFERENCES completion_candidate(id),
    final_acceptance_id TEXT REFERENCES final_acceptance(id),
    closure_kind        TEXT NOT NULL,  -- completed | closed_with_exceptions | cancelled
    exception_count     INTEGER NOT NULL,
    confirmed_at        TEXT NOT NULL,
    UNIQUE (case_id)
);

-- Case 사이의 연결. 완료 후 수정은 기존 Case 재개가 아니라 연결된 새 Case 다(D-33).
CREATE TABLE IF NOT EXISTS case_relation (
    id             TEXT PRIMARY KEY,
    from_case_id   TEXT NOT NULL REFERENCES "case"(id),
    to_case_id     TEXT NOT NULL REFERENCES "case"(id),
    relation       TEXT NOT NULL,   -- follow_up_change
    reason_summary TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    UNIQUE (from_case_id, to_case_id, relation),
    CHECK (length(reason_summary) <= 200)
);

CREATE INDEX IF NOT EXISTS idx_criterion_case ON success_criterion(case_id, state);
CREATE INDEX IF NOT EXISTS idx_criterion_intent ON success_criterion(intent_version_id);
CREATE INDEX IF NOT EXISTS idx_criterion_result_case ON criterion_result(case_id, verdict);
CREATE INDEX IF NOT EXISTS idx_candidate_case ON completion_candidate(case_id, state);
CREATE INDEX IF NOT EXISTS idx_exception_case ON exception_decision(case_id);
CREATE INDEX IF NOT EXISTS idx_case_relation_from ON case_relation(from_case_id);
