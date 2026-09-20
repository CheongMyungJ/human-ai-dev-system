// 의도 화면 — 초안 · 원문 열람 · 피드백 · 질문 · 명시 동의.
//
// 화면이 지켜야 하는 것 두 가지:
//
//   1. **읽지 않은 초안에 동의 버튼을 열어 주지 않는다.** 동의는 사람이 이 화면에서
//      원문을 실제로 받아 본 뒤에만 누를 수 있고, 그때 받은 원문의 해시를 함께 보낸다.
//      서버도 같은 조건을 다시 검사한다(화면 검사를 신뢰 근거로 삼지 않는다).
//   2. 조회·피드백·질문 답변을 동의처럼 보이게 하지 않는다. 각각 별도 동작이며
//      화면 문구에서도 구별한다.
//
// **초안을 쓰는 길은 두 가지다**(P2-03).
//
//   AI 작성  아래 "AI에게 초안 요청"이 요청 원문을 Runner로 보내고, 코딩 CLI가
//            여섯 항목 초안을 써서 의도 버전으로 만든다. FR-03이 말하는 역할
//            분리는 이 경로에서 성립한다 — AI가 제시하고 사람은 검토한다
//   사람 작성 아래 입력 폼. 사람이 직접 쓰거나 고치는 것은 유효한 사용이며
//            없애지 않는다. 두 경로가 같은 문서 형식과 같은 표를 쓴다
//
// 어느 쪽이 썼는지는 **버전마다 기록되고 화면에 표시된다.** 표기만 바꾸면 그
// 문서는 거짓말이 되므로 실제 작성 주체를 그대로 보여 준다.

import { useCallback, useEffect, useState } from 'react'
import {
  api,
  INTENT_FIELDS,
  intentApi,
  type ContentOrigin,
  type DecideAt,
  type DraftFieldInput,
  type DraftQuestionInput,
  type IntentDiff,
  type IntentStateView,
  type IntentVersionDetail,
} from './api'

const ORIGIN_LABEL: Record<ContentOrigin, string> = {
  none: '없음 (미정)',
  user_requirement: '사용자 요구',
  project_rule: '프로젝트 규칙',
  observation: '관찰 사실',
  ai_proposal: 'AI 제안',
  ai_assumption: 'AI 가정',
}

const STATE_LABEL: Record<string, string> = {
  undecided: '미정',
  proposed: '제안됨',
  user_confirmed: '사용자 확인됨',
  needs_recheck: '재검토 필요',
  superseded: '대체됨',
}

const CHANGE_LABEL: Record<string, string> = {
  initial: '첫 버전',
  unchanged: '변화 없음',
  changed: '바뀜',
}

const AGREEMENT_LABEL: Record<string, string> = {
  no_intent: '의도 초안 없음',
  never_agreed: '동의 없음',
  stale_agreement: '이전 버전에만 동의함 — 최신 버전은 미동의',
  agreed_current: '최신 버전에 동의함',
}

const DECIDE_AT_LABEL: Record<DecideAt, string> = {
  intent: '의도 단계에서 결정',
  design: '설계로 이월',
  plan: '개발계획으로 이월',
}

const EDITABLE_ORIGINS: ContentOrigin[] = [
  'user_requirement',
  'project_rule',
  'observation',
  'ai_proposal',
  'ai_assumption',
]

type FieldDraft = { text: string; origin: ContentOrigin }
type QuestionDraft = { key: string; summary: string; text: string; decide_at: DecideAt }

function emptyFields(): Record<string, FieldDraft> {
  const out: Record<string, FieldDraft> = {}
  for (const field of INTENT_FIELDS) out[field.key] = { text: '', origin: 'user_requirement' }
  return out
}

export function IntentPanel(props: {
  caseId: string
  runnerId: string | undefined
  onChanged: () => void
}) {
  const { caseId, runnerId } = props
  const [state, setState] = useState<IntentStateView | null>(null)
  const [diff, setDiff] = useState<IntentDiff | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    const next = await intentApi.state(caseId)
    setState(next)
    if (next.latest_intent_version) {
      setDiff(await intentApi.diff(caseId, next.latest_intent_version.id))
    } else {
      setDiff(null)
    }
  }, [caseId])

  useEffect(() => {
    void refresh().catch((err) => setError(String(err)))
  }, [refresh])

  const guard = async (fn: () => Promise<void>) => {
    try {
      setError(null)
      await fn()
      await refresh()
      props.onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const latest = state?.latest_intent_version ?? null

  return (
    <section className="panel wide">
      <h2>의도</h2>
      <p className="muted small">
        기능 개발은 여섯 항목 초안 · 피드백 · 최신 버전에 대한 명시 동의를 거친다(FR-03).
        <br />
        초안은 <strong>AI가 쓰거나</strong> 사람이 직접 쓴다. 어느 쪽이 썼는지는
        버전마다 기록된다.
      </p>

      {error && <div className="error">오류: {error}</div>}
      {notice && <div className="notice">{notice}</div>}

      <AgreementBanner state={state} />

      <AiDraftRequest caseId={caseId} runnerId={runnerId} onNotice={setNotice} onAction={guard} />

      {latest && (
        <LatestVersion
          caseId={caseId}
          intent={latest}
          diff={diff}
          runnerId={runnerId}
          onNotice={setNotice}
          onAction={guard}
        />
      )}

      <DraftForm
        caseId={caseId}
        runnerId={runnerId}
        hasPrevious={latest !== null}
        unresolvedFeedback={state?.unresolved_feedback ?? []}
        onAction={guard}
        onNotice={setNotice}
      />
    </section>
  )
}

function AgreementBanner(props: { state: IntentStateView | null }) {
  const state = props.state
  if (!state) return null
  const level =
    state.agreement_state === 'agreed_current'
      ? 'notice'
      : state.agreement_state === 'stale_agreement'
        ? 'error'
        : 'muted'
  return (
    <div className={level === 'muted' ? 'notice muted' : level}>
      <strong>동의 상태: {AGREEMENT_LABEL[state.agreement_state]}</strong>
      {state.agreed_version && (
        <div className="small">
          동의한 대상: 의도 v{state.agreed_version.subject_revision} · {state.agreed_version.actor} ·{' '}
          {state.agreed_version.decided_at}
          <br />
          동의한 원문 해시:{' '}
          <span className="mono">
            {state.agreed_version.subject_content_hash ?? '기록되지 않음'}
          </span>
        </div>
      )}
      {state.agreement_state === 'stale_agreement' && (
        <div className="small">
          과거 동의는 기록으로 남지만 최신 버전에 적용되지 않는다. 최신 버전에 다시 동의해야 한다.
        </div>
      )}
      {state.views.length > 0 && (
        <div className="small muted">
          최신 버전 열람 {state.views.length}회 — 열람은 동의가 아니다.
        </div>
      )}
    </div>
  )
}

function AiDraftRequest(props: {
  caseId: string
  runnerId: string | undefined
  onNotice: (text: string | null) => void
  onAction: (fn: () => Promise<void>) => Promise<void>
}) {
  const [request, setRequest] = useState('')
  const [busy, setBusy] = useState(false)

  return (
    <div className="subpanel">
      <h3>AI에게 초안 요청</h3>
      <p className="muted small">
        요청 원문이 소유 Runner로 가고, 코딩 CLI가 <strong>읽기 권한으로</strong> 여섯 항목
        초안을 써서 새 의도 버전을 만든다. 이 요청은 동의가 아니다 — 초안이 오면 원문을
        읽고 피드백하거나 동의한다.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (!request.trim() || !props.runnerId) {
            props.onNotice('요청 내용과 등록된 Runner가 모두 필요하다.')
            return
          }
          const runnerId = props.runnerId
          void props.onAction(async () => {
            setBusy(true)
            try {
              // 1. 요청 원문을 접수한다. 제어부는 보관하지 않고 중계만 한다.
              const accepted = await api.submitArtifact(
                props.caseId,
                'instruction',
                request,
                '초안 작성 요청',
                runnerId,
              )
              // 2. Runner가 **영속 저장을 보고할 때까지** 기다린다. 읽을 수 없는
              //    지시로는 실행을 배정하지 않기 때문이다(진입 조건).
              let stored = false
              for (let attempt = 0; attempt < 30 && !stored; attempt += 1) {
                const intake = await api.getIntake(accepted.intake_id)
                stored = intake.state === 'stored'
                if (!stored) await new Promise((resolve) => setTimeout(resolve, 500))
              }
              if (!stored) {
                props.onNotice(
                  '요청 원문이 아직 Runner에 저장되지 않았다(PC 연결 필요).' +
                    ' 저장되면 다시 눌러 실행을 요청한다.',
                )
                return
              }
              // 3. 초안 작성 목적의 실행을 요청한다. 이 목적에도 진입 검사가 걸린다.
              const runId = `draft-${Date.now()}`
              await api.createRun(props.caseId, accepted.artifact_id, runId, {
                purpose: 'intent_authoring',
                role: 'author',
                permission: 'read_only',
              })
              setRequest('')
              props.onNotice(
                `초안 작성을 요청했다(${runId}). Runner가 실행을 마치면 새 의도 버전이 나타난다.`,
              )
            } finally {
              setBusy(false)
            }
          })
        }}
      >
        <textarea
          value={request}
          rows={3}
          placeholder="무엇을 만들고 싶은지 — 이 본문은 제어부에 저장되지 않는다"
          onChange={(e) => setRequest(e.target.value)}
        />
        <button type="submit" disabled={busy}>
          {busy ? '요청 중…' : 'AI에게 초안 요청'}
        </button>
      </form>
    </div>
  )
}

function LatestVersion(props: {
  caseId: string
  intent: IntentVersionDetail
  diff: IntentDiff | null
  runnerId: string | undefined
  onNotice: (text: string | null) => void
  onAction: (fn: () => Promise<void>) => Promise<void>
}) {
  const { caseId, intent, diff } = props
  // 이 화면에서 **실제로 받아 본** 원문. 동의는 이것이 있어야만 열린다.
  const [original, setOriginal] = useState<{ hash: string; text: string } | null>(null)
  const [readState, setReadState] = useState<string | null>(null)
  const [statement, setStatement] = useState('')
  const [feedback, setFeedback] = useState({ summary: '', content: '' })
  const [answer, setAnswer] = useState<Record<string, string>>({})

  // 버전이 바뀌면 이전에 읽은 원문을 그대로 쓰지 않는다(FR-23: 대상이 바뀌면 재확인).
  useEffect(() => {
    setOriginal(null)
    setReadState(null)
    setStatement('')
  }, [intent.id, intent.content_hash])

  const readOriginal = () =>
    props.onAction(async () => {
      setOriginal(null)
      const created = await intentApi.openRead(intent.artifact_id, intent.artifact_rev)
      // Runner가 폴링으로 가져가므로 잠깐 기다렸다 다시 확인한다.
      for (let attempt = 0; attempt < 15; attempt += 1) {
        const result = await intentApi.fetchRead(created.id)
        setReadState(result.request.state)
        if (result.content !== null) {
          // 열람 기록은 서버가 전달 시점에 남긴다. 화면이 "읽었다"고 보고하지 않는다 —
          // 화면의 주장을 동의의 선행 조건으로 쓸 수 없기 때문이다.
          setOriginal({ hash: result.request.content_hash ?? '', text: result.content })
          return
        }
        if (result.request.state === 'expired' || result.request.state === 'delivered') return
        await new Promise((resolve) => setTimeout(resolve, 700))
      }
      props.onNotice(
        'Runner가 아직 원문을 올리지 않았다 — PC 연결이 필요하다. 원문이 사라진 것은 아니다.',
      )
    })

  const openIntentQuestions = intent.questions.filter(
    (q) => q.state === 'open' && q.decide_at === 'intent',
  )
  const canAgree = original !== null && original.hash === intent.content_hash

  return (
    <>
      <h3>
        최신 의도 v{intent.revision} · {STATE_LABEL[intent.status] ?? intent.status}
      </h3>
      <p className="muted small">
        원문 상태: {intent.availability} · 해시 <span className="mono">{intent.content_hash}</span>
      </p>
      {/* 누가 썼는지를 숨기지 않는다. 기록이 없는 옛 버전은 "기록 없음"이며
          지금 와서 사람이 썼다고 적지 않는다. */}
      <p className="small">
        작성 주체:{' '}
        <strong>
          {intent.authoring_mode === 'ai_drafted'
            ? 'AI가 작성해 제시한 초안'
            : intent.authoring_mode === 'human_typed'
              ? '사람이 직접 입력한 초안'
              : '기록 없음 (P2-03 이전 버전)'}
        </strong>
        {intent.author_run_id && (
          <span className="muted"> · 작성 실행 {intent.author_run_id}</span>
        )}
      </p>

      <table>
        <thead>
          <tr>
            <th>필수 항목</th>
            <th>확인 상태</th>
            <th>내용의 성격</th>
            <th>이전 버전 대비</th>
          </tr>
        </thead>
        <tbody>
          {intent.fields.map((field) => {
            const label = INTENT_FIELDS.find((f) => f.key === field.field)?.label ?? field.field
            return (
              <tr key={field.field}>
                <td>{label}</td>
                <td>{STATE_LABEL[field.state] ?? field.state}</td>
                <td>{ORIGIN_LABEL[field.origin] ?? field.origin}</td>
                <td className={field.change_from_prev === 'changed' ? '' : 'muted'}>
                  {CHANGE_LABEL[field.change_from_prev] ?? field.change_from_prev}
                </td>
              </tr>
            )
          })}
          {intent.fields.length === 0 && (
            <tr>
              <td colSpan={4} className="muted">
                Runner가 아직 구조를 보고하지 않았다 — 원문 저장 대기 중이다.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {diff && diff.compared_with_revision !== null && (
        <p className="small">
          v{diff.compared_with_revision} 대비 바뀐 항목:{' '}
          {diff.changed_fields.length > 0
            ? diff.changed_fields
                .map((f) => INTENT_FIELDS.find((x) => x.key === f)?.label ?? f)
                .join(', ')
            : '없음'}
          . 새 질문 {diff.questions_added.length}건 · 사라진 질문 {diff.questions_removed.length}건.
          <br />
          <span className="muted">
            전체 본문 차이는 제어부에 없다 — 두 버전의 원문을 각각 열람해 비교한다.
          </span>
        </p>
      )}

      <h4>미정 질문</h4>
      <ul className="list">
        {intent.questions.map((question) => (
          <li key={question.id}>
            <div>
              <strong>{question.summary}</strong>{' '}
              <span className="muted small">
                {DECIDE_AT_LABEL[question.decide_at]} · {question.state}
              </span>
            </div>
            {question.state === 'open' && (
              <form
                onSubmit={(event) => {
                  event.preventDefault()
                  const text = (answer[question.id] ?? '').trim()
                  if (!text || !props.runnerId) return
                  void props.onAction(async () => {
                    await intentApi.answerQuestion(
                      caseId,
                      question.id,
                      text,
                      question.summary,
                      props.runnerId as string,
                    )
                    setAnswer((prev) => ({ ...prev, [question.id]: '' }))
                    props.onNotice('질문에 답했다. 이것은 의도 동의가 아니다.')
                  })
                }}
              >
                <input
                  value={answer[question.id] ?? ''}
                  placeholder="이 질문에 대한 사람의 결정 (원문은 Runner에 저장된다)"
                  onChange={(e) =>
                    setAnswer((prev) => ({ ...prev, [question.id]: e.target.value }))
                  }
                />
                <button type="submit">답변 기록</button>
              </form>
            )}
          </li>
        ))}
        {intent.questions.length === 0 && <li className="muted">없음</li>}
      </ul>

      <h4>원문 열람</h4>
      <p className="muted small">
        본문은 소유 Runner에서 온다. 제어부는 메모리로 한 번 중계할 뿐 보관하지 않는다.
      </p>
      <button type="button" onClick={readOriginal}>
        원문 받아 보기
      </button>
      {readState && !original && (
        <p className="small">
          열람 요청 상태: {readState}
          {readState === 'pending' && ' — PC 연결 필요. 원문이 사라진 것은 아니다.'}
          {readState === 'expired' && ' — 중계가 끊겼다. 다시 요청한다.'}
        </p>
      )}
      {original && (
        <>
          <p className="small muted">
            이 본문은 이 화면에만 있다. 해시 <span className="mono">{original.hash}</span>
          </p>
          <pre className="original">{original.text}</pre>
        </>
      )}

      <h4>피드백</h4>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (!feedback.content.trim() || !feedback.summary.trim() || !props.runnerId) return
          void props.onAction(async () => {
            await intentApi.submitFeedback(
              caseId,
              intent.id,
              feedback.content,
              feedback.summary.trim(),
              props.runnerId as string,
            )
            setFeedback({ summary: '', content: '' })
            props.onNotice(
              '피드백을 접수했다. 이것은 의도 동의가 아니다 — 반영한 새 버전을 만들어야 한다.',
            )
          })
        }}
      >
        <input
          value={feedback.summary}
          placeholder="피드백 요약 (목록 표시용)"
          onChange={(e) => setFeedback({ ...feedback, summary: e.target.value })}
        />
        <textarea
          rows={3}
          value={feedback.content}
          placeholder="피드백 원문 — 제어부에 저장되지 않는다"
          onChange={(e) => setFeedback({ ...feedback, content: e.target.value })}
        />
        <button type="submit" disabled={!props.runnerId}>
          피드백 보내기
        </button>
      </form>

      <h4>이 버전에 동의</h4>
      {!canAgree && (
        <p className="muted small">
          원문을 먼저 받아 봐야 동의할 수 있다. 요약만 읽은 상태를 원문 확인으로 기록하지 않는다.
        </p>
      )}
      {canAgree && openIntentQuestions.length > 0 && (
        <p className="muted small">
          의도 단계에서 결정할 질문이 남아 있다:{' '}
          {openIntentQuestions.map((q) => q.summary).join(', ')}. 먼저 답해야 한다.
        </p>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (!canAgree || !statement.trim()) return
          void props.onAction(async () => {
            await intentApi.agree(caseId, intent.id, original!.hash, statement.trim())
            setStatement('')
            props.onNotice(`의도 v${intent.revision} 에 동의했다. 이 동의는 이 버전에만 붙는다.`)
          })
        }}
      >
        <input
          value={statement}
          placeholder="동의 문구를 직접 씁니다 (예: 이 의도대로 진행해도 됩니다)"
          onChange={(e) => setStatement(e.target.value)}
          disabled={!canAgree}
        />
        <button type="submit" disabled={!canAgree || !statement.trim()}>
          이 버전에 명시적으로 동의
        </button>
      </form>
    </>
  )
}

function DraftForm(props: {
  caseId: string
  runnerId: string | undefined
  hasPrevious: boolean
  unresolvedFeedback: { id: string; summary: string }[]
  onAction: (fn: () => Promise<void>) => Promise<void>
  onNotice: (text: string | null) => void
}) {
  const [fields, setFields] = useState<Record<string, FieldDraft>>(emptyFields)
  const [questions, setQuestions] = useState<QuestionDraft[]>([])
  const [summary, setSummary] = useState('')
  const [reflects, setReflects] = useState<string[]>([])

  return (
    <>
      <h3>{props.hasPrevious ? '새 의도 버전 작성' : '의도 초안 작성'}</h3>
      <p className="muted small">
        비워 둔 항목은 <strong>미정</strong>으로 남는다. 시스템이 값을 채우지 않는다.
      </p>
      <form
        className="draft-form"
        onSubmit={(event) => {
          event.preventDefault()
          if (!summary.trim() || !props.runnerId) return
          const payloadFields: Record<string, DraftFieldInput> = {}
          for (const [key, value] of Object.entries(fields)) {
            payloadFields[key] = value.text.trim()
              ? { text: value.text, state: 'proposed', origin: value.origin }
              : { text: '' }
          }
          const payloadQuestions: DraftQuestionInput[] = questions
            .filter((q) => q.key.trim() && q.text.trim() && q.summary.trim())
            .map((q) => ({
              key: q.key.trim(),
              text: q.text,
              summary: q.summary.trim(),
              decide_at: q.decide_at,
            }))
          void props.onAction(async () => {
            await intentApi.submitDraft(props.caseId, {
              summary: summary.trim(),
              target_runner_id: props.runnerId as string,
              fields: payloadFields,
              questions: payloadQuestions,
              reflects_feedback: reflects,
            })
            setFields(emptyFields())
            setQuestions([])
            setSummary('')
            setReflects([])
            props.onNotice(
              '초안을 접수했다. 아직 저장 완료가 아니다 — Runner가 저장하고 구조를 보고하면 나타난다.',
            )
          })
        }}
      >
        <input
          value={summary}
          placeholder="이 버전의 짧은 요약 (목록 표시용, 본문 아님)"
          onChange={(e) => setSummary(e.target.value)}
        />

        {INTENT_FIELDS.map((field) => (
          <div key={field.key} className="field">
            <label>
              {field.label} <span className="muted small">{field.hint}</span>
            </label>
            <textarea
              rows={2}
              value={fields[field.key].text}
              placeholder="비워 두면 미정으로 남는다"
              onChange={(e) =>
                setFields({ ...fields, [field.key]: { ...fields[field.key], text: e.target.value } })
              }
            />
            <select
              value={fields[field.key].origin}
              disabled={!fields[field.key].text.trim()}
              onChange={(e) =>
                setFields({
                  ...fields,
                  [field.key]: { ...fields[field.key], origin: e.target.value as ContentOrigin },
                })
              }
            >
              {EDITABLE_ORIGINS.map((origin) => (
                <option key={origin} value={origin}>
                  {ORIGIN_LABEL[origin]}
                </option>
              ))}
            </select>
          </div>
        ))}

        <h4>미정 질문</h4>
        {questions.map((question, index) => (
          <div key={index} className="field">
            <input
              value={question.key}
              placeholder="질문 키 (버전이 바뀌어도 같은 질문을 잇는다)"
              onChange={(e) => {
                const next = [...questions]
                next[index] = { ...question, key: e.target.value }
                setQuestions(next)
              }}
            />
            <input
              value={question.summary}
              placeholder="질문 요약 — 이것만 제어부에 남는다"
              onChange={(e) => {
                const next = [...questions]
                next[index] = { ...question, summary: e.target.value }
                setQuestions(next)
              }}
            />
            <textarea
              rows={2}
              value={question.text}
              placeholder="대상·근거·선택·영향 (원문은 Runner에 저장된다)"
              onChange={(e) => {
                const next = [...questions]
                next[index] = { ...question, text: e.target.value }
                setQuestions(next)
              }}
            />
            <select
              value={question.decide_at}
              onChange={(e) => {
                const next = [...questions]
                next[index] = { ...question, decide_at: e.target.value as DecideAt }
                setQuestions(next)
              }}
            >
              {(['intent', 'design', 'plan'] as DecideAt[]).map((value) => (
                <option key={value} value={value}>
                  {DECIDE_AT_LABEL[value]}
                </option>
              ))}
            </select>
          </div>
        ))}
        <button
          type="button"
          onClick={() =>
            setQuestions([
              ...questions,
              { key: '', summary: '', text: '', decide_at: 'intent' },
            ])
          }
        >
          질문 추가
        </button>

        {props.unresolvedFeedback.length > 0 && (
          <>
            <h4>이 버전이 반영한 피드백</h4>
            {props.unresolvedFeedback.map((item) => (
              <label key={item.id} className="check">
                <input
                  type="checkbox"
                  checked={reflects.includes(item.id)}
                  onChange={(e) =>
                    setReflects(
                      e.target.checked
                        ? [...reflects, item.id]
                        : reflects.filter((id) => id !== item.id),
                    )
                  }
                />
                {item.summary}
              </label>
            ))}
          </>
        )}

        <button type="submit" disabled={!props.runnerId}>
          {props.hasPrevious ? '새 버전 제출' : '초안 제출'}
        </button>
        {!props.runnerId && (
          <p className="muted small">등록된 Runner가 없어 원문을 저장할 수 없다.</p>
        )}
      </form>
    </>
  )
}
