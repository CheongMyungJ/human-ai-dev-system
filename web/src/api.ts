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
  // UI-04c(D-86). **이 버전의** Profile·정의판·유지 항목(개정 전 Profile 의 의미 항목). Case 의 현재 값이 아니다.
  profile?: string | null
  profile_version?: string | null
  retained_fields?: string[]
  required_fields?: string[]
}

export interface Decision {
  id: string
  kind: string
  subject_type: string
  subject_id: string
  subject_revision: number
  actor: string
  decided_at: string
  // 근거 메시지의 원문 참조(artifact_id). 원문은 PC 에 있다.
  evidence_ref?: string | null
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
  // P4-04: CLI 를 부르기 **전에** 멈춘 이유. 있으면 소비가 0 으로 정산됐다.
  not_started_reason?: string | null
  context_inline_limit?: number | null
  // P4-10(D-95): 이 실행에 적용한 CLI 제한 시간(초)과 끊긴 이유. `null` 은 기록 없음(옛 실행).
  timeout_seconds?: number | null
  stop_reason?: 'timeout' | 'stop_requested' | null
  // D-96(P4-10b): 읽기 전용 실행 전후의 작업 트리 대조(자리 이름뿐). `null` 은 관측 기록 없음.
  read_only_change?: ReadOnlyChange | null
  // P4-04: 무엇을 주려 했고(계획) 무엇을 실제로 읽었는가(영수증). 서버가 도출한 값이다.
  context?: RunContext
}

//: P4-04. `not_reported` 는 영수증이 없는 실행(P4-04 이전)이다 — 읽음으로 보이지 않는다.
export type RunContextState = 'complete' | 'partial' | 'blocked' | 'not_reported'

export interface RunContextFreshness {
  state: 'current' | 'drifted'
  added_count: number
  added: { role: string; artifact_id: string; revision: number }[]
  measured_at: string
  // `at_result` 는 결과 보고 시점의 기록, `live` 는 진행 중 실행의 조회 시점 계산이다.
  basis: 'at_result' | 'live'
}

export interface RunContext {
  state: RunContextState
  limit: number | null
  instruction_bytes: number
  inline_bytes: number
  ref_count: number
  omitted_count: number
  omitted: { seq: number; role: string; artifact_id: string; revision: number }[]
  receipt_generation: number | null
  unread: { seq: number; role: string; status: string }[]
  not_started_reason: string | null
  // `null` 은 "새 입력 없음"이 아니라 계산하지 않았다(옛 실행)는 뜻이다.
  freshness: RunContextFreshness | null
  // P4-06. 지식 Manifest. `recorded = false` 는 기록 전(P4-06 이전 실행)이며 "지식 없음"이 아니다.
  knowledge?: RunKnowledgeView
}

// ------------------------------------------------------------------ P4-06 지식

export type KnowledgeKind = 'decision' | 'constraint' | 'known_problem' | 'operation'
export type KnowledgeObligation = 'required' | 'reference'
export type KnowledgeState = 'candidate' | 'active' | 'superseded' | 'invalid'

export const KNOWLEDGE_KIND_LABEL: Record<KnowledgeKind, string> = {
  decision: '결정',
  constraint: '제약',
  known_problem: '알려진 문제',
  operation: '운영 사실',
}

export const KNOWLEDGE_STATE_LABEL: Record<KnowledgeState, string> = {
  candidate: '후보',
  active: '활성',
  superseded: '대체됨',
  invalid: '무효',
}

export const KNOWLEDGE_AUTHORITY_LABEL: Record<string, string> = {
  user_registration: '사람이 등록',
  user_statement: '대화의 사용자 말(AI 가 옮김)',
  user_decision: '사람이 후보를 활성화',
  ai_proposal: 'AI 제안',
}

export const KNOWLEDGE_DECISION_LABEL: Record<string, string> = {
  provided: '제공',
  omitted_size_limit: '한도로 생략',
  not_applicable_activity: '활동 비적용',
  not_applicable_repository: '다른 저장소',
  scope_undetermined: '범위 미확정',
}

export interface KnowledgeVersion {
  id: string
  knowledge_id: string
  knowledge_key: string
  project_id: string
  version: number
  artifact_id: string
  artifact_rev: number
  kind: KnowledgeKind
  obligation: KnowledgeObligation
  state: KnowledgeState
  summary: string
  scope_kind: 'project' | 'repository'
  repository_id: string | null
  repository_name?: string | null
  paths: string[]
  activities: string[]
  authority_kind: string
  source_case_id: string
  source_message_id: string | null
  source_run_id: string | null
  created_by: string
  reason_summary: string | null
  created_at: string
  superseded_by: string | null
  invalidated_at: string | null
  invalidated_by: string | null
  invalid_reason: string | null
  availability?: string
  // P4-06b. 본문이 어디에 있는가 — `server` 면 어느 PC 의 실행에도 주입된다. `runner` 는 소유 PC 에만
  // 있는 옛 원문(이행 대기)이다. 권위 메시지도 같다(없으면 null).
  storage?: 'server' | 'runner'
  source_storage?: 'server' | 'runner' | null
  // P4-09(f), D-92. AI 후보의 읽지 못한 범위(원래 값). 있으면 주입되지 않고 채택 확인이 `scope_unreadable` 로
  // 막는다 — 활성화 폼에서 활동을 확인하면 풀린다. 사람이 활성화한 새 버전에는 없다.
  reported_scope?: { activities: string[]; paths: string[]; problem: string } | null
  scope_unreadable?: boolean
  // P4-07. 후보와 기존 항목의 관계(대체 제안·반증), 관측 문맥(당시 실행·저장소·기준 커밋·도구 —
  // Case 브랜치의 사실), 활성화 때의 QG-08 채택 확인. 옛 버전은 null(없음이지 값이 아니다).
  relation?: KnowledgeRelation | null
  relates_to_knowledge_id?: string | null
  relates_to_key?: string | null
  observed?: KnowledgeObserved | null
  adoption?: KnowledgeAdoption | null
  source_report_index?: number | null
  // UI-04a. 원래 대화로 이동(D-80) — 출처 대화의 제목과 권위 메시지의 순번. 본문·요약이 아니다.
  source_case_title?: string | null
  source_message_seq?: number | null
}

export type KnowledgeRelation = 'supports' | 'supersedes' | 'contradicts'

export const KNOWLEDGE_RELATION_LABEL: Record<KnowledgeRelation, string> = {
  supports: '뒷받침',
  supersedes: '대체 제안',
  contradicts: '반증',
}

export interface KnowledgeObserved {
  run_id?: string | null
  purpose?: string | null
  case_id?: string | null
  repository_id?: string | null
  repository_name?: string | null
  base_commit?: string | null
  tool_version?: string | null
  relates_to_version?: string | null
}

export interface KnowledgeAdoptionFinding {
  code: string
  blocking: boolean
  detail: string
}

export const KNOWLEDGE_ADOPTION_LABEL: Record<string, string> = {
  not_a_candidate: '후보가 아니다',
  content_unavailable: '적용 내용 원문이 서버에 없다',
  open_conflict: '열린 충돌이 있다',
  contradicts_active: '반증 대상이 아직 활성이다',
  target_not_active: '적용 대상이 활성·후보가 아니다',
  scope_widened: '범위를 넓힐 수 없다',
  no_evidence: '근거 실행이 없다(사유가 근거다)',
  scope_wider_than_observed: '관측한 저장소보다 넓은 범위다',
  obligation_raised: '참고 후보를 필수로 올린다',
  related_version_changed: '관계 대상이 그 뒤 새 버전이 됐다',
  independent_review_not_run: '독립 AI 검토는 돌리지 않았다',
  // P4-09(f), D-92.
  scope_unreadable: 'AI 가 적은 범위를 읽지 못했다 — 활동을 확인한다',
}

export interface KnowledgeAdoption {
  checked_at: string
  by: string
  findings: KnowledgeAdoptionFinding[]
  from_candidate: string
  into: string | null
  independent_review: string
  // P4-07b. 한 번에 활성화(사람의 결정)였다면 그때의 충족 항목과 근거 실행 id.
  auto_reference?: { met: string[]; evidence_runs: string[] } | null
}

export interface KnowledgeAdoptionCheck {
  knowledge_id: string
  version_id: string
  findings: KnowledgeAdoptionFinding[]
  blocked: string[]
  evidence_count: number
  related: { knowledge_key: string; version: number; state: KnowledgeState } | null
  into: { knowledge_key: string; version: number; state: KnowledgeState } | null
  independent_review: string
}

//: P4-07. 기존 항목에 더해진 근거(관측 실행). 참조·요약뿐이다.
export interface KnowledgeEvidence {
  id: string
  knowledge_id: string
  knowledge_key: string
  version_id: string | null
  kind: 'supports' | 'duplicate'
  source_run_id: string
  source_case_id: string
  source_report_index: number
  artifact_id: string
  artifact_rev: number
  summary: string
  recorded_by: string
  created_at: string
  storage: 'server' | 'runner'
  // UI-04a. 근거 실행의 대화 제목(이동용).
  source_case_title?: string | null
}

//: P4-07b. 참고 후보의 **자동 활성 조건**(여덟)의 충족/미충족 — 사용자 결정(2026-09-24): 반자동. 시스템은
//: 계산해 표시할 뿐이고 활성화는 사람이 `activateReady` 로 한 번에 한다. `ready` 는 판정·권한이 아니다.
export interface KnowledgeAutoReferenceFinding {
  code: string
  met: boolean
  detail: string
}

export interface KnowledgeAutoReference {
  knowledge_id: string
  knowledge_key: string
  version_id: string
  ready: boolean
  met: string[]
  unmet: string[]
  findings: KnowledgeAutoReferenceFinding[]
  evidence_runs: { run_id: string; purpose: string | null; ok_command: boolean }[]
}

export const KNOWLEDGE_AUTO_REFERENCE_LABEL: Record<string, string> = {
  candidate: '후보',
  reference: '효력 참고',
  observational_kind: '종류 운영 사실·알려진 문제',
  two_runs: '서로 다른 실행 둘 이상의 근거',
  verified_run: '종료 코드 0 명령의 검증·분석 실행',
  observed_repository: '관측한 저장소 범위',
  no_contradiction: '반증·충돌 없음',
  adoption_clear: '채택 확인 막음 없음',
}

export interface KnowledgeActivateReadyResult {
  project_id: string
  by: string
  activated: { knowledge_id: string; knowledge_key: string; version_id: string; version: number }[]
  skipped: { knowledge_id: string; knowledge_key: string; reason: 'not_ready' | 'refused'; unmet?: string[]; refusals?: string[] }[]
}

export interface KnowledgeItemView {
  id: string
  project_id: string
  knowledge_key: string
  created_by: string
  created_at: string
  current: KnowledgeVersion | null
  versions: KnowledgeVersion[]
  evidence?: KnowledgeEvidence[]
  // P4-07b. 현재 버전이 후보일 때만 있다(표시).
  auto_reference?: KnowledgeAutoReference | null
}

export interface KnowledgeConflict {
  id: string
  project_id: string
  knowledge_a: string
  knowledge_b: string
  key_a: string
  key_b: string
  state: 'open' | 'resolved'
  recorded_by: string
  reason_summary: string | null
  created_at: string
  resolved_at: string | null
  resolution_summary: string | null
}

export interface KnowledgeView {
  project_id: string
  items: KnowledgeItemView[]
  conflicts: KnowledgeConflict[]
  note: string
}

export interface RunKnowledgeRow {
  run_id: string
  version_id: string
  knowledge_id: string
  knowledge_key: string
  version: number
  summary: string
  obligation: KnowledgeObligation
  state: KnowledgeState
  decision: string
  scope_resolution: string | null
  context_seq: number | null
  source_seq: number | null
}

export interface RunKnowledgeView {
  run_id: string
  recorded: boolean
  items: RunKnowledgeRow[]
  note: string
}

//: 대화의 말·실행에서 등록한(또는 거부한·근거로 이은) 지식. 카드가 쓴다.
export interface KnowledgeRegistration {
  run_id: string
  report_index: number
  intake_state: 'registered' | 'refused' | 'evidence'
  refusal: string | null
  // P4-07. 어디서 왔는가 — 사용자 말(P4-06) / 논의 응답의 AI 제안 / 작업 실행의 후보.
  origin?: 'statement' | 'proposal' | 'extraction'
  authority_kind?: string | null
  relation?: KnowledgeRelation | null
  relates_to_key?: string | null
  basis?: string | null
  evidence?: { id: string; kind: 'supports' | 'duplicate'; summary: string; knowledge_key: string } | null
  observed?: KnowledgeObserved | null
  reported_summary: string | null
  created_at: string
  version_id: string | null
  knowledge_id: string | null
  knowledge_key: string | null
  version: number | null
  kind: KnowledgeKind | null
  obligation: KnowledgeObligation | null
  state: KnowledgeState | null
  summary: string | null
  scope_kind: string | null
  repository_name: string | null
  paths: string[]
  activities: string[]
  current_version?: number | null
  current_state?: KnowledgeState | null
  storage?: 'server' | 'runner'
  source_storage?: 'server' | 'runner' | null
  // UI-04a. 원래 메시지로 이동 — 권위 메시지(사용자 말)의 순번, 그 실행이 붙인 응답 메시지의 순번(작업
  // 실행은 메시지가 없어 null).
  source_message_seq?: number | null
  reply_seq?: number | null
  // P4-07b. 지금도 후보인 등록 행의 자동 활성 조건(표시).
  auto_reference?: KnowledgeAutoReference | null
  // P4-09(f), D-92. AI 후보의 읽지 못한 범위(원래 값) — 있으면 주입되지 않고 채택 확인이 막는다. 사유의 읽을 말.
  reported_scope?: { activities: string[]; paths: string[]; problem: string } | null
  refusal_text?: string | null
}

// P4-09(f), D-92. 등록 보고 항목의 내용 열람 — 거부된 행도 본다. 본문은 서버에 있을 때만(없으면 null 과 이유).
export interface KnowledgeIntakeDetail {
  case_id: string
  run_id: string
  report_index: number
  run_purpose: string | null
  intake_state: 'registered' | 'refused' | 'evidence' | 'unprocessed'
  summary: string | null
  refusal: string | null
  refusal_text: string
  knowledge_version_id: string | null
  evidence_id: string | null
  reported: {
    kind: string | null
    obligation: string | null
    summary: string | null
    repository: string | null
    paths: string[]
    activities: string[]
    basis: string | null
    relates_to: string | null
    relation: string | null
    supersedes: string | null
    proposal: boolean
    format_error: boolean
  }
  content: string | null
  content_note: string
  note: string
}

//: UI-04a. 이 업무의 실행들에 **제공된** 규칙(Manifest 집계, 버전별). 제공 기록이며 준수의 증거가 아니다.
export interface CaseKnowledgeUseItem {
  knowledge_id: string
  knowledge_key: string
  version: number
  version_id: string
  summary: string
  kind: KnowledgeKind
  obligation: KnowledgeObligation
  // 제공 당시의 상태(Manifest 그대로)와 그 버전의 지금 상태.
  state: KnowledgeState
  state_now: KnowledgeState
  authority_kind: string
  scope_kind: 'project' | 'repository'
  repository_name: string | null
  provided_runs: number
  skipped: Record<string, number>
  last_run_id: string | null
  last_run_purpose: string | null
  first_at: string
}

export interface CaseKnowledgeUse {
  case_id: string
  items: CaseKnowledgeUseItem[]
  runs_recorded: number
  runs_unrecorded: number
  note: string
}

//: 사람의 결정 종류(`decision.kind`)를 사람 말로. 서버의 `DecisionKind` 와 같은 목록이다.
export const DECISION_KIND_LABEL: Record<string, string> = {
  intent_agreement: '의도 동의',
  design_review: '설계 검토',
  plan_review: '계획 검토',
  final_acceptance: '최종 인수',
  exception_closure: '예외 수용 종료',
  push_approval: 'push 승인',
  publication_grant: '게시 허용',
  material_delta_confirmation: '동의된 의도의 변경 확인',
}

export const knowledgeApi = {
  list: (projectId: string) => request<KnowledgeView>(`/api/projects/${projectId}/knowledge`),

  // P4-09(f). 등록 보고 항목의 내용 열람(거부된 행 포함). 새 저장이 없다 — 서버가 가진 것을 읽는다.
  intakeDetail: (caseId: string, runId: string, index: number) =>
    request<KnowledgeIntakeDetail>(`/api/cases/${caseId}/knowledge-intake/${runId}/${index}`),

  // UI-04a. 이 업무의 실행들에 제공된 규칙(버전별 집계). 결정 사항 패널이 쓴다.
  caseUse: (caseId: string) => request<CaseKnowledgeUse>(`/api/cases/${caseId}/knowledge-use`),

  // UI-04a. 개정 — 새 버전(`user_registration`). 주지 않은 칸은 현재 버전 그대로. 새 내용은 출처 대화와
  // 출처 PC 가 필요하다(서버 본문 저장 경로, P4-06b).
  revise: (
    knowledgeId: string,
    body: {
      reason_summary: string
      content?: string | null
      case_id?: string | null
      target_runner_id?: string | null
      summary?: string | null
      kind?: KnowledgeKind | null
      obligation?: KnowledgeObligation | null
      scope_kind?: 'project' | 'repository' | null
      repository_id?: string | null
      paths?: string[] | null
      activities?: string[] | null
    },
  ) =>
    request<{ version: KnowledgeVersion }>(`/api/knowledge/${knowledgeId}/versions`, {
      method: 'POST',
      body: JSON.stringify({ actor: 'owner', ...body }),
    }),

  // 사람의 등록 — 권위 승계, 재승인 없음. **적용 내용은 서버에 저장된다**(P4-06b, 사용자 결정
  // 2026-09-24) — 비밀값을 적지 말라고 화면이 알린다. 등록은 실행 권한을 만들지 않는다.
  register: (
    caseId: string,
    body: {
      content: string
      summary: string
      kind: KnowledgeKind
      obligation: KnowledgeObligation
      target_runner_id: string
      repository_id?: string | null
      paths?: string[]
      activities?: string[]
      authority?: string
      state?: KnowledgeState
      reason_summary?: string | null
    },
  ) =>
    request<{ version: KnowledgeVersion }>(`/api/cases/${caseId}/knowledge`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // P4-07. 활성화는 QG-08 채택 확인을 지난다(막는 항목이면 409 와 코드). 범위·효력·활동은 좁힐 수만
  // 있고 `into_knowledge_id` 는 그 항목의 새 버전으로 적용한다. 확인만 보려면 `adoptionCheck`.
  activate: (
    knowledgeId: string,
    reason: string,
    options: {
      into_knowledge_id?: string | null
      obligation?: KnowledgeObligation | null
      scope_kind?: 'project' | 'repository' | null
      repository_id?: string | null
      paths?: string[] | null
      activities?: string[] | null
    } = {},
  ) =>
    request<{ version: KnowledgeVersion; adoption: KnowledgeAdoption | null }>(`/api/knowledge/${knowledgeId}/activate`, {
      method: 'POST',
      body: JSON.stringify({ reason_summary: reason, actor: 'owner', ...options }),
    }),

  adoptionCheck: (
    knowledgeId: string,
    intoKnowledgeId?: string | null,
    obligation?: KnowledgeObligation | null,
    scope?: { scope_kind?: 'project' | 'repository' | null; repository_id?: string | null },
    activities?: string[] | null,
  ) => {
    const params = new URLSearchParams()
    if (intoKnowledgeId) params.set('into_knowledge_id', intoKnowledgeId)
    if (obligation) params.set('obligation', obligation)
    // P4-09(f). 활동을 명시하면(빈 목록 포함) 읽지 못한 범위의 막음이 풀린 채로 본다.
    if (activities) params.set('activities', activities.join(','))
    if (scope?.scope_kind) params.set('scope_kind', scope.scope_kind)
    if (scope?.repository_id) params.set('repository_id', scope.repository_id)
    const query = params.toString()
    return request<KnowledgeAdoptionCheck>(`/api/knowledge/${knowledgeId}/adoption-check${query ? `?${query}` : ''}`)
  },

  // P4-07b. 자동 활성 조건(표시)만 다시 본다.
  autoReference: (knowledgeId: string) => request<KnowledgeAutoReference>(`/api/knowledge/${knowledgeId}/auto-reference`),

  // P4-07b. 조건 충족 후보를 **사람이 한 번에** 활성화한다 — 이 호출이 사람의 클릭이다. 화면이 본 항목 id 만
  // 보내고, 각 후보는 QG-08 채택 확인을 그대로 지난다(거부·미충족은 건너뛰어 결과에 적힌다). 효력 참고 그대로.
  activateReady: (projectId: string, knowledgeIds: string[]) =>
    request<KnowledgeActivateReadyResult>(`/api/projects/${projectId}/knowledge/activate-ready`, {
      method: 'POST',
      body: JSON.stringify({ actor: 'owner', knowledge_ids: knowledgeIds }),
    }),

  invalidate: (knowledgeId: string, reason: string) =>
    request<{ version: KnowledgeVersion }>(`/api/knowledge/${knowledgeId}/invalidate`, {
      method: 'POST',
      body: JSON.stringify({ reason_summary: reason, actor: 'owner' }),
    }),

  recordConflict: (projectId: string, a: string, b: string, reason: string) =>
    request<KnowledgeConflict>(`/api/projects/${projectId}/knowledge-conflicts`, {
      method: 'POST',
      body: JSON.stringify({ knowledge_a: a, knowledge_b: b, reason_summary: reason || null, actor: 'owner' }),
    }),

  resolveConflict: (conflictId: string, summary: string) =>
    request<KnowledgeConflict>(`/api/knowledge-conflicts/${conflictId}/resolve`, {
      method: 'POST',
      body: JSON.stringify({ reason_summary: summary, actor: 'owner' }),
    }),
}

export const RUN_CONTEXT_STATE_LABEL: Record<RunContextState, string> = {
  complete: '완전',
  partial: '부분',
  blocked: '핵심 미확인 — 실행 전 중단',
  not_reported: '미보고',
}

export interface CaseDetail extends Case {
  artifacts: ArtifactRef[]
  intent_versions: IntentVersion[]
  decisions: Decision[]
  // UI-01 부터 같은 응답에 실린다. P4-05 의 피드백 처리 카드가 쓴다.
  feedback?: FeedbackRecord[]
  runs: Run[]
  gate: GateResult
  quality_gates: QualityGateState
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
  // UI-01: 대화·현재 요청과 **지금 보낼 수 있는가·왜 아닌가.** 서버가 판정한다.
  conversation?: ConversationView
  // UI-01: 준비(`discussion`)·업무(`work`) 단계. NULL 은 UI-01 이전 Case 다.
  stage?: 'discussion' | 'work' | null
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
      // UI-01. 어느 사용자 요청을 처리하는 실행인가.
      request_id?: string
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
  | 'quality_gate_review'
  | 'limited_analysis'
  // P3-01. 설계와 계획은 서로 다른 목적이며 각각 독립된 검토를 받는다.
  | 'design_authoring'
  | 'plan_authoring'
  | 'feature_implementation'
  // P3-03. 검증은 구현과 **다른 목적**이다 — 완료 판정이 다르다. 구현은 작업공간
  // 변화가 있어야 완료이고, 검증은 실제로 실행된 명령이 있어야 완료다.
  | 'verification_run'
  // UI-01. 대화의 논의 응답. 읽기 전용이며 요청(request_id)에 묶인다.
  | 'discussion_reply'

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

export interface RemediationCycle {
  id: string
  repair_limit: number
  used_attempts: number
  reserved_attempts: number
  state: 'active' | 'passed' | 'exhausted'
}

export interface QualityGateRun {
  id?: string
  legacy_qg01?: boolean
  verdict: GateVerdict
  status?: 'running' | 'completed' | 'blocked'
  validity?: 'current' | 'needs_recheck' | 'historical'
  inspection_required?: 'rule' | 'light' | 'independent'
  inspection_used?: 'rule' | 'light' | 'independent'
  // P4-02. 늦게 도착해 **원래 실행에만** 귀속된 결과인가. 현재 정책의 통과가
  // 아니며 새 수정 차수도 만들지 않는다.
  late_result?: boolean
  stop_requested_at?: string | null
}

/** P4-02. 아직 반영되지 않은 설정 변경. 현재 정책과 **합치지 않는다.** */
export interface ReservedGatePolicy {
  policy_id: string
  revision: number
  task_key: string | null
  setting: 'on' | 'off' | 'inherit'
  inspection: 'rule' | 'light' | 'independent' | null
  repair_limit: number | null
  requested_at: string
  requested_by: string
  reason: string
  apply_after_run_id: string | null
  apply_boundary: 'immediate' | 'verification_end' | null
}

export interface QualityGatePolicy {
  gate: string
  label: string
  task_key: string | null
  setting: 'required' | 'on' | 'off' | 'not_applicable'
  applied: boolean
  inspection_required: 'rule' | 'light' | 'independent'
  source: string
  reason: string
  repair_limit: number
  // P4-02. 요청 시각과 실제 적용 시각은 다를 수 있다. 예약을 거쳐 반영된
  // 설정이 그렇다. 사람이 설정한 적이 없으면 둘 다 null 이다.
  requested_at: string | null
  applied_at: string | null
  apply_boundary: 'immediate' | 'verification_end' | null
  reserved: ReservedGatePolicy[]
  running_gate_run_id: string | null
  latest_run: QualityGateRun | null
  remediation: RemediationCycle | null
}

export interface QualityGateState {
  case_id: string
  task_key: string | null
  gates: QualityGatePolicy[]
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
  quality_gate_not_passed: '명시한 품질 게이트를 현재 입력에서 통과하지 않았다',
  quality_gate_policy_changed:
    '요청이 기대한 게이트 정책이 저장과 배정 사이에 바뀌었다',
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
  // UI-01. 준비 단계와 사용자 요청.
  case_in_discussion_stage: '아직 준비 단계 대화다 — 업무화 뒤에 배정한다',
  request_required: '논의 응답은 어떤 요청에 대한 응답인지가 있어야 한다',
  request_not_processing: '그 요청은 이미 끝났다 — 끝난 요청에 실행을 붙이지 않는다',
  request_original_not_stored: '요청을 연 메시지를 PC가 아직 저장하지 않았다',
  request_instruction_mismatch: '논의 응답의 지시는 그 요청을 연 메시지여야 한다',
  // P4-04. 핵심 입력을 빼고 실행하지 않는다.
  context_over_inline_limit:
    '지시와 핵심 입력만으로 한 실행의 크기 한도를 넘는다 — 나누거나 한도를 조정해야 한다',
  required_context_unavailable: '핵심 입력의 원문을 지금 읽을 수 없다 (저장 대기·유실)',
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
  // **어떻게 충족했는가**(P3-R4). `null` 은 R4 이전 기록이며 "바꾸고 확인했다"가
  // 아니라 그때는 묻지 않았다는 뜻이다.
  satisfaction: string | null
  // 이 판정이 이전 버전에서 이어진 것인가. `carried_from:<id>` 다.
  recheck_source: string | null
  // **P4-03 목적 의무.** 이 기준이 무엇을 입증하는가. `null` 은 정의판 v1 기준이다.
  obligation: CriterionObligation | null
  // 원문이 적었는가(`reported`), 연결 항목에서 정의로 도출했는가.
  obligation_source: 'reported' | 'derived_from_field' | null
  // 원인·조사 기준의 결론 요구. 저장값과 **적용되는 값**을 따로 준다 — NULL 은 확정
  // 필수로 취급한다.
  conclusion_rule: ConclusionRule | null
  conclusion_rule_effective: ConclusionRule | null
  conclusion: 'determined' | 'inconclusive' | null
}

export type CriterionObligation =
  | 'behavior'
  | 'restoration'
  | 'cause'
  | 'answer'
  | 'improvement'
  | 'preservation'
  | 'target_state'

export type ConclusionRule = 'definitive_required' | 'bounded_report_allowed'

export const SATISFACTION_LABEL: Record<string, string> = {
  changed_and_verified: '바꾸고 확인함',
  already_satisfied: '변경 없이 이미 목표 상태 (검증 실행이 관측)',
  not_reproduced: '재현하지 못함 — 해결의 증거가 아니다',
  investigated: '조사·실험의 근거로 답함 (코드 산출물 없음)',
  preserved: '보존 계약·조건이 그대로임을 검증함',
}

export const OBLIGATION_LABEL: Record<CriterionObligation, string> = {
  behavior: '합의한 동작·결과',
  restoration: '기대 동작 복원',
  cause: '원인 질문에 대한 결론',
  answer: '조사 질문에 대한 결론',
  improvement: '구조·품질 개선',
  preservation: '보존 계약·조건 유지',
  target_state: '유지 대상의 목표 상태',
}

/**
 * 의무별로 `met` 에 쓸 수 있는 충족 방식. **서버의 `MET_SATISFACTION` 과 같아야 한다**
 * (domain/completion_meaning.py). 화면은 고를 수 있는 것만 보이고, 판단은 서버가 한다.
 */
export const MET_SATISFACTION_BY_OBLIGATION: Record<CriterionObligation, string[]> = {
  behavior: ['changed_and_verified', 'already_satisfied'],
  restoration: ['changed_and_verified', 'already_satisfied'],
  cause: ['investigated'],
  answer: ['investigated'],
  improvement: ['changed_and_verified', 'already_satisfied'],
  preservation: ['preserved'],
  target_state: ['changed_and_verified', 'already_satisfied'],
}

export const CONCLUSION_LABEL: Record<string, string> = {
  determined: '확정',
  inconclusive: '판단 불가',
}

export const CONCLUSION_RULE_LABEL: Record<ConclusionRule, string> = {
  definitive_required: '확정 결론 필수',
  bounded_report_allowed: '근거·한계 보고면 판단 불가도 정상',
}

export const EXPERIMENT_CLEANUP_LABEL: Record<string, string> = {
  restored_in_run: '실행 안에서 되돌림',
  restored_later: '뒤 실행이 되돌린 상태를 관측',
  left_changes: '임시 변경이 남음',
  unobserved: '관측 없음 — 정리됐는지 모른다',
  no_write_permission: '읽기 권한 실행',
  not_finished: '아직 끝나지 않음',
}

/** 결과 조회의 `completion_meaning`(P4-03). 저장값이 아니라 도출값이다. */
export interface CompletionMeaning {
  contract: 'profile_completion_contract' | null
  profile: string | null
  profile_version: string | null
  detail: string | null
  declared_objectives: CriterionObligation[] | null
  objectives: {
    obligation: CriterionObligation
    required: boolean
    required_by: string[]
    criteria: string[]
    total: number
    met: number
    status: 'missing' | 'met' | 'open'
  }[]
  missing: CriterionObligation[]
  experiments: {
    run_id: string
    repository_id: string | null
    cleanup: string
    restored_by: string | null
    outside_workspace_changed: boolean | null
  }[]
  residue: string[]
  residue_blocks_auto_completion: boolean
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
  // P4-03. 후보가 본 목적별 충족 현황. 완료 계약이 없는 Case(v1)는 `null` 이다.
  meaning: {
    objectives: { obligation: CriterionObligation; required: boolean; criteria: string[]; met: number; status: string }[]
    missing: CriterionObligation[]
    residue: string[]
    residue_blocks_auto_completion: boolean
  } | null
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
  completion_meaning: CompletionMeaning
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
  objective_without_criteria:
    '요구된 목적에 기준이 하나도 없다 — 예외 대상이 아니며 의도·기준을 고쳐야 한다',
  experiment_residue_unresolved:
    '정리되지 않은 실험의 임시 변경이 있다 — 자동 완료하지 않는다(사람은 보고 판단할 수 있다)',
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
      // P3-R4·P4-03. 어떻게 충족했는가와 원인·조사 기준의 결론.
      satisfaction?: string | null
      conclusion?: string | null
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
  // P4-04. 적용되는 등급·인라인 여부. `*_recorded = false` 는 P4-04 이전 참조다.
  tier: 'core' | 'supporting'
  tier_recorded: boolean
  inclusion: 'inline' | 'omitted_size_limit'
  inclusion_recorded: boolean
  byte_size: number
  // Runner 가 실제로 읽었는가. `null` 은 영수증이 없다는 뜻이며 읽음이 아니다.
  receipt_status: 'read' | 'missing' | 'hash_mismatch' | 'omitted' | null
}

export const CONTEXT_ROLE_LABEL: Record<string, string> = {
  previous_intent: '직전 의도 초안',
  agreed_intent: '동의된 의도 원문',
  previous_design: '직전 설계안',
  current_design: '현재 설계안',
  previous_plan: '직전 개발계획',
  feedback: '미해결 피드백',
  current_plan: '현재 개발계획',
  question_answer: '질문 답변',
  original_request: '요청 원문',
  conversation_user_message: '대화 — 사용자 말',
  conversation_assistant_message: '대화 — AI 말',
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
  progressor_remediation: '진행기 수정 사이클(검증 미충족)',
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
  // P3-04. 이 작업이 어느 저장소를 바꾸는가. null 은 **미기록**이며 "주 저장소"가
  // 아니다. repository_ref 가 비어 있지 않은데 이름이 없으면 계획이 적은 이름을
  // 이 업무의 선택 안에서 찾지 못한 것이다 — 조용히 버리지 않고 그대로 보인다.
  repository_id: string | null
  repository_name: string | null
  repository_ref: string
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
  // 그 시점 트리 내용의 **지문(해시)**. 조합이 이것으로 스냅샷을 고정한다(P3-R2).
  tree_digest_before?: string
  tree_digest_after?: string
  // UI-04c(D-89). Runner 가 CLI 를 부르기 전에 직전 실행의 지문과 대조한 결과. `null` 은 대조하지 않았다.
  external_change_before_run?: boolean | null
  external_change_basis_run_id?: string | null
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
  // UI-04c(D-89). Runner 가 CLI 를 부르기 **전에** 직전 지문과 대조한 결과. `null` 은 대조하지 않았다
  // (직전 실행 없음·옛 Runner)이며 `false` 가 아니다.
  external_change_before_run?: boolean | null
  external_change_basis_run_id?: string | null
  // 어느 저장소의 실행인가(P3-R2). `repository_recorded` 가 false 면 **모른다**이며
  // 아무 저장소에나 붙이지 않는다.
  repository_id: string | null
  repository_recorded?: boolean
}

// UI-04c(D-89). 작업 PC 에서 폴더·편집기를 열어 달라는 요청 한 건. 경로는 서버의 작업공간 행이다.
export interface WorkspaceOpenRequest {
  id: string
  case_id: string
  repository_id: string
  runner_id: string
  target: 'folder' | 'editor'
  requested_by: string
  state: 'pending' | 'done' | 'failed' | 'expired'
  result_reason: string | null
  requested_at: string
  delivered_at: string | null
  finished_at: string | null
}

export const OPEN_STATE_LABEL: Record<string, string> = {
  pending: '작업 PC 에 전달 대기',
  done: '작업 PC 에서 열림',
  failed: '열지 못함',
  expired: '전달되지 않아 만료됨',
}

export const OPEN_SUPPORT_LABEL: Record<string, string> = {
  verified: '이 PC 에서 확인됨',
  unsupported: '이 PC 는 지원하지 않음',
  unknown: '이 PC 는 보고하지 않음',
  doc_only: '문서만 있음(확인 안 됨)',
}

// UI-04d(D-77). `awaiting_basis` — 사용자 트리에 커밋하지 않은 변경이 있어 사람이 시작 기준을 고르는 중(만들어지지 않음).
export type WorkspaceState = 'requested' | 'ready' | 'failed' | 'awaiting_basis'

// UI-04d(D-77). 어떤 코드에서 시작했는가. `null` 은 기록 없음(옛 작업공간·아직 안 정함)이며 `committed` 가 아니다.
// P4-09(c). `previous_result` — 후속 대화가 이전 업무 결과(그 대화 브랜치의 끝 커밋)에서 시작했다(D-77 마지막 문장).
export type StartBasis = 'committed' | 'include_uncommitted' | 'previous_result'

export const START_BASIS_LABEL: Record<StartBasis, string> = {
  committed: '커밋된 코드에서 시작',
  include_uncommitted: '커밋하지 않은 변경을 포함해 시작',
  previous_result: '이전 업무 결과에서 시작',
}

// 미커밋 변경 목록(메모리 중계). `available` 이 거짓이면 서버에 없다(재시작·만료) — PC 에서 다시 불러온다.
export interface UncommittedList {
  case_id: string
  repository_id: string
  state: WorkspaceState
  start_basis: StartBasis | null
  head: string | null
  digest: string | null
  entry_count: number | null
  available: boolean
  entries: { status: string; path: string }[] | null
  truncated: boolean | null
  stale_choice: boolean
  note: string
  // P4-09(c). 이전 업무 결과의 선택지 — HEAD 에 없는 이전 대화 브랜치의 끝 커밋. 없으면 빈 값.
  previous_case_id?: string | null
  previous_case_title?: string | null
  previous_branch?: string
  previous_commit?: string
}

// 저장소 **하나**의 작업공간(P3-R2·D-39).
export interface RepositoryWorkspace {
  case_id: string
  repository_id: string
  repository_name: string
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
  // 무엇을 근거로 이 작업공간을 만들었는가. `implicit_single_repository` 는
  // 선택 기록이 없는 이행된 Case 이며, **없던 선택을 만들어 적지 않는다**.
  allowance_source: string
  run_effects: RunEffectRow[]
  outside_workspace_changed: boolean
  // UI-04c(D-89). 이 작업공간을 만든 **작업 PC**(브라우저 PC 와 같다고 가정하지 않는다)와 그 PC 의 열기
  // 지원·최근 열기 요청. `runner` 가 null 이면 소유 PC 를 기록하지 않은 옛 작업공간이다.
  runner_id?: string | null
  runner?: { runner_id: string; name?: string; host: string | null; connection: RunnerConnectionState | null } | null
  open_support?: Record<'open_folder' | 'open_editor', { state: string; source: string }>
  open_requests?: WorkspaceOpenRequest[]
  // UI-04d(D-77). 시작 기준(서버 값 그대로). 포함이면 `base_commit` 이 스냅샷 커밋이고 `committed_base` 가 그때의 HEAD 다.
  start_basis?: StartBasis | null
  // P4-09(c). 이전 업무 결과의 관측·선택 — 이전 대화·브랜치·끝 커밋. 없으면 빈 값.
  previous_case_id?: string | null
  previous_case_title?: string | null
  previous_branch?: string
  previous_commit?: string
  basis_decided_by?: string | null
  basis_decided_at?: string | null
  committed_base?: string
  included_entries?: number | null
  included_tree_digest?: string
  basis_tree_digest?: string
  basis_entries?: number | null
}

// 저장소별 작업공간 전부와 조합·선택을 담은 조회 결과(P3-R2).
export interface WorkspaceView {
  case_id: string
  workspaces: RepositoryWorkspace[]
  // **부분 준비를 완전 준비로 읽지 않는다.** 하나라도 실패·대기면 false 다.
  all_ready: boolean
  ready_count: number
  repository_count: number
  // 대상 저장소가 기록되지 않은 실행. 숨기지 않고 따로 보인다.
  unattributed_run_effects: RunEffectRow[]
  composition: CodeComposition | null
  selection: CaseRepositoryState
  isolation: string
  // 한계 문구는 **서버가 준다.** 화면이 지어내면 언젠가 "격리됨"으로 바뀐다.
  isolation_note: string
}

// --------------------------------------------------- P3-R2 코드 조합
//
// `Repo ID → 정확한 스냅샷 참조` 의 벡터(execution-workspace-review 2.1절).

export interface CodeCompositionEntry {
  repository_id: string
  repository_name: string
  base_commit: string
  head_commit: string
  // `null` 은 **관측하지 않았다**이며 0이 아니다.
  dirty_entries: number | null
  tree_digest: string
  source: 'run_effect' | 'workspace_base'
  observed_run_id: string | null
  observed_at: string | null
  // 기준 커밋만 있고 지금 상태는 모른다.
  snapshot_incomplete: boolean
}

export interface CompositionValidity {
  composition_id: string | null
  linked: boolean
  // 이 조합에 **든** 저장소만 본다. 무관한 저장소의 변경은 stale 이 아니다.
  changed_repositories?: string[]
  stale?: boolean
  detail: string
}

export interface CodeComposition {
  id: string
  case_id: string
  revision: number
  composition_hash: string
  entries: CodeCompositionEntry[]
  covers_all_code_repositories: boolean
  snapshot_complete: boolean
  // **개별 저장소 통과가 통합 통과가 아니다.**
  integration_verified: boolean
  integration_detail?: string
  matches_current_state?: boolean
  state: string
  created_at: string
}

export const WORKSPACE_STATE_LABEL: Record<WorkspaceState, string> = {
  requested: '요청됨 (아직 만들어지지 않음)',
  ready: '준비됨',
  failed: '준비 실패',
  awaiting_basis: '시작 기준 선택 대기 (아직 만들어지지 않음)',
}

export const workspaceApi = {
  state: (caseId: string) => request<WorkspaceView | null>(`/api/cases/${caseId}/workspace`),

  // 작업공간을 준비해 달라고 기록한다. **응답은 준비 완료가 아니다** —
  // Runner 가 실제로 만든 뒤에야 `ready` 가 된다.
  prepare: (caseId: string, baseRef = 'HEAD', repositoryId?: string) =>
    request<RepositoryWorkspace>(`/api/cases/${caseId}/workspace`, {
      method: 'POST',
      body: JSON.stringify({ base_ref: baseRef, repository_id: repositoryId ?? null }),
    }),

  // 지금 상태로 코드 조합을 **고정한다.** 같은 상태면 새 revision 을 만들지 않는다.
  buildComposition: (caseId: string) =>
    request<CodeComposition | null>(`/api/cases/${caseId}/composition`, { method: 'POST' }),

  // UI-04c(D-89). 작업 PC 에서 폴더·편집기를 열어 달라고 남긴다. **응답은 열렸다는 뜻이 아니다** — 결과는
  // 작업공간 조회의 `open_requests` 에 온다. 미연결·미지원은 409 다. 경로는 보내지 않는다.
  open: (caseId: string, repositoryId: string, target: 'folder' | 'editor') =>
    request<WorkspaceOpenRequest>(`/api/cases/${caseId}/workspaces/${repositoryId}/open`, {
      method: 'POST',
      body: JSON.stringify({ target, requested_by: 'owner' }),
    }),

  // UI-04d(D-77). 미커밋 변경 목록 — 서버 메모리에서 온다(저장되지 않는다). 없으면 `available: false`.
  uncommitted: (caseId: string, repositoryId: string) =>
    request<UncommittedList>(`/api/cases/${caseId}/workspaces/${repositoryId}/uncommitted`),

  // 사람의 시작 기준 선택. `seen_digest` 는 본 목록의 지문이다 — 다르면 서버가 409 로 거부한다.
  decideBasis: (caseId: string, repositoryId: string, basis: StartBasis, seenDigest: string) =>
    request<RepositoryWorkspace>(`/api/cases/${caseId}/workspaces/${repositoryId}/start-basis`, {
      method: 'POST',
      body: JSON.stringify({ basis, actor: 'owner', seen_digest: seenDigest }),
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
  // UI-04b. 프로젝트 설정 화면의 기본값이 이 Case 의 첫 행(또는 복귀)이 된 경우.
  project_default: '프로젝트 기본값',
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
  // **이 한도가 지금 약속하는 것**(P3-R3). 행의 `enforcement` 는 설정 시점의 값이고
  // 이쪽이 현재 판정이다. `absolute` 만 절대 상한이다.
  guarantee?: string
}

// 지표 하나의 소비. **`exposure` 가 한도 판정값이다** — 확정 사용량만 보면
// 진행 중 실행과 결과 불명이 공짜가 된다(P3-R3).
export interface BudgetMetricUsage {
  metric: string
  unit: string
  settled: number
  held: number
  unresolved: number
  exposure: number
  reservation: string
  measurement: string
  runs_counted: number
  runs_unknown: number
  runs_in_flight: number
  // `false` 면 이 수가 소비 전부가 아니다. **모자란 만큼을 0으로 채우지 않는다**(D-61).
  complete: boolean
}

export interface BudgetStop {
  stopped: boolean
  metrics: Array<{
    metric: string
    limit_value: number
    unit: string
    exposure: number
    guarantee: string
    complete: boolean
  }>
  detail: string
  resume: string | null
}

export interface BudgetReservationRow {
  id: string
  run_id: string
  generation: number
  metric: string
  reserved_value: number | null
  // `null` 은 **아직 모른다**이며 0이 아니다.
  actual_value: number | null
  measurement: string
  reservation_kind: string
  role: string
  purpose: string
  state: string
  source: string
  settle_source: string | null
}

export interface BudgetReservationContract {
  measurement: string
  reservation: string
  hard_guarantee: string
  reason: string
}

export interface BudgetState {
  unlimited: boolean
  limits: BudgetLimit[]
  history: BudgetLimit[]
  usage: Record<string, BudgetMetricUsage>
  usage_detail: string
  by_role: Record<string, Record<string, { settled: number; unknown_rows: number; rows: number }>>
  by_purpose: Record<string, Record<string, { settled: number; unknown_rows: number; rows: number }>>
  warnings: Array<{ metric: string; limit_value: number; unit: string; exposure: number; detail: string }>
  stop: BudgetStop
  reservations: BudgetReservationRow[]
  measurement_contract: Record<string, string>
  reservation_contract: Record<string, BudgetReservationContract>
  repair_limit_note: string
  enforcement: EnforcementNote
}

export interface ControlledCheckpointRow {
  // **도출된 요구는 아직 행이 없다**(P3-R4). Autonomy 가 기록되지 않아 controlled 로
  // 취급되는 Case 의 요구는 사람이 실제로 확인할 때 행이 된다 — 조회가 쓰기를 하지
  // 않게 하면서도 없음을 통과로 읽지 않기 위해서다.
  id: string | null
  derived?: boolean
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
  // 허용 내 자동 추가의 결과(P3-R2). 허용 밖은 여기 오지 않고 거절된다.
  auto_selection?: { repository_id: string; changed: boolean; detail: string }
}

export interface DelegationBasisRow {
  revision: number
  basis_kind: string
  summary: string
  content_hash: string | null
  state: string
  recorded_at: string
}

export interface FastLaneState {
  eligible: boolean
  blockers: { reason: string; detail: string }[]
}

export interface ConformanceState {
  intent_version_id: string | null
  // **실제로 한 방식.** `null` 은 아직 확인하지 않았다는 뜻이며 통과가 아니다.
  method: string | null
  verdict: string
  required_method: string
  independent_review_required: boolean
  reasons: { reason: string; detail: string }[]
  // **가벼운 확인이 보지 않은 것.** 이 문장이 없으면 두 방식이 같은 통과로 보인다.
  unverified_scope: string | null
  checks: { method: string; verdict: string; run_id: string | null }[]
}

export interface MaterialDeltaRow {
  id: string
  change_class: string
  target_key: string
  materiality: string
  state: string
  detail: string
  ai_assessment: string | null
  detected_at: string
}

export interface MaterialDeltaState {
  basis: DelegationBasisRow | null
  pending: MaterialDeltaRow[]
  all: MaterialDeltaRow[]
  blocked_task_keys: string[]
  blocks_all_tasks: boolean
  detail: string
}

export interface CasePolicy {
  case_id: string
  revision: number
  // `null` 은 기록되지 않음이다. 화면이 기본값으로 채우지 않는다.
  autonomy: Autonomy | null
  autonomy_source: string
  autonomy_recorded: boolean
  policy_version: string
  // UI-04b. 이 프로젝트의 새 Case 가 받을 기본값과 그 출처(`project_default` | `system_default`) — 복귀하면
  // 무엇이 되는가. 이 Case 에 적용된 값이 아니다.
  default_autonomy: Autonomy
  default_autonomy_source?: string
  work_depth: string | null
  work_depth_source: string
  completion_mode: string
  // **어디서 온 값인가**(P3-R4). 사람이 정한 설정과 Autonomy 에서 도출한 값을
  // 같은 모양으로 보이면 고르지 않은 자동 완료가 사용자의 설정처럼 읽힌다.
  completion_mode_source: string
  // **적용되는** Autonomy. 저장된 값과 다를 수 있는 경우가 정확히 하나다 —
  // R1 이전 Case 는 미기록이지만 controlled 로 취급된다(사용자 결정 2026-09-22).
  effective_autonomy: Autonomy
  effective_source: string
  is_treatment: boolean
  fast_lane: FastLaneState
  conformance: ConformanceState
  material_delta: MaterialDeltaState
  profile: CaseProfileState
  checkpoints: ControlledCheckpointRow[]
  budget: BudgetState
  // P4-05b. 진행기 상한과 출처.
  progress_limits?: ProgressLimitsView
  delegation_basis: { current: DelegationBasisRow | null; history: DelegationBasisRow[]; detail: string }
  repositories: CaseRepositoryState
  enforcement: Record<string, EnforcementNote>
  case_status: string
}

export const CONFORMANCE_METHOD_LABEL: Record<string, string> = {
  light: '가벼운 확인 (구조·참조·버전의 결정적 검사)',
  independent: '독립 의미 검토 (작성과 별도 세션의 AI)',
}

export const MATERIALITY_LABEL: Record<string, string> = {
  material: '확인 필요',
  user_directed: '사용자 지시 · 위임 기준 갱신',
  draft_work: '초안 작업',
}

export const COMPLETION_SOURCE_LABEL: Record<string, string> = {
  case_explicit: '사람이 정한 설정',
  migrated_explicit: '사람이 정한 설정 (R4 이전)',
  autonomy_derived: 'Autonomy 에서 도출',
}

export const CHECKPOINT_LABEL: Record<string, string> = {
  start_scope: '시작 범위 확인 (목표·범위·기준·허용 행동)',
  result_candidate: '결과 후보 확인 (게시 전)',
}

export const progressionApi = {
  /** 가벼운 요청 정합성 확인을 기록한다. **독립 검토로 표시되지 않는다**(D-25). */
  lightConformance: (caseId: string, intentVersionId: string) =>
    request<ConformanceState>(`/api/cases/${caseId}/conformance-checks/light`, {
      method: 'POST',
      body: JSON.stringify({ intent_version_id: intentVersionId }),
    }),
  /** 사람이 누적 변경 한 건을 확인한다. 남은 변경은 그대로 남는다(D-60). */
  confirmDelta: (caseId: string, deltaId: string, actor = 'owner') =>
    request<MaterialDeltaState>(
      `/api/cases/${caseId}/material-deltas/${deltaId}/confirmation`,
      {
        method: 'POST',
        body: JSON.stringify({ actor, explicit: true }),
      },
    ),
  /** 이 Case 에 독립 의미 검토를 요구한다. **올리는 방향으로만 작용한다.** */
  requireIndependentReview: (caseId: string, required: boolean, reason: string) =>
    request<ConformanceState>(`/api/cases/${caseId}/conformance-policy`, {
      method: 'PUT',
      body: JSON.stringify({ required, set_by: 'owner', reason }),
    }),
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

  confirmCheckpoint: (
    caseId: string,
    checkpoint: string,
    subjectId: string,
    note: string,
    // **무엇을 보고 확인했는가**(P3-R4·FR-23). 이 해시가 없으면 나중에 내용이
    // 바뀌었는지 알 수 없고, 바뀐 후보가 옛 확인으로 종료된다.
    subjectHash?: string | null,
  ) =>
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
          subject_hash: subjectHash ?? null,
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

  // UI-04b. Autonomy 를 기본값(프로젝트 → 시스템)으로 되돌린다 — 새 리비전이며 출처는 그 기본값이다.
  resetAutonomy: (caseId: string, reason: string) =>
    request<CasePolicy>(`/api/cases/${caseId}/autonomy/reset`, {
      method: 'POST',
      body: JSON.stringify({ set_by: 'owner', reason_summary: reason || null }),
    }),

  // UI-04b. 프로젝트 기본 예산을 이 업무에 다시 적용한다(같은 지표·경계 대체). 없으면 `applied = 0`.
  applyProjectBudgetDefaults: (caseId: string) =>
    request<BudgetState & { applied: number }>(`/api/cases/${caseId}/budget/project-defaults`, {
      method: 'POST',
      body: JSON.stringify({ set_by: 'owner' }),
    }),
}

// ===================================================================== UI-04b
//
// 프로젝트 기본값(D-72 · autonomy-budget-policy 5절의 Project 층)과 Case 상세 설정이 쓰는 조회·변경.
// **설정은 실행 허용·동의·인수가 아니다.** 값·출처·적용 시점은 서버가 준 그대로 보인다.

export type ProjectSettingSource = 'project_setting' | 'system_default' | 'registration'

export interface ProjectSettingRow {
  id: string
  project_id: string
  revision: number
  setting_key: string
  value: string | number
  set_by: string
  reason_summary: string | null
  state: 'current' | 'superseded'
  created_at: string
  superseded_at: string | null
}

export interface ProjectSettingValue {
  value: string | number | null
  source: ProjectSettingSource
  setting: ProjectSettingRow | null
  system_default: string | number | null
}

export interface ProjectBudgetDefault {
  key: string
  metric: string
  threshold_kind: string
  limit_value: number
  unit: string
  guarantee: string
  setting: ProjectSettingRow
}

export interface ProjectSettingsView {
  project_id: string
  name: string
  default_tool_id: string
  tool_verified_on: { runner_id: string; host: string; state: string }[]
  model: { value: null; note: string }
  depth: { value: null; note: string }
  settings: Record<string, ProjectSettingValue>
  budget_defaults: ProjectBudgetDefault[]
  budget_metrics: Record<string, { unit: string; hard_guarantee: string }>
  ranges: { progress_limit: { min: number; max: number } } & Partial<Record<ProgressLimitKey, { min: number; max: number }>>
  history: ProjectSettingRow[]
  applies_to: string
  note: string
}

export const PROJECT_SETTING_LABEL: Record<string, string> = {
  default_tool_id: '기본 도구(CLI)',
  default_autonomy: '기본 확인 경계(Autonomy)',
  repair_limit: '재작성 상한',
  task_retry_limit: '재시도 상한',
  remediation_limit: '검증 미충족 수정 사이클 한도',
  run_timeout_seconds: '실행 제한 시간',
  context_inline_limit_bytes: '실행당 인라인 한도(바이트)',
}

export const PROJECT_SETTING_SOURCE_LABEL: Record<ProjectSettingSource, string> = {
  project_setting: '프로젝트 설정',
  system_default: '시스템 기본값',
  registration: '등록 시 값',
}

export const projectSettingsApi = {
  get: (projectId: string) => request<ProjectSettingsView>(`/api/projects/${projectId}/settings`),

  // `null` 은 기본값 복귀(현재 행을 닫는다). 하나라도 잘못되면 422 이고 아무 것도 저장되지 않는다.
  set: (projectId: string, values: Record<string, string | number | null>, reason: string) =>
    request<ProjectSettingsView>(`/api/projects/${projectId}/settings`, {
      method: 'PUT',
      body: JSON.stringify({ values, set_by: 'owner', reason_summary: reason || null }),
    }),
}

export interface ProjectRepositoryView {
  project_id: string
  repositories: ProjectRepository[]
  journal_repository_id: string | null
  legacy_repo_path: string
  legacy_repo_path_matches_registry: boolean
}

export const repositoryApi = {
  project: (projectId: string) => request<ProjectRepositoryView>(`/api/projects/${projectId}/repositories`),

  // 등록은 선택도 허용도 아니다(D-38).
  register: (projectId: string, name: string, repoPath: string) =>
    request<ProjectRepository>(`/api/projects/${projectId}/repositories`, {
      method: 'POST',
      body: JSON.stringify({ name, repo_path: repoPath, registered_by: 'owner' }),
    }),

  // 기록 이슈를 만들 저장소. 코드 대상이 아니다(D-17).
  setJournal: (projectId: string, repositoryId: string) =>
    request<ProjectRepositoryView>(`/api/projects/${projectId}/journal-repository`, {
      method: 'PUT',
      body: JSON.stringify({ repository_id: repositoryId }),
    }),

  // Case 의 저장소 선택. **쓰기·게시 허용을 명시로 받는다**(기본값 없음, D-64).
  select: (caseId: string, repositoryId: string, codeWrite: boolean, publish: boolean, reason: string) =>
    request<CaseRepositoryState>(`/api/cases/${caseId}/repositories`, {
      method: 'PUT',
      body: JSON.stringify({
        repository_id: repositoryId,
        selection_source: 'explicit',
        code_write_allowed: codeWrite,
        publish_allowed: publish,
        selected_by: 'owner',
        reason_summary: reason || null,
      }),
    }),
}

export const qualityGateApi = {
  // QG-02~07 의 적용·검사 강도·수정 한도. 사유가 필수이며 강도를 낮추는 요청은 서버가 거부한다(P4-01·02).
  setPolicy: (
    caseId: string,
    gate: string,
    body: {
      setting: 'on' | 'off' | 'inherit'
      inspection: string | null
      repair_limit: number | null
      reason: string
      // UI-05a. 작업 범위 설정(QG-03·04 의 대기 카드는 그 작업에서만 끄거나 한도를 올린다). 비우면 업무 전체.
      task_key?: string
    },
  ) =>
    request<QualityGateState>(`/api/cases/${caseId}/quality-gates/${gate}/policy`, {
      method: 'PUT',
      body: JSON.stringify({
        task_key: body.task_key ?? '',
        setting: body.setting,
        inspection: body.inspection,
        repair_limit: body.repair_limit,
        actor: 'owner',
        reason_summary: body.reason,
      }),
    }),
}


// ===================================================================== UI-01
//
// 대화·요청 기반. **화면은 보낼 수 있는지를 판단하지 않는다** — `send.general` 은
// 서버가 실제로 적용하는 판정과 같은 값이고, 버튼을 비활성화해도 서버가 같은 이유로
// 거부한다(FR-11). 초안의 브라우저 저장·복구(D-83)는 기본 대화 화면(web/src/lib/drafts.ts)이 한다.

export type MessageReceipt = 'pending' | 'stored' | 'lost_before_persist'
export type RequestState = 'processing' | 'completed' | 'failed' | 'unknown' | 'interrupted'

export interface ConversationMessage {
  id: string
  case_id: string
  seq: number
  author: 'user' | 'assistant'
  message_kind: 'general' | 'correction' | 'card_answer' | 'assistant_reply'
  actor: string
  client_message_id: string | null
  artifact_id: string
  artifact_rev: number
  content_hash: string
  intake_id: string | null
  request_id: string | null
  corrects_message_id: string | null
  question_id: string | null
  question_intent_version_id: string | null
  run_id: string | null
  summary: string
  created_at: string
  // **`stored` 만 접수 완료다.** 202 응답이나 중계는 접수가 아니다.
  receipt: MessageReceipt
  references: Record<string, unknown>[]
  corrected_by: string[]
}

export interface ConversationRequest {
  id: string
  case_id: string
  // P4-05. 시스템이 연 진행 요청은 여는 메시지가 없다(`origin` 이 말한다).
  opened_by_message_id: string | null
  origin?: 'user_message' | 'human_decision' | 'system_resume'
  origin_ref?: string | null
  state: RequestState
  opened_at: string
  settled_at: string | null
  settled_by: string | null
  outcome_reason: string | null
  note_summary: string | null
  locking: boolean
  opening_receipt: MessageReceipt
  runs: RequestRun[]
  unfinished_runs: number
  unknown_runs: number
  // UI-02. 중단 요청과 실제 종료 확인.
  stop_requested_at: string | null
  stop_requested_by: string | null
  stop_reason_summary: string | null
  stopping: boolean
  unconfirmed_runs: number
  interruption_summary: InterruptionSummary | null
}

// UI-02. 실행이 **지금 실제로** 어떤가. 결과(`outcome`)와 다른 축이다.
export type RunExecutionState =
  | 'pending'
  | 'executing'
  | 'unconfirmed'
  | 'ended'
  | 'ended_unconfirmed'

export interface RequestRun {
  run_id: string
  purpose: string | null
  status: string
  outcome: string | null
  not_started_reason: string | null
  residual_activity: string
  residual_observed: string | null
  residual_basis: string | null
  residual_terminated: number | null
  stop_requested_at: string | null
  stop_delivered_at: string | null
  liveness_at: string | null
  execution_state: RunExecutionState
}

export interface InterruptionSummary {
  runs: number
  by_outcome: Record<string, number>
  not_started: string[]
  result_unknown: string[]
  execution_unconfirmed: string[]
  workspace_changed_by: string[]
  workspace_unobserved: string[]
  workspace_files_changed_cumulative: number | null
  detail: string
}

export interface SendState {
  allowed: boolean
  refusal: string | null
  // UI-02. 지금 걸리는 사유 전부(요청 잠금과 PC 미연결이 함께 걸릴 수 있다).
  refusals: string[]
  detail: string
  active_request_id: string | null
  // P4-05. 열려 있어도 **무엇으로** 열렸는지. `explanation_only` 는 종료 뒤 설명 전용이다(D-87).
  note?: string | null
}

// UI-02. PC 연결은 heartbeat 에서 도출한다. `basis` 는 어느 PC 를 기준으로 판단했는가다.
export interface RunnerConnectionState {
  state: 'connected' | 'disconnected' | 'never_seen' | 'not_determined'
  runner_id: string | null
  last_seen_at: string | null
  stale_after_seconds: number
  basis: string
}

export interface ConversationView {
  case_id: string
  title: string
  status: string
  stage: 'discussion' | 'work'
  stage_source: string
  kind: string
  profile: string | null
  profile_version: string | null
  profile_source: string | null
  visibility: { archived: boolean; archived_at: string | null; history: unknown[] }
  // P4-09(e). 취소 기록(행위자·사유·시각). 취소가 아니면 null.
  cancellation?: { by: string | null; reason: string | null; at: string | null; note?: string } | null
  // D-96(P4-10b). 읽기 전용 실행 동안 작업 폴더가 바뀐 실행 — 알림(실패 아님).
  read_only_changes?: ReadOnlyChangeRow[]
  // P4-09(g). 제목의 출처(default|ai|user, 옛 행은 null)와 가벼운 이력.
  title_source?: 'default' | 'ai' | 'user' | null
  title_set_by?: string | null
  title_set_at?: string | null
  title_previous?: string | null
  work_start: { request_message_id: string; profile: string; decided_by: string } | null
  messages: ConversationMessage[]
  requests: ConversationRequest[]
  current_request: ConversationRequest | null
  send: {
    general: SendState
    card_answer: { allowed: boolean; open_questions: number; refusal: string | null }
    runner_connection_enforced: boolean
    runner_connection: RunnerConnectionState
  }
  needs_response: boolean
  // UI-03. **요청을 누가 처리하는가.** 켜져 있으면 제어부가 논의 응답을 만들고 요청을 끝낸다.
  processing?: { auto: boolean; actor: string; scope: string }
  // UI-03. 준비 단계 응답의 AI 해석(본문 없음). 업무화의 **근거가 아니라 기록**이다.
  interpretations?: ConversationInterpretation[]
  // P4-05. 업무 단계 진행 상태·이력(행이 없으면 null — 진행기가 잇지 않는 Case)과 연결 Case·종료 기록.
  progress?: ProgressView | null
  relations?: CaseRelationView[]
  // P4-06. 이 대화의 말에서 등록한(또는 거부한) 프로젝트 지식.
  knowledge_registrations?: KnowledgeRegistration[]
  closure?: ClosureRecord | null
  // UI-04c(D-86). 업무 단계의 목적·유형 개정 이력(요약 — 대응 목록은 `profileRevisionApi.get`).
  profile_revisions?: ProfileRevision[]
}

export interface ConversationInterpretation {
  run_id: string
  case_id: string
  request_id: string
  opening_message_id: string
  report_status: 'reported' | 'missing' | 'invalid'
  // UI-04c(D-86). `profile_change` 는 업무 단계의 목적·유형 변경 요청이다.
  kind: 'discussion' | 'work_request' | 'profile_change' | null
  profile: string | null
  applied: boolean
  refusal: string | null
  recorded_at: string
  evaluated_at: string | null
  objectives_json?: string | null
}

// UI-04c(D-86). 업무 단계 Case 의 Profile 개정 한 건(이력). 되돌림도 또 하나의 개정이다.
export interface ProfileRevision {
  id: string
  revision: number
  from_profile: string
  from_profile_version: string
  to_profile: string
  to_profile_version: string
  // 개정 뒤 의도 문서에 남는 이전 Profile 의 의미 항목.
  retained_fields: string[]
  // 계속 충족해야 하는 이전 목적 의무 — 새 의도 버전의 선언 목적에 합쳐진다.
  carried_objectives: string[]
  added_objectives: string[]
  decided_by: 'person' | 'ai_interpretation'
  actor: string
  request_message_id: string | null
  request_message_seq: number | null
  interpretation_run_id: string | null
  reason_summary: string | null
  intent_version_id_before: string | null
  intent_version_id_after: string | null
  created_at: string
  // 개정 직전 버전의 기준 → 개정 뒤 첫 버전의 같은 키 기준(승계/재검사/대상 없음/대기).
  criteria_mapping?: CriteriaMappingRow[]
}

export interface CriteriaMappingRow {
  key: string
  summary: string | null
  relates_to: string | null
  obligation: string | null
  before_id: string
  before_verdict: string | null
  after: { id: string; verdict: string | null; carried: boolean; obligation: string | null; relates_to: string | null } | null
  state: 'carried' | 'recheck' | 'no_target' | 'pending'
}

export interface ProfileRevisionsView {
  case_id: string
  profile: string | null
  profile_version: string | null
  profile_source: string | null
  kind: string
  retained_fields: string[]
  carried_objectives: string[]
  revisions: ProfileRevision[]
  note: string
}

export const CRITERIA_MAPPING_LABEL: Record<string, string> = {
  carried: '판정 승계됨',
  recheck: '재검사 필요(새 버전에서 다시 확인)',
  no_target: '새 버전에 같은 키 없음(옛 판정은 보존)',
  pending: '새 버전 대기',
}

export const profileRevisionApi = {
  get: (caseId: string) => request<ProfileRevisionsView>(`/api/cases/${caseId}/profile-revisions`),

  // 사람의 개정. **권한·동의·인수가 아니다** — 새 의도 버전이 기존 의도 단계(동의 포함)를 지난다.
  revise: (
    caseId: string,
    profile: string,
    addedObjectives: string[],
    keepPreviousObjectives: boolean,
    reason: string,
  ) =>
    request<ProfileRevisionsView>(`/api/cases/${caseId}/profile-revisions`, {
      method: 'POST',
      body: JSON.stringify({
        profile,
        added_objectives: addedObjectives,
        keep_previous_objectives: keepPreviousObjectives,
        actor: 'owner',
        reason_summary: reason,
      }),
    }),
}

export interface SubmittedMessage {
  message: ConversationMessage
  request: ConversationRequest | null
  receipt: MessageReceipt
  created: boolean
}

export const RECEIPT_LABEL: Record<MessageReceipt, string> = {
  pending: '접수 대기 (PC 저장 전)',
  stored: '접수됨',
  lost_before_persist: '저장 전 유실 — 새로 보내야 한다',
}

export const REQUEST_STATE_LABEL: Record<RequestState, string> = {
  processing: '처리 중',
  completed: '완료',
  failed: '실패',
  unknown: '실행 상태 확인 필요',
  interrupted: '중단됨 (실행 종료 확인)',
}

export const RUN_EXECUTION_LABEL: Record<RunExecutionState, string> = {
  pending: '배정 대기',
  executing: '실행 중',
  unconfirmed: '실행 상태 확인 끊김',
  ended: '종료 확인',
  ended_unconfirmed: '끝났는지 확인 못 함',
}

export const RUNNER_CONNECTION_LABEL: Record<RunnerConnectionState['state'], string> = {
  connected: 'PC 연결됨',
  disconnected: 'PC 미연결',
  never_seen: 'PC 연결 기록 없음',
  not_determined: '이 대화의 PC 를 아직 정할 수 없다',
}

export const CONVERSATION_REFUSAL_LABEL: Record<string, string> = {
  case_already_closed: '종료된 업무다 — 실제 수정은 연결된 새 업무로 한다',
  request_in_progress: '현재 요청을 처리하고 있다 — 초안은 편집할 수 있고 질문에는 답할 수 있다',
  request_state_unknown: '현재 요청의 실행 상태를 확인하지 못했다 — 확인 전에는 새 요청을 받지 않는다',
  client_message_id_conflict: '같은 전송 식별자로 다른 내용이 왔다',
  correction_target_invalid: '정정 대상은 이 대화의 사용자 메시지여야 한다',
  question_target_stale: '카드가 보인 의도 버전이 최신이 아니다',
  question_already_answered: '이미 답한 질문이다',
  question_not_open: '열려 있지 않은 질문이다',
  card_answer_target_missing: '카드 답변의 대상 질문·버전이 없다',
  reference_invalid: '참조한 자료가 이 업무·프로젝트의 것이 아니다',
  case_in_discussion_stage: '아직 준비 단계 대화다 — 업무화가 먼저다',
  case_not_in_discussion_stage: '이미 업무 단계다 — 목적·유형 변경은 결정 사항 패널의 개정으로 한다',
  // UI-04c(D-86). 개정의 거부.
  case_not_in_work_stage: '아직 준비 단계 대화다 — 처음 Profile 은 업무화가 정한다',
  profile_definition_not_current: '정의판 v1·Profile 미기록 업무는 개정할 수 없다(D-62)',
  profile_revision_empty: '같은 Profile 이고 더하는 목적도 없다 — 바꿀 것이 없다',
  runs_unfinished: '끝나지 않은 실행이 있다 — 끝난 뒤(사람 대기)에 개정한다',
  work_request_invalid: '업무 요청은 이 대화의 사용자 메시지여야 한다',
  work_request_not_stored: '업무 요청 메시지를 PC가 아직 저장하지 않았다',
  work_request_not_current: '그 메시지가 연 요청은 이미 끝났다',
  interpretation_run_invalid: 'AI 해석의 근거 실행이 같은 요청의 완료된 실행이 아니다',
  request_runs_unfinished: '이 요청의 실행이 아직 끝나지 않았다 — 실행 사이에 잠금을 풀지 않는다',
  request_original_not_stored: '요청을 연 메시지가 저장되지 않았다 — 완료로 적지 않는다',
  request_already_settled: '이미 끝난 요청이다',
  runner_disconnected: 'PC 가 연결돼 있지 않다 — 입력은 그대로 두고 연결되면 직접 보낸다',
  request_stop_requested: '중단 요청 중 — 관련 실행이 실제로 끝난 것을 확인하면 다시 보낼 수 있다',
  request_not_stoppable: '처리 중인 요청만 중단할 수 있다',
  run_linked_to_request: '요청에 연결된 실행은 요청 단위로 중단한다',
  run_already_finished: '이미 끝난 실행이다',
  request_not_unknown: '다시 확인할 것은 실행 상태를 모르는 요청뿐이다',
}

export interface MessageReferenceInput {
  kind: 'artifact' | 'project_file'
  artifact_id?: string
  revision?: number
  repository_id?: string
  path?: string
  location?: string
}

export const conversationApi = {
  create: (projectId: string, title: string) =>
    request<ConversationView>(`/api/projects/${projectId}/conversations`, {
      method: 'POST',
      body: JSON.stringify({ title }),
    }),

  get: (caseId: string, runnerId?: string) =>
    request<ConversationView>(
      `/api/cases/${caseId}/conversation${runnerId ? `?runner_id=${encodeURIComponent(runnerId)}` : ''}`,
    ),

  // 202 는 **접수 대기**다. `receipt === 'stored'` 가 될 때까지 초안을 비우지 않는다.
  send: (
    caseId: string,
    body: {
      client_message_id: string
      kind: 'general' | 'correction' | 'card_answer'
      content: string
      summary: string
      target_runner_id: string
      corrects_message_id?: string
      question_id?: string
      intent_version_id?: string
      // UI-03. 자료 참조(D-81). 서버가 버전·해시를 고정한다. 본문·이미지가 아니다.
      references?: MessageReferenceInput[]
    },
  ) =>
    request<SubmittedMessage>(`/api/cases/${caseId}/messages`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // 접수 불명 대조. 404 는 받은 적 없음이다.
  findByClientId: (caseId: string, clientMessageId: string) =>
    request<{ message: ConversationMessage; receipt: MessageReceipt }>(
      `/api/cases/${caseId}/messages/by-client-id/${clientMessageId}`,
    ),

  settle: (caseId: string, requestId: string, outcome: 'completed' | 'failed') =>
    request<ConversationRequest>(`/api/cases/${caseId}/requests/${requestId}/settle`, {
      method: 'POST',
      body: JSON.stringify({ outcome, actor: 'owner' }),
    }),

  // UI-02. **중단은 취소 성공이 아니다.** 관련 실행이 실제로 끝난 것을 서버가 확인하면
  // 요청이 `interrupted` 가 되고 전송이 열린다. 확인하지 못하면 `unknown` 으로 잠긴다.
  stop: (caseId: string, requestId: string, reason: string) =>
    request<ConversationRequest>(`/api/cases/${caseId}/requests/${requestId}/stop`, {
      method: 'POST',
      body: JSON.stringify({ actor: 'owner', reason }),
    }),

  // UI-02. 잠긴 요청의 실행 상태를 PC 가 **다시 확인하게** 한다. 사람이 확인을 선언하는
  // 경로가 아니다 — PC 가 확인 근거를 보내야 풀린다.
  reconcile: (caseId: string, requestId: string) =>
    request<ConversationRequest>(`/api/cases/${caseId}/requests/${requestId}/reconcile`, {
      method: 'POST',
    }),

  startWork: (caseId: string, requestMessageId: string, profile: string, summary: string) =>
    request<ConversationView>(`/api/cases/${caseId}/work-start`, {
      method: 'POST',
      body: JSON.stringify({
        profile,
        request_message_id: requestMessageId,
        decided_by: 'person',
        actor: 'owner',
        summary,
      }),
    }),

  archive: (caseId: string) =>
    request<unknown>(`/api/cases/${caseId}/archive`, {
      method: 'POST',
      body: JSON.stringify({ actor: 'owner' }),
    }),

  // P4-09(e), 이슈 #4. 업무 취소 — 사람의 결정(사유 필수). 실행이 남아 있으면 서버가 409 `runs_unfinished` 로 거부한다.
  cancel: (caseId: string, reason: string) =>
    request<ConversationView>(`/api/cases/${caseId}/cancel`, {
      method: 'POST',
      body: JSON.stringify({ actor: 'owner', reason }),
    }),

  // P4-09(g), 이슈 #6. 사람이 제목을 바꾼다(1~200자, 종료·보관 대화도). 자동 제목은 이 제목을 덮지 않는다.
  setTitle: (caseId: string, title: string) =>
    request<ConversationView>(`/api/cases/${caseId}/title`, {
      method: 'PUT',
      body: JSON.stringify({ actor: 'owner', title }),
    }),

  restore: (caseId: string) =>
    request<unknown>(`/api/cases/${caseId}/restore`, {
      method: 'POST',
      body: JSON.stringify({ actor: 'owner' }),
    }),
}


// ===================================================================== UI-03
//
// 기본 대화 화면이 쓰는 조회. **판단 값은 서버가 준다** — 목록의 상태, 프로젝트 주의 수, PC 연결
// 상태 모두 서버가 도출한 값이며 화면이 heartbeat 시각 등으로 따로 계산하지 않는다.

export interface ProjectAttention {
  needs_response: number
  request_unknown: number
  processing: number
  // UI-04b 보충. 예산 hard 도달로 새 실행이 중지된 대화 수.
  budget_stopped?: number
}

export interface ProjectWithAttention extends Project {
  attention: ProjectAttention
}

export interface RunnerWithConnection extends RunnerInfo {
  connection: RunnerConnectionState
}

export interface ConversationRow extends Case {
  // P4-05. 진행 상태(서버 도출). null 은 진행기가 잇지 않는 Case.
  progress_state?: ProgressStateCode | null
  progress_wait?: string[]
  stage?: 'discussion' | 'work' | null
  profile?: string | null
  effective_stage: 'discussion' | 'work'
  stage_source: string
  archived: boolean
  current_request_state: RequestState | null
  current_request_stopping: boolean
  needs_response: boolean
  // UI-04b 보충. 예산 hard 도달로 새 실행이 중지됐는가(서버 도출, R3 판정 그대로).
  budget_stopped?: boolean
  // D-96(P4-10b). 읽기 전용 실행 동안 작업 폴더가 바뀐 실행 수.
  read_only_changes?: number
  last_activity_at: string | null
}

// D-96(P4-10b). 읽기 전용 실행의 전후 대조 — 자리 이름뿐이다(경로·본문 없음).
export type ReadOnlyPlace = 'workspace' | 'original_repo'
export interface ReadOnlyChange {
  observed: boolean
  changed: boolean
  where: ReadOnlyPlace[]
  unobserved: ReadOnlyPlace[]
}
export interface ReadOnlyChangeRow {
  run_id: string
  purpose: string | null
  task_id: string
  finished_at: string | null
  where: ReadOnlyPlace[]
}
export const READ_ONLY_PLACE_LABEL: Record<ReadOnlyPlace, string> = {
  workspace: '작업공간(worktree)',
  original_repo: '원래 저장소 폴더',
}

export interface ProjectRepository {
  id: string
  project_id: string
  name: string
  repo_path: string
}

export const INTERPRETATION_REFUSAL_LABEL: Record<string, string> = {
  not_a_work_request: '논의로 읽었다',
  not_reported: '해석이 없거나 형식이 맞지 않았다',
  reply_not_completed: '응답이 완료되지 않았다',
  case_not_in_discussion_stage: '이미 업무 단계였다',
  case_already_closed: '종료된 업무였다',
  work_request_not_current: '그 요청이 이미 끝났다',
  work_request_not_stored: '요청 메시지가 저장되지 않았다',
  // UI-04c(D-86). 목적·유형 변경 해석이 적용되지 않은 이유.
  case_not_in_work_stage: '아직 준비 단계였다',
  profile_definition_not_current: '정의판 v1·미기록 업무라 개정하지 않았다',
  profile_revision_empty: '바꿀 것이 없었다',
  runs_unfinished: '끝나지 않은 실행이 있었다',
}

export const PROFILE_LABEL: Record<string, string> = {
  feature: '기능 개발',
  defect_fix: '결함 수정',
  root_cause_analysis: '원인 분석',
  research: '조사·연구',
  refactoring: '리팩터링',
  maintenance: '유지 보수',
}

// UI-04c(D-86). 목적 의무의 사람 말 — 모르는 값은 그대로 보인다(지어내지 않는다).
export function obligationLabel(obligation: string | null | undefined): string {
  if (!obligation) return '-'
  return (OBLIGATION_LABEL as Record<string, string>)[obligation] ?? obligation
}

// Profile 의 각 의무가 어느 Profile 의 것인가 — 개정 폼이 "이전 목적 유지" 의 뜻을 보이는 데 쓴다.
export const PROFILE_PRIMARY_OBLIGATION: Record<string, string[]> = {
  feature: ['behavior'],
  defect_fix: ['restoration'],
  root_cause_analysis: ['cause'],
  research: ['answer'],
  refactoring: ['improvement', 'preservation'],
  maintenance: ['target_state'],
}

export const PROFILE_SOURCE_LABEL: Record<string, string> = {
  explicit: '요청에 지정',
  derived_from_kind: 'kind 에서 유도(사람의 선택 아님)',
  not_recorded: '기록되지 않음(R1 이전)',
  work_start: '업무화 때 정함',
  not_yet_decided: '아직 정하지 않음(준비 단계)',
  revised: '업무 단계에서 개정함(D-86)',
}

// UI-04c(D-88). 예산 지표의 사람 말·시간 표시는 순수 모듈에 있다(시험이 그것을 본다).
export {
  BUDGET_METRIC_LABEL,
  BUDGET_METRIC_NOTE,
  DEFAULT_TIME_METRIC,
  formatSeconds,
  metricLabel,
  orderMetrics,
  TIME_METRICS,
  timeSummary,
} from './lib/budget'

// ===================================================================== UI-04d
//
// 대화 검색(D-84). **판단 값은 서버가 준다** — 무엇을 검색했는가(범위)·무엇이 제외됐는가(미연결 PC 의 본문 수)·
// 본문 결과가 도착했는가는 서버가 도출한 값이며 화면은 그대로 보인다. 발췌는 서버 메모리로만 중계된 것이다.

export type SearchMatchKind =
  | 'title'
  | 'message_summary'
  | 'work_request'
  | 'decision'
  | 'profile_revision'
  | 'rule'
  | 'body'

export const SEARCH_KIND_LABEL: Record<SearchMatchKind, string> = {
  title: '제목',
  message_summary: '메시지 요약',
  work_request: '업무 요청',
  decision: '결정',
  profile_revision: '목적·유형 변경',
  rule: '이 대화에서 정한 규칙',
  body: '본문(PC)',
}

export interface SearchMatch {
  kind: SearchMatchKind
  case_id: string
  case_title: string
  archived: boolean
  status: string
  seq: number | null
  author?: string
  text: string
  match_count: number
  item_key: string | null
  target: 'message' | 'decisions' | 'rule' | 'conversation'
  source: 'server' | 'runner'
}

export type SearchBodyState = 'none' | 'pending' | 'partial' | 'relayed' | 'expired' | 'excluded'

export interface SearchScope {
  archived_included: boolean
  server_fields: string[]
  bodies: SearchBodyState
  candidate_message_count: number
  excluded_message_count: number
  expired_message_count: number
  unreadable_message_count: number
  truncated: boolean
  runners: { runner_id: string; host: string | null; connection: string | null; state: string; message_count: number }[]
  note: string
}

export interface SearchView {
  id: string
  project_id: string
  requested_at: string
  query_length: number
  words: string[]
  scope: SearchScope
  matches: SearchMatch[]
  body: { state: SearchBodyState; matches: SearchMatch[]; scanned: number; unreadable: number }
  not_stored: boolean
}

export const searchApi = {
  start: (projectId: string, query: string) =>
    request<SearchView>(`/api/projects/${projectId}/conversation-searches`, {
      method: 'POST',
      body: JSON.stringify({ query, requested_by: 'owner' }),
    }),
  // 본문 결과가 도착했는지 다시 본다. 404 는 만료·재시작이다 — 빈 결과가 아니다.
  get: (searchId: string) => request<SearchView>(`/api/conversation-searches/${searchId}`),
}

export const shellApi = {
  projects: () => request<ProjectWithAttention[]>('/api/projects'),

  runners: () => request<RunnerWithConnection[]>('/api/runners'),

  conversations: (projectId: string) =>
    request<ConversationRow[]>(`/api/projects/${projectId}/conversations?archived=include`),

  repositories: (projectId: string) =>
    request<{ repositories: ProjectRepository[] }>(`/api/projects/${projectId}/repositories`),
}

// ===================================================================== P4-05
//
// 업무 단계 자동 진행·완료·예외·후속. **판단 값은 서버가 준다** — 진행 상태·대기 사유·연결 Case 는
// 서버가 도출한 값이며 화면은 그 코드로 카드를 고를 뿐이다. 카드의 확인 동작은 기존 사람 경로
// (동의·확인 지점·delta·단계 검토·피드백·예외·인수)를 그대로 부른다.

export type ProgressStateCode = 'running' | 'waiting_human' | 'blocked' | 'paused' | 'done'

export interface ProgressWait {
  code: string
  detail: string
  [key: string]: unknown
}

export interface ProgressEvent {
  id: string
  case_id: string
  seq: number
  at: string
  step: string
  action: string
  run_id: string | null
  request_id: string | null
  detail: string | null
  codes: string[]
}

// P4-05b. 진행기의 재작성·재시도 상한. Case 명시 → 시스템 기본값(제어부 환경 변수).
// P4-10. 검증 미충족의 수정 사이클 한도와 실행 제한 시간(초)이 같은 자리에 더해졌다.
export type ProgressLimitKey = 'repair_limit' | 'task_retry_limit' | 'remediation_limit' | 'run_timeout_seconds'
export const PROGRESS_LIMIT_KEYS: ProgressLimitKey[] = [
  'repair_limit',
  'task_retry_limit',
  'remediation_limit',
  'run_timeout_seconds',
]

export interface ProgressLimitSettingRow {
  id: string
  case_id: string
  revision: number
  limit_key: ProgressLimitKey
  limit_value: number
  set_by: string
  reason_summary: string | null
  state: 'current' | 'superseded'
  created_at: string
  superseded_at: string | null
}

export interface ProgressLimitValue {
  value: number
  // UI-04b. `project_setting` 은 프로젝트 설정 화면의 기본값(Case 설정이 없을 때).
  source: 'case_setting' | 'project_setting' | 'system_default'
  setting: ProgressLimitSettingRow | null
}

export interface ProgressLimitsView {
  repair_limit: ProgressLimitValue
  task_retry_limit: ProgressLimitValue
  // P4-10. 옛 제어부는 이 둘을 주지 않는다.
  remediation_limit?: ProgressLimitValue
  run_timeout_seconds?: ProgressLimitValue
  system_default: Record<ProgressLimitKey, number>
  // UI-04b. 프로젝트 기본값(없으면 null).
  project_default?: Record<ProgressLimitKey, number | null>
  range: { min: number; max: number }
  // P4-10. 키별 범위(제한 시간은 초).
  ranges?: Partial<Record<ProgressLimitKey, { min: number; max: number }>>
  history: ProgressLimitSettingRow[]
  closed: boolean
}

export const PROGRESS_LIMIT_LABEL: Record<ProgressLimitKey, string> = {
  repair_limit: '재작성',
  task_retry_limit: '재시도',
  remediation_limit: '수정 사이클',
  run_timeout_seconds: '제한 시간',
}

export const PROGRESS_LIMIT_SOURCE_LABEL: Record<ProgressLimitValue['source'], string> = {
  case_setting: '이 업무에서 정함',
  project_setting: '프로젝트 기본값',
  system_default: '시스템 기본값',
}

export interface ProgressView {
  case_id: string
  state: ProgressStateCode
  step: string
  step_detail: string | null
  wait: ProgressWait[]
  request_id: string | null
  last_run_id: string | null
  attempts: Record<string, number>
  paused_at: string | null
  paused_by: string | null
  started_at: string
  updated_at: string
  events: ProgressEvent[]
  actor: string
  auto: boolean
  limits: ProgressLimitsView
}

export interface CaseRelationView {
  relation: string
  direction: 'successor' | 'predecessor'
  case_id: string
  title: string
  status: string
  reason_summary: string | null
  created_at: string
}

export const PROGRESS_STATE_LABEL: Record<ProgressStateCode, string> = {
  running: '진행 중',
  waiting_human: '확인 필요',
  blocked: '막힘',
  paused: '멈춤',
  done: '완료',
}

export const WAIT_LABEL: Record<string, string> = {
  intent_questions: '의도 질문에 답하기',
  intent_agreement: '의도 동의',
  material_delta: '동의된 의도의 변경 확인',
  gate_repair_exhausted: 'QG-01 지적이 남음',
  sizing_not_decided: '작업 수준 미결정',
  controlled_start: '시작 범위 확인(controlled)',
  stage_review: '준비 산출물 검토',
  preparation_repair_exhausted: '준비 산출물의 필수 항목 미정',
  deferred_questions: '이월 질문에 답하기',
  work_graph_missing: '작업 그래프 없음',
  tasks_blocked: '배정 가능한 작업 없음',
  repository_selection: '코드 쓰기 저장소 선택',
  workspace_start_basis: '시작 코드 선택(커밋하지 않은 변경)',
  task_failed: '작업 실행 실패',
  unresolved_feedback: '미해결 피드백',
  controlled_result: '결과 확인(controlled)',
  criteria_unresolved: '미충족·미검증 기준',
  objective_without_criteria: '목적 의무에 기준 없음',
  quality_gate: '명시 품질 게이트 미통과',
  run_timed_out: '시간 초과 — 제한 시간 늘리기',
  admission_refused: '진입 검사 거부',
  tool_unavailable: '도구를 쓸 수 없음',
  workspace_failed: '작업공간 준비 실패',
  budget_hard_limit: '예산 hard 한도 도달',
  context_unavailable: '핵심 입력을 읽을 수 없음',
  run_not_created: '실행을 만들지 못함',
}

export const PROGRESS_STEP_LABEL: Record<string, string> = {
  work_started: '업무화',
  remediation: '검증 미충족 → 수정 사이클',
  intent_authoring: '의도 초안 작성',
  intent_rewrite_answers: '답을 반영한 의도 재작성',
  intent_repair: 'QG-01 지적 반영 재작성',
  intent_gate_review: 'QG-01 독립 검토',
  light_conformance: '가벼운 정합성 확인',
  design_authoring: '설계 작성',
  design_rewrite: '설계 재작성',
  plan_authoring: '개발계획 작성',
  plan_rewrite: '개발계획 재작성',
  combined_authoring: '결합 기록 작성',
  combined_rewrite: '결합 기록 재작성',
  plan_rewrite_stale_graph: '개발계획 재작성(의도 변경)',
  analysis: '분석 실행',
  analysis_retry: '분석 다시 시도',
  candidate: '종료 후보 확인',
  request_opened: '진행 요청 열림',
  resumed: '계속 진행',
  paused: '멈춤',
  closed: '종료',
  criteria: '기준 판정',
}

export const PROGRESS_ACTION_LABEL: Record<string, string> = {
  started: '업무화',
  run_created: '실행 만듦',
  run_exists: '실행 있음',
  workspace_requested: '작업공간 요청',
  recorded: '기록',
  candidate: '종료 후보',
  waiting_human: '확인 필요',
  blocked: '막힘',
  paused: '멈춤',
  resumed: '계속 진행',
  done: '완료',
  request_opened: '진행 요청',
  admission_refused: '진입 거부',
  criteria_recorded: '기준 판정 기록',
  criteria_refused: '기준 판정 거부',
}

export const progressApi = {
  get: (caseId: string) =>
    request<{ case_id: string; progress: ProgressView | null; auto: boolean; limits: ProgressLimitsView }>(
      `/api/cases/${caseId}/progress`,
    ),

  // P4-05b. 재작성·재시도 상한을 이 업무에서 바꾼다(이력). 상한 대기에서 올리면 그 자리에서 한 번 더
  // 간다 — 확인·인수·권한이 아니다.
  setLimits: (
    caseId: string,
    values: Partial<Record<ProgressLimitKey, number>>,
    reasonSummary: string,
  ) =>
    request<{ limits: ProgressLimitsView; progress: ProgressView | null }>(
      `/api/cases/${caseId}/progress/limits`,
      {
        method: 'PUT',
        body: JSON.stringify({ ...values, set_by: 'owner', reason_summary: reasonSummary || null }),
      },
    ),

  // UI-04b. Case 별 상한 설정을 닫는다 — 프로젝트 기본값·시스템 기본값이 유효해진다(이력 보존).
  clearLimit: (caseId: string, key: ProgressLimitKey) =>
    request<{ limits: ProgressLimitsView; progress: ProgressView | null }>(
      `/api/cases/${caseId}/progress/limits/${key}`,
      { method: 'DELETE' },
    ),

  // 멈춤·막힘·실패 뒤 **계속 진행**. 확인·동의·인수가 아니다 — 다음 걸음을 다시 보라는 요청이다.
  resume: (caseId: string) =>
    request<{ result: unknown; progress: ProgressView | null }>(`/api/cases/${caseId}/progress/resume`, {
      method: 'POST',
      body: JSON.stringify({ actor: 'owner' }),
    }),

  // controlled 확인 지점. **대상·해시를 함께** 보낸다(FR-23) — 대상이 바뀌면 서버가 낡은 확인으로 본다.
  confirmCheckpoint: (
    caseId: string,
    checkpoint: 'start_scope' | 'result_candidate',
    subjectType: string,
    subjectId: string,
    subjectHash: string | null,
    note: string,
  ) =>
    request<ControlledCheckpointRow[]>(
      `/api/cases/${caseId}/controlled-checkpoints/${checkpoint}/confirmation`,
      {
        method: 'POST',
        body: JSON.stringify({
          confirmed_by: 'owner',
          explicit: true,
          subject_type: subjectType,
          subject_id: subjectId,
          subject_hash: subjectHash,
          note_summary: note || null,
        }),
      },
    ),

  materialDeltas: (caseId: string) =>
    request<MaterialDeltaState>(`/api/cases/${caseId}/material-deltas`),

  // 단계 검토(결합 기록 포함). `reviewed` 를 명시로 보낸다 — 화면을 열어 본 것이 검토가 아니다.
  reviewStage: (caseId: string, stage: string, note: string) =>
    request<StageReview>(`/api/cases/${caseId}/stage-reviews/${stage}`, {
      method: 'POST',
      body: JSON.stringify({ reviewed: true, note, actor: 'owner' }),
    }),
}
