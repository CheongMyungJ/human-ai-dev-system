// D-85 결과물 목록·검토 버전 유지의 단위 시험(UI-PLAN-03 AC-17).
import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import {
  buildResultDocs,
  isLatest,
  newerVersions,
  openLatest,
  openRef,
  type ResultDoc,
} from './versions.ts'

const intents = [
  { id: 'iv2', revision: 2, artifact_id: 'a-int-2', artifact_rev: 1, created_at: '2' },
  { id: 'iv1', revision: 1, artifact_id: 'a-int-1', artifact_rev: 1, created_at: '1' },
]

test('only existing results become documents', () => {
  assert.deepEqual(buildResultDocs({ intents: [], preparations: [], runs: [] }), [])
  const docs = buildResultDocs({
    intents,
    preparations: [
      { stage: 'design', revision: 1, artifact_id: 'a-d1', artifact_rev: 1, created_at: '3' },
    ],
    runs: [
      { run_id: 'reply-1', purpose: 'discussion_reply', output_artifact_id: 'o1', created_at: '1', finished_at: '1' },
      { run_id: 'run-2', purpose: 'limited_analysis', output_artifact_id: 'o2', created_at: '2', finished_at: '2' },
      { run_id: 'run-3', purpose: 'limited_analysis', output_artifact_id: null, created_at: '3', finished_at: null },
    ],
  })
  assert.deepEqual(docs.map((d) => d.key), ['intent', 'prep:design', 'run:run-2'])
  // 계획이 없으면 계획 문서가 없다. 논의 응답은 대화에 있으므로 결과물에 넣지 않는다.
  assert.equal(docs.find((d) => d.key === 'prep:plan'), undefined)
  assert.deepEqual(docs[0].versions.map((v) => v.label), ['v1', 'v2'])
})

test('opening from the list shows the latest version', () => {
  const [intent] = buildResultDocs({ intents, preparations: [], runs: [] })
  assert.deepEqual(openLatest(intent).pinned, { artifact_id: 'a-int-2', revision: 1 })
})

test('a pinned version stays pinned when a newer one appears', () => {
  const [before] = buildResultDocs({ intents: intents.slice(1), preparations: [], runs: [] })
  const viewer = openLatest(before)
  assert.deepEqual(viewer.pinned, { artifact_id: 'a-int-1', revision: 1 })
  const [after] = buildResultDocs({ intents, preparations: [], runs: [] })
  // 목록은 바뀌었지만 열람 버전은 그대로이고, 새 버전은 안내 대상이다.
  assert.deepEqual(newerVersions(after, viewer.pinned).map((v) => v.label), ['v2'])
  assert.equal(isLatest(after, viewer.pinned), false)
  assert.equal(isLatest(after, { artifact_id: 'a-int-2', revision: 1 }), true)
})

test('a reference from an old message opens that exact version', () => {
  const docs: ResultDoc[] = buildResultDocs({ intents, preparations: [], runs: [] })
  const viewer = openRef(docs, { artifact_id: 'a-int-1', revision: 1 })
  assert.deepEqual(viewer, { docKey: 'intent', pinned: { artifact_id: 'a-int-1', revision: 1 } })
  // 모르는 버전은 지어내지 않는다.
  assert.equal(openRef(docs, { artifact_id: 'nope', revision: 1 }), null)
})
