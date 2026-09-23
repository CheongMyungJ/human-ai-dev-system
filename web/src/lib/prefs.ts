// 화면 설정(테마·패널 폭·마지막 대화·읽던 위치)을 현재 브라우저에 기억한다(D-68). **업무 정책이
// 아니다** — 서버로 가지 않고 다른 기기와 동기화하지 않는다. **import 가 없다.**
//
// 저장소가 없거나 쓰기가 실패해도 화면은 동작한다(기본값). 그 경우 기억하지 못할 뿐이다.

export type ThemeChoice = 'light' | 'dark' | 'system'

export interface Prefs {
  theme: ThemeChoice
  sidebarWidth: number
  sidebarCollapsed: boolean
  panelWidth: number
  lastProjectId: string | null
  // 프로젝트마다 마지막으로 연 대화.
  lastCaseByProject: Record<string, string>
  // 대화마다 읽던 위치(스크롤, px).
  scrollByCase: Record<string, number>
}

export const PREFS_KEY = 'hads.prefs.v1'

export const DEFAULT_PREFS: Prefs = {
  theme: 'light',
  sidebarWidth: 280,
  sidebarCollapsed: false,
  panelWidth: 460,
  lastProjectId: null,
  lastCaseByProject: {},
  scrollByCase: {},
}

export const WIDTH_LIMITS = {
  sidebar: { min: 200, max: 440 },
  panel: { min: 320, max: 900 },
} as const

export interface KeyValueStore {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

export function clampWidth(value: number, limits: { min: number; max: number }): number {
  if (!Number.isFinite(value)) return limits.min
  return Math.min(limits.max, Math.max(limits.min, Math.round(value)))
}

export function readPrefs(store: KeyValueStore | null): Prefs {
  if (!store) return { ...DEFAULT_PREFS }
  try {
    const raw = store.getItem(PREFS_KEY)
    if (!raw) return { ...DEFAULT_PREFS }
    const parsed = JSON.parse(raw) as Partial<Prefs>
    const theme: ThemeChoice =
      parsed.theme === 'dark' || parsed.theme === 'system' || parsed.theme === 'light'
        ? parsed.theme
        : DEFAULT_PREFS.theme
    return {
      theme,
      sidebarWidth: clampWidth(Number(parsed.sidebarWidth ?? DEFAULT_PREFS.sidebarWidth), WIDTH_LIMITS.sidebar),
      sidebarCollapsed: parsed.sidebarCollapsed === true,
      panelWidth: clampWidth(Number(parsed.panelWidth ?? DEFAULT_PREFS.panelWidth), WIDTH_LIMITS.panel),
      lastProjectId: typeof parsed.lastProjectId === 'string' ? parsed.lastProjectId : null,
      lastCaseByProject:
        parsed.lastCaseByProject && typeof parsed.lastCaseByProject === 'object'
          ? { ...parsed.lastCaseByProject }
          : {},
      scrollByCase:
        parsed.scrollByCase && typeof parsed.scrollByCase === 'object' ? { ...parsed.scrollByCase } : {},
    }
  } catch {
    return { ...DEFAULT_PREFS }
  }
}

//: 읽던 위치는 최근 것만 남긴다 — 대화가 늘어도 저장소가 끝없이 커지지 않게.
export const SCROLL_MEMORY = 50

export function writePrefs(store: KeyValueStore | null, prefs: Prefs): boolean {
  if (!store) return false
  const entries = Object.entries(prefs.scrollByCase)
  const trimmed = entries.length > SCROLL_MEMORY ? Object.fromEntries(entries.slice(-SCROLL_MEMORY)) : prefs.scrollByCase
  try {
    store.setItem(PREFS_KEY, JSON.stringify({ ...prefs, scrollByCase: trimmed }))
    return true
  } catch {
    return false
  }
}

/** 적용할 테마. `system` 은 운영체제 설정을 따른다. */
export function resolveTheme(choice: ThemeChoice, systemPrefersDark: boolean): 'light' | 'dark' {
  if (choice === 'system') return systemPrefersDark ? 'dark' : 'light'
  return choice
}

/** 브라우저 저장소. 쓸 수 없으면(차단·사생활 모드 등) `null`. */
export function browserStore(): (KeyValueStore & { removeItem(key: string): void }) | null {
  try {
    const store = globalThis.localStorage
    if (!store) return null
    const probe = '__hads_probe__'
    store.setItem(probe, '1')
    store.removeItem(probe)
    return store
  } catch {
    return null
  }
}
