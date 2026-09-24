// 오른쪽 검토 패널(D-71·D-80·D-85·D-89). `결과물`·`결정 사항`을 누를 때만 열린다.
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
  CRITERION_VERDICT_LABEL,
  DECISION_KIND_LABEL,
  INTERPRETATION_REFUSAL_LABEL,
  KNOWLEDGE_KIND_LABEL,
  KNOWLEDGE_STATE_LABEL,
  knowledgeApi,
  PROFILE_LABEL,
  PROGRESS_ACTION_LABEL,
  PROGRESS_STEP_LABEL,
  type CaseKnowledgeUse,
  type ConversationView,
  type KnowledgeRegistration,
  type PreparationArtifact,
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
import { emit } from './events'
import type { ShellCaseDetail } from './useCaseData'

export type PanelTab = 'results' | 'decisions'

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
      </div>
    </aside>
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
  const runner = props.runners.find((r) => r.id === props.conv?.send.runner_connection.runner_id)
  const nothing =
    props.docs.length === 0 && changedRuns.length === 0 && verificationRuns.length === 0 && criteria.length === 0
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
              return (
                <li key={run.run_id} className="sh-plain-row">
                  {run.run_id} · {effect.changed ? '변경 있음' : '이 실행이 바꾼 것 없음'} · 기준 대비 누적 파일{' '}
                  {effect.files_changed} (+{effect.insertions} −{effect.deletions})
                </li>
              )
            })}
          </ul>
          {workspaces.map((ws) => (
            <p key={ws.repository_id} className="sh-muted">
              작업 PC {runner?.host ?? '미상'} · {ws.repository_name} · {ws.branch} ·{' '}
              <span className="sh-mono">{ws.worktree_path}</span>{' '}
              <button
                type="button"
                className="sh-link"
                onClick={() => void navigator.clipboard?.writeText(ws.worktree_path)}
              >
                경로 복사
              </button>
            </p>
          ))}
          <p className="sh-muted">
            변경 내용(diff) 본문은 작업 PC 에 있다. 이 화면의 diff 열람과 작업 PC 폴더·편집기 열기는 아직
            지원하지 않는다 — 경로를 복사해 외부 편집기로 연다.
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
      {work && (
        <section>
          <h3 className="sh-section-title">업무</h3>
          <p>
            {PROFILE_LABEL[work.profile] ?? work.profile} · 결정 주체{' '}
            {work.decided_by === 'ai_interpretation' ? 'AI 해석' : '사람'}
            {work.started_at ? ` · ${work.started_at.replace('T', ' ').slice(0, 16)}` : ''}
          </p>
          {basis && (
            <p className="sh-muted">
              위임 근거: 사용자 메시지 원문({basis.basis_kind}) — AI 해석 글이 근거가 아니다
            </p>
          )}
        </section>
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
