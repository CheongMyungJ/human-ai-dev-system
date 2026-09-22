// 작업 그래프 — 무엇을 어떤 순서로 만들고, 그중 **무엇이 왜 지금 막혀 있는가** (P3-02).
//
// 이 화면이 지키는 것 넷.
//
//   **차단 사유를 서버가 계산한 그대로 보인다.** 화면이 따로 계산하면 버튼은
//   눌리는데 서버가 거부하는(또는 그 반대의) 상태가 생긴다.
//
//   **그래프가 없는 것과 Task 가 없는 것을 "준비됨"으로 보이지 않는다.**
//   `present=false` 는 "Task 가 필요 없다"가 아니라 계획이 작업을 정의하지 않았다는
//   뜻이고, 그 Case 의 기능 구현은 막힌다.
//
//   **연결 없는 질문이 전부 막는다는 사실을 눈에 보이게 한다.** 좁히기가 우회가
//   되지 않는 이유를 사람이 화면에서 확인할 수 있어야 한다.
//
//   **완료는 실행 결과다.** `완료 (실행 결과)` 라고 쓰고 사람이 누르는 완료 버튼은
//   두지 않는다 — 그것은 실행 증거 없이 의존을 푸는 문이다.
//
// 검증 Task 가 없는 기준은 **보이기만 한다.** 배정을 막지 않는다 — 시스템은
// 산출물의 내용이 충분한지 판정하지 않는다는 P3-01의 경계를 그대로 유지한다.

import { useState } from 'react'

import {
  ApiError,
  TASK_BLOCK_LABEL,
  TASK_KIND_LABEL,
  TASK_RELATION_LABEL,
  TASK_STATE_LABEL,
  WORK_GRAPH_SOURCE_LABEL,
  workGraphApi,
  type CaseDetail,
  type TaskKind,
  type TaskRow,
} from './api'

const KINDS: TaskKind[] = [
  'investigation',
  'implementation',
  'verification',
  'experiment',
  'integration',
]

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (typeof err.detail === 'string') return err.detail
    if (err.detail && typeof err.detail === 'object') {
      const detail = err.detail as { message?: unknown; admission?: { refusals?: string[] } }
      if (detail.admission?.refusals) return detail.admission.refusals.join(', ')
      if (detail.message) return String(detail.message)
    }
  }
  return err instanceof Error ? err.message : String(err)
}

function TaskCard(props: {
  task: TaskRow
  criterionKey: (id: string) => string
  onCancel: (key: string) => void
  busy: boolean
}) {
  const { task } = props
  const blocked = task.readiness?.blocked_by ?? []
  return (
    <li className={task.cancelled ? 'task task-cancelled' : 'task'}>
      <div className="task-head">
        <strong>{task.task_key}</strong>
        <span className="tag">{TASK_KIND_LABEL[task.kind] ?? task.kind}</span>
        <span className="tag">{TASK_STATE_LABEL[task.state] ?? task.state}</span>
        {task.readiness?.runnable ? <span className="tag ok">배정 가능</span> : null}
      </div>
      <p>{task.summary}</p>
      <dl className="task-detail">
        <dt>대상 저장소</dt>
        <dd>
          {task.repository_name
            ? task.repository_name
            : task.repository_ref
              ? `기록되지 않음 — 계획이 적은 «${task.repository_ref}» 를 이 업무의 선택에서 찾지 못했다`
              : '기록되지 않음'}
        </dd>
        <dt>산출물</dt>
        <dd>{task.deliverable_summary || '기록 없음'}</dd>
        <dt>완료 조건</dt>
        <dd>{task.completion_summary || '기록 없음'}</dd>
        <dt>선행 작업</dt>
        <dd>{task.depends_on.length ? task.depends_on.join(', ') : '없음'}</dd>
        <dt>성공 기준</dt>
        <dd>
          {task.criteria.length
            ? task.criteria
                .map(
                  (c) =>
                    `${props.criterionKey(c.criterion_id)} (${
                      TASK_RELATION_LABEL[c.relation] ?? c.relation
                    })`,
                )
                .join(', ')
            : '연결된 기준 없음'}
        </dd>
      </dl>
      {task.cancelled ? (
        <p className="muted">취소됨 — {task.cancel_reason || '이유 기록 없음'}</p>
      ) : blocked.length ? (
        <ul className="blocked">
          {blocked.map((b, i) => (
            <li key={i}>
              <strong>{TASK_BLOCK_LABEL[b.reason] ?? b.reason}</strong> — {b.detail}
            </li>
          ))}
        </ul>
      ) : null}
      {task.cancelled ? null : (
        <button
          type="button"
          disabled={props.busy}
          onClick={() => props.onCancel(task.task_key)}
        >
          이 작업 취소
        </button>
      )}
    </li>
  )
}

export function WorkGraphPanel(props: { detail: CaseDetail; onChanged: () => void }) {
  const caseId = props.detail.id
  const graph = props.detail.preparation.work_graph
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [newKey, setNewKey] = useState('')
  const [newSummary, setNewSummary] = useState('')
  const [newKind, setNewKind] = useState<TaskKind>('implementation')
  const [reason, setReason] = useState('')

  const guard = async (work: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await work()
    } catch (err) {
      setError(describeError(err))
    } finally {
      setBusy(false)
      props.onChanged()
    }
  }

  const criterionKey = (id: string) => {
    const found = props.detail.result.criteria.find((c) => c.id === id)
    return found ? found.criterion_key : id
  }

  if (!graph.present) {
    return (
      <section className="panel">
        <h2>작업 그래프</h2>
        {/* **없음을 "준비됨"으로 보이지 않는다.** 계획이 작업을 정의하지 않았다는
            사실과 그 결과를 함께 적는다. */}
        <p className="muted">
          아직 작업 그래프가 없다. 개발계획이 Task 를 정의하면 여기에 생긴다 —
          그때까지 기능 구현 배정은 <code>work_graph_missing</code> 으로 막힌다.
        </p>
      </section>
    )
  }

  const questionName = (id: string) => {
    const found = graph.deferred_open_questions.find((q) => q.id === id)
    return found ? found.question_key : id
  }
  const unlinked = graph.deferred_open_questions.filter(
    (q) => !(graph.question_blocks[q.id] ?? []).length,
  )

  return (
    <section className="panel">
      <h2>작업 그래프</h2>
      <p className="muted">
        리비전 {graph.graph?.revision} ·{' '}
        {WORK_GRAPH_SOURCE_LABEL[graph.graph?.source ?? ''] ?? graph.graph?.source} ·{' '}
        {graph.graph?.reason_summary}
      </p>
      {graph.stale ? (
        <p className="warn">
          의도가 바뀌어 이 그래프는 오래된 것이다. 최신 의도 기준으로 계획을 다시
          만들기 전까지 배정되지 않는다.
        </p>
      ) : null}
      {error ? <p className="error">{error}</p> : null}

      {/* 좁히기가 우회가 되지 않는다는 것을 **화면에서** 확인할 수 있어야 한다. */}
      {unlinked.length ? (
        <p className="warn">
          어떤 작업을 막는지 연결되지 않은 이월 질문이 {unlinked.length}건 있어
          <strong> 모든 작업이 막혀 있다</strong> (
          {unlinked.map((q) => q.question_key).join(', ')}). 질문에 답하거나 기다리는
          작업을 지정하면 좁혀진다.
        </p>
      ) : null}
      {graph.unresolved_block_refs.length ? (
        <p className="warn">
          계획 원문이 가리킨 작업을 찾지 못했다:{' '}
          {graph.unresolved_block_refs
            .map((r) => `${questionName(r.question_id)} → ${r.raw_ref}`)
            .join(', ')}
          . 버리지 않고 남겨 두며, 그 질문은 모든 작업을 막는다.
        </p>
      ) : null}

      <ul className="tasks">
        {graph.tasks.map((task) => (
          <TaskCard
            key={task.id}
            task={task}
            busy={busy}
            criterionKey={criterionKey}
            onCancel={(key) =>
              guard(async () => {
                const why = reason.trim()
                if (!why) throw new Error('취소 이유를 적는다 — 왜 빠졌는지가 남아야 한다')
                await workGraphApi.cancelTask(caseId, key, why)
                setReason('')
              })
            }
          />
        ))}
      </ul>

      <h3>성공 기준 대응</h3>
      {/* **판정하지 않는다.** 확인할 작업이 없는 기준을 보이기만 한다. */}
      <table className="coverage">
        <thead>
          <tr>
            <th>기준</th>
            <th>구현 작업</th>
            <th>검증 작업</th>
          </tr>
        </thead>
        <tbody>
          {graph.criteria_coverage.map((row) => (
            <tr key={row.criterion_id}>
              <td>
                {row.criterion_key} — {row.summary}
              </td>
              <td>{row.implemented_by.join(', ') || '없음'}</td>
              <td>
                {row.has_verification_task ? (
                  row.verified_by.join(', ')
                ) : (
                  <span className="warn">확인할 작업이 없다</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>사람의 재계획</h3>
      <p className="muted">
        작업을 더하거나 취소하면 <strong>새 리비전</strong>이 만들어지고 이유가 남는다.
        이전 리비전과 실행 이력은 그대로 보존된다. 분할은 추가 + 취소로 한다.
      </p>
      <div className="replan">
        <input
          placeholder="작업 키 (예: T3)"
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
        />
        <select value={newKind} onChange={(e) => setNewKind(e.target.value as TaskKind)}>
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {TASK_KIND_LABEL[k]}
            </option>
          ))}
        </select>
        <input
          placeholder="목적 한 줄"
          value={newSummary}
          onChange={(e) => setNewSummary(e.target.value)}
        />
        <input
          placeholder="왜 계획을 바꾸는가 (필수)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        <button
          type="button"
          disabled={busy}
          onClick={() =>
            guard(async () => {
              await workGraphApi.addTask(
                caseId,
                { key: newKey.trim(), kind: newKind, summary: newSummary.trim() },
                reason.trim(),
              )
              setNewKey('')
              setNewSummary('')
              setReason('')
            })
          }
        >
          작업 추가
        </button>
      </div>

      {graph.deferred_open_questions.length ? (
        <>
          <h3>기다리는 사람 결정</h3>
          <ul className="questions">
            {graph.deferred_open_questions.map((q) => {
              const blocks = graph.question_blocks[q.id] ?? []
              return (
                <li key={q.id}>
                  <strong>{q.question_key}</strong> — {q.summary}
                  <br />
                  <span className="muted">
                    {blocks.length
                      ? `기다리는 작업: ${blocks.join(', ')}`
                      : '기다리는 작업이 지정되지 않아 모든 작업을 막는다'}
                  </span>
                </li>
              )
            })}
          </ul>
        </>
      ) : null}
    </section>
  )
}
