// UI-04b 알림 전이의 단위 시험(UI-PLAN-04b AC-8a·b). 실행: `npm test`.
import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import { appendLog, diffConversations, diffProjects, NOTICE_LOG_CAP, suppressed, type NoticeRow } from './notify.ts'

function row(over: Partial<NoticeRow> & { id: string }): NoticeRow {
  return { title: `대화 ${over.id}`, status: 'received', needs_response: false, progress_state: null, current_request_state: null, ...over }
}

const away = { caseId: null, visible: false }

test('the first poll and routine progress produce no notice', () => {
  const rows = [row({ id: 'c1', needs_response: true, progress_state: 'waiting_human' })]
  assert.deepEqual(diffConversations(null, rows, 'p1', away), [])
  // 진행 중·처리 중·멈춤은 일상 진행이다.
  const prev = [row({ id: 'c1' })]
  const running = [row({ id: 'c1', progress_state: 'running', current_request_state: 'processing' })]
  assert.deepEqual(diffConversations(prev, running, 'p1', away), [])
  const paused = [row({ id: 'c1', progress_state: 'paused' })]
  assert.deepEqual(diffConversations(running, paused, 'p1', away), [])
  // 같은 상태가 이어지면 다시 알리지 않는다.
  const waiting = [row({ id: 'c1', needs_response: true })]
  assert.equal(diffConversations(waiting, waiting, 'p1', away).length, 0)
})

test('answers, confirmations, blocks, unknown runs and completion are noticed once each', () => {
  const prev = [row({ id: 'c1', progress_state: 'running', current_request_state: 'processing' })]
  const next = [row({ id: 'c1', needs_response: true, progress_state: 'waiting_human' })]
  const notices = diffConversations(prev, next, 'p1', away)
  // 답변 필요가 확인 필요를 대신한다(같은 대기를 두 번 알리지 않는다).
  assert.deepEqual(notices.map((n) => [n.kind, n.caseId, n.suppressed]), [['needs_response', 'c1', false]])
  assert.equal(notices[0].title, '대화 c1')

  const confirm = diffConversations(prev, [row({ id: 'c1', progress_state: 'waiting_human' })], 'p1', away)
  assert.deepEqual(confirm.map((n) => n.kind), ['waiting_human'])
  const blocked = diffConversations(prev, [row({ id: 'c1', progress_state: 'blocked' })], 'p1', away)
  assert.deepEqual(blocked.map((n) => n.kind), ['blocked'])
  const unknown = diffConversations(prev, [row({ id: 'c1', current_request_state: 'unknown' })], 'p1', away)
  assert.deepEqual(unknown.map((n) => n.kind), ['request_unknown'])
  const done = diffConversations(prev, [row({ id: 'c1', progress_state: 'done', status: 'closed' })], 'p1', away)
  assert.deepEqual(done.map((n) => [n.kind, n.body]), [['done', '업무가 종료됐다(closed)']])
  const doneOpen = diffConversations(prev, [row({ id: 'c1', progress_state: 'done' })], 'p1', away)
  assert.deepEqual(doneOpen.map((n) => n.body), ['진행이 끝났다'])
  // 예산 hard 도달(UI-04b 보충) — 한 번, 풀렸다 다시 닿으면 다시.
  const stopped = [row({ id: 'c1', budget_stopped: true })]
  assert.deepEqual(diffConversations(prev, stopped, 'p1', away).map((n) => [n.kind, n.body.includes('예산 한도')]), [['budget_stop', true]])
  assert.deepEqual(diffConversations(stopped, stopped, 'p1', away), [])
  const lifted = [row({ id: 'c1', budget_stopped: false })]
  assert.deepEqual(diffConversations(stopped, lifted, 'p1', away), [])
  assert.deepEqual(diffConversations(lifted, stopped, 'p1', away).map((n) => n.kind), ['budget_stop'])
  // 새로 나타난 대화도 지금 상태가 알릴 것이면 알린다; 빈 새 대화는 아니다.
  const appeared = diffConversations([], [row({ id: 'c2', needs_response: true }), row({ id: 'c3' })], 'p1', away)
  assert.deepEqual(appeared.map((n) => n.caseId), ['c2'])
})

test('the conversation being viewed is suppressed but still recorded', () => {
  const prev = [row({ id: 'c1' }), row({ id: 'c2' })]
  const next = [row({ id: 'c1', needs_response: true }), row({ id: 'c2', needs_response: true })]
  const viewing = { caseId: 'c1', visible: true }
  const notices = diffConversations(prev, next, 'p1', viewing)
  assert.deepEqual(notices.map((n) => [n.caseId, n.suppressed]), [['c1', true], ['c2', false]])
  // 창이 보이지 않으면(다른 창·최소화) 보고 있는 것이 아니다.
  assert.equal(suppressed('c1', { caseId: 'c1', visible: false }), false)
  assert.equal(suppressed(null, viewing), false)
})

test('other projects are noticed when their attention count grows, never the current one', () => {
  const prev = [
    { id: 'p1', name: '지금', attention: { needs_response: 0, request_unknown: 0 } },
    { id: 'p2', name: '다른', attention: { needs_response: 1, request_unknown: 0 } },
  ]
  const next = [
    { id: 'p1', name: '지금', attention: { needs_response: 3, request_unknown: 1 } },
    { id: 'p2', name: '다른', attention: { needs_response: 2, request_unknown: 0 } },
    { id: 'p3', name: '새것', attention: { needs_response: 0, request_unknown: 1 } },
  ]
  const notices = diffProjects(prev, next, 'p1')
  assert.deepEqual(notices.map((n) => [n.projectId, n.kind, n.caseId, n.suppressed]), [
    ['p2', 'project_attention', null, false],
    ['p3', 'project_attention', null, false],
  ])
  assert.equal(notices[0].body, '답변 필요 2 — 자동으로 옮기지 않는다')
  assert.equal(notices[1].body, '실행 상태 확인 필요 1 — 자동으로 옮기지 않는다')
  // 줄어들면 알리지 않는다. 첫 조회도 아니다.
  assert.deepEqual(diffProjects(next, prev, 'p1'), [])
  assert.deepEqual(diffProjects(null, next, 'p1'), [])
  // 예산 도달 수 증가(UI-04b 보충). 옛 조회에 값이 없으면 0 으로 본다.
  const budget = [{ id: 'p2', name: '다른', attention: { needs_response: 2, request_unknown: 0, budget_stopped: 1 } }]
  const grown = diffProjects(next, budget, 'p1')
  assert.deepEqual(grown.map((n) => [n.projectId, n.body]), [['p2', '예산 도달 1 — 자동으로 옮기지 않는다']])
})

test('the in-page log keeps only the most recent entries', () => {
  let log: number[] = []
  for (let i = 0; i < NOTICE_LOG_CAP + 5; i += 1) log = appendLog(log, [i])
  assert.equal(log.length, NOTICE_LOG_CAP)
  assert.equal(log[0], 5)
  assert.equal(appendLog(log, []), log)
})

test('a new read-only change is announced once and a steady count is not (D-96)', () => {
  const away = { caseId: null, visible: false }
  const before = [row({ id: 'c1', read_only_changes: 0 })]
  const changed = [row({ id: 'c1', read_only_changes: 1 })]
  assert.deepEqual(
    diffConversations(before, changed, 'p1', away).map((n) => [n.kind, n.body.includes('실패로 표시하지 않았다')]),
    [['read_only_change', true]],
  )
  assert.deepEqual(diffConversations(changed, changed, 'p1', away), [])
})
