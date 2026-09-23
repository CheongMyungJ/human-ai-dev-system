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

-- ===================================================================
-- 스키마 v5 (P3-01 수준·설계·계획)
--
-- 같은 저장 경계 규칙이 그대로 적용된다. 아래 표에도 **본문 컬럼은 없다.**
-- 축별 근거의 서술, 설계안·개발계획의 본문, 수준 조정 이유의 원문은 모두 소유
-- Runner에 있고 여기에는 판단값·상태·참조와 짧은 요약만 남는다.
--
-- **세 종류의 기록을 합치지 않는다.**
--   sizing_assessment    이 업무에 어느 정도 준비가 필요한가(AI 제안 / 사람 조정)
--   preparation_artifact 설계안·개발계획 산출물이 실제로 존재하는가
--   stage_review         그 산출물을 사람이 검토했는가, 또는 자동 조건이 충족됐는가
-- 산출물의 존재·품질 판정·사람 검토는 서로 다른 것이다(FR-05 검토).
-- ===================================================================

-- 작업 수준 판단. **AI 제안과 사람 조정이 같은 표의 다른 행이다.**
--
-- `recommended_level` 은 AI가 제안한 수준, `derived_level` 은 제어부가 축에서
-- 도출한 수준, `level` 은 실제로 적용되는 수준이다. 셋을 따로 두는 이유는
-- "AI가 진행을 위해 수행 수준을 묵시적으로 낮추는 것"을 기록으로 드러내기
-- 위해서다(sizing-and-review-ux 1·3절). AI 제안이 도출값보다 낮으면 `level` 은
-- 도출값이 되고 두 값이 모두 남는다. 낮추는 것은 사람만 할 수 있다.
CREATE TABLE IF NOT EXISTS sizing_assessment (
    id                    TEXT PRIMARY KEY,
    case_id               TEXT NOT NULL REFERENCES "case"(id),
    revision              INTEGER NOT NULL,
    intent_version_id     TEXT REFERENCES intent_version(id),
    source                TEXT NOT NULL,   -- ai_recommendation | human_adjustment
    recommended_level     TEXT NOT NULL,   -- AI가 제안한 수준
    derived_level         TEXT NOT NULL,   -- 축에서 도출한 수준
    level                 TEXT NOT NULL,   -- 실제 적용 수준
    adjusted_from         TEXT,            -- 사람이 바꿨다면 이전 수준
    evidence_gap          INTEGER NOT NULL DEFAULT 0,  -- 근거 부족 축이 있는가
    reason_summary        TEXT NOT NULL,   -- 조정 이유의 짧은 요약. 원문 대체 아님
    residual_risk_summary TEXT NOT NULL,   -- 남는 위험의 짧은 요약. 원문 대체 아님
    actor                 TEXT NOT NULL,
    state                 TEXT NOT NULL,   -- current | superseded
    created_at            TEXT NOT NULL,
    superseded_at         TEXT,
    UNIQUE (case_id, revision),
    CHECK (length(reason_summary) <= 200),
    CHECK (length(residual_risk_summary) <= 200)
);

-- 축별 판단. **숫자 점수가 없다.** 축마다 영향·판단·미확인 사항을 따로 남기며
-- 평균을 내지 않는다 — 낮은 항목들의 평균으로 권한·마이그레이션 같은 중요한
-- 영향을 상쇄하지 않기 위해서다(sizing-and-review-ux 1절).
CREATE TABLE IF NOT EXISTS sizing_axis (
    assessment_id       TEXT NOT NULL REFERENCES sizing_assessment(id),
    axis                TEXT NOT NULL,   -- 일곱 축
    weight              TEXT NOT NULL,   -- low|medium|high|insufficient_evidence
    judgement_summary   TEXT NOT NULL,   -- 현재 판단의 짧은 요약
    unconfirmed_summary TEXT NOT NULL,   -- 아직 확인할 것의 짧은 요약
    PRIMARY KEY (assessment_id, axis),
    CHECK (length(judgement_summary) <= 200),
    CHECK (length(unconfirmed_summary) <= 200)
);

-- 설계안·개발계획 산출물. **본문 컬럼 없음.**
--
-- 한 표에 `stage` 로 두 단계를 담는다. 표를 둘로 나누면 버전·대체·검토 규칙을
-- 두 벌 쓰게 되고 한쪽만 고치는 실수가 생긴다. **조회 경로는 단계별로 따로** 두어
-- "각각 조회할 수 있다"를 지킨다(intent-artifacts 2절).
--
-- `intent_version_id` 가 오래된 승인을 막는 지점이다. 새 의도 버전이 생기면 그
-- 위에 세운 산출물은 `superseded` 가 되고 그 검토도 재사용되지 않는다.
CREATE TABLE IF NOT EXISTS preparation_artifact (
    id                 TEXT PRIMARY KEY,
    case_id            TEXT NOT NULL REFERENCES "case"(id),
    stage              TEXT NOT NULL,   -- design | plan
    revision           INTEGER NOT NULL,
    artifact_id        TEXT NOT NULL,
    artifact_rev       INTEGER NOT NULL,
    intent_version_id  TEXT NOT NULL REFERENCES intent_version(id),
    based_on_design_id TEXT REFERENCES preparation_artifact(id),  -- 계획이 세운 설계
    level              TEXT NOT NULL,   -- 작성 시점의 작업 수준
    authoring_mode     TEXT NOT NULL,   -- human_typed | ai_drafted
    author_run_id      TEXT,
    summary            TEXT NOT NULL,   -- 짧은 요약. 원문 대체 아님
    state              TEXT NOT NULL,   -- current | superseded
    created_at         TEXT NOT NULL,
    superseded_at      TEXT,
    UNIQUE (case_id, stage, revision),
    FOREIGN KEY (artifact_id, artifact_rev) REFERENCES artifact_ref(artifact_id, revision),
    CHECK (length(summary) <= 200)
);

-- 산출물의 항목 구조 보고. **본문 없음.** 소유 Runner가 원문에서 뽑아 올린다.
-- 수준이 요구하는 항목이 미정인지를 이 표로 판단한다(진입 조건).
CREATE TABLE IF NOT EXISTS preparation_section (
    preparation_id TEXT NOT NULL REFERENCES preparation_artifact(id),
    section        TEXT NOT NULL,
    state          TEXT NOT NULL,   -- undecided|proposed|user_confirmed|needs_recheck|superseded
    origin         TEXT NOT NULL,   -- none|user_requirement|project_rule|observation|ai_*
    -- 보고 시점의 수준에서 필수였는가(기록). **지금 필수인지는 이 값으로 판단하지
    -- 않는다** — Case 의 현재 수준에서 도출한다(repository.effective_required_sections).
    -- 사람이 수준을 올리면 이미 있는 산출물도 부족해져야 하기 때문이다.
    required       INTEGER NOT NULL,
    PRIMARY KEY (preparation_id, section)
);

-- 단계별 검토 설정. **행이 없으면 사람 검토다**(D-14 프로젝트 기본값).
-- 없음을 자동 진행으로 읽으면 기본값이 조용히 뒤집힌다.
CREATE TABLE IF NOT EXISTS stage_review_setting (
    case_id        TEXT NOT NULL REFERENCES "case"(id),
    stage          TEXT NOT NULL,
    mode           TEXT NOT NULL,   -- human_review | auto_proceed
    set_by         TEXT NOT NULL,
    reason_summary TEXT NOT NULL,
    set_at         TEXT NOT NULL,
    PRIMARY KEY (case_id, stage),
    CHECK (length(reason_summary) <= 200)
);

-- 단계 검토 기록. **자동 진행을 사람 승인으로 적지 않는다.**
--
-- `decision_id` 는 **사람 검토에만** 채운다. 자동 진행이 `decision` 행을 만들면
-- 그것이 곧 "사람 승인 기록 생성"이 된다(sizing-and-review-ux 2절).
-- `subject_content_hash` 는 검토한 원문을 고정한다 — 내용이 바뀌면 새 산출물
-- 행이 생기고 이 검토는 그 새 산출물에 적용되지 않는다.
CREATE TABLE IF NOT EXISTS stage_review (
    id                   TEXT PRIMARY KEY,
    case_id              TEXT NOT NULL REFERENCES "case"(id),
    stage                TEXT NOT NULL,
    preparation_id       TEXT NOT NULL REFERENCES preparation_artifact(id),
    mode                 TEXT NOT NULL,   -- human_review | auto_proceed
    state                TEXT NOT NULL,   -- human_reviewed | auto_conditions_met
    decision_id          TEXT REFERENCES decision(id),  -- 사람 검토만 채운다
    actor                TEXT NOT NULL,
    subject_content_hash TEXT NOT NULL,
    note_summary         TEXT NOT NULL,
    recorded_at          TEXT NOT NULL,
    UNIQUE (preparation_id),
    CHECK (length(note_summary) <= 200)
);

-- 실행에 고정한 참조 목록. **본문 없음.**
--
-- review-context-contract 2절: "전체 대화 복사본 대신 필수 핵심 정보 +
-- 버전이 고정된 참조 목록". 이 표가 P2-04의 위험 1(재작성이 이전 버전을 보지
-- 못해 산출물이 퇴화하는 문제)을 해소하는 지점이다. 무엇을 보여 줬는지가
-- 기록으로 남아야 나중에 "그 실행이 무엇을 읽었는가"를 답할 수 있다.
CREATE TABLE IF NOT EXISTS run_context_ref (
    run_id      TEXT NOT NULL REFERENCES run(run_id),
    seq         INTEGER NOT NULL,
    role        TEXT NOT NULL,   -- previous_intent | agreed_intent | current_design | ...
    artifact_id TEXT NOT NULL,
    revision    INTEGER NOT NULL,
    PRIMARY KEY (run_id, seq),
    FOREIGN KEY (artifact_id, revision) REFERENCES artifact_ref(artifact_id, revision)
);

CREATE INDEX IF NOT EXISTS idx_sizing_case ON sizing_assessment(case_id, state);
CREATE INDEX IF NOT EXISTS idx_preparation_case
    ON preparation_artifact(case_id, stage, state);
CREATE INDEX IF NOT EXISTS idx_stage_review_case ON stage_review(case_id, stage);
CREATE INDEX IF NOT EXISTS idx_run_context_run ON run_context_ref(run_id);

-- ===================================================================
-- 스키마 v6 (P3-02 작업 그래프·질문)
--
-- 같은 저장 경계 규칙이 그대로 적용된다. 아래 표에도 **본문 컬럼은 없다.**
-- Task 의 목적·산출물·완료 조건 서술은 개발계획 원문 안에 있고 여기에는 짧은
-- 요약·종류·순서·상태와 참조만 남는다.
--
-- **Task 의 완료 상태는 컬럼이 아니다.** 그 `task_key` 의 실행 결과에서 도출한다.
-- 사람이 "끝났다"고 적는 경로를 만들면 실행 증거 없이 의존을 푸는 문이 된다
-- (FR-09 "미실행을 실행·통과로 표시하지 않는다").
--
-- **그래프는 리비전 단위로 통째로 바뀐다.** Task 행을 그 자리에서 고치지 않는다 —
-- 고치면 "그때 무엇이 유효했는가"를 답할 수 없고 실행 기록이 가리키는 계획이
-- 사라진다(FR-07 "변경 이유와 현재 유효한 계획을 남긴다").
-- ===================================================================

-- 작업 그래프 리비전. 현재 유효한 계획은 항상 하나다.
--
-- `intent_version_id` 가 오래된 그래프를 막는 지점이다. 설계·계획과 같은 규칙이며,
-- 새 의도 버전이 생기면 그 위에 세운 그래프는 `stale` 이 된다.
CREATE TABLE IF NOT EXISTS work_graph_revision (
    id                  TEXT PRIMARY KEY,
    case_id             TEXT NOT NULL REFERENCES "case"(id),
    revision            INTEGER NOT NULL,
    intent_version_id   TEXT NOT NULL REFERENCES intent_version(id),
    plan_preparation_id TEXT NOT NULL REFERENCES preparation_artifact(id),
    source              TEXT NOT NULL,   -- plan_artifact | human_replanning
    -- 왜 바뀌었는가. 첫 리비전도 비워 두지 않는다.
    reason_summary      TEXT NOT NULL,
    actor               TEXT NOT NULL,
    state               TEXT NOT NULL,   -- current | superseded
    created_at          TEXT NOT NULL,
    superseded_at       TEXT,
    UNIQUE (case_id, revision),
    CHECK (length(reason_summary) <= 200)
);

-- Task. **본문 컬럼 없음.**
--
-- `task_key` 가 리비전을 가로지르는 식별자다. 행 id 는 리비전마다 새로 생기지만
-- 키는 남으므로 **재분할이 실행 이력을 초기화하지 않는다**(FR-07 수용 기준).
-- `run.task_id` 에 들어가는 값도 이 키다.
CREATE TABLE IF NOT EXISTS task (
    id                 TEXT PRIMARY KEY,
    case_id            TEXT NOT NULL REFERENCES "case"(id),
    graph_revision_id  TEXT NOT NULL REFERENCES work_graph_revision(id),
    task_key           TEXT NOT NULL,
    kind               TEXT NOT NULL,   -- investigation|implementation|verification|experiment|integration
    -- 연결된 의도 항목(goal|expected_outcome|scope|...). 없으면 빈 문자열.
    relates_to         TEXT NOT NULL,
    summary            TEXT NOT NULL,   -- 목적의 짧은 요약. 원문 대체 아님
    deliverable_summary TEXT NOT NULL,  -- 산출물의 짧은 요약. 원문 대체 아님
    completion_summary  TEXT NOT NULL,  -- 완료 조건의 짧은 요약. 원문 대체 아님
    order_index        INTEGER NOT NULL,
    origin             TEXT NOT NULL,   -- none|user_requirement|project_rule|observation|ai_*
    -- 이 리비전에서 취소됐는가. 취소된 Task 는 **지우지 않는다** — 무엇이 있었고
    -- 왜 빠졌는지가 남아야 한다.
    cancelled          INTEGER NOT NULL DEFAULT 0,
    cancel_reason      TEXT NOT NULL DEFAULT '',
    created_at         TEXT NOT NULL,
    UNIQUE (graph_revision_id, task_key),
    CHECK (length(summary) <= 200),
    CHECK (length(deliverable_summary) <= 200),
    CHECK (length(completion_summary) <= 200),
    CHECK (length(cancel_reason) <= 200)
);

-- 의존 관계. `task_key` 는 `depends_on_key` 가 완료된 뒤에 실행할 수 있다.
-- 순환은 `controller/work_graph.py` 가 리비전을 만들 때 거부한다.
CREATE TABLE IF NOT EXISTS task_dependency (
    graph_revision_id TEXT NOT NULL REFERENCES work_graph_revision(id),
    task_key          TEXT NOT NULL,
    depends_on_key    TEXT NOT NULL,
    PRIMARY KEY (graph_revision_id, task_key, depends_on_key),
    FOREIGN KEY (graph_revision_id, task_key)
        REFERENCES task(graph_revision_id, task_key),
    FOREIGN KEY (graph_revision_id, depends_on_key)
        REFERENCES task(graph_revision_id, task_key),
    CHECK (task_key <> depends_on_key)
);

-- Task 와 성공 기준의 연결(FR-06·FR-07).
--
-- **현재 의도 버전의 기준만 받는다.** 성공 기준은 의도 버전에 묶여 있고 새 버전은
-- 기준을 승계하지 않으므로(스키마 v4), 옛 기준을 가리키는 연결을 받아 두면
-- 대체된 기준이 새 그래프에 그대로 붙는다.
CREATE TABLE IF NOT EXISTS task_criterion (
    graph_revision_id TEXT NOT NULL REFERENCES work_graph_revision(id),
    task_key          TEXT NOT NULL,
    criterion_id      TEXT NOT NULL REFERENCES success_criterion(id),
    relation          TEXT NOT NULL,   -- implements | verifies
    PRIMARY KEY (graph_revision_id, task_key, criterion_id, relation),
    FOREIGN KEY (graph_revision_id, task_key)
        REFERENCES task(graph_revision_id, task_key)
);

-- 어떤 사람 결정이 어떤 Task 를 막는가(intent-artifacts 3절 "결정을 기다리는
-- 작업과 차단 관계", FR-13 "답변 의존 작업과 독립 작업을 구분한다").
--
-- **연결이 없는 열린 이월 질문은 전부 막는다.** 그 규칙은 이 표의 부재로
-- 표현되며 `controller/work_graph.py` 가 판정한다 — 행이 없다는 것을 "막을 것이
-- 없다"로 읽으면 좁히기가 곧 우회가 된다.
CREATE TABLE IF NOT EXISTS task_question_block (
    graph_revision_id TEXT NOT NULL REFERENCES work_graph_revision(id),
    question_id       TEXT NOT NULL REFERENCES intent_question(id),
    task_key          TEXT NOT NULL,
    PRIMARY KEY (graph_revision_id, question_id, task_key),
    FOREIGN KEY (graph_revision_id, task_key)
        REFERENCES task(graph_revision_id, task_key)
);

-- 해석되지 않은 `blocks` 참조. **조용히 버리지 않는다.**
--
-- 산출물 원문의 `blocks` 는 자유 문자열이라 존재하지 않는 Task 를 가리킬 수 있다.
-- 그것을 버리면 "이 질문은 아무 것도 막지 않는다"가 되어 버린다. 남겨 두고 그
-- 질문을 **연결 없는 질문**으로 취급한다(= 전부 막는다).
CREATE TABLE IF NOT EXISTS task_block_unresolved (
    graph_revision_id TEXT NOT NULL REFERENCES work_graph_revision(id),
    question_id       TEXT NOT NULL REFERENCES intent_question(id),
    raw_ref           TEXT NOT NULL,
    PRIMARY KEY (graph_revision_id, question_id, raw_ref),
    CHECK (length(raw_ref) <= 200)
);

-- 산출물 원문이 적은 `blocks` 참조. **자유 문자열 그대로 남긴다.**
--
-- 설계 단계의 질문도 계획이 정의할 Task 를 가리킬 수 있는데, 그 Task 는 질문이
-- 제기되는 시점에 아직 없다. 그래서 참조를 **해석하지 않고 먼저 보관**하고,
-- 그래프를 만들 때 그 리비전의 Task 키로 해석한다.
--
-- 여기 들어오는 것은 Task 키를 가리키는 **식별자**이며 질문 본문이 아니다.
-- 길이 상한을 두어 본문을 밀어 넣지 못하게 한다.
CREATE TABLE IF NOT EXISTS question_block_ref (
    question_id TEXT NOT NULL REFERENCES intent_question(id),
    raw_ref     TEXT NOT NULL,
    PRIMARY KEY (question_id, raw_ref),
    CHECK (length(raw_ref) <= 200)
);

CREATE INDEX IF NOT EXISTS idx_work_graph_case ON work_graph_revision(case_id, state);
CREATE INDEX IF NOT EXISTS idx_task_graph ON task(graph_revision_id, order_index);
CREATE INDEX IF NOT EXISTS idx_task_case_key ON task(case_id, task_key);

-- =========================================================== P3-03 작업공간·실행
--
-- **본문 컬럼이 없다.** 코드·diff·명령 원문·빌드 로그는 Runner 의 산출물에 있고
-- 여기에는 식별자(SHA·경로·브랜치)와 수, 짧은 요약만 온다(D-43·NFR-12).
--
-- 경로와 브랜치 이름은 **식별자**다. 어느 파일이 어떻게 바뀌었는지는 여기 없다 —
-- 변경은 수(파일 수·삽입·삭제)와 HEAD SHA 로만 남고 상세는 원문 조회로 본다.

-- Case 하나의 전용 작업공간(FR-08·FR-26, D-39).
--
-- 실제 git 작업은 **저장소를 가진 Runner** 가 한다. 제어부가 직접 git 을 부르면
-- 단일 호스트에서만 동작하고 서버+PC 배치(FR-27)에서 무너진다. 그래서 이 표는
-- "요청"과 "Runner 가 보고한 결과"를 함께 담는다.
-- **v9(P3-R2)에서 기본 키가 `(case_id, repository_id)` 로 바뀌었다.** Case 하나가
-- 여러 저장소를 선택할 수 있고 저장소마다 브랜치·worktree·시작 기준이 따로 있다
-- (D-39). 옛 행은 Project 의 이행된 저장소에 연결되며 브랜치·기준 커밋·worktree
-- 경로는 그대로 남는다 — 옮기면 이미 한 작업이 떨어져 나간다.
CREATE TABLE IF NOT EXISTS case_workspace (
    case_id           TEXT NOT NULL REFERENCES "case"(id),
    -- 어느 저장소의 작업공간인가. v9 이전 행은 이행이 채운다.
    repository_id     TEXT NOT NULL REFERENCES project_repository(id),
    project_id        TEXT NOT NULL REFERENCES project(id),
    state             TEXT NOT NULL,          -- requested | ready | failed
    branch            TEXT NOT NULL,          -- 전용 브랜치 이름(제어부가 정한다)
    -- **무엇을 근거로 이 작업공간을 만들었는가**(P3-R2).
    --   `case_repository`             Case 가 그 저장소를 선택하고 쓰기를 허용했다
    --   `implicit_single_repository`  선택 기록이 없는 이행된 Case 다. 없던 선택을
    --                                 지어내지 않고 허용의 출처를 그대로 남긴다
    allowance_source  TEXT NOT NULL DEFAULT '',
    -- 아래는 Runner 가 실제로 만든 뒤 보고하는 값. 요청 시점에는 비어 있다.
    runner_id         TEXT REFERENCES runner(id),
    repo_path         TEXT NOT NULL DEFAULT '',  -- Runner 호스트에서 해석된 저장소
    worktree_path     TEXT NOT NULL DEFAULT '',  -- 이 Case 의 작업 파일이 있는 곳
    base_commit       TEXT NOT NULL DEFAULT '',  -- **기준 커밋 SHA.** 커밋된 상태다
    base_ref          TEXT NOT NULL DEFAULT '',  -- 그 커밋을 고른 근거 ref
    -- 준비 시점에 관측한 **사용자의 원래 작업 트리**. 건드리지 않았다는 사실을
    -- 남기기 위한 관측값이며 파일 경로는 넣지 않는다(수만 센다).
    --
    -- **저장소마다 따로 센다.** 한 Case 가 두 저장소를 쓰면 각 저장소의 사용자
    -- 변경은 서로 다른 것이고, 하나로 합치면 어느 쪽을 보존했는지 말할 수 없다.
    user_tree_dirty   INTEGER NOT NULL DEFAULT 0,
    user_tree_entries INTEGER NOT NULL DEFAULT 0,
    failure_reason    TEXT NOT NULL DEFAULT '',
    requested_at      TEXT NOT NULL,
    ready_at          TEXT,
    PRIMARY KEY (case_id, repository_id),
    CHECK (length(failure_reason) <= 200)
);

-- 그 실행이 **무엇을 실제로 실행했는가**(FR-08 "명령·결과를 실행에 연결한다").
--
-- 명령 원문과 출력은 Runner 에 있다. 여기에는 짧은 요약과 종료 코드·소요만 온다.
-- 종료 코드가 0이 아니어도 그것은 "검증을 수행했고 실패했다"이며 실행 실패와
-- 다르다 — 기준 판정의 입력이다.
CREATE TABLE IF NOT EXISTS run_command (
    run_id          TEXT NOT NULL REFERENCES run(run_id),
    seq             INTEGER NOT NULL,
    command_summary TEXT NOT NULL,           -- 짧은 요약. 원문 대체 아님
    exit_code       INTEGER,                 -- NULL 은 "끝을 확인하지 못함"
    duration_ms     INTEGER,
    started_at      TEXT NOT NULL,
    PRIMARY KEY (run_id, seq),
    CHECK (length(command_summary) <= 200)
);

CREATE INDEX IF NOT EXISTS idx_case_workspace_project ON case_workspace(project_id, state);

-- ===================================================================
-- 스키마 v8 (P3-R1 정책·Profile·저장소·예산 모델)
--
-- 같은 저장 경계 규칙이 그대로 적용된다. 아래 표에도 **본문 컬럼은 없다.**
-- 정책을 바꾼 이유의 서술, Profile 항목의 내용, 예산을 정한 배경은 소유 Runner 의
-- 원문 또는 사용자의 결정 근거에 있고 여기에는 판정·값·코드·짧은 요약만 남는다.
--
-- 이 표들은 **기록**이다. 그 위에 강제가 하나씩 붙었다 — Case×Repo 작업공간과
-- 허용 내 자동 추가는 R2(v9), 예산의 예약·집계·정지는 R3(v10, `budget_reservation`).
-- **Autonomy 에 따른 실행 경로와 확인 지점은 아직 R4 다.** 행이 생겼다는 이유로
-- 그 기능을 지원한다고 표시하지 않는다.
--
-- 그리고 **행이 없는 상태의 의미가 표마다 다르다.** 한 규칙으로 통일하면 어느 한쪽이
-- 반드시 거짓이 된다.
--   `case_policy`       없음 = R1 이후 Case 의 기본값(ask-on-decision). 이행된
--                       Case 에는 `migrated_unknown` 행을 **명시로** 넣는다
--   `budget_setting`    없음 = 무제한(D-56)
--   `case_repository`   없음 = 선택이 기록되지 않음. 조회는 이행된 단일 저장소를
--                       `implicit_single_repository` 로 **따로** 표시한다
--   `controlled_checkpoint` 없음 = 요구되지 않음(ask-on-decision) 또는 아직 생성 전
-- ===================================================================

-- 이 Case 에 적용되는 Autonomy 와 그 출처. 바뀐 값은 `superseded` 로 보존한다.
--
-- `autonomy` 가 **NULL 일 수 있다.** R1 이전에 만들어진 Case 는 이 축이 기록되지
-- 않았고, 기본값으로 읽으면 v0.6에서 사람이 검토·인수하기로 하고 진행한 업무가
-- 조용히 자동 진행 대상이 된다. NULL 은 "기록되지 않음"이며 `ask_on_decision` 이
-- 아니다(DEVELOPMENT.md 3절).
CREATE TABLE IF NOT EXISTS case_policy (
    id               TEXT PRIMARY KEY,
    case_id          TEXT NOT NULL REFERENCES "case"(id),
    revision         INTEGER NOT NULL,
    autonomy         TEXT,                  -- ask_on_decision | controlled | NULL(미기록)
    autonomy_source  TEXT NOT NULL,         -- system_default | case_explicit | migrated_unknown
    policy_version   TEXT NOT NULL,         -- 이 행을 정한 규칙판. 이행 행은 "0.6"
    set_by           TEXT NOT NULL,         -- 주체. 이행 행은 "migration"
    reason_summary   TEXT,                  -- 짧은 요약. 원문 대체 아님
    state            TEXT NOT NULL,         -- current | superseded
    created_at       TEXT NOT NULL,
    superseded_at    TEXT,
    UNIQUE (case_id, revision),
    CHECK (reason_summary IS NULL OR length(reason_summary) <= 200)
);

-- 지금 무엇을 근거로 자동 진행하는가(D-60).
--
-- 위임 기준은 `최초 요청 + 사용자의 후속 명시 결정·변경 요청 + 유효한 정책` 이다.
-- **AI 초안은 근거가 아니다** — 비교 자료이며 `basis_kind` 에 값도 없다.
-- 누적 material delta 는 이 기록들과 대조해 계산한다(R4).
CREATE TABLE IF NOT EXISTS delegation_basis (
    id             TEXT PRIMARY KEY,
    case_id        TEXT NOT NULL REFERENCES "case"(id),
    revision       INTEGER NOT NULL,
    basis_kind     TEXT NOT NULL,           -- original_request | user_decision | project_policy
    artifact_id    TEXT,                    -- 원문 참조. 본문은 Runner 에
    artifact_rev   INTEGER,
    content_hash   TEXT,                    -- 그 시점 원문의 해시
    decision_id    TEXT REFERENCES decision(id),
    summary        TEXT NOT NULL,           -- 짧은 요약. 원문 대체 아님
    state          TEXT NOT NULL,           -- current | superseded
    recorded_at    TEXT NOT NULL,
    superseded_at  TEXT,
    UNIQUE (case_id, revision),
    CHECK (length(summary) <= 200)
);

-- controlled 가 요구하는 확인 지점과 실제 확인(D-65).
--
-- 확인은 **그 대상에만** 붙는다. 대상이 바뀌면 `superseded` 가 되고 새 행으로 다시
-- 확인받는다. 확인 기록을 지우지 않는 이유는 "무엇을 보고 확인했는가"가 FR-23 의
-- 요구이기 때문이다.
--
-- **이 확인이 권한을 만들지 않는다.** push·게시 허용과 최종 인수는 각각
-- `decision`·`final_acceptance` 의 별도 기록이다(D-32·D-65).
CREATE TABLE IF NOT EXISTS controlled_checkpoint (
    id               TEXT PRIMARY KEY,
    case_id          TEXT NOT NULL REFERENCES "case"(id),
    policy_id        TEXT NOT NULL REFERENCES case_policy(id),
    checkpoint       TEXT NOT NULL,         -- start_scope | result_candidate
    state            TEXT NOT NULL,         -- required | confirmed | superseded
    subject_type     TEXT,                  -- case | completion_candidate | ...
    subject_id       TEXT,
    subject_hash     TEXT,                  -- 확인한 대상의 해시
    decision_id      TEXT REFERENCES decision(id),
    confirmed_by     TEXT,
    confirmed_at     TEXT,
    note_summary     TEXT,
    created_at       TEXT NOT NULL,
    superseded_at    TEXT,
    CHECK (note_summary IS NULL OR length(note_summary) <= 200)
);

-- 선택한 예산 한도(D-56·D-61). **행이 없으면 무제한이다.**
--
-- `measurement` 와 `enforcement` 를 값과 **함께** 남기는 것이 핵심이다. 강제할 수
-- 없는 지표에 정확한 hard 한도를 걸어 두면 사람이 상한이 있다고 믿는다. 그런 설정은
-- 애초에 받지 않으며(`PolicyRefusal.HARD_LIMIT_NOT_ENFORCEABLE`) 받은 설정도
-- R1 에서는 전부 `recorded_not_enforced` 다 — 예약·집계·정지는 R3 이다.
--
-- repair 한도(D-29)는 여기 없다. 품질 수정 차수와 자원 한도는 별개이며
-- 하나가 다른 하나를 대신하지 않는다.
CREATE TABLE IF NOT EXISTS budget_setting (
    id              TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES "case"(id),
    revision        INTEGER NOT NULL,
    metric          TEXT NOT NULL,          -- run_count | input_tokens | ...
    threshold_kind  TEXT NOT NULL,          -- warn | hard
    limit_value     REAL NOT NULL,
    unit            TEXT NOT NULL,
    measurement     TEXT NOT NULL,          -- exact | estimated | unavailable
    enforcement     TEXT NOT NULL,          -- recorded_not_enforced | not_enforceable
    enforced_by     TEXT NOT NULL,          -- 어느 하위 작업이 실제로 강제하는가
    policy_version  TEXT NOT NULL,
    set_by          TEXT NOT NULL,
    reason_summary  TEXT,
    state           TEXT NOT NULL,          -- current | superseded
    created_at      TEXT NOT NULL,
    superseded_at   TEXT,
    UNIQUE (case_id, revision),
    CHECK (limit_value > 0),
    CHECK (reason_summary IS NULL OR length(reason_summary) <= 200)
);

-- Project 에 등록된 저장소들(D-38·FR-01).
--
-- v1의 `project.repo_path` 를 대체한다. 그 컬럼은 **지우지 않는다** — 기존 배정·
-- 작업공간 경로가 그 값을 쓰고 있고, 이행은 같은 값을 이 표에 한 건으로 옮기는
-- 것으로 한다(`source = migrated_from_project`).
CREATE TABLE IF NOT EXISTS project_repository (
    id             TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL REFERENCES project(id),
    name           TEXT NOT NULL,
    repo_path      TEXT NOT NULL,           -- Runner 호스트에서 해석하는 경로
    source         TEXT NOT NULL,           -- registered | migrated_from_project
    registered_by  TEXT NOT NULL,
    registered_at  TEXT NOT NULL,
    UNIQUE (project_id, name),
    CHECK (length(name) <= 100)
);

-- Case 가 선택한 저장소와 허용 범위(D-63·D-64·FR-01).
--
-- **세 가지가 서로 다른 집합이다.** 선택했다는 것, 코드를 바꿔도 된다는 것, 외부에
-- 게시해도 된다는 것. 쓰기 허용만으로 게시 허용이 생기지 않는다(D-64 "쓰기 허용
-- 저장소 추가는 게시 허용 확대가 아니다").
--
-- `selection_source = excluded` 는 **명시적으로 제외한** 저장소다. 행이 없는 것과
-- 다르다 — 없음은 아직 판단하지 않은 것이고, 제외는 R2 의 자동 추가가 건드리지
-- 못하는 경계다.
CREATE TABLE IF NOT EXISTS case_repository (
    case_id            TEXT NOT NULL REFERENCES "case"(id),
    repository_id      TEXT NOT NULL REFERENCES project_repository(id),
    selection_source   TEXT NOT NULL,       -- explicit | auto_in_allowance | excluded
    code_write_allowed INTEGER NOT NULL,    -- 0/1. 작업공간 준비는 R2
    publish_allowed    INTEGER NOT NULL,    -- 0/1. 실제 push·PR 은 P5
    selected_by        TEXT NOT NULL,
    reason_summary     TEXT,
    state              TEXT NOT NULL,       -- current | superseded
    selected_at        TEXT NOT NULL,
    superseded_at      TEXT,
    PRIMARY KEY (case_id, repository_id),
    CHECK (reason_summary IS NULL OR length(reason_summary) <= 200)
);

CREATE INDEX IF NOT EXISTS idx_case_policy_case ON case_policy(case_id, state);
CREATE INDEX IF NOT EXISTS idx_delegation_case ON delegation_basis(case_id, state);
CREATE INDEX IF NOT EXISTS idx_checkpoint_case ON controlled_checkpoint(case_id, state);
CREATE INDEX IF NOT EXISTS idx_budget_case ON budget_setting(case_id, state);
CREATE INDEX IF NOT EXISTS idx_project_repository ON project_repository(project_id);
CREATE INDEX IF NOT EXISTS idx_case_repository_case ON case_repository(case_id, state);

-- ===================================================================
-- 스키마 v9 (P3-R2 Case × Repository 작업공간·코드 조합)
--
-- 같은 저장 경계 규칙이 그대로 적용된다. **본문 컬럼은 없다.** 아래의
-- `tree_digest` 는 그 시점 작업 트리 내용의 **지문(해시)** 이며
-- `artifact_ref.content_hash` 와 같은 성격이다 — 파일 경로도 diff 본문도 아니다.
--
-- R2 가 강제하는 것과 강제하지 않는 것을 구별한다. 저장소 **선택·쓰기 허용**은 이제
-- 작업공간을 만들 수 있는지를 실제로 정한다. **게시 허용**은 여전히 기록일 뿐이고
-- 실제 push·PR·기록 이슈는 P5 다. 조합이 생겼다는 이유로 외부 반영을 지원한다고
-- 표시하지 않는다.
-- ===================================================================

-- 이 Case 의 **코드 조합**(execution-workspace-review 2.1절).
--
-- 왜 필요한가. 저장소가 여럿이면 "무엇을 검증했는가"를 브랜치 이름이나 파일 경로로
-- 말할 수 없다. 움직이는 이름이 아니라 `Repo ID → 정확한 스냅샷 참조` 의 벡터로
-- 대상을 고정해야 나중에 그 근거가 아직 유효한지 답할 수 있다.
--
-- 조합은 **기존 기록에서 만든다.** 새 관측을 요구하지 않으며, 관측이 없는 저장소는
-- 기준 커밋만 담고 `snapshot_incomplete` 로 표시한다 — 기준 커밋만으로 실제 입력을
-- 설명할 수 없다는 사실을 값으로 남기는 것이다.
CREATE TABLE IF NOT EXISTS code_composition (
    id            TEXT PRIMARY KEY,
    case_id       TEXT NOT NULL REFERENCES "case"(id),
    revision      INTEGER NOT NULL,
    -- 항목을 저장소 순으로 정렬해 만든 지문. 같은 상태면 같은 값이고, 그때는 새
    -- revision 을 만들지 않는다.
    composition_hash TEXT NOT NULL,
    -- 이 조합이 이 Case 의 쓰기 허용 저장소를 **전부** 담았는가. 담지 않았다면
    -- 개별 저장소 검사가 모두 통과해도 통합 조건을 충족했다고 보지 않는다.
    covers_all_code_repositories INTEGER NOT NULL DEFAULT 0,
    state         TEXT NOT NULL,          -- current | superseded
    created_at    TEXT NOT NULL,
    superseded_at TEXT,
    UNIQUE (case_id, revision)
);

-- 조합의 저장소별 항목. **식별자와 수, 지문만 있다.**
CREATE TABLE IF NOT EXISTS code_composition_entry (
    composition_id TEXT NOT NULL REFERENCES code_composition(id),
    repository_id  TEXT NOT NULL REFERENCES project_repository(id),
    base_commit    TEXT NOT NULL,          -- 시작 기준. 커밋된 상태다
    head_commit    TEXT NOT NULL DEFAULT '',   -- 관측된 HEAD. 없으면 빈 문자열
    dirty_entries  INTEGER,                -- 미커밋·미추적 **수**. NULL 은 미관측
    tree_digest    TEXT NOT NULL DEFAULT '',   -- 그 시점 트리 내용의 지문(해시)
    -- 이 항목을 무엇으로 채웠는가.
    --   `run_effect`      실행이 실제로 관측했다. HEAD·미커밋까지 고정된다
    --   `workspace_base`  관측이 없다. 기준 커밋만 있고 지금 상태는 **모른다**
    source         TEXT NOT NULL,
    observed_run_id TEXT REFERENCES run(run_id),
    observed_at    TEXT,
    PRIMARY KEY (composition_id, repository_id)
);

CREATE INDEX IF NOT EXISTS idx_composition_case ON code_composition(case_id, state);

-- ===================================================================
-- 스키마 v10 (P3-R3 예산 예약·집계·정지)
--
-- 기존 표의 컬럼을 **하나도 바꾸지 않는다.** 새 표 하나와 그 표를 채우는 이행이
-- 전부다. 예산 강제는 판정이지 저장 구조의 재설계가 아니다.
--
-- **집계의 출처는 이 표 하나다.** `run` 표에서 따로 세고 여기서도 세면 두 수가
-- 갈라지고, 갈라지면 어느 쪽이 한도인지 아무도 말할 수 없다. 그래서 v10 이행이
-- 기존 실행에도 행을 만든다(`source = migrated_from_run`) — 스키마를 올리는 것만으로
-- 소비가 0 이 되면 "세션·Task 분할로 초기화하지 않는다"(D-61)가 이행에서 깨진다.
--
-- 없음의 뜻:
--   `budget_reservation` 행이 없는 Run = R3 이행 대상이 아닌 실행(있을 수 없다).
--                       이행이 모든 기존 Run 에 행을 만들기 때문이다
--   `actual_value IS NULL` = **아직 모른다.** 0 이 아니다(D-61 "미제공을 0으로
--                       기록하지 않는다")
-- ===================================================================

-- 한 실행이 잡아 둔 예산 한 건. 배정 **전에** 잡고 종료 후 정산한다.
--
-- `generation` 이 키에 있는 이유: 재배정된 실행은 CLI 를 다시 부르고 그것은 새
-- 소비다(autonomy-budget-policy 7절 "재시작된 실제 AI 호출은 새 소비"). 같은
-- `run_id` 라는 이유로 두 번째 호출을 공짜로 두지 않는다.
--
-- 본문은 없다. 여기 있는 것은 수·상태·측정 방식·참조뿐이다.
CREATE TABLE IF NOT EXISTS budget_reservation (
    id               TEXT PRIMARY KEY,
    -- **누적 단위는 Case 하나다.** 역할·Task·저장소·세션으로 나뉘지 않는다(D-61).
    case_id          TEXT NOT NULL REFERENCES "case"(id),
    run_id           TEXT NOT NULL REFERENCES run(run_id),
    generation       INTEGER NOT NULL,
    metric           TEXT NOT NULL,
    -- 실행 전에 잡은 양. `open_ended`·사후 보고 지표는 NULL(=모름)이며 0 이 아니다.
    reserved_value   REAL,
    -- 정산된 실제 사용량. NULL = 아직 모른다.
    actual_value     REAL,
    measurement      TEXT NOT NULL,   -- exact | estimated | unavailable
    reservation_kind TEXT NOT NULL,   -- exact_per_run | open_ended_per_run | post_hoc_reported
    -- 역할별·목적별 집계의 축. Run 표를 다시 읽지 않고 집계하기 위해 복제한다.
    role             TEXT NOT NULL,
    purpose          TEXT NOT NULL,
    state            TEXT NOT NULL,   -- held | settled | unresolved
    source           TEXT NOT NULL,   -- reserved | migrated_from_run
    settle_source    TEXT,            -- 왜 그 값인지. 특히 **왜 모르는지**
    reserved_at      TEXT NOT NULL,
    settled_at       TEXT,
    UNIQUE (run_id, generation, metric)
);

CREATE INDEX IF NOT EXISTS idx_budget_reservation_case
    ON budget_reservation(case_id, metric, state);

-- ===================================================================
-- 스키마 v11 (P3-R4 자동 실행·진입·완료 경로)
--
-- 기존 컬럼의 뜻을 **바꾸지 않는다.** 새 표 둘과 새 컬럼 다섯이며, 도출로 충분한
-- 것은 표를 만들지 않았다 — Fast Lane 여부와 유효 Autonomy 는 기록된 사실에서
-- 계산한다(R3 의 `stop` 과 같은 판단: 저장하면 "누가 그 값을 적었는가"가 새 문제가
-- 된다).
--
-- 없음의 뜻:
--   `conformance_check` 행이 없다 = 요청 정합성을 **아직 확인하지 않았다.**
--                       게이트는 `not_run` 이며 자동으로 통과하지 않는다
--   `material_delta` 행이 없다 = 마지막 유효 위임 이후 관측된 변경이 없다
--   `criterion_result.satisfaction IS NULL` = R4 이전 기록. **`changed_and_verified`
--                       로 채우지 않는다** — 어떻게 충족했는지 그때는 묻지 않았다
--   `completion_policy.source IS NULL` = R4 이전에 명시 설정된 행. 도출값이 덮지 않는다
-- ===================================================================

-- 마지막 유효 위임 이후 관측된 변경 한 건(D-60).
--
-- **비교 대상이 `basis_id` 인 것이 이 표의 핵심이다.** AI 가 직전에 쓴 초안과
-- 비교하면 작은 변경을 연속 채택해 원래 요청과 다른 결과로 이동할 수 있다
-- (autonomy-budget-policy 3절). 그래서 기준은 `delegation_basis` 의 행이고,
-- `pending` 이 **쌓인다**.
--
-- `ai_assessment` 는 AI 의 의미 평가를 적어 두는 자리다. **이것만으로 `pending` 이
-- 풀리지 않는다** — "'의미가 같음'이라는 주장만으로 새 의미를 승인하지 않는다".
-- 풀리는 경로는 사람의 확인(`decision_id`)과 사용자 지시(`user_directed`) 둘이다.
--
-- 본문은 없다. 해시·출처·분류·참조뿐이다.
CREATE TABLE IF NOT EXISTS material_delta (
    id             TEXT PRIMARY KEY,
    case_id        TEXT NOT NULL REFERENCES "case"(id),
    -- 무엇과 비교했는가. NULL = 위임 기준이 기록되지 않은 Case
    basis_id       TEXT REFERENCES delegation_basis(id),
    change_class   TEXT NOT NULL,   -- intent_field | success_criterion | repository_allowance
    target_type    TEXT NOT NULL,
    target_id      TEXT,
    target_key     TEXT NOT NULL,
    from_hash      TEXT,
    to_hash        TEXT,
    origin         TEXT,            -- 바뀐 항목의 출처(ContentOrigin)
    materiality    TEXT NOT NULL,   -- material | user_directed | draft_work
    state          TEXT NOT NULL,   -- pending | confirmed | adopted | superseded
    detail         TEXT NOT NULL,   -- 왜 그 분류인지. 짧은 설명
    ai_assessment  TEXT,            -- AI 의 의미 평가. **해소 근거가 아니다**
    decision_id    TEXT REFERENCES decision(id),
    detected_at    TEXT NOT NULL,
    resolved_at    TEXT,
    resolution_source TEXT,         -- human_confirmation | user_direction | superseded
    CHECK (length(detail) <= 200),
    CHECK (ai_assessment IS NULL OR length(ai_assessment) <= 200)
);

CREATE INDEX IF NOT EXISTS idx_material_delta_case
    ON material_delta(case_id, state, materiality);

-- 요청 정합성 확인 한 건(D-25·QG-01).
--
-- **방식과 결과를 따로 적는다.** `method` 가 무엇을 실제로 했는지이고
-- `required_method` 가 규칙이 요구한 것이다. 둘이 어긋나면(light 를 했는데 규칙은
-- independent 를 요구) 그 확인은 충분하지 않으며 게이트가 통과하지 않는다.
--
-- `unverified_scope` 가 **가벼운 확인이 보지 않은 것**을 값으로 남긴다. 이 컬럼이
-- 없으면 두 방식이 같은 `pass` 로 보이고, 그 순간 "미실행을 통과로 표시하지 않는다"
-- (D-25)가 깨진다.
CREATE TABLE IF NOT EXISTS conformance_check (
    id                TEXT PRIMARY KEY,
    case_id           TEXT NOT NULL REFERENCES "case"(id),
    intent_version_id TEXT NOT NULL REFERENCES intent_version(id),
    method            TEXT NOT NULL,   -- light | independent
    required_method   TEXT NOT NULL,   -- 규칙이 요구한 방식
    verdict           TEXT NOT NULL,   -- pass | fail | hold | not_run
    -- 독립 검토의 실행. 가벼운 확인은 NULL 이며 그것이 두 방식을 가르는 사실이다.
    run_id            TEXT REFERENCES run(run_id),
    subject_content_hash TEXT NOT NULL,
    unverified_scope  TEXT,
    reasons_json      TEXT NOT NULL DEFAULT '[]',
    recorded_at       TEXT NOT NULL,
    UNIQUE (intent_version_id, method),
    CHECK (unverified_scope IS NULL OR length(unverified_scope) <= 300)
);

CREATE INDEX IF NOT EXISTS idx_conformance_case ON conformance_check(case_id);

-- ===================================================================
-- 스키마 v12 (P3-04 수직 통합)
--
-- **새 표가 없다.** `task` 에 컬럼 둘을 더할 뿐이며 기존 컬럼의 뜻은 바뀌지 않는다.
--
-- 설계는 처음부터 이것을 요구했다 — "Task·Run이 사용하는 Repo와 작업공간을
-- 명시한다"(execution-workspace-review 19행). R2 가 `run.repository_id` 로 실행
-- 쪽을 채웠고 Task 쪽이 비어 있었다. 저장소가 하나뿐인 동안에는 그 빈칸이 보이지
-- 않았지만, 두 저장소를 **함께 바꾸는** 업무에서는 "UI 작업을 한다면서 API 저장소를
-- 고치는 실행"이 조용히 통과한다. 실행 전후 대조가 우리가 가진 유일한 증거인데
-- 그 대조가 엉뚱한 Task 에 붙는다.
--
-- 없음의 뜻:
--   `repository_id IS NULL`   **미기록.** "주 저장소"가 아니다. v12 이전 Task 와
--                             계획이 저장소를 말하지 않은 Task 가 이 값이다.
--                             작업공간에서 유도해 채우지 않는다 — 없던 계획의
--                             판단을 만드는 일이다(D-62).
--   `repository_ref = ''`     계획이 아무 것도 적지 않았다
--   `repository_ref <> ''` 이고 `repository_id IS NULL`
--                             계획이 적었는데 **해석되지 않았다.** 조용히 버리지
--                             않는 이유는 `task_block_unresolved` 와 같다 —
--                             버리면 "저장소를 말하지 않은 계획"과 "선택 밖
--                             저장소를 가리킨 계획"이 같은 모양이 된다
-- ===================================================================

-- (아래 두 컬럼은 `controller/db.py` 의 `_add_column_if_missing` 이 기존 DB 에
--  더한다. 새로 만드는 DB 는 위 `CREATE TABLE task` 가 만들지 않으므로 같은
--  경로로 더해진다 — 한 곳에서만 정의하기 위해서다.)

-- ===================================================================
-- 스키마 v13 (P4-01 게이트·repair)
--
-- v3의 `gate_result`는 QG-01/intent_version 전용 기록이라 그대로 둔다. 아래 표는
-- QG-02~07의 논리적 채택 경계와 Case/Task 정책, 같은 경계의 repair 누적을 담는다.
-- 본문·코드·diff·로그는 없고 참조·해시·짧은 요약만 저장한다.
-- ===================================================================

CREATE TABLE IF NOT EXISTS quality_gate_policy (
    id                TEXT PRIMARY KEY,
    case_id           TEXT NOT NULL REFERENCES "case"(id),
    task_key          TEXT NOT NULL DEFAULT '',
    gate              TEXT NOT NULL,
    revision          INTEGER NOT NULL,
    setting           TEXT NOT NULL,  -- on | off | inherit
    inspection        TEXT,           -- rule | light | independent | NULL(추천 따름)
    repair_limit      INTEGER,        -- NULL = 기본 2
    source            TEXT NOT NULL,  -- case_explicit | task_explicit
    set_by            TEXT NOT NULL,
    reason_summary    TEXT NOT NULL,
    state             TEXT NOT NULL,  -- current | superseded
    created_at        TEXT NOT NULL,
    superseded_at     TEXT,
    UNIQUE (case_id, task_key, gate, revision),
    CHECK (length(task_key) <= 120),
    CHECK (length(reason_summary) <= 200),
    CHECK (repair_limit IS NULL OR repair_limit >= 0)
);

CREATE INDEX IF NOT EXISTS idx_quality_gate_policy_current
    ON quality_gate_policy(case_id, task_key, gate, state);

CREATE TABLE IF NOT EXISTS quality_gate_run (
    id                 TEXT PRIMARY KEY,
    case_id            TEXT NOT NULL REFERENCES "case"(id),
    task_key           TEXT NOT NULL DEFAULT '',
    gate               TEXT NOT NULL,
    subject_key        TEXT NOT NULL,
    input_hash         TEXT NOT NULL,
    policy_fingerprint TEXT NOT NULL,
    inspection_required TEXT NOT NULL,
    inspection_used    TEXT NOT NULL,
    status             TEXT NOT NULL, -- running | completed | blocked
    verdict            TEXT NOT NULL,
    validity           TEXT NOT NULL, -- current | needs_recheck | historical
    context_refs_json  TEXT NOT NULL,
    criteria_refs_json TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    author_run_id      TEXT REFERENCES run(run_id),
    reviewer_run_id    TEXT REFERENCES run(run_id),
    author_session_ref TEXT,
    reviewer_session_ref TEXT,
    created_at         TEXT NOT NULL,
    completed_at       TEXT,
    CHECK (length(task_key) <= 120),
    CHECK (length(subject_key) <= 160),
    CHECK (length(input_hash) <= 128),
    CHECK (author_session_ref IS NULL OR length(author_session_ref) <= 200),
    CHECK (reviewer_session_ref IS NULL OR length(reviewer_session_ref) <= 200)
);

CREATE INDEX IF NOT EXISTS idx_quality_gate_run_subject
    ON quality_gate_run(case_id, gate, subject_key, created_at);

CREATE TABLE IF NOT EXISTS quality_gate_finding (
    id                   TEXT PRIMARY KEY,
    gate_run_id          TEXT NOT NULL REFERENCES quality_gate_run(id),
    finding_key          TEXT NOT NULL,
    criterion            TEXT NOT NULL,
    severity             TEXT NOT NULL, -- required | advisory
    blocking             INTEGER NOT NULL,
    certainty            TEXT NOT NULL, -- confirmed | suspected
    target               TEXT NOT NULL,
    summary              TEXT NOT NULL,
    evidence_artifact_id TEXT,
    state                TEXT NOT NULL, -- open | resolved | dismissed
    created_at           TEXT NOT NULL,
    UNIQUE (gate_run_id, finding_key),
    CHECK (length(finding_key) <= 120),
    CHECK (length(criterion) <= 120),
    CHECK (length(target) <= 120),
    CHECK (length(summary) <= 200),
    CHECK (evidence_artifact_id IS NULL OR length(evidence_artifact_id) <= 160)
);

CREATE TABLE IF NOT EXISTS remediation_cycle (
    id                  TEXT PRIMARY KEY,
    case_id             TEXT NOT NULL REFERENCES "case"(id),
    gate                TEXT NOT NULL,
    subject_key         TEXT NOT NULL,
    task_key            TEXT NOT NULL DEFAULT '',
    initial_gate_run_id TEXT NOT NULL REFERENCES quality_gate_run(id),
    repair_limit        INTEGER NOT NULL,
    used_attempts       INTEGER NOT NULL DEFAULT 0,
    reserved_attempts   INTEGER NOT NULL DEFAULT 0,
    state               TEXT NOT NULL, -- active | passed | exhausted
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (case_id, gate, subject_key),
    CHECK (length(subject_key) <= 160),
    CHECK (length(task_key) <= 120),
    CHECK (repair_limit >= 0),
    CHECK (used_attempts >= 0),
    CHECK (reserved_attempts >= 0)
);

CREATE TABLE IF NOT EXISTS remediation_attempt (
    id                  TEXT PRIMARY KEY,
    cycle_id            TEXT NOT NULL REFERENCES remediation_cycle(id),
    sequence_no         INTEGER NOT NULL,
    repair_no           INTEGER,
    kind                TEXT NOT NULL, -- product_repair | environment_recovery
    task_key            TEXT NOT NULL DEFAULT '',
    session_ref         TEXT,
    author_run_id       TEXT REFERENCES run(run_id),
    verification_run_id TEXT REFERENCES run(run_id),
    state               TEXT NOT NULL, -- reserved | completed | abandoned
    outcome             TEXT,
    started_at          TEXT NOT NULL,
    completed_at        TEXT,
    UNIQUE (cycle_id, sequence_no),
    UNIQUE (cycle_id, repair_no),
    CHECK (length(task_key) <= 120),
    CHECK (session_ref IS NULL OR length(session_ref) <= 200)
);

CREATE INDEX IF NOT EXISTS idx_remediation_attempt_cycle
    ON remediation_attempt(cycle_id, sequence_no);


-- ===================================================================
-- 스키마 v14 (P4-02 변경·예약)
--
-- 게이트 설정 변경은 진행 중 검증 1회가 끝난 뒤 반영된다(D-30). 그래서 정책 행에
-- `요청 시각`과 `적용 시각`이 따로 있고, 예약 행은 `pending` 으로 남아 유효 정책
-- 조회에 섞이지 않는다. 예약만으로 진행 중 검사를 무효화하지 않기 때문이다.
--
-- 아래 두 표는 **변경이 어떤 증거를 무효화했는가**를 남긴다. 재검증과 재사용을
-- 둘 다 기록하는 이유는, 재사용이 "아무 일도 없었다"가 아니라 **이유와 참조 버전이
-- 있는 판단**이기 때문이다(gate-operations 3절). 영향을 확인하지 못한 경우는
-- `unknown` 이며 재사용으로 적지 않는다.
--
-- 정책·실행 표에 더한 시간축 컬럼은 `db.py` 의 v14 이행이 붙인다. 기존 DB 에도
-- 같은 컬럼이 필요하기 때문이며, v12 의 `task.repository_id` 와 같은 방식이다.
-- ===================================================================

CREATE TABLE IF NOT EXISTS quality_change_event (
    id                TEXT PRIMARY KEY,
    case_id           TEXT NOT NULL REFERENCES "case"(id),
    kind              TEXT NOT NULL,  -- request | code | permission
    change_ref        TEXT NOT NULL,  -- 바뀐 대상의 참조(원문 아님)
    changed_refs_json TEXT NOT NULL,  -- 영향 계산에 쓰는 참조 목록
    scope_known       INTEGER NOT NULL DEFAULT 1,
    summary           TEXT NOT NULL,
    recorded_by       TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    CHECK (kind IN ('request', 'code', 'permission')),
    CHECK (length(change_ref) <= 160),
    CHECK (length(summary) <= 200),
    -- 참조 100개 × 160자에 JSON 구분자를 더한 상한이다. 런타임이 항목마다
    -- 검사하지만 DB 제약도 함께 둔다 — 내부 호출이 본문을 밀어 넣을 수 있는
    -- 자리를 하나만 남기지 않는다(P4-01 검토에서 고친 것과 같은 이유).
    CHECK (length(changed_refs_json) <= 17000),
    CHECK (scope_known IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_quality_change_event_case
    ON quality_change_event(case_id, created_at);

CREATE TABLE IF NOT EXISTS quality_revalidation (
    id                 TEXT PRIMARY KEY,
    change_event_id    TEXT NOT NULL REFERENCES quality_change_event(id),
    gate_run_id        TEXT NOT NULL REFERENCES quality_gate_run(id),
    decision           TEXT NOT NULL,  -- revalidate | reuse | unknown
    reason_summary     TEXT NOT NULL,
    referenced_version TEXT NOT NULL,  -- 재사용 판단이 기댄 입력 버전(해시)
    created_at         TEXT NOT NULL,
    UNIQUE (change_event_id, gate_run_id),
    CHECK (decision IN ('revalidate', 'reuse', 'unknown')),
    CHECK (length(reason_summary) <= 200),
    CHECK (length(referenced_version) <= 128)
);

CREATE INDEX IF NOT EXISTS idx_quality_revalidation_run
    ON quality_revalidation(gate_run_id, created_at);

-- ===================================================================
-- 스키마 v15 (P4-03) — 여섯 Profile 의 완료 의미
--
-- 새 표는 없다. 기준이 **무엇을 입증하는가**(목적 의무)·원인/조사 기준의 결론 요구·
-- 결과의 결론·의도의 목적 선언·후보의 목적별 충족 현황이 기존 표의 컬럼으로 붙는다.
-- 컬럼은 `db.py` 의 v15 이행이 붙인다 — 기존 DB 에도 같은 컬럼이 필요하기 때문이며
-- v11 의 `criterion_result.satisfaction` 과 같은 방식이다.
--
-- 값은 전부 열거형이고 `CHECK` 로 묶는다. 본문 자리는 없다.
-- 옛 행은 NULL 이며 그것은 "Profile 정의 v1 로 만들어졌다"이다. 도출해 채우지 않는다.
-- ===================================================================
