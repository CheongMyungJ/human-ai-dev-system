// P2-01 최소 화면 + P2-02 의도 흐름.
//
// 제어부에서 오는 것은 상태 · 요약 · 원문 참조뿐이다. 원문 본문은 의도 화면의
// 열람 경로(일시중계)로만 나타나며 제어부에 보관되지 않는다.

import { useCallback, useEffect, useState } from 'react'
import {
  api,
  type ArtifactRef,
  type CaseDetail,
  type Project,
  type RunnerInfo,
} from './api'
import { IntentPanel } from './IntentPanel'

const AVAILABILITY_LABEL: Record<string, string> = {
  pending: '저장 대기 (아직 저장 완료 아님)',
  available: 'Runner에 저장됨',
  runner_offline: 'Runner 연결 필요',
  lost_before_persist: '영속 저장 전 유실',
}

function useAsyncError() {
  const [error, setError] = useState<string | null>(null)
  const guard = useCallback(async (fn: () => Promise<void>) => {
    try {
      setError(null)
      await fn()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [])
  return { error, guard }
}

export function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [runners, setRunners] = useState<RunnerInfo[]>([])
  const [selectedProject, setSelectedProject] = useState<Project | null>(null)
  const [cases, setCases] = useState<CaseDetail[] | null>(null)
  const [selectedCase, setSelectedCase] = useState<CaseDetail | null>(null)
  const { error, guard } = useAsyncError()

  const refreshTop = useCallback(async () => {
    setProjects(await api.listProjects())
    setRunners(await api.listRunners())
  }, [])

  // 현재 보고 있는 대상을 주소에 남긴다. 새로 고침과 링크 공유가 같은 화면을 연다.
  const remember = (projectId?: string, caseId?: string) => {
    const params = new URLSearchParams()
    if (projectId) params.set('project', projectId)
    if (caseId) params.set('case', caseId)
    const query = params.toString()
    window.history.replaceState(null, '', query ? `?${query}` : window.location.pathname)
  }

  const openProject = useCallback(
    (project: Project, caseId?: string) =>
      guard(async () => {
        setSelectedProject(project)
        setSelectedCase(null)
        const list = await api.listCases(project.id)
        setCases(list as CaseDetail[])
        remember(project.id, caseId)
      }),
    [guard],
  )

  const openCase = useCallback(
    (caseId: string) =>
      guard(async () => {
        const detail = await api.getCase(caseId)
        setSelectedCase(detail)
        remember(detail.project_id, detail.id)
      }),
    [guard],
  )

  useEffect(() => {
    void guard(async () => {
      await refreshTop()
      const params = new URLSearchParams(window.location.search)
      const projectId = params.get('project')
      const caseId = params.get('case')
      if (projectId) {
        const project = (await api.listProjects()).find((p) => p.id === projectId)
        if (project) await openProject(project, caseId ?? undefined)
      }
      if (caseId) await openCase(caseId)
    })
  }, [guard, refreshTop, openProject, openCase])

  return (
    <div className="app">
      <header>
        <h1>사람–AI 개발 협업 시스템</h1>
        <p className="sub">
          P2-02 의도·피드백 · 제어부는 상태와 참조만 보관하고 원문은 Runner에 있다
        </p>
      </header>

      {error && <div className="error">오류: {error}</div>}

      <div className="columns">
        <ProjectPanel
          projects={projects}
          runners={runners}
          selected={selectedProject}
          onOpen={openProject}
          onCreated={() => guard(refreshTop)}
        />

        {selectedProject && (
          <CasePanel
            project={selectedProject}
            cases={cases ?? []}
            onOpen={openCase}
            onCreated={() => openProject(selectedProject)}
          />
        )}

        {selectedCase && (
          <CaseDetailPanel
            detail={selectedCase}
            runners={runners}
            onChanged={() => openCase(selectedCase.id)}
          />
        )}

        {selectedCase && selectedCase.kind === 'feature' && (
          <IntentPanel
            key={selectedCase.id}
            caseId={selectedCase.id}
            runnerId={runners[0]?.id}
            onChanged={() => openCase(selectedCase.id)}
          />
        )}
      </div>
    </div>
  )
}

function ProjectPanel(props: {
  projects: Project[]
  runners: RunnerInfo[]
  selected: Project | null
  onOpen: (project: Project) => void
  onCreated: () => void
}) {
  const [name, setName] = useState('')
  const [repoPath, setRepoPath] = useState('')

  return (
    <section className="panel">
      <h2>프로젝트</h2>
      <ul className="list">
        {props.projects.map((project) => (
          <li key={project.id}>
            <button
              className={props.selected?.id === project.id ? 'row active' : 'row'}
              onClick={() => props.onOpen(project)}
            >
              <strong>{project.name}</strong>
              <span className="muted">{project.repo_path}</span>
            </button>
          </li>
        ))}
        {props.projects.length === 0 && <li className="muted">아직 없음</li>}
      </ul>

      <form
        onSubmit={async (event) => {
          event.preventDefault()
          if (!name.trim() || !repoPath.trim()) return
          await api.createProject(name.trim(), repoPath.trim())
          setName('')
          setRepoPath('')
          props.onCreated()
        }}
      >
        <input value={name} placeholder="프로젝트 이름" onChange={(e) => setName(e.target.value)} />
        <input
          value={repoPath}
          placeholder="저장소 경로 (Runner 호스트 기준)"
          onChange={(e) => setRepoPath(e.target.value)}
        />
        <button type="submit">프로젝트 추가</button>
      </form>

      <h3>연결된 Runner</h3>
      <ul className="list">
        {props.runners.map((runner) => (
          <li key={runner.id} className="muted">
            {runner.id} · {runner.host} · 마지막 생존 보고 {runner.last_heartbeat_at ?? '없음'}
          </li>
        ))}
        {props.runners.length === 0 && (
          <li className="muted">등록된 Runner 없음 — scripts/run-runner.ps1 을 실행한다</li>
        )}
      </ul>
    </section>
  )
}

function CasePanel(props: {
  project: Project
  cases: CaseDetail[]
  onOpen: (caseId: string) => void
  onCreated: () => void
}) {
  const [title, setTitle] = useState('')
  const [kind, setKind] = useState('feature')

  return (
    <section className="panel">
      <h2>Case — {props.project.name}</h2>
      <ul className="list">
        {props.cases.map((item) => (
          <li key={item.id}>
            <button className="row" onClick={() => props.onOpen(item.id)}>
              <strong>{item.title}</strong>
              <span className="muted">
                {item.kind} · {item.status}
              </span>
            </button>
          </li>
        ))}
        {props.cases.length === 0 && <li className="muted">아직 없음</li>}
      </ul>

      <form
        onSubmit={async (event) => {
          event.preventDefault()
          if (!title.trim()) return
          await api.createCase(props.project.id, title.trim(), kind)
          setTitle('')
          props.onCreated()
        }}
      >
        <input value={title} placeholder="문제 제기 한 줄" onChange={(e) => setTitle(e.target.value)} />
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="feature">기능 개발</option>
          <option value="bug">버그</option>
          <option value="analysis">원인 분석</option>
          <option value="research">연구</option>
        </select>
        <button type="submit">Case 추가</button>
      </form>
    </section>
  )
}

function CaseDetailPanel(props: {
  detail: CaseDetail
  runners: RunnerInfo[]
  onChanged: () => void
}) {
  const { detail } = props
  const [content, setContent] = useState('')
  const [summary, setSummary] = useState('')
  const [runId, setRunId] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const runnerId = props.runners[0]?.id
  const runnableArtifacts = detail.artifacts.filter(
    (artifact) => artifact.availability === 'available' && artifact.kind !== 'run_output',
  )

  return (
    <section className="panel wide">
      <h2>{detail.title}</h2>
      <p className="muted">
        {detail.id} · {detail.kind} · {detail.status}
      </p>
      {notice && <div className="notice">{notice}</div>}

      <h3>원문 참조</h3>
      <p className="muted small">
        제어부는 참조만 보관한다. 본문은 소유 Runner에 있다. 본문 열람(일시중계)은 P2-04 범위다.
      </p>
      <table>
        <thead>
          <tr>
            <th>종류</th>
            <th>요약</th>
            <th>상태</th>
            <th>해시</th>
            <th>소유 Runner</th>
          </tr>
        </thead>
        <tbody>
          {detail.artifacts.map((artifact) => (
            <tr key={`${artifact.artifact_id}-${artifact.revision}`}>
              <td>{artifact.kind}</td>
              <td>{artifact.summary}</td>
              <td>{AVAILABILITY_LABEL[artifact.availability] ?? artifact.availability}</td>
              <td className="mono small">{artifact.content_hash.slice(0, 19)}…</td>
              <td className="mono small">{artifact.owner_runner_id}</td>
            </tr>
          ))}
          {detail.artifacts.length === 0 && (
            <tr>
              <td colSpan={5} className="muted">
                아직 없음
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <h3>원문 제출</h3>
      <form
        onSubmit={async (event) => {
          event.preventDefault()
          if (!runnerId) {
            setNotice('등록된 Runner가 없어 원문을 영속 저장할 수 없다.')
            return
          }
          if (!content.trim() || !summary.trim()) return
          const accepted = await api.submitArtifact(
            detail.id,
            'instruction',
            content,
            summary.trim(),
            runnerId,
          )
          setContent('')
          setSummary('')
          setNotice(
            `접수함(${accepted.artifact_id}). 아직 저장 완료가 아니다 —` +
              ' Runner가 저장을 보고하면 상태가 바뀐다. 목록을 새로 고쳐 확인한다.',
          )
          props.onChanged()
        }}
      >
        <input
          value={summary}
          placeholder="짧은 요약 (목록 표시용)"
          onChange={(e) => setSummary(e.target.value)}
        />
        <textarea
          value={content}
          rows={4}
          placeholder="원문 본문 — 제어부에 저장되지 않는다"
          onChange={(e) => setContent(e.target.value)}
        />
        <button type="submit">원문 제출</button>
        <button type="button" onClick={props.onChanged}>
          새로 고침
        </button>
      </form>

      <h3>의도 버전과 결정</h3>
      {/* 여기에는 동의 버튼을 두지 않는다. 의도 동의는 원문 열람·미해결 질문 검사를
          거치는 아래 의도 화면에서만 할 수 있다(FR-03). 목록에서 바로 누르는 버튼은
          그 검사를 건너뛰게 만든다. */}
      <ul className="list">
        {detail.intent_versions.map((intent) => (
          <li key={intent.id} className="small">
            v{intent.revision} · {intent.status}
          </li>
        ))}
        {detail.intent_versions.length === 0 && <li className="muted">아직 없음</li>}
      </ul>
      <ul className="list">
        {detail.decisions.map((decision) => (
          <li key={decision.id} className="muted small">
            {decision.kind} · 대상 {decision.subject_id} v{decision.subject_revision} ·{' '}
            {decision.actor} · {decision.decided_at}
          </li>
        ))}
      </ul>

      <h3>실행</h3>
      <form
        onSubmit={async (event) => {
          event.preventDefault()
          const artifact = runnableArtifacts[0]
          if (!artifact) {
            setNotice('저장 완료된 지시 원문이 없다.')
            return
          }
          const id = runId.trim() || `run-${Date.now()}`
          const created = await api.createRun(detail.id, artifact.artifact_id, id)
          setRunId(id)
          setNotice(
            created.created
              ? `Run ${id} 를 새로 만들었다.`
              : `Run ${id} 는 이미 있다. 같은 run_id 는 새 실행을 만들지 않는다.`,
          )
          props.onChanged()
        }}
      >
        <input
          value={runId}
          placeholder="run_id (비워 두면 자동 생성)"
          onChange={(e) => setRunId(e.target.value)}
        />
        <button type="submit" disabled={runnableArtifacts.length === 0}>
          실행 요청
        </button>
      </form>

      <table>
        <thead>
          <tr>
            <th>run_id</th>
            <th>상태</th>
            <th>결과</th>
            <th>세대</th>
            <th>사용량</th>
            <th>잔여 활동</th>
          </tr>
        </thead>
        <tbody>
          {detail.runs.map((run) => (
            <tr key={run.run_id}>
              <td className="mono small">{run.run_id}</td>
              <td>{run.status}</td>
              <td>{run.outcome ?? '—'}</td>
              <td>{run.assignment_generation}</td>
              <td className="small">
                {typeof run.usage === 'string' ? run.usage : JSON.stringify(run.usage)}
              </td>
              <td className="small">{run.residual_activity}</td>
            </tr>
          ))}
          {detail.runs.length === 0 && (
            <tr>
              <td colSpan={6} className="muted">
                아직 없음
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  )
}

export type { ArtifactRef }
