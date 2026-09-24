// 지식 원문(적용 내용) 한 번 읽기(P4-06b → UI-04a 에서 공용으로 옮김). 열람 경로로 받는다 — 서버 본문이면 바로
// 오고, 소유 PC 에만 있는 옛 원문이면 그 PC 가 올릴 때까지 기다린다. 화면이 본문을 다른 곳에 저장하지 않는다.

import { intentApi } from '../api'

export const KNOWLEDGE_STORAGE_LABEL: Record<string, string> = {
  server: '서버 저장',
  runner: 'PC 에만(소유 PC 가 연결되면 서버로 올라온다)',
}

export async function readKnowledgeBody(artifactId: string, revision: number): Promise<string> {
  const request = await intentApi.openRead(artifactId, revision)
  const deadline = Date.now() + 15_000
  while (Date.now() < deadline) {
    const result = await intentApi.fetchRead(request.id)
    if (result.content !== null) return result.content
    if (result.request.state === 'expired') throw new Error('열람 중계가 끊겼다 — 다시 시도한다')
    await new Promise((resolve) => setTimeout(resolve, 300))
  }
  throw new Error('원문이 제한 시간 안에 오지 않았다(PC 에만 있는 원문은 그 PC 가 연결돼야 한다)')
}
