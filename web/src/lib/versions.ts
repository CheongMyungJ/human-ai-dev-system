// 결과물 목록과 검토 버전 유지(D-85). **import 가 없다** — Node 내장 시험 실행기로 돌린다.
//
//   **있는 것만 나열한다.** 서버가 준 실제 산출물만 문서가 된다. 없는 종류의 빈 탭을 만들지 않는다.
//   **열람 버전은 고정된다.** 새 버전이 생겨도 본문을 바꾸지 않는다 — 안내만 하고 전환은 사용자가
//   고른다. 과거 메시지의 참조는 그 메시지가 가리킨 버전을 연다.

export interface VersionRef {
  artifact_id: string
  revision: number
}

export interface DocVersion extends VersionRef {
  label: string
  created_at: string
  availability?: string
  owner_runner_id?: string
}

export type DocKind = 'intent' | 'design' | 'dev_plan' | 'combined' | 'run_output'

export interface ResultDoc {
  key: string
  kind: DocKind
  title: string
  // 오래된 것부터. 마지막이 최신이다.
  versions: DocVersion[]
  // 실행 출력이면 그 실행.
  run_id?: string
}

// ---- 서버 응답의 필요한 부분만(구조적 타입). api.ts 를 import 하지 않는다.

export interface IntentVersionLike {
  id: string
  revision: number
  artifact_id: string
  artifact_rev?: number
  created_at: string
  availability?: string
}

export interface PreparationArtifactLike {
  stage: string
  revision: number
  artifact_id: string
  artifact_rev: number
  created_at: string
  availability?: string
  owner_runner_id?: string
}

export interface RunLike {
  run_id: string
  purpose: string | null
  output_artifact_id: string | null
  created_at: string
  finished_at: string | null
}

const STAGE_TITLE: Record<string, string> = {
  design: '설계',
  plan: '개발계획',
  combined: '결합 기록(설계+계획)',
}

const STAGE_KIND: Record<string, DocKind> = {
  design: 'design',
  plan: 'dev_plan',
  combined: 'combined',
}

export function buildResultDocs(input: {
  intents: IntentVersionLike[]
  preparations: PreparationArtifactLike[]
  runs: RunLike[]
}): ResultDoc[] {
  const docs: ResultDoc[] = []
  if (input.intents.length > 0) {
    const versions = [...input.intents]
      .sort((a, b) => a.revision - b.revision)
      .map((iv) => ({
        artifact_id: iv.artifact_id,
        revision: iv.artifact_rev ?? 1,
        label: `v${iv.revision}`,
        created_at: iv.created_at,
        availability: iv.availability,
      }))
    docs.push({ key: 'intent', kind: 'intent', title: '의도', versions })
  }
  const byStage = new Map<string, PreparationArtifactLike[]>()
  for (const prep of input.preparations) {
    const list = byStage.get(prep.stage) ?? []
    list.push(prep)
    byStage.set(prep.stage, list)
  }
  for (const stage of ['design', 'plan', 'combined']) {
    const list = byStage.get(stage)
    if (!list || list.length === 0) continue
    docs.push({
      key: `prep:${stage}`,
      kind: STAGE_KIND[stage],
      title: STAGE_TITLE[stage],
      versions: [...list]
        .sort((a, b) => a.revision - b.revision)
        .map((p) => ({
          artifact_id: p.artifact_id,
          revision: p.artifact_rev,
          label: `v${p.revision}`,
          created_at: p.created_at,
          availability: p.availability,
          owner_runner_id: p.owner_runner_id,
        })),
    })
  }
  // 실행 출력. 논의 응답은 대화의 AI 메시지로 이미 보인다 — 결과물에 두 번 넣지 않는다.
  for (const run of [...input.runs].sort((a, b) => a.created_at.localeCompare(b.created_at))) {
    if (!run.output_artifact_id || run.purpose === 'discussion_reply') continue
    docs.push({
      key: `run:${run.run_id}`,
      kind: 'run_output',
      title: `실행 출력 · ${run.purpose ?? '목적 미기록'}`,
      run_id: run.run_id,
      versions: [
        {
          artifact_id: run.output_artifact_id,
          revision: 1,
          label: run.run_id,
          created_at: run.finished_at ?? run.created_at,
        },
      ],
    })
  }
  return docs
}

export function latestVersion(doc: ResultDoc): DocVersion {
  return doc.versions[doc.versions.length - 1]
}

export function sameRef(a: VersionRef, b: VersionRef): boolean {
  return a.artifact_id === b.artifact_id && a.revision === b.revision
}

export function versionIndex(doc: ResultDoc, ref: VersionRef): number {
  return doc.versions.findIndex((v) => sameRef(v, ref))
}

/** 열람 중인 버전보다 새 버전들. 고정 버전이 목록에 없으면(알 수 없음) 빈 목록이다. */
export function newerVersions(doc: ResultDoc, pinned: VersionRef): DocVersion[] {
  const index = versionIndex(doc, pinned)
  if (index < 0) return []
  return doc.versions.slice(index + 1)
}

export function isLatest(doc: ResultDoc, ref: VersionRef): boolean {
  const index = versionIndex(doc, ref)
  return index >= 0 && index === doc.versions.length - 1
}

export function findDocFor(
  docs: ResultDoc[],
  ref: VersionRef,
): { doc: ResultDoc; version: DocVersion } | null {
  for (const doc of docs) {
    const version = doc.versions.find((v) => sameRef(v, ref))
    if (version) return { doc, version }
  }
  return null
}

export interface ViewerState {
  docKey: string
  pinned: VersionRef
}

/** 목록에서 열 때는 최신 버전이다. */
export function openLatest(doc: ResultDoc): ViewerState {
  const latest = latestVersion(doc)
  return { docKey: doc.key, pinned: { artifact_id: latest.artifact_id, revision: latest.revision } }
}

/** 과거 참조로 열 때는 **그 버전**이다. 모르는 버전이면 `null`(지어내지 않는다). */
export function openRef(docs: ResultDoc[], ref: VersionRef): ViewerState | null {
  const found = findDocFor(docs, ref)
  if (!found) return null
  return { docKey: found.doc.key, pinned: { artifact_id: ref.artifact_id, revision: ref.revision } }
}
