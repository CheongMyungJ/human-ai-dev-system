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
  INTERPRETATION_REFUSAL_LABEL,
  PROFILE_LABEL,
  PROGRESS_ACTION_LABEL,
  PROGRESS_STEP_LABEL,
  type ConversationView,
  type PreparationArtifact,
  type RunnerWithConnection,
} from '../api'
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
        {detail && props.tab === 'decisions' && <Decisions conv={props.conv} detail={detail} />}
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

// ------------------------------------------------------------------ 결정 사항

function Decisions(props: { conv: ConversationView | null; detail: ShellCaseDetail }) {
  const { conv, detail } = props
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
  const empty =
    !work && answered.length === 0 && detail.decisions.length === 0 && interpretations.length === 0 && events.length === 0
  return (
    <div data-testid="decisions">
      {empty && <p className="sh-muted">아직 기록된 결정이 없다. 논의 중의 동의는 그 선택에만 적용된다.</p>}
      {work && (
        <section>
          <h3 className="sh-section-title">업무화</h3>
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
      {detail.decisions.length > 0 && (
        <section>
          <h3 className="sh-section-title">기록된 결정</h3>
          <ul className="sh-result-list">
            {detail.decisions.map((d) => (
              <li key={d.id} className="sh-plain-row">
                {d.kind} · 대상 {d.subject_type} r{d.subject_revision} · {d.actor} · {d.decided_at.slice(0, 16)}
              </li>
            ))}
          </ul>
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
        프로젝트 공통 규칙·지식은 이후 작업(P4-06·UI-04)이다. 여기에는 이 대화의 기록만 있다.
      </p>
    </div>
  )
}
