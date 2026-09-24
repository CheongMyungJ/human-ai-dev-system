// 오른쪽 검토 패널(D-71·D-72·D-80·D-85·D-89). `결과물`·`결정 사항`·`설정`(UI-04b 상세 설정)을 누를 때만 열린다.
//
//   **실제로 있는 것만 보인다.** 산출물이 없으면 빈 탭을 만들지 않는다.
//   **열람 버전을 고정한다.** 새 버전이 생기면 안내하고, 비교·전환은 사람이 고른다. 이미 쓴 참조는
//   원래 버전에 남는다.
//   **요약만 본 것을 원문을 읽은 것으로 바꾸지 않는다.** 원문은 사람이 열 때 PC 에서 불러온다(의도
//   원문 전달은 열람 기록을 남긴다).
//   **코드 diff 본문은 작업 PC 에 있다.** 이 화면은 요약과 작업 PC·경로만 보이고 diff 열람·폴더 열기는
//   지원하지 않는다고 말한다.

import { useEffect, useMemo, useState } from 'react'

import {
  ApiError,
  CONVERSATION_REFUSAL_LABEL,
  CRITERIA_MAPPING_LABEL,
  CRITERION_VERDICT_LABEL,
  DECISION_KIND_LABEL,
  INTERPRETATION_REFUSAL_LABEL,
  KNOWLEDGE_KIND_LABEL,
  KNOWLEDGE_STATE_LABEL,
  knowledgeApi,
  OBLIGATION_LABEL,
  obligationLabel,
  OPEN_STATE_LABEL,
  OPEN_SUPPORT_LABEL,
  PROFILE_LABEL,
  PROFILE_PRIMARY_OBLIGATION,
  PROFILE_SOURCE_LABEL,
  profileRevisionApi,
  PROGRESS_ACTION_LABEL,
  PROGRESS_STEP_LABEL,
  START_BASIS_LABEL,
  WORKSPACE_STATE_LABEL,
  workspaceApi,
  type CaseKnowledgeUse,
  type ConversationView,
  type KnowledgeRegistration,
  type PreparationArtifact,
  type ProfileRevisionsView,
  type ProjectRepository,
  type RepositoryWorkspace,
  type RunnerWithConnection,
} from '../api'
import { rulesLink } from '../lib/address'
import { splitRunOutput } from '../lib/runOutput'
import { diffLines } from '../lib/textDiff'
import {
  buildResultDocs,
  isLatest,
  latestVersion,
  newerVersions,
  openLatest,
  openRef,
  versionIndex,
  type DocVersion,
  type ResultDoc,
  type VersionRef,
  type ViewerState,
} from '../lib/versions'
import { BODY_STATUS_LABEL, retryBody, useBody, type BodyOptions } from './bodies'
import { CaseSettings } from './CaseSettings'
import { emit } from './events'
import type { ShellCaseDetail } from './useCaseData'

export type PanelTab = 'results' | 'decisions' | 'settings'

function pretty(kind: ResultDoc['kind'], text: string): string {
  if (kind === 'run_output') return splitRunOutput(text).message
  const trimmed = text.trim()
  if (trimmed.startsWith('{')) {
    try {
      return JSON.stringify(JSON.parse(trimmed), null, 2)
    } catch {
      return text
    }
  }
  return text
}

export function ReviewPanel(props: {
  caseId: string
  projectId: string
  tab: PanelTab
  conv: ConversationView | null
  detail: ShellCaseDetail | null
  preparations: PreparationArtifact[]
  runners: RunnerWithConnection[]
  openRequest: { ref: VersionRef; nonce: number } | null
  // UI-04b. 상세 설정 탭이 쓴다 — 등록 저장소 목록과 변경 뒤 다시 읽기.
  repositories: ProjectRepository[]
  onChanged: () => void
  onTab: (tab: PanelTab) => void
  onClose: () => void
}) {
  const { detail } = props
  const docs = useMemo(
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
  const [viewer, setViewer] = useState<ViewerState | null>(null)

  // 메시지의 참조로 열면 **그 버전**이다.
  useEffect(() => {
    if (!props.openRequest) return
    const opened = openRef(docs, props.openRequest.ref)
    if (opened) setViewer(opened)
    // 목록이 아직 없으면 목록이 올 때 다시 본다(같은 요청이므로 한 번만 연다).
  }, [props.openRequest, docs.length > 0])

  const doc = viewer ? docs.find((d) => d.key === viewer.docKey) ?? null : null

  return (
    <aside className="sh-panel" data-testid="review-panel">
      <div className="sh-panel-head">
        <button
          type="button"
          className={props.tab === 'results' ? 'sh-tab sh-tab-on' : 'sh-tab'}
          onClick={() => props.onTab('results')}
        >
          결과물
        </button>
        <button
          type="button"
          className={props.tab === 'decisions' ? 'sh-tab sh-tab-on' : 'sh-tab'}
          onClick={() => props.onTab('decisions')}
        >
          결정 사항
        </button>
        <button
          type="button"
          className={props.tab === 'settings' ? 'sh-tab sh-tab-on' : 'sh-tab'}
          onClick={() => props.onTab('settings')}
          data-testid="panel-tab-settings"
        >
          설정
        </button>
        <span className="sh-spacer" />
        <button type="button" className="sh-icon-button" title="패널 닫기" onClick={props.onClose}>
          ×
        </button>
      </div>
      <div className="sh-panel-body">
        {!detail && <p className="sh-muted">불러오는 중</p>}
        {detail && props.tab === 'results' && (
          <>
            {viewer && doc ? (
              <Viewer
                caseId={props.caseId}
                doc={doc}
                viewer={viewer}
                runners={props.runners}
                detail={detail}
                onPin={(pinned) => setViewer({ docKey: doc.key, pinned })}
                onBack={() => setViewer(null)}
              />
            ) : (
              <ResultList docs={docs} detail={detail} runners={props.runners} conv={props.conv} onOpen={(d) => setViewer(openLatest(d))} />
            )}
          </>
        )}
        {detail && props.tab === 'decisions' && (
          <Decisions conv={props.conv} detail={detail} caseId={props.caseId} projectId={props.projectId} />
        )}
        {detail && props.tab === 'settings' && (
          <CaseSettings
            caseId={props.caseId}
            projectId={props.projectId}
            detail={detail}
            repositories={props.repositories}
            onChanged={props.onChanged}
          />
        )}
      </div>
    </aside>
  )
}

// ------------------------------------------------- 업무 · 목적·유형 개정 (D-86)

function WorkSection(props: {
  conv: ConversationView | null
  work: { profile: string; decided_by: string; started_at?: string } | null
  basisKind: string | null
  caseId: string
  focus: (seq: number) => void
  closed: boolean
  stamp: string
}) {
  const { conv, work } = props
  const current = conv?.profile ?? work?.profile ?? null
  const revisions = conv?.profile_revisions ?? []
  // 대응 목록(승계/재검사)은 개정 조회에 있다 — 개정이 있을 때만 읽는다.
  const [view, setView] = useState<ProfileRevisionsView | null>(null)
  useEffect(() => {
    if (revisions.length === 0) {
      setView(null)
      return
    }
    let stopped = false
    void profileRevisionApi
      .get(props.caseId)
      .then((next) => {
        if (!stopped) setView(next)
      })
      .catch(() => {
        if (!stopped) setView(null)
      })
    return () => {
      stopped = true
    }
  }, [props.caseId, revisions.length, props.stamp])
  const mappings = new Map((view?.revisions ?? []).map((r) => [r.id, r.criteria_mapping ?? []]))

  const [profile, setProfile] = useState<string>(current ?? 'defect_fix')
  const [objectives, setObjectives] = useState<string[]>([])
  const [keep, setKeep] = useState(true)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const submit = async () => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await profileRevisionApi.revise(props.caseId, profile, objectives, keep, reason.trim())
      setNotice('개정을 기록했다 — 진행기가 의도를 새 버전으로 다시 쓰고, 그 버전은 동의를 기다린다')
      setReason('')
      setObjectives([])
    } catch (err) {
      setError(describeApiError(err))
    } finally {
      setBusy(false)
    }
  }
  const previousObligations = current ? PROFILE_PRIMARY_OBLIGATION[current] ?? [] : []
  return (
    <section data-testid="decisions-work" data-profile={current ?? ''}>
      <h3 className="sh-section-title">업무</h3>
      <p>
        지금 <strong data-testid="decisions-current-profile">{current ? PROFILE_LABEL[current] ?? current : '—'}</strong>
        {conv?.profile_source ? ` · ${PROFILE_SOURCE_LABEL[conv.profile_source] ?? conv.profile_source}` : ''}
        {work && (
          <>
            {' '}· 처음 {PROFILE_LABEL[work.profile] ?? work.profile} · 결정 주체{' '}
            {work.decided_by === 'ai_interpretation' ? 'AI 해석' : '사람'}
            {work.started_at ? ` · ${work.started_at.replace('T', ' ').slice(0, 16)}` : ''}
          </>
        )}
      </p>
      {props.basisKind && (
        <p className="sh-muted">위임 근거: 사용자 메시지 원문({props.basisKind}) — AI 해석 글이 근거가 아니다. 개정도 근거를 바꾸지 않는다</p>
      )}
      {(view?.carried_objectives?.length ?? 0) > 0 && (
        <p className="sh-muted" data-testid="decisions-carried">
          계속 충족해야 하는 이전 목적: {view!.carried_objectives.map((o) => obligationLabel(o)).join(', ')} · 유지 항목{' '}
          {view!.retained_fields.length}건
        </p>
      )}
      {revisions.length > 0 && (
        <ul className="sh-result-list" data-testid="profile-revisions">
          {revisions.map((r) => {
            const mapping = mappings.get(r.id) ?? []
            return (
              <li key={r.id} className="sh-plain-row" data-testid={`profile-revision-${r.revision}`}>
                <strong>개정 {r.revision}</strong> · {PROFILE_LABEL[r.from_profile] ?? r.from_profile} → {PROFILE_LABEL[r.to_profile] ?? r.to_profile}
                {r.carried_objectives.length > 0 && ` · 이전 목적 유지: ${r.carried_objectives.map((o) => obligationLabel(o)).join(', ')}`}
                {r.added_objectives.length > 0 && ` · 추가 목적: ${r.added_objectives.map((o) => obligationLabel(o)).join(', ')}`}
                {' '}· {r.decided_by === 'ai_interpretation' ? 'AI 해석(사용자 메시지를 근거로)' : '사람'} · {r.created_at.replace('T', ' ').slice(0, 16)}
                {r.request_message_seq !== null && (
                  <>
                    {' '}·{' '}
                    <button type="button" className="sh-link" onClick={() => props.focus(r.request_message_seq!)}>
                      근거 메시지 #{r.request_message_seq}
                    </button>
                  </>
                )}
                {r.reason_summary && <div className="sh-muted">사유: {r.reason_summary}</div>}
                {mapping.length > 0 && (
                  <ul className="sh-result-list" data-testid={`revision-mapping-${r.revision}`}>
                    {mapping.map((m) => (
                      <li key={m.key} className="sh-muted" data-state={m.state}>
                        {m.key} · {m.summary ?? ''} · {obligationLabel(m.obligation)} →{' '}
                        {CRITERIA_MAPPING_LABEL[m.state] ?? m.state}
                        {m.after ? ` (${CRITERION_VERDICT_LABEL[m.after.verdict as keyof typeof CRITERION_VERDICT_LABEL] ?? m.after.verdict ?? ''})` : ''}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            )
          })}
        </ul>
      )}
      {props.closed ? (
        <p className="sh-muted">종료된 업무 — 목적 확장·수정은 연결된 새 대화로 한다(D-33·D-78)</p>
      ) : current ? (
        <div className="sh-form" data-testid="profile-revision-form">
          <p className="sh-muted">
            목적·유형 변경(D-86): 같은 대화에서 의도·Profile 을 새 버전으로 개정한다. 이전 기준·판정·결정·소비는 그대로이고,
            새 의도 버전은 검토·동의를 다시 지난다. 권한·동의·인수가 아니다 — 제품 쓰기는 진입 검사가 그대로 본다.
          </p>
          <label>
            바꿀 유형{' '}
            <select value={profile} onChange={(e) => setProfile(e.target.value)} data-testid="revision-profile">
              {Object.entries(PROFILE_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <div className="sh-muted">
            추가 목적:{' '}
            {Object.entries(OBLIGATION_LABEL).map(([value, label]) => (
              <label key={value} className="sh-inline-check">
                <input
                  type="checkbox"
                  checked={objectives.includes(value)}
                  onChange={(e) => setObjectives((prev) => (e.target.checked ? [...prev, value] : prev.filter((o) => o !== value)))}
                  data-testid={`revision-objective-${value}`}
                />{' '}
                {label}
              </label>
            ))}
          </div>
          <label className="sh-inline-check">
            <input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} data-testid="revision-keep" /> 이전 목적 유지
            {previousObligations.length > 0 && ` (${previousObligations.map((o) => obligationLabel(o)).join(', ')} — 끄면 유형 정정이다)`}
          </label>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="사유(필수) — 사용자의 말이나 결정"
            data-testid="revision-reason"
          />
          <button type="button" disabled={busy || !reason.trim()} onClick={() => void submit()} data-testid="revision-submit">
            개정 기록
          </button>
          {error && <p className="sh-warn" data-testid="revision-refusal">거부: {error}</p>}
          {notice && <p className="sh-muted" data-testid="revision-notice">{notice}</p>}
        </div>
      ) : null}
    </section>
  )
}

// ------------------------------------------------------ 작업공간 · 작업 PC (D-89)

function describeApiError(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = err.detail as { refusals?: string[]; message?: string } | string | undefined
    if (detail && typeof detail === 'object' && Array.isArray(detail.refusals) && detail.refusals.length) {
      return detail.refusals.map((r) => CONVERSATION_REFUSAL_LABEL[r] ?? r).join(', ')
    }
    if (detail && typeof detail === 'object' && typeof detail.message === 'string') return detail.message
    return typeof detail === 'string' ? detail : err.message
  }
  return err instanceof Error ? err.message : String(err)
}

function WorkspaceRow(props: { caseId: string; ws: RepositoryWorkspace; runners: RunnerWithConnection[] }) {
  const { ws } = props
  const [error, setError] = useState<string | null>(null)
  const [sent, setSent] = useState<string | null>(null)
  // 작업 PC 는 **이 작업공간을 만든 Runner** 다 — 대화의 연결 PC 가 아니다. 서버가 실어 준 값이 정본이고,
  // 없으면(옛 작업공간) 목록에서 같은 id 를 찾아 본다.
  const fromList = props.runners.find((r) => r.id === ws.runner_id)
  const host = ws.runner?.host ?? fromList?.host ?? null
  const connection = ws.runner?.connection?.state ?? fromList?.connection?.state ?? null
  const connected = connection === 'connected'
  const support = ws.open_support
  const canOpen = (target: 'folder' | 'editor') =>
    connected && support?.[target === 'folder' ? 'open_folder' : 'open_editor']?.state === 'verified'
  const supportText = (target: 'folder' | 'editor') => {
    const row = support?.[target === 'folder' ? 'open_folder' : 'open_editor']
    if (!row) return OPEN_SUPPORT_LABEL.unknown
    return `${OPEN_SUPPORT_LABEL[row.state] ?? row.state} — ${row.source}`
  }
  const latest = ws.open_requests?.[0] ?? null
  const open = async (target: 'folder' | 'editor') => {
    setError(null)
    setSent(null)
    try {
      const request = await workspaceApi.open(props.caseId, ws.repository_id, target)
      setSent(`${target === 'folder' ? '폴더' : '편집기'} 열기 요청을 작업 PC 에 남겼다(${request.id.slice(0, 12)}) — 결과는 아래에`)
    } catch (err) {
      setError(describeApiError(err))
    }
  }
  // UI-04d(D-77). 시작 기준 — 서버 값 그대로. NULL 은 "기록 없음"(옛 작업공간·아직 안 정함)이지 커밋된 코드가 아니다.
  const basisText = (() => {
    if (ws.state === 'awaiting_basis') return '시작 기준 선택 대기 — 대화의 카드에서 고른다(아직 만들어지지 않음)'
    if (ws.start_basis === 'include_uncommitted') {
      return `${START_BASIS_LABEL.include_uncommitted} — ${ws.included_entries ?? '?'}건, 스냅샷 ${ws.base_commit.slice(0, 10)} (커밋 기준 ${(ws.committed_base ?? '').slice(0, 10) || '?'})`
    }
    if (ws.start_basis === 'committed') return `${START_BASIS_LABEL.committed} ${ws.base_commit.slice(0, 10)}`
    return ws.base_commit ? `기준 커밋 ${ws.base_commit.slice(0, 10)} · 시작 기준 기록 없음(옛 작업공간)` : '아직 만들어지지 않음'
  })()
  return (
    <div className="sh-plain-row" data-testid={`workspace-${ws.repository_id}`} data-connection={connection ?? 'unknown'}>
      <div>
        <strong>{ws.repository_name}</strong> · {ws.branch} · {WORKSPACE_STATE_LABEL[ws.state] ?? ws.state} · 작업 PC{' '}
        <span data-testid={`ws-runner-${ws.repository_id}`}>
          {host ?? (ws.runner_id ? ws.runner_id : '기록 없음')}
          {connection ? ` (${connected ? '연결됨' : connection})` : ''}
        </span>
      </div>
      <div className="sh-muted" data-testid={`ws-basis-${ws.repository_id}`} data-basis={ws.start_basis ?? ''}>
        시작 코드: {basisText}
        {ws.user_tree_dirty && ws.start_basis === 'committed' && ' · 원래 폴더의 미커밋 변경은 그대로 남았다(포함하지 않음)'}
      </div>
      <div>
        경로 <span className="sh-mono" data-testid={`ws-path-${ws.repository_id}`}>{ws.worktree_path}</span>{' '}
        <button
          type="button"
          className="sh-link"
          onClick={() => void navigator.clipboard?.writeText(ws.worktree_path)}
          data-testid={`ws-copy-${ws.repository_id}`}
        >
          경로 복사
        </button>
      </div>
      <div className="sh-rule-actions">
        <button
          type="button"
          disabled={!canOpen('folder')}
          onClick={() => void open('folder')}
          data-testid={`ws-open-folder-${ws.repository_id}`}
          title={supportText('folder')}
        >
          작업 PC 에서 폴더 열기
        </button>
        <button
          type="button"
          disabled={!canOpen('editor')}
          onClick={() => void open('editor')}
          data-testid={`ws-open-editor-${ws.repository_id}`}
          title={supportText('editor')}
        >
          편집기(VS Code) 열기
        </button>
      </div>
      <p className="sh-muted" data-testid={`ws-open-support-${ws.repository_id}`}>
        폴더: {supportText('folder')} · 편집기: {supportText('editor')}
        {!connected && ' · 작업 PC 가 연결돼 있지 않아 열 수 없다'}
      </p>
      {sent && <p className="sh-muted">{sent}</p>}
      {error && <p className="sh-warn" data-testid={`ws-open-error-${ws.repository_id}`}>열기 요청 거부: {error}</p>}
      {latest && (
        <p className="sh-muted" data-testid={`ws-open-result-${ws.repository_id}`} data-state={latest.state}>
          최근 열기 요청({latest.target === 'folder' ? '폴더' : '편집기'}, {latest.requested_at.replace('T', ' ').slice(0, 19)}):{' '}
          {OPEN_STATE_LABEL[latest.state] ?? latest.state}
          {latest.result_reason ? ` — ${latest.result_reason}` : ''}
        </p>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ 목록

function ResultList(props: {
  docs: ResultDoc[]
  detail: ShellCaseDetail
  runners: RunnerWithConnection[]
  conv: ConversationView | null
  onOpen: (doc: ResultDoc) => void
}) {
  const { detail } = props
  const changedRuns = detail.runs.filter((run) => run.workspace_effect)
  const verificationRuns = detail.runs.filter((run) => run.purpose === 'verification_run')
  const criteria = detail.result?.criteria ?? []
  const workspaces = detail.workspace?.workspaces ?? []
  const effectRows = new Map(
    workspaces.flatMap((ws) => ws.run_effects.map((row) => [row.run_id, row] as const)),
  )
  const nothing =
    props.docs.length === 0 &&
    changedRuns.length === 0 &&
    verificationRuns.length === 0 &&
    criteria.length === 0 &&
    workspaces.length === 0
  return (
    <div data-testid="result-list">
      {nothing && (
        <p className="sh-muted">
          아직 결과물이 없다. 논의 응답은 대화에 있다. 문서·코드 변경·검증이 생기면 여기에 나타난다.
        </p>
      )}
      {props.docs.length > 0 && (
        <section>
          <h3 className="sh-section-title">문서·실행 출력</h3>
          <ul className="sh-result-list">
            {props.docs.map((doc) => {
              const latest = latestVersion(doc)
              return (
                <li key={doc.key}>
                  <button type="button" className="sh-row" onClick={() => props.onOpen(doc)} data-testid={`result-${doc.key}`}>
                    <span className="sh-row-title">{doc.title}</span>
                    <span className="sh-muted">
                      {doc.kind === 'run_output' ? latest.label : `최신 ${latest.label} · 버전 ${doc.versions.length}`}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </section>
      )}
      {changedRuns.length > 0 && (
        <section data-testid="code-changes">
          <h3 className="sh-section-title">코드 변경</h3>
          <ul className="sh-result-list">
            {changedRuns.map((run) => {
              const effect = run.workspace_effect!
              const row = effectRows.get(run.run_id)
              const external = row?.external_change_before_run ?? effect.external_change_before_run ?? null
              return (
                <li key={run.run_id} className="sh-plain-row" data-testid={`effect-${run.run_id}`} data-external={String(external)}>
                  {run.run_id} · {effect.changed ? '변경 있음' : '이 실행이 바꾼 것 없음'} · 기준 대비 누적 파일{' '}
                  {effect.files_changed} (+{effect.insertions} −{effect.deletions})
                  {external === true && (
                    <span className="sh-warn" data-testid={`effect-external-${run.run_id}`}>
                      {' '}· 직전 실행 뒤 외부 변경이 있었다 — 보존됨(되돌리지 않음), 이 실행의 입력이 됐다
                    </span>
                  )}
                  {external === false && <span className="sh-muted"> · 직전 실행 뒤 외부 변경 없음</span>}
                  {external === null && row?.unexpected_external_change && (
                    <span className="sh-warn"> · 직전 실행이 남긴 상태와 다른 자리에서 시작했다(되돌리지 않음)</span>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      )}
      {workspaces.length > 0 && (
        <section data-testid="workspaces">
          <h3 className="sh-section-title">작업공간 · 작업 PC</h3>
          {workspaces.map((ws) => (
            <WorkspaceRow key={ws.repository_id} caseId={detail.id} ws={ws} runners={props.runners} />
          ))}
          <p className="sh-muted">
            직접 편집은 외부 편집기로 한다(D-89). 변경 내용(diff) 본문은 작업 PC 에 있고 이 화면의 diff 열람은 없다.
            열기는 지원을 확인한 작업 PC 에서만 되며 브라우저 PC 와 같다고 가정하지 않는다. 외부 편집은 다음 쓰기
            실행 전에 확인·보존된다(되돌리지 않음). 열기는 쓰기 허용·동의가 아니다.
          </p>
        </section>
      )}
      {(verificationRuns.length > 0 || criteria.length > 0) && (
        <section data-testid="verification">
          <h3 className="sh-section-title">검증</h3>
          <ul className="sh-result-list">
            {verificationRuns.map((run) => (
              <li key={run.run_id} className="sh-plain-row">
                검증 실행 {run.run_id} · {run.status}
                {run.outcome ? ` · ${run.outcome}` : ''}
              </li>
            ))}
            {criteria.map((criterion) => {
              const c = criterion as unknown as { id: string; summary: string; verdict?: string; result?: { verdict?: string } }
              const verdict = c.result?.verdict ?? c.verdict ?? 'unverified'
              return (
                <li key={c.id} className="sh-plain-row">
                  기준 · {c.summary} ·{' '}
                  <strong>{CRITERION_VERDICT_LABEL[verdict as keyof typeof CRITERION_VERDICT_LABEL] ?? verdict}</strong>
                </li>
              )
            })}
          </ul>
        </section>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ 열람기

function Viewer(props: {
  caseId: string
  doc: ResultDoc
  viewer: ViewerState
  runners: RunnerWithConnection[]
  detail: ShellCaseDetail
  onPin: (ref: VersionRef) => void
  onBack: () => void
}) {
  const { doc, viewer } = props
  const index = versionIndex(doc, viewer.pinned)
  const version: DocVersion | null = index >= 0 ? doc.versions[index] : null
  const newer = newerVersions(doc, viewer.pinned)
  const latest = latestVersion(doc)
  const [showDiff, setShowDiff] = useState(false)
  const [location, setLocation] = useState('')
  const [attached, setAttached] = useState(false)

  const artifactOf = (ref: VersionRef) =>
    props.detail.artifacts.find((a) => a.artifact_id === ref.artifact_id && a.revision === ref.revision)
  const optionsFor = (ref: VersionRef): BodyOptions => {
    const artifact = artifactOf(ref)
    const owner = artifact?.owner_runner_id
    const runner = props.runners.find((r) => r.id === owner)
    return {
      connected: runner ? runner.connection.state === 'connected' : false,
      availability: artifact?.availability ?? 'available',
    }
  }
  const pinnedOptions = optionsFor(viewer.pinned)
  const body = useBody(viewer.pinned.artifact_id, viewer.pinned.revision, pinnedOptions)
  const latestOptions = optionsFor(latest)
  const latestBody = useBody(latest.artifact_id, latest.revision, { ...latestOptions, enabled: showDiff })

  const diff = useMemo(() => {
    if (!showDiff || body.status !== 'loaded' || latestBody.status !== 'loaded') return null
    return diffLines(pretty(doc.kind, body.text ?? ''), pretty(doc.kind, latestBody.text ?? ''))
  }, [showDiff, body, latestBody, doc.kind])

  return (
    <div className="sh-viewer" data-testid="viewer">
      <div className="sh-viewer-head">
        <button type="button" className="sh-link" onClick={props.onBack}>
          ← 목록
        </button>
        <strong data-testid="viewer-title">
          {doc.title} {version?.label ?? '(목록에 없는 버전)'}
        </strong>
        {version && isLatest(doc, version) && <span className="sh-badge sh-badge-plain">최신</span>}
      </div>
      {newer.length > 0 && (
        <div className="sh-banner sh-info" data-testid="newer-version">
          읽는 동안 새 버전 {newer.map((v) => v.label).join(', ')} 이 생겼다. 본문은 {version?.label} 그대로다 —
          이 버전에 남긴 의견은 이 버전에 연결된 채 남는다.{' '}
          <button type="button" className="sh-link" onClick={() => setShowDiff((v) => !v)} data-testid="show-diff">
            {showDiff ? '비교 닫기' : '변경 내용 보기'}
          </button>{' '}
          <button
            type="button"
            className="sh-link"
            onClick={() => {
              setShowDiff(false)
              props.onPin({ artifact_id: latest.artifact_id, revision: latest.revision })
            }}
            data-testid="switch-latest"
          >
            최신 {latest.label} 로 전환
          </button>
        </div>
      )}
      {doc.versions.length > 1 && (
        <div className="sh-versions">
          버전:{' '}
          {doc.versions.map((v) => (
            <button
              key={`${v.artifact_id}@${v.revision}`}
              type="button"
              className={v === version ? 'sh-tab sh-tab-on' : 'sh-tab'}
              onClick={() => props.onPin({ artifact_id: v.artifact_id, revision: v.revision })}
            >
              {v.label}
            </button>
          ))}
        </div>
      )}
      {showDiff ? (
        <div className="sh-diff" data-testid="diff">
          {!diff && <p className="sh-muted">두 버전을 불러오는 중 — {BODY_STATUS_LABEL[latestBody.status]}</p>}
          {diff?.tooLarge && <p className="sh-muted">너무 커서 비교하지 않았다(같다는 뜻이 아니다).</p>}
          {diff && !diff.tooLarge && (
            <>
              <p className="sh-muted">
                {version?.label} → {latest.label}: 추가 {diff.added}줄 · 삭제 {diff.removed}줄
              </p>
              <pre>
                {diff.lines.map((line, i) => (
                  <div key={i} className={`sh-diff-${line.op}`}>
                    {line.op === 'added' ? '+ ' : line.op === 'removed' ? '- ' : '  '}
                    {line.text}
                  </div>
                ))}
              </pre>
            </>
          )}
        </div>
      ) : body.status === 'loaded' ? (
        <pre className="sh-doc" data-testid="viewer-body">
          {pretty(doc.kind, body.text ?? '')}
        </pre>
      ) : (
        <p className="sh-muted" data-testid="viewer-body-state" data-status={body.status}>
          {BODY_STATUS_LABEL[body.status]}
          {body.detail ? ` — ${body.detail}` : ''}
          {(body.status === 'failed' || body.status === 'expired') && (
            <button
              type="button"
              className="sh-link"
              onClick={() => retryBody(viewer.pinned.artifact_id, viewer.pinned.revision, pinnedOptions)}
            >
              다시 불러오기
            </button>
          )}
        </p>
      )}
      {version && (
        <div className="sh-attach">
          <input
            value={location}
            placeholder="위치 표시(선택, 예: 범위 항목·12-18행)"
            onChange={(e) => setLocation(e.target.value)}
          />
          <button
            type="button"
            onClick={() => {
              emit('hads:attach-ref', {
                caseId: props.caseId,
                ref: {
                  kind: 'artifact',
                  artifact_id: version.artifact_id,
                  revision: version.revision,
                  ...(location.trim() ? { location: location.trim() } : {}),
                  label: `${doc.title} ${version.label}`,
                },
              })
              setAttached(true)
              setLocation('')
            }}
            data-testid="attach-ref"
          >
            대화에 참조
          </button>
          {attached && <span className="sh-muted">입력창 초안에 붙였다 — 보낼 때 서버가 버전을 고정한다</span>}
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ 결정 사항 (UI-03 → UI-04a, D-80)
//
// 이 대화의 **목표·기준·결정**과 여기서 정한 프로젝트 규칙·후보, 이 업무에 적용된 규칙을 **보고 이동**하는
// 자리다. 값은 전부 서버 것이고 없으면 절을 만들지 않는다. 규칙의 변경(활성화·개정)은 프로젝트 규칙 화면에서
// 한다. 의도 본문(목표·범위·제약)은 PC 원문이라 여기 적지 않는다 — 결과물 패널이 연다.

const AGREEMENT_LABEL: Record<string, string> = {
  no_intent: '의도 초안 없음',
  never_agreed: '의도 동의 전',
  stale_agreement: '동의 이후 의도가 바뀜',
  agreed_current: '의도 동의됨',
}

const ORIGIN_LABEL: Record<string, string> = {
  statement: '이 대화에서 한 말(AI 가 옮겨 활성 등록)',
  proposal: 'AI 제안(후보)',
  extraction: '실행이 남긴 후보',
}

const PURPOSE_SHORT: Record<string, string> = {
  discussion_reply: '논의 응답',
  intent_authoring: '의도 초안',
  intent_gate_review: 'QG-01',
  quality_gate_review: '게이트 검토',
  limited_analysis: '분석',
  design_authoring: '설계',
  plan_authoring: '계획',
  feature_implementation: '구현',
  verification_run: '검증',
  local_experiment: '실험',
}

function registrationSeq(r: KnowledgeRegistration): number | null {
  return r.source_message_seq ?? r.reply_seq ?? null
}

function Decisions(props: { conv: ConversationView | null; detail: ShellCaseDetail; caseId: string; projectId: string }) {
  const { conv, detail, caseId, projectId } = props
  const work = conv?.work_start as
    | (NonNullable<ConversationView['work_start']> & { started_at?: string; interpretation_run_id?: string | null })
    | null
  const answered = detail.intent_versions.flatMap((iv) =>
    ((iv as unknown as { questions?: { id: string; summary: string; state: string; answered_at: string | null }[] })
      .questions ?? [])
      .filter((q) => q.state === 'answered')
      .map((q) => ({ ...q, revision: iv.revision })),
  )
  const interpretations = conv?.interpretations ?? []
  const basis = detail.policy?.delegation_basis.current
  const events = conv?.progress?.events ?? []
  const latest = detail.intent_state?.latest_intent_version ?? null
  const criteria = (detail.result?.criteria ?? []) as unknown as {
    id: string
    summary: string
    verdict?: string
    result?: { verdict?: string }
  }[]
  const registrations = conv?.knowledge_registrations ?? []
  const messagesByArtifact = new Map((conv?.messages ?? []).map((m) => [m.artifact_id, m.seq]))
  const intentById = new Map(detail.intent_versions.map((iv) => [iv.id, iv]))

  // 이 업무에 적용된 규칙(Manifest 집계). 패널을 열 때 한 번, 진행 상태·실행 수가 바뀌면 다시.
  const [use, setUse] = useState<CaseKnowledgeUse | null>(null)
  const useStamp = `${conv?.progress?.updated_at ?? ''}|${detail.runs.length}|${registrations.length}`
  useEffect(() => {
    let stopped = false
    void knowledgeApi
      .caseUse(caseId)
      .then((next) => {
        if (!stopped) setUse(next)
      })
      .catch(() => {
        if (!stopped) setUse(null)
      })
    return () => {
      stopped = true
    }
  }, [caseId, useStamp])

  const focus = (seq: number) => emit('hads:focus-message', { caseId, seq })
  const openIntent = (artifactId: string, revision: number) =>
    emit('hads:open-ref', { caseId, ref: { artifact_id: artifactId, revision } })

  const empty =
    !work &&
    !latest &&
    answered.length === 0 &&
    detail.decisions.length === 0 &&
    interpretations.length === 0 &&
    events.length === 0 &&
    registrations.length === 0 &&
    (use?.items.length ?? 0) === 0
  return (
    <div data-testid="decisions">
      {empty && <p className="sh-muted">아직 기록된 결정이 없다. 논의 중의 동의는 그 선택에만 적용된다.</p>}
      {(work || conv?.profile) && (
        <WorkSection
          conv={conv}
          work={work}
          basisKind={basis?.basis_kind ?? null}
          caseId={caseId}
          focus={focus}
          closed={['closed', 'cancelled'].includes(conv?.status ?? '')}
          stamp={useStamp}
        />
      )}
      {latest && (
        <section data-testid="decisions-goal">
          <h3 className="sh-section-title">목표·기준</h3>
          <p>
            의도 v{latest.revision} · {latest.status} ·{' '}
            {AGREEMENT_LABEL[detail.intent_state?.agreement_state ?? ''] ?? detail.intent_state?.agreement_state}
            {latest.authoring_mode ? ` · ${latest.authoring_mode === 'ai_drafted' ? 'AI 초안' : '사람이 씀'}` : ''}{' '}
            <button
              type="button"
              className="sh-link"
              onClick={() => openIntent(latest.artifact_id, (latest as { artifact_rev?: number }).artifact_rev ?? 1)}
              data-testid="decisions-open-intent"
            >
              원문 열기
            </button>
          </p>
          <p className="sh-muted">목표·범위·제약의 본문은 PC 의 의도 원문에 있다 — 여기에는 서버가 아는 버전·동의·기준만 있다.</p>
          {criteria.length > 0 && (
            <ul className="sh-result-list">
              {criteria.map((c) => {
                const verdict = c.result?.verdict ?? c.verdict ?? 'unverified'
                return (
                  <li key={c.id} className="sh-plain-row">
                    기준 · {c.summary} ·{' '}
                    <strong>{CRITERION_VERDICT_LABEL[verdict as keyof typeof CRITERION_VERDICT_LABEL] ?? verdict}</strong>
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      )}
      {detail.decisions.length > 0 && (
        <section data-testid="decisions-list">
          <h3 className="sh-section-title">결정</h3>
          <ul className="sh-result-list">
            {detail.decisions.map((d) => {
              const intent = d.subject_type === 'intent_version' ? intentById.get(d.subject_id) ?? null : null
              const evidenceSeq = d.evidence_ref ? messagesByArtifact.get(d.evidence_ref) ?? null : null
              return (
                <li key={d.id} className="sh-plain-row" data-testid={`decision-${d.kind}`}>
                  <strong>{DECISION_KIND_LABEL[d.kind] ?? d.kind}</strong> · 대상{' '}
                  {intent ? (
                    <button
                      type="button"
                      className="sh-link"
                      onClick={() => openIntent(intent.artifact_id, (intent as { artifact_rev?: number }).artifact_rev ?? 1)}
                    >
                      의도 v{intent.revision}
                    </button>
                  ) : (
                    `${d.subject_type} ${d.subject_id.slice(0, 12)} r${d.subject_revision}`
                  )}{' '}
                  · {d.actor} · {d.decided_at.replace('T', ' ').slice(0, 16)}
                  {evidenceSeq !== null && (
                    <>
                      {' '}
                      ·{' '}
                      <button type="button" className="sh-link" onClick={() => focus(evidenceSeq)}>
                        근거 메시지 #{evidenceSeq}
                      </button>
                    </>
                  )}
                  {' '}· 이 버전에만 적용된다
                </li>
              )
            })}
          </ul>
        </section>
      )}
      {registrations.length > 0 && (
        <section data-testid="decisions-knowledge">
          <h3 className="sh-section-title">이 대화에서 정한 프로젝트 규칙·후보</h3>
          <ul className="sh-result-list">
            {registrations.map((r) => {
              const seq = registrationSeq(r)
              const key = r.intake_state === 'evidence' ? r.evidence?.knowledge_key ?? null : r.knowledge_key
              return (
                <li
                  key={`${r.run_id}-${r.report_index}`}
                  className="sh-plain-row"
                  data-testid={key ? `decisions-rule-${key}` : `decisions-rule-refused-${r.report_index}`}
                  data-state={r.intake_state === 'registered' ? r.current_state ?? r.state ?? '' : r.intake_state}
                >
                  {r.intake_state === 'registered' && (
                    <>
                      <strong>{r.knowledge_key}</strong> v{r.version} · 지금{' '}
                      {KNOWLEDGE_STATE_LABEL[r.current_state ?? r.state ?? 'active']}
                      {r.current_version && r.current_version !== r.version ? ` v${r.current_version}` : ''} ·{' '}
                      {r.obligation === 'required' ? '필수' : '참고'} · {KNOWLEDGE_KIND_LABEL[r.kind ?? 'constraint']} · {r.summary}
                      <div className="sh-muted">{ORIGIN_LABEL[r.origin ?? 'statement']}</div>
                    </>
                  )}
                  {r.intake_state === 'evidence' && r.evidence && (
                    <>
                      <strong>{r.evidence.knowledge_key}</strong> 의 근거로 이음 ·{' '}
                      {r.evidence.kind === 'supports' ? '뒷받침하는 관측' : '같은 내용'} · {r.reported_summary ?? ''}
                    </>
                  )}
                  {r.intake_state === 'refused' && <>등록하지 않음 · {r.reported_summary ?? ''} · {r.refusal ?? ''}</>}
                  <div className="sh-muted">
                    {seq !== null && (
                      <>
                        <button type="button" className="sh-link" onClick={() => focus(seq)} data-testid={key ? `decisions-rule-message-${key}` : undefined}>
                          메시지 #{seq}
                        </button>{' '}
                        ·{' '}
                      </>
                    )}
                    {r.run_id && seq === null ? `실행 ${r.run_id} · ` : ''}
                    {key && (
                      <a className="sh-link" href={rulesLink(projectId, key)} data-testid={`decisions-rule-open-${key}`}>
                        프로젝트 규칙에서 보기
                      </a>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
          <p className="sh-muted">활성화·개정은 프로젝트 규칙 화면에서, 무효화는 대화의 카드에서 한다. 등록은 실행 권한이 아니다.</p>
        </section>
      )}
      {use && (use.items.length > 0 || use.runs_unrecorded > 0) && (
        <section data-testid="decisions-applied">
          <h3 className="sh-section-title">이 업무에 적용된 프로젝트 규칙</h3>
          <p className="sh-muted">{use.note}</p>
          <ul className="sh-result-list">
            {use.items.map((item) => {
              const skipped = Object.entries(item.skipped)
              return (
                <li key={item.version_id} className="sh-plain-row" data-testid={`applied-${item.knowledge_key}`} data-provided={item.provided_runs}>
                  <strong>{item.knowledge_key}</strong> v{item.version} · {item.obligation === 'required' ? '필수' : '참고'} ·{' '}
                  {KNOWLEDGE_STATE_LABEL[item.state]}
                  {item.state_now !== item.state ? `(지금 ${KNOWLEDGE_STATE_LABEL[item.state_now]})` : ''} · {item.summary}
                  <div className="sh-muted">
                    제공 실행 {item.provided_runs}
                    {item.last_run_id
                      ? ` · 마지막 ${PURPOSE_SHORT[item.last_run_purpose ?? ''] ?? item.last_run_purpose ?? ''} ${item.last_run_id}`
                      : ''}
                    {skipped.length ? ` · 넣지 않음 ${skipped.map(([code, n]) => `${code} ${n}`).join(', ')}` : ''}
                  </div>
                </li>
              )
            })}
          </ul>
          {use.runs_unrecorded > 0 && (
            <p className="sh-muted">Manifest 기록 전 실행 {use.runs_unrecorded}(지식 없음이 아니다 — P4-06 이전 실행)</p>
          )}
        </section>
      )}
      {answered.length > 0 && (
        <section>
          <h3 className="sh-section-title">답한 질문</h3>
          <ul className="sh-result-list">
            {answered.map((q) => (
              <li key={q.id} className="sh-plain-row">
                의도 v{q.revision} · {q.summary} · 답함 {q.answered_at?.slice(0, 16)}
              </li>
            ))}
          </ul>
        </section>
      )}
      {interpretations.length > 0 && (
        <section>
          <h3 className="sh-section-title">AI 해석 기록</h3>
          <ul className="sh-result-list">
            {interpretations.map((i) => (
              <li key={i.run_id} className="sh-plain-row">
                {i.run_id} ·{' '}
                {i.report_status !== 'reported'
                  ? i.report_status === 'missing'
                    ? '해석 없음'
                    : '형식 오류'
                  : i.kind === 'work_request'
                    ? `업무 요청(${PROFILE_LABEL[i.profile ?? ''] ?? i.profile})`
                    : '논의'}
                {i.applied ? ' · 업무화 적용' : i.refusal ? ` · 적용 안 함(${INTERPRETATION_REFUSAL_LABEL[i.refusal] ?? i.refusal})` : ''}
              </li>
            ))}
          </ul>
        </section>
      )}
      {events.length > 0 && (
        <section data-testid="progress-events">
          <h3 className="sh-section-title">진행 이력</h3>
          <ul className="sh-result-list">
            {events.map((e) => (
              <li key={e.id} className="sh-plain-row">
                {e.at.slice(11, 19)} · {PROGRESS_STEP_LABEL[e.step] ?? e.step} · {PROGRESS_ACTION_LABEL[e.action] ?? e.action}
                {e.detail ? ` · ${e.detail}` : ''}
                {e.run_id ? ` · ${e.run_id}` : ''}
              </li>
            ))}
          </ul>
        </section>
      )}
      <p className="sh-muted">
        여기에는 이 대화의 기록만 있다. 프로젝트 공통 규칙은{' '}
        <a className="sh-link" href={rulesLink(projectId)} data-testid="decisions-open-rules">
          프로젝트 규칙 화면
        </a>
        에서 확인·변경한다.
      </p>
    </div>
  )
}
