// 프로젝트 규칙 화면(UI-04a, D-80). 프로젝트 공통 규칙(지식 등록부)을 **확인·변경**하고 원래 대화·근거로
// 이동하는 자리다. 관리 화면의 지식 패널(P4-06·07)과 같은 API 를 쓴다 — 화면이 판정하지 않는다.
//
//   **등록·활성화·개정·무효는 실행 권한·동의·인수가 아니다.** 주입은 준수의 증거가 아니다.
//   **AI 제안은 후보로만** 들어가고 활성화는 사람의 결정이다(QG-08 채택 확인을 지난다, 자동 활성화 없음).
//   **본문은 누를 때만** 열람 경로로 온다(서버 본문, P4-06b). 화면이 본문을 다른 곳에 두지 않는다.
//   **출처 없는 규칙을 만들지 않는다.** 수동 등록은 출처 대화(이 프로젝트의 대화)를 고른다.

import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  ApiError,
  KNOWLEDGE_ADOPTION_LABEL,
  KNOWLEDGE_AUTHORITY_LABEL,
  KNOWLEDGE_KIND_LABEL,
  KNOWLEDGE_RELATION_LABEL,
  KNOWLEDGE_STATE_LABEL,
  knowledgeApi,
  shellApi,
  type ConversationRow,
  type KnowledgeAdoptionCheck,
  type KnowledgeItemView,
  type KnowledgeKind,
  type KnowledgeObligation,
  type KnowledgeVersion,
  type KnowledgeView,
  type ProjectRepository,
  type ProjectWithAttention,
  type RunnerWithConnection,
} from '../api'
import { messageLink } from '../lib/address'
import { KNOWLEDGE_STORAGE_LABEL, readKnowledgeBody } from '../lib/knowledgeBody'

const RULE_ACTIVITIES = ['intent', 'design', 'plan', 'implementation', 'verification', 'investigation', 'review', 'discussion']

function describe(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = err.detail as { refusals?: string[]; message?: string } | undefined
    if (detail && Array.isArray(detail.refusals) && detail.refusals.length) {
      return `${err.status}: 활성화 거부 — ${detail.refusals.map((c) => KNOWLEDGE_ADOPTION_LABEL[c] ?? c).join(', ')}`
    }
    if (detail && typeof detail === 'object' && typeof detail.message === 'string') return `${err.status}: ${detail.message}`
    return `${err.status}: ${typeof err.detail === 'string' ? err.detail : err.message}`
  }
  return err instanceof Error ? err.message : String(err)
}

function splitList(text: string): string[] {
  return text
    .split(',')
    .map((a) => a.trim())
    .filter(Boolean)
}

function observedLine(version: KnowledgeVersion): string | null {
  const observed = version.observed
  if (!observed) return null
  const where = observed.repository_name ?? observed.repository_id ?? '?'
  const commit = observed.base_commit ? `@${observed.base_commit.slice(0, 7)}` : ''
  const tool = observed.tool_version ? ` · ${observed.tool_version}` : ''
  return `관측: 저장소 ${where}${commit} (Case 브랜치)${tool}`
}

function scopeText(version: KnowledgeVersion): string {
  return version.scope_kind === 'project'
    ? '프로젝트 전체'
    : `저장소 ${version.repository_name ?? version.repository_id ?? '?'}${version.paths.length ? ` · 경로 ${version.paths.join(', ')}` : ''}`
}

type Guard = (fn: () => Promise<unknown>) => Promise<void>

export function ProjectRules(props: {
  project: ProjectWithAttention
  rows: ConversationRow[]
  runners: RunnerWithConnection[]
  focusItem: string | null
  lastCaseId: string | null
  onBack: () => void
}) {
  const { project } = props
  const [view, setView] = useState<KnowledgeView | null>(null)
  const [repositories, setRepositories] = useState<ProjectRepository[]>([])
  const [error, setError] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(props.focusItem ? [props.focusItem] : []))

  const load = useCallback(async () => {
    try {
      const [next, repos] = await Promise.all([
        knowledgeApi.list(project.id),
        shellApi.repositories(project.id).then((v) => v.repositories).catch(() => [] as ProjectRepository[]),
      ])
      setView(next)
      setRepositories(repos)
    } catch (err) {
      setError(describe(err))
    }
  }, [project.id])

  useEffect(() => {
    void load()
  }, [load])

  // 주소의 `item` 이 바뀌면(카드에서 다른 항목으로) 그 항목을 펼친다.
  useEffect(() => {
    if (props.focusItem) setExpanded((prev) => new Set([...prev, props.focusItem as string]))
  }, [props.focusItem])

  const guard: Guard = async (fn) => {
    try {
      setError(null)
      await fn()
    } catch (err) {
      setError(describe(err))
    }
    await load()
  }

  const items = view?.items ?? []
  const live = items.filter((i) => i.current && (i.current.state === 'active' || i.current.state === 'candidate'))
  const required = live.filter((i) => i.current!.state === 'active' && i.current!.obligation === 'required')
  const reference = live.filter((i) => i.current!.state === 'active' && i.current!.obligation === 'reference')
  const candidates = live.filter((i) => i.current!.state === 'candidate')
  const history = items.filter((i) => i.current && (i.current.state === 'superseded' || i.current.state === 'invalid'))
  const toggle = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  const renderSection = (title: string, list: KnowledgeItemView[], testId: string, empty: string) => (
    <section data-testid={testId}>
      <h3 className="sh-section-title">
        {title} · {list.length}
      </h3>
      {list.length === 0 && <p className="sh-muted sh-rule-empty">{empty}</p>}
      <ul className="sh-result-list">
        {list.map((item) => (
          <RuleRow
            key={item.id}
            item={item}
            items={items}
            project={project}
            repositories={repositories}
            rows={props.rows}
            runners={props.runners}
            lastCaseId={props.lastCaseId}
            expanded={expanded.has(item.knowledge_key)}
            onToggle={() => toggle(item.knowledge_key)}
            guard={guard}
          />
        ))}
      </ul>
    </section>
  )

  return (
    <div className="sh-rules" data-testid="rules-screen">
      <header className="sh-header">
        <div className="sh-header-title">
          <h1>프로젝트 규칙 · {project.name}</h1>
          <span className="sh-muted">
            공통 규칙·참고 지식·AI 후보. 등록·활성화·개정·무효는 실행 권한·동의·인수가 아니고, 주입은 준수의 증거가
            아니다. AI 제안은 후보로만 들어가며 활성화는 사람의 결정이다(자동 활성화 없음)
          </span>
        </div>
        <div className="sh-header-actions">
          <button type="button" className="sh-link" onClick={props.onBack} data-testid="rules-back">
            ← 대화로
          </button>
        </div>
      </header>
      <div className="sh-rules-body">
        {error && <div className="sh-banner sh-error" data-testid="rules-error">{error}</div>}
        {!view && !error && <p className="sh-muted">불러오는 중</p>}
        {view && (
          <>
            <p className="sh-muted sh-rules-note" data-testid="rules-note">
              적용 내용(조건·예외)과 대화에서 정한 규칙의 권위 메시지 한 건은 <strong>서버에 저장된다</strong> — 어느 PC 의
              실행에도 주입하기 위해서다. <strong>비밀값(토큰·비밀번호·키)을 적지 말 것.</strong> 옛 원문(PC 에만)은 소유 PC
              가 연결되면 올라온다.
            </p>
            {renderSection('활성 필수 규칙', required, 'rules-required', '활성 필수 규칙이 없다')}
            {renderSection('활성 참고 지식', reference, 'rules-reference', '활성 참고 지식이 없다')}
            {renderSection('후보(AI 제안 — 규칙이 아니다)', candidates, 'rules-candidates', '후보가 없다')}
            <section data-testid="rules-history">
              <button type="button" className="sh-list-toggle" onClick={() => setShowHistory((v) => !v)} data-testid="rules-history-toggle">
                {showHistory ? '▾' : '▸'} 대체·무효 {history.length}
              </button>
              {showHistory && (
                <ul className="sh-result-list">
                  {history.map((item) => (
                    <RuleRow
                      key={item.id}
                      item={item}
                      items={items}
                      project={project}
                      repositories={repositories}
                      rows={props.rows}
                      runners={props.runners}
                      lastCaseId={props.lastCaseId}
                      expanded={expanded.has(item.knowledge_key)}
                      onToggle={() => toggle(item.knowledge_key)}
                      guard={guard}
                    />
                  ))}
                  {history.length === 0 && <li className="sh-muted sh-rule-empty">없다</li>}
                </ul>
              )}
            </section>
            <Conflicts view={view} items={items} guard={guard} projectId={project.id} />
            <RegisterForm
              projectId={project.id}
              rows={props.rows}
              runners={props.runners}
              repositories={repositories}
              lastCaseId={props.lastCaseId}
              guard={guard}
            />
          </>
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ 항목 행

function RuleRow(props: {
  item: KnowledgeItemView
  items: KnowledgeItemView[]
  project: ProjectWithAttention
  repositories: ProjectRepository[]
  rows: ConversationRow[]
  runners: RunnerWithConnection[]
  lastCaseId: string | null
  expanded: boolean
  onToggle: () => void
  guard: Guard
}) {
  const { item, project } = props
  const current = item.current!
  const key = item.knowledge_key
  const [body, setBody] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [asking, setAsking] = useState<'invalidate' | 'revise' | null>(null)
  const evidence = item.evidence ?? []
  const observed = observedLine(current)
  const sourceCase = current.source_case_id
  const sourceTitle = current.source_case_title ?? sourceCase
  const sourceSeq = current.source_message_seq ?? null

  return (
    <li className="sh-rule" data-testid={`rule-${key}`} data-state={current.state} data-obligation={current.obligation}>
      <div className="sh-rule-head">
        <button type="button" className="sh-link sh-rule-toggle" onClick={props.onToggle} data-testid={`rule-toggle-${key}`}>
          {props.expanded ? '▾' : '▸'}
        </button>
        <strong>{key}</strong> v{current.version} · {KNOWLEDGE_STATE_LABEL[current.state]} ·{' '}
        {current.obligation === 'required' ? '필수' : '참고'} · {KNOWLEDGE_KIND_LABEL[current.kind]} · {current.summary}
      </div>
      <div className="sh-muted sh-rule-line">
        {scopeText(current)} · 활동 {current.activities.join(', ') || '모든 작업'} · 권위{' '}
        {KNOWLEDGE_AUTHORITY_LABEL[current.authority_kind] ?? current.authority_kind}
        {current.invalid_reason ? ` · 무효 사유: ${current.invalid_reason}` : ''}
      </div>
      <div className="sh-muted sh-rule-line" data-testid={`rule-source-${key}`}>
        출처:{' '}
        {sourceCase ? (
          <a className="sh-link" href={messageLink(project.id, sourceCase, sourceSeq)} data-testid={`rule-source-link-${key}`}>
            대화 “{sourceTitle}”{sourceSeq ? ` · 메시지 #${sourceSeq}` : ''}
          </a>
        ) : (
          '없음'
        )}
        {sourceSeq ? ' (그 말이 권위 원문이다)' : current.authority_kind === 'ai_proposal' ? ' (AI 제안 — 권위 메시지 없음)' : ''}
      </div>
      {props.expanded && (
        <div className="sh-rule-details" data-testid={`rule-details-${key}`}>
          {(current.relation || observed || current.reason_summary) && (
            <div className="sh-muted sh-rule-line" data-testid={`rule-origin-${key}`}>
              {current.relation && current.relates_to_key
                ? `← ${current.relates_to_key} ${KNOWLEDGE_RELATION_LABEL[current.relation]} · `
                : ''}
              {observed ? `${observed} · ` : ''}
              {current.reason_summary ?? ''}
            </div>
          )}
          {current.adoption && (
            <div className="sh-muted sh-rule-line" data-testid={`rule-adoption-${key}`}>
              채택 확인({current.adoption.by}
              {current.adoption.into ? ` · ${current.adoption.into} 의 새 버전으로` : ''}):{' '}
              {current.adoption.findings.length
                ? current.adoption.findings.map((f) => KNOWLEDGE_ADOPTION_LABEL[f.code] ?? f.code).join(', ')
                : '항목 없음'}{' '}
              · 독립 검토 {current.adoption.independent_review === 'not_run' ? '없음' : current.adoption.independent_review}
            </div>
          )}
          {evidence.length > 0 && (
            <div className="sh-muted sh-rule-line" data-testid={`rule-evidence-${key}`}>
              근거 {evidence.length}건:{' '}
              {evidence.map((e, index) => (
                <span key={e.id}>
                  {index ? ' · ' : ''}
                  {e.kind === 'supports' ? '뒷받침' : '같은 내용'} · {e.summary} · 실행 {e.source_run_id} ·{' '}
                  <a className="sh-link" href={messageLink(project.id, e.source_case_id)}>
                    대화 “{e.source_case_title ?? e.source_case_id}”
                  </a>
                </span>
              ))}
            </div>
          )}
          <div className="sh-muted sh-rule-line" data-testid={`rule-storage-${key}`}>
            내용 {KNOWLEDGE_STORAGE_LABEL[current.storage ?? 'runner']}
            {current.source_storage ? ` · 권위 메시지 ${KNOWLEDGE_STORAGE_LABEL[current.source_storage]}` : ''} ·{' '}
            <code>
              {current.artifact_id}@{current.artifact_rev}
            </code>{' '}
            <button
              type="button"
              className="sh-link"
              data-testid={`rule-show-${key}`}
              onClick={() =>
                void props.guard(async () => setBody(await readKnowledgeBody(current.artifact_id, current.artifact_rev)))
              }
            >
              내용 보기
            </button>
          </div>
          {body !== null && (
            <pre className="sh-doc" data-testid={`rule-body-${key}`}>
              {body}
            </pre>
          )}
          {item.versions.length > 1 && (
            <div className="sh-muted sh-rule-line" data-testid={`rule-history-${key}`}>
              이력:{' '}
              {item.versions
                .map(
                  (v) =>
                    `v${v.version} ${KNOWLEDGE_STATE_LABEL[v.state]}(${KNOWLEDGE_AUTHORITY_LABEL[v.authority_kind] ?? v.authority_kind}${v.reason_summary ? ` · ${v.reason_summary}` : ''})`,
                )
                .join(' → ')}
            </div>
          )}
          {current.state === 'candidate' && (
            <CandidateActions item={item} current={current} items={props.items} repositories={props.repositories} guard={props.guard} />
          )}
          {(current.state === 'candidate' || current.state === 'active') && (
            <div className="sh-composer-bar sh-rule-actions">
              {current.state === 'active' && (
                <button type="button" onClick={() => setAsking(asking === 'revise' ? null : 'revise')} data-testid={`rule-revise-${key}`}>
                  개정(새 버전)
                </button>
              )}
              {asking === 'invalidate' ? (
                <>
                  <input
                    className="sh-input"
                    placeholder="무효 사유(필수)"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    data-testid={`rule-invalidate-reason-${key}`}
                  />
                  <button
                    type="button"
                    disabled={!reason.trim()}
                    onClick={() =>
                      void props.guard(async () => {
                        await knowledgeApi.invalidate(item.id, reason)
                        setAsking(null)
                      })
                    }
                    data-testid={`rule-invalidate-confirm-${key}`}
                  >
                    무효로
                  </button>
                </>
              ) : (
                <button type="button" onClick={() => setAsking('invalidate')} data-testid={`rule-invalidate-${key}`}>
                  무효로
                </button>
              )}
            </div>
          )}
          {asking === 'revise' && current.state === 'active' && (
            <ReviseForm
              item={item}
              current={current}
              projectId={project.id}
              repositories={props.repositories}
              rows={props.rows}
              runners={props.runners}
              lastCaseId={props.lastCaseId}
              guard={props.guard}
              onDone={() => setAsking(null)}
            />
          )}
        </div>
      )}
    </li>
  )
}

// ------------------------------------------------------------------ 후보의 채택 확인·활성화

function CandidateActions(props: {
  item: KnowledgeItemView
  current: KnowledgeVersion
  items: KnowledgeItemView[]
  repositories: ProjectRepository[]
  guard: Guard
}) {
  const { item, current } = props
  const key = item.knowledge_key
  const [check, setCheck] = useState<KnowledgeAdoptionCheck | null>(null)
  const [into, setInto] = useState('')
  const [obligation, setObligation] = useState<KnowledgeObligation>(current.obligation)
  const [activities, setActivities] = useState(current.activities.join(', '))
  const [narrowTo, setNarrowTo] = useState('')
  const [reason, setReason] = useState('')
  const others = props.items.filter((i) => i.id !== item.id && i.current && i.current.state !== 'invalid')
  const scope = narrowTo ? { scope_kind: 'repository' as const, repository_id: narrowTo } : {}
  const runCheck = () =>
    props.guard(async () => {
      setCheck(await knowledgeApi.adoptionCheck(item.id, into || null, obligation, scope))
    })
  return (
    <div className="sh-rule-candidate" data-testid={`rule-candidate-${key}`}>
      <div className="sh-muted sh-rule-line">
        후보는 규칙이 아니다. 채택 확인(QG-08: 원문·근거·충돌·반증 대상·범위)을 본 뒤 사람이 활성화한다 — 범위·효력·활동은
        좁힐 수만 있다.
      </div>
      <div className="sh-composer-bar sh-rule-actions">
        <button type="button" onClick={() => void runCheck()} data-testid={`rule-check-${key}`}>
          채택 확인
        </button>
        <select value={obligation} onChange={(e) => setObligation(e.target.value as KnowledgeObligation)} data-testid={`rule-obligation-${key}`}>
          <option value="reference">참고로</option>
          <option value="required">필수로</option>
        </select>
        <input
          className="sh-input sh-rule-input"
          placeholder="활동(쉼표, 좁힐 때만)"
          value={activities}
          onChange={(e) => setActivities(e.target.value)}
          data-testid={`rule-activities-${key}`}
        />
        {current.scope_kind === 'project' && props.repositories.length > 0 && (
          <select value={narrowTo} onChange={(e) => setNarrowTo(e.target.value)} data-testid={`rule-narrow-${key}`}>
            <option value="">프로젝트 전체 그대로</option>
            {props.repositories.map((r) => (
              <option key={r.id} value={r.id}>
                저장소 {r.name} 로 좁힘
              </option>
            ))}
          </select>
        )}
        <select value={into} onChange={(e) => setInto(e.target.value)} data-testid={`rule-into-${key}`}>
          <option value="">이 항목의 활성으로</option>
          {others.map((o) => (
            <option key={o.id} value={o.id}>
              {o.knowledge_key} 의 새 버전으로
            </option>
          ))}
        </select>
        <input
          className="sh-input sh-rule-input"
          placeholder="활성화 사유"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          data-testid={`rule-activate-reason-${key}`}
        />
        <button
          type="button"
          className="sh-primary"
          data-testid={`rule-activate-${key}`}
          onClick={() =>
            void props.guard(() =>
              knowledgeApi.activate(item.id, reason || '확인했다', {
                into_knowledge_id: into || null,
                obligation,
                activities: splitList(activities),
                ...scope,
              }),
            )
          }
        >
          활성으로(사람의 결정)
        </button>
      </div>
      {check && (
        <ul className="sh-result-list sh-rule-findings" data-testid={`rule-check-result-${key}`}>
          {check.findings.map((f) => (
            <li key={f.code} className="sh-plain-row" data-blocking={f.blocking ? '1' : '0'}>
              {f.blocking ? '막음' : '경고'} · {KNOWLEDGE_ADOPTION_LABEL[f.code] ?? f.code} — {f.detail}
            </li>
          ))}
          <li className="sh-plain-row sh-muted">
            근거 {check.evidence_count}건 · 독립 검토 {check.independent_review === 'not_run' ? '없음' : check.independent_review}
            {check.blocked.length ? ' · 막는 항목이 있어 활성화되지 않는다' : ' · 막는 항목 없음(활성화는 사람의 결정)'}
          </li>
        </ul>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ 개정

function ReviseForm(props: {
  item: KnowledgeItemView
  current: KnowledgeVersion
  projectId: string
  repositories: ProjectRepository[]
  rows: ConversationRow[]
  runners: RunnerWithConnection[]
  lastCaseId: string | null
  guard: Guard
  onDone: () => void
}) {
  const { item, current } = props
  const key = item.knowledge_key
  const [content, setContent] = useState('')
  const [summary, setSummary] = useState(current.summary)
  const [kind, setKind] = useState<KnowledgeKind>(current.kind)
  const [obligation, setObligation] = useState<KnowledgeObligation>(current.obligation)
  const [repositoryId, setRepositoryId] = useState(current.scope_kind === 'repository' ? current.repository_id ?? '' : '')
  const [activities, setActivities] = useState(current.activities.join(', '))
  const [reason, setReason] = useState('')
  const [caseId, setCaseId] = useState(props.lastCaseId ?? props.rows[0]?.id ?? '')
  const runnerId = props.runners[0]?.id
  const submit = () =>
    props.guard(async () => {
      const newContent = content.trim()
      if (newContent && !caseId) throw new Error('새 내용을 저장할 출처 대화를 고른다')
      if (newContent && !runnerId) throw new Error('출처로 적을 PC(Runner)가 없다')
      await knowledgeApi.revise(item.id, {
        reason_summary: reason,
        content: newContent || null,
        case_id: newContent ? caseId : null,
        target_runner_id: newContent ? runnerId : null,
        summary,
        kind,
        obligation,
        scope_kind: repositoryId ? 'repository' : 'project',
        repository_id: repositoryId || null,
        activities: splitList(activities),
      })
      props.onDone()
    })
  return (
    <div className="sh-rule-form" data-testid={`rule-revise-form-${key}`}>
      <div className="sh-muted sh-rule-line">
        개정은 새 버전이다 — 이전 버전은 대체 관계와 함께 남는다. 내용을 비우면 이전 원문을 그대로 가리킨다.
      </div>
      <textarea
        className="sh-input"
        rows={3}
        placeholder="새 적용 내용(선택 — 서버에 저장된다, 비밀값 금지)"
        value={content}
        onChange={(e) => setContent(e.target.value)}
        data-testid={`rule-revise-content-${key}`}
      />
      <div className="sh-composer-bar sh-rule-actions">
        <input className="sh-input sh-rule-input" placeholder="짧은 제목" value={summary} onChange={(e) => setSummary(e.target.value)} data-testid={`rule-revise-summary-${key}`} />
        <select value={kind} onChange={(e) => setKind(e.target.value as KnowledgeKind)}>
          {Object.entries(KNOWLEDGE_KIND_LABEL).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
        <select value={obligation} onChange={(e) => setObligation(e.target.value as KnowledgeObligation)} data-testid={`rule-revise-obligation-${key}`}>
          <option value="required">필수</option>
          <option value="reference">참고</option>
        </select>
        <select value={repositoryId} onChange={(e) => setRepositoryId(e.target.value)}>
          <option value="">프로젝트 전체</option>
          {props.repositories.map((r) => (
            <option key={r.id} value={r.id}>
              저장소 {r.name}
            </option>
          ))}
        </select>
        <input className="sh-input sh-rule-input" placeholder="활동(쉼표, 비우면 모든 작업)" value={activities} onChange={(e) => setActivities(e.target.value)} />
      </div>
      <div className="sh-composer-bar sh-rule-actions">
        {content.trim() && (
          <select value={caseId} onChange={(e) => setCaseId(e.target.value)} data-testid={`rule-revise-case-${key}`}>
            <option value="">출처 대화 선택</option>
            {props.rows.map((r) => (
              <option key={r.id} value={r.id}>
                {r.title}
              </option>
            ))}
          </select>
        )}
        <input className="sh-input sh-rule-input" placeholder="개정 사유(필수)" value={reason} onChange={(e) => setReason(e.target.value)} data-testid={`rule-revise-reason-${key}`} />
        <span className="sh-spacer" />
        <button type="button" onClick={props.onDone}>
          취소
        </button>
        <button type="button" className="sh-primary" disabled={!reason.trim() || !summary.trim()} onClick={() => void submit()} data-testid={`rule-revise-submit-${key}`}>
          새 버전으로 저장
        </button>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ 충돌

function Conflicts(props: { view: KnowledgeView; items: KnowledgeItemView[]; guard: Guard; projectId: string }) {
  const [pair, setPair] = useState({ a: '', b: '' })
  const [reason, setReason] = useState('')
  const keyOf = (id: string) => props.items.find((i) => i.id === id)?.knowledge_key ?? id
  const conflicts = props.view.conflicts
  return (
    <section data-testid="rules-conflicts">
      <h3 className="sh-section-title">충돌 · {conflicts.length}</h3>
      {conflicts.length === 0 && <p className="sh-muted sh-rule-empty">기록된 충돌이 없다(자동 탐지는 없다 — 사람이 기록한다)</p>}
      <ul className="sh-result-list">
        {conflicts.map((c) => (
          <li key={c.id} className="sh-plain-row" data-testid={`rules-conflict-${c.key_a}-${c.key_b}`} data-state={c.state}>
            {c.key_a} ↔ {c.key_b} · {c.state === 'open' ? '열림 — 둘 다 적용되는 필수 작업은 보류' : `해소: ${c.resolution_summary ?? ''}`}
            {c.reason_summary ? ` · ${c.reason_summary}` : ''}{' '}
            {c.state === 'open' && (
              <button
                type="button"
                className="sh-link"
                onClick={() =>
                  void props.guard(async () => {
                    if (!reason.trim()) throw new Error('해소 내용을 아래 사유 칸에 적는다')
                    await knowledgeApi.resolveConflict(c.id, reason)
                    setReason('')
                  })
                }
                data-testid={`rules-conflict-resolve-${c.key_a}-${c.key_b}`}
              >
                해소 기록
              </button>
            )}
          </li>
        ))}
      </ul>
      {props.items.length > 1 && (
        <div className="sh-composer-bar sh-rule-actions">
          <select value={pair.a} onChange={(e) => setPair({ ...pair, a: e.target.value })} data-testid="rules-conflict-a">
            <option value="">충돌 항목 A</option>
            {props.items.map((i) => (
              <option key={i.id} value={i.id}>
                {i.knowledge_key}
              </option>
            ))}
          </select>
          <select value={pair.b} onChange={(e) => setPair({ ...pair, b: e.target.value })} data-testid="rules-conflict-b">
            <option value="">충돌 항목 B</option>
            {props.items.map((i) => (
              <option key={i.id} value={i.id}>
                {i.knowledge_key}
              </option>
            ))}
          </select>
          <input className="sh-input sh-rule-input" placeholder="사유(기록·해소)" value={reason} onChange={(e) => setReason(e.target.value)} data-testid="rules-conflict-reason" />
          <button
            type="button"
            disabled={!pair.a || !pair.b || pair.a === pair.b}
            onClick={() =>
              void props.guard(async () => {
                await knowledgeApi.recordConflict(props.projectId, pair.a, pair.b, reason)
                setPair({ a: '', b: '' })
                setReason('')
              })
            }
            data-testid="rules-conflict-record"
          >
            충돌 기록 ({pair.a ? keyOf(pair.a) : '?'} ↔ {pair.b ? keyOf(pair.b) : '?'})
          </button>
        </div>
      )}
    </section>
  )
}

// ------------------------------------------------------------------ 수동 등록

function RegisterForm(props: {
  projectId: string
  rows: ConversationRow[]
  runners: RunnerWithConnection[]
  repositories: ProjectRepository[]
  lastCaseId: string | null
  guard: Guard
}) {
  const sorted = useMemo(
    () => [...props.rows].sort((a, b) => (b.last_activity_at ?? b.updated_at).localeCompare(a.last_activity_at ?? a.updated_at)),
    [props.rows],
  )
  const [caseId, setCaseId] = useState(props.lastCaseId ?? '')
  const [content, setContent] = useState('')
  const [summary, setSummary] = useState('')
  const [kind, setKind] = useState<KnowledgeKind>('constraint')
  const [obligation, setObligation] = useState<KnowledgeObligation>('required')
  const [repositoryId, setRepositoryId] = useState('')
  const [activities, setActivities] = useState('')
  const [candidate, setCandidate] = useState(false)
  const [reason, setReason] = useState('')
  const [done, setDone] = useState<string | null>(null)
  useEffect(() => {
    if (!caseId && sorted.length) setCaseId(props.lastCaseId && sorted.some((r) => r.id === props.lastCaseId) ? props.lastCaseId : sorted[0].id)
  }, [sorted, caseId, props.lastCaseId])
  const runnerId = props.runners[0]?.id
  const register = () =>
    props.guard(async () => {
      if (!caseId) throw new Error('출처 대화를 고른다 — 출처 없는 규칙은 등록하지 않는다')
      if (!runnerId) throw new Error('출처로 적을 PC(Runner)가 없다')
      const created = await knowledgeApi.register(caseId, {
        content,
        summary,
        kind,
        obligation,
        target_runner_id: runnerId,
        repository_id: repositoryId || null,
        activities: splitList(activities),
        // AI 제안을 적어 두는 자리는 후보다 — 사람의 확정 결정·규칙은 활성으로(재승인 없음).
        authority: candidate ? 'ai_proposal' : 'user_registration',
        state: candidate ? 'candidate' : 'active',
        reason_summary: reason || null,
      })
      setDone(`${created.version.knowledge_key} v${created.version.version} 로 등록됐다(${candidate ? '후보' : '활성 — 재승인 없음'})`)
      setContent('')
      setSummary('')
      setReason('')
    })
  return (
    <section data-testid="rules-register-form">
      <h3 className="sh-section-title">규칙·지식 등록</h3>
      <p className="sh-muted sh-rule-line">
        사람이 등록한 확정 결정·규칙은 다시 승인받지 않고 바로 활성이다. AI 가 제안한 것은 후보로만 적는다. 출처 대화는 그
        내용이 속하는 대화다(등록은 그 대화의 기록·판정을 바꾸지 않는다). 등록은 실행 권한이 아니다.
      </p>
      <div className="sh-composer-bar sh-rule-actions">
        <select value={caseId} onChange={(e) => setCaseId(e.target.value)} data-testid="rules-register-case">
          <option value="">출처 대화 선택</option>
          {sorted.map((r) => (
            <option key={r.id} value={r.id}>
              {r.title}
            </option>
          ))}
        </select>
        <span className="sh-muted">출처 PC {props.runners[0]?.host ?? '없음'}</span>
      </div>
      <textarea
        className="sh-input"
        rows={3}
        placeholder="적용 내용(조건·예외 포함) — 서버에 저장된다, 비밀값 금지"
        value={content}
        onChange={(e) => setContent(e.target.value)}
        data-testid="rules-register-content"
      />
      <div className="sh-composer-bar sh-rule-actions">
        <input className="sh-input sh-rule-input" placeholder="짧은 제목" value={summary} onChange={(e) => setSummary(e.target.value)} data-testid="rules-register-summary" />
        <select value={kind} onChange={(e) => setKind(e.target.value as KnowledgeKind)} data-testid="rules-register-kind">
          {Object.entries(KNOWLEDGE_KIND_LABEL).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
        <select value={obligation} onChange={(e) => setObligation(e.target.value as KnowledgeObligation)} data-testid="rules-register-obligation">
          <option value="required">필수</option>
          <option value="reference">참고</option>
        </select>
        <select value={repositoryId} onChange={(e) => setRepositoryId(e.target.value)} data-testid="rules-register-repository">
          <option value="">프로젝트 전체</option>
          {props.repositories.map((r) => (
            <option key={r.id} value={r.id}>
              저장소 {r.name}
            </option>
          ))}
        </select>
        <input
          className="sh-input sh-rule-input"
          placeholder={`활동(쉼표: ${RULE_ACTIVITIES.join('·')}, 비우면 모든 작업)`}
          value={activities}
          onChange={(e) => setActivities(e.target.value)}
          data-testid="rules-register-activities"
        />
        <label>
          <input type="checkbox" checked={candidate} onChange={(e) => setCandidate(e.target.checked)} data-testid="rules-register-candidate" /> AI 제안(후보로만)
        </label>
      </div>
      <div className="sh-composer-bar sh-rule-actions">
        <input className="sh-input sh-rule-input" placeholder="사유(선택)" value={reason} onChange={(e) => setReason(e.target.value)} data-testid="rules-register-reason" />
        <span className="sh-spacer" />
        {done && <span className="sh-notice sh-notice-ok" data-testid="rules-register-done">{done}</span>}
        <button type="button" className="sh-primary" disabled={!content.trim() || !summary.trim() || !caseId} onClick={() => void register()} data-testid="rules-register">
          등록
        </button>
      </div>
    </section>
  )
}
