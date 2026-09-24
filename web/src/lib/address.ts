// 화면 주소(UI-03 → UI-04a → UI-04b). **import 가 없다.**
//
//   `?project=P[&case=C][&screen=rules|settings|repositories][&item=K-001][&seq=N]`
//
//   `screen=settings` 는 가운데가 프로젝트 설정 화면(기본값 탭), `screen=rules` 는 그 화면의 프로젝트 규칙
//   탭(UI-04a 의 주소 그대로 — 카드 링크·시험이 그것을 쓴다), `screen=repositories` 는 저장소 탭이다.
//   `item` 은 규칙 탭에서 펼쳐 보일 항목이다. `seq` 는 대화를 연 뒤 **한 번** 소비하는 이동 요청(원래
//   메시지로)이며 주소에 남기지 않는다 — 새로 고침이 같은 이동을 반복하지 않게. 읽던 위치 기억(D-68)보다
//   우선한다.

export type Screen = 'conversation' | 'rules' | 'settings' | 'repositories'

//: 프로젝트 설정 화면의 탭. 화면 값 → 탭.
export type SettingsTab = 'defaults' | 'rules' | 'repositories'

export const SETTINGS_SCREENS: readonly Screen[] = ['rules', 'settings', 'repositories']

export interface Address {
  project: string | null
  case: string | null
  screen: Screen
  item: string | null
  seq: number | null
}

function screenOf(raw: string | null): Screen {
  return raw === 'rules' || raw === 'settings' || raw === 'repositories' ? raw : 'conversation'
}

export function parseAddress(search: string): Address {
  const params = new URLSearchParams(search)
  const rawSeq = params.get('seq')
  const seq = rawSeq !== null && /^\d+$/.test(rawSeq) ? Number(rawSeq) : null
  const item = params.get('item')
  const screen = screenOf(params.get('screen'))
  return {
    project: params.get('project'),
    case: params.get('case'),
    screen,
    item: screen === 'rules' && item && /^[A-Za-z0-9-]{1,16}$/.test(item) ? item : null,
    seq: seq !== null && seq > 0 ? seq : null,
  }
}

/** 주소 문자열. `seq` 는 소비한 뒤에는 넣지 않는다(호출자가 null 로 준다). 빈 주소는 `''` 다. */
export function formatAddress(address: Partial<Address>): string {
  const params = new URLSearchParams()
  if (address.project) params.set('project', address.project)
  if (address.case) params.set('case', address.case)
  if (address.screen && address.screen !== 'conversation') params.set('screen', address.screen)
  if (address.screen === 'rules' && address.item) params.set('item', address.item)
  if (address.seq && address.seq > 0) params.set('seq', String(address.seq))
  const query = params.toString()
  return query ? `?${query}` : ''
}

/** 설정 화면인가(어느 탭이든). */
export function isSettingsScreen(screen: Screen): boolean {
  return SETTINGS_SCREENS.includes(screen)
}

/** 화면 값 → 설정 탭. 대화 화면이면 기본값 탭. */
export function settingsTabOf(screen: Screen): SettingsTab {
  if (screen === 'rules') return 'rules'
  if (screen === 'repositories') return 'repositories'
  return 'defaults'
}

/** 설정 탭 → 화면 값. */
export function screenOfTab(tab: SettingsTab): Screen {
  if (tab === 'rules') return 'rules'
  if (tab === 'repositories') return 'repositories'
  return 'settings'
}

/** 프로젝트 규칙 화면(설정 화면의 규칙 탭)의 링크(카드·패널이 쓴다). */
export function rulesLink(projectId: string, item?: string | null): string {
  return formatAddress({ project: projectId, screen: 'rules', item: item ?? null })
}

/** 프로젝트 설정 화면의 링크. */
export function settingsLink(projectId: string, tab: SettingsTab = 'defaults'): string {
  return formatAddress({ project: projectId, screen: screenOfTab(tab) })
}

/** 어느 대화의 어느 메시지로 가는 링크. `seq` 가 없으면 대화만 연다. */
export function messageLink(projectId: string, caseId: string, seq?: number | null): string {
  return formatAddress({ project: projectId, case: caseId, seq: seq ?? null })
}
