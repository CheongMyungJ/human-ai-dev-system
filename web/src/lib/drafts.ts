// 현재 브라우저의 대화별 초안(D-83). **이 모듈은 아무 것도 import 하지 않는다** — Node 의 내장
// 시험 실행기로 그대로 돌리기 위해서다(web/src/lib/drafts.test.ts).
//
// 지키는 것 넷.
//
//   **초안 저장과 메시지 접수는 다른 상태다.** 이 모듈이 저장하는 것은 브라우저의 초안이고,
//   접수는 서버가 `stored` 로 말할 때만이다.
//
//   **접수가 확인된 전송분만 비운다.** 보낼 때의 스냅샷(보냄 기록)과 지금 초안이 같을 때만
//   비운다. 보낸 뒤 사용자가 고쳤으면 고친 초안을 남긴다 — 늦게 온 접수 확인이 새 편집을
//   지우면 안 된다.
//
//   **자동 전송하지 않는다.** 복구된 초안과 보냄 기록은 확인(대조)만 하고 다시 보내지 않는다.
//
//   **저장 실패를 저장됨으로 보이지 않는다.** 저장소가 없거나 쓰기가 실패하면 그 사실을 돌려준다.

export interface DraftRef {
  kind: 'artifact' | 'project_file'
  artifact_id?: string
  revision?: number
  repository_id?: string
  path?: string
  location?: string
  // 화면 표시용(서버로 가지 않는다).
  label: string
}

export type DraftKind = 'general' | 'correction' | 'card_answer'

export interface DraftContent {
  text: string
  kind: DraftKind
  correctsMessageId: string | null
  refs: DraftRef[]
}

export interface PendingSend {
  clientId: string
  content: DraftContent
  sentAt: string
}

export interface Draft {
  content: DraftContent
  // 보냄 기록. 접수가 확인되거나(비움) 받지 않은 것이 확인되면(유지) 지운다.
  pending: PendingSend | null
  updatedAt: string
}

export interface KeyValueStore {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}

export const DRAFT_VERSION = 'v1'

export function draftKey(caseId: string): string {
  return `hads.draft.${DRAFT_VERSION}.${caseId}`
}

export function cardDraftKey(caseId: string, questionId: string): string {
  return `hads.card.${DRAFT_VERSION}.${caseId}.${questionId}`
}

export function emptyContent(kind: DraftKind = 'general'): DraftContent {
  return { text: '', kind, correctsMessageId: null, refs: [] }
}

export function emptyDraft(kind: DraftKind = 'general'): Draft {
  return { content: emptyContent(kind), pending: null, updatedAt: '' }
}

function refKey(ref: DraftRef): string {
  return [ref.kind, ref.artifact_id ?? '', ref.revision ?? '', ref.repository_id ?? '', ref.path ?? '', ref.location ?? ''].join('|')
}

export function sameContent(a: DraftContent, b: DraftContent): boolean {
  return (
    a.text === b.text &&
    a.kind === b.kind &&
    (a.correctsMessageId ?? null) === (b.correctsMessageId ?? null) &&
    a.refs.length === b.refs.length &&
    a.refs.every((ref, i) => refKey(ref) === refKey(b.refs[i]))
  )
}

export function isEmptyContent(content: DraftContent): boolean {
  return content.text.trim() === '' && content.refs.length === 0 && content.kind !== 'correction'
}

export function edit(draft: Draft, content: DraftContent, now: string): Draft {
  return { ...draft, content, updatedAt: now }
}

export function addRef(draft: Draft, ref: DraftRef, now: string): Draft {
  if (draft.content.refs.some((r) => refKey(r) === refKey(ref))) return draft
  return edit(draft, { ...draft.content, refs: [...draft.content.refs, ref] }, now)
}

/**
 * 보내기 시작. 같은 내용을 다시 보내면 **같은 전송 식별자**를 쓴다 — 응답을 못 받은 전송이 두 번
 * 접수되지 않는다(서버가 같은 식별자·같은 내용은 재전송으로 본다). 내용이 바뀌었으면 새 식별자다.
 */
export function beginSend(
  draft: Draft,
  newClientId: () => string,
  now: string,
): { draft: Draft; clientId: string } {
  const reuse = draft.pending && sameContent(draft.pending.content, draft.content)
  const clientId = reuse && draft.pending ? draft.pending.clientId : newClientId()
  return {
    clientId,
    draft: { ...draft, pending: { clientId, content: draft.content, sentAt: now }, updatedAt: now },
  }
}

//: 전송의 결말. `stored` 만 접수다.
export type SendOutcome = 'stored' | 'waiting' | 'lost_before_persist' | 'not_received' | 'refused'

/**
 * 전송의 결말을 초안에 반영한다. **그 보냄 기록의 결말일 때만** 바꾼다 — 다른(더 새) 전송의
 * 기록을 늦게 온 옛 결말이 지우지 않는다.
 */
export function settle(draft: Draft, clientId: string, outcome: SendOutcome, now: string): Draft {
  if (!draft.pending || draft.pending.clientId !== clientId) return draft
  if (outcome === 'waiting') return draft
  if (outcome === 'stored') {
    const unchanged = sameContent(draft.content, draft.pending.content)
    return {
      content: unchanged ? emptyContent(draft.content.kind === 'card_answer' ? 'card_answer' : 'general') : draft.content,
      pending: null,
      updatedAt: now,
    }
  }
  // 거부·유실·받지 않음: 입력은 사용자에게 남는다. 다시 보내는 것은 사용자다.
  return { ...draft, pending: null, updatedAt: now }
}

function isRef(value: unknown): value is DraftRef {
  if (!value || typeof value !== 'object') return false
  const ref = value as Record<string, unknown>
  return (ref.kind === 'artifact' || ref.kind === 'project_file') && typeof ref.label === 'string'
}

function isContent(value: unknown): value is DraftContent {
  if (!value || typeof value !== 'object') return false
  const c = value as Record<string, unknown>
  return (
    typeof c.text === 'string' &&
    (c.kind === 'general' || c.kind === 'correction' || c.kind === 'card_answer') &&
    (c.correctsMessageId === null || typeof c.correctsMessageId === 'string') &&
    Array.isArray(c.refs) &&
    c.refs.every(isRef)
  )
}

export interface LoadResult {
  draft: Draft
  // 복구하지 못한 이유. 있으면 화면이 "복구 불가"를 보인다(빈 초안을 복구됨으로 보이지 않는다).
  error: string | null
  restored: boolean
}

export function load(store: KeyValueStore | null, key: string, kind: DraftKind = 'general'): LoadResult {
  if (!store) return { draft: emptyDraft(kind), error: '이 브라우저에 저장소가 없다', restored: false }
  let raw: string | null
  try {
    raw = store.getItem(key)
  } catch {
    return { draft: emptyDraft(kind), error: '브라우저 저장소를 읽지 못했다', restored: false }
  }
  if (raw === null) return { draft: emptyDraft(kind), error: null, restored: false }
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>
    const pending = parsed.pending as Record<string, unknown> | null
    if (!isContent(parsed.content)) throw new Error('shape')
    const validPending =
      pending && typeof pending.clientId === 'string' && isContent(pending.content)
        ? { clientId: pending.clientId, content: pending.content, sentAt: String(pending.sentAt ?? '') }
        : null
    return {
      draft: {
        content: parsed.content,
        pending: validPending,
        updatedAt: String(parsed.updatedAt ?? ''),
      },
      error: null,
      restored: true,
    }
  } catch {
    return { draft: emptyDraft(kind), error: '저장된 초안을 읽을 수 없다(형식이 맞지 않음)', restored: false }
  }
}

/** 초안을 저장한다. 비었고 보냄 기록도 없으면 지운다. 실패하면 `false`. */
export function save(store: KeyValueStore | null, key: string, draft: Draft): boolean {
  if (!store) return false
  try {
    if (isEmptyContent(draft.content) && !draft.pending) {
      store.removeItem(key)
    } else {
      store.setItem(key, JSON.stringify(draft))
    }
    return true
  } catch {
    return false
  }
}

/** 전송 식별자. 서버 형식(`^[A-Za-z0-9_-]{1,64}$`)을 지킨다. */
export function newClientId(random: () => string): string {
  return `web-${random()}`.replace(/[^A-Za-z0-9_-]/g, '').slice(0, 64)
}
