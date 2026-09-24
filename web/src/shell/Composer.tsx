// 공통 입력창(D-70·D-72·D-81·D-83).
//
//   **보낼 수 있는지는 서버가 말한다**(`send.general`). 버튼이 꺼져도 입력·참조 편집은 된다.
//   **초안은 이 브라우저에 자동 저장된다.** 접수가 확인된(`stored`) 전송분만 비우고, 보낸 뒤 고친
//   내용은 남긴다. 거부·유실·응답 없음에는 그대로 남는다. **자동으로 보내지 않는다.**
//   **초안 저장과 메시지 접수를 구별한다.** 저장 실패는 저장됨으로 보이지 않는다.

import { useEffect, useRef, useState } from 'react'

import {
  CONVERSATION_REFUSAL_LABEL,
  metricLabel,
  shellApi,
  type ConversationView,
  type MessageReferenceInput,
  type ProjectRepository,
  type ProjectWithAttention,
  type RunnerWithConnection,
} from '../api'
import {
  addRef,
  beginSend,
  draftKey,
  edit,
  load,
  newClientId,
  save,
  settle,
  type Draft,
  type DraftRef,
  type SendOutcome,
} from '../lib/drafts'
import { browserStore } from '../lib/prefs'
import { emit, listen } from './events'
import { checkReceipt, sendAndConfirm } from './send'
import type { ShellCaseDetail } from './useCaseData'

const store = browserStore()

export function randomId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function now(): string {
  return new Date().toISOString()
}

export function refusalText(codes: string[], fallback?: string | null): string {
  if (codes.length === 0) return fallback ?? '서버가 거부했다'
  return codes.map((code) => CONVERSATION_REFUSAL_LABEL[code] ?? code).join(' · ')
}

function toServerRef(ref: DraftRef): MessageReferenceInput {
  const { label: _label, ...rest } = ref
  return rest
}

const OUTCOME_NOTICE: Record<Exclude<SendOutcome, 'waiting'>, string> = {
  stored: '메시지 접수됨 — PC 가 원문을 저장했다',
  lost_before_persist: '저장 전에 유실됐다 — 입력은 그대로 있다. 다시 보내면 새 전송이다',
  not_received: '서버가 받지 않았다 — 입력은 그대로 있다. 직접 다시 보낸다',
  refused: '보내지 못했다',
}

export function Composer(props: {
  caseId: string
  conv: ConversationView
  detail: ShellCaseDetail | null
  project: ProjectWithAttention
  runners: RunnerWithConnection[]
  onChanged: () => void
}) {
  const { caseId, conv } = props
  const key = draftKey(caseId)
  const initial = useRef(load(store, key))
  const [draft, setDraft] = useState<Draft>(initial.current.draft)
  // 저장소가 없으면(차단·사생활 모드) 처음부터 "저장하지 못함"이다 — 저장됨으로 보이지 않는다.
  const [saveState, setSaveState] = useState<'clean' | 'saved' | 'failed'>(
    store === null ? 'failed' : 'clean',
  )
  const [notice, setNotice] = useState<{ text: string; tone: 'ok' | 'warn' | 'info' } | null>(
    initial.current.restored
      ? { text: '이 브라우저에 남아 있던 초안을 복구했다 — 자동으로 보내지 않는다', tone: 'info' }
      : initial.current.error
        ? { text: `초안을 복구하지 못했다: ${initial.current.error}`, tone: 'warn' }
        : null,
  )
  const [sending, setSending] = useState(false)
  const [chosenRunner, setChosenRunner] = useState<string>('')
  const [showFileRef, setShowFileRef] = useState(false)
  const [repositories, setRepositories] = useState<ProjectRepository[]>([])
  const [fileRef, setFileRef] = useState({ repository_id: '', path: '', location: '' })
  const firstSave = useRef(true)
  // 마지막으로 **실제로 저장한** 초안. 지금 초안이 이것과 다르면 아직 저장되지 않았다 — 앞선
  // 저장의 "저장됨" 표시가 새 편집 위에 남지 않게 렌더 때 바로 비교한다.
  const lastSaved = useRef<Draft>(initial.current.draft)

  // ------------------------------------------------------------ 자동 저장
  useEffect(() => {
    if (firstSave.current) {
      firstSave.current = false
      return
    }
    const timer = setTimeout(() => {
      const ok = save(store, key, draft)
      if (ok) lastSaved.current = draft
      setSaveState(ok ? 'saved' : 'failed')
    }, 300)
    return () => clearTimeout(timer)
  }, [draft, key])

  // 보냄 기록이 남아 있으면(응답을 못 받았거나 새로 고침) **대조만** 한다. 다시 보내지 않는다.
  useEffect(() => {
    const pending = initial.current.draft.pending
    if (!pending) return
    let cancelled = false
    void checkReceipt(caseId, pending.clientId).then((outcome) => {
      if (cancelled) return
      setDraft((d) => settle(d, pending.clientId, outcome, now()))
      if (outcome === 'waiting') {
        setNotice({ text: '앞서 보낸 메시지가 아직 접수 대기다(PC 저장 전) — 초안은 지우지 않았다', tone: 'info' })
      } else {
        setNotice({ text: OUTCOME_NOTICE[outcome], tone: outcome === 'stored' ? 'ok' : 'warn' })
      }
    })
    return () => {
      cancelled = true
    }
  }, [caseId])

  // 결과물 패널의 `대화에 참조`, 메시지의 `수정해서 다시 요청`.
  useEffect(
    () =>
      listen('hads:attach-ref', (detail) => {
        if (detail.caseId === caseId) setDraft((d) => addRef(d, detail.ref, now()))
      }),
    [caseId],
  )
  useEffect(
    () =>
      listen('hads:correct', (detail) => {
        if (detail.caseId !== caseId) return
        setDraft((d) =>
          edit(d, { ...d.content, kind: 'correction', correctsMessageId: detail.messageId, text: detail.text }, now()),
        )
        setNotice({
          text: `#${detail.seq} 을 정정하는 새 메시지로 보낸다 — 원본과 그 결과는 지워지지 않는다`,
          tone: 'info',
        })
      }),
    [caseId],
  )

  useEffect(() => {
    if (!showFileRef) return
    void shellApi
      .repositories(props.project.id)
      .then((view) => setRepositories(view.repositories))
      .catch(() => setRepositories([]))
  }, [showFileRef, props.project.id])

  // -------------------------------------------------------------- 대상 PC
  const connection = conv.send.runner_connection
  const runnerId = connection.runner_id ?? (chosenRunner || null)
  const general = conv.send.general

  const correctsSeq = draft.content.correctsMessageId
    ? conv.messages.find((m) => m.id === draft.content.correctsMessageId)?.seq
    : undefined

  const canSend =
    general.allowed && !sending && !!runnerId && draft.content.text.trim().length > 0 &&
    (draft.content.kind !== 'correction' || !!draft.content.correctsMessageId)

  const send = async () => {
    if (!canSend || !runnerId) return
    const started = beginSend(draft, () => newClientId(randomId), now())
    setDraft(started.draft)
    save(store, key, started.draft)
    setSending(true)
    setNotice({ text: '보내는 중 — PC 저장을 확인할 때까지 초안을 지우지 않는다', tone: 'info' })
    const content = started.draft.content
    const kind = content.kind === 'correction' ? 'correction' : 'general'
    const result = await sendAndConfirm(caseId, {
      client_message_id: started.clientId,
      kind,
      content: content.text,
      // **본문에서 잘라 내지 않는다.** 요약은 제어부에 남는 표시다(D-51·D-84).
      summary: `${kind === 'correction' ? '정정' : '사용자'} 메시지 · ${content.text.length}자`,
      target_runner_id: runnerId,
      ...(kind === 'correction' && content.correctsMessageId
        ? { corrects_message_id: content.correctsMessageId }
        : {}),
      ...(content.refs.length ? { references: content.refs.map(toServerRef) } : {}),
    })
    setSending(false)
    setDraft((d) => settle(d, started.clientId, result.outcome, now()))
    if (result.outcome === 'waiting') {
      setNotice({
        text: '접수 여부를 아직 모른다 — 초안과 보냄 기록을 남겼다. 다시 열면 대조만 한다(자동 전송 없음)',
        tone: 'warn',
      })
    } else if (result.outcome === 'refused') {
      setNotice({ text: `보내지 못했다: ${refusalText(result.refusals, result.detail)}`, tone: 'warn' })
    } else {
      setNotice({ text: OUTCOME_NOTICE[result.outcome], tone: result.outcome === 'stored' ? 'ok' : 'warn' })
    }
    props.onChanged()
  }

  const removeRef = (index: number) =>
    setDraft((d) => edit(d, { ...d.content, refs: d.content.refs.filter((_, i) => i !== index) }, now()))

  const cancelCorrection = () =>
    setDraft((d) => edit(d, { ...d.content, kind: 'general', correctsMessageId: null }, now()))

  return (
    <div className="sh-composer" data-testid="composer">
      <SettingsSummary
        conv={conv}
        detail={props.detail}
        project={props.project}
        runners={props.runners}
        runnerId={runnerId}
      />
      {general.allowed && general.note === 'explanation_only' && (
        <p className="sh-send-refusal" data-testid="send-note">
          종료된 업무 — 기존 결과·근거의 설명만 답한다. 실제 수정·추가 개발 요청은 연결된 새 대화로 옮겨진다(이 업무는 다시
          열리지 않는다).
        </p>
      )}
      {!general.allowed && (
        <p className="sh-send-refusal" data-testid="send-refusal">
          지금은 보낼 수 없다:{' '}
          {refusalText(general.refusals.length ? general.refusals : general.refusal ? [general.refusal] : [], general.detail)}
          {' '}(작성 중인 입력은 자동으로 보내지지 않는다)
        </p>
      )}
      {!connection.runner_id && (
        <p className="sh-send-refusal">
          이 대화의 원문을 저장할 PC 를 아직 정할 수 없다.{' '}
          <select value={chosenRunner} onChange={(e) => setChosenRunner(e.target.value)}>
            <option value="">PC 선택</option>
            {props.runners.map((r) => (
              <option key={r.id} value={r.id}>
                {r.host} ({r.connection.state})
              </option>
            ))}
          </select>
        </p>
      )}
      {draft.content.kind === 'correction' && (
        <div className="sh-correction">
          #{correctsSeq ?? '?'} 을 정정하는 새 메시지 — 원본과 그 결과는 남는다{' '}
          <button type="button" className="sh-link" onClick={cancelCorrection}>
            정정 취소
          </button>
        </div>
      )}
      {draft.content.refs.length > 0 && (
        <ul className="sh-chips" data-testid="draft-refs">
          {draft.content.refs.map((ref, index) => (
            <li key={`${ref.kind}-${ref.artifact_id ?? ref.path}-${ref.revision ?? ''}-${index}`} className="sh-chip">
              {ref.label}
              {ref.location ? ` · ${ref.location}` : ''}
              <button type="button" aria-label="참조 빼기" onClick={() => removeRef(index)}>
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <textarea
        className="sh-input"
        value={draft.content.text}
        rows={3}
        placeholder="메시지 — 본문은 PC 에 저장되고 서버에는 참조만 남는다 (Ctrl+Enter 로 보내기)"
        onChange={(e) => setDraft((d) => edit(d, { ...d.content, text: e.target.value }, now()))}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault()
            void send()
          }
        }}
        data-testid="composer-input"
      />
      {showFileRef && (
        <div className="sh-file-ref">
          {repositories.length === 0 ? (
            <span className="sh-muted">이 프로젝트에 등록된 저장소가 없다.</span>
          ) : (
            <>
              <select
                value={fileRef.repository_id}
                onChange={(e) => setFileRef({ ...fileRef, repository_id: e.target.value })}
              >
                <option value="">저장소</option>
                {repositories.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
              <input
                value={fileRef.path}
                placeholder="경로 (예: src/app.py)"
                onChange={(e) => setFileRef({ ...fileRef, path: e.target.value })}
              />
              <input
                value={fileRef.location}
                placeholder="위치 (예: 12-18행)"
                onChange={(e) => setFileRef({ ...fileRef, location: e.target.value })}
              />
              <button
                type="button"
                disabled={!fileRef.repository_id || !fileRef.path.trim()}
                onClick={() => {
                  const repo = repositories.find((r) => r.id === fileRef.repository_id)
                  setDraft((d) =>
                    addRef(
                      d,
                      {
                        kind: 'project_file',
                        repository_id: fileRef.repository_id,
                        path: fileRef.path.trim(),
                        ...(fileRef.location.trim() ? { location: fileRef.location.trim() } : {}),
                        label: `${repo?.name ?? '저장소'}:${fileRef.path.trim()}`,
                      },
                      now(),
                    ),
                  )
                  setFileRef({ repository_id: fileRef.repository_id, path: '', location: '' })
                }}
              >
                참조 추가
              </button>
            </>
          )}
        </div>
      )}
      <div className="sh-composer-bar">
        <span className={`sh-save sh-save-${saveState}`} data-testid="draft-state">
          {saveState === 'failed'
            ? '초안을 저장하지 못했다 — 새로 고치면 사라진다'
            : draft !== lastSaved.current
              ? '초안 저장 중…'
              : saveState === 'saved'
                ? '초안 저장됨 · 이 브라우저'
                : draft.pending
                  ? '보냄 기록 있음 · 접수 확인 전'
                  : ' '}
        </span>
        {notice && (
          <span className={`sh-notice sh-notice-${notice.tone}`} data-testid="send-notice">
            {notice.text}
          </span>
        )}
        <span className="sh-spacer" />
        <button
          type="button"
          className="sh-link"
          title="프로젝트 파일 위치를 참조로 붙인다. 이미지·외부 파일 첨부는 지원하지 않는다"
          onClick={() => setShowFileRef((v) => !v)}
        >
          파일 참조
        </button>
        <button
          type="button"
          className="sh-primary"
          disabled={!canSend}
          onClick={() => void send()}
          data-testid="send-button"
        >
          {sending ? '보내는 중…' : '보내기'}
        </button>
      </div>
    </div>
  )
}

const AUTONOMY_LABEL: Record<string, string> = {
  ask_on_decision: '판단이 필요할 때 묻기',
  controlled: '시작·결과 확인(controlled)',
}

// UI-04b. 적용 값의 출처를 사람 말로(D-72 "설정 출처").
const SOURCE_LABEL: Record<string, string> = {
  case_explicit: '이 업무에서 정함',
  project_default: '프로젝트 기본값',
  system_default: '시스템 기본값',
  migrated_unknown: '기록 없음(이행 취급)',
  treatment_controlled: '이행 취급(controlled)',
  case_setting: '이 업무에서 정함',
  project_setting: '프로젝트 기본값',
}

function SettingsSummary(props: {
  conv: ConversationView
  detail: ShellCaseDetail | null
  project: ProjectWithAttention
  runners: RunnerWithConnection[]
  runnerId: string | null
}) {
  const [open, setOpen] = useState(false)
  const policy = props.detail?.policy
  const runner = props.runners.find((r) => r.id === props.runnerId)
  const toolVerified = runner?.capabilities.some(
    (c) =>
      c.tool_id === props.project.default_tool_id &&
      c.capability === 'coding_cli' &&
      c.state === 'verified',
  )
  const budget = policy?.budget
  const activeLimits = budget?.limits.filter((l) => l.state === 'current') ?? []
  const budgetText = !budget
    ? '예산 —'
    : budget.unlimited || activeLimits.length === 0
      ? '예산 한도 없음'
      : `예산 ${activeLimits.map((l) => `${metricLabel(l.metric)} ≤ ${l.limit_value}${l.unit ? ` ${l.unit}` : ''}`).join(', ')}`
  const repos = policy?.repositories
  const repoCount = repos ? repos.selected.length || (repos.implicit_single_repository ? 1 : 0) : null
  const auto = props.conv.processing?.auto
  return (
    <div className="sh-settings-summary" data-testid="settings-summary">
      <button type="button" className="sh-summary-line" onClick={() => setOpen((v) => !v)} data-testid="settings-summary-line">
        <span>
          응답 {props.project.default_tool_id}
          {runner && !toolVerified ? ' (이 PC 에서 확인 안 됨)' : ''}
        </span>
        <span>{auto === undefined ? '' : auto ? 'AI 자동 응답' : '자동 응답 꺼짐'}</span>
        <span>
          {policy ? AUTONOMY_LABEL[policy.effective_autonomy] ?? policy.effective_autonomy : 'Autonomy —'}
          {policy?.is_treatment ? ' · 이행 취급' : ''}
        </span>
        <span>깊이 {policy?.work_depth ?? '미정'}</span>
        <span>{budgetText}</span>
        <span>저장소 {repoCount ?? '—'}</span>
        <span className="sh-muted">{open ? '▾' : '▸'}</span>
      </button>
      {open && policy && (
        <div className="sh-summary-detail">
          <p data-testid="settings-summary-sources">
            적용 값의 출처 — Autonomy: {SOURCE_LABEL[policy.autonomy_source] ?? policy.autonomy_source}
            {policy.autonomy_recorded ? '' : ' (기록 없음)'}
            {policy.is_treatment ? ' · 이행 취급' : ''} · 깊이: 수준 판단 · 완료: {policy.completion_mode} (
            {policy.completion_mode_source})
            {policy.progress_limits
              ? ` · 진행 상한 ${policy.progress_limits.repair_limit.value}/${policy.progress_limits.task_retry_limit.value} (${SOURCE_LABEL[policy.progress_limits.repair_limit.source] ?? policy.progress_limits.repair_limit.source})`
              : ''}
          </p>
          {activeLimits.map((l) => (
            <p key={l.id}>
              {metricLabel(l.metric)} {l.threshold_kind} {l.limit_value} {l.unit} · {l.enforcement} · 설정{' '}
              {l.set_by === 'project_default' ? '프로젝트 기본값' : l.set_by}
            </p>
          ))}
          <p className="sh-muted">
            이 값들은 서버 정책 그대로다. 실행 중인 실행의 고정 입력은 바뀌지 않는다.{' '}
            <button
              type="button"
              className="sh-link"
              onClick={() => emit('hads:open-panel', { caseId: props.conv.case_id, tab: 'settings' })}
              data-testid="open-case-settings"
            >
              상세 설정 열기
            </button>
          </p>
        </div>
      )}
    </div>
  )
}

