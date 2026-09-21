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
  // P3-03: 실행 전후 작업공간 대조의 결과. **`null` 은 "변경 없음"이 아니라
  // 관측하지 않았다는 뜻이다** — 화면이 둘을 같게 보이면 안 된다.
  workspace_effect?: WorkspaceEffect | null
  // 그 실행이 **실제로 실행한 명령**. 원문은 Runner 에 있다.
  commands?: RunCommand[]
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
  // P3-01: 수준·설계·계획·검토 상태. 화면과 서버가 **같은 값**을 본다 —
  // 화면이 따로 계산하면 버튼은 눌리는데 서버가 거부하는 상태가 생긴다.
  preparation: PreparationState
  // P3-03: 어떤 코드 위에서 어디에 만들고 있는가. `null` 은 **아직 준비되지
  // 않았다**는 뜻이며 그 Case 의 쓰기는 `workspace_not_ready` 로 막힌다.
  workspace: WorkspaceView | null
  // P3-R1: 이 업무에 적용되는 목적·깊이·확인 경계·한도·저장소와 **각 축을 지금
  // 누가 강제하는가.** 화면이 기록과 강제를 구별해 보여야 한다(FR-14).
  policy?: CasePolicy
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
  // P3-01: 이 질문이 **어느 단계에서 제기됐는가.** 옛 행은 `null` 이며 그것은
  // 의도 단계에서 제기됐다는 사실과 일치한다 — P3-01 전에는 다른 단계가 없었다.
  raised_in_stage?: string | null
  preparation_id?: string | null
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
  // P3-01. 설계와 계획은 서로 다른 목적이며 각각 독립된 검토를 받는다.
  | 'design_authoring'
  | 'plan_authoring'
  | 'feature_implementation'
  // P3-03. 검증은 구현과 **다른 목적**이다 — 완료 판정이 다르다. 구현은 작업공간
  // 변화가 있어야 완료이고, 검증은 실제로 실행된 명령이 있어야 완료다.
  | 'verification_run'

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
  // P2 시절의 사유. 지금은 발급되지 않지만 과거 기록을 읽기 위해 문구를 남긴다.
  prerequisite_not_implemented: '선행 조건(설계·계획 검토)이 아직 구현되지 않았다',
  sizing_not_decided: '작업 수준이 결정되지 않았다 — 축별 판단이 있는 의도 초안이 필요하다',
  design_missing: '설계안이 없다',
  design_stale: '설계안이 대체된 의도 버전 위에 있거나 원문을 읽을 수 없다',
  design_incomplete_for_level: '현재 수준이 요구하는 설계 항목이 미정이다',
  design_review_missing: '설계 검토(사람 검토 또는 자동 조건 충족)가 없다',
  plan_missing: '개발계획이 없다',
  plan_stale: '개발계획이 대체된 의도 버전 위에 있거나 원문을 읽을 수 없다',
  plan_incomplete_for_level: '현재 수준이 요구하는 계획 항목이 미정이다',
  plan_review_missing: '개발계획 검토가 없다',
  deferred_questions_unresolved: '설계·계획으로 이월한 질문이 남아 있다',
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


// ===================================================================== P3-01
//
// 작업 수준 · 설계안 · 개발계획 · 단계별 사람 검토.
//
// **자동 진행을 `사람 승인됨` 으로 표시하지 않는다.** 두 상태의 문구를 여기서
// 나눠 두고 화면은 그 문구만 쓴다(sizing-and-review-ux 2·5절).

export type WorkLevel = 'simple' | 'standard' | 'deep'

export type AxisWeight = 'low' | 'medium' | 'high' | 'insufficient_evidence'

export type PreparationStage = 'design' | 'plan'

export type ReviewMode = 'human_review' | 'auto_proceed'

export type StageReviewState =
  | 'not_ready'
  | 'awaiting_human_review'
  | 'awaiting_auto_conditions'
  | 'human_reviewed'
  | 'auto_conditions_met'
  | 'needs_recheck'

export const WORK_LEVEL_LABEL: Record<WorkLevel, string> = {
  simple: '간소',
  standard: '표준',
  deep: '심층',
}

export const AXIS_WEIGHT_LABEL: Record<AxisWeight, string> = {
  low: '낮음',
  medium: '중간',
  high: '높음',
  // 모르는 것을 "영향 없음"으로 보이게 하지 않는다.
  insufficient_evidence: '근거 부족 — 조사 필요',
}

export const SIZING_AXIS_LABEL: Record<string, string> = {
  intent_clarity: '의도와 성공 기준의 명확성',
  change_scope: '변경 범위·구성 요소 의존성',
  compatibility_and_data: '호환성과 데이터 생명주기',
  permission_and_security: '권한·보안·민감 데이터 영향',
  reversibility: '가역성과 실패 비용',
  uncertainty: '해법·환경의 불확실성',
  verification_difficulty: '검증 난도',
}

export const SIZING_SOURCE_LABEL: Record<string, string> = {
  ai_recommendation: 'AI 제안',
  human_assessment: '사람이 쓴 판단',
  human_adjustment: '사람의 조정',
}

//: **여기가 자동 진행과 사람 승인을 가르는 문구다.** 합치지 않는다.
export const STAGE_STATE_LABEL: Record<StageReviewState, string> = {
  not_ready: '산출물 준비 전',
  awaiting_human_review: '사람 검토 대기',
  awaiting_auto_conditions: '자동 진행 — 조건 충족 미기록',
  human_reviewed: '사람이 검토함',
  auto_conditions_met: '자동 조건 충족 (사람 승인 아님)',
  needs_recheck: '의도가 바뀌어 재검토 필요',
}

export const REVIEW_MODE_LABEL: Record<ReviewMode, string> = {
  human_review: '사람 검토',
  auto_proceed: '자동 진행',
}

export const STAGE_LABEL: Record<PreparationStage, string> = {
  design: '설계안',
  plan: '개발계획',
}

export interface SizingAxisRow {
  axis: string
  weight: AxisWeight
  judgement_summary: string
  unconfirmed_summary: string
}

export interface SizingAssessment {
  id: string
  case_id: string
  revision: number
  intent_version_id: string | null
  source: string
  // 세 값을 따로 보여 준다 — AI가 수준을 조용히 낮추지 못한다는 것이 보여야 한다.
  recommended_level: WorkLevel
  derived_level: WorkLevel
  level: WorkLevel
  adjusted_from: WorkLevel | null
  evidence_gap: boolean
  reason_summary: string
  residual_risk_summary: string
  actor: string
  state: string
  created_at: string
  axes: SizingAxisRow[]
}

export interface PreparationSection {
  section: string
  label: string
  state: ConfirmationState
  origin: ContentOrigin
  // **지금** 요구되는지. 사람이 수준을 올리면 이 값이 함께 바뀐다.
  required: boolean
  // 보고 시점에 요구됐는지(기록). 판단에는 쓰지 않는다.
  required_at_report: boolean
}

export interface PreparationArtifact {
  id: string
  case_id: string
  stage: PreparationStage
  revision: number
  artifact_id: string
  artifact_rev: number
  intent_version_id: string
  based_on_design_id: string | null
  level: WorkLevel
  authoring_mode: string
  author_run_id: string | null
  summary: string
  state: string
  created_at: string
  availability: Availability
  content_hash: string
  owner_runner_id: string
  sections: PreparationSection[]
  review: StageReview | null
  missing_required_sections: string[]
}

export interface StageReview {
  id: string
  case_id: string
  stage: PreparationStage
  preparation_id: string
  mode: ReviewMode
  state: StageReviewState
  // 사람 검토만 채운다. 자동 진행은 `null` 이며 그것이 구별의 근거다.
  decision_id: string | null
  actor: string
  subject_content_hash: string
  note_summary: string
  recorded_at: string
}

export interface StageState {
  stage: PreparationStage
  mode: ReviewMode
  mode_source: 'project_default' | 'case_setting'
  mode_reason: string
  artifact: PreparationArtifact | null
  review: StageReview | null
  state: StageReviewState
  stale: boolean
  missing_required_sections: string[]
}

export interface PreparationState {
  case_id: string
  sizing: SizingAssessment | null
  // `null` 은 **미결정**이다. 간소로 읽지 않는다.
  level: WorkLevel | null
  sizing_history: SizingAssessment[]
  design: StageState
  plan: StageState
  deferred_open_questions: IntentQuestion[]
  // P3-02. 준비 조건 **위에 얹히는** 상태다. 계획 검토가 끝났다는 사실과
  // 무엇을 어떤 순서로 만들지가 정해졌다는 사실은 다른 것이다.
  work_graph: WorkGraphState
}

export interface RunContextRef {
  run_id: string
  seq: number
  role: string
  artifact_id: string
  revision: number
  availability: Availability
  content_hash: string
}

export const CONTEXT_ROLE_LABEL: Record<string, string> = {
  previous_intent: '직전 의도 초안',
  agreed_intent: '동의된 의도 원문',
  previous_design: '직전 설계안',
  current_design: '현재 설계안',
  previous_plan: '직전 개발계획',
  feedback: '미해결 피드백',
}

//: 항목의 확인 상태와 내용의 성격 문구. 의도 화면과 준비 화면이 **같은 말**을
//: 쓰도록 한 곳에 둔다. 두 곳에 따로 두면 문구가 갈라진다.
export const CONFIRMATION_LABEL: Record<string, string> = {
  undecided: '미정',
  proposed: '제안됨',
  user_confirmed: '사용자 확인됨',
  needs_recheck: '재검토 필요',
  superseded: '대체됨',
}

export const ORIGIN_LABEL: Record<string, string> = {
  none: '없음 (미정)',
  user_requirement: '사용자 요구',
  project_rule: '프로젝트 규칙',
  observation: '관찰 사실',
  ai_proposal: 'AI 제안',
  ai_assumption: 'AI 가정',
}

export const preparationApi = {
  state: (caseId: string) => request<PreparationState>(`/api/cases/${caseId}/preparation`),

  artifacts: (caseId: string, stage?: PreparationStage) =>
    request<PreparationArtifact[]>(
      `/api/cases/${caseId}/preparation-artifacts${stage ? `?stage=${stage}` : ''}`,
    ),

  // 수준 조정. **이유와 남는 위험이 필수다**(sizing-and-review-ux 1절).
  adjustLevel: (caseId: string, level: WorkLevel, reason: string, residualRisk: string) =>
    request<SizingAssessment>(`/api/cases/${caseId}/sizing-adjustment`, {
      method: 'POST',
      body: JSON.stringify({
        level,
        reason,
        residual_risk: residualRisk,
        actor: 'owner',
      }),
    }),

  setMode: (caseId: string, stage: PreparationStage, mode: ReviewMode, reason: string) =>
    request<StageState>(`/api/cases/${caseId}/stage-review-settings/${stage}`, {
      method: 'PUT',
      body: JSON.stringify({ mode, reason, set_by: 'owner' }),
    }),

  // 사람 검토. `reviewed` 를 명시로 보낸다 — 화면을 열어 본 것이 검토가 아니다.
  review: (caseId: string, stage: PreparationStage, note: string) =>
    request<StageReview>(`/api/cases/${caseId}/stage-reviews/${stage}`, {
      method: 'POST',
      body: JSON.stringify({ reviewed: true, note, actor: 'owner' }),
    }),

  autoProceed: (caseId: string, stage: PreparationStage) =>
    request<StageReview>(`/api/cases/${caseId}/stage-auto-proceed/${stage}`, {
      method: 'POST',
    }),

  contextRefs: (runId: string) => request<RunContextRef[]>(`/api/runs/${runId}/context-refs`),
}

// ===================================================================== P3-02
//
// 작업 그래프 — 무엇을 어떤 순서로 만들고, 그중 무엇이 **왜 지금 막혀 있는가.**
//
// 차단 사유는 서버가 계산한 것을 그대로 보인다. 화면이 따로 계산하면 버튼은
// 눌리는데 서버가 거부하는(또는 그 반대의) 상태가 생긴다.

export type TaskKind =
  | 'investigation'
  | 'implementation'
  | 'verification'
  | 'experiment'
  | 'integration'

export type TaskState = 'planned' | 'in_progress' | 'done' | 'cancelled'

export const TASK_KIND_LABEL: Record<TaskKind, string> = {
  investigation: '조사',
  implementation: '구현',
  verification: '검증',
  experiment: '실험',
  integration: '통합',
}

export const TASK_STATE_LABEL: Record<TaskState, string> = {
  planned: '대기',
  in_progress: '진행 중',
  // **실행 증거가 있는 완료다.** 사람이 적어서 되는 상태가 아니다.
  done: '완료 (실행 결과)',
  cancelled: '취소됨',
}

export const TASK_RELATION_LABEL: Record<string, string> = {
  implements: '구현',
  verifies: '검증',
}

export const WORK_GRAPH_SOURCE_LABEL: Record<string, string> = {
  plan_artifact: '개발계획이 정의함',
  human_replanning: '사람의 재계획',
}

//: 차단 사유의 사람 문구. 진입 검사의 사유 코드와 **같은 값**을 쓴다.
export const TASK_BLOCK_LABEL: Record<string, string> = {
  deferred_questions_unresolved: '사람 결정 대기',
  task_dependencies_unmet: '선행 작업 미완료',
  task_not_in_work_graph: '현재 그래프의 작업이 아님',
}

export interface TaskCriterionLink {
  criterion_id: string
  relation: string
}

export interface TaskReadiness {
  task_key: string
  state: TaskState
  runnable: boolean
  blocked_by: { reason: string; detail: string }[]
}

export interface TaskRow {
  id: string
  task_key: string
  kind: TaskKind
  relates_to: string
  summary: string
  deliverable_summary: string
  completion_summary: string
  order_index: number
  origin: string
  cancelled: boolean
  cancel_reason: string
  depends_on: string[]
  criteria: TaskCriterionLink[]
  state: TaskState
  readiness: TaskReadiness | null
}

export interface WorkGraphRevision {
  id: string
  case_id: string
  revision: number
  intent_version_id: string
  plan_preparation_id: string
  source: string
  reason_summary: string
  actor: string
  state: string
  created_at: string
  tasks: TaskRow[]
}

export interface CriterionCoverage {
  criterion_id: string
  criterion_key: string
  summary: string
  implemented_by: string[]
  verified_by: string[]
  has_verification_task: boolean
}

export interface WorkGraphState {
  case_id: string
  // `false` 는 "Task 가 필요 없다"가 아니라 **그래프가 아직 없다**는 뜻이다.
  present: boolean
  stale: boolean
  graph: WorkGraphRevision | null
  tasks: TaskRow[]
  readiness: Record<string, TaskReadiness>
  criteria_coverage: CriterionCoverage[]
  deferred_open_questions: IntentQuestion[]
  question_blocks: Record<string, string[]>
  // **해석되지 않은 참조는 버려지지 않는다.** 그 질문은 전부 막는다.
  unresolved_block_refs: { question_id: string; raw_ref: string }[]
}

export const workGraphApi = {
  state: (caseId: string) => request<WorkGraphState>(`/api/cases/${caseId}/work-graph`),

  revisions: (caseId: string) =>
    request<WorkGraphRevision[]>(`/api/cases/${caseId}/work-graph-revisions`),

  taskRuns: (caseId: string, taskKey: string) =>
    request<Run[]>(`/api/cases/${caseId}/tasks/${encodeURIComponent(taskKey)}/runs`),

  // 사람의 재계획. **이유가 필수다**(FR-07).
  addTask: (
    caseId: string,
    task: {
      key: string
      kind: TaskKind
      summary: string
      deliverable_summary?: string
      completion_summary?: string
      depends_on?: string[]
    },
    reason: string,
  ) =>
    request<WorkGraphRevision>(`/api/cases/${caseId}/work-graph/tasks`, {
      method: 'POST',
      body: JSON.stringify({ task, reason, actor: 'owner' }),
    }),

  cancelTask: (caseId: string, taskKey: string, reason: string) =>
    request<WorkGraphRevision>(
      `/api/cases/${caseId}/work-graph/tasks/${encodeURIComponent(taskKey)}/cancel`,
      { method: 'POST', body: JSON.stringify({ reason, actor: 'owner' }) },
    ),

  // 어떤 Task 가 이 결정을 기다리는지 고친다. **답하는 것이 아니다.**
  setQuestionBlocks: (caseId: string, questionId: string, taskKeys: string[], reason: string) =>
    request<WorkGraphRevision>(`/api/cases/${caseId}/questions/${questionId}/blocks`, {
      method: 'PUT',
      body: JSON.stringify({ task_keys: taskKeys, reason, actor: 'owner' }),
    }),
}


// ===================================================================== P3-03
//
// 작업공간과 실행 효과. **수와 SHA 만 온다** — diff·파일 경로·명령 원문·빌드
// 로그는 Runner 에 있고 상세는 원문 조회로 본다(D-43).

export interface WorkspaceEffect {
  base_commit: string
  head_before: string
  head_after: string
  entries_before: number
  entries_after: number
  // **이 실행이 무엇인가 바꿨는가.** 아래 수와 다르다.
  changed: boolean
  // 기준 커밋 대비 **누적** 변경. 이 실행만의 것이 아니다.
  files_changed: number
  insertions: number
  deletions: number
  numbers_are_cumulative?: boolean
  // **"격리했다"가 아니라 "이만큼 봤다"이다**(D-44).
  isolation: string
  outside_workspace_observed: boolean
  // `null` 은 관측하지 않았다는 뜻이다. `false` 와 다르다.
  outside_workspace_changed: boolean | null
}

export interface RunCommand {
  run_id: string
  seq: number
  command_summary: string
  // `null` 은 **끝을 확인하지 못했다**이며 실패가 아니다.
  exit_code: number | null
  duration_ms: number | null
  started_at: string
}

export interface RunEffectRow {
  run_id: string
  task_id: string
  purpose: string | null
  permission: string
  outcome: string | null
  finished_at: string | null
  effect: WorkspaceEffect
  // 직전 실행이 남긴 상태와 다른 자리에서 시작했다. **드러내되 되돌리지 않는다**(FR-26).
  unexpected_external_change: boolean
}

export type WorkspaceState = 'requested' | 'ready' | 'failed'

export interface WorkspaceView {
  case_id: string
  state: WorkspaceState
  branch: string
  repo_path: string
  worktree_path: string
  base_commit: string
  base_ref: string
  // 준비 시점에 관측한 **사용자의 원래 작업 트리**. 시스템이 정리하지 않았다.
  user_tree_dirty: boolean
  user_tree_entries: number
  failure_reason: string
  requested_at: string
  ready_at: string | null
  run_effects: RunEffectRow[]
  outside_workspace_changed: boolean
  isolation: string
  // 한계 문구는 **서버가 준다.** 화면이 지어내면 언젠가 "격리됨"으로 바뀐다.
  isolation_note: string
}

export const WORKSPACE_STATE_LABEL: Record<WorkspaceState, string> = {
  requested: '요청됨 (아직 만들어지지 않음)',
  ready: '준비됨',
  failed: '준비 실패',
}

export const workspaceApi = {
  state: (caseId: string) => request<WorkspaceView | null>(`/api/cases/${caseId}/workspace`),

  // 작업공간을 준비해 달라고 기록한다. **응답은 준비 완료가 아니다** —
  // Runner 가 실제로 만든 뒤에야 `ready` 가 된다.
  prepare: (caseId: string, baseRef = 'HEAD') =>
    request<WorkspaceView>(`/api/cases/${caseId}/workspace`, {
      method: 'POST',
      body: JSON.stringify({ base_ref: baseRef }),
    }),
}

// --------------------------------------------------------------- P3-R1 정책

export type Autonomy = 'ask_on_decision' | 'controlled'

export const AUTONOMY_LABEL: Record<Autonomy, string> = {
  ask_on_decision: '기본 자율 진행 (판단이 필요할 때 사람 호출)',
  controlled: '확인 경계 (시작 범위·결과 후보를 사람이 확인)',
}

export const AUTONOMY_SOURCE_LABEL: Record<string, string> = {
  system_default: '시스템 기본값',
  case_explicit: '이 업무에 명시 설정',
  // **기본값으로 읽지 않는다.** R1 이전 Case 는 이 축이 기록되지 않았다.
  migrated_unknown: '기록되지 않음 (v0.6 기준으로 진행한 업무)',
}

export interface ProfileFieldInfo {
  field: string
  label: string
}

export interface ProfileDefinition {
  profile: string
  version: string
  purpose: string
  common_fields: string[]
  semantic_fields: ProfileFieldInfo[]
  required_fields: string[]
  minimum_evidence: string
  conditional_evidence: string
  completion_meaning: string
  not_fixed_in_draft: string
}

export interface CaseProfileState {
  profile: string | null
  version: string | null
  source: string
  definition: ProfileDefinition | null
  required_fields: string[]
  kind: string
  detail: string | null
}

export interface EnforcementNote {
  state: string
  enforced_by: string
  detail: string
}

export interface BudgetLimit {
  id: string
  metric: string
  threshold_kind: string
  limit_value: number
  unit: string
  measurement: string
  enforcement: string
  enforced_by: string
  state: string
  set_by: string
  reason_summary: string | null
  created_at: string
}

export interface BudgetState {
  unlimited: boolean
  limits: BudgetLimit[]
  history: BudgetLimit[]
  // `null` 은 **아직 측정하지 않는다**는 뜻이며 0이 아니다(D-61).
  usage: null | Record<string, unknown>
  usage_detail: string
  measurement_contract: Record<string, string>
  repair_limit_note: string
  enforcement: EnforcementNote
}

export interface ControlledCheckpointRow {
  id: string
  checkpoint: string
  state: string
  subject_type: string | null
  subject_id: string | null
  subject_hash: string | null
  confirmed_by: string | null
  confirmed_at: string | null
  note_summary: string | null
}

export interface CaseRepositoryRow {
  repository_id: string
  repository_name: string
  repo_path: string
  selection_source: string
  code_write_allowed: number
  publish_allowed: number
  selected_by: string
  state: string
}

export interface CaseRepositoryState {
  selected: CaseRepositoryRow[]
  excluded: CaseRepositoryRow[]
  // 선택 기록이 없는 Case. **"선택했다"로 적지 않는다**(이행된 가정이다).
  implicit_single_repository: { repository_id: string; repo_path: string; detail: string } | null
  journal_repository_id: string | null
  write_allowance_implies_publish: boolean
}

export interface DelegationBasisRow {
  revision: number
  basis_kind: string
  summary: string
  content_hash: string | null
  state: string
  recorded_at: string
}

export interface CasePolicy {
  case_id: string
  revision: number
  // `null` 은 기록되지 않음이다. 화면이 기본값으로 채우지 않는다.
  autonomy: Autonomy | null
  autonomy_source: string
  autonomy_recorded: boolean
  policy_version: string
  default_autonomy: Autonomy
  work_depth: string | null
  work_depth_source: string
  completion_mode: string
  profile: CaseProfileState
  checkpoints: ControlledCheckpointRow[]
  budget: BudgetState
  delegation_basis: { current: DelegationBasisRow | null; history: DelegationBasisRow[]; detail: string }
  repositories: CaseRepositoryState
  enforcement: Record<string, EnforcementNote>
  case_status: string
}

export const CHECKPOINT_LABEL: Record<string, string> = {
  start_scope: '시작 범위 확인 (목표·범위·기준·허용 행동)',
  result_candidate: '결과 후보 확인 (게시 전)',
}

export const policyApi = {
  get: (caseId: string) => request<CasePolicy>(`/api/cases/${caseId}/policy`),

  profiles: () =>
    request<{ current_version: string; profiles: ProfileDefinition[]; note: string }>(
      '/api/profiles',
    ),

  // **설정이 실행 경로를 바꾸지 않는다**(P3-R1). 값과 출처가 기록될 뿐이며 화면은
  // 그 사실을 `enforcement` 로 함께 보인다.
  setAutonomy: (caseId: string, autonomy: Autonomy, reason: string) =>
    request<CasePolicy>(`/api/cases/${caseId}/autonomy`, {
      method: 'PUT',
      body: JSON.stringify({ autonomy, set_by: 'owner', reason_summary: reason || null }),
    }),

  confirmCheckpoint: (caseId: string, checkpoint: string, subjectId: string, note: string) =>
    request<ControlledCheckpointRow[]>(
      `/api/cases/${caseId}/controlled-checkpoints/${checkpoint}/confirmation`,
      {
        method: 'POST',
        body: JSON.stringify({
          confirmed_by: 'owner',
          // 화면의 확인 버튼은 **명시적 확인**이다. 서버는 그렇지 않은 요청을 거부한다.
          explicit: true,
          subject_type: checkpoint === 'start_scope' ? 'case' : 'completion_candidate',
          subject_id: subjectId,
          note_summary: note || null,
        }),
      },
    ),

  setBudget: (caseId: string, metric: string, thresholdKind: string, value: number) =>
    request<BudgetState>(`/api/cases/${caseId}/budget`, {
      method: 'PUT',
      body: JSON.stringify({
        metric,
        threshold_kind: thresholdKind,
        limit_value: value,
        set_by: 'owner',
      }),
    }),

  clearBudget: (caseId: string, metric: string, thresholdKind: string) =>
    request<BudgetState>(`/api/cases/${caseId}/budget/${metric}/${thresholdKind}`, {
      method: 'DELETE',
    }),
}
