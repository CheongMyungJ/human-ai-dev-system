// 작업 수준 · 설계안 · 개발계획 · 단계별 사람 검토 (P3-01).
//
// 이 화면이 지키는 것 셋.
//
//   **"이 정도 준비가 필요한 이유"가 보인다.** 축마다 판단·미확인·영향을 따로 보이고
//   총점이나 평균을 만들지 않는다(sizing-and-review-ux 1절). AI 제안과 도출값이
//   다르면 둘 다 보인다 — 조용한 하향이 드러나야 한다.
//
//   **설계와 개발계획을 각각 조회한다.** 한 화면에 나란히 보이되 버전·항목·검토
//   상태는 따로다(intent-artifacts 2절).
//
//   **자동 진행을 `사람 승인됨` 으로 표시하지 않는다.** `자동 조건 충족` 이라고
//   쓰고 사람 검토 기록이 없다는 사실을 함께 보인다(sizing-and-review-ux 2·5절).
//
// 그리고 이 화면의 버튼은 조건이 아니다. 서버가 같은 요청을 같은 사유로 거부한다.

import { useState } from 'react'

import {
  AXIS_WEIGHT_LABEL,
  ApiError,
  CONFIRMATION_LABEL,
  ORIGIN_LABEL,
  REVIEW_MODE_LABEL,
  SIZING_AXIS_LABEL,
  SIZING_SOURCE_LABEL,
  STAGE_LABEL,
  STAGE_STATE_LABEL,
  WORK_LEVEL_LABEL,
  intentApi,
  preparationApi,
  type CaseDetail,
  type PreparationStage,
  type StageState,
  type WorkLevel,
} from './api'

const LEVELS: WorkLevel[] = ['simple', 'standard', 'deep']

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (typeof err.detail === 'string') return err.detail
    if (err.detail && typeof err.detail === 'object' && 'message' in err.detail) {
      return String((err.detail as { message: unknown }).message)
    }
  }
  return err instanceof Error ? err.message : String(err)
}

export function PreparationPanel(props: { detail: CaseDetail; onChanged: () => void }) {
  const prep = props.detail.preparation
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [original, setOriginal] = useState<{ title: string; body: string } | null>(null)

  const guard = async (work: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await work()
    } catch (err) {
      setError(describeError(err))
    } finally {
      setBusy(false)
      props.onChanged()
    }
  }

  return (
    <section className="subpanel">
      <h3>작업 수준과 준비 산출물</h3>
      <p className="muted small">
        기능 구현은 <strong>필요한 준비가 실제로 갖춰진 뒤에만</strong> 배정된다(FR-29).
        빠진 것은 아래에 그대로 보이고, 실행 요청을 보내면 서버가 같은 사유로 거부한다.
      </p>

      {error && <p className="error">{error}</p>}
      {note && <p className="notice">{note}</p>}

      <SizingBlock
        detail={props.detail}
        busy={busy}
        onAdjust={(level, reason, risk) =>
          guard(async () => {
            const next = await preparationApi.adjustLevel(
              props.detail.id,
              level,
              reason,
              risk,
            )
            setNote(
              `작업 수준을 ${WORK_LEVEL_LABEL[next.level]} 로 조정했다.` +
                ' 검토 옵션·성공 기준·의도 동의는 그대로다.',
            )
          })
        }
      />

      <h4>단계별 산출물과 검토</h4>
      <p className="muted small">
        두 단계는 <strong>서로 독립된 옵션</strong>이다. 프로젝트 기본값은 둘 다 사람
        검토이며, 한 단계를 자동 진행으로 바꿔도 다른 단계는 그대로다.
      </p>
      {(['design', 'plan'] as PreparationStage[]).map((stage) => (
        <StageBlock
          key={stage}
          stage={stage}
          state={prep[stage]}
          level={prep.level}
          busy={busy}
          onSetMode={(mode, reason) =>
            guard(async () => {
              await preparationApi.setMode(props.detail.id, stage, mode, reason)
              setNote(
                `${STAGE_LABEL[stage]} 검토 방식을 ${REVIEW_MODE_LABEL[mode]} 로 바꿨다.` +
                  ' 산출물과 성공 기준은 그대로 필요하다.',
              )
            })
          }
          onReview={(text) =>
            guard(async () => {
              await preparationApi.review(props.detail.id, stage, text)
              setNote(`${STAGE_LABEL[stage]}을 사람이 검토한 것으로 기록했다.`)
            })
          }
          onAutoProceed={() =>
            guard(async () => {
              await preparationApi.autoProceed(props.detail.id, stage)
              setNote(
                `${STAGE_LABEL[stage]}의 자동 진행 조건 충족을 기록했다.` +
                  ' 이것은 사람 승인이 아니다.',
              )
            })
          }
          onOpenOriginal={() =>
            guard(async () => {
              const artifact = prep[stage].artifact
              if (!artifact) return
              const opened = await intentApi.openRead(
                artifact.artifact_id,
                artifact.artifact_rev,
              )
              // 소유 Runner가 **폴링으로** 가져가므로 한 번 물어보고 없다고 하면
              // 사람은 늘 "아직 오지 않았다"만 보게 된다. 의도 원문 열람과 같은
              // 방식으로 잠깐 기다렸다 다시 확인한다.
              for (let attempt = 0; attempt < 15; attempt += 1) {
                const fetched = await intentApi.fetchRead(opened.id)
                if (fetched.content !== null) {
                  setOriginal({
                    title: `${STAGE_LABEL[stage]} 원문 v${artifact.revision}`,
                    body: fetched.content,
                  })
                  return
                }
                if (fetched.request.state === 'expired' || fetched.request.state === 'delivered') {
                  setNote(
                    `원문 중계가 ${fetched.request.state} 상태다.` +
                      ' 원문이 사라진 것은 아니며 다시 요청할 수 있다.',
                  )
                  return
                }
                await new Promise((resolve) => setTimeout(resolve, 700))
              }
              setNote(
                'Runner가 아직 원문을 올리지 않았다 — PC 연결이 필요하다.' +
                  ' 원문이 사라진 것은 아니다.',
              )
            })
          }
        />
      ))}

      {prep.deferred_open_questions.length > 0 && (
        <>
          <h4>설계·계획으로 이월한 질문</h4>
          <p className="muted small">
            이월은 “AI가 알아서 정한다”가 아니다. <strong>해당 작업 전에 사람이
            결정한다</strong> — 아래가 남아 있으면 기능 구현이 배정되지 않는다(FR-03).
          </p>
          <ul className="list">
            {prep.deferred_open_questions.map((question) => (
              <li key={question.id} className="small">
                <strong>{question.question_key}</strong> · {question.summary} · 결정 단계{' '}
                {question.decide_at}
                {question.raised_in_stage ? ` · ${question.raised_in_stage} 에서 제기` : ''}
              </li>
            ))}
          </ul>
        </>
      )}

      {original && (
        <div className="original">
          <h4>{original.title}</h4>
          <p className="muted small">
            이 원문은 소유 Runner에서 <strong>일시 중계</strong>로 왔고 제어부에
            보관되지 않는다. 창을 닫으면 버퍼에서 사라진다.
          </p>
          <pre>{original.body}</pre>
          <button type="button" onClick={() => setOriginal(null)}>
            닫기
          </button>
        </div>
      )}
    </section>
  )
}

function SizingBlock(props: {
  detail: CaseDetail
  busy: boolean
  onAdjust: (level: WorkLevel, reason: string, risk: string) => void
}) {
  const prep = props.detail.preparation
  const sizing = prep.sizing
  const [level, setLevel] = useState<WorkLevel>(prep.level ?? 'standard')
  const [reason, setReason] = useState('')
  const [risk, setRisk] = useState('')

  if (sizing === null) {
    return (
      <>
        <h4>작업 수준</h4>
        <p className="notice">
          <strong>수준 미결정.</strong> 의도 초안에 축별 판단이 없다. 이 상태를 “간소”로
          읽지 않으며, 기능 구현은 <span className="mono">sizing_not_decided</span> 로
          거부된다. 축별 판단이 있는 의도 초안이 먼저 필요하다.
        </p>
      </>
    )
  }

  const lowered = sizing.recommended_level !== sizing.level
  return (
    <>
      <h4>작업 수준 — {WORK_LEVEL_LABEL[sizing.level]}</h4>
      <p className="small">
        {SIZING_SOURCE_LABEL[sizing.source] ?? sizing.source} · 제안{' '}
        {WORK_LEVEL_LABEL[sizing.recommended_level]} · 축에서 도출{' '}
        {WORK_LEVEL_LABEL[sizing.derived_level]}
        {sizing.adjusted_from
          ? ` · 이전 수준 ${WORK_LEVEL_LABEL[sizing.adjusted_from]}`
          : ''}
      </p>
      {lowered && sizing.source !== 'human_adjustment' && (
        <p className="notice">
          제안({WORK_LEVEL_LABEL[sizing.recommended_level]})이 축에서 도출한 수준
          ({WORK_LEVEL_LABEL[sizing.derived_level]})보다 낮아{' '}
          <strong>낮은 쪽을 쓰지 않았다.</strong> 수준을 낮추는 것은 사람만 할 수 있고
          이유와 남는 위험이 기록된다.
        </p>
      )}
      {sizing.evidence_gap && (
        <p className="notice">
          <strong>근거가 부족한 축이 있다.</strong> 모르는 것을 “영향 없음”으로 읽지
          않는다. 아래 표에서 조사할 축을 확인한다.
        </p>
      )}
      {sizing.source === 'human_adjustment' && (
        <p className="small">
          조정 이유: {sizing.reason_summary} · 남는 위험: {sizing.residual_risk_summary}
        </p>
      )}

      <table>
        <thead>
          <tr>
            <th>판단 축</th>
            <th>준비·검증에 주는 영향</th>
            <th>현재 판단</th>
            <th>아직 확인할 것</th>
          </tr>
        </thead>
        <tbody>
          {sizing.axes.map((axis) => (
            <tr key={axis.axis}>
              <td className="small">{SIZING_AXIS_LABEL[axis.axis] ?? axis.axis}</td>
              <td className="small">{AXIS_WEIGHT_LABEL[axis.weight]}</td>
              <td className="small">{axis.judgement_summary}</td>
              <td className="small muted">{axis.unconfirmed_summary || '적히지 않음'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">
        축을 <strong>점수로 합산하지 않는다.</strong> 낮은 축들의 평균으로 권한·
        마이그레이션 같은 중요한 영향을 상쇄하지 않기 위해서다.
      </p>

      <form
        className="draft-form"
        onSubmit={(event) => {
          event.preventDefault()
          props.onAdjust(level, reason, risk)
          setReason('')
          setRisk('')
        }}
      >
        <div className="field">
          <label>수준 조정</label>
          <select value={level} onChange={(event) => setLevel(event.target.value as WorkLevel)}>
            {LEVELS.map((value) => (
              <option key={value} value={value}>
                {WORK_LEVEL_LABEL[value]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>조정 이유 (필수)</label>
          <input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="왜 이 수준인가"
          />
        </div>
        <div className="field">
          <label>남는 위험 (필수)</label>
          <input
            value={risk}
            onChange={(event) => setRisk(event.target.value)}
            placeholder="이 조정으로 확인하지 않고 남는 것"
          />
        </div>
        <button type="submit" disabled={props.busy || !reason.trim() || !risk.trim()}>
          수준 조정
        </button>
        <p className="muted small">
          조정은 <strong>의도 동의·성공 기준·검토 옵션을 해제하지 않는다.</strong>
          바뀌는 것은 산출물에 요구되는 항목의 범위다.
        </p>
      </form>

      {prep.sizing_history.length > 1 && (
        <>
          <h4>수준 판단 이력</h4>
          <ul className="list">
            {prep.sizing_history.map((row) => (
              <li key={row.id} className="muted small">
                v{row.revision} · {SIZING_SOURCE_LABEL[row.source] ?? row.source} ·{' '}
                {WORK_LEVEL_LABEL[row.level]} · {row.state} · {row.created_at}
                {row.reason_summary ? ` · ${row.reason_summary}` : ''}
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  )
}

function StageBlock(props: {
  stage: PreparationStage
  state: StageState
  level: WorkLevel | null
  busy: boolean
  onSetMode: (mode: 'human_review' | 'auto_proceed', reason: string) => void
  onReview: (note: string) => void
  onAutoProceed: () => void
  onOpenOriginal: () => void
}) {
  const { state, stage } = props
  const [reviewNote, setReviewNote] = useState('')
  const [modeReason, setModeReason] = useState('')
  const artifact = state.artifact

  return (
    <div className="subpanel">
      <h4>
        {STAGE_LABEL[stage]} — {STAGE_STATE_LABEL[state.state]}
      </h4>
      <p className="small">
        검토 방식: <strong>{REVIEW_MODE_LABEL[state.mode]}</strong> (
        {state.mode_source === 'project_default' ? '프로젝트 기본값' : '이 업무의 설정'}
        {state.mode_source === 'case_setting' ? ` — ${state.mode_reason}` : ''})
      </p>

      {artifact === null ? (
        <p className="notice muted">
          아직 산출물이 없다. {STAGE_LABEL[stage]} 작성 실행(
          <span className="mono">{stage}_authoring</span>)을 배정하면 AI가 작성한다.
          {stage === 'plan' && ' 개발계획은 검토를 마친 설계 위에서만 작성된다.'}
        </p>
      ) : (
        <>
          <p className="small">
            v{artifact.revision} · 수준 {WORK_LEVEL_LABEL[artifact.level]} · 기준 의도{' '}
            <span className="mono">{artifact.intent_version_id}</span> · 원문{' '}
            {artifact.availability}
            {artifact.based_on_design_id ? ' · 현재 설계 위에 세움' : ''}
          </p>
          {state.stale && (
            <p className="notice">
              <strong>새 의도 버전이 생겼다.</strong> 이 산출물은 대체된 의도 위에
              세워져 있어 이전 검토를 재사용하지 않는다. 최신 의도 기준으로 다시 만든다.
            </p>
          )}
          <table>
            <thead>
              <tr>
                <th>항목</th>
                <th>이 수준에서</th>
                <th>상태</th>
                <th>내용의 성격</th>
              </tr>
            </thead>
            <tbody>
              {artifact.sections.map((section) => (
                <tr key={section.section}>
                  <td className="small">{section.label}</td>
                  <td className="small">{section.required ? '필수' : '선택'}</td>
                  <td className="small">
                    {CONFIRMATION_LABEL[section.state] ?? section.state}
                  </td>
                  <td className="small muted">
                    {ORIGIN_LABEL[section.origin] ?? section.origin}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {state.missing_required_sections.length > 0 && (
            <p className="notice">
              현재 수준이 요구하는 항목이 미정이다:{' '}
              <span className="mono">{state.missing_required_sections.join(', ')}</span>.
              <strong> 사람 검토가 이 빈 항목을 채우지 않는다</strong> — 이대로는 기능
              구현이 배정되지 않는다.
            </p>
          )}
          <button type="button" onClick={props.onOpenOriginal} disabled={props.busy}>
            원문 열람 (일시 중계)
          </button>

          {state.review ? (
            <p className="small">
              {STAGE_STATE_LABEL[state.review.state]} · {state.review.actor} ·{' '}
              {state.review.recorded_at}
              {state.review.decision_id === null
                ? ' · 사람 승인 기록 없음 (자동 조건 충족)'
                : ` · 결정 기록 ${state.review.decision_id}`}
              {state.review.note_summary ? ` · ${state.review.note_summary}` : ''}
            </p>
          ) : state.mode === 'human_review' ? (
            <form
              className="draft-form"
              onSubmit={(event) => {
                event.preventDefault()
                props.onReview(reviewNote)
                setReviewNote('')
              }}
            >
              <div className="field">
                <label>검토 메모 (짧게)</label>
                <input
                  value={reviewNote}
                  onChange={(event) => setReviewNote(event.target.value)}
                  placeholder="원문을 읽고 확인한 것"
                />
              </div>
              <button type="submit" disabled={props.busy}>
                이 {STAGE_LABEL[stage]}을 검토했다
              </button>
              <p className="muted small">
                <strong>화면을 열어 본 것은 검토가 아니다.</strong> 이 버튼이 사람의
                검토 결정을 기록한다.
              </p>
            </form>
          ) : (
            <>
              <button type="button" onClick={props.onAutoProceed} disabled={props.busy}>
                자동 진행 조건 충족 기록
              </button>
              <p className="muted small">
                이것은 <strong>사람 승인이 아니다.</strong> 산출물과 수준이 요구하는
                항목이 갖춰졌다는 사실만 기록하며, 사람 검토 결정은 만들지 않는다.
              </p>
            </>
          )}
        </>
      )}

      <form
        className="draft-form"
        onSubmit={(event) => {
          event.preventDefault()
          const next = state.mode === 'human_review' ? 'auto_proceed' : 'human_review'
          props.onSetMode(next, modeReason)
          setModeReason('')
        }}
      >
        <div className="field">
          <label>검토 방식 변경 이유</label>
          <input
            value={modeReason}
            onChange={(event) => setModeReason(event.target.value)}
            placeholder={
              state.mode === 'human_review' ? '자동 진행을 고르는 이유 (필수)' : '되돌리는 이유'
            }
          />
        </div>
        <button
          type="submit"
          disabled={props.busy || (state.mode === 'human_review' && !modeReason.trim())}
        >
          {state.mode === 'human_review' ? '자동 진행으로 바꾸기' : '사람 검토로 되돌리기'}
        </button>
      </form>
    </div>
  )
}
