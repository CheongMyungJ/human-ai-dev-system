// 메시지 전송과 접수 대조(D-70·D-83). **202 는 접수가 아니다** — `receipt = stored` 가 될 때만
// 접수다. 응답을 못 받은 전송은 같은 전송 식별자로 **대조만** 한다. 다시 보내는 것은 사람이다.

import { ApiError, conversationApi } from '../api'
import type { SendOutcome } from '../lib/drafts'

export interface SendResult {
  outcome: SendOutcome
  refusals: string[]
  detail: string | null
}

type SendBody = Parameters<typeof conversationApi.send>[1]

function refusalsOf(err: ApiError): { refusals: string[]; detail: string | null } {
  const detail = err.detail as { refusals?: string[]; message?: string } | string | null
  if (detail && typeof detail === 'object') {
    return { refusals: detail.refusals ?? [], detail: detail.message ?? null }
  }
  return { refusals: [], detail: typeof detail === 'string' ? detail : err.message }
}

/** 이 전송 식별자가 접수됐는가. 404 는 받은 적 없음이다. */
export async function checkReceipt(caseId: string, clientId: string): Promise<SendOutcome> {
  try {
    const found = await conversationApi.findByClientId(caseId, clientId)
    if (found.receipt === 'stored') return 'stored'
    if (found.receipt === 'lost_before_persist') return 'lost_before_persist'
    return 'waiting'
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return 'not_received'
    return 'waiting'
  }
}

/** 보내고 접수를 확인한다. 확인하지 못하면 `waiting` 이다(초안의 보냄 기록이 남는다). */
export async function sendAndConfirm(caseId: string, body: SendBody): Promise<SendResult> {
  try {
    await conversationApi.send(caseId, body)
  } catch (err) {
    if (err instanceof ApiError && err.status >= 400 && err.status < 500) {
      // 서버가 거부했다 — 받지 않았다. 사유를 그대로 보인다.
      return { outcome: 'refused', ...refusalsOf(err) }
    }
    // 응답을 못 받았다. 받았는지는 대조로만 안다.
    return { outcome: await checkReceipt(caseId, body.client_message_id), refusals: [], detail: null }
  }
  for (let i = 0; i < 40; i += 1) {
    const outcome = await checkReceipt(caseId, body.client_message_id)
    if (outcome !== 'waiting') return { outcome, refusals: [], detail: null }
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  return { outcome: 'waiting', refusals: [], detail: null }
}
