// D-83 초안 규칙의 단위 시험(UI-PLAN-03 AC-14). 실행: `npm test` (Node 내장 시험 실행기).
import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import {
  addRef,
  beginSend,
  draftKey,
  edit,
  emptyDraft,
  load,
  newClientId,
  save,
  settle,
  type Draft,
  type KeyValueStore,
} from './drafts.ts'

class MemoryStore implements KeyValueStore {
  data = new Map<string, string>()
  failWrites = false
  getItem(key: string) {
    return this.data.has(key) ? (this.data.get(key) as string) : null
  }
  setItem(key: string, value: string) {
    if (this.failWrites) throw new Error('quota')
    this.data.set(key, value)
  }
  removeItem(key: string) {
    if (this.failWrites) throw new Error('quota')
    this.data.delete(key)
  }
}

const T = '2026-09-23T00:00:00Z'
let counter = 0
const ids = () => `id${++counter}`

function typed(text: string): Draft {
  return edit(emptyDraft(), { text, kind: 'general', correctsMessageId: null, refs: [] }, T)
}

test('a draft survives a reload in the same browser', () => {
  const store = new MemoryStore()
  const key = draftKey('case-1')
  const draft = addRef(typed('설계 v2 의 범위가 넓어요'), { kind: 'artifact', artifact_id: 'a1', revision: 2, label: '설계 v2' }, T)
  assert.equal(save(store, key, draft), true)
  const loaded = load(store, key)
  assert.equal(loaded.restored, true)
  assert.equal(loaded.error, null)
  assert.deepEqual(loaded.draft.content, draft.content)
  // 다른 대화의 초안과 섞이지 않는다.
  assert.equal(load(store, draftKey('case-2')).restored, false)
})

test('only the stored snapshot is cleared, later edits are kept', () => {
  const sent = beginSend(typed('첫 문장'), ids, T)
  // 보낸 뒤, 접수 확인이 오기 전에 사용자가 이어서 고쳤다.
  const edited = edit(sent.draft, { ...sent.draft.content, text: '첫 문장. 그리고 더' }, T)
  const settled = settle(edited, sent.clientId, 'stored', T)
  assert.equal(settled.content.text, '첫 문장. 그리고 더')
  assert.equal(settled.pending, null)

  // 고치지 않았으면 비운다.
  const untouched = settle(sent.draft, sent.clientId, 'stored', T)
  assert.equal(untouched.content.text, '')
  assert.equal(untouched.pending, null)
})

test('refused, lost and never-received sends keep the draft', () => {
  for (const outcome of ['refused', 'lost_before_persist', 'not_received'] as const) {
    const sent = beginSend(typed('보낼 말'), ids, T)
    const after = settle(sent.draft, sent.clientId, outcome, T)
    assert.equal(after.content.text, '보낼 말', outcome)
    assert.equal(after.pending, null, outcome)
  }
  // 아직 확인 중이면 아무 것도 바꾸지 않는다.
  const sent = beginSend(typed('보낼 말'), ids, T)
  assert.deepEqual(settle(sent.draft, sent.clientId, 'waiting', T), sent.draft)
})

test('resending the same content reuses the client id, changed content gets a new one', () => {
  const first = beginSend(typed('같은 말'), ids, T)
  const again = beginSend(first.draft, ids, T)
  assert.equal(again.clientId, first.clientId)
  const changed = edit(first.draft, { ...first.draft.content, text: '다른 말' }, T)
  assert.notEqual(beginSend(changed, ids, T).clientId, first.clientId)
})

test('a late outcome for an older send does not touch the newer one', () => {
  const first = beginSend(typed('하나'), ids, T)
  const changed = edit(first.draft, { ...first.draft.content, text: '둘' }, T)
  const second = beginSend(changed, ids, T)
  const late = settle(second.draft, first.clientId, 'stored', T)
  assert.deepEqual(late, second.draft)
})

test('a pending send is restored as pending, never re-sent by loading', () => {
  const store = new MemoryStore()
  const key = draftKey('case-1')
  const sent = beginSend(typed('응답을 못 받은 전송'), ids, T)
  save(store, key, sent.draft)
  const loaded = load(store, key)
  assert.equal(loaded.draft.pending?.clientId, sent.clientId)
  assert.equal(loaded.draft.content.text, '응답을 못 받은 전송')
})

test('storage failures are reported, not shown as saved', () => {
  const store = new MemoryStore()
  store.failWrites = true
  assert.equal(save(store, draftKey('c'), typed('x')), false)
  assert.equal(save(null, draftKey('c'), typed('x')), false)
  const missing = load(null, draftKey('c'))
  assert.equal(missing.restored, false)
  assert.ok(missing.error)
  const corrupt = new MemoryStore()
  corrupt.data.set(draftKey('c'), '{"content": 3}')
  const bad = load(corrupt, draftKey('c'))
  assert.equal(bad.restored, false)
  assert.ok(bad.error)
})

test('an emptied draft removes its key', () => {
  const store = new MemoryStore()
  const key = draftKey('case-1')
  save(store, key, typed('잠깐'))
  save(store, key, typed(''))
  assert.equal(store.data.has(key), false)
})

test('client ids follow the server format', () => {
  const id = newClientId(() => '1234-abcd-ef/+=:')
  assert.match(id, /^[A-Za-z0-9_-]{1,64}$/)
  assert.ok(newClientId(() => 'x'.repeat(200)).length <= 64)
})
