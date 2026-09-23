// 가운데 대화(D-70·D-71·D-75·D-76). 대표 대화, 근거 있는 진행 표시, 질문 카드, 공통 입력창.
//
//   **진행은 서버 상태로만 말한다.** 요청 상태와 실행별 실제 상태(`execution_state`)를 문장으로
//   옮길 뿐이고 진행률·예상 시간을 지어내지 않는다.
//   **중단은 요청이다.** 관련 실행이 실제로 끝난 것을 서버가 확인해야 전송이 열린다.
//   **업무 단계는 진행기가 잇는다**(P4-05). 진행 상태·확인 카드는 서버의 `progress` 값 그대로이며
//   진행기가 잇지 않는 Case 는 그 사실을 보이고 관리 화면으로 연결한다.

import { useEffect, useMemo, useRef, useState } from 'react'

import {
  conversationApi,
  CONVERSATION_REFUSAL_LABEL,
  GATE_VERDICT_LABEL,
  INTERPRETATION_REFUSAL_LABEL,
  PROFILE_LABEL,
  RECEIPT_LABEL,
  REQUEST_STATE_LABEL,
  RUN_EXECUTION_LABEL,
  type ConversationMessage,
  type ConversationRequest,
  type ConversationView as ConversationData,
  type IntentQuestion,
  type PreparationArtifact,
  type ProjectWithAttention,
  type RequestRun,
  type RunnerWithConnection,
} from '../api'
import {
  beginSend,
  cardDraftKey,
  edit,
  load,
  newClientId,
  save,
  settle,
  type Draft,
} from '../lib/drafts'
import { browserStore } from '../lib/prefs'
import { splitRunOutput } from '../lib/runOutput'
import { buildResultDocs, findDocFor, isLatest, type ResultDoc } from '../lib/versions'
import { BODY_STATUS_LABEL, retryBody, useBody, type BodyOptions } from './bodies'
import { Composer, randomId, refusalText } from './Composer'
import { emit } from './events'
import type { PanelTab } from './ReviewPanel'
import { KnowledgeCards, PredecessorLine, ProgressBanner, RelationCards, WaitCards } from './ProgressCards'
import { checkReceipt, sendAndConfirm } from './send'
import type { ShellCaseDetail } from './useCaseData'

const store = browserStore()

const PURPOSE_LABEL: Record<string, string> = {
  discussion_reply: '논의 응답',
  intent_authoring: '의도 초안 작성',
  intent_gate_review: 'QG-01 의미 검토',
  quality_gate_review: '품질 게이트 검토',
  limited_analysis: '제한 분석',
  design_authoring: '설계 작성',
  plan_authoring: '계획 작성',
  feature_implementation: '구현',
  verification_run: '검증',
  local_experiment: '로컬 실험',
}

const CASE_STATUS_LABEL: Record<string, string> = {
  received: '접수',
  in_progress: '진행 중',
  waiting_human: '사람 대기',
  waiting_environment: '환경 대기',
  paused: '일시 정지',
  waiting_final_acceptance: '최종 확인 대기',
  closed: '종료',
  cancelled: '취소',
}

const AGREEMENT_LABEL: Record<string, string> = {
  no_intent: '의도 초안 없음',
  never_agreed: '의도 동의 전',
  stale_agreement: '동의 이후 의도가 바뀜',
  agreed_current: '의도 동의됨',
}

function receiptAvailability(receipt: string): BodyOptions['availability'] {
  if (receipt === 'stored') return 'available'
  if (receipt === 'lost_before_persist') return 'lost_before_persist'
  return 'pending'
}

function time(value: string | null | undefined): string {
  return value ? value.slice(11, 16) : ''
}

export function ConversationView(props: {
  caseId: string
  project: ProjectWithAttention
  conv: ConversationData | null
  detail: ShellCaseDetail | null
  preparations: PreparationArtifact[]
  dataError: string | null
  runners: RunnerWithConnection[]
  panel: PanelTab | null
  scrollTop: number | null
  onScroll: (top: number) => void
  onPanel: (tab: PanelTab) => void
  onChanged: () => void
}) {
  const { conv, detail, caseId } = props
  const scroller = useRef<HTMLDivElement | null>(null)
  const restored = useRef(false)
  const nearBottom = useRef(true)
  const scrollTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const [actionError, setActionError] = useState<string | null>(null)

  // 원문을 가진 PC 의 연결. **서버가 도출한 값**을 쓴다.
  const connected = useMemo(() => {
    const byRunner = new Map(props.runners.map((r) => [r.id, r.connection.state === 'connected']))
    return (runnerId: string | null | undefined) =>
      runnerId ? byRunner.get(runnerId) ?? false : conv?.send.runner_connection.state === 'connected'
  }, [props.runners, conv])
  const owners = useMemo(() => {
    const map = new Map<string, string>()
    for (const artifact of detail?.artifacts ?? []) {
      map.set(`${artifact.artifact_id}@${artifact.revision}`, artifact.owner_runner_id)
    }
    return map
  }, [detail])
  const ownerOf = (artifactId: string, revision: number) =>
    owners.get(`${artifactId}@${revision}`) ?? conv?.send.runner_connection.runner_id ?? null

  const docs: ResultDoc[] = useMemo(
    () =>
      detail
        ? buildResultDocs({
            intents: detail.intent_versions.map((iv) => ({
              ...iv,
              artifact_rev: (iv as { artifact_rev?: number }).artifact_rev ?? 1,
            })),
            preparations: props.preparations,
            runs: detail.runs,
          })
        : [],
    [detail, props.preparations],
  )

  // ---------------------------------------------------------- 읽던 위치
  useEffect(() => {
    const el = scroller.current
    if (!el || !conv) return
    if (!restored.current) {
      restored.current = true
      el.scrollTop = props.scrollTop ?? el.scrollHeight
      nearBottom.current = props.scrollTop === null
      return
    }
    if (nearBottom.current) el.scrollTop = el.scrollHeight
  }, [conv, props.scrollTop])

  const onScroll = () => {
    const el = scroller.current
    if (!el) return
    nearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    clearTimeout(scrollTimer.current)
    scrollTimer.current = setTimeout(() => props.onScroll(Math.round(el.scrollTop)), 400)
  }

  if (!conv) {
    return (
      <div className="sh-empty">
        {props.dataError ? `대화를 불러오지 못했다: ${props.dataError}` : '대화를 불러오는 중'}
      </div>
    )
  }

  const current = conv.current_request
  const interpretationByRun = new Map((conv.interpretations ?? []).map((i) => [i.run_id, i]))
  const openedBy = new Map(conv.requests.map((r) => [r.opened_by_message_id, r]))
  const latestIntent = detail?.intent_state?.latest_intent_version ?? null
  // P4-05. 이월 질문(설계·계획 단계에서 정한다)도 카드다. 답은 그 질문에만 적용된다.
  // 서버가 **최신 의도 버전의** 이월 질문만 준다(`deferred_open_questions`).
  const deferred: IntentQuestion[] = (detail?.preparation?.deferred_open_questions ?? []) as IntentQuestion[]
  const openQuestions: IntentQuestion[] = [
    ...(detail?.intent_state?.open_intent_questions ?? []),
    ...deferred,
  ]
  const resultCount = docs.length

  const archiveToggle = async () => {
    try {
      setActionError(null)
      if (conv.visibility.archived) await conversationApi.restore(caseId)
      else await conversationApi.archive(caseId)
      props.onChanged()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <div className="sh-conversation" data-testid="conversation">
      <header className="sh-header">
        <div className="sh-header-title">
          <h1 data-testid="conversation-title">{conv.title}</h1>
          <span className="sh-muted" data-testid="stage-label">
            {conv.stage === 'discussion'
              ? '논의 중 · 목표·업무 유형 미정'
              : `업무 · ${conv.profile ? PROFILE_LABEL[conv.profile] ?? conv.profile : conv.kind}`}
            {conv.visibility.archived && ' · 보관됨(종료 아님)'}
            {['closed', 'cancelled'].includes(conv.status) && ` · 종료(${conv.status})`}
          </span>
        </div>
        <div className="sh-header-actions">
          <button
            type="button"
            className={props.panel === 'results' ? 'sh-tab sh-tab-on' : 'sh-tab'}
            onClick={() => props.onPanel('results')}
            data-testid="open-results"
          >
            결과물{resultCount ? ` ${resultCount}` : ''}
          </button>
          <button
            type="button"
            className={props.panel === 'decisions' ? 'sh-tab sh-tab-on' : 'sh-tab'}
            onClick={() => props.onPanel('decisions')}
            data-testid="open-decisions"
          >
            결정 사항
          </button>
          <button type="button" className="sh-link" onClick={() => void archiveToggle()} data-testid="archive-toggle">
            {conv.visibility.archived ? '보관 해제' : '보관'}
          </button>
        </div>
      </header>
      {actionError && <div className="sh-banner sh-error">{actionError}</div>}
      <StageBanner conv={conv} />
      <ProgressBanner conv={conv} detail={detail} caseId={caseId} projectId={props.project.id} onChanged={props.onChanged} />
      <PredecessorLine relations={conv.relations ?? []} projectId={props.project.id} />
      {conv.send.runner_connection.state !== 'connected' &&
        conv.send.runner_connection.state !== 'not_determined' && (
          <div className="sh-banner sh-warn" data-testid="pc-disconnected">
            PC 미연결
            {conv.send.runner_connection.last_seen_at &&
              ` · 마지막 확인 ${conv.send.runner_connection.last_seen_at.replace('T', ' ').slice(0, 19)}`}{' '}
            — 이미 불러온 내용과 작성 중인 초안은 그대로다. 새 원문 열람과 전송은 연결된 뒤에 한다.
          </div>
        )}

      <div className="sh-timeline" ref={scroller} onScroll={onScroll} data-testid="timeline">
        {conv.messages.length === 0 && (
          <p className="sh-muted sh-timeline-empty">
            {conv.stage === 'discussion'
              ? '무엇이든 이야기로 시작한다. 분명한 작업 요청(예: "분석해서 개선안을 정리해줘")을 보내면 AI 가 해석해 같은 대화에서 업무로 전환한다.'
              : '아직 메시지가 없다.'}
          </p>
        )}
        {conv.messages.map((message) => {
          const opened = openedBy.get(message.id)
          const interp = message.run_id ? interpretationByRun.get(message.run_id) : undefined
          return (
            <div key={message.id}>
              <MessageItem
                caseId={caseId}
                message={message}
                messages={conv.messages}
                docs={docs}
                connected={connected(ownerOf(message.artifact_id, message.artifact_rev))}
                questionSummary={
                  message.question_id
                    ? latestIntent?.questions.find((q) => q.id === message.question_id)?.summary ?? null
                    : null
                }
              />
              {message.run_id && (
                <KnowledgeCards
                  registrations={(conv.knowledge_registrations ?? []).filter((r) => r.run_id === message.run_id)}
                  projectId={props.project.id}
                  caseId={caseId}
                  onChanged={props.onChanged}
                />
              )}
              {interp && (interp.kind === 'work_request' || interp.report_status === 'invalid') && (
                <p className="sh-system-line" data-testid="interpretation-line">
                  AI 해석:{' '}
                  {interp.kind === 'work_request'
                    ? `업무 요청(${PROFILE_LABEL[interp.profile ?? ''] ?? interp.profile ?? '?'})`
                    : '형식이 맞지 않음'}
                  {interp.applied
                    ? ' → 같은 대화에서 업무로 전환'
                    : interp.refusal
                      ? ` → 전환하지 않음(${INTERPRETATION_REFUSAL_LABEL[interp.refusal] ?? interp.refusal})`
                      : ''}
                </p>
              )}
              {conv.work_start?.request_message_id === message.id && (
                <WorkStartCard conv={conv} basisSeq={message.seq} />
              )}
              {opened && opened.id !== current?.id && <RequestOutcome request={opened} />}
            </div>
          )
        })}
        <RelationCards relations={conv.relations ?? []} projectId={props.project.id} />
      </div>

      <div className="sh-bottom">
        {current && (
          <RequestProgress
            caseId={caseId}
            request={current}
            auto={conv.processing?.auto ?? false}
            onChanged={props.onChanged}
          />
        )}
        <WaitCards
          conv={conv}
          detail={detail}
          caseId={caseId}
          projectId={props.project.id}
          runnerId={conv.send.runner_connection.runner_id}
          onChanged={props.onChanged}
        />
        {openQuestions.length > 0 && latestIntent && (
          <div className="sh-cards" data-testid="question-cards">
            {openQuestions.map((question) => (
              <QuestionCard
                key={question.id}
                caseId={caseId}
                question={question}
                intentVersionId={latestIntent.id}
                intentRevision={latestIntent.revision}
                allowed={conv.send.card_answer.allowed}
                refusal={conv.send.card_answer.refusal}
                runnerId={conv.send.runner_connection.runner_id}
                onChanged={props.onChanged}
              />
            ))}
          </div>
        )}
        <Composer
          caseId={caseId}
          conv={conv}
          detail={detail}
          project={props.project}
          runners={props.runners}
          onChanged={props.onChanged}
        />
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ 단계 안내

function StageBanner(props: { conv: ConversationData }) {
  const { conv } = props
  if (conv.stage === 'discussion' && conv.processing && !conv.processing.auto) {
    return (
      <div className="sh-banner sh-info">
        이 제어부는 요청을 자동으로 처리하지 않는다(요청 처리기 꺼짐). 응답은 관리 화면에서 만든다.
      </div>
    )
  }
  return null
}

// 진행 카드가 쓰는 서버 상태 표시(업무 단계). 값은 서버가 준 그대로다.
export function stageSummary(detail: ShellCaseDetail | null): string {
  if (!detail) return ''
  return [
    AGREEMENT_LABEL[detail.intent_state?.agreement_state] ?? detail.intent_state?.agreement_state,
    `QG-01 ${GATE_VERDICT_LABEL[detail.gate.verdict] ?? detail.gate.verdict}`,
    `상태 ${CASE_STATUS_LABEL[detail.status] ?? detail.status}`,
  ].join(' · ')
}

function WorkStartCard(props: { conv: ConversationData; basisSeq: number }) {
  const work = props.conv.work_start as
    | (NonNullable<ConversationData['work_start']> & {
        interpretation_run_id?: string | null
        started_at?: string
        actor?: string
      })
    | null
  if (!work) return null
  return (
    <div className="sh-card sh-card-event" data-testid="work-start-card">
      <strong>업무로 전환됨</strong> · {PROFILE_LABEL[work.profile] ?? work.profile}
      <div className="sh-muted">
        결정 주체: {work.decided_by === 'ai_interpretation' ? 'AI 해석(사용자 메시지를 근거로)' : '사람'}
        {work.started_at ? ` · ${time(work.started_at)}` : ''} · 위임 근거: 메시지 #{props.basisSeq} 원문. 논의
        중의 동의·금지·소비는 그대로 이어진다.
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ 메시지

function MessageItem(props: {
  caseId: string
  message: ConversationMessage
  messages: ConversationMessage[]
  docs: ResultDoc[]
  connected: boolean
  questionSummary: string | null
}) {
  const { message } = props
  const options: BodyOptions = {
    connected: props.connected,
    availability: receiptAvailability(message.receipt),
  }
  const body = useBody(message.artifact_id, message.artifact_rev, options)
  const assistant = message.author === 'assistant'
  const split = body.status === 'loaded' && assistant ? splitRunOutput(body.text ?? '') : null
  const text = assistant ? split?.message : body.text
  const corrects = message.corrects_message_id
    ? props.messages.find((m) => m.id === message.corrects_message_id)
    : null
  const canCorrect =
    !assistant && message.message_kind !== 'card_answer' && body.status === 'loaded'

  return (
    <article
      className={assistant ? 'sh-message sh-message-ai' : 'sh-message sh-message-user'}
      data-testid={`message-${message.seq}`}
      data-author={message.author}
    >
      <div className="sh-message-meta">
        <span>{assistant ? 'AI' : '나'}</span>
        {message.message_kind === 'correction' && <span className="sh-badge sh-badge-plain">정정 · #{corrects?.seq ?? '?'} 을 고침</span>}
        {message.message_kind === 'card_answer' && (
          <span className="sh-badge sh-badge-plain">질문 답변{props.questionSummary ? ` · ${props.questionSummary}` : ''}</span>
        )}
        {message.corrected_by.length > 0 && <span className="sh-badge sh-badge-plain">정정됨</span>}
        {message.receipt !== 'stored' && (
          <span className="sh-badge sh-badge-warn" data-testid="receipt-badge">
            {RECEIPT_LABEL[message.receipt]}
          </span>
        )}
        <span className="sh-muted">#{message.seq} · {time(message.created_at)}</span>
      </div>
      {body.status === 'loaded' ? (
        <div className="sh-message-body" data-testid="message-body">
          {text}
        </div>
      ) : (
        <div className="sh-message-body sh-body-placeholder" data-testid="message-body-state" data-status={body.status}>
          {BODY_STATUS_LABEL[body.status]}
          {body.detail ? ` — ${body.detail}` : ''}
          {(body.status === 'failed' || body.status === 'expired') && (
            <button
              type="button"
              className="sh-link"
              onClick={() => retryBody(message.artifact_id, message.artifact_rev, options)}
            >
              다시 불러오기
            </button>
          )}
        </div>
      )}
      {message.references.length > 0 && (
        <ul className="sh-chips">
          {message.references.map((ref, index) => (
            <ReferenceChip key={index} caseId={props.caseId} refData={ref} docs={props.docs} />
          ))}
        </ul>
      )}
      <div className="sh-message-actions">
        {split?.header && (
          <details className="sh-run-info">
            <summary>실행 정보</summary>
            <pre>{split.header}</pre>
          </details>
        )}
        {canCorrect && (
          <button
            type="button"
            className="sh-link"
            onClick={() =>
              emit('hads:correct', {
                caseId: props.caseId,
                messageId: message.id,
                seq: message.seq,
                text: body.text ?? '',
              })
            }
          >
            수정해서 다시 요청
          </button>
        )}
      </div>
    </article>
  )
}

function ReferenceChip(props: { caseId: string; refData: Record<string, unknown>; docs: ResultDoc[] }) {
  const ref = props.refData
  if (ref.ref_kind === 'artifact' && typeof ref.artifact_id === 'string') {
    const target = { artifact_id: ref.artifact_id, revision: Number(ref.artifact_rev ?? 1) }
    const found = findDocFor(props.docs, target)
    const stale = found ? !isLatest(found.doc, target) : false
    return (
      <li className="sh-chip">
        <button
          type="button"
          className="sh-link"
          onClick={() => emit('hads:open-ref', { caseId: props.caseId, ref: target })}
          title="이 메시지가 가리킨 버전을 연다"
        >
          {found ? `${found.doc.title} ${found.version.label}` : `산출물 ${target.artifact_id.slice(0, 12)} r${target.revision}`}
        </button>
        {typeof ref.location === 'string' && ` · ${ref.location}`}
        {stale && <span className="sh-badge sh-badge-warn">최신 아님</span>}
      </li>
    )
  }
  return (
    <li className="sh-chip">
      파일 {String(ref.path ?? '')}
      {typeof ref.location === 'string' && ` · ${ref.location}`}
    </li>
  )
}

// ------------------------------------------------------------------ 요청

function runSentence(run: RequestRun): string {
  const purpose = PURPOSE_LABEL[run.purpose ?? ''] ?? run.purpose ?? '목적 미기록'
  if (run.execution_state === 'executing') {
    return run.purpose === 'discussion_reply' ? 'AI 가 답을 쓰는 중' : `${purpose} 실행 중`
  }
  return `${purpose} · ${RUN_EXECUTION_LABEL[run.execution_state]}`
}

function RequestProgress(props: {
  caseId: string
  request: ConversationRequest
  auto: boolean
  onChanged: () => void
}) {
  const { request } = props
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
    setBusy(false)
    props.onChanged()
  }
  let headline: string
  if (request.state === 'unknown') {
    headline = '실행 상태 확인 필요 — 관련 실행이 실제로 끝났는지 확인하기 전에는 새 요청을 받지 않는다'
  } else if (request.stopping) {
    headline = '중단 요청 중 — 관련 실행이 실제로 끝난 것을 확인하면 다시 보낼 수 있다'
  } else if (request.runs.length === 0) {
    headline =
      request.opening_receipt !== 'stored'
        ? '메시지 접수 대기 — PC 가 원문을 저장하면 처리를 시작한다'
        : request.origin && request.origin !== 'user_message'
          ? '다음 작업을 준비하는 중(작업공간 등)'
          : props.auto
            ? '응답 준비 중'
            : '처리하는 쪽이 아직 응답을 만들지 않았다(자동 처리 꺼짐)'
  } else {
    headline = request.runs.map(runSentence).join(' · ')
  }
  // P4-05. 시스템이 연 진행 요청은 "누구의 결정 뒤에 이어 가는가"를 보인다.
  const originText =
    request.origin === 'human_decision'
      ? '사람의 결정 뒤 자동 진행'
      : request.origin === 'system_resume'
        ? '계속 진행 뒤 자동 진행'
        : null
  return (
    <div className={`sh-progress sh-progress-${request.state}`} data-testid="request-progress" data-state={request.state}>
      <div className="sh-progress-line">
        <span className="sh-progress-state">{REQUEST_STATE_LABEL[request.state]}</span>
        <span data-testid="progress-headline">
          {originText ? `${originText} · ` : ''}
          {headline}
        </span>
        <span className="sh-spacer" />
        {request.state === 'processing' && !request.stopping && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void act(() => conversationApi.stop(props.caseId, request.id, ''))}
            data-testid="stop-button"
          >
            중단
          </button>
        )}
        {request.state === 'unknown' && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void act(() => conversationApi.reconcile(props.caseId, request.id))}
          >
            상태 다시 확인
          </button>
        )}
      </div>
      {error && <p className="sh-error-text">{error}</p>}
      <details className="sh-progress-detail">
        <summary>실행 세부</summary>
        <ul>
          {request.runs.map((run) => (
            <li key={run.run_id} className="sh-mono">
              {run.run_id} · {PURPOSE_LABEL[run.purpose ?? ''] ?? run.purpose} · {RUN_EXECUTION_LABEL[run.execution_state]}
              {run.outcome ? ` · 결과 ${run.outcome}` : ''}
              {run.not_started_reason ? ` · 시작하지 않음(${run.not_started_reason})` : ''}
              {` · 잔류 ${run.residual_observed ?? run.residual_activity}`}
              {run.residual_basis ? `(${run.residual_basis})` : ''}
            </li>
          ))}
        </ul>
        {request.interruption_summary && <p>{request.interruption_summary.detail}</p>}
      </details>
    </div>
  )
}

function RequestOutcome(props: { request: ConversationRequest }) {
  const { request } = props
  if (request.state === 'completed' || request.state === 'processing') return null
  const summary = request.interruption_summary
  return (
    <p className={`sh-system-line sh-outcome-${request.state}`} data-testid="request-outcome">
      {REQUEST_STATE_LABEL[request.state]}
      {request.note_summary ? ` · ${request.note_summary}` : ''}
      {request.outcome_reason && request.outcome_reason !== 'settled' ? ` · ${request.outcome_reason}` : ''}
      {summary
        ? ` · 실행 ${summary.runs}건, 시작하지 않음 ${summary.not_started.length}, 결과 모름 ${summary.result_unknown.length}` +
          (summary.workspace_changed_by.length ? `, 작업공간을 바꾼 실행 ${summary.workspace_changed_by.length}` : '') +
          ' — 만든 결과·사용량은 남아 있다(취소·되돌림이 아니다)'
        : ''}
    </p>
  )
}

// ------------------------------------------------------------------ 질문 카드

const DECIDE_AT_LABEL: Record<string, string> = {
  intent: '의도 단계에서 정한다',
  design: '설계 단계에서 정한다',
  plan: '계획 단계에서 정한다',
}

function QuestionCard(props: {
  caseId: string
  question: IntentQuestion
  intentVersionId: string
  intentRevision: number
  allowed: boolean
  refusal: string | null
  runnerId: string | null
  onChanged: () => void
}) {
  const key = cardDraftKey(props.caseId, props.question.id)
  const initial = useRef(load(store, key, 'card_answer'))
  const [draft, setDraft] = useState<Draft>(initial.current.draft)
  const [notice, setNotice] = useState<string | null>(
    initial.current.restored ? '복구한 답변 초안 — 자동으로 보내지 않는다' : null,
  )
  const [sending, setSending] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => save(store, key, draft), 300)
    return () => clearTimeout(timer)
  }, [draft, key])

  useEffect(() => {
    const pending = initial.current.draft.pending
    if (!pending) return
    void checkReceipt(props.caseId, pending.clientId).then((outcome) =>
      setDraft((d) => settle(d, pending.clientId, outcome, new Date().toISOString())),
    )
  }, [props.caseId])

  const send = async () => {
    if (!props.allowed || !props.runnerId || !draft.content.text.trim() || sending) return
    const now = new Date().toISOString()
    const started = beginSend(draft, () => newClientId(randomId), now)
    setDraft(started.draft)
    save(store, key, started.draft)
    setSending(true)
    const result = await sendAndConfirm(props.caseId, {
      client_message_id: started.clientId,
      kind: 'card_answer',
      content: started.draft.content.text,
      summary: `질문 답변 · ${started.draft.content.text.length}자`,
      target_runner_id: props.runnerId,
      question_id: props.question.id,
      // **카드가 보인 의도 버전**. 그 사이 새 버전이 생기면 서버가 거부한다.
      intent_version_id: props.intentVersionId,
    })
    setSending(false)
    setDraft((d) => settle(d, started.clientId, result.outcome, new Date().toISOString()))
    setNotice(
      result.outcome === 'stored'
        ? '답변 접수됨 — 이 질문의 답일 뿐이며 의도 동의나 권한 확대가 아니다'
        : result.outcome === 'refused'
          ? `보내지 못했다: ${refusalText(result.refusals, result.detail)}`
          : result.outcome === 'waiting'
            ? '접수 여부를 아직 모른다 — 답변 초안을 남겼다'
            : '접수되지 않았다 — 답변 초안을 남겼다',
    )
    props.onChanged()
  }

  return (
    <div className="sh-card sh-card-question" data-testid={`question-card-${props.question.question_key}`}>
      <div className="sh-card-head">
        <strong>질문</strong> · {props.question.summary}
      </div>
      <div className="sh-muted">
        {DECIDE_AT_LABEL[props.question.decide_at] ?? props.question.decide_at} · 의도 v{props.intentRevision}의 질문
        · 답은 이 질문에만 적용된다(동의·권한이 아니다)
      </div>
      <textarea
        className="sh-input"
        rows={2}
        value={draft.content.text}
        placeholder="직접 입력해 답한다 — 질문의 전문은 결과물 패널의 의도 원문에 있다"
        onChange={(e) =>
          setDraft((d) => edit(d, { ...d.content, text: e.target.value }, new Date().toISOString()))
        }
      />
      <div className="sh-composer-bar">
        {!props.allowed && (
          <span className="sh-notice sh-notice-warn">
            지금은 답할 수 없다{props.refusal ? `: ${CONVERSATION_REFUSAL_LABEL[props.refusal] ?? props.refusal}` : ''}
          </span>
        )}
        {notice && <span className="sh-notice sh-notice-info">{notice}</span>}
        <span className="sh-spacer" />
        <button
          type="button"
          className="sh-primary"
          disabled={!props.allowed || !props.runnerId || !draft.content.text.trim() || sending}
          onClick={() => void send()}
        >
          {sending ? '보내는 중…' : '답변 보내기'}
        </button>
      </div>
    </div>
  )
}
