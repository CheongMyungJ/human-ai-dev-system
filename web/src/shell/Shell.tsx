// 기본 대화 화면(UI-03, D-68·D-71). 왼쪽 목록 · 가운데 대화 · 필요할 때 여는 오른쪽 검토 패널.
//
// 이 화면이 지키는 것.
//
//   **판단은 서버가 한다.** 보낼 수 있는지, 요청이 어떤 상태인지, PC 가 연결됐는지, 원문을 쓸 수
//   있는지는 서버가 준 값을 그대로 보인다. 버튼을 끄는 것은 잠금이 아니다 — 서버가 같은 이유로
//   거부한다(FR-11).
//
//   **없는 것을 보이지 않는다.** 결과물은 실제로 있는 것만, 지원하지 않는 능력은 "지원하지 않음"
//   으로 보인다. 업무 단계의 자동 진행은 아직 없고 관리 화면으로 연결한다(UI-PLAN-03 3.11).
//
//   **화면 설정은 이 브라우저에만.** 테마·패널 폭·마지막 대화·읽던 위치는 업무 정책이 아니다.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  conversationApi,
  shellApi,
  type ConversationRow,
  type ProjectWithAttention,
  type RunnerWithConnection,
} from '../api'
import {
  browserStore,
  clampWidth,
  readPrefs,
  resolveTheme,
  WIDTH_LIMITS,
  writePrefs,
  type Prefs,
  type ThemeChoice,
} from '../lib/prefs'
import type { VersionRef } from '../lib/versions'
import { ConversationView } from './ConversationView'
import { listen } from './events'
import { ReviewPanel, type PanelTab } from './ReviewPanel'
import { Sidebar } from './Sidebar'
import { useCaseData } from './useCaseData'
import './shell.css'

const store = browserStore()

function usePrefs(): [Prefs, (update: (prev: Prefs) => Prefs) => void] {
  const [prefs, setPrefs] = useState<Prefs>(() => readPrefs(store))
  const update = useCallback((fn: (prev: Prefs) => Prefs) => {
    setPrefs((prev) => {
      const next = fn(prev)
      writePrefs(store, next)
      return next
    })
  }, [])
  return [prefs, update]
}

function useSystemDark(): boolean {
  const query = typeof window !== 'undefined' ? window.matchMedia?.('(prefers-color-scheme: dark)') : null
  const [dark, setDark] = useState(Boolean(query?.matches))
  useEffect(() => {
    if (!query) return
    const onChange = () => setDark(query.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [query])
  return dark
}

function readAddress(): { project: string | null; case: string | null } {
  const params = new URLSearchParams(window.location.search)
  return { project: params.get('project'), case: params.get('case') }
}

function writeAddress(projectId: string | null, caseId: string | null) {
  const params = new URLSearchParams()
  if (projectId) params.set('project', projectId)
  if (caseId) params.set('case', caseId)
  const query = params.toString()
  window.history.replaceState(null, '', query ? `?${query}` : window.location.pathname)
}

export function Shell() {
  const [prefs, updatePrefs] = usePrefs()
  const systemDark = useSystemDark()
  const theme = resolveTheme(prefs.theme, systemDark)
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.style.colorScheme = theme
  }, [theme])

  const [projects, setProjects] = useState<ProjectWithAttention[]>([])
  const [runners, setRunners] = useState<RunnerWithConnection[]>([])
  const [rows, setRows] = useState<ConversationRow[]>([])
  const [topError, setTopError] = useState<string | null>(null)
  const initial = useRef(readAddress())
  const [projectId, setProjectId] = useState<string | null>(
    initial.current.project ?? prefs.lastProjectId,
  )
  const [caseId, setCaseId] = useState<string | null>(initial.current.case)
  const [panel, setPanel] = useState<PanelTab | null>(null)
  const [openRequest, setOpenRequest] = useState<{ ref: VersionRef; nonce: number } | null>(null)
  const [listNonce, setListNonce] = useState(0)

  // ---------------------------------------------------------------- 목록 조회
  useEffect(() => {
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const tick = async () => {
      try {
        const [nextProjects, nextRunners] = await Promise.all([shellApi.projects(), shellApi.runners()])
        if (stopped) return
        setProjects(nextProjects)
        setRunners(nextRunners)
        setTopError(null)
      } catch (err) {
        if (!stopped) setTopError(err instanceof Error ? err.message : String(err))
      }
      if (!stopped) timer = setTimeout(() => void tick(), 5000)
    }
    void tick()
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
    }
  }, [])

  // 프로젝트가 정해지지 않았으면 첫 프로젝트. 사라진 프로젝트를 가리키면 풀어 준다.
  useEffect(() => {
    if (projects.length === 0) return
    if (!projectId || !projects.some((p) => p.id === projectId)) {
      setProjectId(projects[0].id)
    }
  }, [projects, projectId])

  useEffect(() => {
    if (!projectId) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const tick = async () => {
      try {
        const next = await shellApi.conversations(projectId)
        if (!stopped) setRows(next)
      } catch (err) {
        if (!stopped) setTopError(err instanceof Error ? err.message : String(err))
      }
      if (!stopped) timer = setTimeout(() => void tick(), 5000)
    }
    void tick()
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
    }
  }, [projectId, listNonce])

  // 프로젝트를 바꾸면 **그 프로젝트의 마지막 대화**를 연다(D-68). 자동으로 다른 프로젝트로 옮기지 않는다.
  const selectProject = (id: string) => {
    setProjectId(id)
    setCaseId(prefs.lastCaseByProject[id] ?? null)
    setPanel(null)
    updatePrefs((prev) => ({ ...prev, lastProjectId: id }))
  }

  const selectCase = useCallback(
    (id: string | null) => {
      setCaseId(id)
      setPanel(null)
      if (projectId && id) {
        updatePrefs((prev) => ({
          ...prev,
          lastProjectId: projectId,
          lastCaseByProject: { ...prev.lastCaseByProject, [projectId]: id },
        }))
      }
    },
    [projectId, updatePrefs],
  )

  // 주소에서 온 대화가 이 프로젝트의 것이 아니면(다른 프로젝트 주소) 목록이 오면 확인한다.
  useEffect(() => {
    if (!caseId && projectId && rows.length > 0) {
      const remembered = prefs.lastCaseByProject[projectId]
      if (remembered && rows.some((r) => r.id === remembered)) setCaseId(remembered)
    }
  }, [caseId, projectId, rows, prefs.lastCaseByProject])

  useEffect(() => writeAddress(projectId, caseId), [projectId, caseId])

  // 메시지의 참조를 누르면 결과물 패널에서 **그 버전**을 연다(D-85).
  useEffect(
    () =>
      listen('hads:open-ref', (detail) => {
        if (detail.caseId !== caseId) return
        setPanel('results')
        setOpenRequest({ ref: detail.ref, nonce: Date.now() })
      }),
    [caseId],
  )

  const data = useCaseData(caseId)
  const project = useMemo(() => projects.find((p) => p.id === projectId) ?? null, [projects, projectId])

  const createConversation = async () => {
    if (!projectId) return
    try {
      const view = await conversationApi.create(projectId, '새 대화')
      setListNonce((n) => n + 1)
      selectCase(view.case_id)
    } catch (err) {
      setTopError(err instanceof Error ? err.message : String(err))
    }
  }

  // ------------------------------------------------------------ 패널 폭 조절
  const startResize = (which: 'sidebar' | 'panel') => (event: React.PointerEvent) => {
    event.preventDefault()
    const startX = event.clientX
    const startWidth = which === 'sidebar' ? prefs.sidebarWidth : prefs.panelWidth
    const limits = which === 'sidebar' ? WIDTH_LIMITS.sidebar : WIDTH_LIMITS.panel
    const move = (e: PointerEvent) => {
      const delta = e.clientX - startX
      const width = clampWidth(which === 'sidebar' ? startWidth + delta : startWidth - delta, limits)
      document.documentElement.style.setProperty(`--${which}-width`, `${width}px`)
    }
    const up = (e: PointerEvent) => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      const delta = e.clientX - startX
      const width = clampWidth(which === 'sidebar' ? startWidth + delta : startWidth - delta, limits)
      updatePrefs((prev) =>
        which === 'sidebar' ? { ...prev, sidebarWidth: width } : { ...prev, panelWidth: width },
      )
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  useEffect(() => {
    document.documentElement.style.setProperty('--sidebar-width', `${prefs.sidebarWidth}px`)
    document.documentElement.style.setProperty('--panel-width', `${prefs.panelWidth}px`)
  }, [prefs.sidebarWidth, prefs.panelWidth])

  const setTheme = (choice: ThemeChoice) => updatePrefs((prev) => ({ ...prev, theme: choice }))

  const layoutClass = [
    'sh-layout',
    prefs.sidebarCollapsed ? 'sh-sidebar-collapsed' : '',
    panel ? 'sh-panel-open' : '',
  ].join(' ')

  const conv = data.conv && data.conv.case_id === caseId ? data.conv : null
  const detail = data.detail && data.detail.id === caseId ? data.detail : null

  // 열린 대화의 요청 상태·단계가 바뀌면 목록도 바로 다시 묻는다 — 목록이 5초 동안 옛 상태
  // ("처리 중")를 보이지 않게.
  const listSignal = conv
    ? `${conv.case_id}|${conv.current_request?.state ?? '-'}|${conv.current_request?.stopping ?? '-'}|${conv.stage}|${conv.needs_response}|${conv.visibility.archived}`
    : ''
  useEffect(() => {
    if (listSignal) setListNonce((n) => n + 1)
  }, [listSignal])

  return (
    <div className={layoutClass} data-testid="shell">
      {!prefs.sidebarCollapsed && (
        <>
          <Sidebar
            projects={projects}
            project={project}
            runners={runners}
            rows={rows}
            caseId={caseId}
            theme={prefs.theme}
            onSelectProject={selectProject}
            onSelectCase={selectCase}
            onNewConversation={createConversation}
            onProjectCreated={(id) => {
              setListNonce((n) => n + 1)
              selectProject(id)
            }}
            onTheme={setTheme}
            onCollapse={() => updatePrefs((prev) => ({ ...prev, sidebarCollapsed: true }))}
          />
          <div
            className="sh-resizer"
            role="separator"
            aria-label="목록 폭 조절"
            onPointerDown={startResize('sidebar')}
          />
        </>
      )}
      <main className="sh-center">
        {prefs.sidebarCollapsed && (
          <button
            type="button"
            className="sh-icon-button sh-expand"
            title="목록 펼치기"
            onClick={() => updatePrefs((prev) => ({ ...prev, sidebarCollapsed: false }))}
          >
            ☰
          </button>
        )}
        {topError && <div className="sh-banner sh-error">서버와 통신하지 못했다: {topError}</div>}
        {caseId && project ? (
          <ConversationView
            key={caseId}
            caseId={caseId}
            project={project}
            conv={conv}
            detail={detail}
            preparations={data.preparations}
            dataError={data.error}
            runners={runners}
            panel={panel}
            scrollTop={prefs.scrollByCase[caseId] ?? null}
            onScroll={(top) =>
              updatePrefs((prev) => ({ ...prev, scrollByCase: { ...prev.scrollByCase, [caseId]: top } }))
            }
            onPanel={(tab) => setPanel((current) => (current === tab ? null : tab))}
            onChanged={() => {
              data.refresh()
              setListNonce((n) => n + 1)
            }}
          />
        ) : (
          <EmptyCenter hasProject={Boolean(project)} onNew={createConversation} />
        )}
      </main>
      {panel && caseId && (
        <>
          <div
            className="sh-resizer"
            role="separator"
            aria-label="검토 패널 폭 조절"
            onPointerDown={startResize('panel')}
          />
          <ReviewPanel
            key={caseId}
            caseId={caseId}
            tab={panel}
            conv={conv}
            detail={detail}
            preparations={data.preparations}
            runners={runners}
            openRequest={openRequest}
            onTab={setPanel}
            onClose={() => setPanel(null)}
          />
        </>
      )}
    </div>
  )
}

function EmptyCenter(props: { hasProject: boolean; onNew: () => void }) {
  return (
    <div className="sh-empty">
      {props.hasProject ? (
        <>
          <p>대화를 고르거나 새로 시작한다.</p>
          <button type="button" className="sh-primary" onClick={props.onNew}>
            새 대화
          </button>
          <p className="sh-muted">
            목표나 업무 유형을 정하지 않아도 시작할 수 있다. 분명한 작업 요청을 보내면 같은 대화에서
            업무로 전환된다.
          </p>
        </>
      ) : (
        <p>프로젝트가 없다. 왼쪽에서 프로젝트를 추가한다.</p>
      )}
    </div>
  )
}
