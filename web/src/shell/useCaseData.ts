// 열린 대화 하나의 서버 상태. **조회를 반복한다**(푸시·알림은 UI-04). 처리 중이거나 접수 대기인
// 메시지가 있으면 짧게, 아니면 길게 묻는다.

import { useCallback, useEffect, useRef, useState } from 'react'

import {
  api,
  conversationApi,
  preparationApi,
  type CaseDetail,
  type ConversationView,
  type IntentStateView,
  type PreparationArtifact,
} from '../api'

export type ShellCaseDetail = CaseDetail & { intent_state: IntentStateView }

export interface CaseData {
  conv: ConversationView | null
  detail: ShellCaseDetail | null
  preparations: PreparationArtifact[]
  error: string | null
  loadedAt: string | null
  refresh: () => void
}

const FAST_MS = 1500
const SLOW_MS = 5000

function busy(conv: ConversationView | null): boolean {
  if (!conv) return false
  return (
    conv.current_request !== null ||
    conv.messages.some((m) => m.receipt === 'pending') ||
    // P4-05. 진행기가 실행을 만들고 있는 동안도 짧게 묻는다.
    conv.progress?.state === 'running'
  )
}

export function useCaseData(caseId: string | null): CaseData {
  const [conv, setConv] = useState<ConversationView | null>(null)
  const [detail, setDetail] = useState<ShellCaseDetail | null>(null)
  const [preparations, setPreparations] = useState<PreparationArtifact[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loadedAt, setLoadedAt] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)
  const convRef = useRef<ConversationView | null>(null)
  const lastDetailAt = useRef(0)
  // P4-05. 진행 상태가 바뀌면(걸음·대기) 상세도 바로 다시 묻는다 — 카드가 옛 버전을 가리키지 않게.
  const lastProgressStamp = useRef<string | null>(null)

  const refresh = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    setConv(null)
    setDetail(null)
    setPreparations([])
    setError(null)
    convRef.current = null
    lastDetailAt.current = 0
  }, [caseId])

  useEffect(() => {
    if (!caseId) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const tick = async (forceDetail: boolean) => {
      try {
        const nextConv = await conversationApi.get(caseId)
        if (stopped) return
        convRef.current = nextConv
        setConv(nextConv)
        const stamp = nextConv.progress ? `${nextConv.progress.state}|${nextConv.progress.updated_at}` : null
        const progressChanged = stamp !== lastProgressStamp.current
        lastProgressStamp.current = stamp
        if (forceDetail || progressChanged || Date.now() - lastDetailAt.current >= SLOW_MS) {
          const [nextDetail, preps] = await Promise.all([
            api.getCase(caseId) as Promise<ShellCaseDetail>,
            preparationApi.artifacts(caseId).catch(() => [] as PreparationArtifact[]),
          ])
          if (stopped) return
          lastDetailAt.current = Date.now()
          setDetail(nextDetail)
          setPreparations(preps)
        }
        setError(null)
        setLoadedAt(new Date().toISOString())
      } catch (err) {
        if (!stopped) setError(err instanceof Error ? err.message : String(err))
      }
      if (!stopped) {
        timer = setTimeout(() => void tick(false), busy(convRef.current) ? FAST_MS : SLOW_MS)
      }
    }
    void tick(true)
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
    }
  }, [caseId, nonce])

  return { conv, detail, preparations, error, loadedAt, refresh }
}
