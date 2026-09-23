// 대화·요청 (UI-01).
//
// **이것은 새 대화 화면이 아니다.** 기본 대화 화면·초안 복구·알림은 UI-03 이다. 여기서는
// UI-01 이 고정한 계약을 관리 화면에서 **보이게** 한다 — 준비 단계, 메시지와 접수 상태,
// 현재 요청과 전송 잠금, 최초 업무화, 보관.
//
// 이 화면이 지키는 것 넷.
//
//   **보낼 수 있는지는 서버가 말한다.** `send.general` 을 그대로 보이고, 버튼이 꺼져
//   있어도 서버가 같은 이유로 거부한다. 화면이 스스로 판단하면 둘이 어긋난다(FR-11).
//
//   **접수 대기와 접수를 구별한다.** 202 는 접수가 아니다. `stored` 가 될 때만 입력을
//   비운다 — 저장되지 않은 말을 보낸 것처럼 지우지 않는다(D-83).
//
//   **대기열을 만들지 않는다.** 처리 중에 막힌 입력은 입력창에 남고 자동으로 보내지지
//   않는다(D-70).
//
//   **보관은 종료가 아니다.** 보관 버튼 옆에 종료 상태를 따로 보인다(D-69).

import { useState } from 'react'

import {
  ApiError,
  api,
  codingCliTools,
  conversationApi,
  CONVERSATION_REFUSAL_LABEL,
  RECEIPT_LABEL,
  REFUSAL_LABEL,
  REQUEST_STATE_LABEL,
  type CaseDetail,
  type ConversationMessage,
  type RunnerInfo,
} from './api'

const PROFILE_OPTIONS = [
  { value: 'feature', label: '기능 개발' },
  { value: 'defect_fix', label: '결함 수정' },
  { value: 'root_cause_analysis', label: '원인 분석' },
  { value: 'research', label: '조사·연구' },
  { value: 'refactoring', label: '리팩터링' },
  { value: 'maintenance', label: '유지 보수' },
]

const STAGE_LABEL: Record<string, string> = {
  discussion: '준비 단계 (목표·Profile 미정)',
  work: '업무 단계',
}

function describeError(err: unknown): string {
  if (err instanceof ApiError && err.detail && typeof err.detail === 'object') {
    const detail = err.detail as {
      refusals?: string[]
      message?: string
      admission?: { refusals: string[] }
    }
    const codes = detail.refusals ?? detail.admission?.refusals ?? []
    if (codes.length) {
      return codes
        .map((code) => CONVERSATION_REFUSAL_LABEL[code] ?? REFUSAL_LABEL[code] ?? code)
        .join(' · ')
    }
    if (detail.message) return detail.message
  }
  return err instanceof Error ? err.message : String(err)
}

function newClientId(): string {
  // 전송 식별자. 같은 값의 재전송은 새 메시지를 만들지 않는다.
  const random =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `web-${random}`.slice(0, 64)
}

export function ConversationPanel(props: {
  detail: CaseDetail
  runners: RunnerInfo[]
  onChanged: () => void
}) {
  const { detail } = props
  const view = detail.conversation
  const [text, setText] = useState('')
  const [kind, setKind] = useState<'general' | 'correction'>('general')
  const [correctsId, setCorrectsId] = useState('')
  const [pendingClientId, setPendingClientId] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [profile, setProfile] = useState('feature')
  const runnerId = props.runners[0]?.id
  const cliTools = codingCliTools(props.runners).map((t) => t.tool_id)

  if (!view) return null
  const current = view.current_request
  const general = view.send.general
  const userMessages = view.messages.filter(
    (m) => m.author === 'user' && m.message_kind !== 'card_answer',
  )
  const workCandidates = current
    ? userMessages.filter((m) => m.request_id === current.id && m.receipt === 'stored')
    : []

  const guard = async (fn: () => Promise<void>) => {
    try {
      setNotice(null)
      await fn()
    } catch (err) {
      setNotice(describeError(err))
    }
    props.onChanged()
  }

  // 접수 대조. **stored 가 될 때만** 입력을 비운다. 응답이 없던 전송도 같은 식별자로
  // 다시 물어 받았는지 확인한다.
  const confirmReceipt = async (clientId: string) => {
    for (let i = 0; i < 20; i += 1) {
      try {
        const found = await conversationApi.findByClientId(detail.id, clientId)
        if (found.receipt === 'stored') {
          setText('')
          setPendingClientId(null)
          setNotice('접수됨 — PC가 원문을 저장했다.')
          return
        }
        if (found.receipt === 'lost_before_persist') {
          setPendingClientId(null)
          setNotice('저장 전에 유실됐다. 입력은 그대로 있다 — 다시 보내면 새 전송이 된다.')
          return
        }
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 404)) throw err
      }
      await new Promise((resolve) => setTimeout(resolve, 500))
    }
    setNotice('아직 접수 대기다(PC 저장 전). 입력은 지우지 않았다 — 나중에 다시 확인한다.')
  }

  const describeMessage = (m: ConversationMessage) => {
    const parts = [`#${m.seq}`, m.author === 'user' ? '사용자' : 'AI', m.message_kind]
    if (m.corrects_message_id) parts.push(`정정 대상 ${m.corrects_message_id}`)
    if (m.question_id) parts.push(`질문 ${m.question_id}`)
    return parts.join(' · ')
  }

  return (
    <div className="subpanel">
      <h3>대화·요청 (UI-01)</h3>
      <p className="small">
        {STAGE_LABEL[view.stage] ?? view.stage} · 출처 {view.stage_source} · 종료 상태{' '}
        {view.status}
        {view.profile && ` · Profile ${view.profile} v${view.profile_version} (${view.profile_source})`}
        {view.visibility.archived && ' · 보관됨(종료 아님)'}
        {view.needs_response && ' · 답변이 필요한 질문이 있다'}
      </p>
      {notice && <div className="notice">{notice}</div>}

      <ul className="list">
        {view.messages.map((m) => (
          <li key={m.id} className="small">
            <span className="mono">{describeMessage(m)}</span> — {m.summary}{' '}
            <span className={m.receipt === 'stored' ? 'muted' : 'warn'}>
              [{RECEIPT_LABEL[m.receipt]}]
            </span>
            {m.corrected_by.length > 0 && (
              <span className="muted"> · 정정됨({m.corrected_by.length})</span>
            )}
          </li>
        ))}
        {view.messages.length === 0 && <li className="muted">아직 메시지가 없다</li>}
      </ul>

      <h4>현재 요청</h4>
      {current ? (
        <div className="small">
          <p>
            {current.id} · {REQUEST_STATE_LABEL[current.state]} · 여는 메시지{' '}
            {RECEIPT_LABEL[current.opening_receipt]} · 실행 {current.runs.length}건(미종료{' '}
            {current.unfinished_runs}, 불명 {current.unknown_runs})
          </p>
          <button
            type="button"
            disabled={current.state !== 'processing' || !cliTools.length}
            onClick={() =>
              guard(async () => {
                const opening = view.messages.find((m) => m.id === current.opened_by_message_id)
                if (!opening) return
                const tool = cliTools[0]
                await api.createRun(detail.id, opening.artifact_id, `run-reply-${Date.now()}`, {
                  purpose: 'discussion_reply',
                  role: 'author',
                  tool_id: tool,
                  mode: tool === 'claude' ? 'print' : 'exec',
                  permission: 'read_only',
                  instruction_artifact_rev: opening.artifact_rev,
                  request_id: current.id,
                })
                setNotice('논의 응답 실행을 만들었다. Runner 가 끝내면 AI 메시지로 붙는다.')
              })
            }
          >
            논의 응답 실행 (읽기 전용)
          </button>{' '}
          {/* 요청 종료는 **요청을 처리하는 쪽**의 기록이다. 실행이 끝나지 않았으면 서버가
              거부한다 — 실행 사이에 잠금을 풀지 않는다. */}
          <button
            type="button"
            disabled={current.state !== 'processing'}
            onClick={() => guard(async () => void (await conversationApi.settle(detail.id, current.id, 'completed')))}
          >
            처리 완료 기록
          </button>{' '}
          <button
            type="button"
            disabled={current.state !== 'processing'}
            onClick={() => guard(async () => void (await conversationApi.settle(detail.id, current.id, 'failed')))}
          >
            처리 실패 기록
          </button>
        </div>
      ) : (
        <p className="muted small">처리 중인 요청이 없다.</p>
      )}

      <h4>메시지 보내기</h4>
      {!general.allowed && (
        <p className="warn small">
          지금은 보낼 수 없다: {CONVERSATION_REFUSAL_LABEL[general.refusal ?? ''] ?? general.detail}
          {' '}— 입력은 편집할 수 있고 자동으로 보내지지 않는다.
        </p>
      )}
      <form
        onSubmit={async (event) => {
          event.preventDefault()
          if (!runnerId) {
            setNotice('등록된 Runner가 없어 원문을 저장할 수 없다.')
            return
          }
          if (!text.trim()) return
          // 같은 입력을 다시 보내면 같은 식별자를 쓴다 — 응답을 못 받은 전송이 두 번
          // 접수되지 않는다.
          const clientId = pendingClientId ?? newClientId()
          setPendingClientId(clientId)
          await guard(async () => {
            await conversationApi.send(detail.id, {
              client_message_id: clientId,
              kind,
              content: text,
              // **본문에서 잘라 내지 않는다.** 요약은 제어부에 남는 목록용 표시이고, 본문
              // 앞부분을 넣으면 PC 에만 있어야 할 원문이 서버에 복제된다(D-51·D-84).
              summary: `${kind === 'correction' ? '정정' : '사용자'} 메시지 · ${text.length}자`,
              target_runner_id: runnerId,
              ...(kind === 'correction' ? { corrects_message_id: correctsId } : {}),
            })
            await confirmReceipt(clientId)
          })
        }}
      >
        <select value={kind} onChange={(e) => setKind(e.target.value as 'general' | 'correction')}>
          <option value="general">일반 메시지</option>
          <option value="correction">보낸 메시지 정정 (새 메시지)</option>
        </select>
        {kind === 'correction' && (
          <select value={correctsId} onChange={(e) => setCorrectsId(e.target.value)}>
            <option value="">정정할 메시지 선택</option>
            {userMessages.map((m) => (
              <option key={m.id} value={m.id}>
                #{m.seq} {m.summary}
              </option>
            ))}
          </select>
        )}
        <textarea
          value={text}
          rows={3}
          placeholder="메시지 — 본문은 PC에 저장되고 제어부에는 참조만 남는다"
          onChange={(e) => {
            setText(e.target.value)
            // 내용을 바꾸면 새 전송이다.
            setPendingClientId(null)
          }}
        />
        <button type="submit" disabled={!general.allowed}>
          보내기
        </button>
      </form>

      {view.stage === 'discussion' && current && current.state === 'processing' && (
        <>
          <h4>업무로 전환</h4>
          <p className="muted small">
            처리 중 요청의 <strong>저장된</strong> 사용자 메시지가 위임 근거가 된다. 앞선 논의·동의는
            문맥이지 위임이 아니다. Autonomy·예산·저장소 선택은 그대로 이어진다.
          </p>
          <select value={profile} onChange={(e) => setProfile(e.target.value)}>
            {PROFILE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>{' '}
          {workCandidates.map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() =>
                guard(async () => {
                  await conversationApi.startWork(detail.id, m.id, profile, m.summary)
                  setNotice('같은 대화에서 업무로 전환했다.')
                })
              }
            >
              #{m.seq} 로 업무 시작
            </button>
          ))}
          {workCandidates.length === 0 && (
            <span className="muted small"> 저장된 요청 메시지가 아직 없다.</span>
          )}
        </>
      )}

      <p className="small">
        <button
          type="button"
          onClick={() =>
            guard(async () => {
              if (view.visibility.archived) await conversationApi.restore(detail.id)
              else await conversationApi.archive(detail.id)
            })
          }
        >
          {view.visibility.archived ? '보관 해제' : '보관'}
        </button>{' '}
        <span className="muted">보관은 목록 정리이며 종료·취소·실행 중단이 아니다.</span>
      </p>
      {!view.send.runner_connection_enforced && (
        <p className="muted small">
          PC 연결 상태에 따른 전송 차단·재연결 대조는 아직 없다(UI-02). 접수는 PC 저장 보고로만
          확정된다.
        </p>
      )}
    </div>
  )
}
