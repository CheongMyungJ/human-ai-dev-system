// 원문 본문 불러오기(UI-03 3.4). 본문은 **소유 PC 에서 열람 중계로** 온다 — 서버에 저장되지 않는다.
//
//   **브라우저 메모리에만 둔다.** 탭이 살아 있는 동안의 사본이며 브라우저 저장소에 쓰지 않는다.
//   한 번 불러온 본문은 PC 가 끊겨도 보인다(D-75 "이미 불러온 내용 유지").
//
//   **PC 가 미연결이면 새 열람 요청을 만들지 않는다.** "연결 필요"를 보이고, 연결되면 불러온다.
//   서버는 미연결에도 열람 요청을 대기시키지만(UI-02) 그 대기를 화면이 쌓지 않는다.
//
//   **의도 원문은 부르는 쪽이 사람의 열람일 때만 부른다.** 의도 원문 전달은 "사람이 원문을
//   확인했다"는 기록을 남긴다 — 화면이 스스로 불러오면 그 기록이 거짓이 된다.

import { useEffect, useState } from 'react'

import { intentApi, type Availability } from '../api'

export type BodyStatus =
  | 'idle'
  | 'loading'
  | 'loaded'
  | 'needs_connection'
  | 'pending_store'
  | 'lost'
  | 'expired'
  | 'failed'

export interface BodyState {
  status: BodyStatus
  text?: string
  detail?: string
}

export const BODY_STATUS_LABEL: Record<BodyStatus, string> = {
  idle: '불러오기 전',
  loading: '원문을 PC 에서 불러오는 중',
  loaded: '불러옴',
  needs_connection: '연결 필요 — 원문은 PC 에 있고 PC 가 연결되면 불러온다',
  pending_store: 'PC 저장 전 — 아직 접수되지 않았다',
  lost: '저장 전 유실 — 원문이 PC 에 닿지 않았다',
  expired: '열람 중계가 끊겼다 — 다시 불러온다',
  failed: '불러오지 못했다',
}

const cache = new Map<string, BodyState>()
const listeners = new Map<string, Set<() => void>>()
const queue: Array<() => Promise<void>> = []
let active = 0
const MAX_ACTIVE = 3
//: 열람 결과를 기다리는 한도. Runner 제어 루프는 1초마다 열람을 처리한다.
const WAIT_MS = 30_000

export function bodyKey(artifactId: string, revision: number): string {
  return `${artifactId}@${revision}`
}

function set(key: string, state: BodyState) {
  cache.set(key, state)
  for (const listener of listeners.get(key) ?? []) listener()
}

export function peekBody(artifactId: string, revision: number): BodyState {
  return cache.get(bodyKey(artifactId, revision)) ?? { status: 'idle' }
}

function pump() {
  while (active < MAX_ACTIVE && queue.length > 0) {
    const job = queue.shift() as () => Promise<void>
    active += 1
    void job().finally(() => {
      active -= 1
      pump()
    })
  }
}

async function fetchOnce(key: string, artifactId: string, revision: number) {
  set(key, { status: 'loading' })
  try {
    const request = await intentApi.openRead(artifactId, revision)
    const deadline = Date.now() + WAIT_MS
    while (Date.now() < deadline) {
      const result = await intentApi.fetchRead(request.id)
      if (result.content !== null) {
        set(key, { status: 'loaded', text: result.content })
        return
      }
      if (result.request.state === 'expired') {
        set(key, { status: 'expired' })
        return
      }
      await new Promise((resolve) => setTimeout(resolve, 400))
    }
    set(key, { status: 'failed', detail: 'PC 가 제한 시간 안에 원문을 보내지 않았다' })
  } catch (err) {
    set(key, { status: 'failed', detail: err instanceof Error ? err.message : String(err) })
  }
}

export interface BodyOptions {
  // 원문을 가진 PC 가 연결돼 있는가(서버가 도출한 값).
  connected: boolean
  availability: Availability
  // `false` 면 부르지 않는다(예: 의도 원문을 사람이 열기 전).
  enabled?: boolean
}

/** 본문을 요청한다. 이미 있거나 부를 수 없는 상태면 그 상태만 적는다. */
export function requestBody(artifactId: string, revision: number, options: BodyOptions) {
  const key = bodyKey(artifactId, revision)
  const current = cache.get(key)
  if (current && (current.status === 'loaded' || current.status === 'loading')) return
  if (options.availability === 'pending') return set(key, { status: 'pending_store' })
  if (options.availability === 'lost_before_persist') return set(key, { status: 'lost' })
  if (options.enabled === false) return
  if (!options.connected) return set(key, { status: 'needs_connection' })
  if (current && current.status === 'failed') return // 사람이 다시 누를 때만 다시 부른다
  queue.push(() => fetchOnce(key, artifactId, revision))
  pump()
}

/** 실패·만료를 지우고 다시 부른다(사람이 누른 경우). */
export function retryBody(artifactId: string, revision: number, options: BodyOptions) {
  const key = bodyKey(artifactId, revision)
  cache.delete(key)
  requestBody(artifactId, revision, options)
}

export function useBody(
  artifactId: string | null,
  revision: number | null,
  options: BodyOptions,
): BodyState {
  const key = artifactId && revision !== null ? bodyKey(artifactId, revision) : ''
  const [, tick] = useState(0)
  useEffect(() => {
    if (!key) return
    const listener = () => tick((n) => n + 1)
    const set = listeners.get(key) ?? new Set()
    set.add(listener)
    listeners.set(key, set)
    return () => {
      set.delete(listener)
    }
  }, [key])
  const { connected, availability, enabled } = options
  useEffect(() => {
    if (!artifactId || revision === null) return
    requestBody(artifactId, revision, { connected, availability, enabled })
  }, [artifactId, revision, connected, availability, enabled])
  if (!key) return { status: 'idle' }
  return cache.get(key) ?? { status: 'idle' }
}
