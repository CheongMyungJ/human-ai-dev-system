// P4-10(D-95) 실행 제한 시간 표시·제안값의 단위 시험(P4-PLAN-10). 실행: `npm test`.
import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import { formatTimeout, minutesToSeconds, stopReasonText, suggestedMinutes } from './timeout.ts'

test('formatTimeout shows hours and minutes, and never shows an unknown limit as zero', () => {
  assert.equal(formatTimeout(3600), '1시간')
  assert.equal(formatTimeout(5400), '1시간 30분')
  assert.equal(formatTimeout(600), '10분')
  assert.equal(formatTimeout(30), '30초')
  assert.equal(formatTimeout(90), '1분 30초')
  assert.equal(formatTimeout(null), '기록 없음')
  assert.equal(formatTimeout(0), '기록 없음')
})

test('a timeout is described as a cut, not a failure', () => {
  const text = stopReasonText('timeout', 3600)
  assert.match(text, /시간 초과/)
  assert.match(text, /1시간/)
  assert.match(text, /실패가 아니다/)
  assert.equal(stopReasonText('stop_requested'), '중단 요청으로 끊음')
  assert.equal(stopReasonText(null), '')
})

test('the suggested new limit is larger than both the cut and the current limit, and capped at a day', () => {
  assert.equal(suggestedMinutes(3600, 3600), 120)
  assert.equal(suggestedMinutes(600, 3600), 120)
  assert.equal(suggestedMinutes(20, null), 2)
  assert.equal(suggestedMinutes(80000, 80000), 1440)
})

test('minutes are converted to seconds within the setting range', () => {
  assert.equal(minutesToSeconds('90'), 5400)
  assert.equal(minutesToSeconds('0.5'), 30)
  assert.equal(minutesToSeconds('0.1'), null) // 6초 — 10초 미만
  assert.equal(minutesToSeconds('1441'), null)
  assert.equal(minutesToSeconds('abc'), null)
})
