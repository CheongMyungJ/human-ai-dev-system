// UI-05a(이슈 #7). 오른쪽 패널의 `작업` 탭 — 작업 그래프(무엇을 어떤 순서로, 그중 무엇이 **왜** 멈췄나)와 실행 상세(그
// 실행이 무엇을 받고 무엇을 했나). 관리 화면(`WorkGraphPanel`·실행 표)에만 있던 것을 새 화면으로 옮겼다.
//
//   **서버 값을 그대로 보인다.** 배정 가능·막힌 이유·기준 대응은 진입 검사와 같은 서버 계산이다 — 화면이 계산하지 않는다.
//   **그래프가 없는 것을 "준비됨"으로 보이지 않는다.** 없으면 없다고, 그 결과(구현 배정이 막힘)와 함께 적는다.
//   **재계획은 이유가 필수다.** 추가·취소·질문 연결은 새 리비전을 만들고 이전 리비전·실행 이력은 남는다(FR-07).
//   **질문 연결은 답이 아니다.** 누가 기다리는지를 고칠 뿐 질문은 열린 채이고 연결된 작업은 계속 막힌다.
//   **완료는 실행 결과다.** 사람이 누르는 완료 버튼이 없다 — 실행 증거 없이 의존을 푸는 문이 되기 때문이다.
//   **실행 상세는 읽기다.** 요약·수·식별자만 서버에서 오고 출력 본문은 결과물 뷰어가 PC 에서 불러온다.

import { useEffect, useState } from 'react'

import {
  api,
  ApiError,
  CONTEXT_ROLE_LABEL,
  preparationApi,
  REFUSAL_LABEL,
  RUN_CONTEXT_STATE_LABEL,
  TASK_BLOCK_LABEL,
  TASK_KIND_LABEL,
  TASK_RELATION_LABEL,
  TASK_STATE_LABEL,
  WORK_GRAPH_SOURCE_LABEL,
  workGraphApi,
  type AdmissionCheck,
  type ProjectRepository,
  type Run,
  type RunContextRef,
  type TaskKind,
  type TaskRow,
  type WorkGraphState,
} from '../api'
import { emit } from './events'
import type { ShellCaseDetail } from './useCaseData'
import { formatTimeout, stopReasonText } from '../lib/timeout'

const KINDS: TaskKind[] = ['implementation', 'verification', 'investigation', 'experiment', 'integration']

export const RUN_PURPOSE_LABEL: Record<string, string> = {
  discussion_reply: '논의 응답',
  intent_authoring: '의도 초안 작성',
  intent_gate_review: 'QG-01 의미 검토',
  quality_gate_review: '품질 게이트 검토',
  limited_analysis: '분석',
  design_authoring: '설계 작성',
  plan_authoring: '계획 작성',
  feature_implementation: '구현',
  verification_run: '검증',
  local_experiment: '로컬 실험',
}

const RUN_STATUS_LABEL: Record<string, string> = {
  created: '만듦(배정 전)',
  assigned: '배정됨',
  running: '실행 중',
  finished: '끝남',
}

const RECEIPT_LABEL: Record<string, string> = {
  read: '읽음',
  missing: '못 읽음(없음)',
  hash_mismatch: '못 읽음(해시 다름)',
  omitted: '생략(크기 한도)',
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (typeof err.detail === 'string') return err.detail
    if (Array.isArray(err.detail)) return '입력을 확인한다 — 필수 값이 비었거나 너무 길다'
    if (err.detail && typeof err.detail === 'object') {
      const detail = err.detail as { message?: unknown }
      if (detail.message) return String(detail.message)
    }
  }
  return err instanceof Error ? err.message : String(err)
}

function when(value: string | null | undefined): string {
  return value ? value.replace('T', ' ').slice(0, 19) : '—'
}

function short(value: string | null | undefined, n = 12): string {
  return value ? value.slice(0, n) : '—'
}

type Guard = (fn: () => Promise<unknown>) => Promise<boolean>

// ------------------------------------------------------------------ 탭

export function WorkPanel(props: {
  caseId: string
  detail: ShellCaseDetail
  repositories: ProjectRepository[]
  openRun: { runId: string; nonce: number } | null
  onChanged: () => void
}) {
  const { detail } = props
  const graph = detail.preparation?.work_graph ?? null
  const closed = ['closed', 'cancelled'].includes(detail.status)
  const [runId, setRunId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // 대화의 실행 id·대기 카드에서 오면 **그 실행**을 연다.
  useEffect(() => {
    if (props.openRun) setRunId(props.openRun.runId)
  }, [props.openRun])

  const guard: Guard = async (fn) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
      return true
    } catch (err) {
      setError(describeError(err))
      return false
    } finally {
      setBusy(false)
      props.onChanged()
    }
  }

  if (runId) {
    const summary = detail.runs.find((r) => r.run_id === runId) ?? null
    return (
      <RunDetail
        caseId={props.caseId}
        runId={runId}
        summary={summary}
        checks={detail.admission_checks.filter((c) => c.requested_run_id === runId)}
        onBack={() => setRunId(null)}
      />
    )
  }

  return (
    <div className="sh-work" data-testid="work-panel">
      {error && (
        <div className="sh-banner sh-error" data-testid="work-error">
          {error}
        </div>
      )}
      {closed && (
        <p className="sh-muted sh-rules-note" data-testid="work-closed">
          종료된 업무 — 작업 그래프는 보기만 한다. 고치려면 연결된 새 대화에서 한다(서버도 거부한다).
        </p>
      )}
      {graph ? (
        <GraphSection
          caseId={props.caseId}
          detail={detail}
          graph={graph}
          repositories={props.repositories}
          closed={closed}
          busy={busy}
          guard={guard}
          onRun={setRunId}
        />
      ) : (
        <p className="sh-muted">작업 그래프 정보를 아직 불러오지 못했다</p>
      )}
      <RunList runs={detail.runs} graph={graph} onOpen={setRunId} />
    </div>
  )
}

// ------------------------------------------------------------------ 작업 그래프

function GraphSection(props: {
  caseId: string
  detail: ShellCaseDetail
  graph: WorkGraphState
  repositories: ProjectRepository[]
  closed: boolean
  busy: boolean
  guard: Guard
  onRun: (runId: string) => void
}) {
  const { graph } = props
  if (!graph.present) {
    return (
      <section data-testid="work-graph" data-present="false">
        <h3 className="sh-section-title">작업 그래프</h3>
        {/* 없음을 "준비됨"으로 보이지 않는다. */}
        <p className="sh-muted">
          아직 작업 그래프가 없다. 개발계획(또는 결합 기록)이 작업을 정의하면 여기에 생긴다 — 그때까지 구현 배정은 막힌다
          (작업 그래프 없음).
        </p>
      </section>
    )
  }
  const criterionKey = (id: string) =>
    (props.detail.result?.criteria ?? []).find((c) => c.id === id)?.criterion_key ?? id
  const questionName = (id: string) =>
    graph.deferred_open_questions.find((q) => q.id === id)?.question_key ?? id
  const unlinked = graph.deferred_open_questions.filter((q) => !(graph.question_blocks[q.id] ?? []).length)
  const liveKeys = graph.tasks.filter((t) => !t.cancelled).map((t) => t.task_key)
  return (
    <section data-testid="work-graph" data-present="true" data-revision={graph.graph?.revision ?? ''}>
      <h3 className="sh-section-title">작업 그래프</h3>
      <p className="sh-muted">
        리비전 {graph.graph?.revision} · {WORK_GRAPH_SOURCE_LABEL[graph.graph?.source ?? ''] ?? graph.graph?.source} ·{' '}
        {graph.graph?.reason_summary}
      </p>
      {graph.stale && (
        <p className="sh-notice sh-notice-warn" data-testid="work-graph-stale">
          의도가 바뀌어 이 그래프는 오래된 것이다. 최신 의도로 계획을 다시 만들기 전까지 배정되지 않고, 고칠 수도 없다(계획을
          다시 쓴다).
        </p>
      )}
      {unlinked.length > 0 && (
        <p className="sh-notice sh-notice-warn" data-testid="work-graph-unlinked">
          어떤 작업을 막는지 연결되지 않은 결정 {unlinked.length}건({unlinked.map((q) => q.question_key).join(', ')}) 때문에{' '}
          <strong>모든 작업이 막혀 있다</strong>. 질문에 답하거나, 아래 “기다리는 사람 결정”에서 기다리는 작업을 지정하면 좁혀진다.
        </p>
      )}
      {graph.unresolved_block_refs.length > 0 && (
        <p className="sh-notice sh-notice-warn">
          계획 원문이 가리킨 작업을 찾지 못했다:{' '}
          {graph.unresolved_block_refs.map((r) => `${questionName(r.question_id)} → ${r.raw_ref}`).join(', ')}. 버리지 않고
          남겨 두며, 그 질문은 모든 작업을 막는다.
        </p>
      )}

      <ul className="sh-result-list" data-testid="work-tasks">
        {graph.tasks.map((task) => (
          <TaskItem
            key={task.id}
            caseId={props.caseId}
            task={task}
            criterionKey={criterionKey}
            editable={!props.closed && !graph.stale}
            busy={props.busy}
            guard={props.guard}
            onRun={props.onRun}
          />
        ))}
      </ul>

      {graph.criteria_coverage.length > 0 && (
        <>
          <h4 className="sh-section-title">성공 기준 대응</h4>
          {/* 판정하지 않는다. 확인할 작업이 없는 기준을 보이기만 한다. */}
          <ul className="sh-result-list" data-testid="work-coverage">
            {graph.criteria_coverage.map((row) => (
              <li key={row.criterion_id} className="sh-plain-row">
                <strong>{row.criterion_key}</strong> {row.summary} · 구현 {row.implemented_by.join(', ') || '없음'} · 검증{' '}
                {row.has_verification_task ? row.verified_by.join(', ') : <span className="sh-warn">확인할 작업이 없다</span>}
              </li>
            ))}
          </ul>
        </>
      )}

      {graph.deferred_open_questions.length > 0 && (
        <>
          <h4 className="sh-section-title">기다리는 사람 결정</h4>
          <ul className="sh-result-list" data-testid="work-questions">
            {graph.deferred_open_questions.map((q) => (
              <QuestionLinkItem
                key={q.id}
                caseId={props.caseId}
                questionId={q.id}
                questionKey={q.question_key}
                summary={q.summary}
                blocks={graph.question_blocks[q.id] ?? []}
                taskKeys={liveKeys}
                editable={!props.closed && !graph.stale}
                busy={props.busy}
                guard={props.guard}
              />
            ))}
          </ul>
          <p className="sh-muted">
            답은 대화의 질문 카드에서 한다. 여기서 고치는 것은 <strong>어느 작업이 이 결정을 기다리는가</strong>뿐이다 — 답이
            아니며 질문은 열린 채다.
          </p>
        </>
      )}

      {!props.closed && !graph.stale && (
        <AddTaskForm
          caseId={props.caseId}
          taskKeys={liveKeys}
          repositories={props.repositories}
          busy={props.busy}
          guard={props.guard}
        />
      )}
    </section>
  )
}

function TaskItem(props: {
  caseId: string
  task: TaskRow
  criterionKey: (id: string) => string
  editable: boolean
  busy: boolean
  guard: Guard
  onRun: (runId: string) => void
}) {
  const { task } = props
  const blocked = task.readiness?.blocked_by ?? []
  const [cancelling, setCancelling] = useState(false)
  const [reason, setReason] = useState('')
  const [runs, setRuns] = useState<Run[] | null>(null)
  const [runsOpen, setRunsOpen] = useState(false)
  const runStamp = `${task.state}|${task.readiness?.runnable ?? ''}`
  useEffect(() => {
    if (!runsOpen) return
    let stopped = false
    void workGraphApi
      .taskRuns(props.caseId, task.task_key)
      .then((next) => {
        if (!stopped) setRuns(next)
      })
      .catch(() => {
        if (!stopped) setRuns([])
      })
    return () => {
      stopped = true
    }
  }, [runsOpen, props.caseId, task.task_key, runStamp])
  return (
    <li
      className="sh-plain-row sh-task"
      data-testid={`work-task-${task.task_key}`}
      data-state={task.state}
      data-cancelled={task.cancelled ? 'true' : 'false'}
      data-runnable={task.readiness?.runnable ? 'true' : 'false'}
    >
      <div>
        <strong>{task.task_key}</strong> · {TASK_KIND_LABEL[task.kind] ?? task.kind} ·{' '}
        <strong>{TASK_STATE_LABEL[task.state] ?? task.state}</strong>
        {task.readiness?.runnable ? <span className="sh-badge sh-badge-info"> 배정 가능</span> : null} · {task.summary}
      </div>
      <div className="sh-muted">
        저장소{' '}
        {task.repository_name
          ? task.repository_name
          : task.repository_ref
            ? `기록되지 않음 — 계획이 적은 «${task.repository_ref}» 를 이 업무의 선택에서 찾지 못했다`
            : '기록되지 않음'}
        {' '}· 산출물 {task.deliverable_summary || '기록 없음'} · 완료 조건 {task.completion_summary || '기록 없음'} · 선행{' '}
        {task.depends_on.length ? task.depends_on.join(', ') : '없음'} · 기준{' '}
        {task.criteria.length
          ? task.criteria
              .map((c) => `${props.criterionKey(c.criterion_id)}(${TASK_RELATION_LABEL[c.relation] ?? c.relation})`)
              .join(', ')
          : '연결 없음'}
      </div>
      {task.cancelled ? (
        <div className="sh-muted" data-testid={`work-task-cancelled-${task.task_key}`}>
          취소됨 — {task.cancel_reason || '이유 기록 없음'}
        </div>
      ) : blocked.length > 0 ? (
        <ul className="sh-result-list" data-testid={`work-task-blocked-${task.task_key}`}>
          {blocked.map((b, i) => (
            <li key={i} className="sh-warn">
              {TASK_BLOCK_LABEL[b.reason] ?? b.reason} — {b.detail}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="sh-composer-bar sh-rule-actions">
        <button
          type="button"
          className="sh-link"
          onClick={() => setRunsOpen(!runsOpen)}
          data-testid={`work-task-runs-toggle-${task.task_key}`}
        >
          {runsOpen ? '실행 닫기' : '이 작업의 실행'}
        </button>
        {props.editable && !task.cancelled && !cancelling && (
          <button
            type="button"
            className="sh-link"
            onClick={() => setCancelling(true)}
            data-testid={`work-task-cancel-${task.task_key}`}
          >
            이 작업 취소
          </button>
        )}
      </div>
      {runsOpen && (
        <ul className="sh-result-list" data-testid={`work-task-runs-${task.task_key}`}>
          {runs === null && <li className="sh-muted">불러오는 중</li>}
          {runs !== null && runs.length === 0 && <li className="sh-muted">아직 실행이 없다</li>}
          {(runs ?? []).map((run) => (
            <li key={run.run_id} className="sh-plain-row">
              <button type="button" className="sh-link sh-mono" onClick={() => props.onRun(run.run_id)}>
                {run.run_id}
              </button>{' '}
              · {RUN_PURPOSE_LABEL[run.purpose ?? ''] ?? run.purpose ?? '목적 미기록'} ·{' '}
              {RUN_STATUS_LABEL[run.status] ?? run.status}
              {run.outcome ? ` · ${run.outcome}` : ''}
              {run.stop_reason === 'timeout' ? ` · 시간 초과(제한 ${formatTimeout(run.timeout_seconds)})` : ''}
            </li>
          ))}
        </ul>
      )}
      {cancelling && (
        <div className="sh-composer-bar sh-rule-actions" data-testid={`work-task-cancel-form-${task.task_key}`}>
          <input
            className="sh-rule-input"
            placeholder="왜 취소하는가 (필수)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            data-testid={`work-task-cancel-reason-${task.task_key}`}
          />
          <button
            type="button"
            disabled={props.busy || !reason.trim()}
            onClick={() =>
              void props
                .guard(() => workGraphApi.cancelTask(props.caseId, task.task_key, reason.trim()))
                .then((ok) => {
                  if (ok) {
                    setCancelling(false)
                    setReason('')
                  }
                })
            }
            data-testid={`work-task-cancel-submit-${task.task_key}`}
          >
            취소 기록
          </button>
          <button type="button" className="sh-link" onClick={() => setCancelling(false)}>
            그만두기
          </button>
          <span className="sh-muted">행은 지워지지 않고 새 리비전에 취소로 남는다. 취소된 작업은 의존도 충족시키지 않는다.</span>
        </div>
      )}
    </li>
  )
}

function QuestionLinkItem(props: {
  caseId: string
  questionId: string
  questionKey: string
  summary: string
  blocks: string[]
  taskKeys: string[]
  editable: boolean
  busy: boolean
  guard: Guard
}) {
  const [editing, setEditing] = useState(false)
  const [chosen, setChosen] = useState<string[]>(props.blocks)
  const [reason, setReason] = useState('')
  useEffect(() => {
    if (!editing) setChosen(props.blocks)
  }, [editing, props.blocks.join('|')])
  const toggle = (key: string) =>
    setChosen((now) => (now.includes(key) ? now.filter((k) => k !== key) : [...now, key]))
  return (
    <li className="sh-plain-row" data-testid={`work-question-${props.questionKey}`} data-blocks={props.blocks.join(',')}>
      <strong>{props.questionKey}</strong> · {props.summary}
      <div className="sh-muted">
        {props.blocks.length
          ? `기다리는 작업: ${props.blocks.join(', ')}`
          : '기다리는 작업이 지정되지 않아 모든 작업을 막는다'}
        {props.editable && !editing && (
          <>
            {' '}
            <button
              type="button"
              className="sh-link"
              onClick={() => setEditing(true)}
              data-testid={`work-question-edit-${props.questionKey}`}
            >
              기다리는 작업 고치기
            </button>
          </>
        )}
      </div>
      {editing && (
        <div className="sh-rule-form" data-testid={`work-question-form-${props.questionKey}`}>
          <div className="sh-composer-bar sh-rule-actions">
            {props.taskKeys.map((key) => (
              <label key={key} className="sh-inline-check">
                <input
                  type="checkbox"
                  checked={chosen.includes(key)}
                  onChange={() => toggle(key)}
                  data-testid={`work-question-task-${props.questionKey}-${key}`}
                />{' '}
                {key}
              </label>
            ))}
          </div>
          <div className="sh-composer-bar sh-rule-actions">
            <input
              className="sh-rule-input"
              placeholder="왜 연결을 고치는가 (필수)"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              data-testid={`work-question-reason-${props.questionKey}`}
            />
            <button
              type="button"
              disabled={props.busy || !reason.trim()}
              onClick={() =>
                void props
                  .guard(() => workGraphApi.setQuestionBlocks(props.caseId, props.questionId, chosen, reason.trim()))
                  .then((ok) => {
                    if (ok) {
                      setEditing(false)
                      setReason('')
                    }
                  })
              }
              data-testid={`work-question-submit-${props.questionKey}`}
            >
              연결 저장
            </button>
            <button type="button" className="sh-link" onClick={() => setEditing(false)}>
              그만두기
            </button>
          </div>
          <p className="sh-muted">
            아무 작업도 고르지 않으면 이 결정이 모든 작업을 막는다. 연결은 답이 아니다 — 고른 작업은 답이 올 때까지 계속 막힌다.
          </p>
        </div>
      )}
    </li>
  )
}

function AddTaskForm(props: {
  caseId: string
  taskKeys: string[]
  repositories: ProjectRepository[]
  busy: boolean
  guard: Guard
}) {
  const [open, setOpen] = useState(false)
  const [key, setKey] = useState('')
  const [kind, setKind] = useState<TaskKind>('implementation')
  const [summary, setSummary] = useState('')
  const [deliverable, setDeliverable] = useState('')
  const [completion, setCompletion] = useState('')
  const [dependsOn, setDependsOn] = useState<string[]>([])
  const [repository, setRepository] = useState('')
  const [reason, setReason] = useState('')
  if (!open) {
    return (
      <button type="button" className="sh-link" onClick={() => setOpen(true)} data-testid="work-add-open">
        작업 추가
      </button>
    )
  }
  const reset = () => {
    setKey('')
    setSummary('')
    setDeliverable('')
    setCompletion('')
    setDependsOn([])
    setRepository('')
    setReason('')
    setOpen(false)
  }
  return (
    <div className="sh-rule-form" data-testid="work-add-form">
      <h4 className="sh-section-title">작업 추가 (사람의 재계획)</h4>
      <div className="sh-composer-bar sh-rule-actions">
        <input
          className="sh-rule-input"
          placeholder="작업 키 (예: T3)"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          data-testid="work-add-key"
        />
        <select value={kind} onChange={(e) => setKind(e.target.value as TaskKind)} data-testid="work-add-kind">
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {TASK_KIND_LABEL[k]}
            </option>
          ))}
        </select>
        <input
          className="sh-rule-input"
          placeholder="목적 한 줄 (필수)"
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          data-testid="work-add-summary"
        />
      </div>
      <div className="sh-composer-bar sh-rule-actions">
        <input
          className="sh-rule-input"
          placeholder="산출물 한 줄"
          value={deliverable}
          onChange={(e) => setDeliverable(e.target.value)}
        />
        <input
          className="sh-rule-input"
          placeholder="완료 조건 한 줄"
          value={completion}
          onChange={(e) => setCompletion(e.target.value)}
        />
        {props.repositories.length > 0 && (
          <select value={repository} onChange={(e) => setRepository(e.target.value)} data-testid="work-add-repository">
            <option value="">저장소 기록 안 함</option>
            {props.repositories.map((repo) => (
              <option key={repo.id} value={repo.id}>
                {repo.name}
              </option>
            ))}
          </select>
        )}
      </div>
      {props.taskKeys.length > 0 && (
        <div className="sh-composer-bar sh-rule-actions">
          <span className="sh-muted">선행 작업</span>
          {props.taskKeys.map((k) => (
            <label key={k} className="sh-inline-check">
              <input
                type="checkbox"
                checked={dependsOn.includes(k)}
                onChange={() => setDependsOn((now) => (now.includes(k) ? now.filter((x) => x !== k) : [...now, k]))}
                data-testid={`work-add-dep-${k}`}
              />{' '}
              {k}
            </label>
          ))}
        </div>
      )}
      <div className="sh-composer-bar sh-rule-actions">
        <input
          className="sh-rule-input"
          placeholder="왜 계획을 바꾸는가 (필수)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          data-testid="work-add-reason"
        />
        <button
          type="button"
          disabled={props.busy || !key.trim() || !summary.trim() || !reason.trim()}
          onClick={() =>
            void props
              .guard(() =>
                workGraphApi.addTask(
                  props.caseId,
                  {
                    key: key.trim(),
                    kind,
                    summary: summary.trim(),
                    deliverable_summary: deliverable.trim(),
                    completion_summary: completion.trim(),
                    depends_on: dependsOn,
                    ...(repository ? { repository } : {}),
                  },
                  reason.trim(),
                ),
              )
              .then((ok) => {
                if (ok) reset()
              })
          }
          data-testid="work-add-submit"
        >
          작업 추가
        </button>
        <button type="button" className="sh-link" onClick={() => setOpen(false)}>
          그만두기
        </button>
      </div>
      <p className="sh-muted">
        새 리비전이 만들어지고 이유가 남는다. 이전 리비전과 실행 이력은 그대로다. 분할은 추가 + 취소로 한다. 저장소가 둘 이상인
        업무에서 저장소를 적지 않은 작업은 구현·검증이 열리지 않는다(서버 규칙).
      </p>
    </div>
  )
}

// ------------------------------------------------------------------ 실행 목록

function RunList(props: { runs: Run[]; graph: WorkGraphState | null; onOpen: (runId: string) => void }) {
  const taskKey = (taskId: string) => props.graph?.tasks.find((t) => t.id === taskId)?.task_key ?? null
  return (
    <section data-testid="work-runs">
      <h3 className="sh-section-title">실행</h3>
      {props.runs.length === 0 && <p className="sh-muted">아직 실행이 없다</p>}
      <ul className="sh-result-list">
        {props.runs.map((run) => {
          const key = run.task_id ? taskKey(run.task_id) : null
          return (
            <li key={run.run_id} className="sh-plain-row" data-testid={`work-run-${run.run_id}`}>
              <button
                type="button"
                className="sh-link sh-mono"
                onClick={() => props.onOpen(run.run_id)}
                data-testid={`work-run-open-${run.run_id}`}
              >
                {run.run_id}
              </button>{' '}
              · {RUN_PURPOSE_LABEL[run.purpose ?? ''] ?? run.purpose ?? '목적 미기록'}
              {key ? ` · ${key}` : ''} · {RUN_STATUS_LABEL[run.status] ?? run.status}
              {run.outcome ? ` · ${run.outcome}` : ''}
              {run.stop_reason === 'timeout' && (
                <span className="sh-warn" data-testid={`work-run-timeout-${run.run_id}`}>
                  {' '}· 시간 초과(제한 {formatTimeout(run.timeout_seconds)})
                </span>
              )}
              {run.not_started_reason ? ' · 시작하지 않음' : ''} · {when(run.created_at)}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

// ------------------------------------------------------------------ 실행 상세

type RunDetailView = Run & {
  residual_observations?: { seq: number; residual: string; basis: string; observed_at?: string; recorded_at?: string }[]
  request_id?: string | null
}

function RunDetail(props: {
  caseId: string
  runId: string
  summary: Run | null
  checks: AdmissionCheck[]
  onBack: () => void
}) {
  const [run, setRun] = useState<RunDetailView | null>(null)
  const [refs, setRefs] = useState<RunContextRef[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  // 목록의 상태가 바뀌면(끝남·결과) 다시 묻는다.
  const stamp = `${props.summary?.status ?? ''}|${props.summary?.outcome ?? ''}|${props.summary?.finished_at ?? ''}`
  useEffect(() => {
    let stopped = false
    setError(null)
    void Promise.all([api.getRun(props.runId), preparationApi.contextRefs(props.runId)])
      .then(([nextRun, nextRefs]) => {
        if (stopped) return
        setRun(nextRun as RunDetailView)
        setRefs(nextRefs)
      })
      .catch((err) => {
        if (!stopped) setError(describeError(err))
      })
    return () => {
      stopped = true
    }
  }, [props.runId, stamp])

  const context = run?.context ?? null
  const knowledge = context?.knowledge ?? null
  const effect = run?.workspace_effect ?? null
  return (
    <div className="sh-work" data-testid="run-detail" data-run-id={props.runId}>
      <div className="sh-composer-bar">
        <button type="button" className="sh-link" onClick={props.onBack} data-testid="run-detail-back">
          ← 작업·실행 목록
        </button>
        <span className="sh-spacer" />
        <span className="sh-mono sh-muted">{props.runId}</span>
      </div>
      {error && <div className="sh-banner sh-error">{error}</div>}
      {!run && !error && <p className="sh-muted">불러오는 중</p>}
      {run && (
        <>
          <section data-testid="run-detail-basics">
            <h3 className="sh-section-title">
              {RUN_PURPOSE_LABEL[run.purpose ?? ''] ?? run.purpose ?? '목적 미기록'} · {RUN_STATUS_LABEL[run.status] ?? run.status}
              {run.outcome ? ` · ${run.outcome}` : ''}
            </h3>
            {run.status !== 'finished' && <p className="sh-notice sh-notice-info">아직 끝나지 않은 실행이다 — 결과·영수증은 끝난 뒤 온다</p>}
            <ul className="sh-result-list">
              <li className="sh-plain-row">
                역할 {run.role} · 도구 {run.tool_id}
                {run.observed_tool_version ? ` (${run.observed_tool_version})` : ''} · 모드 {run.mode} · 권한 {run.permission}
              </li>
              <li className="sh-plain-row">
                종료 코드 {run.exit_code ?? '—'} · 배정 세대 {run.assignment_generation} · PC {run.assigned_runner_id ?? '배정 전'} · 세션{' '}
                <span className="sh-mono">{run.session_ref ?? '보고 없음'}</span>
              </li>
              <li className="sh-plain-row">
                만듦 {when(run.created_at)} · 끝남 {when(run.finished_at)}
                {run.request_id ? ` · 요청 ${short(run.request_id)}` : ''}
              </li>
              {run.not_started_reason && (
                <li className="sh-plain-row sh-warn">CLI 를 부르기 전에 멈췄다 — {run.not_started_reason} · 소비 0 으로 정산</li>
              )}
              {run.read_only_change && (
                <li
                  className={`sh-plain-row${run.read_only_change.changed ? ' sh-warn' : ''}`}
                  data-testid="run-detail-read-only"
                  data-changed={String(run.read_only_change.changed)}
                >
                  읽기 전용 실행 전후 대조:{' '}
                  {run.read_only_change.changed
                    ? `바뀜 — ${run.read_only_change.where.join(', ')} (실패로 표시하지 않았다, D-96)`
                    : run.read_only_change.observed
                      ? '바뀌지 않음'
                      : '관측하지 못함(git 저장소가 아니거나 실패)'}
                  {run.read_only_change.unobserved.length > 0 && ` · 관측 못 함 ${run.read_only_change.unobserved.join(', ')}`}
                </li>
              )}
              <li className="sh-plain-row" data-testid="run-detail-timeout" data-stop-reason={run.stop_reason ?? ''}>
                제한 시간 {formatTimeout(run.timeout_seconds)}
                {run.stop_reason ? ` · ${stopReasonText(run.stop_reason, run.timeout_seconds)}` : ''}
                {run.stop_reason === 'timeout' && ' · 끊기기 전의 부분 결과는 기준 판정에 쓰지 않았다(출력은 아래에서 연다)'}
              </li>
              <li className="sh-plain-row">
                사용량 {typeof run.usage === 'string' ? run.usage : JSON.stringify(run.usage)} · 잔류 활동 {run.residual_activity}
                {(run.residual_observations ?? []).length > 0 &&
                  ` · 다시 확인 ${(run.residual_observations ?? []).map((o) => `${o.residual}(${o.basis})`).join(', ')}`}
              </li>
            </ul>
            {run.output_artifact_id && run.purpose !== 'discussion_reply' && (
              <button
                type="button"
                onClick={() =>
                  emit('hads:open-ref', { caseId: props.caseId, ref: { artifact_id: run.output_artifact_id as string, revision: 1 } })
                }
                data-testid="run-detail-open-output"
              >
                출력 원문 열기(결과물 뷰어 — PC 에서 불러온다)
              </button>
            )}
            {run.output_artifact_id && run.purpose === 'discussion_reply' && (
              <p className="sh-muted">이 실행의 출력은 대화의 AI 메시지로 보인다.</p>
            )}
          </section>

          <section data-testid="run-detail-context">
            <h3 className="sh-section-title">고정 입력</h3>
            <p className="sh-muted">
              이 실행에 넘긴 참조(시작 때 고정)와 Runner 가 실제로 읽었다고 보고한 영수증이다. 영수증이 없으면 읽음으로 보이지
              않는다.
            </p>
            {context && (
              <p data-testid="run-detail-context-state" data-state={context.state}>
                <strong>{RUN_CONTEXT_STATE_LABEL[context.state] ?? context.state}</strong> · 참조 {context.ref_count} · 인라인{' '}
                {context.inline_bytes} B{context.limit ? ` / 한도 ${context.limit} B` : ''} · 지시문 {context.instruction_bytes} B
                {context.omitted_count > 0 ? ` · 크기 한도로 생략 ${context.omitted_count}` : ''}
                {context.unread.length > 0
                  ? ` · 못 읽음 ${context.unread.map((u) => `${CONTEXT_ROLE_LABEL[u.role] ?? u.role}(${u.status})`).join(', ')}`
                  : ''}
                {context.receipt_generation !== null ? ` · 영수증 세대 ${context.receipt_generation}` : ''}
                {context.freshness?.state === 'drifted'
                  ? ` · ${context.freshness.basis === 'live' ? '지금' : '결과 시점'} 기준 고정 뒤 새 입력 ${context.freshness.added_count}`
                  : context.freshness
                    ? ' · 고정 뒤 새 입력 없음'
                    : ''}
              </p>
            )}
            {refs && refs.length === 0 && <p className="sh-muted">고정한 참조가 없다(지시문만)</p>}
            {refs && refs.length > 0 && (
              <ul className="sh-result-list" data-testid="run-detail-refs">
                {refs.map((ref) => (
                  <li key={ref.seq} className="sh-plain-row" data-testid={`run-detail-ref-${ref.role}`}>
                    #{ref.seq} · {CONTEXT_ROLE_LABEL[ref.role] ?? ref.role} ·{' '}
                    <span className="sh-mono">
                      {short(ref.artifact_id, 16)} r{ref.revision}
                    </span>{' '}
                    · {ref.tier_recorded ? (ref.tier === 'core' ? '핵심' : '보조') : '등급 미기록'} ·{' '}
                    {ref.inclusion_recorded ? (ref.inclusion === 'inline' ? '인라인' : '크기 한도로 생략') : '포함 미기록'} ·{' '}
                    {ref.byte_size} B · {ref.receipt_status ? RECEIPT_LABEL[ref.receipt_status] ?? ref.receipt_status : '영수증 없음'}
                  </li>
                ))}
              </ul>
            )}
            {knowledge && !knowledge.recorded && <p className="sh-muted">프로젝트 규칙 기록 전 실행(규칙 없음이 아니다)</p>}
            {knowledge && knowledge.recorded && knowledge.items.length > 0 && (
              <ul className="sh-result-list" data-testid="run-detail-knowledge">
                {knowledge.items.map((k) => (
                  <li key={`${k.knowledge_key}-${k.version}`} className="sh-plain-row">
                    규칙 {k.knowledge_key} v{k.version} · {k.decision}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {props.checks.length > 0 && (
            <section data-testid="run-detail-admission">
              <h3 className="sh-section-title">진입 검사</h3>
              <ul className="sh-result-list">
                {props.checks.map((check) => (
                  <li key={check.id} className="sh-plain-row">
                    {check.outcome === 'admitted' ? '허용' : '거부'} · {check.requested_permission} · {check.profile}
                    {check.refusals.length > 0 ? ` · ${check.refusals.map((c) => REFUSAL_LABEL[c] ?? c).join(' / ')}` : ''} ·{' '}
                    {when(check.checked_at)}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section data-testid="run-detail-events" data-count={(run.events ?? []).length}>
            <h3 className="sh-section-title">이벤트 {(run.events ?? []).length}</h3>
            {(run.events ?? []).length === 0 ? (
              <p className="sh-muted">보고된 이벤트가 없다</p>
            ) : (
              <ul className="sh-result-list">
                {(run.events ?? []).map((event) => (
                  <li key={event.seq} className="sh-plain-row sh-mono">
                    #{event.seq} · {when(event.ts)} · {event.type}
                    {event.native_type ? ` (${event.native_type})` : ''}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {(run.commands ?? []).length > 0 && (
            <section data-testid="run-detail-commands">
              <h3 className="sh-section-title">명령 {(run.commands ?? []).length}</h3>
              <ul className="sh-result-list">
                {(run.commands ?? []).map((cmd) => (
                  <li key={cmd.seq} className="sh-plain-row">
                    <span className="sh-mono">{cmd.command_summary}</span> · 종료 코드{' '}
                    {cmd.exit_code === null ? '확인 못 함' : cmd.exit_code}
                    {cmd.duration_ms !== null ? ` · ${cmd.duration_ms} ms` : ''}
                  </li>
                ))}
              </ul>
              <p className="sh-muted">명령 원문·출력은 작업 PC 의 실행 출력에 있다.</p>
            </section>
          )}

          <section data-testid="run-detail-workspace">
            <h3 className="sh-section-title">작업공간 효과</h3>
            {effect ? (
              <p>
                {effect.changed ? '이 실행이 바꿨다' : '이 실행이 바꾼 것이 없다'} · 기준 대비 누적 파일 {effect.files_changed} · +
                {effect.insertions} −{effect.deletions} · 관측 {effect.isolation}
                {effect.outside_workspace_changed === null
                  ? ' · 작업공간 밖은 관측하지 않음'
                  : effect.outside_workspace_changed
                    ? ' · 작업공간 밖 변경 관측'
                    : ' · 작업공간 밖 변경 없음'}
                {effect.external_change_before_run ? ' · 실행 전 외부 변경 있음' : ''}
              </p>
            ) : (
              <p className="sh-muted">대조 기록이 없다(쓰기 실행이 아니거나 관측하지 않았다 — "변경 없음"이 아니다)</p>
            )}
          </section>
        </>
      )}
    </div>
  )
}
