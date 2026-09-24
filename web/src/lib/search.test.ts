// UI-04d 대화 검색의 화면 규칙 단위 시험(UI-PLAN-04d 5절). 실행: `npm test`.
import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import type { SearchMatch, SearchScope } from '../api'
import { groupByCase, highlight, scopeText, titleMatches, tokens } from './search.ts'

test('tokens: whitespace-split, lower-cased, de-duplicated, capped', () => {
  assert.deepEqual(tokens('  Reader   오류  reader '), ['reader', '오류'])
  assert.deepEqual(tokens(''), [])
  assert.equal(tokens('a b c d e f g h i j').length, 8)
})

test('highlight: marks every word case-insensitively and keeps the rest as plain pieces', () => {
  const pieces = highlight('Reader 의 오류를 reader 가 읽는다', ['reader', '오류'])
  assert.deepEqual(pieces, [
    { text: 'Reader', hit: true },
    { text: ' 의 ', hit: false },
    { text: '오류', hit: true },
    { text: '를 ', hit: false },
    { text: 'reader', hit: true },
    { text: ' 가 읽는다', hit: false },
  ])
  assert.deepEqual(highlight('없음', ['reader']), [{ text: '없음', hit: false }])
  assert.deepEqual(highlight('', ['x']), [])
})

test('scope text names the body state and repeats the server note', () => {
  const scope = (bodies: SearchScope['bodies'], note: string): SearchScope => ({
    archived_included: true,
    server_fields: ['title'],
    bodies,
    candidate_message_count: 3,
    excluded_message_count: 3,
    expired_message_count: 0,
    unreadable_message_count: 0,
    truncated: false,
    runners: [],
    note,
  })
  assert.equal(scopeText(scope('excluded', 'PC 미연결로 본문 3건 검색 제외')), 'PC 미연결 — 본문 제외 · PC 미연결로 본문 3건 검색 제외')
  assert.equal(scopeText(scope('relayed', '제목·요약·결정과 본문(PC)을 검색했다')), '본문 포함(PC) · 제목·요약·결정과 본문(PC)을 검색했다')
  assert.equal(scopeText(scope('pending', '본문은 작업 PC 가 검색하는 중이다')).startsWith('본문 검색 중(PC)'), true)
})

test('groupByCase keeps first-seen case order and sorts matches by seq inside a group', () => {
  const m = (case_id: string, seq: number | null, kind: SearchMatch['kind'] = 'body'): SearchMatch => ({
    kind,
    case_id,
    case_title: `t-${case_id}`,
    archived: case_id === 'c2',
    status: 'received',
    seq,
    text: 'x',
    match_count: 1,
    item_key: null,
    target: seq === null ? 'decisions' : 'message',
    source: 'server',
  })
  const groups = groupByCase([m('c1', 5), m('c2', 1), m('c1', 2), m('c1', null, 'decision')])
  assert.deepEqual(groups.map((g) => [g.case_id, g.archived, g.matches.map((x) => x.seq)]), [
    ['c1', false, [null, 2, 5]],
    ['c2', true, [1]],
  ])
})

test('titleMatches needs every word', () => {
  assert.equal(titleMatches('오류 필터 기능', ['오류', '필터']), true)
  assert.equal(titleMatches('오류 필터 기능', ['오류', '검색']), false)
  assert.equal(titleMatches('', ['x']), false)
})
