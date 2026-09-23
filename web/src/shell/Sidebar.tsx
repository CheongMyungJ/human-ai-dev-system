// 왼쪽 목록(D-68·D-69·D-82). 현재 프로젝트 · 새 대화 · 답변이 필요한 대화 · 최근 대화 · 보관된 대화,
// 아래에 PC 연결·테마·관리 화면. 목록 행에는 제목과 **필요한 상태만** 보인다.
//
// 다른 프로젝트의 주의 상태(답변 필요·실행 상태 확인 필요)는 선택기에 수로 알리고 **자동으로
// 옮기지 않는다.** 보관은 목록 정리이며 종료가 아니다 — 보관된 대화도 복원해 이어 간다.

import { useState } from 'react'

import {
  api,
  PROFILE_LABEL,
  RUNNER_CONNECTION_LABEL,
  type ConversationRow,
  type ProjectWithAttention,
  type RunnerWithConnection,
} from '../api'
import type { ThemeChoice } from '../lib/prefs'

const CLOSED_STATUSES = new Set(['closed', 'cancelled'])

function attentionText(project: ProjectWithAttention): string {
  const parts: string[] = []
  if (project.attention.needs_response) parts.push(`답변 필요 ${project.attention.needs_response}`)
  if (project.attention.request_unknown) parts.push(`확인 필요 ${project.attention.request_unknown}`)
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
  if (row.effective_stage === 'work') {
    badges.push({ text: row.profile ? PROFILE_LABEL[row.profile] ?? row.profile : row.kind, tone: 'plain' })
  }
  if (CLOSED_STATUSES.has(row.status)) badges.push({ text: '종료', tone: 'plain' })
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
  onSelectProject: (id: string) => void
  onSelectCase: (id: string) => void
  onNewConversation: () => void
  onProjectCreated: (id: string) => void
  onTheme: (choice: ThemeChoice) => void
  onCollapse: () => void
}) {
  const [showArchived, setShowArchived] = useState(false)
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [path, setPath] = useState('')
  const [addError, setAddError] = useState<string | null>(null)

  const active = props.rows.filter((r) => !r.archived).sort(byActivity)
  const needs = active.filter((r) => r.needs_response)
  const archived = props.rows.filter((r) => r.archived).sort(byActivity)

  const renderRow = (row: ConversationRow) => (
    <li key={row.id}>
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
