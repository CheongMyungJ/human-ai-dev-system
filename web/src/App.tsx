// P2-01 최소 화면 + P2-02 의도 흐름 + P2-03 게이트·진입 제어.
//
// 제어부에서 오는 것은 상태 · 요약 · 원문 참조뿐이다. 원문 본문은 의도 화면의
// 열람 경로(일시중계)로만 나타나며 제어부에 보관되지 않는다.
//
// **이 화면은 조건을 판단하지 않는다.** 실행 버튼을 감추는 것은 조건이 아니므로
// 여기서는 서버가 돌려준 판정과 사유를 보여 주기만 한다. 같은 요청을 브라우저
// 밖에서 보내도 서버가 같은 답을 한다(FR-29).

import { useCallback, useEffect, useState } from 'react'
import {
  api,
  ApiError,
  codingCliTools,
  conversationApi,
  gateApi,
  GATE_VERDICT_LABEL,
  REFUSAL_LABEL,
  type AdmissionCheck,
  type AdmissionView,
  type ArtifactRef,
  type CaseDetail,
  type GateResult,
  type Project,
  type RunnerInfo,
  type RunPurpose,
} from './api'
import { ConversationPanel } from './ConversationPanel'
import { IntentPanel } from './IntentPanel'
import { PolicyPanel } from './PolicyPanel'
import { PreparationPanel } from './PreparationPanel'
import { ResultPanel } from './ResultPanel'
import { WorkGraphPanel } from './WorkGraphPanel'
import { WorkspacePanel } from './WorkspacePanel'

//: 화면에서 고를 수 있는 목적. `feature_implementation` 도 **일부러 남겨 둔다** —
//: 조건을 갖추지 못했으면 서버가 무엇이 빠졌는지 사유 코드로 거부하는 것을 볼 수
//: 있어야 한다. 목록에서 지우면 그 사실이 화면에서 사라진다.
//:
//: P3-01에서 설계·계획 작성이 더해졌다. 두 목적을 **따로** 둔다 — 하나로 합치면
//: 두 산출물의 검토가 한 실행에 묶여 "각각 독립된 검토 옵션"을 지킬 수 없다.
const PURPOSE_OPTIONS: { value: RunPurpose; label: string }[] = [
  { value: 'limited_analysis', label: '제한 작업 (읽기·결과 작성)' },
  { value: 'intent_gate_review', label: 'QG-01 의미 검토 (별도 세션)' },
  { value: 'quality_gate_review', label: 'QG-02~07 의미 검토 (별도 세션)' },
  { value: 'design_authoring', label: '설계안 작성 (동의된 의도 위에)' },
  { value: 'plan_authoring', label: '개발계획 작성 (검토된 설계 위에)' },
  { value: 'feature_implementation', label: '기능 구현 (작업공간이 준비되면 쓰기가 열린다)' },
  { value: 'verification_run', label: '검증 실행 (빌드·테스트와 명령 증거)' },
]

function describeAdmission(detail: unknown): AdmissionView | null {
  if (detail && typeof detail === 'object' && 'admission' in detail) {
    return (detail as { admission: AdmissionView }).admission
  }
  return null
}

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
          P2-03 진입 제어·제한 실행 · 제어부는 상태와 참조만 보관하고 원문은 Runner에 있다
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
            runners={runners}
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
                {/* UI-01. 준비 단계·보관·현재 요청은 종료 상태와 다른 축이다. */}
                {item.stage === 'discussion' && ' · 준비 단계'}
                {(item as { archived?: boolean }).archived && ' · 보관됨'}
                {(item as { current_request_state?: string | null }).current_request_state &&
                  ` · 요청 ${(item as { current_request_state?: string | null }).current_request_state}`}
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
      {/* UI-01. 목표·Profile 없이 시작하는 대화. 업무화는 대화 안에서 한다. */}
      <button
        type="button"
        onClick={async () => {
          await conversationApi.create(props.project.id, title.trim() || '새 대화')
          setTitle('')
          props.onCreated()
        }}
      >
        새 대화 (준비 단계)
      </button>
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
  const [purpose, setPurpose] = useState<RunPurpose>('limited_analysis')
  const [permission, setPermission] = useState<'read_only' | 'workspace_write'>('read_only')
  const [refusal, setRefusal] = useState<AdmissionView | null>(null)

  const runnerId = props.runners[0]?.id
  // 사용 가능하다고 **보고된** 도구만 고를 수 있다. 목록에 없는 도구를 골라도
  // 서버가 거부하지만, 없는 선택지를 보여 주지 않는 편이 정직하다.
  const installedTools = Array.from(
    new Set(
      props.runners
        .flatMap((runner) => runner.capabilities)
        .filter((cap) => cap.capability === 'installed' && cap.state === 'verified')
        .map((cap) => cap.tool_id),
    ),
  )
  // 의미 검토는 AI가 글을 써야 하므로 코딩 CLI만 고를 수 있다. 제한 작업은
  // 골격 실행기로도 할 수 있으므로 설치된 도구를 모두 보여 준다.
  const cliTools = codingCliTools(props.runners).map((t) => t.tool_id)
  const isReviewerPurpose =
    purpose === 'intent_gate_review' || purpose === 'quality_gate_review'
  const toolOptions = isReviewerPurpose ? cliTools : installedTools
  const [toolId, setToolId] = useState(toolOptions[0] ?? 'codex')
  useEffect(() => {
    if (toolOptions.length > 0 && !toolOptions.includes(toolId)) setToolId(toolOptions[0])
  }, [purpose, toolOptions, toolId])
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

      {/* UI-01. 대화와 현재 요청. 전송 가능 여부는 서버가 판정한다. */}
      <ConversationPanel detail={detail} runners={props.runners} onChanged={props.onChanged} />

      <h3>원문 참조</h3>
      <p className="muted small">
        제어부는 참조만 보관한다. 본문은 소유 Runner에 있고, 아래 의도 화면의
        원문 열람(일시중계)으로만 한 번씩 지나간다.
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

      {/* 어떤 목적·깊이·확인 경계·한도로 진행하는가. 게이트 판정과 **다른 기록**
          이므로 패널을 나눈다 — 정책은 "언제 사람을 부르는가"이고 게이트는
          "결과를 채택할 수 있는가"다(D-59). */}
      <PolicyPanel detail={detail} onChanged={props.onChanged} />

      <GatePanel detail={detail} onChanged={props.onChanged} />
      <QualityGatesPanel detail={detail} />

      {/* 수준·설계·계획과 단계별 검토. 게이트 판정과 **다른 기록**이므로 패널을
          나눈다 — 게이트 통과가 설계 검토가 아니고, 검토가 게이트를 통과시키지도
          않는다(FR-05 "산출물 존재, 품질 판정, 사람 검토는 구분한다"). */}
      <PreparationPanel detail={detail} onChanged={props.onChanged} />
      <WorkGraphPanel detail={detail} onChanged={props.onChanged} />

      {/* 어떤 코드 위에서 어디에 만드는가. 그래프(무엇을 어떤 순서로)와 **다른
          기록**이므로 패널을 나눈다 — 그래프를 갖췄다고 작업공간이 생기지 않고,
          작업공간이 있다고 계획이 선 것도 아니다(FR-08·FR-26). */}
      <WorkspacePanel detail={detail} onChanged={props.onChanged} />

      {/* 결과·근거와 최종 확인. 게이트 판정과 **다른 기록**이므로 패널을 나눈다 —
          게이트 통과가 결과 인수가 아니고, 인수가 게이트를 통과시키지도 않는다. */}
      <ResultPanel detail={detail} onChanged={props.onChanged} />

      <h3>실행</h3>
      <p className="muted small">
        실행 요청은 언제든 보낼 수 있다. <strong>조건은 서버가 검사한다</strong> —
        갖추지 못하면 아래에 사유가 나오고 Run은 만들어지지 않는다(FR-29).
      </p>
      <form
        onSubmit={async (event) => {
          event.preventDefault()
          // **최신 의도 버전의 원문**을 지정한다. 목록에서 첫 intent 원문을 집으면
          // 새 버전이 생긴 뒤에도 v1을 검토하게 된다 — 라이브에서 실제로 났던 일이다.
          // 검토가 끝나도 최신 버전의 게이트는 `not_run` 그대로라 아무 것도
          // 진척되지 않는다. 서버도 같은 조합을 거부한다(intent_version_not_latest).
          const latestIntent = detail.intent_versions[0]
          const artifact =
            purpose === 'intent_gate_review'
              ? detail.artifacts.find(
                  (a) =>
                    a.kind === 'intent' &&
                    a.availability === 'available' &&
                    a.artifact_id === latestIntent?.artifact_id,
                )
              : runnableArtifacts.find((a) => a.kind !== 'intent')
          if (!artifact) {
            setNotice('이 목적에 쓸 저장 완료된 원문이 없다.')
            return
          }
          const id = runId.trim() || `run-${Date.now()}`
          setRefusal(null)
          try {
            const created = await api.createRun(detail.id, artifact.artifact_id, id, {
              purpose,
              role: isReviewerPurpose ? 'reviewer' : 'author',
              tool_id: toolId,
              mode: toolId === 'claude' ? 'print' : 'exec',
              permission,
              instruction_artifact_rev: artifact.revision,
            })
            setRunId(id)
            setNotice(
              created.created
                ? `Run ${id} 를 만들었다. 진입 조건을 통과했다(${created.admission?.profile}).`
                : `Run ${id} 는 이미 있다. 같은 run_id 는 새 실행도 새 검사도 만들지 않는다.`,
            )
          } catch (err) {
            if (err instanceof ApiError && err.status === 409) {
              const admission = describeAdmission(err.detail)
              if (admission) {
                setRefusal(admission)
                setNotice(null)
              } else {
                setNotice(err.message)
              }
            } else {
              setNotice(err instanceof Error ? err.message : String(err))
            }
          }
          props.onChanged()
        }}
      >
        <select value={purpose} onChange={(e) => setPurpose(e.target.value as RunPurpose)}>
          {PURPOSE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <select value={toolId} onChange={(e) => setToolId(e.target.value)}>
          {toolOptions.map((tool) => (
            <option key={tool} value={tool}>
              {tool}
            </option>
          ))}
        </select>
        <select
          value={permission}
          onChange={(e) => setPermission(e.target.value as 'read_only' | 'workspace_write')}
        >
          <option value="read_only">read_only</option>
          {/* P3-03에서 열렸다 — **준비된 작업공간이 있는 구현·검증 실행에만**.
              목록에서 지우지 않는 이유는 P3-01과 같다: 조건을 갖추지 못했을 때
              서버가 무엇이 빠졌는지 사유 코드로 거부하는 것을 볼 수 있어야 한다. */}
          <option value="workspace_write">workspace_write (작업공간이 준비된 구현·검증만)</option>
        </select>
        <input
          value={runId}
          placeholder="run_id (비워 두면 자동 생성)"
          onChange={(e) => setRunId(e.target.value)}
        />
        <button type="submit">실행 요청</button>
      </form>

      {refusal && (
        <div className="notice refusal">
          <strong>진입 조건 미충족 — Run을 만들지 않았다.</strong>
          <p className="small">
            적용한 조건표: {refusal.profile} · 의도 동의:{' '}
            {refusal.intent_agreement_state ?? '—'} · QG-01: {refusal.gate_verdict ?? '—'}
          </p>
          <ul className="list">
            {refusal.refusals.map((code) => (
              <li key={code} className="small">
                <strong>{REFUSAL_LABEL[code] ?? code}</strong>
                <br />
                <span className="muted">{refusal.reasons[code]}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <AdmissionLog checks={detail.admission_checks} />

      <table>
        <thead>
          <tr>
            <th>run_id</th>
            <th>목적</th>
            <th>도구</th>
            <th>상태</th>
            <th>결과</th>
            <th>세션</th>
            <th>사용량</th>
            <th>잔여 활동</th>
          </tr>
        </thead>
        <tbody>
          {detail.runs.map((run) => (
            <tr key={run.run_id}>
              <td className="mono small">{run.run_id}</td>
              {/* 목적이 없는 행은 P2-03 이전에 만들어진 것이다. 지금 값을 지어내지 않는다. */}
              <td className="small">{run.purpose ?? '기록 없음'}</td>
              <td className="small">
                {run.tool_id}
                {run.observed_tool_version ? ` (${run.observed_tool_version})` : ''}
              </td>
              <td>{run.status}</td>
              <td>{run.outcome ?? '—'}</td>
              <td className="mono small">{run.session_ref ?? 'not_reported'}</td>
              <td className="small">
                {typeof run.usage === 'string' ? run.usage : JSON.stringify(run.usage)}
              </td>
              <td className="small">{run.residual_activity}</td>
            </tr>
          ))}
          {detail.runs.length === 0 && (
            <tr>
              <td colSpan={8} className="muted">
                아직 없음
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  )
}

function QualityGatesPanel(props: { detail: CaseDetail }) {
  return (
    <section className="subpanel">
      <h3>품질 게이트 적용안 · repair</h3>
      <p className="muted small">
        적용 설정, 실제 검사, 품질 판정과 repair 누적은 서로 다른 상태다. OFF나 업무상
        미적용을 통과로 표시하지 않으며 최초 실패는 repair 1회로 세지 않는다.
        <br />
        P4-02: <strong>요청한 설정과 실제 적용된 설정</strong>은 다를 수 있다. 진행 중
        검증이 있으면 변경은 예약되고 그 검증 1회가 끝난 뒤 반영된다. 예약은 취소
        명령이 아니며, 예약만으로 진행 중 검사가 멈추거나 그 결과가 무효화되지 않는다.
      </p>
      <table>
        <thead>
          <tr>
            <th>게이트</th>
            <th>적용</th>
            <th>요구 검사</th>
            <th>현재 판정</th>
            <th>repair</th>
            <th>근거 · 변경</th>
          </tr>
        </thead>
        <tbody>
          {props.detail.quality_gates.gates.map((gate) => (
            <tr key={gate.gate}>
              <td>
                <span className="mono">{gate.gate}</span> · {gate.label}
              </td>
              <td>
                {gate.setting}
                {gate.applied_at && (
                  <>
                    <br />
                    <span className="muted small">적용 {gate.applied_at}</span>
                  </>
                )}
                {gate.requested_at && gate.requested_at !== gate.applied_at && (
                  <>
                    <br />
                    <span className="muted small">요청 {gate.requested_at}</span>
                  </>
                )}
              </td>
              <td>{gate.inspection_required}</td>
              <td>
                {gate.latest_run ? (
                  <>
                    {GATE_VERDICT_LABEL[gate.latest_run.verdict]}
                    {gate.latest_run.validity && ` · ${gate.latest_run.validity}`}
                    {gate.latest_run.status === 'running' && (
                      <>
                        <br />
                        <span className="muted small">검사 중</span>
                      </>
                    )}
                    {gate.latest_run.late_result && (
                      <>
                        <br />
                        <span className="muted small">
                          늦게 도착한 결과 · 현재 정책의 통과가 아니다
                        </span>
                      </>
                    )}
                  </>
                ) : (
                  <span className="muted">검사 안 함</span>
                )}
              </td>
              <td>
                {gate.remediation
                  ? `${gate.remediation.used_attempts} 사용 + ${gate.remediation.reserved_attempts} 예약 / ${gate.remediation.repair_limit}`
                  : `0 / ${gate.repair_limit}`}
              </td>
              <td className="small">
                <span className="mono">{gate.source}</span>
                <br />
                <span className="muted">{gate.reason}</span>
                {gate.reserved.map((reservation) => (
                  <div key={reservation.policy_id} className="muted">
                    예약 · {reservation.setting}
                    {reservation.inspection && ` · ${reservation.inspection}`}
                    {reservation.repair_limit !== null &&
                      ` · 한도 ${reservation.repair_limit}`}
                    <br />
                    검증 1회 종료 뒤 반영 (요청 {reservation.requested_at} ·{' '}
                    {reservation.requested_by})
                  </div>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

function GatePanel(props: { detail: CaseDetail; onChanged: () => void }) {
  const gate: GateResult = props.detail.gate
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  const ruleFindings = gate.findings.filter((f) => f.source === 'rule')
  const aiFindings = gate.findings.filter((f) => f.source === 'ai')

  return (
    <section className="subpanel">
      <h3>QG-01 의도 초안 품질 게이트</h3>
      <p className="muted small">
        기능 개발의 <strong>필수 게이트</strong>이며 끌 수 없다. 이 게이트가 보는 것은
        “사람에게 검토를 요청할 준비가 됐는가”이고, 의도에 부합한다는 판정은 사람의
        명시적 동의로 <strong>따로</strong> 충족한다.
      </p>

      <table>
        <tbody>
          <tr>
            <th>종합 판정</th>
            <td>
              <strong className={`verdict verdict-${gate.verdict}`}>
                {GATE_VERDICT_LABEL[gate.verdict]}
              </strong>
            </td>
          </tr>
          <tr>
            <th>규칙 검사</th>
            <td>{GATE_VERDICT_LABEL[gate.rule_verdict]}</td>
          </tr>
          <tr>
            <th>AI 의미 검토</th>
            <td>
              {GATE_VERDICT_LABEL[gate.ai_verdict]}
              {gate.ai_verdict === 'not_run' && (
                <span className="muted small">
                  {' '}
                  — 규칙만 통과한 것은 통과가 아니다. 별도 세션 검토가 필요하다
                </span>
              )}
            </td>
          </tr>
          {gate.ai_session_ref && (
            <tr>
              <th>세션 분리</th>
              <td className="mono small">
                작성 {gate.author_session_ref ?? '사람이 작성(실행 없음)'} · 검토{' '}
                {gate.ai_session_ref}
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {note && <div className="notice">{note}</div>}

      <button
        type="button"
        disabled={busy || !gate.intent_version_id}
        onClick={async () => {
          if (!gate.intent_version_id) return
          setBusy(true)
          try {
            const result = await gateApi.runRules(props.detail.id, gate.intent_version_id)
            setNote(
              `규칙 검사를 다시 돌렸다: ${GATE_VERDICT_LABEL[result.rule_verdict]}.` +
                ' AI 검토 결과는 그대로 둔다.',
            )
          } catch (err) {
            setNote(err instanceof Error ? err.message : String(err))
          } finally {
            setBusy(false)
            props.onChanged()
          }
        }}
      >
        규칙 검사 다시 실행
      </button>
      <p className="muted small">
        AI 의미 검토는 아래 실행에서 목적을 “QG-01 의미 검토”로 골라 시작한다.
        작성과 다른 세션에서 수행되며, 그 사실이 위 표에 기록된다.
      </p>

      <h4>발견 사항</h4>
      {gate.findings.length === 0 && <p className="muted small">아직 없음</p>}
      {[
        { label: '규칙', items: ruleFindings },
        { label: 'AI 의미 검토', items: aiFindings },
      ].map((group) =>
        group.items.length === 0 ? null : (
          <div key={group.label}>
            <p className="small">
              <strong>{group.label}</strong>
            </p>
            <ul className="list">
              {group.items.map((finding) => (
                <li key={finding.id} className="small">
                  <span className={finding.severity === 'required' ? 'required' : 'muted'}>
                    [{finding.severity === 'required' ? '필수' : '권고'}
                    {finding.blocking ? ' · 차단' : ''} · {finding.certainty === 'confirmed' ? '확정' : '의심'}]
                  </span>{' '}
                  <span className="mono">{finding.criterion}</span> · {finding.target}
                  <br />
                  <span className="muted">{finding.summary}</span>
                </li>
              ))}
            </ul>
          </div>
        ),
      )}
    </section>
  )
}

function AdmissionLog(props: { checks: AdmissionCheck[] }) {
  if (props.checks.length === 0) return null
  return (
    <>
      <h4>진입 검사 기록</h4>
      <p className="muted small">
        통과도 거부도 남는다. 왜 실행이 시작되지 않았는지 다른 화면을 찾아다니지 않고
        알 수 있어야 한다.
      </p>
      <table>
        <thead>
          <tr>
            <th>요청 run_id</th>
            <th>목적</th>
            <th>권한</th>
            <th>결과</th>
            <th>사유</th>
            <th>시각</th>
          </tr>
        </thead>
        <tbody>
          {props.checks.map((check) => (
            <tr key={check.id}>
              <td className="mono small">{check.requested_run_id}</td>
              <td className="small">{check.requested_purpose}</td>
              <td className="small">{check.requested_permission}</td>
              <td className="small">
                {check.outcome === 'admitted' ? '허용' : '거부'}
              </td>
              <td className="small">
                {check.refusals.map((code) => REFUSAL_LABEL[code] ?? code).join(' / ') || '—'}
              </td>
              <td className="muted small">{check.checked_at}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

export type { ArtifactRef }
