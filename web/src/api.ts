// 제어부 API 클라이언트.
//
// 화면은 여기를 통해서만 서버와 이야기한다. 원문 본문은 이 경로로 서버에 "제출"되지만
// 서버가 보관하지 않는다. 제출 응답은 202이고 저장 완료가 아니다 —
// 소유 Runner가 저장을 보고해야 availability 가 available 이 된다.

export type Availability =
  | 'pending'
  | 'available'
  | 'runner_offline'
  | 'lost_before_persist'

export interface Project {
  id: string
  name: string
  repo_path: string
  default_tool_id: string
  created_at: string
}

export interface Case {
  id: string
  project_id: string
  title: string
  kind: string
  status: string
  created_at: string
  updated_at: string
}

export interface ArtifactRef {
  artifact_id: string
  revision: number
  kind: string
  content_hash: string
  byte_size: number
  owner_runner_id: string
  availability: Availability
  summary: string
  created_at: string
}

export interface IntentVersion {
  id: string
  revision: number
  artifact_id: string
  status: string
  created_at: string
  // **누가 실제로 썼는가.** 기록되지 않은 옛 버전은 null 이다.
  authoring_mode: 'human_typed' | 'ai_drafted' | null
  author_run_id: string | null
}

export interface Decision {
  id: string
  kind: string
  subject_type: string
  subject_id: string
  subject_revision: number
  actor: string
  decided_at: string
}

export interface RunEvent {
  seq: number
  ts: string
  type: string
  native_type: string | null
}

export interface Run {
  run_id: string
  case_id: string
  task_id: string
  purpose: RunPurpose | null
  session_ref: string | null
  role: string
  tool_id: string
  mode: string
  permission: string
  status: string
  outcome: string | null
  exit_code: number | null
  assignment_generation: number
  assigned_runner_id: string | null
  output_artifact_id: string | null
  usage: unknown
  residual_activity: string
  observed_tool_version: string | null
  created_at: string
  finished_at: string | null
  events?: RunEvent[]
}

export interface CaseDetail extends Case {
  artifacts: ArtifactRef[]
  intent_versions: IntentVersion[]
  decisions: Decision[]
  runs: Run[]
  gate: GateResult
  admission_checks: AdmissionCheck[]
  // P2-04: 기준별 결과·미정리 실행·종료 후보를 같은 응답에 담는다.
  // "지금 무엇을 기다리는가"를 다른 화면에서 찾게 하지 않는다(FR-14).
  result: ResultView
}

export interface RunnerCapability {
  tool_id: string
  mode: string
  capability: string
  state: string
  source: string
}

export interface RunnerInfo {
  id: string
  name: string
  host: string
  status: string
  last_heartbeat_at: string | null
  capabilities: RunnerCapability[]
}

/**
 * 실제로 **AI가 글을 쓰는** 도구만 고른다.
 *
 * 골격 실행기(`local-echo`)도 `installed` 는 `verified` 지만 초안을 쓰지 못한다.
 * 그것을 초안 작성에 배정하면 실행이 정상 종료하면서 아무 것도 만들어지지 않아
 * "요청했는데 아무 일도 없는" 상태가 된다. 서버도 같은 조건으로 거부하지만
 * (`tool_is_not_a_coding_cli`), 화면이 고를 수 없는 것을 보여 주지 않는 편이 낫다.
 */
export function codingCliTools(runners: RunnerInfo[]): { tool_id: string; mode: string }[] {
  const seen = new Map<string, string>()
  for (const runner of runners) {
    for (const cap of runner.capabilities) {
      if (cap.capability === 'coding_cli' && cap.state === 'verified') {
        seen.set(cap.tool_id, cap.mode)
      }
    }
  }
  return [...seen].map(([tool_id, mode]) => ({ tool_id, mode }))
}

// 서버가 구조화된 거절 사유를 주는 경우가 있다(의도 동의 거절, 진입 조건 거부).
// 화면이 그 사유를 사람에게 그대로 보여 줄 수 있도록 본문을 붙여 던진다.
export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, detail: unknown, text: string) {
    super(`${status} ${text}`)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!response.ok) {
    const text = await response.text()
    let detail: unknown = text
    try {
      detail = (JSON.parse(text) as { detail?: unknown }).detail ?? text
    } catch {
      // JSON이 아니면 원문 그대로 둔다.
    }
    throw new ApiError(response.status, detail, text)
  }
  return (await response.json()) as T
}

export const api = {
  health: () => request<{ status: string; relay_buffered: number }>('/api/health'),

  listProjects: () => request<Project[]>('/api/projects'),

  createProject: (name: string, repoPath: string) =>
    request<Project>('/api/projects', {
      method: 'POST',
      body: JSON.stringify({ name, repo_path: repoPath, default_tool_id: 'codex' }),
    }),

  listCases: (projectId: string) => request<Case[]>(`/api/projects/${projectId}/cases`),

  createCase: (projectId: string, title: string, kind: string) =>
    request<Case>(`/api/projects/${projectId}/cases`, {
      method: 'POST',
      body: JSON.stringify({ title, kind }),
    }),

  getCase: (caseId: string) => request<CaseDetail>(`/api/cases/${caseId}`),

  listRunners: () => request<RunnerInfo[]>('/api/runners'),

  // 원문 제출. 응답은 접수 확인이며 저장 완료가 아니다.
  submitArtifact: (caseId: string, kind: string, content: string, summary: string, runnerId: string) =>
    request<{
      intake_id: string
      artifact_id: string
      revision: number
      availability: Availability
    }>(
      `/api/cases/${caseId}/artifacts`,
      {
        method: 'POST',
        body: JSON.stringify({ kind, content, summary, target_runner_id: runnerId }),
      },
    ),

  createIntentVersion: (caseId: string, artifactId: string) =>
    request<IntentVersion>(`/api/cases/${caseId}/intent-versions`, {
      method: 'POST',
      body: JSON.stringify({ artifact_id: artifactId, revision: 1 }),
    }),

  // run_id 를 화면이 만들어 보낸다. 같은 값으로 다시 눌러도 새 실행은 생기지 않는다.
  //
  // P2-03: 목적·역할·도구·권한을 함께 보낸다. **서버가 진입 조건을 검사하며**
  // 조건을 못 갖추면 409와 사유 코드가 돌아온다. 화면에서 버튼을 감추는 것은
  // 조건이 아니므로 이 호출은 언제든 할 수 있고, 답은 서버가 한다.
  createRun: (
    caseId: string,
    artifactId: string,
    runId: string,
    options?: {
      purpose?: RunPurpose
      role?: 'author' | 'reviewer'
      tool_id?: string
      mode?: string
      permission?: 'read_only' | 'workspace_write' | 'explicit_escalated'
      task_id?: string
      instruction_artifact_rev?: number
    },
  ) =>
    request<{ run: Run; created: boolean; admission: AdmissionView | null }>(
      `/api/cases/${caseId}/runs`,
      {
        method: 'POST',
        body: JSON.stringify({
          run_id: runId,
          instruction_artifact_id: artifactId,
          ...options,
        }),
      },
    ),

  getRun: (runId: string) => request<Run>(`/api/runs/${runId}`),

  // 접수 상태 조회. 202 응답은 저장 완료가 아니므로 화면이 여기서 확인한다.
  getIntake: (intakeId: string) =>
    request<{ id: string; state: string; artifact_id: string; revision: number }>(
      `/api/intakes/${intakeId}`,
    ),
}

// ===================================================================== P2-02
//
// 의도 초안 · 피드백 · 질문 · 원문 열람 · 명시 동의.
//
// 원문 본문은 두 방향 모두 **중계만** 된다. 제출한 본문은 서버에 저장되지 않고,
// 열람한 본문은 서버 메모리를 한 번 지나 이 화면에만 나타난다.

export type ConfirmationState =
  | 'undecided'
  | 'proposed'
  | 'user_confirmed'
  | 'needs_recheck'
  | 'superseded'

export type ContentOrigin =
  | 'none'
  | 'user_requirement'
  | 'project_rule'
  | 'observation'
  | 'ai_proposal'
  | 'ai_assumption'

export type DecideAt = 'intent' | 'design' | 'plan'

export type ReadRequestState = 'pending' | 'relayed' | 'delivered' | 'expired'

export type AgreementState =
  | 'no_intent'
  | 'never_agreed'
  | 'stale_agreement'
  | 'agreed_current'

export const INTENT_FIELDS: { key: string; label: string; hint: string }[] = [
  { key: 'goal', label: '목표', hint: '해결하려는 문제와 이번 개발로 얻으려는 가치' },
  { key: 'expected_outcome', label: '기대 결과', hint: '사용자가 무엇을 할 수 있게 되는지' },
  { key: 'scope', label: '범위', hint: '이번 개발에 포함할 기능·대상·사용 상황' },
  { key: 'exclusions', label: '제외사항', hint: '이번에 다루지 않기로 확인한 내용' },
  { key: 'constraints', label: '제약', hint: '지켜야 할 조건과 그 출처' },
  { key: 'open_questions', label: '미정 질문', hint: '아래 질문 목록과 연결되는 설명' },
]

export interface IntentFieldState {
  field: string
  state: ConfirmationState
  origin: ContentOrigin
  change_from_prev: 'initial' | 'unchanged' | 'changed'
}

export interface IntentQuestion {
  id: string
  question_key: string
  summary: string
  decide_at: DecideAt
  state: 'open' | 'answered' | 'withdrawn'
  answered_by: string | null
  answered_at: string | null
}

export interface IntentVersionDetail extends IntentVersion {
  case_id: string
  artifact_rev: number
  superseded_by: string | null
  fields: IntentFieldState[]
  questions: IntentQuestion[]
  // 성공 기준은 의도와 같은 묶음으로 온다. 다른 곳에서 찾게 하지 않는다.
  criteria: SuccessCriterion[]
  content_hash: string
  availability: Availability
  summary: string
}

export interface FeedbackRecord {
  id: string
  target_intent_version_id: string
  target_intent_revision: number
  artifact_id: string
  author: string
  summary: string
  state: 'received' | 'reflected' | 'not_reflected'
  reflected_in_version_id: string | null
  disposition_note: string | null
  created_at: string
}

export interface IntentStateView {
  case_id: string
  latest_intent_version: IntentVersionDetail | null
  agreement_state: AgreementState
  agreed_version: (Decision & { subject_content_hash: string | null }) | null
  open_intent_questions: IntentQuestion[]
  unresolved_feedback: FeedbackRecord[]
  views: { id: string; actor: string; content_hash: string; viewed_at: string }[]
}

export interface IntentDiff {
  intent_version_id: string
  revision: number
  compared_with_revision: number | null
  changed_fields: string[]
  questions_added: string[]
  questions_removed: string[]
  open_questions: IntentQuestion[]
  reflected_feedback: FeedbackRecord[]
  full_text_diff: string
  note: string
}

export interface ReadRequest {
  id: string
  artifact_id: string
  revision: number
  owner_runner_id: string
  state: ReadRequestState
  content_hash: string | null
  byte_size: number | null
}

export interface DraftFieldInput {
  text: string
  state?: ConfirmationState
  origin?: ContentOrigin
}

export interface DraftQuestionInput {
  key: string
  text: string
  summary: string
  decide_at: DecideAt
}

/**
 * 성공 기준 입력.
 *
 * `method` 를 따로 받는 이유는 **확인 방법 없는 기준은 기준이 아니기** 때문이다.
 * 비워 두면 서버가 422로 거절한다 — 빈 값으로 통과시키면 QG-01의
 * `unverifiable_success_criteria` 가 볼 것이 없어진다.
 */
export interface DraftCriterionInput {
  key: string
  relates_to: string
  text: string
  method: string
  summary: string
  method_summary: string
}

export const intentApi = {
  // 여섯 항목 본문은 정규 문서로 묶여 Runner로 간다. 서버에 저장되지 않는다.
  submitDraft: (
    caseId: string,
    payload: {
      summary: string
      target_runner_id: string
      fields: Record<string, DraftFieldInput>
      questions: DraftQuestionInput[]
      criteria?: DraftCriterionInput[]
      reflects_feedback?: string[]
      not_reflected?: Record<string, string>
    },
  ) =>
    request<{ artifact_id: string; revision: number; content_hash: string }>(
      `/api/cases/${caseId}/intent-drafts`,
      { method: 'POST', body: JSON.stringify(payload) },
    ),

  state: (caseId: string) => request<IntentStateView>(`/api/cases/${caseId}/intent-state`),

  diff: (caseId: string, intentId: string) =>
    request<IntentDiff>(`/api/cases/${caseId}/intent-versions/${intentId}/diff`),

  agree: (caseId: string, intentId: string, contentHash: string, statement: string) =>
    request<{ decision: Decision }>(
      `/api/cases/${caseId}/intent-versions/${intentId}/agreement`,
      {
        method: 'POST',
        body: JSON.stringify({
          agree: true,
          statement,
          content_hash: contentHash,
          actor: 'owner',
        }),
      },
    ),

  submitFeedback: (
    caseId: string,
    intentVersionId: string,
    content: string,
    summary: string,
    runnerId: string,
  ) =>
    request<{ feedback: FeedbackRecord }>(`/api/cases/${caseId}/feedback`, {
      method: 'POST',
      body: JSON.stringify({
        target_intent_version_id: intentVersionId,
        content,
        summary,
        target_runner_id: runnerId,
      }),
    }),

  answerQuestion: (
    caseId: string,
    questionId: string,
    content: string,
    summary: string,
    runnerId: string,
  ) =>
    request<{ question: IntentQuestion }>(
      `/api/cases/${caseId}/questions/${questionId}/answer`,
      {
        method: 'POST',
        body: JSON.stringify({ content, summary, target_runner_id: runnerId }),
      },
    ),

  // 피드백의 처리 결과는 **사람이** 정한다. AI가 새 버전을 쓴 뒤 스스로
  // "반영했다"고 선언하게 두지 않는다. 미반영은 이유와 함께 닫는다.
  resolveFeedback: (
    caseId: string,
    feedbackId: string,
    payload: { reflected: boolean; reflected_in_version_id?: string; reason?: string },
  ) =>
    request<FeedbackRecord>(`/api/cases/${caseId}/feedback/${feedbackId}/disposition`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  openRead: (artifactId: string, revision: number) =>
    request<ReadRequest>(`/api/artifacts/${artifactId}/${revision}/read-requests`, {
      method: 'POST',
      body: JSON.stringify({ requested_by: 'owner' }),
    }),

  // 한 번만 받아 갈 수 있다. 받은 즉시 서버 버퍼에서 버려진다.
  fetchRead: (requestId: string) =>
    request<{ request: ReadRequest; content: string | null }>(
      `/api/read-requests/${requestId}`,
    ),
}

// ===================================================================== P2-03
//
// QG-01 게이트 · FR-29 진입 조건 검사 · AI 작성 경로.
//
// 화면이 하는 일은 **보여 주는 것**이다. 조건 판단은 전부 서버에 있다.
// 여기서 버튼을 감추더라도 그것이 조건이 아니며, 서버가 같은 요청을 거부한다.

export type RunPurpose =
  | 'intent_authoring'
  | 'intent_gate_review'
  | 'limited_analysis'
  | 'feature_implementation'

export type GateVerdict =
  | 'pass'
  | 'fail'
  | 'hold'
  | 'not_run'
  | 'needs_recheck'
  | 'blocked'
  | 'not_applicable'

export interface GateFinding {
  id: string
  source: 'rule' | 'ai'
  criterion: string
  severity: 'required' | 'advisory'
  blocking: number
  certainty: 'confirmed' | 'suspected'
  target: string
  summary: string
}

export interface GateResult {
  gate: string
  intent_version_id: string | null
  verdict: GateVerdict
  rule_verdict: GateVerdict
  ai_verdict: GateVerdict
  findings: GateFinding[]
  ai_run_id?: string | null
  ai_session_ref?: string | null
  author_session_ref?: string | null
  reviewed_at?: string | null
  superseded_at?: string | null
}

export interface AdmissionView {
  outcome: 'admitted' | 'refused'
  profile: string
  refusals: string[]
  reasons: Record<string, string>
  intent_version_id: string | null
  intent_agreement_state: string | null
  gate_verdict: string | null
}

export interface AdmissionCheck {
  id: string
  run_id: string | null
  requested_run_id: string
  requested_purpose: RunPurpose
  requested_role: string
  requested_permission: string
  requested_task_id: string
  requested_tool_id: string
  profile: string
  outcome: 'admitted' | 'refused'
  refusals: string[]
  intent_agreement_state: string | null
  gate_verdict: string | null
  checked_at: string
}

//: 판정을 사람 말로. 값을 합치지 않는다 — `not_run` 과 `pass` 는 다른 상태다.
export const GATE_VERDICT_LABEL: Record<GateVerdict, string> = {
  pass: '통과',
  fail: '실패',
  hold: '판단 보류',
  not_run: '검토 안 함',
  needs_recheck: '재검토 필요',
  blocked: '실행 불가',
  not_applicable: '미적용',
}

export const REFUSAL_LABEL: Record<string, string> = {
  intent_not_agreed: '최신 의도에 대한 사람의 동의가 없다',
  open_intent_questions: '의도 단계에서 결정할 질문이 남아 있다',
  intent_gate_not_passed: 'QG-01 의도 품질 게이트를 통과하지 않았다',
  intent_original_not_available: '의도 원문을 지금 읽을 수 없다',
  instruction_not_available: '지시 원문을 실행자가 읽을 수 없다',
  permission_not_allowed_in_stage: '이 단계에서 배정하지 않는 권한이다',
  permission_not_mapped: '이 도구에 해당 권한 매핑이 확인되지 않았다',
  role_mismatch: '목적에 맞지 않는 역할이다',
  prerequisite_not_implemented: '선행 조건(설계·계획 검토)이 아직 구현되지 않았다',
  tool_not_available: '사용 가능하다고 보고된 도구가 아니다',
  tool_is_not_a_coding_cli: '이 도구는 코딩 CLI가 아니다 — AI가 글을 쓰지 않는다',
  review_session_not_separate: '검토가 작성과 별도 세션이 아니다',
  intent_version_missing: '검토할 의도 버전이 없다',
  intent_version_not_latest: '검토 대상이 최신 의도 버전이 아니다',
  case_already_closed: '이미 종료된 업무다 — 수정은 연결된 새 Case 로 한다',
}

export const gateApi = {
  state: (caseId: string) => request<GateResult>(`/api/cases/${caseId}/gate`),

  results: (caseId: string) => request<GateResult[]>(`/api/cases/${caseId}/gate-results`),

  // 규칙 검사만 다시 돌린다. **AI 검토 결과는 그대로 둔다.**
  runRules: (caseId: string, intentId: string) =>
    request<GateResult>(`/api/cases/${caseId}/intent-versions/${intentId}/gate-rules`, {
      method: 'POST',
    }),

  admissionChecks: (caseId: string) =>
    request<AdmissionCheck[]>(`/api/cases/${caseId}/admission-checks`),
}

// ===================================================================== P2-04
//
// 기준별 결과·근거 · 최종 결과 후보 · 사람 최종 확인 · 예외 수용 · 종료 후 새 Case.
//
// **총점 하나를 만들지 않는다.** 기준마다 판정과 근거를 그대로 보여 준다
// (sizing-and-review-ux 6절). 그리고 인수·예외·종료는 서로 다른 기록이며
// 화면이 한자리에서 결정하더라도 합쳐서 보여 주지 않는다.

export type CriterionVerdict =
  | 'unverified'
  | 'met'
  | 'not_met'
  | 'blocked'
  | 'needs_recheck'

export type EvidenceKind = 'none' | 'run_output' | 'human_judgement'

export type CompletionMode = 'human_acceptance' | 'auto_on_conditions'

export type ClosureKind = 'completed' | 'closed_with_exceptions' | 'cancelled'

export interface SuccessCriterion {
  id: string
  case_id: string
  intent_version_id: string
  criterion_key: string
  summary: string
  method_summary: string
  relates_to: string
  state: 'proposed' | 'user_confirmed' | 'superseded'
  created_at: string
  verdict: CriterionVerdict
  evidence_kind: EvidenceKind
  evidence_run_id: string | null
  evidence_artifact_id: string | null
  evidence_artifact_rev: number | null
  result_summary: string
  recorded_by: string
  recorded_at: string
}

/** `criterion_result` 한 행. 기준 정의가 아니라 **판정**만 담는다. */
export interface CriterionResultRow {
  id: string
  criterion_id: string
  case_id: string
  verdict: CriterionVerdict
  evidence_kind: EvidenceKind
  evidence_run_id: string | null
  evidence_artifact_id: string | null
  evidence_artifact_rev: number | null
  summary: string
  recorded_by: string
  recorded_at: string
}

export interface UnsettledRun {
  run_id: string
  status: string
  outcome: string | null
  purpose: RunPurpose | null
  tool_id: string
}

export interface ExceptionDecision {
  id: string
  candidate_id: string
  target_type: string
  target_id: string
  original_verdict: CriterionVerdict
  scope_summary: string
  actor: string
  decided_at: string
}

export interface FinalAcceptance {
  id: string
  candidate_id: string
  decision_id: string
  mode: 'human' | 'auto_policy'
  actor: string
  accepted_at: string
}

export interface CandidateCriterion {
  criterion_id: string
  verdict: CriterionVerdict
  criterion_key: string
  summary: string
  method_summary: string
  relates_to: string
  state: string
}

export interface CompletionCandidate {
  id: string
  case_id: string
  revision: number
  intent_version_id: string | null
  intent_agreement_state: string
  gate_verdict: string
  criteria_total: number
  criteria_met: number
  unresolved: { kind: string; id: string; key?: string; verdict: string }[]
  unsettled_runs: UnsettledRun[]
  snapshot_hash: string
  state: 'open' | 'superseded'
  created_at: string
  criteria: CandidateCriterion[]
  exceptions: ExceptionDecision[]
  acceptance: FinalAcceptance | null
}

export interface ClosureRecord {
  id: string
  case_id: string
  candidate_id: string
  final_acceptance_id: string | null
  closure_kind: ClosureKind
  exception_count: number
  confirmed_at: string
}

export interface CaseRelation {
  id: string
  from_case_id: string
  to_case_id: string
  relation: string
  reason_summary: string
  created_at: string
}

export interface ResultView {
  case_id: string
  completion_mode: CompletionMode
  criteria: SuccessCriterion[]
  unsettled_runs: UnsettledRun[]
  candidate: CompletionCandidate | null
  closure: ClosureRecord | null
  relations: CaseRelation[]
}

//: 판정을 사람 말로. `unverified` 와 `not_met` 을 합치지 않는다 — 확인하지 않은 것과
//: 확인해서 미충족인 것은 다르다. `blocked` 도 미충족이 아니다.
export const CRITERION_VERDICT_LABEL: Record<CriterionVerdict, string> = {
  unverified: '미확인',
  met: '충족',
  not_met: '미충족',
  blocked: '확인 불가',
  needs_recheck: '재검토 필요',
}

export const EVIDENCE_KIND_LABEL: Record<EvidenceKind, string> = {
  none: '근거 없음',
  run_output: '실행 결과',
  human_judgement: '사람 판단',
}

export const CLOSURE_KIND_LABEL: Record<ClosureKind, string> = {
  completed: '완료',
  closed_with_exceptions: '예외 수용으로 종료',
  cancelled: '취소',
}

export const ACCEPTANCE_REFUSAL_LABEL: Record<string, string> = {
  not_explicit: '대상이 분명한 인수 문구가 아니다',
  candidate_superseded: '그 사이 결과 후보가 바뀌었다 — 지금 후보를 다시 본다',
  unresolved_criteria: '충족되지 않은 기준이 남아 있다 (예외를 수용하거나 채워야 한다)',
  open_intent_questions: '의도 단계에서 결정할 질문이 남아 있다',
  unresolved_feedback: '아직 반영도 미반영도 정해지지 않은 피드백이 남아 있다',
  no_success_criteria: '합의한 성공 기준이 0건이다 — 견줄 기준 없이 인수할 수 없다',
  unsettled_runs_present: '결과를 확정할 수 없는 실행이 남아 있다',
  intent_not_agreed: '최신 의도에 대한 사람의 동의가 없다',
  case_already_closed: '이미 종료된 업무다 — 수정은 연결된 새 Case 로 한다',
  auto_policy_cannot_accept_exception: '자동 완료 모드는 예외를 수용하지 않는다',
  exception_target_not_failing: '충족된 기준에는 예외를 걸 수 없다',
}

/** 인수 문구로 인정하는 표현. 서버의 목록과 같아야 한다. */
export const ACCEPTANCE_PHRASES = ['이 결과를 인수', '결과 인수', '최종 인수']

export const resultApi = {
  view: (caseId: string) => request<ResultView>(`/api/cases/${caseId}/result`),

  recordVerdict: (
    caseId: string,
    criterionId: string,
    payload: {
      verdict: CriterionVerdict
      summary: string
      recorded_by?: string
      evidence_kind: EvidenceKind
      evidence_run_id?: string | null
      evidence_artifact_id?: string | null
      evidence_artifact_rev?: number | null
    },
  ) =>
    request<CriterionResultRow>(`/api/cases/${caseId}/criteria/${criterionId}/result`, {
      method: 'POST',
      body: JSON.stringify({ recorded_by: 'owner', ...payload }),
    }),

  setCompletionMode: (caseId: string, mode: CompletionMode) =>
    request<{ mode: CompletionMode }>(`/api/cases/${caseId}/completion-policy`, {
      method: 'PUT',
      body: JSON.stringify({ mode, set_by: 'owner' }),
    }),

  buildCandidate: (caseId: string) =>
    request<{ created: boolean; candidate: CompletionCandidate }>(
      `/api/cases/${caseId}/completion-candidates`,
      { method: 'POST' },
    ),

  acceptException: (
    caseId: string,
    candidateId: string,
    criterionId: string,
    scopeSummary: string,
  ) =>
    request<ExceptionDecision>(
      `/api/cases/${caseId}/completion-candidates/${candidateId}/exceptions`,
      {
        method: 'POST',
        body: JSON.stringify({
          actor: 'owner',
          criterion_id: criterionId,
          scope_summary: scopeSummary,
        }),
      },
    ),

  // 인수 문구는 서버가 판단에만 쓰고 버린다. 저장되지 않는다.
  accept: (caseId: string, candidateId: string, statement: string) =>
    request<{
      acceptance: FinalAcceptance
      closure: ClosureRecord | null
      candidate: CompletionCandidate
    }>(`/api/cases/${caseId}/completion-candidates/${candidateId}/acceptance`, {
      method: 'POST',
      body: JSON.stringify({ actor: 'owner', statement }),
    }),

  autoComplete: (caseId: string) =>
    request<{
      applied: boolean
      reason?: string
      refusals?: string[]
      candidate: CompletionCandidate
      closure: ClosureRecord | null
    }>(`/api/cases/${caseId}/auto-complete`, { method: 'POST' }),

  createSuccessor: (caseId: string, title: string, kind: string, reason: string) =>
    request<Case>(`/api/cases/${caseId}/successor`, {
      method: 'POST',
      body: JSON.stringify({ title, kind, reason_summary: reason }),
    }),
}
