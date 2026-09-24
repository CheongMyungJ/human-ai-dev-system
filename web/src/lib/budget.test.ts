// UI-04c(D-88) 예산 지표 이름표·시간 표시의 단위 시험(UI-PLAN-04c 5절). 실행: `npm test`.
import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import {
  BUDGET_METRIC_LABEL,
  BUDGET_METRIC_NOTE,
  DEFAULT_TIME_METRIC,
  formatSeconds,
  metricLabel,
  orderMetrics,
  TIME_METRICS,
  timeSummary,
} from './budget.ts'

// 서버의 `BudgetMetric` 여덟 값. 하나라도 이름표가 없으면 화면에 날것이 보인다.
const SERVER_METRICS = [
  'run_count',
  'review_run_count',
  'input_tokens',
  'output_tokens',
  'context_bytes',
  'execution_seconds',
  'elapsed_seconds',
  'estimated_cost',
]

test('every server metric has a label and the time metrics have a note', () => {
  for (const name of SERVER_METRICS) {
    assert.ok(BUDGET_METRIC_LABEL[name], `label missing for ${name}`)
    assert.equal(metricLabel(name), BUDGET_METRIC_LABEL[name])
  }
  assert.equal(metricLabel('unknown_metric'), 'unknown_metric')
  for (const name of TIME_METRICS) assert.ok(BUDGET_METRIC_NOTE[name], `note missing for ${name}`)
  // 시간 한도의 기본 지표는 실행시간 합계다(D-88). 경과시간은 별도 선택이다.
  assert.equal(DEFAULT_TIME_METRIC, 'execution_seconds')
  assert.deepEqual([...TIME_METRICS], ['execution_seconds', 'elapsed_seconds'])
  assert.match(BUDGET_METRIC_NOTE.execution_seconds, /병렬/)
  assert.match(BUDGET_METRIC_NOTE.execution_seconds, /절대 상한이 아니다/)
})

test('metrics are ordered with the time metrics right after the run count', () => {
  const ordered = orderMetrics(['estimated_cost', 'elapsed_seconds', 'run_count', 'execution_seconds', 'zzz_new'])
  assert.deepEqual(ordered, ['run_count', 'execution_seconds', 'elapsed_seconds', 'estimated_cost', 'zzz_new'])
})

test('seconds are shown in hours, minutes and seconds; unknown values are a dash, not 0', () => {
  assert.equal(formatSeconds(0), '0초')
  assert.equal(formatSeconds(59.4), '59초')
  assert.equal(formatSeconds(60), '1분')
  assert.equal(formatSeconds(3723), '1시간 2분 3초')
  assert.equal(formatSeconds(null), '—')
  assert.equal(formatSeconds(undefined), '—')
  assert.equal(formatSeconds(-1), '—')
  assert.equal(formatSeconds(Number.NaN), '—')
})

test('the time summary separates settled, in-flight and unresolved and says when it is not everything', () => {
  assert.equal(timeSummary(null), '—')
  assert.equal(timeSummary({ settled: 90, held: 0, unresolved: 0, exposure: 90, complete: true }), '합계 1분 30초')
  const partial = timeSummary({ settled: 60, held: 30, unresolved: 12, exposure: 102, complete: false, runs_in_flight: 1, runs_unknown: 1 })
  assert.equal(partial, '합계 1분 42초 · 진행 중 30초 · 미확정 12초 · 전부가 아니다(진행 중·미확정 포함)')
})
