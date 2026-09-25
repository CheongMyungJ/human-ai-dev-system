// P4-10d(D-98) 결과 모름 실행의 해소 표시 단위 시험(P4-PLAN-10d). 실행: `npm test`.
import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import { unknownSettlementBadge, unknownSettlementText } from './unknownRuns.ts'

test('a superseded unknown run names the later attempt and keeps the result unknown', () => {
  const s = { kind: 'superseded' as const, by_run_id: 'wp-x-task-T2-3' }
  assert.equal(unknownSettlementText(s), '결과 모름 — 뒤 시도 wp-x-task-T2-3 가 완료해 대체됨(종료를 막지 않음)')
  assert.equal(unknownSettlementBadge(s), '대체됨')
})

test('a confirmed unknown run shows who confirmed it and why, and nothing shows for an unsettled run', () => {
  const s = {
    kind: 'confirmed' as const,
    actor: 'owner',
    reason: '출력과 작업 폴더를 봤다',
    workspace_checked: true,
    confirmed_at: '2026-09-25T00:00:00+00:00',
    decision_id: 'd-1',
  }
  assert.equal(unknownSettlementText(s), '결과 모름 — owner 가 확인함(종료를 막지 않음): 출력과 작업 폴더를 봤다')
  assert.equal(unknownSettlementBadge(s), '사람이 확인함')
  assert.equal(unknownSettlementText(null), null)
  assert.equal(unknownSettlementBadge(undefined), null)
})
