// 결과·근거 열람과 사람 최종 확인 (P2-04).
//
// **총점 하나와 녹색 표시만 보여주지 않는다**(sizing-and-review-ux 6절).
// 기준마다 판정·근거 종류·근거 원문을 따로 보이고, 미확인과 미충족과 확인 불가를
// 구별한다. 예외를 수용해도 원래 판정을 지우지 않고 나란히 보인다.
//
// 그리고 이 화면의 버튼은 조건이 아니다. 서버가 같은 요청을 같은 사유로 거부한다.

import { useState } from 'react'

import {
  ACCEPTANCE_PHRASES,
  ACCEPTANCE_REFUSAL_LABEL,
  ApiError,
  CLOSURE_KIND_LABEL,
  CRITERION_VERDICT_LABEL,
  EVIDENCE_KIND_LABEL,
  SATISFACTION_LABEL,
  api,
  intentApi,
  resultApi,
  type CaseDetail,
  type CompletionCandidate,
  type CriterionVerdict,
  type Run,
  type SuccessCriterion,
} from './api'

const CRITERION_STATE_LABEL: Record<string, string> = {
  proposed: 'AI·사람이 제안한 기준',
  user_confirmed: '사람이 확인한 기준',
  superseded: '대체된 버전의 기준',
}

/** 사람이 직접 적을 수 있는 판정. `needs_recheck` 는 시스템이 전이시키는 값이다. */
const RECORDABLE: { value: CriterionVerdict; label: string }[] = [
  { value: 'met', label: '충족' },
  { value: 'not_met', label: '미충족' },
  { value: 'blocked', label: '확인 불가 (환경·도구 문제)' },
  { value: 'unverified', label: '미확인으로 되돌리기' },
]

function refusalList(detail: unknown): string[] | null {
  if (detail && typeof detail === 'object' && 'refusals' in detail) {
    const value = (detail as { refusals?: unknown }).refusals
    if (Array.isArray(value)) return value.map(String)
  }
  return null
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    const codes = refusalList(err.detail)
    if (codes) {
      return codes.map((c) => ACCEPTANCE_REFUSAL_LABEL[c] ?? c).join(' · ')
    }
    if (typeof err.detail === 'string') return err.detail
  }
  return err instanceof Error ? err.message : String(err)
}

export function ResultPanel(props: { detail: CaseDetail; onChanged: () => void }) {
  const { detail } = props
  const view = detail.result
  const [note, setNote] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [evidence, setEvidence] = useState<{ title: string; body: string } | null>(null)
  const [statement, setStatement] = useState('')
  const [busy, setBusy] = useState(false)

  const finishedRuns = detail.runs.filter(
    (run) => run.status === 'finished' && run.outcome === 'completed',
  )

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

  return (
    <section className="subpanel">
      <h3>결과와 최종 확인</h3>
      <p className="muted small">
        기준마다 판정과 근거를 따로 본다. <strong>총점은 만들지 않는다.</strong>{' '}
        실행이 끝났다는 사실은 충족이 아니며, 결과가 <code>unknown</code> 인 실행을
        근거로는 충족을 적을 수 없다.
      </p>

      {note && <div className="notice">{note}</div>}
      {error && (
        <div className="notice refusal">
          <strong>기록하지 않았다.</strong>
          <p className="small">{error}</p>
        </div>
      )}

      <CompletionModeSwitch
        caseId={detail.id}
        mode={view.completion_mode}
        disabled={busy || view.closure !== null}
        onChange={(mode) =>
          guard(async () => {
            await resultApi.setCompletionMode(detail.id, mode)
            setNote(
              mode === 'auto_on_conditions'
                ? '자동 완료로 바꿨다. 조건을 갖추면 정책으로 완료되며 사람 인수로 기록되지 않는다.'
                : '사람 최종 확인으로 되돌렸다.',
            )
          })
        }
      />

      <h4>기준별 결과</h4>
      {view.criteria.length === 0 ? (
        <p className="muted small">
          합의할 성공 기준이 <strong>0건</strong>이다. 견줄 기준이 없으므로 최종 인수는
          거부된다. 의도 초안에 성공 기준을 넣고 새 버전을 만든다.
        </p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>기준</th>
              <th>확인 방법</th>
              <th>확인 상태</th>
              <th>판정</th>
              <th>근거</th>
              <th>판정 기록</th>
            </tr>
          </thead>
          <tbody>
            {view.criteria.map((criterion) => (
              <CriterionRow
                key={criterion.id}
                caseId={detail.id}
                criterion={criterion}
                runs={finishedRuns}
                exception={
                  view.candidate?.exceptions.find((e) => e.target_id === criterion.id) ?? null
                }
                disabled={busy || view.closure !== null}
                onRecord={(payload) =>
                  guard(async () => {
                    await resultApi.recordVerdict(detail.id, criterion.id, payload)
                    setNote(`${criterion.criterion_key} 판정을 기록했다.`)
                  })
                }
                onShowEvidence={(title, body) => setEvidence({ title, body })}
                onError={setError}
              />
            ))}
          </tbody>
        </table>
      )}

      {evidence && (
        <div className="notice">
          <strong>근거 원문 — {evidence.title}</strong>
          <p className="muted small">
            소유 Runner에서 한 번 지나간 본문이다. 제어부에 저장되지 않았고 이 화면을
            떠나면 사라진다. 다시 보려면 다시 요청한다.
          </p>
          <pre className="original">{evidence.body}</pre>
          <button type="button" onClick={() => setEvidence(null)}>
            닫기
          </button>
        </div>
      )}

      <h4>결과를 확정할 수 없는 실행</h4>
      {view.unsettled_runs.length === 0 ? (
        <p className="muted small">없다. 모든 실행의 결과가 확정됐다.</p>
      ) : (
        <>
          <p className="muted small">
            진행 중이거나 결과가 <code>unknown</code> 인 실행이다.{' '}
            <strong>인수는 기록되지만 종료는 확정되지 않는다.</strong> 불명을 성공으로도
            실패로도 바꾸지 않는다.
          </p>
          <ul className="list">
            {view.unsettled_runs.map((run) => (
              <li key={run.run_id} className="small">
                <span className="mono">{run.run_id}</span> · {run.status} ·{' '}
                {run.outcome ?? '결과 없음'}
              </li>
            ))}
          </ul>
        </>
      )}

      <h4>최종 결과 후보</h4>
      {view.candidate === null ? (
        <p className="muted small">아직 만들지 않았다.</p>
      ) : (
        <CandidateView
          candidate={view.candidate}
          criteria={view.criteria}
          disabled={busy || view.closure !== null}
          onAcceptException={(criterionId, scope) =>
            guard(async () => {
              await resultApi.acceptException(
                detail.id,
                view.candidate!.id,
                criterionId,
                scope,
              )
              setNote('예외를 수용했다. 원래 판정은 그대로 남는다.')
            })
          }
        />
      )}
      <button
        type="button"
        disabled={busy || view.closure !== null}
        onClick={() =>
          guard(async () => {
            const built = await resultApi.buildCandidate(detail.id)
            setNote(
              built.created
                ? `결과 후보 v${built.candidate.revision} 을 만들었다.`
                : '내용이 그대로라 같은 후보를 다시 보여 준다.',
            )
          })
        }
      >
        결과 후보 만들기 / 새로 고침
      </button>

      {view.closure === null ? (
        <AcceptanceForm
          candidate={view.candidate}
          statement={statement}
          setStatement={setStatement}
          mode={view.completion_mode}
          disabled={busy}
          onAccept={() =>
            guard(async () => {
              const accepted = await resultApi.accept(
                detail.id,
                view.candidate!.id,
                statement,
              )
              setStatement('')
              setNote(
                accepted.closure
                  ? `종료로 확정했다 — ${CLOSURE_KIND_LABEL[accepted.closure.closure_kind]}.`
                  : '인수를 기록했다. 다만 결과를 확정할 수 없는 실행이 남아 종료는 보류한다.',
              )
            })
          }
          onAutoComplete={() =>
            guard(async () => {
              const result = await resultApi.autoComplete(detail.id)
              if (result.applied) {
                setNote('자동 완료 정책이 적용됐다. 사람 인수로 기록되지 않았다.')
              } else if (result.refusals) {
                setNote(
                  '자동 완료 조건을 갖추지 못했다: ' +
                    result.refusals
                      .map((c) => ACCEPTANCE_REFUSAL_LABEL[c] ?? c)
                      .join(' · '),
                )
              } else {
                setNote('이 Case 는 사람 최종 확인 정책이다. 자동 완료하지 않는다.')
              }
            })
          }
        />
      ) : (
        <ClosureView detail={detail} onChanged={props.onChanged} />
      )}
    </section>
  )
}

function CompletionModeSwitch(props: {
  caseId: string
  mode: string
  disabled: boolean
  onChange: (mode: 'human_acceptance' | 'auto_on_conditions') => void
}) {
  return (
    <p className="small">
      완료 정책:{' '}
      <select
        value={props.mode}
        disabled={props.disabled}
        onChange={(e) =>
          props.onChange(e.target.value as 'human_acceptance' | 'auto_on_conditions')
        }
      >
        <option value="human_acceptance">사람 최종 확인 (기본)</option>
        <option value="auto_on_conditions">조건 충족 시 자동 완료</option>
      </select>{' '}
      <span className="muted">
        자동 완료는 <strong>사람 인수로 기록되지 않고</strong>, 미충족·미검증을 스스로
        수용하지도 않는다.
      </span>
    </p>
  )
}

function CriterionRow(props: {
  caseId: string
  criterion: SuccessCriterion
  runs: Run[]
  exception: { original_verdict: string; scope_summary: string } | null
  disabled: boolean
  onRecord: (payload: {
    verdict: CriterionVerdict
    summary: string
    evidence_kind: 'none' | 'run_output' | 'human_judgement'
    evidence_run_id?: string | null
    evidence_artifact_id?: string | null
    evidence_artifact_rev?: number | null
  }) => void
  onShowEvidence: (title: string, body: string) => void
  onError: (message: string) => void
}) {
  const { criterion } = props
  const [verdict, setVerdict] = useState<CriterionVerdict>('met')
  const [runId, setRunId] = useState('')
  const [summary, setSummary] = useState('')
  const [loading, setLoading] = useState(false)

  const chosenRun = props.runs.find((r) => r.run_id === runId) ?? null

  const openEvidence = async () => {
    if (!criterion.evidence_artifact_id) return
    setLoading(true)
    try {
      const opened = await intentApi.openRead(
        criterion.evidence_artifact_id,
        criterion.evidence_artifact_rev ?? 1,
      )
      // Runner 가 올릴 때까지 잠깐 기다린다. 오지 않으면 "PC 연결 필요"다.
      for (let attempt = 0; attempt < 12; attempt += 1) {
        const got = await intentApi.fetchRead(opened.id)
        if (got.content !== null) {
          props.onShowEvidence(criterion.criterion_key, got.content)
          return
        }
        if (got.request.state === 'expired') break
        await new Promise((resolve) => setTimeout(resolve, 400))
      }
      props.onError(
        '근거 원문이 오지 않았다. 소유 Runner 연결이 필요하다 — 원문이 사라진 것이 아니다.',
      )
    } catch (err) {
      props.onError(describeError(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <tr>
      <td className="small">
        <strong>{criterion.criterion_key}</strong> {criterion.summary}
        <br />
        <span className="muted">연결된 항목: {criterion.relates_to}</span>
      </td>
      <td className="small">{criterion.method_summary}</td>
      <td className="small">
        {CRITERION_STATE_LABEL[criterion.state] ?? criterion.state}
      </td>
      <td className="small">
        <strong>{CRITERION_VERDICT_LABEL[criterion.verdict] ?? criterion.verdict}</strong>
        {/* **어떻게 충족했는가**(P3-R4). 바꾸고 확인한 것과 이미 목표 상태였던 것은
            같은 `met` 이지만 다른 사실이며, 그 구별이 보이지 않으면 무변경 충족이
            미재현과 섞여 보인다(case-profiles 4절). */}
        {criterion.satisfaction && (
          <>
            <br />
            <span className="muted">
              {SATISFACTION_LABEL[criterion.satisfaction] ?? criterion.satisfaction}
            </span>
          </>
        )}
        {/* **다시 확인한 판정과 이어진 판정을 구별한다**(intent-artifacts 69행). */}
        {criterion.recheck_source?.startsWith('carried_from:') && (
          <>
            <br />
            <span className="muted">
              이전 버전에서 이어진 판정 — 이 버전에서 다시 확인한 것이 아니다
            </span>
          </>
        )}
        {props.exception && (
          <>
            <br />
            {/* 예외를 수용해도 원래 판정을 지우지 않는다. 둘을 함께 보인다. */}
            <span className="muted">
              예외 수용됨 (원래 판정:{' '}
              {CRITERION_VERDICT_LABEL[
                props.exception.original_verdict as CriterionVerdict
              ] ?? props.exception.original_verdict}
              )
            </span>
          </>
        )}
      </td>
      <td className="small">
        {EVIDENCE_KIND_LABEL[criterion.evidence_kind] ?? criterion.evidence_kind}
        {criterion.evidence_run_id && (
          <>
            <br />
            <span className="mono">{criterion.evidence_run_id}</span>
          </>
        )}
        {criterion.result_summary && (
          <>
            <br />
            <span className="muted">{criterion.result_summary}</span>
          </>
        )}
        {criterion.evidence_artifact_id && (
          <>
            <br />
            <button type="button" disabled={loading} onClick={openEvidence}>
              {loading ? '받는 중…' : '근거 원문 받아 보기'}
            </button>
          </>
        )}
      </td>
      <td className="small">
        <select
          value={verdict}
          disabled={props.disabled}
          onChange={(e) => setVerdict(e.target.value as CriterionVerdict)}
        >
          {RECORDABLE.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <select
          value={runId}
          disabled={props.disabled}
          onChange={(e) => setRunId(e.target.value)}
        >
          <option value="">사람 판단</option>
          {props.runs.map((run) => (
            <option key={run.run_id} value={run.run_id}>
              {run.run_id}
            </option>
          ))}
        </select>
        <input
          value={summary}
          placeholder="판정 요약 (짧게)"
          disabled={props.disabled}
          onChange={(e) => setSummary(e.target.value)}
        />
        <button
          type="button"
          disabled={props.disabled}
          onClick={() => {
            if (verdict !== 'unverified' && !summary.trim()) {
              props.onError('판정에는 짧은 요약이 필요하다.')
              return
            }
            props.onRecord({
              verdict,
              summary: summary.trim() || '미확인으로 되돌림',
              evidence_kind:
                verdict === 'unverified' ? 'none' : runId ? 'run_output' : 'human_judgement',
              evidence_run_id: runId || null,
              evidence_artifact_id: chosenRun?.output_artifact_id ?? null,
              evidence_artifact_rev: chosenRun?.output_artifact_id ? 1 : null,
            })
            setSummary('')
          }}
        >
          기록
        </button>
      </td>
    </tr>
  )
}

function CandidateView(props: {
  candidate: CompletionCandidate
  criteria: SuccessCriterion[]
  disabled: boolean
  onAcceptException: (criterionId: string, scope: string) => void
}) {
  const { candidate } = props
  const [target, setTarget] = useState('')
  const [scope, setScope] = useState('')

  const failing = props.criteria.filter((c) => c.verdict !== 'met')
  const excepted = new Set(candidate.exceptions.map((e) => e.target_id))

  return (
    <div className="notice">
      <p className="small">
        후보 v{candidate.revision} · 의도 {candidate.intent_agreement_state} · QG-01{' '}
        {candidate.gate_verdict} · 기준 {candidate.criteria_met}/{candidate.criteria_total}{' '}
        충족
        {candidate.state !== 'open' && ' · 대체됨'}
      </p>
      {candidate.acceptance && (
        <p className="small">
          <strong>
            인수됨 —{' '}
            {candidate.acceptance.mode === 'human'
              ? `사람 확인 (${candidate.acceptance.actor})`
              : `자동 완료 정책 (${candidate.acceptance.actor})`}
          </strong>
          {candidate.unsettled_runs.length > 0 && ' · 실행 상태 확인 필요'}
        </p>
      )}
      {candidate.unresolved.length > 0 && (
        <>
          <p className="small">남은 항목:</p>
          <ul className="list">
            {candidate.unresolved.map((item) => (
              <li key={`${item.kind}-${item.id}`} className="small">
                {item.kind} · {item.key ?? item.id} · {item.verdict}
                {excepted.has(item.id) && ' (예외 수용됨)'}
              </li>
            ))}
          </ul>
        </>
      )}
      {failing.length > 0 && !candidate.acceptance && (
        <div>
          <p className="small">
            남은 미충족·미검증을 확인하고 <strong>예외로 수용</strong>할 수 있다.
            수용해도 원래 판정은 바뀌지 않는다.
          </p>
          <select
            value={target}
            disabled={props.disabled}
            onChange={(e) => setTarget(e.target.value)}
          >
            <option value="">대상 기준을 고른다</option>
            {failing.map((c) => (
              <option key={c.id} value={c.id}>
                {c.criterion_key} ({CRITERION_VERDICT_LABEL[c.verdict]})
              </option>
            ))}
          </select>
          <input
            value={scope}
            placeholder="이 예외가 적용되는 범위 (짧게)"
            disabled={props.disabled}
            onChange={(e) => setScope(e.target.value)}
          />
          <button
            type="button"
            disabled={props.disabled || !target || !scope.trim()}
            onClick={() => {
              props.onAcceptException(target, scope.trim())
              setTarget('')
              setScope('')
            }}
          >
            이 예외를 수용
          </button>
        </div>
      )}
    </div>
  )
}

function AcceptanceForm(props: {
  candidate: CompletionCandidate | null
  statement: string
  setStatement: (value: string) => void
  mode: string
  disabled: boolean
  onAccept: () => void
  onAutoComplete: () => void
}) {
  const ready = props.candidate !== null && props.candidate.acceptance === null
  return (
    <div>
      <h4>최종 확인</h4>
      <p className="muted small">
        인수는 <strong>대상이 분명한 문구</strong>로만 기록된다. 다음 중 하나를 포함해야
        한다: {ACCEPTANCE_PHRASES.join(' / ')}.{' '}
        <strong>이 문구는 저장되지 않는다</strong> — 서버가 판단에만 쓰고 버린다.
      </p>
      <input
        value={props.statement}
        placeholder="예: 이 결과를 인수합니다."
        disabled={props.disabled || !ready}
        onChange={(e) => props.setStatement(e.target.value)}
      />
      <button
        type="button"
        disabled={props.disabled || !ready || !props.statement.trim()}
        onClick={props.onAccept}
      >
        이 결과를 인수
      </button>
      {props.mode === 'auto_on_conditions' && (
        <button type="button" disabled={props.disabled} onClick={props.onAutoComplete}>
          자동 완료 조건 확인
        </button>
      )}
      {props.candidate?.acceptance && (
        <p className="small muted">
          이미 인수했다. 결과를 확정할 수 없는 실행이 정리되면 종료가 확정된다.
        </p>
      )}
    </div>
  )
}

function ClosureView(props: { detail: CaseDetail; onChanged: () => void }) {
  const closure = props.detail.result.closure!
  const [title, setTitle] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [created, setCreated] = useState<string | null>(null)

  return (
    <div className="notice">
      <strong>{CLOSURE_KIND_LABEL[closure.closure_kind]}</strong>
      <p className="small">
        확정 {closure.confirmed_at} · 수용한 예외 {closure.exception_count}건
      </p>
      <p className="muted small">
        종료된 업무는 다시 바꾸지 않는다. <strong>수정 요청은 연결된 새 Case</strong> 이며
        이전 동의·인수를 승계하지 않는다. 결과를 설명하는 조회와 원문 열람은 그대로 된다.
      </p>
      {props.detail.result.relations.length > 0 && (
        <ul className="list">
          {props.detail.result.relations.map((relation) => (
            <li key={relation.id} className="small">
              {relation.from_case_id === props.detail.id ? '후속 →' : '← 출처'}{' '}
              <span className="mono">
                {relation.from_case_id === props.detail.id
                  ? relation.to_case_id
                  : relation.from_case_id}
              </span>{' '}
              · {relation.reason_summary}
            </li>
          ))}
        </ul>
      )}
      {created && <p className="small">새 Case 를 만들었다: <span className="mono">{created}</span></p>}
      {error && <p className="small">{error}</p>}
      <input
        value={title}
        placeholder="후속 업무 제목"
        onChange={(e) => setTitle(e.target.value)}
      />
      <input
        value={reason}
        placeholder="연결 사유 (짧게)"
        onChange={(e) => setReason(e.target.value)}
      />
      <button
        type="button"
        disabled={busy || !title.trim() || !reason.trim()}
        onClick={async () => {
          setBusy(true)
          setError(null)
          try {
            const successor = await resultApi.createSuccessor(
              props.detail.id,
              title.trim(),
              props.detail.kind,
              reason.trim(),
            )
            setCreated(successor.id)
            setTitle('')
            setReason('')
            // 새 Case 가 목록에 보이도록 갱신한다.
            await api.listCases(props.detail.project_id)
          } catch (err) {
            setError(describeError(err))
          } finally {
            setBusy(false)
            props.onChanged()
          }
        }}
      >
        연결된 새 Case 만들기
      </button>
    </div>
  )
}
