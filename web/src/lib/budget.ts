// 예산 지표의 사람 말과 시간 표시(UI-04c, D-88). 순수 함수 — 화면·시험이 같은 문구를 쓴다.
//
//   **지표의 뜻은 서버가 정한다.** 여기 있는 것은 이름표와 설명이며 값·한도·보장은 서버 조회 그대로다.
//   **시간 한도의 기본 지표는 실행시간 합계다**(D-88). 경과시간은 별도 선택이다. 절대 상한이 아니다.
//   **모르는 값을 0 으로 보이지 않는다.** `complete` 가 거짓이면 "미확정 포함" 을 함께 보인다.

export const BUDGET_METRIC_LABEL: Record<string, string> = {
  run_count: '실행 수',
  review_run_count: '검토 실행 수',
  input_tokens: '입력 토큰',
  output_tokens: '출력 토큰',
  context_bytes: '문맥 크기(바이트)',
  execution_seconds: '실행시간 합계(초)',
  elapsed_seconds: '대화 생성 후 경과시간(초)',
  estimated_cost: '추정 비용',
}

export const BUDGET_METRIC_NOTE: Record<string, string> = {
  execution_seconds:
    '실행별 배정~종료 시각의 합 — 논의·업무·재시도·종료 후 설명 실행 전부, 병렬 실행은 각각 더한다. 사람의 답변 대기는 실행 밖이라 들어가지 않는다. 시간 한도의 기본 지표(D-88). 절대 상한이 아니다 — 돌고 있는 실행을 초 단위로 끊지 못한다',
  elapsed_seconds: '대화를 만든 뒤 지금까지의 벽시계 — 사람 대기를 포함한다. 별도로 선택하는 한도(D-88)',
}

//: 시간 지표. 이 순서로 "시간 한도 추가" 가 기본값을 고른다 — 실행시간 합계가 먼저다(D-88).
export const TIME_METRICS = ['execution_seconds', 'elapsed_seconds'] as const
export const DEFAULT_TIME_METRIC = 'execution_seconds'

//: 화면의 지표 순서 — 실행 수 다음에 시간 둘, 그 뒤 나머지. 서버가 모르는 지표는 뒤에 그대로 둔다.
export const METRIC_ORDER = [
  'run_count',
  'execution_seconds',
  'elapsed_seconds',
  'review_run_count',
  'context_bytes',
  'input_tokens',
  'output_tokens',
  'estimated_cost',
]

export function metricLabel(metric: string): string {
  return BUDGET_METRIC_LABEL[metric] ?? metric
}

export function orderMetrics(names: string[]): string[] {
  const index = (name: string) => {
    const at = METRIC_ORDER.indexOf(name)
    return at < 0 ? METRIC_ORDER.length : at
  }
  return [...names].sort((a, b) => index(a) - index(b) || a.localeCompare(b))
}

// 초 → "1시간 2분 3초". 0 은 "0초". 음수·NaN 은 "—"(값이 아니다).
export function formatSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) return '—'
  const total = Math.round(seconds)
  if (total === 0) return '0초'
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const rest = total % 60
  const parts: string[] = []
  if (hours) parts.push(`${hours}시간`)
  if (minutes) parts.push(`${minutes}분`)
  if (rest || parts.length === 0) parts.push(`${rest}초`)
  return parts.join(' ')
}

export interface TimeUsage {
  settled: number
  held: number
  unresolved: number
  exposure: number
  complete: boolean
  runs_in_flight?: number
  runs_unknown?: number
}

// 시간 지표 한 줄. 확정·진행 중·미확정을 따로 말하고 전부가 아니면 그렇게 말한다.
export function timeSummary(usage: TimeUsage | null | undefined): string {
  if (!usage) return '—'
  const parts = [`합계 ${formatSeconds(usage.exposure)}`]
  if (usage.held > 0 || (usage.runs_in_flight ?? 0) > 0) parts.push(`진행 중 ${formatSeconds(usage.held)}`)
  if (usage.unresolved > 0 || (usage.runs_unknown ?? 0) > 0) parts.push(`미확정 ${formatSeconds(usage.unresolved)}`)
  if (!usage.complete) parts.push('전부가 아니다(진행 중·미확정 포함)')
  return parts.join(' · ')
}
