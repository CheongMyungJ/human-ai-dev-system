// 줄 비교와 실행 출력 분리의 단위 시험(UI-PLAN-03 AC-17·AC-13).
import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import { diffLines, DIFF_CELL_LIMIT } from './textDiff.ts'
import { splitRunOutput } from './runOutput.ts'
import { clampWidth, readPrefs, resolveTheme, writePrefs, WIDTH_LIMITS } from './prefs.ts'

test('changed lines are marked, unchanged lines stay', () => {
  const result = diffLines('목표\n범위: A\n제외: B\n', '목표\n범위: A, C\n제외: B\n추가 제약\n')
  assert.equal(result.tooLarge, false)
  assert.deepEqual(
    result.lines.map((l) => `${l.op}:${l.text}`),
    ['same:목표', 'removed:범위: A', 'added:범위: A, C', 'same:제외: B', 'added:추가 제약'],
  )
  assert.equal(result.added, 2)
  assert.equal(result.removed, 1)
})

test('identical texts have no changes, CRLF is not a change', () => {
  const result = diffLines('a\r\nb\r\n', 'a\nb\n')
  assert.equal(result.added + result.removed, 0)
})

test('a very large comparison is refused, not reported as equal', () => {
  const side = Math.ceil(Math.sqrt(DIFF_CELL_LIMIT)) + 10
  const a = Array.from({ length: side }, (_, i) => `a${i}`).join('\n')
  const b = Array.from({ length: side }, (_, i) => `b${i}`).join('\n')
  const result = diffLines(a, b)
  assert.equal(result.tooLarge, true)
  assert.deepEqual(result.lines, [])
})

test('a run output splits into run information and the final message', () => {
  const body = 'run_id=r1\noutcome=completed\n--- final message ---\n안녕하세요\n둘째 줄'
  assert.deepEqual(splitRunOutput(body), {
    header: 'run_id=r1\noutcome=completed',
    message: '안녕하세요\n둘째 줄',
  })
  // 구분 줄이 없으면 머리를 지어내지 않는다.
  assert.deepEqual(splitRunOutput('fake run r1\n답'), { header: null, message: 'fake run r1\n답' })
})

test('screen preferences default to the light theme and survive bad storage', () => {
  assert.equal(readPrefs(null).theme, 'light')
  const store = {
    data: new Map<string, string>(),
    getItem(key: string) {
      return this.data.get(key) ?? null
    },
    setItem(key: string, value: string) {
      this.data.set(key, value)
    },
  }
  store.data.set('hads.prefs.v1', 'not json')
  assert.equal(readPrefs(store).theme, 'light')
  const prefs = { ...readPrefs(null), theme: 'dark' as const, panelWidth: 10_000 }
  assert.equal(writePrefs(store, prefs), true)
  const back = readPrefs(store)
  assert.equal(back.theme, 'dark')
  assert.equal(back.panelWidth, WIDTH_LIMITS.panel.max)
  assert.equal(resolveTheme('system', true), 'dark')
  assert.equal(resolveTheme('system', false), 'light')
  assert.equal(clampWidth(Number.NaN, WIDTH_LIMITS.sidebar), WIDTH_LIMITS.sidebar.min)
})
