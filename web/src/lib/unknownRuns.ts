// P4-10d(이슈 #10, D-98). 결과를 모르는(`unknown`) 실행이 종료를 막지 않게 된 까닭의 표시. 결과는 바꾸지 않는다 —
// `superseded` 는 같은 작업의 뒤 시도가 완료해 대체됐다(자동), `confirmed` 는 사람이 실행과 작업공간 영향을 확인했다.

export type UnknownSettlement =
  | { kind: 'superseded'; by_run_id: string }
  | {
      kind: 'confirmed'
      actor: string
      reason: string
      workspace_checked: boolean
      confirmed_at: string
      decision_id: string
    }

export function unknownSettlementText(s: UnknownSettlement | null | undefined): string | null {
  if (!s) return null
  if (s.kind === 'superseded') return `결과 모름 — 뒤 시도 ${s.by_run_id} 가 완료해 대체됨(종료를 막지 않음)`
  return `결과 모름 — ${s.actor} 가 확인함(종료를 막지 않음): ${s.reason}`
}

export function unknownSettlementBadge(s: UnknownSettlement | null | undefined): string | null {
  if (!s) return null
  return s.kind === 'superseded' ? '대체됨' : '사람이 확인함'
}
