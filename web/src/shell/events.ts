// 화면 부분 사이의 신호. 결과물 패널의 `대화에 참조`가 입력창 초안에 붙고, 메시지의 `수정해서 다시
// 요청`이 입력창을 정정 모드로 바꾸며, 메시지의 참조가 결과물 패널에서 **그 버전**을 연다.
// 서버로 가는 것은 없다 — 보내는 것은 입력창의 전송뿐이다.

import type { DraftRef } from '../lib/drafts'
import type { VersionRef } from '../lib/versions'

export interface ShellEvents {
  'hads:attach-ref': { caseId: string; ref: DraftRef }
  'hads:correct': { caseId: string; messageId: string; seq: number; text: string }
  'hads:open-ref': { caseId: string; ref: VersionRef }
  // P4-05. 확인 카드가 결과물·결정 패널을 연다.
  'hads:open-panel': { caseId: string; tab: 'results' | 'decisions' }
}

export function emit<K extends keyof ShellEvents>(name: K, detail: ShellEvents[K]) {
  window.dispatchEvent(new CustomEvent(name, { detail }))
}

export function listen<K extends keyof ShellEvents>(
  name: K,
  handler: (detail: ShellEvents[K]) => void,
): () => void {
  const wrapped = (event: Event) => handler((event as CustomEvent<ShellEvents[K]>).detail)
  window.addEventListener(name, wrapped)
  return () => window.removeEventListener(name, wrapped)
}
