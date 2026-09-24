// 기본 대화 화면(UI-03, D-68·D-71). 왼쪽 목록 · 가운데 대화(또는 프로젝트 설정) · 필요할 때 여는 오른쪽 검토 패널.
//
// 이 화면이 지키는 것.
//
//   **판단은 서버가 한다.** 보낼 수 있는지, 요청이 어떤 상태인지, PC 가 연결됐는지, 원문을 쓸 수
//   있는지는 서버가 준 값을 그대로 보인다. 버튼을 끄는 것은 잠금이 아니다 — 서버가 같은 이유로
//   거부한다(FR-11).
//
//   **없는 것을 보이지 않는다.** 결과물은 실제로 있는 것만, 지원하지 않는 능력은 "지원하지 않음"
//   으로 보인다.
//
//   **화면 설정은 이 브라우저에만.** 테마·패널 폭·마지막 대화·읽던 위치·PC 알림 켬/끔은 업무 정책이 아니다.
//
//   **알림은 조회 위의 전이다**(UI-04b, D-82). 서버 도출 값의 변화를 `lib/notify.ts` 가 계산하고, 보고 있는
//   대화는 억제되며, 첫 조회는 알리지 않는다. 팝업 클릭으로 대화를 여는 것은 사람의 행동이다(자동 전환 없음).

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  conversationApi,
  shellApi,
  type ConversationRow,
  type ProjectRepository,
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
import {
  formatAddress,
  isSettingsScreen,
  parseAddress,
  screenOfTab,
  settingsTabOf,
  type Screen,
  type SettingsTab,
} from '../lib/address'
import { appendLog, diffConversations, diffProjects, NOTICE_LABEL, type Notice } from '../lib/notify'
import type { VersionRef } from '../lib/versions'
import { ConversationView } from './ConversationView'
import { listen } from './events'
import { permissionState, requestPermission, show, type PermissionState } from './notifier'
import { ProjectSettings } from './ProjectSettings'
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

/** 문서가 보이고 창에 포커스가 있는가 — 그럴 때만 "보고 있다"다(D-82 억제 조건). */
function viewingNow(): boolean {
  return document.visibilityState === 'visible' && document.hasFocus()
}

function writeAddress(address: {
  project: string | null
  case: string | null
  screen: Screen
  item: string | null
  seq: number | null
}) {
  const query = formatAddress(address)
  window.history.replaceState(null, '', query || window.location.pathname)
}

export interface NoticeEntry extends Notice {
  n: number
  at: string
  popped: boolean
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
  const [repositories, setRepositories] = useState<ProjectRepository[]>([])
  const [topError, setTopError] = useState<string | null>(null)
  const initial = useRef(parseAddress(window.location.search))
  const [projectId, setProjectId] = useState<string | null>(
    initial.current.project ?? prefs.lastProjectId,
  )
  const [caseId, setCaseId] = useState<string | null>(initial.current.case)
  const [panel, setPanel] = useState<PanelTab | null>(null)
  // UI-04a·04b. 가운데 화면(대화 / 프로젝트 설정의 탭)과 규칙 탭에서 펼칠 항목, 대화를 연 뒤 한 번 소비하는 메시지 이동.
  const [screen, setScreen] = useState<Screen>(initial.current.screen)
  const [rulesItem, setRulesItem] = useState<string | null>(initial.current.item)
  const [focusSeq, setFocusSeq] = useState<number | null>(initial.current.seq)
  const [openRequest, setOpenRequest] = useState<{ ref: VersionRef; nonce: number } | null>(null)
  const [listNonce, setListNonce] = useState(0)

  // ------------------------------------------------------------ 알림(UI-04b)
  const [permission, setPermission] = useState<PermissionState>(() => permissionState())
  const [noticeLog, setNoticeLog] = useState<NoticeEntry[]>([])
  const noticeCount = useRef(0)
  const prevProjects = useRef<ProjectWithAttention[] | null>(null)
  const prevRows = useRef<{ projectId: string; rows: ConversationRow[] } | null>(null)
  const notifyRef = useRef({ on: prefs.notifications, caseId, projectId })
  notifyRef.current = { on: prefs.notifications, caseId, projectId }
  const openNotice = useCallback((notice: Notice) => {
    // 사람이 팝업을 눌렀다 — 그 프로젝트·대화를 연다. 시스템이 스스로 옮기는 것이 아니다.
    setProjectId(notice.projectId)
    setScreen('conversation')
    setPanel(null)
    setRulesItem(null)
    if (notice.caseId) setCaseId(notice.caseId)
    else setCaseId(null)
    updatePrefs((prev) => ({ ...prev, lastProjectId: notice.projectId }))
  }, [updatePrefs])
  const record = useCallback(
    (notices: Notice[]) => {
      if (notices.length === 0) return
      const at = new Date().toISOString()
      const entries = notices.map((notice) => {
        noticeCount.current += 1
        const popped = notifyRef.current.on && !notice.suppressed ? show(notice, () => openNotice(notice)) : false
        return { ...notice, n: noticeCount.current, at, popped }
      })
      setNoticeLog((log) => appendLog(log, entries))
    },
    [openNotice],
  )

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
        record(diffProjects(prevProjects.current, nextProjects, notifyRef.current.projectId))
        prevProjects.current = nextProjects
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
  }, [record])

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
        if (!stopped) {
          setRows(next)
          // 프로젝트를 바꾼 첫 조회는 비교할 이전 상태가 없다 — 알리지 않는다.
          const prev = prevRows.current && prevRows.current.projectId === projectId ? prevRows.current.rows : null
          record(
            diffConversations(prev, next, projectId, {
              caseId: notifyRef.current.caseId,
              visible: viewingNow(),
            }),
          )
          prevRows.current = { projectId, rows: next }
        }
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
  }, [projectId, listNonce, record])

  // 등록 저장소(상세 설정 탭이 쓴다). 프로젝트가 바뀌거나 설정 화면에서 돌아오면 다시 읽는다.
  useEffect(() => {
    if (!projectId) return
    let stopped = false
    void shellApi
      .repositories(projectId)
      .then((view) => {
        if (!stopped) setRepositories(view.repositories)
      })
      .catch(() => {
        if (!stopped) setRepositories([])
      })
    return () => {
      stopped = true
    }
  }, [projectId, screen])

  // 프로젝트를 바꾸면 **그 프로젝트의 마지막 대화**를 연다(D-68). 자동으로 다른 프로젝트로 옮기지 않는다.
  const selectProject = (id: string) => {
    setProjectId(id)
    setCaseId(prefs.lastCaseByProject[id] ?? null)
    setPanel(null)
    setRulesItem(null)
    updatePrefs((prev) => ({ ...prev, lastProjectId: id }))
  }

  const selectCase = useCallback(
    (id: string | null) => {
      setCaseId(id)
      setPanel(null)
      setScreen('conversation')
      setRulesItem(null)
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

  useEffect(
    () => writeAddress({ project: projectId, case: caseId, screen, item: rulesItem, seq: focusSeq }),
    [projectId, caseId, screen, rulesItem, focusSeq],
  )

  const openSettings = (tab: SettingsTab) => {
    setScreen(screenOfTab(tab))
    if (tab !== 'rules') setRulesItem(null)
    setPanel(null)
  }

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

  // P4-05. 확인 카드가 결과물·결정 패널을 연다. UI-04b. 입력창 요약이 설정 탭을 연다.
  useEffect(
    () =>
      listen('hads:open-panel', (detail) => {
        if (detail.caseId !== caseId) return
        setPanel(detail.tab)
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

  // PC 알림 켬/끔 — 켤 때 브라우저 권한을 청한다(사람의 행동이 있을 때만 가능하다).
  const setNotifications = async (on: boolean) => {
    updatePrefs((prev) => ({ ...prev, notifications: on }))
    if (on && permissionState() === 'default') {
      setPermission(await requestPermission())
    } else {
      setPermission(permissionState())
    }
  }

  const settingsOpen = isSettingsScreen(screen)
  const panelOpen = panel !== null && !settingsOpen
  const layoutClass = [
    'sh-layout',
    prefs.sidebarCollapsed ? 'sh-sidebar-collapsed' : '',
    panelOpen ? 'sh-panel-open' : '',
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

  const onChanged = () => {
    data.refresh()
    setListNonce((n) => n + 1)
  }

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
            settingsTab={settingsOpen ? settingsTabOf(screen) : null}
            notifications={prefs.notifications}
            permission={permission}
            onSelectProject={selectProject}
            onSelectCase={selectCase}
            onNewConversation={createConversation}
            onOpenSettings={openSettings}
            onProjectCreated={(id) => {
              setListNonce((n) => n + 1)
              selectProject(id)
            }}
            onTheme={setTheme}
            onNotifications={(on) => void setNotifications(on)}
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
        <NoticeLog log={noticeLog} onOpen={openNotice} />
        {settingsOpen && project ? (
          <ProjectSettings
            key={project.id}
            project={project}
            rows={rows}
            runners={runners}
            tab={settingsTabOf(screen)}
            focusItem={rulesItem}
            lastCaseId={caseId ?? prefs.lastCaseByProject[project.id] ?? null}
            onTab={openSettings}
            onBack={() => {
              setScreen('conversation')
              setRulesItem(null)
            }}
          />
        ) : caseId && project ? (
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
            focusSeq={focusSeq}
            onFocused={() => setFocusSeq(null)}
            onScroll={(top) =>
              updatePrefs((prev) => ({ ...prev, scrollByCase: { ...prev.scrollByCase, [caseId]: top } }))
            }
            onPanel={(tab) => setPanel((current) => (current === tab ? null : tab))}
            onChanged={onChanged}
          />
        ) : (
          <EmptyCenter hasProject={Boolean(project)} onNew={createConversation} />
        )}
      </main>
      {panelOpen && panel && caseId && project && (
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
            projectId={project.id}
            tab={panel}
            conv={conv}
            detail={detail}
            preparations={data.preparations}
            runners={runners}
            repositories={repositories}
            openRequest={openRequest}
            onChanged={onChanged}
            onTab={setPanel}
            onClose={() => setPanel(null)}
          />
        </>
      )}
    </div>
  )
}

/** 화면 안 알림 기록(UI-04b). 팝업은 브라우저 밖이라 여기서 다시 본다 — 억제된 것도 표시한다. 기록은 알림이 아니다. */
function NoticeLog(props: { log: NoticeEntry[]; onOpen: (notice: Notice) => void }) {
  const [open, setOpen] = useState(false)
  const latest = props.log.length ? props.log[props.log.length - 1] : null
  return (
    <div className="sh-notice-log" data-testid="notice-log" data-count={props.log.length} aria-live="polite">
      <button type="button" className="sh-list-toggle" onClick={() => setOpen((v) => !v)} data-testid="notice-log-toggle">
        {open ? '▾' : '▸'} 알림 기록 {props.log.length}
        {latest && !open ? ` · 최근: ${NOTICE_LABEL[latest.kind]} · ${latest.title}` : ''}
      </button>
      {open && (
        <ul className="sh-result-list">
          {[...props.log].reverse().map((entry) => (
            <li
              key={entry.n}
              className="sh-rule-line"
              data-testid={`notice-${entry.n}`}
              data-kind={entry.kind}
              data-case={entry.caseId ?? ''}
              data-project={entry.projectId}
              data-suppressed={entry.suppressed ? '1' : '0'}
              data-popped={entry.popped ? '1' : '0'}
            >
              {entry.at.slice(11, 19)} · <strong>{NOTICE_LABEL[entry.kind]}</strong> · {entry.title} — {entry.body}
              {entry.suppressed ? ' · 보고 있는 대화라 팝업 없음' : entry.popped ? ' · 팝업' : ' · 팝업 없음(꺼짐·권한 없음)'}
              {entry.caseId && (
                <button type="button" className="sh-link" onClick={() => props.onOpen(entry)} data-testid={`notice-open-${entry.n}`}>
                  열기
                </button>
              )}
            </li>
          ))}
          {props.log.length === 0 && <li className="sh-muted sh-rule-line">아직 없다 — 첫 조회는 알리지 않는다</li>}
        </ul>
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
