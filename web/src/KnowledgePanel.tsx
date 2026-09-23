// P4-06. 관리 화면의 **프로젝트 지식** 패널. 등록부(항목·현재 버전·원문 가용성·이력)와 충돌을 보이고,
// 사람이 이 대화(Case)에서 지식을 등록·활성화·무효화하고 충돌을 기록·해소한다.
//
//   **적용 내용은 서버에 있다**(P4-06b, 사용자 결정 2026-09-24 — 원문 PC 경계의 유일한 예외). 어느 PC 의
//   실행에도 주입하기 위해서다. 그래서 비밀값을 적지 말라고 알린다. 옛 원문은 소유 PC 가 연결되면
//   올라온다(`PC 에만`). 이 패널의 "내용 보기"는 열람 경로로 서버 본문을 받는다 — PC 연결과 무관하다.
//   **등록은 실행 권한이 아니고 주입은 준수의 증거가 아니다.** 필수 규칙이 제공됐다고 지켰다고 보지
//   않는다 — 준수는 기준 판정·검토가 따로 본다.
//   **AI 제안은 후보로만** 들어온다. 활성 필수는 사람의 권위(등록·대화의 사용자 말·활성화)뿐이다.

import { useCallback, useEffect, useState } from 'react'

import {
  ApiError,
  KNOWLEDGE_AUTHORITY_LABEL,
  KNOWLEDGE_KIND_LABEL,
  KNOWLEDGE_STATE_LABEL,
  intentApi,
  knowledgeApi,
  type KnowledgeKind,
  type KnowledgeObligation,
  type KnowledgeView,
} from './api'

function describe(err: unknown): string {
  if (err instanceof ApiError) return `${err.status}: ${err.message}`
  return err instanceof Error ? err.message : String(err)
}

export const KNOWLEDGE_STORAGE_LABEL: Record<string, string> = {
  server: '서버 저장',
  runner: 'PC 에만(소유 PC 가 연결되면 서버로 올라온다)',
}

// 열람 경로로 본문 한 번 받기. 서버 본문이면 바로 오고, PC 에만 있으면 그 PC 가 올릴 때까지 기다린다.
async function readBody(artifactId: string, revision: number): Promise<string> {
  const request = await intentApi.openRead(artifactId, revision)
  const deadline = Date.now() + 15_000
  while (Date.now() < deadline) {
    const result = await intentApi.fetchRead(request.id)
    if (result.content !== null) return result.content
    if (result.request.state === 'expired') throw new Error('열람 중계가 끊겼다 — 다시 시도한다')
    await new Promise((resolve) => setTimeout(resolve, 300))
  }
  throw new Error('원문이 제한 시간 안에 오지 않았다(PC 에만 있는 원문은 그 PC 가 연결돼야 한다)')
}

export function KnowledgePanel(props: { projectId: string; caseId: string; runnerId: string | undefined }) {
  const [view, setView] = useState<KnowledgeView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [content, setContent] = useState('')
  const [summary, setSummary] = useState('')
  const [kind, setKind] = useState<KnowledgeKind>('constraint')
  const [obligation, setObligation] = useState<KnowledgeObligation>('required')
  const [candidate, setCandidate] = useState(false)
  const [activities, setActivities] = useState('')
  const [reason, setReason] = useState('')
  const [pair, setPair] = useState({ a: '', b: '' })
  const [bodies, setBodies] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    try {
      setView(await knowledgeApi.list(props.projectId))
    } catch (err) {
      setError(describe(err))
    }
  }, [props.projectId])

  useEffect(() => {
    void load()
  }, [load])

  const guard = async (fn: () => Promise<unknown>) => {
    try {
      setError(null)
      await fn()
    } catch (err) {
      setError(describe(err))
    }
    await load()
  }

  const register = () =>
    guard(async () => {
      // 출처 PC 다 — 내용은 서버에 저장되므로 그 PC 가 지금 연결돼 있을 필요는 없다.
      if (!props.runnerId) throw new Error('출처로 적을 PC(Runner)가 없다')
      await knowledgeApi.register(props.caseId, {
        content,
        summary,
        kind,
        obligation,
        target_runner_id: props.runnerId,
        activities: activities
          .split(',')
          .map((a) => a.trim())
          .filter(Boolean),
        // 후보로 적는 것은 **AI 제안을 적어 두는** 자리다 — 사람의 확정 결정은 활성으로 등록한다.
        authority: candidate ? 'ai_proposal' : 'user_registration',
        state: candidate ? 'candidate' : 'active',
        reason_summary: reason || null,
      })
      setContent('')
      setSummary('')
    })

  const items = view?.items ?? []
  const keyOf = (id: string) => items.find((i) => i.id === id)?.knowledge_key ?? id
  return (
    <section className="subpanel" data-testid="knowledge-panel">
      <h3>프로젝트 지식</h3>
      {error && <p className="error">{error}</p>}
      {view && <p className="muted small">{view.note}</p>}
      <ul className="list">
        {items.map((item) => {
          const current = item.current
          if (!current) return null
          return (
            <li key={item.id} className="small" data-testid={`knowledge-${item.knowledge_key}`}>
              <strong>{item.knowledge_key}</strong> v{current.version} · {KNOWLEDGE_STATE_LABEL[current.state]} ·{' '}
              {current.obligation === 'required' ? '필수' : '참고'} · {KNOWLEDGE_KIND_LABEL[current.kind]} ·{' '}
              {current.summary}
              <div className="muted">
                범위{' '}
                {current.scope_kind === 'project'
                  ? '프로젝트 전체'
                  : `저장소 ${current.repository_name ?? current.repository_id}${current.paths.length ? ` · 경로 ${current.paths.join(', ')}` : ''}`}{' '}
                · 활동 {current.activities.join(', ') || '모든 작업'} · 권위{' '}
                {KNOWLEDGE_AUTHORITY_LABEL[current.authority_kind] ?? current.authority_kind} · 원문{' '}
                {current.availability ?? '-'} · <code>{current.artifact_id}@{current.artifact_rev}</code>
                {current.invalid_reason ? ` · 무효 사유: ${current.invalid_reason}` : ''}
              </div>
              <div className="muted" data-testid={`knowledge-storage-${item.knowledge_key}`}>
                내용 {KNOWLEDGE_STORAGE_LABEL[current.storage ?? 'runner']}
                {current.source_storage
                  ? ` · 권위 메시지 ${KNOWLEDGE_STORAGE_LABEL[current.source_storage]}`
                  : ''}{' '}
                <button
                  type="button"
                  data-testid={`knowledge-show-${item.knowledge_key}`}
                  onClick={() =>
                    void guard(async () => {
                      const text = await readBody(current.artifact_id, current.artifact_rev)
                      setBodies((prev) => ({ ...prev, [item.id]: text }))
                    })
                  }
                >
                  내용 보기
                </button>
              </div>
              {bodies[item.id] !== undefined && (
                <pre className="small" data-testid={`knowledge-body-${item.knowledge_key}`}>
                  {bodies[item.id]}
                </pre>
              )}
              {item.versions.length > 1 && (
                <div className="muted">
                  이력:{' '}
                  {item.versions
                    .map((v) => `v${v.version} ${KNOWLEDGE_STATE_LABEL[v.state]}(${KNOWLEDGE_AUTHORITY_LABEL[v.authority_kind] ?? v.authority_kind})`)
                    .join(' → ')}
                </div>
              )}
              <span className="row">
                {current.state === 'candidate' && (
                  <button
                    type="button"
                    onClick={() => void guard(() => knowledgeApi.activate(item.id, reason || '확인했다'))}
                  >
                    활성으로
                  </button>
                )}
                {(current.state === 'candidate' || current.state === 'active') && (
                  <button
                    type="button"
                    data-testid={`knowledge-invalidate-${item.knowledge_key}`}
                    onClick={() =>
                      void guard(async () => {
                        if (!reason.trim()) throw new Error('무효 사유를 아래 사유 칸에 적는다')
                        await knowledgeApi.invalidate(item.id, reason)
                      })
                    }
                  >
                    무효로
                  </button>
                )}
              </span>
            </li>
          )
        })}
        {items.length === 0 && <li className="muted small">등록된 지식이 없다</li>}
      </ul>

      {view && view.conflicts.length > 0 && (
        <>
          <h4>충돌</h4>
          <ul className="list">
            {view.conflicts.map((c) => (
              <li key={c.id} className="small">
                {c.key_a} ↔ {c.key_b} · {c.state === 'open' ? '열림 — 둘 다 적용되는 필수 작업은 보류' : `해소: ${c.resolution_summary ?? ''}`}
                {c.reason_summary ? ` · ${c.reason_summary}` : ''}
                {c.state === 'open' && (
                  <button
                    type="button"
                    onClick={() =>
                      void guard(async () => {
                        if (!reason.trim()) throw new Error('해소 내용을 아래 사유 칸에 적는다')
                        await knowledgeApi.resolveConflict(c.id, reason)
                      })
                    }
                  >
                    해소 기록
                  </button>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      <h4>이 대화에서 등록</h4>
      <p className="muted small" data-testid="knowledge-storage-note">
        적용 내용(조건·예외 포함)은 <strong>서버에 저장된다</strong> — 어느 PC 의 실행에도 주입하기 위해서다.{' '}
        <strong>비밀값(토큰·비밀번호·키)을 적지 말 것.</strong> 사람이 등록한 확정 결정·규칙은 다시 승인받지 않고
        바로 활성이다. AI 가 제안한 것은 후보로만 적는다.
      </p>
      <textarea
        rows={3}
        placeholder="적용 내용(조건·예외 포함)"
        value={content}
        onChange={(e) => setContent(e.target.value)}
        data-testid="knowledge-content"
      />
      <div className="row">
        <input placeholder="짧은 제목" value={summary} onChange={(e) => setSummary(e.target.value)} data-testid="knowledge-summary" />
        <select value={kind} onChange={(e) => setKind(e.target.value as KnowledgeKind)}>
          {Object.entries(KNOWLEDGE_KIND_LABEL).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
        <select value={obligation} onChange={(e) => setObligation(e.target.value as KnowledgeObligation)}>
          <option value="required">필수</option>
          <option value="reference">참고</option>
        </select>
        <label className="small">
          <input type="checkbox" checked={candidate} onChange={(e) => setCandidate(e.target.checked)} /> AI 제안(후보)
        </label>
        <input placeholder="활동(쉼표, 비우면 모든 작업)" value={activities} onChange={(e) => setActivities(e.target.value)} />
      </div>
      <div className="row">
        <input placeholder="사유(등록·무효·해소)" value={reason} onChange={(e) => setReason(e.target.value)} data-testid="knowledge-reason" />
        <button
          type="button"
          disabled={!content.trim() || !summary.trim()}
          onClick={() => void register()}
          data-testid="knowledge-register"
        >
          등록
        </button>
      </div>
      {items.length > 1 && (
        <div className="row">
          <select value={pair.a} onChange={(e) => setPair({ ...pair, a: e.target.value })}>
            <option value="">충돌 항목 A</option>
            {items.map((i) => (
              <option key={i.id} value={i.id}>
                {i.knowledge_key}
              </option>
            ))}
          </select>
          <select value={pair.b} onChange={(e) => setPair({ ...pair, b: e.target.value })}>
            <option value="">충돌 항목 B</option>
            {items.map((i) => (
              <option key={i.id} value={i.id}>
                {i.knowledge_key}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={!pair.a || !pair.b || pair.a === pair.b}
            onClick={() =>
              void guard(async () => {
                await knowledgeApi.recordConflict(props.projectId, pair.a, pair.b, reason)
                setPair({ a: '', b: '' })
              })
            }
          >
            충돌 기록 ({pair.a ? keyOf(pair.a) : '?'} ↔ {pair.b ? keyOf(pair.b) : '?'})
          </button>
        </div>
      )}
    </section>
  )
}
