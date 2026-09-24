// UI-04a 주소 규칙의 단위 시험(UI-PLAN-04a 5절). 실행: `npm test`.
import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import { formatAddress, messageLink, parseAddress, rulesLink } from './address.ts'

test('parses project, case, screen, item and seq; ignores malformed values', () => {
  assert.deepEqual(parseAddress('?project=p1&case=c1'), {
    project: 'p1', case: 'c1', screen: 'conversation', item: null, seq: null,
  })
  assert.deepEqual(parseAddress('?project=p1&screen=rules&item=K-001'), {
    project: 'p1', case: null, screen: 'rules', item: 'K-001', seq: null,
  })
  assert.deepEqual(parseAddress('?project=p1&case=c1&seq=7'), {
    project: 'p1', case: 'c1', screen: 'conversation', item: null, seq: 7,
  })
  // 모르는 화면·이상한 순번·이상한 항목 키는 없는 것으로 읽는다.
  assert.deepEqual(parseAddress('?screen=other&seq=abc&item=%3Cscript%3E'), {
    project: null, case: null, screen: 'conversation', item: null, seq: null,
  })
  assert.equal(parseAddress('?seq=0').seq, null)
  assert.equal(parseAddress('').screen, 'conversation')
})

test('formats only what is set and keeps item only on the rules screen', () => {
  assert.equal(formatAddress({}), '')
  assert.equal(formatAddress({ project: 'p1', case: 'c1' }), '?project=p1&case=c1')
  assert.equal(formatAddress({ project: 'p1', screen: 'rules', item: 'K-002' }), '?project=p1&screen=rules&item=K-002')
  assert.equal(formatAddress({ project: 'p1', case: 'c1', screen: 'conversation', item: 'K-002' }), '?project=p1&case=c1')
  // `seq` 는 요청일 때만 들어가고 소비한 뒤(null)에는 빠진다.
  assert.equal(formatAddress({ project: 'p1', case: 'c1', seq: 3 }), '?project=p1&case=c1&seq=3')
  assert.equal(formatAddress({ project: 'p1', case: 'c1', seq: null }), '?project=p1&case=c1')
})

test('links: rules screen with an item, and a message inside a conversation', () => {
  assert.equal(rulesLink('p1'), '?project=p1&screen=rules')
  assert.equal(rulesLink('p1', 'K-001'), '?project=p1&screen=rules&item=K-001')
  assert.equal(messageLink('p1', 'c1'), '?project=p1&case=c1')
  assert.equal(messageLink('p1', 'c1', 12), '?project=p1&case=c1&seq=12')
  // 왕복.
  assert.deepEqual(parseAddress(rulesLink('p1', 'K-001')), {
    project: 'p1', case: null, screen: 'rules', item: 'K-001', seq: null,
  })
})
