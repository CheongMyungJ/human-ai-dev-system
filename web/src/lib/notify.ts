// PC 알림의 **전이 계산**(UI-04b, D-82). **import 가 없다.**
//
//   답변·결과 확인 필요, 의미 있는 차단·오류, 완료를 알리고 일상 진행은 알리지 않는다. 사용자가 그 대화를
//   보고 있으면 팝업을 억제한다(기록에는 남긴다). 다른 프로젝트의 상태는 수로 알리고 자동으로 옮기지 않는다.
//
//   여기서 보는 것은 서버가 도출한 값의 **전이**다(이전 조회 → 다음 조회). 첫 조회는 비교할 이전 상태가
//   없으므로 알리지 않는다. 화면은 이 함수의 결과를 기록하고, 억제되지 않은 것만 브라우저 알림으로 띄운다.
//   서버 푸시가 아니다 — 조회 간격 안의 두 전이는 마지막 것만 보인다.

export type NoticeKind =
  | 'needs_response'
  | 'waiting_human'
  | 'blocked'
  | 'request_unknown'
  | 'budget_stop'
  | 'read_only_change'
  | 'done'
  | 'project_attention'

export interface NoticeRow {
  id: string
  title: string
  status: string
  needs_response: boolean
  progress_state?: string | null
  current_request_state?: string | null
  // 예산 hard 도달로 새 실행이 중지됐는가(UI-04b 보충, 사용자 결정 2026-09-24).
  budget_stopped?: boolean
  // D-96(P4-10b). 읽기 전용 실행 동안 작업 폴더가 바뀐 실행 수 — 늘면 알린다(실패가 아니다).
  read_only_changes?: number
}

export interface NoticeProject {
  id: string
  name: string
  attention: { needs_response: number; request_unknown: number; budget_stopped?: number }
}

export interface Notice {
  key: string
  kind: NoticeKind
  title: string
  body: string
  projectId: string
  caseId: string | null
  suppressed: boolean
}

export interface ViewingContext {
  /** 지금 열려 있는 대화. */
  caseId: string | null
  /** 문서가 보이고 창에 포커스가 있는가 — 그럴 때만 "보고 있다"다. */
  visible: boolean
}

export const NOTICE_LABEL: Record<NoticeKind, string> = {
  needs_response: '답변 필요',
  waiting_human: '확인 필요',
  blocked: '막힘',
  request_unknown: '실행 상태 확인 필요',
  budget_stop: '예산 도달',
  read_only_change: '읽기 전용 실행이 폴더를 바꿈',
  done: '완료',
  project_attention: '다른 프로젝트의 주의',
}

const CLOSED = new Set(['closed', 'cancelled'])

/** 보고 있는 대화의 사건은 팝업을 억제한다. 다른 프로젝트의 수는 대화가 아니므로 억제하지 않는다. */
export function suppressed(caseId: string | null, ctx: ViewingContext): boolean {
  return caseId !== null && ctx.visible && ctx.caseId === caseId
}

/**
 * 한 프로젝트의 대화 목록 두 조회 사이의 전이. `prev` 가 없으면(첫 조회) 빈 목록이다.
 * 목록에 새로 나타난 대화도 "이전 상태 없음"으로 보고 지금 상태가 알릴 것이면 알린다 — 다른 탭에서 시작한
 * 업무의 질문을 놓치지 않게. 다만 처음 만든 빈 대화는 아무 상태도 아니므로 알리지 않는다.
 */
export function diffConversations(
  prev: NoticeRow[] | null,
  next: NoticeRow[],
  projectId: string,
  ctx: ViewingContext,
): Notice[] {
  if (prev === null) return []
  const before = new Map(prev.map((r) => [r.id, r]))
  const out: Notice[] = []
  const push = (row: NoticeRow, kind: NoticeKind, body: string) => {
    out.push({
      key: `${row.id}:${kind}`,
      kind,
      title: row.title,
      body,
      projectId,
      caseId: row.id,
      suppressed: suppressed(row.id, ctx),
    })
  }
  for (const row of next) {
    const old = before.get(row.id)
    const wasNeeds = old?.needs_response ?? false
    const wasProgress = old?.progress_state ?? null
    const wasRequest = old?.current_request_state ?? null
    const wasClosed = old ? CLOSED.has(old.status) : false
    if (row.needs_response && !wasNeeds) push(row, 'needs_response', '질문에 답이 필요하다')
    // 진행 상태 — 확인 필요·막힘·완료만. 진행 중·멈춤(사람이 멈춘 것)은 알리지 않는다.
    if (row.progress_state !== wasProgress) {
      if (row.progress_state === 'waiting_human' && !row.needs_response) {
        push(row, 'waiting_human', '사람의 확인이 필요하다')
      } else if (row.progress_state === 'blocked') {
        push(row, 'blocked', '환경·조건 때문에 진행이 막혔다')
      }
    }
    if (row.current_request_state === 'unknown' && wasRequest !== 'unknown') {
      push(row, 'request_unknown', '실행이 실제로 끝났는지 확인하지 못했다')
    }
    // 예산 hard 도달 — 새 실행이 중지됐다. 한도를 올리면 풀리고, 다시 닿으면 다시 알린다.
    if (row.budget_stopped === true && !(old?.budget_stopped ?? false)) {
      push(row, 'budget_stop', '예산 한도에 닿아 새 실행이 중지됐다 — 한도 조정은 상세 설정에서')
    }
    // D-96(P4-10b). 읽기 전용 실행 동안 작업 폴더가 바뀌었다 — 알리기만 한다(실행은 실패가 아니다).
    if ((row.read_only_changes ?? 0) > (old?.read_only_changes ?? 0)) {
      push(row, 'read_only_change', '읽기 전용 실행 동안 작업 폴더가 바뀌었다 — 실패로 표시하지 않았다. 대화에서 확인한다')
    }
    const closedNow = CLOSED.has(row.status)
    if ((closedNow && !wasClosed) || (row.progress_state === 'done' && wasProgress !== 'done' && !closedNow)) {
      push(row, 'done', closedNow ? `업무가 종료됐다(${row.status})` : '진행이 끝났다')
    }
  }
  return out
}

/** 다른 프로젝트의 주의 수가 **늘면** 한 건으로 알린다. 지금 프로젝트는 대화 목록 쪽이 맡는다. */
export function diffProjects(
  prev: NoticeProject[] | null,
  next: NoticeProject[],
  currentProjectId: string | null,
): Notice[] {
  if (prev === null) return []
  const before = new Map(prev.map((p) => [p.id, p]))
  const out: Notice[] = []
  for (const project of next) {
    if (project.id === currentProjectId) continue
    const old = before.get(project.id)
    const needs = project.attention.needs_response - (old?.attention.needs_response ?? 0)
    const unknown = project.attention.request_unknown - (old?.attention.request_unknown ?? 0)
    const budget = (project.attention.budget_stopped ?? 0) - (old?.attention.budget_stopped ?? 0)
    if (needs <= 0 && unknown <= 0 && budget <= 0) continue
    const parts: string[] = []
    if (needs > 0) parts.push(`답변 필요 ${project.attention.needs_response}`)
    if (unknown > 0) parts.push(`실행 상태 확인 필요 ${project.attention.request_unknown}`)
    if (budget > 0) parts.push(`예산 도달 ${project.attention.budget_stopped ?? 0}`)
    out.push({
      key: `${project.id}:attention:${project.attention.needs_response}:${project.attention.request_unknown}:${project.attention.budget_stopped ?? 0}`,
      kind: 'project_attention',
      title: project.name,
      body: `${parts.join(' · ')} — 자동으로 옮기지 않는다`,
      projectId: project.id,
      caseId: null,
      suppressed: false,
    })
  }
  return out
}

//: 화면 안 알림 기록의 길이. 오래된 것부터 버린다.
export const NOTICE_LOG_CAP = 20

export function appendLog<T>(log: T[], items: T[]): T[] {
  if (items.length === 0) return log
  const next = [...log, ...items]
  return next.length > NOTICE_LOG_CAP ? next.slice(next.length - NOTICE_LOG_CAP) : next
}
