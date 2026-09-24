// 화면 주소(UI-03 → UI-04a). **import 가 없다.**
//
//   `?project=P[&case=C][&screen=rules][&item=K-001][&seq=N]`
//
//   `screen=rules` 는 가운데가 프로젝트 규칙 화면이라는 뜻이고, `item` 은 그 화면에서 펼쳐 보일 항목이다.
//   `seq` 는 대화를 연 뒤 **한 번** 소비하는 이동 요청(원래 메시지로)이며 주소에 남기지 않는다 — 새로 고침이
//   같은 이동을 반복하지 않게. 읽던 위치 기억(D-68)보다 우선한다.

export type Screen = 'conversation' | 'rules'

export interface Address {
  project: string | null
  case: string | null
  screen: Screen
  item: string | null
  seq: number | null
}

export function parseAddress(search: string): Address {
  const params = new URLSearchParams(search)
  const rawSeq = params.get('seq')
  const seq = rawSeq !== null && /^\d+$/.test(rawSeq) ? Number(rawSeq) : null
  const item = params.get('item')
  return {
    project: params.get('project'),
    case: params.get('case'),
    screen: params.get('screen') === 'rules' ? 'rules' : 'conversation',
    item: item && /^[A-Za-z0-9-]{1,16}$/.test(item) ? item : null,
    seq: seq !== null && seq > 0 ? seq : null,
  }
}

/** 주소 문자열. `seq` 는 소비한 뒤에는 넣지 않는다(호출자가 null 로 준다). 빈 주소는 `''` 다. */
export function formatAddress(address: Partial<Address>): string {
  const params = new URLSearchParams()
  if (address.project) params.set('project', address.project)
  if (address.case) params.set('case', address.case)
  if (address.screen === 'rules') params.set('screen', 'rules')
  if (address.screen === 'rules' && address.item) params.set('item', address.item)
  if (address.seq && address.seq > 0) params.set('seq', String(address.seq))
  const query = params.toString()
  return query ? `?${query}` : ''
}

/** 프로젝트 규칙 화면의 링크(카드·패널이 쓴다). */
export function rulesLink(projectId: string, item?: string | null): string {
  return formatAddress({ project: projectId, screen: 'rules', item: item ?? null })
}

/** 어느 대화의 어느 메시지로 가는 링크. `seq` 가 없으면 대화만 연다. */
export function messageLink(projectId: string, caseId: string, seq?: number | null): string {
  return formatAddress({ project: projectId, case: caseId, seq: seq ?? null })
}
