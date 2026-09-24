// 왼쪽 목록(D-68·D-69·D-72·D-82). 현재 프로젝트 · 새 대화 · 프로젝트 설정(기본값·규칙·저장소) · 답변이 필요한
// 대화 · 최근 대화 · 보관된 대화, 아래에 PC 연결·테마·PC 알림·관리 화면. 목록 행에는 제목과 **필요한 상태만** 보인다.
//
// 다른 프로젝트의 주의 상태(답변 필요·실행 상태 확인 필요)는 선택기에 수로 알리고 **자동으로
// 옮기지 않는다.** 보관은 목록 정리이며 종료가 아니다 — 보관된 대화도 복원해 이어 간다.

import { useState } from 'react'

import {
  api,
  conversationApi,
  PROFILE_LABEL,
  RUNNER_CONNECTION_LABEL,
  type ConversationRow,
  type ProjectWithAttention,
  type RunnerWithConnection,
} from '../api'
import type { SettingsTab } from '../lib/address'
import type { ThemeChoice } from '../lib/prefs'
import type { PermissionState } from './notifier'

const CLOSED_STATUSES = new Set(['closed', 'cancelled'])

function attentionText(project: ProjectWithAttention): string {
  const parts: string[] = []
  if (project.attention.needs_response) parts.push(`답변 필요 ${project.attention.needs_response}`)
  if (project.attention.request_unknown) parts.push(`확인 필요 ${project.attention.request_unknown}`)
  if (project.attention.budget_stopped) parts.push(`예산 도달 ${project.attention.budget_stopped}`)
  return parts.length ? ` · ${parts.join(' · ')}` : ''
}

function rowBadges(row: ConversationRow): { text: string; tone: string }[] {
  const badges: { text: string; tone: string }[] = []
  if (row.current_request_state === 'unknown') {
    badges.push({ text: '실행 상태 확인 필요', tone: 'warn' })
  } else if (row.current_request_stopping) {
    badges.push({ text: '중단 요청 중', tone: 'warn' })
  } else if (row.current_request_state === 'processing') {
    badges.push({ text: '처리 중', tone: 'info' })
  }
  if (row.needs_response) badges.push({ text: '답변 필요', tone: 'attention' })
  // UI-04b 보충. 예산 hard 도달로 새 실행이 중지됨(서버 도출).
  if (row.budget_stopped) badges.push({ text: '예산 도달', tone: 'warn' })
  // D-96(P4-10b). 읽기 전용 실행이 폴더를 바꿨다(알림 — 실패 아님).
  if (row.read_only_changes) badges.push({ text: `읽기 전용 변경 ${row.read_only_changes}`, tone: 'warn' })
  // P4-05. 진행 상태(서버 도출). 확인 필요·막힘·멈춤만 보인다 — 진행 중은 "처리 중"이 이미 말한다.
  if (row.progress_state === 'waiting_human' && !row.needs_response) {
    badges.push({ text: '확인 필요', tone: 'attention' })
  } else if (row.progress_state === 'blocked') {
    badges.push({ text: '막힘', tone: 'warn' })
  } else if (row.progress_state === 'paused') {
    badges.push({ text: '멈춤', tone: 'warn' })
  }
  if (row.effective_stage === 'work') {
    badges.push({ text: row.profile ? PROFILE_LABEL[row.profile] ?? row.profile : row.kind, tone: 'plain' })
  }
  // P4-09(e). 취소는 종료의 한 종류지만 성공·예외 인수가 아니다 — 따로 보인다.
  if (row.status === 'cancelled') badges.push({ text: '취소됨', tone: 'plain' })
  else if (CLOSED_STATUSES.has(row.status)) badges.push({ text: '종료', tone: 'plain' })
  return badges
}

function byActivity(a: ConversationRow, b: ConversationRow): number {
  return (b.last_activity_at ?? b.updated_at).localeCompare(a.last_activity_at ?? a.updated_at)
}

export function Sidebar(props: {
  projects: ProjectWithAttention[]
  project: ProjectWithAttention | null
  runners: RunnerWithConnection[]
  rows: ConversationRow[]
  caseId: string | null
  theme: ThemeChoice
  // UI-04b. 가운데가 프로젝트 설정 화면이면 그 탭(규칙 탭은 UI-04a 의 프로젝트 규칙 화면이 옮겨 온 것).
  settingsTab: SettingsTab | null
  // UI-04b. PC 알림(D-82) — 이 브라우저의 설정과 브라우저 권한 상태.
  notifications: boolean
  permission: PermissionState
  // UI-04d(D-84). 대화 검색 — 제출하면 가운데가 검색 화면이 된다. 검색어는 주소·서버에 남지 않는다.
  searchOpen: boolean
  onSearch: (query: string) => void
  onSelectProject: (id: string) => void
  onSelectCase: (id: string) => void
  // P4-09(g). 목록에서 이름을 바꾼 뒤 목록·대화를 다시 읽는다.
  onRenamed?: () => void
  onNewConversation: () => void
  onOpenSettings: (tab: SettingsTab) => void
  onProjectCreated: (id: string) => void
  onTheme: (choice: ThemeChoice) => void
  onNotifications: (on: boolean) => void
  onCollapse: () => void
}) {
  const [showArchived, setShowArchived] = useState(false)
  const [renaming, setRenaming] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [renameError, setRenameError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [path, setPath] = useState('')
  const [addError, setAddError] = useState<string | null>(null)

  const active = props.rows.filter((r) => !r.archived).sort(byActivity)
  const needs = active.filter((r) => r.needs_response)
  const archived = props.rows.filter((r) => r.archived).sort(byActivity)

  // P4-09(g), D-93. 목록 행의 이름 바꾸기 — 행 위의 ✎ 로 인라인 입력을 연다(1~200자). 제목은 표시값이다.
  const rename = async (row: ConversationRow) => {
    const next = renameValue.trim()
    if (!next || next === row.title) {
      setRenaming(null)
      return
    }
    try {
      await conversationApi.setTitle(row.id, next)
      setRenaming(null)
      props.onRenamed?.()
    } catch (err) {
      setRenameError(err instanceof Error ? err.message : String(err))
    }
  }
  const renderRow = (row: ConversationRow) => (
    <li key={row.id} className="sh-row-item">
      {renaming === row.id ? (
        <form
          className="sh-composer-bar sh-rename-form"
          data-testid={`rename-form-${row.id}`}
          onSubmit={(e) => {
            e.preventDefault()
            void rename(row)
          }}
        >
          <input
            className="sh-input sh-rule-input"
            value={renameValue}
            maxLength={200}
            autoFocus
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setRenaming(null)
            }}
            data-testid={`rename-input-${row.id}`}
          />
          <button type="submit" className="sh-primary" data-testid={`rename-save-${row.id}`}>
            저장
          </button>
          <button type="button" onClick={() => setRenaming(null)}>
            취소
          </button>
          {renameError && <span className="sh-notice sh-notice-warn">{renameError}</span>}
        </form>
      ) : (
        <>
          <button
            type="button"
            className={row.id === props.caseId ? 'sh-row sh-row-active' : 'sh-row'}
            onClick={() => props.onSelectCase(row.id)}
            data-testid={`conversation-row-${row.id}`}
          >
            <span className="sh-row-title">{row.title}</span>
            <span className="sh-row-badges">
              {rowBadges(row).map((badge) => (
                <span key={badge.text} className={`sh-badge sh-badge-${badge.tone}`}>
                  {badge.text}
                </span>
              ))}
            </span>
          </button>
          <button
            type="button"
            className="sh-icon-button sh-row-rename"
            title="이름 바꾸기"
            data-testid={`rename-${row.id}`}
            onClick={() => {
              setRenameValue(row.title)
              setRenameError(null)
              setRenaming(row.id)
            }}
          >
            ✎
          </button>
        </>
      )}
    </li>
  )

  return (
    <aside className="sh-sidebar" data-testid="sidebar">
      <div className="sh-sidebar-top">
        <label className="sh-project-select">
          <span className="sh-visually-hidden">프로젝트</span>
          <select
            value={props.project?.id ?? ''}
            onChange={(e) => props.onSelectProject(e.target.value)}
            data-testid="project-select"
          >
            {props.projects.length === 0 && <option value="">프로젝트 없음</option>}
            {props.projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
                {project.id === props.project?.id ? '' : attentionText(project)}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="sh-icon-button" title="목록 접기" onClick={props.onCollapse}>
          ⟨
        </button>
      </div>
      <button
        type="button"
        className="sh-new"
        disabled={!props.project}
        onClick={props.onNewConversation}
        data-testid="new-conversation"
      >
        ＋ 새 대화
      </button>
      <form
        className={props.searchOpen ? 'sh-search-form sh-search-form-on' : 'sh-search-form'}
        data-testid="search-form"
        onSubmit={(event) => {
          event.preventDefault()
          if (query.trim()) props.onSearch(query.trim())
        }}
      >
        <input
          value={query}
          placeholder="대화 검색(보관 포함)"
          disabled={!props.project}
          onChange={(e) => setQuery(e.target.value)}
          data-testid="search-input"
          aria-label="대화 검색"
        />
        <button type="submit" disabled={!props.project || !query.trim()} data-testid="search-submit" title="제목·요약·결정·규칙은 서버에서, 본문은 작업 PC 에서">
          검색
        </button>
      </form>
      <button
        type="button"
        className={props.settingsTab === 'defaults' || props.settingsTab === 'repositories' ? 'sh-row sh-row-active sh-rules-entry' : 'sh-row sh-rules-entry'}
        disabled={!props.project}
        onClick={() => props.onOpenSettings('defaults')}
        data-testid="open-settings"
      >
        <span className="sh-row-title">프로젝트 설정</span>
      </button>
      <button
        type="button"
        className={props.settingsTab === 'rules' ? 'sh-row sh-row-active sh-rules-entry sh-rules-sub' : 'sh-row sh-rules-entry sh-rules-sub'}
        disabled={!props.project}
        onClick={() => props.onOpenSettings('rules')}
        data-testid="open-rules"
      >
        <span className="sh-row-title">프로젝트 규칙</span>
      </button>

      <nav className="sh-lists">
        {needs.length > 0 && (
          <>
            <h2 className="sh-list-title">답변이 필요한 대화</h2>
            <ul className="sh-list">{needs.map(renderRow)}</ul>
          </>
        )}
        <h2 className="sh-list-title">대화</h2>
        <ul className="sh-list" data-testid="conversation-list">
          {active.map(renderRow)}
          {active.length === 0 && <li className="sh-muted sh-list-empty">아직 대화가 없다</li>}
        </ul>
        {archived.length > 0 && (
          <>
            <button
              type="button"
              className="sh-list-toggle"
              onClick={() => setShowArchived((v) => !v)}
            >
              {showArchived ? '▾' : '▸'} 보관된 대화 {archived.length}
            </button>
            {showArchived && <ul className="sh-list sh-list-archived">{archived.map(renderRow)}</ul>}
          </>
        )}
      </nav>

      <div className="sh-sidebar-bottom">
        <ul className="sh-runners" data-testid="runner-status">
          {props.runners.map((runner) => (
            <li
              key={runner.id}
              className={runner.connection.state === 'connected' ? 'sh-runner-ok' : 'sh-runner-off'}
              title={`기준 ${runner.connection.stale_after_seconds}초`}
            >
              <span className="sh-dot" aria-hidden="true" />
              {RUNNER_CONNECTION_LABEL[runner.connection.state]} · {runner.host}
              {runner.connection.state !== 'connected' && runner.connection.last_seen_at && (
                <span className="sh-muted"> · 마지막 확인 {runner.connection.last_seen_at.slice(11, 19)}</span>
              )}
            </li>
          ))}
          {props.runners.length === 0 && (
            <li className="sh-runner-off">
              <span className="sh-dot" aria-hidden="true" />
              등록된 PC 없음 — scripts\run-runner.ps1
            </li>
          )}
        </ul>
        {adding ? (
          <form
            className="sh-add-project"
            onSubmit={async (event) => {
              event.preventDefault()
              if (!name.trim() || !path.trim()) return
              try {
                const created = await api.createProject(name.trim(), path.trim())
                setAdding(false)
                setName('')
                setPath('')
                setAddError(null)
                props.onProjectCreated(created.id)
              } catch (err) {
                setAddError(err instanceof Error ? err.message : String(err))
              }
            }}
          >
            <input value={name} placeholder="프로젝트 이름" onChange={(e) => setName(e.target.value)} />
            <input
              value={path}
              placeholder="대표 저장소 경로 (작업 PC 기준)"
              onChange={(e) => setPath(e.target.value)}
            />
            {addError && <p className="sh-error-text">{addError}</p>}
            <div className="sh-row-actions">
              <button type="submit" className="sh-primary">
                추가
              </button>
              <button type="button" onClick={() => setAdding(false)}>
                취소
              </button>
            </div>
          </form>
        ) : (
          <button type="button" className="sh-link" onClick={() => setAdding(true)}>
            프로젝트 추가
          </button>
        )}
        <div className="sh-settings" data-testid="notify-settings">
          <label title="답변·확인 필요·막힘·완료를 알린다. 일상 진행은 알리지 않고, 보고 있는 대화는 팝업을 억제한다">
            <input
              type="checkbox"
              checked={props.notifications}
              onChange={(e) => props.onNotifications(e.target.checked)}
              data-testid="notify-toggle"
            />{' '}
            PC 알림
          </label>
          <span className="sh-muted" data-testid="notify-state" data-permission={props.permission}>
            {!props.notifications
              ? '꺼짐'
              : props.permission === 'granted'
                ? '켜짐'
                : props.permission === 'denied'
                  ? '브라우저가 차단함(기록만)'
                  : props.permission === 'unsupported'
                    ? '이 브라우저는 지원하지 않음(기록만)'
                    : '권한 필요(기록만)'}
          </span>
        </div>
        <div className="sh-settings">
          <label>
            테마{' '}
            <select
              value={props.theme}
              onChange={(e) => props.onTheme(e.target.value as ThemeChoice)}
              data-testid="theme-select"
            >
              <option value="light">라이트</option>
              <option value="dark">다크</option>
              <option value="system">시스템 따르기</option>
            </select>
          </label>
          <a
            className="sh-link"
            href={`?view=admin${props.project ? `&project=${props.project.id}` : ''}${
              props.caseId ? `&case=${props.caseId}` : ''
            }`}
          >
            관리 화면
          </a>
        </div>
      </div>
    </aside>
  )
}
