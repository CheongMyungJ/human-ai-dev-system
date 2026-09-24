// 프로젝트 설정 화면(UI-04b, D-72). 탭: 기본값 · 프로젝트 규칙(UI-04a 화면이 여기로 옮겨 왔다) · 저장소.
//
//   **기본값은 이 뒤에 만드는 대화·실행에 적용된다.** 기존 대화의 설정은 그 대화의 상세 설정에서 바꾼다 —
//   프로젝트 기본값을 바꿔도 기존 정책·예산 행·실행 기록은 그대로다(소급 없음). 진행 상한은 조회 때 계산되므로
//   Case 설정이 없는 대화에 지금 값이 보인다.
//   **값·출처·적용 시점은 서버 값 그대로다.** 모델·깊이의 프로젝트 기본값은 없고 그 사실을 그대로 보인다.
//   **설정은 실행 허용·동의·인수가 아니다.** 진입 검사·예산 강제·확인 지점은 값을 읽을 뿐이다.
//   **복귀는 현재 행을 닫는 것이다**(이력 보존). 값이 아니다.

import { useCallback, useEffect, useState, type ReactNode } from 'react'

import {
  ApiError,
  AUTONOMY_LABEL,
  projectSettingsApi,
  PROJECT_SETTING_LABEL,
  PROJECT_SETTING_SOURCE_LABEL,
  repositoryApi,
  type ConversationRow,
  type ProjectRepositoryView,
  type ProjectSettingsView,
  type ProjectWithAttention,
  type RunnerWithConnection,
} from '../api'
import type { SettingsTab } from '../lib/address'
import { ProjectRules } from './ProjectRules'

function describe(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = err.detail as { message?: string } | string | undefined
    if (detail && typeof detail === 'object' && typeof detail.message === 'string') return `${err.status}: ${detail.message}`
    return `${err.status}: ${typeof detail === 'string' ? detail : err.message}`
  }
  return err instanceof Error ? err.message : String(err)
}

function when(iso: string | null | undefined): string {
  return iso ? iso.replace('T', ' ').slice(0, 19) : '—'
}

const GUARANTEE_LABEL: Record<string, string> = {
  absolute: '절대 상한',
  no_absolute_cap: '새 배정만 차단',
  display_only: '표시만',
  not_enforceable: '강제 불가',
}

const TABS: { key: SettingsTab; label: string }[] = [
  { key: 'defaults', label: '기본값' },
  { key: 'rules', label: '프로젝트 규칙' },
  { key: 'repositories', label: '저장소' },
]

export function ProjectSettings(props: {
  project: ProjectWithAttention
  rows: ConversationRow[]
  runners: RunnerWithConnection[]
  tab: SettingsTab
  focusItem: string | null
  lastCaseId: string | null
  onTab: (tab: SettingsTab) => void
  onBack: () => void
}) {
  const { project } = props
  return (
    <div className="sh-rules sh-settings-screen" data-testid="settings-screen" data-tab={props.tab}>
      <header className="sh-header">
        <div className="sh-header-title">
          <h1>프로젝트 설정 · {project.name}</h1>
          <span className="sh-muted">
            기본값(도구·확인 경계·예산·진행 상한·인라인 한도) · 프로젝트 규칙 · 저장소. 설정은 실행 허용·동의·인수가 아니다
          </span>
        </div>
        <div className="sh-header-actions">
          {TABS.map((tab) => (
            <button
              type="button"
              key={tab.key}
              className={props.tab === tab.key ? 'sh-tab sh-tab-on' : 'sh-tab'}
              onClick={() => props.onTab(tab.key)}
              data-testid={`settings-tab-${tab.key}`}
            >
              {tab.label}
            </button>
          ))}
          <button type="button" className="sh-link" onClick={props.onBack} data-testid="settings-back">
            ← 대화로
          </button>
        </div>
      </header>
      {props.tab === 'defaults' && <DefaultsTab project={project} runners={props.runners} />}
      {props.tab === 'rules' && (
        <ProjectRules
          project={project}
          rows={props.rows}
          runners={props.runners}
          focusItem={props.focusItem}
          lastCaseId={props.lastCaseId}
          onBack={props.onBack}
          embedded
        />
      )}
      {props.tab === 'repositories' && <RepositoriesTab project={project} />}
    </div>
  )
}

// ------------------------------------------------------------------ 기본값

function DefaultsTab(props: { project: ProjectWithAttention; runners: RunnerWithConnection[] }) {
  const projectId = props.project.id
  const [view, setView] = useState<ProjectSettingsView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [showHistory, setShowHistory] = useState(false)
  const load = useCallback(async () => {
    try {
      setView(await projectSettingsApi.get(projectId))
    } catch (err) {
      setError(describe(err))
    }
  }, [projectId])
  useEffect(() => {
    void load()
  }, [load])

  const change = async (values: Record<string, string | number | null>) => {
    try {
      setError(null)
      setView(await projectSettingsApi.set(projectId, values, reason))
    } catch (err) {
      setError(describe(err))
    }
  }

  if (!view) {
    return (
      <div className="sh-rules-body">
        {error ? <div className="sh-banner sh-error">{error}</div> : <p className="sh-muted">불러오는 중</p>}
      </div>
    )
  }
  const settings = view.settings
  return (
    <div className="sh-rules-body" data-testid="settings-defaults">
      {error && <div className="sh-banner sh-error" data-testid="settings-error">{error}</div>}
      <p className="sh-muted sh-rules-note" data-testid="settings-note">
        {view.applies_to}. {view.note}.
      </p>
      <div className="sh-composer-bar sh-rule-actions">
        <input
          className="sh-rule-input"
          placeholder="변경 사유(선택 — 이력에 남는다)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          data-testid="settings-reason"
        />
      </div>

      <SettingRow
        keyName="default_tool_id"
        view={view}
        extra={
          <span className="sh-muted" data-testid="settings-tool-verified">
            {' '}· 확인한 PC:{' '}
            {view.tool_verified_on.length === 0
              ? '등록된 PC 없음'
              : view.tool_verified_on.map((r) => `${r.host}(${r.state})`).join(', ')}
          </span>
        }
        form={
          <ToolForm current={view.default_tool_id} runners={props.runners} onSet={(tool) => change({ default_tool_id: tool })} />
        }
        onReset={null}
      />
      <section data-testid="setting-model">
        <h3 className="sh-section-title">모델</h3>
        <p className="sh-muted sh-rule-line">{view.model.note}</p>
      </section>
      <section data-testid="setting-depth">
        <h3 className="sh-section-title">깊이(WorkDepth)</h3>
        <p className="sh-muted sh-rule-line">{view.depth.note}</p>
      </section>
      <SettingRow
        keyName="default_autonomy"
        view={view}
        display={(v) => AUTONOMY_LABEL[v as 'ask_on_decision' | 'controlled'] ?? String(v)}
        form={
          <>
            <button type="button" onClick={() => void change({ default_autonomy: 'ask_on_decision' })} data-testid="setting-autonomy-ask">
              기본 자율 진행
            </button>
            <button type="button" onClick={() => void change({ default_autonomy: 'controlled' })} data-testid="setting-autonomy-controlled">
              확인 경계(controlled)
            </button>
          </>
        }
        onReset={settings.default_autonomy.setting ? () => void change({ default_autonomy: null }) : null}
      />
      {(['repair_limit', 'task_retry_limit'] as const).map((key) => (
        <SettingRow
          key={key}
          keyName={key}
          view={view}
          form={
            <NumberForm
              initial={String(settings[key].value ?? '')}
              min={view.ranges.progress_limit.min}
              max={view.ranges.progress_limit.max}
              testId={`setting-input-${key}`}
              onSet={(n) => change({ [key]: n })}
            />
          }
          onReset={settings[key].setting ? () => void change({ [key]: null }) : null}
        />
      ))}
      <SettingRow
        keyName="context_inline_limit_bytes"
        view={view}
        form={
          <NumberForm
            initial={String(settings.context_inline_limit_bytes.value ?? '')}
            min={1}
            testId="setting-input-context_inline_limit_bytes"
            onSet={(n) => change({ context_inline_limit_bytes: n })}
          />
        }
        onReset={settings.context_inline_limit_bytes.setting ? () => void change({ context_inline_limit_bytes: null }) : null}
      />
      <BudgetDefaults view={view} onChange={change} />

      <section data-testid="settings-history">
        <button type="button" className="sh-list-toggle" onClick={() => setShowHistory((v) => !v)} data-testid="settings-history-toggle">
          {showHistory ? '▾' : '▸'} 변경 이력 {view.history.length}
        </button>
        {showHistory && (
          <ul className="sh-result-list">
            {view.history.map((row) => (
              <li key={row.id} className="sh-rule-line sh-muted" data-testid={`settings-history-${row.revision}`}>
                r{row.revision} · {PROJECT_SETTING_LABEL[row.setting_key] ?? row.setting_key} = {String(row.value)} · {row.set_by} ·{' '}
                {when(row.created_at)} · {row.state === 'current' ? '현재' : `대체됨 ${when(row.superseded_at)}`}
                {row.reason_summary ? ` · ${row.reason_summary}` : ''}
              </li>
            ))}
            {view.history.length === 0 && <li className="sh-muted sh-rule-line">없다</li>}
          </ul>
        )}
      </section>
    </div>
  )
}

function SettingRow(props: {
  keyName: string
  view: ProjectSettingsView
  display?: (value: string | number) => string
  extra?: ReactNode
  form: ReactNode
  onReset: (() => void) | null
}) {
  const item = props.view.settings[props.keyName]
  const value = item.value === null ? '없음' : props.display ? props.display(item.value) : String(item.value)
  return (
    <section data-testid={`setting-${props.keyName}`} data-source={item.source} data-value={item.value === null ? '' : String(item.value)}>
      <h3 className="sh-section-title">{PROJECT_SETTING_LABEL[props.keyName] ?? props.keyName}</h3>
      <div className="sh-rule-line">
        <strong data-testid={`setting-value-${props.keyName}`}>{value}</strong> ·{' '}
        <span data-testid={`setting-source-${props.keyName}`}>{PROJECT_SETTING_SOURCE_LABEL[item.source]}</span>
        {item.setting ? ` · 적용 시점 ${when(item.setting.created_at)} · ${item.setting.set_by}` : ''}
        {item.system_default !== null ? ` · 시스템 기본값 ${String(item.system_default)}` : ''}
        {props.extra}
      </div>
      <div className="sh-composer-bar sh-rule-actions">
        {props.form}
        {props.onReset && (
          <button type="button" className="sh-link" onClick={props.onReset} data-testid={`setting-reset-${props.keyName}`}>
            기본값으로 복귀
          </button>
        )}
      </div>
    </section>
  )
}

function ToolForm(props: { current: string; runners: RunnerWithConnection[]; onSet: (tool: string) => void }) {
  const known = new Set<string>([props.current])
  for (const runner of props.runners) {
    for (const cap of runner.capabilities) if (cap.capability === 'coding_cli') known.add(cap.tool_id)
  }
  const [tool, setTool] = useState(props.current)
  return (
    <>
      <select value={tool} onChange={(e) => setTool(e.target.value)} data-testid="setting-tool-select">
        {[...known].map((id) => (
          <option key={id} value={id}>
            {id}
          </option>
        ))}
      </select>
      <button type="button" disabled={tool === props.current} onClick={() => props.onSet(tool)} data-testid="setting-tool-set">
        기본 도구로
      </button>
    </>
  )
}

function NumberForm(props: { initial: string; min: number; max?: number; testId: string; onSet: (n: number) => void }) {
  const [value, setValue] = useState(props.initial)
  return (
    <>
      <input size={8} value={value} onChange={(e) => setValue(e.target.value)} data-testid={props.testId} />
      <span className="sh-muted">
        {props.min}~{props.max ?? ''}
      </span>
      <button type="button" onClick={() => props.onSet(Number(value))} data-testid={`${props.testId}-set`}>
        변경
      </button>
    </>
  )
}

function BudgetDefaults(props: { view: ProjectSettingsView; onChange: (values: Record<string, string | number | null>) => Promise<void> }) {
  const [metric, setMetric] = useState('run_count')
  const [threshold, setThreshold] = useState('hard')
  const [value, setValue] = useState('5')
  return (
    <section data-testid="setting-budget">
      <h3 className="sh-section-title">기본 예산(새 대화의 한도)</h3>
      {props.view.budget_defaults.length === 0 && <p className="sh-muted sh-rule-line">없음 — 새 대화는 무제한으로 시작한다(D-56)</p>}
      <ul className="sh-result-list">
        {props.view.budget_defaults.map((row) => (
          <li key={row.key} className="sh-rule-line" data-testid={`setting-budget-${row.metric}-${row.threshold_kind}`}>
            {row.metric} {row.threshold_kind} <strong>{row.limit_value}</strong> {row.unit} · {GUARANTEE_LABEL[row.guarantee] ?? row.guarantee} · 적용
            시점 {when(row.setting.created_at)}
            <button type="button" className="sh-link" onClick={() => void props.onChange({ [row.key]: null })} data-testid={`setting-budget-clear-${row.metric}-${row.threshold_kind}`}>
              해제
            </button>
          </li>
        ))}
      </ul>
      <div className="sh-composer-bar sh-rule-actions">
        <select value={metric} onChange={(e) => setMetric(e.target.value)} data-testid="setting-budget-metric">
          {Object.entries(props.view.budget_metrics).map(([name, info]) => (
            <option key={name} value={name}>
              {name} (hard {GUARANTEE_LABEL[info.hard_guarantee] ?? info.hard_guarantee})
            </option>
          ))}
        </select>
        <select value={threshold} onChange={(e) => setThreshold(e.target.value)} data-testid="setting-budget-threshold">
          <option value="warn">경고선</option>
          <option value="hard">hard 한도</option>
        </select>
        <input size={6} value={value} onChange={(e) => setValue(e.target.value)} data-testid="setting-budget-value" />
        <button type="button" onClick={() => void props.onChange({ [`budget:${metric}:${threshold}`]: Number(value) })} data-testid="setting-budget-set">
          기본 한도 추가
        </button>
      </div>
      <p className="sh-muted sh-rule-line">강제할 수 없는 지표의 hard 한도는 거부된다(D-61). 기존 대화의 예산은 그 대화의 상세 설정에서.</p>
    </section>
  )
}

// ------------------------------------------------------------------ 저장소

function RepositoriesTab(props: { project: ProjectWithAttention }) {
  const projectId = props.project.id
  const [view, setView] = useState<ProjectRepositoryView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [path, setPath] = useState('')
  const load = useCallback(async () => {
    try {
      setView(await repositoryApi.project(projectId))
    } catch (err) {
      setError(describe(err))
    }
  }, [projectId])
  useEffect(() => {
    void load()
  }, [load])
  const guard = async (fn: () => Promise<unknown>) => {
    try {
      setError(null)
      await fn()
    } catch (err) {
      setError(describe(err))
    }
    await load()
  }
  return (
    <div className="sh-rules-body" data-testid="settings-repositories">
      {error && <div className="sh-banner sh-error">{error}</div>}
      <p className="sh-muted sh-rules-note">
        등록은 선택도 허용도 아니다(D-38) — 어느 대화도 등록만으로 그 저장소를 쓰지 않는다. 대화의 선택·쓰기 허용은 그 대화의
        상세 설정에서 기록한다. 기록 저장소는 업무 이슈를 만들 위치이며 코드 대상이 아니다(D-17). 실제 GitHub 연결·게시는
        아직 없다(P5).
      </p>
      {!view && !error && <p className="sh-muted">불러오는 중</p>}
      {view && (
        <>
          <ul className="sh-result-list">
            {view.repositories.map((repo) => (
              <li key={repo.id} className="sh-rule-line" data-testid={`settings-repo-${repo.id}`}>
                <strong>{repo.name}</strong> <span className="sh-mono sh-muted">{repo.repo_path}</span>
                {view.journal_repository_id === repo.id ? ' · 기록 저장소' : ''}
                {view.journal_repository_id !== repo.id && (
                  <button
                    type="button"
                    className="sh-link"
                    onClick={() => void guard(() => repositoryApi.setJournal(projectId, repo.id))}
                    data-testid={`settings-repo-journal-${repo.id}`}
                  >
                    기록 저장소로
                  </button>
                )}
              </li>
            ))}
          </ul>
          {!view.legacy_repo_path_matches_registry && (
            <p className="sh-muted sh-rule-line">등록 시 경로 {view.legacy_repo_path} 가 등록 저장소 어느 것과도 맞지 않는다 — 어느 쪽이 맞는지는 사람이 안다.</p>
          )}
          <div className="sh-composer-bar sh-rule-actions">
            <input className="sh-rule-input" placeholder="이름" value={name} onChange={(e) => setName(e.target.value)} data-testid="settings-repo-name" />
            <input className="sh-rule-input" placeholder="경로(작업 PC 기준)" value={path} onChange={(e) => setPath(e.target.value)} data-testid="settings-repo-path" />
            <button
              type="button"
              disabled={!name.trim() || !path.trim()}
              onClick={() =>
                void guard(async () => {
                  await repositoryApi.register(projectId, name.trim(), path.trim())
                  setName('')
                  setPath('')
                })
              }
              data-testid="settings-repo-register"
            >
              저장소 등록
            </button>
          </div>
        </>
      )}
    </div>
  )
}
