// P4-05. 업무 단계 진행 카드와 **확인 카드**(D-72). 서버가 준 진행 상태·대기 사유 코드로 카드를
// 고르고, 카드의 동작은 기존 사람 경로(동의·확인 지점·delta·단계 검토·피드백·예외·인수)를 그대로
// 부른다. 카드가 스스로 판정하지 않는다 — 대상·버전·해시를 보이고 서버가 검사한다.
//
//   **의례 문구를 타이핑하게 하지 않는다.** 동의·인수 문구는 버튼이 정해진 문구를 보낸다(서버 계약).
//   **확인은 다른 행동의 허용이 되지 않는다.** 카드마다 무엇에만 적용되는지 적는다.
//   **원문을 읽은 뒤에만 동의한다.** 의도 동의 카드는 결과물 패널에서 그 버전을 연 뒤 열린다 —
//   서버도 열람 기록·해시를 검사한다(FR-23).

import { useEffect, useState } from 'react'

import {
  intentApi,
  knowledgeApi,
  KNOWLEDGE_KIND_LABEL,
  KNOWLEDGE_STATE_LABEL,
  progressApi,
  resultApi,
  PROGRESS_LIMIT_LABEL,
  PROGRESS_LIMIT_SOURCE_LABEL,
  PROGRESS_STATE_LABEL,
  PROGRESS_STEP_LABEL,
  WAIT_LABEL,
  type ProgressLimitKey,
  type CaseRelationView,
  type KnowledgeRegistration,
  type ConversationView,
  type MaterialDeltaRow,
  type ProgressView,
  type ProgressWait,
} from '../api'
import { peekBody } from './bodies'
import { emit } from './events'
import type { ShellCaseDetail } from './useCaseData'

//: 의도 동의 문구. 서버는 명시 표시와 문구가 있는지만 본다 — 저장하지 않는다.
const AGREEMENT_STATEMENT = '이 의도에 동의합니다. 이 범위의 실행을 위임합니다.'
//: 최종 인수 문구. 서버가 대상이 분명한 표현인지 판단하고 본문은 버린다.
const ACCEPTANCE_STATEMENT = '이 결과를 인수합니다.'

function short(value: string | null | undefined, n = 12): string {
  return value ? value.slice(0, n) : '-'
}

function useAction(onChanged: () => void) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
    setBusy(false)
    onChanged()
  }
  return { busy, error, run }
}

// ------------------------------------------------------------------ 진행 배너

export function ProgressBanner(props: {
  conv: ConversationView
  detail: ShellCaseDetail | null
  caseId: string
  projectId: string
  onChanged: () => void
}) {
  const { conv } = props
  const progress = conv.progress ?? null
  const admin = `?view=admin&project=${props.projectId}&case=${props.caseId}`
  const action = useAction(props.onChanged)
  if (conv.stage !== 'work') return null
  if (!progress) {
    return (
      <div className="sh-banner sh-info" data-testid="work-stage-banner" data-progress="none">
        <strong>업무 단계</strong> · 이 대화의 다음 작업은 이 화면이 아직 자동으로 진행하지 않는다
        {conv.processing && !conv.processing.auto
          ? '(요청 처리기·진행기 꺼짐)'
          : '(진행기 꺼짐 또는 관리 화면·API 로 업무화된 Case)'}
        .{' '}
        <a className="sh-link" href={admin}>
          관리 화면에서 진행
        </a>
      </div>
    )
  }
  const tone =
    progress.state === 'blocked' ? 'sh-warn' : progress.state === 'paused' ? 'sh-warn' : 'sh-info'
  const waitText = progress.wait.map((w) => WAIT_LABEL[w.code] ?? w.code).join(' · ')
  return (
    <div className={`sh-banner ${tone}`} data-testid="work-stage-banner" data-progress={progress.state}>
      <strong>{PROGRESS_STATE_LABEL[progress.state]}</strong>
      {progress.state === 'running' && (
        <>
          {' '}· {PROGRESS_STEP_LABEL[progress.step] ?? progress.step}
          {progress.step_detail ? ` — ${progress.step_detail}` : ''}
        </>
      )}
      {progress.state === 'waiting_human' && <> · {waitText} — 아래 카드에서 확인한다</>}
      {progress.state === 'blocked' && (
        <>
          {' '}· {waitText}
          {progress.step_detail ? ` — ${progress.step_detail}` : ''}{' '}
          <button
            type="button"
            className="sh-link"
            disabled={action.busy}
            onClick={() => void action.run(() => progressApi.resume(props.caseId))}
            data-testid="progress-retry"
          >
            다시 시도
          </button>
        </>
      )}
      {progress.state === 'paused' && (
        <>
          {' '}· {progress.step_detail ?? '사람이 멈췄다'}{' '}
          <button
            type="button"
            className="sh-link"
            disabled={action.busy}
            onClick={() => void action.run(() => progressApi.resume(props.caseId))}
            data-testid="progress-resume"
          >
            계속 진행
          </button>
        </>
      )}
      {progress.state === 'done' && conv.closure && (
        <>
          {' '}· {conv.closure.closure_kind === 'closed_with_exceptions' ? `예외 ${conv.closure.exception_count}건을 수용하고 종료` : conv.closure.closure_kind === 'completed' ? '조건을 충족해 완료' : conv.closure.closure_kind}
          {' '}· 설명은 이 대화에서, 수정 요청은 연결된 새 대화로
        </>
      )}
      {action.error && <span className="sh-error-text"> {action.error}</span>}
      {' '}
      <a className="sh-link sh-muted" href={admin}>
        관리 화면
      </a>
    </div>
  )
}

// ------------------------------------------------------------------ 대기 카드

export function WaitCards(props: {
  conv: ConversationView
  detail: ShellCaseDetail | null
  caseId: string
  projectId: string
  runnerId: string | null
  onChanged: () => void
}) {
  const progress = props.conv.progress
  if (!progress || progress.state !== 'waiting_human') return null
  return (
    <div className="sh-cards" data-testid="wait-cards">
      {progress.wait.map((wait, index) => (
        <WaitCard key={`${wait.code}-${index}`} wait={wait} progress={progress} {...props} />
      ))}
    </div>
  )
}

function WaitCard(props: {
  wait: ProgressWait
  progress: ProgressView
  conv: ConversationView
  detail: ShellCaseDetail | null
  caseId: string
  projectId: string
  runnerId: string | null
  onChanged: () => void
}) {
  const { wait } = props
  switch (wait.code) {
    case 'intent_questions':
    case 'deferred_questions':
      return null // 질문 카드가 따로 있다
    case 'intent_agreement':
      return <AgreementCard {...props} />
    case 'controlled_start':
      return (
        <CheckpointCard
          {...props}
          checkpoint="start_scope"
          title="이 범위로 시작"
          subjectType="intent_version"
          subjectId={String(wait.subject_id ?? '')}
          subjectHash={(wait.subject_hash as string | null) ?? null}
          text="controlled 업무다. 최신 의도의 목표·범위·기준·허용 행동을 확인하면 준비·구현이 시작된다. 이 확인은 시작 범위에만 적용되며 결과 확인·게시 허용이 아니다."
        />
      )
    case 'controlled_result':
      return (
        <CheckpointCard
          {...props}
          checkpoint="result_candidate"
          title="이 결과 확인"
          subjectType="completion_candidate"
          subjectId={String(wait.candidate_id ?? '')}
          subjectHash={(wait.snapshot_hash as string | null) ?? null}
          text="controlled 업무다. 종료 후보(기준별 결과·실행 정리)를 확인하면 시스템이 종료를 확정한다. 게시·push 허용이 아니다(P5)."
        />
      )
    case 'material_delta':
      return <DeltaCard {...props} />
    case 'stage_review':
      return <StageReviewCard {...props} stage={String(wait.stage ?? '')} />
    case 'unresolved_feedback':
      return <FeedbackCard {...props} />
    case 'criteria_unresolved':
      return <ExceptionCard {...props} />
    default:
      // P4-05b. 상한에 걸린 대기는 한도·사용 수를 싣는다 — "한도를 올리고 계속" 카드.
      if (wait.limit_key === 'repair_limit' || wait.limit_key === 'task_retry_limit') {
        return <LimitWaitCard {...props} limitKey={wait.limit_key} />
      }
      return <GenericWaitCard {...props} />
  }
}

// ------------------------------------------------------------------ 의도 동의

function AgreementCard(props: {
  wait: ProgressWait
  conv: ConversationView
  detail: ShellCaseDetail | null
  caseId: string
  onChanged: () => void
}) {
  const action = useAction(props.onChanged)
  const latest = props.detail?.intent_state?.latest_intent_version ?? null
  // **대기가 가리킨 버전**이 대상이다. 상세 조회가 늦게 오면 그 버전을 아직 모를 수 있다 — 그때는
  // 동의 버튼을 열지 않는다(모르는 버전에 동의하지 않는다).
  const versionId = String(props.wait.intent_version_id ?? latest?.id ?? '')
  const target =
    (props.detail?.intent_versions ?? []).find((iv) => iv.id === versionId) ??
    (latest && latest.id === versionId ? latest : null)
  const revision = (props.wait.revision as number | undefined) ?? target?.revision
  const hash =
    (props.wait.content_hash as string | undefined) ??
    (target as { content_hash?: string } | null)?.content_hash ??
    null
  const artifactId = target?.artifact_id ?? null
  const artifactRev = (target as { artifact_rev?: number } | null)?.artifact_rev ?? 1
  // 이 탭에서 **그 원문을 불러왔는가.** 불러오는 것이 열람 기록을 남기고, 서버는 그 기록을 검사한다.
  const [, tick] = useState(0)
  useEffect(() => {
    const timer = setInterval(() => tick((n) => n + 1), 700)
    return () => clearInterval(timer)
  }, [])
  const read = artifactId ? peekBody(artifactId, artifactRev).status === 'loaded' : false
  // 더 새 버전이 있으면 이 카드는 낡았다. 상세가 늦게 온 경우(대상 버전을 아직 모름)는 낡음이 아니다.
  const stale = latest !== null && target !== null && latest.revision > target.revision
  return (
    <div className="sh-card sh-card-wait" data-testid="agreement-card">
      <div className="sh-card-head">
        <strong>의도 동의</strong> · v{revision ?? '?'}
      </div>
      <div className="sh-muted">
        의도 원문을 읽고 동의하면 그 범위의 실행을 위임한 것이 된다. 동의는 <strong>이 버전·이 원문</strong>에만
        붙는다 — 원문이 바뀌면 다시 동의한다. 게시·push 허용이 아니다.
      </div>
      {stale && <p className="sh-notice sh-notice-warn">새 버전이 생겼다. 최신 버전을 다시 본다.</p>}
      <div className="sh-composer-bar">
        <button
          type="button"
          onClick={() =>
            artifactId && emit('hads:open-ref', { caseId: props.caseId, ref: { artifact_id: artifactId, revision: artifactRev } })
          }
          data-testid="agreement-open"
        >
          원문 열기
        </button>
        {!read && <span className="sh-notice sh-notice-info">원문을 연 뒤 동의할 수 있다</span>}
        {action.error && <span className="sh-notice sh-notice-warn">{action.error}</span>}
        <span className="sh-spacer" />
        <button
          type="button"
          className="sh-primary"
          disabled={!read || stale || !hash || !target || action.busy}
          onClick={() => void action.run(() => intentApi.agree(props.caseId, versionId, hash as string, AGREEMENT_STATEMENT))}
          data-testid="agreement-agree"
        >
          이 의도에 동의 — 이 범위의 실행을 위임
        </button>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ controlled 확인

function CheckpointCard(props: {
  caseId: string
  checkpoint: 'start_scope' | 'result_candidate'
  title: string
  subjectType: string
  subjectId: string
  subjectHash: string | null
  text: string
  onChanged: () => void
}) {
  const action = useAction(props.onChanged)
  return (
    <div className="sh-card sh-card-wait" data-testid={`checkpoint-card-${props.checkpoint}`}>
      <div className="sh-card-head">
        <strong>{props.title}</strong> · 대상 {props.subjectType} {short(props.subjectId)}
        {props.subjectHash ? ` · 해시 ${short(props.subjectHash, 10)}` : ''}
      </div>
      <div className="sh-muted">{props.text}</div>
      <div className="sh-composer-bar">
        {props.checkpoint === 'result_candidate' && (
          <button type="button" onClick={() => emit('hads:open-panel', { caseId: props.caseId, tab: 'results' })}>
            결과물 보기
          </button>
        )}
        {action.error && <span className="sh-notice sh-notice-warn">{action.error}</span>}
        <span className="sh-spacer" />
        <button
          type="button"
          className="sh-primary"
          disabled={!props.subjectId || action.busy}
          onClick={() =>
            void action.run(() =>
              progressApi.confirmCheckpoint(
                props.caseId,
                props.checkpoint,
                props.subjectType,
                props.subjectId,
                props.subjectHash,
                '',
              ),
            )
          }
          data-testid={`checkpoint-confirm-${props.checkpoint}`}
        >
          {props.title}
        </button>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ material delta

function DeltaCard(props: { caseId: string; onChanged: () => void }) {
  const action = useAction(props.onChanged)
  const [pending, setPending] = useState<MaterialDeltaRow[]>([])
  useEffect(() => {
    void progressApi.materialDeltas(props.caseId).then((s) => setPending(s.pending)).catch(() => setPending([]))
  }, [props.caseId])
  return (
    <div className="sh-card sh-card-wait" data-testid="delta-card">
      <div className="sh-card-head">
        <strong>동의된 의도의 변경 확인</strong> · {pending.length}건
      </div>
      <div className="sh-muted">
        AI 가 동의된 항목을 바꿨다. 마지막 유효 위임과 대조해 한 건씩 확인한다 — 한 번의 확인은 한 건에만 적용된다.
      </div>
      <ul className="sh-result-list">
        {pending.map((delta) => (
          <li key={delta.id} className="sh-plain-row">
            {delta.change_class} {delta.target_key} · {delta.detail}{' '}
            <button
              type="button"
              className="sh-link"
              disabled={action.busy}
              onClick={() => void action.run(() => progressApi.materialDeltas(props.caseId).then(() => confirmDelta(props.caseId, delta.id)))}
            >
              확인
            </button>
          </li>
        ))}
      </ul>
      {action.error && <p className="sh-notice sh-notice-warn">{action.error}</p>}
    </div>
  )
}

async function confirmDelta(caseId: string, deltaId: string) {
  const { progressionApi } = await import('../api')
  return progressionApi.confirmDelta(caseId, deltaId)
}

// ------------------------------------------------------------------ 단계 검토

function StageReviewCard(props: { caseId: string; stage: string; wait: ProgressWait; onChanged: () => void }) {
  const action = useAction(props.onChanged)
  const label: Record<string, string> = { design: '설계', plan: '개발계획', combined: '결합 기록' }
  return (
    <div className="sh-card sh-card-wait" data-testid="stage-review-card">
      <div className="sh-card-head">
        <strong>{label[props.stage] ?? props.stage} 검토</strong> · 사람 검토 설정
      </div>
      <div className="sh-muted">
        결과물 패널에서 원문을 읽고 검토를 기록한다. 화면을 연 것은 검토가 아니다. 검토는 이 산출물에만 붙는다.
      </div>
      <div className="sh-composer-bar">
        <button type="button" onClick={() => emit('hads:open-panel', { caseId: props.caseId, tab: 'results' })}>
          결과물 보기
        </button>
        {action.error && <span className="sh-notice sh-notice-warn">{action.error}</span>}
        <span className="sh-spacer" />
        <button
          type="button"
          className="sh-primary"
          disabled={action.busy}
          onClick={() => void action.run(() => progressApi.reviewStage(props.caseId, props.stage, '원문을 읽고 검토했다'))}
          data-testid="stage-review-confirm"
        >
          검토함
        </button>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ 피드백 처리

function FeedbackCard(props: { caseId: string; detail: ShellCaseDetail | null; onChanged: () => void }) {
  const action = useAction(props.onChanged)
  const [reason, setReason] = useState('')
  const received = (props.detail?.feedback ?? []).filter((f) => f.state === 'received')
  return (
    <div className="sh-card sh-card-wait" data-testid="feedback-card">
      <div className="sh-card-head">
        <strong>미해결 피드백</strong> · {received.length}건
      </div>
      <div className="sh-muted">피드백을 준 사람이 새 버전을 보고 반영됐는지 판단한다. AI 가 스스로 반영했다고 선언하지 않는다.</div>
      <ul className="sh-result-list">
        {received.map((fb) => (
          <li key={fb.id} className="sh-plain-row">
            v{fb.target_intent_revision} · {fb.summary}{' '}
            <button type="button" className="sh-link" disabled={action.busy} onClick={() => void action.run(() => intentApi.resolveFeedback(props.caseId, fb.id, { reflected: true }))}>
              반영됨
            </button>{' '}
            <button type="button" className="sh-link" disabled={action.busy || !reason.trim()} onClick={() => void action.run(() => intentApi.resolveFeedback(props.caseId, fb.id, { reflected: false, reason }))}>
              미반영(사유 필요)
            </button>
          </li>
        ))}
      </ul>
      <input className="sh-input" value={reason} placeholder="미반영 사유" onChange={(e) => setReason(e.target.value)} />
      {action.error && <p className="sh-notice sh-notice-warn">{action.error}</p>}
    </div>
  )
}

// ------------------------------------------------------------------ 예외 수용

function ExceptionCard(props: { wait: ProgressWait; caseId: string; detail: ShellCaseDetail | null; onChanged: () => void }) {
  const action = useAction(props.onChanged)
  const criteria = (props.wait.criteria as { id: string; key: string | null; verdict: string | null }[] | undefined) ?? []
  const candidateId = String(props.wait.candidate_id ?? '')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [scope, setScope] = useState('')
  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const acceptWithExceptions = async () => {
    for (const criterion of criteria) {
      if (selected.has(criterion.id)) {
        await resultApi.acceptException(props.caseId, candidateId, criterion.id, scope.trim())
      }
    }
    await resultApi.accept(props.caseId, candidateId, ACCEPTANCE_STATEMENT)
  }
  const summaries = new Map((props.detail?.result?.criteria ?? []).map((c) => [c.id, c]))
  return (
    <div className="sh-card sh-card-wait" data-testid="exception-card">
      <div className="sh-card-head">
        <strong>미충족·미검증 기준</strong> · {criteria.length}건 · 후보 {short(candidateId)}
      </div>
      <div className="sh-muted">
        자동 정책은 예외를 스스로 수용하지 않는다. 수용할 기준을 고르고 남은 범위·영향을 적어 종료하거나, 수정을 요청한다(종료된 뒤의
        수정은 새 대화). 원래 판정은 그대로 남는다.
      </div>
      <ul className="sh-result-list">
        {criteria.map((criterion) => (
          <li key={criterion.id} className="sh-plain-row">
            <label>
              <input type="checkbox" checked={selected.has(criterion.id)} onChange={() => toggle(criterion.id)} data-testid={`exception-pick-${criterion.key}`} />{' '}
              {criterion.key} · {criterion.verdict} · {summaries.get(criterion.id)?.summary ?? ''}
            </label>
          </li>
        ))}
      </ul>
      <textarea className="sh-input" rows={2} value={scope} placeholder="수용하는 범위와 알려진 영향(필수)" onChange={(e) => setScope(e.target.value)} data-testid="exception-scope" />
      <div className="sh-composer-bar">
        {action.error && <span className="sh-notice sh-notice-warn">{action.error}</span>}
        <span className="sh-spacer" />
        <button
          type="button"
          className="sh-primary"
          disabled={!candidateId || selected.size === 0 || !scope.trim() || action.busy}
          onClick={() => void action.run(acceptWithExceptions)}
          data-testid="exception-accept"
        >
          선택한 예외를 수용하고 종료
        </button>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ 그 밖의 대기

function GenericWaitCard(props: { wait: ProgressWait; progress: ProgressView; caseId: string; projectId: string; onChanged: () => void }) {
  const action = useAction(props.onChanged)
  const admin = `?view=admin&project=${props.projectId}&case=${props.caseId}`
  const extra = Object.entries(props.wait)
    .filter(([k]) => !['code', 'detail'].includes(k))
    .map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
    .join(' · ')
  return (
    <div className="sh-card sh-card-wait" data-testid={`wait-card-${props.wait.code}`}>
      <div className="sh-card-head">
        <strong>{WAIT_LABEL[props.wait.code] ?? props.wait.code}</strong>
      </div>
      <div className="sh-muted">{props.wait.detail}</div>
      {extra && <div className="sh-mono sh-muted">{extra}</div>}
      <div className="sh-composer-bar">
        <a className="sh-link" href={admin}>
          관리 화면에서 보기
        </a>
        {action.error && <span className="sh-notice sh-notice-warn">{action.error}</span>}
        <span className="sh-spacer" />
        <button type="button" disabled={action.busy} onClick={() => void action.run(() => progressApi.resume(props.caseId))} data-testid="wait-retry">
          다시 시도
        </button>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ 상한 대기 (P4-05b)

function LimitWaitCard(props: {
  wait: ProgressWait
  progress: ProgressView
  caseId: string
  projectId: string
  limitKey: ProgressLimitKey
  onChanged: () => void
}) {
  const action = useAction(props.onChanged)
  const admin = `?view=admin&project=${props.projectId}&case=${props.caseId}`
  const limit = Number(props.wait.limit ?? 0)
  const used = Number(props.wait.used ?? 0)
  const max = props.progress.limits?.range.max ?? 10
  const source = props.wait.limit_source === 'case_setting' ? 'case_setting' : 'system_default'
  const label = PROGRESS_LIMIT_LABEL[props.limitKey]
  const target = [props.wait.task_key, props.wait.stage].filter(Boolean).join(' · ')
  // 올리면 서버가 기록 뒤 진행기를 부른다 — 그 자리에서 한 번 더 가고, 다시 실패하면 새 한도에서 멈춘다.
  const raise = () =>
    progressApi.setLimits(props.caseId, { [props.limitKey]: limit + 1 }, '대기 카드에서 한도를 올림')
  return (
    <div className="sh-card sh-card-wait" data-testid={`wait-card-${props.wait.code}`} data-limit-key={props.limitKey}>
      <div className="sh-card-head">
        <strong>{WAIT_LABEL[props.wait.code] ?? props.wait.code}</strong>
        <span className="sh-muted" data-testid="limit-usage">
          {' '}· {label} {used}/{limit} ({PROGRESS_LIMIT_SOURCE_LABEL[source]})
        </span>
      </div>
      <div className="sh-muted">{props.wait.detail}</div>
      {target && <div className="sh-mono sh-muted">{target}</div>}
      <div className="sh-muted">
        한도를 올리면 한 번 더 시도하고, 다시 실패하면 새 한도에서 멈춘다. 시도 수는 처음부터 다시 세지 않는다.
        한도를 올리는 것은 결과의 인수·예외 수용이 아니다.
      </div>
      <div className="sh-composer-bar">
        <a className="sh-link" href={admin}>
          관리 화면에서 보기
        </a>
        {action.error && <span className="sh-notice sh-notice-warn">{action.error}</span>}
        <span className="sh-spacer" />
        {limit < max ? (
          <button
            type="button"
            className="sh-primary"
            disabled={action.busy}
            onClick={() => void action.run(raise)}
            data-testid="limit-raise"
          >
            한도를 올리고 계속 ({label} {limit} → {limit + 1})
          </button>
        ) : (
          <span className="sh-notice sh-notice-warn">한도가 최대({max})다. 요청을 고치거나 관리 화면에서 본다</span>
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ 지식 자동 등록 (P4-06)

//: 등록하지 않은 이유(서버 사유 코드 → 읽을 말).
const KNOWLEDGE_REFUSAL_LABEL: Record<string, string> = {
  unknown_repository: '그런 저장소가 이 프로젝트에 없다',
  unknown_supersedes_key: '바꾸라는 기존 규칙을 찾지 못했다',
  invalid_kind_or_obligation: '종류·효력을 알아볼 수 없다',
  format_error: '형식이 맞지 않는다',
  reply_not_completed: '응답이 완료되지 않았다',
  summary_missing: '제목이 없다',
  content_not_stored: '내용이 저장되지 않았다',
  invalid_scope: '범위를 알아볼 수 없다',
  too_many_items: '한 번에 너무 많다',
}

/**
 * 대화의 말에서 **프로젝트 규칙으로 등록한 것**(사용자 결정 2026-09-24 — 자동 활성, 재승인 없음).
 * 권위는 사용자가 한 말이고 AI 는 옮겨 적었다. 옮기며 뜻이 바뀌었을 수 있으므로 여기서 바로
 * **무효로** 할 수 있다(내용 고치기는 관리 화면의 새 버전). 등록은 실행 권한이 아니다.
 */
export function KnowledgeCards(props: {
  registrations: KnowledgeRegistration[]
  projectId: string
  caseId: string
  onChanged: () => void
}) {
  if (props.registrations.length === 0) return null
  return (
    <>
      {props.registrations.map((r) => (
        <KnowledgeCard key={`${r.run_id}-${r.report_index}`} registration={r} {...props} />
      ))}
    </>
  )
}

function KnowledgeCard(props: { registration: KnowledgeRegistration; projectId: string; caseId: string; onChanged: () => void }) {
  const r = props.registration
  const action = useAction(props.onChanged)
  const [reason, setReason] = useState('')
  const [asking, setAsking] = useState(false)
  const admin = `?view=admin&project=${props.projectId}&case=${props.caseId}`
  if (r.intake_state === 'refused') {
    return (
      <div className="sh-card sh-card-event" data-testid="knowledge-refused-card">
        <strong>프로젝트 규칙으로 등록하지 않음</strong> · {r.reported_summary ?? ''}
        <div className="sh-muted">
          {KNOWLEDGE_REFUSAL_LABEL[r.refusal ?? ''] ?? r.refusal ?? ''} — 필요하면 범위·내용을 분명히 해서 다시 말하거나 관리 화면에서 등록한다
        </div>
      </div>
    )
  }
  const live = r.current_state === 'active' || r.current_state === 'candidate'
  const scope =
    r.scope_kind === 'repository'
      ? `저장소 ${r.repository_name ?? '?'}${r.paths.length ? ` · 경로 ${r.paths.join(', ')}` : ''}`
      : '프로젝트 전체'
  return (
    <div className="sh-card sh-card-event" data-testid="knowledge-card" data-state={r.current_state ?? ''}>
      <div className="sh-card-head">
        <strong>프로젝트 규칙으로 등록됨</strong> · {r.knowledge_key} v{r.version} ·{' '}
        {r.obligation === 'required' ? '필수' : '참고'} · {KNOWLEDGE_KIND_LABEL[r.kind ?? 'constraint']}
      </div>
      <div>{r.summary}</div>
      <div className="sh-muted">
        {scope} · 활동 {r.activities.join(', ') || '모든 작업'} · 권위: 이 대화에서 한 말(AI 가 옮겨 적음)
        {r.current_version && r.current_version !== r.version
          ? ` · 지금은 v${r.current_version}(${KNOWLEDGE_STATE_LABEL[r.current_state ?? 'active']})`
          : r.current_state && r.current_state !== 'active'
            ? ` · 지금 ${KNOWLEDGE_STATE_LABEL[r.current_state]}`
            : ''}
      </div>
      <div className="sh-muted">
        앞으로 이 프로젝트의 해당 작업에 원문과 함께 주입된다. 옮긴 내용이 다르면 무효로 하고 다시 말한다. 주입은 준수의 증거가 아니다.
      </div>
      {live && r.knowledge_id && (
        <div className="sh-composer-bar">
          <a className="sh-link" href={admin}>
            관리 화면에서 보기·고치기
          </a>
          {action.error && <span className="sh-notice sh-notice-warn">{action.error}</span>}
          <span className="sh-spacer" />
          {asking ? (
            <>
              <input
                className="sh-input"
                placeholder="무효 사유"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                data-testid="knowledge-invalidate-reason"
              />
              <button
                type="button"
                disabled={!reason.trim() || action.busy}
                onClick={() => void action.run(() => knowledgeApi.invalidate(r.knowledge_id!, reason))}
                data-testid="knowledge-invalidate-confirm"
              >
                무효로
              </button>
            </>
          ) : (
            <button type="button" onClick={() => setAsking(true)} data-testid="knowledge-invalidate">
              이 등록을 무효로
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ 후속 Case

export function RelationCards(props: { relations: CaseRelationView[]; projectId: string }) {
  const successors = props.relations.filter((r) => r.direction === 'successor')
  if (successors.length === 0) return null
  return (
    <>
      {successors.map((relation) => (
        <div key={relation.case_id} className="sh-card sh-card-event" data-testid="follow-up-card">
          <strong>수정 요청이 연결된 새 대화로 옮겨졌다</strong> · {relation.title}
          <div className="sh-muted">
            {relation.reason_summary ?? ''} · 이 종료된 업무의 결과·판정은 그대로다. 이전 동의·권한은 새 업무에 승계되지 않는다.{' '}
            <a className="sh-link" href={`?project=${props.projectId}&case=${relation.case_id}`} data-testid="follow-up-link">
              새 대화로 이동
            </a>
          </div>
        </div>
      ))}
    </>
  )
}

export function PredecessorLine(props: { relations: CaseRelationView[]; projectId: string }) {
  const predecessors = props.relations.filter((r) => r.direction === 'predecessor')
  if (predecessors.length === 0) return null
  return (
    <div className="sh-banner sh-info" data-testid="predecessor-line">
      이전 업무에서 이어진 대화 ·{' '}
      {predecessors.map((relation) => (
        <a key={relation.case_id} className="sh-link" href={`?project=${props.projectId}&case=${relation.case_id}`}>
          {relation.title}
        </a>
      ))}{' '}
      — 이전 동의·권한은 승계되지 않는다. 필요한 의도·검토·검증을 새로 거친다.
    </div>
  )
}
