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
}

export interface RunnerInfo {
  id: string
  name: string
  host: string
  status: string
  last_heartbeat_at: string | null
  capabilities: { tool_id: string; mode: string; capability: string; state: string }[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`${response.status} ${detail}`)
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
    request<{ intake_id: string; artifact_id: string; availability: Availability }>(
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
  createRun: (caseId: string, artifactId: string, runId: string) =>
    request<{ run: Run; created: boolean }>(`/api/cases/${caseId}/runs`, {
      method: 'POST',
      body: JSON.stringify({ run_id: runId, instruction_artifact_id: artifactId }),
    }),

  getRun: (runId: string) => request<Run>(`/api/runs/${runId}`),
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

export const intentApi = {
  // 여섯 항목 본문은 정규 문서로 묶여 Runner로 간다. 서버에 저장되지 않는다.
  submitDraft: (
    caseId: string,
    payload: {
      summary: string
      target_runner_id: string
      fields: Record<string, DraftFieldInput>
      questions: DraftQuestionInput[]
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
