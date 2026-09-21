// 정책 — **어떤 목적·깊이·확인 경계·한도로 진행하는가, 그리고 그것이 실제로
// 강제되는가** (P3-R1).
//
// 이 화면이 지키는 것 넷.
//
//   **기록과 강제를 구별한다.** 값이 저장됐다는 사실은 동작이 바뀐다는 뜻이 아니다.
//   서버가 준 `enforcement` 문구를 그대로 보인다 — 화면이 지어내면 hard 한도를 설정한
//   사람이 상한이 있다고 믿는다(D-61).
//
//   **미기록을 기본값으로 칠하지 않는다.** R1 이전 Case 의 Autonomy 는 기록되지
//   않았고 `ask-on-decision` 이 아니다. 기본값이 무엇인지는 보여 주되 그것이 이
//   Case 에 적용됐다고 말하지 않는다.
//
//   **네 축을 한 줄로 합치지 않는다.** WorkDepth(깊이), Autonomy(확인 경계),
//   Budget(한도), Profile(목적)은 서로 다른 설정이며 하나가 다른 하나를 대신하지
//   않는다(D-59).
//
//   **선택·쓰기 허용·게시 허용을 따로 보인다.** 쓰기 허용이 게시 허용으로 보이면
//   D-64가 화면에서 깨진다.
//
// P3-R4가 더한 것 셋. 전부 **같은 규칙의 다른 얼굴**이다 — 방식과 결과를 구별한다.
//
//   **가벼운 확인과 독립 의미 검토를 같은 `통과` 로 보이지 않는다.** 방식과 보지
//   않은 범위를 함께 적는다. 합치면 "미실행을 통과로 표시하지 않는다"(D-25)가
//   화면에서 깨진다.
//
//   **도출된 값과 사람이 정한 값을 구별한다.** 완료 모드와 유효 Autonomy 는
//   Autonomy 에서 도출될 수 있고, 그 사실이 보이지 않으면 고르지 않은 자동 완료가
//   사용자의 설정처럼 읽힌다.
//
//   **누적 변경이 무엇을 막는지 보인다.** 사람이 확인해야 할 것과 이미 위임된 것을
//   같은 목록에 섞지 않는다(D-60).

import { useState } from 'react'

import {
  ApiError,
  AUTONOMY_LABEL,
  AUTONOMY_SOURCE_LABEL,
  CHECKPOINT_LABEL,
  COMPLETION_SOURCE_LABEL,
  CONFORMANCE_METHOD_LABEL,
  MATERIALITY_LABEL,
  policyApi,
  progressionApi,
  type Autonomy,
  type CaseDetail,
  type CasePolicy,
} from './api'

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (typeof err.detail === 'string') return err.detail
    if (err.detail && typeof err.detail === 'object') {
      const detail = err.detail as { message?: unknown; refusals?: unknown }
      if (Array.isArray(detail.refusals) && detail.refusals.length) {
        return `거부: ${detail.refusals.join(', ')}`
      }
      if (detail.message) return String(detail.message)
    }
  }
  return err instanceof Error ? err.message : String(err)
}

function EnforcementTag(props: { note: { state: string; enforced_by: string; detail: string } }) {
  const { note } = props
  return (
    <span className="muted small" title={note.detail}>
      {note.state === 'recorded_not_enforced'
        ? `기록됨 · 아직 강제하지 않음 (${note.enforced_by})`
        : note.state === 'enforced'
          ? `강제함 (${note.enforced_by})`
          : `미구현 (${note.enforced_by})`}
    </span>
  )
}

/** 보장 범위를 사람 말로. **셋을 한 단어로 합치지 않는다**(D-61). */
function guaranteeLabel(guarantee: string | undefined): string {
  switch (guarantee) {
    case 'absolute':
      return '절대 상한'
    case 'no_absolute_cap':
      return '새 배정만 차단 (절대 상한 아님)'
    case 'display_only':
      return '표시만'
    case 'not_enforceable':
      return '강제 불가'
    default:
      return '보장 범위 미표시'
  }
}

/** 바이트·초가 소수점으로 길어지지 않게. 값을 **반올림할 뿐 바꾸지 않는다.** */
function round2(value: number): number {
  return Math.round(value * 100) / 100
}

export function PolicyPanel(props: {
  detail: CaseDetail
  onChanged: () => void | Promise<void>
}) {
  const policy: CasePolicy | undefined = props.detail.policy
  const [error, setError] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [metric, setMetric] = useState('run_count')
  const [threshold, setThreshold] = useState('hard')
  const [limit, setLimit] = useState('5')

  if (!policy) return null

  const guard = async (fn: () => Promise<void>) => {
    try {
      setError(null)
      await fn()
      await props.onChanged()
    } catch (err) {
      setError(describeError(err))
    }
  }

  const profile = policy.profile
  const budget = policy.budget

  return (
    <section className="subpanel">
      <h3>정책 · Profile · 예산</h3>
      {error && <p className="error">{error}</p>}

      {/* --- 목적 ---------------------------------------------------- */}
      <div className="task">
        <div className="task-head">
          <strong>대표 목적</strong>
          {profile.profile ? (
            <>
              <span className="tag">{profile.profile}</span>
              <span className="muted small">정의판 v{profile.version}</span>
              <span className="muted small">
                {profile.source === 'explicit' ? '사람이 지정' : 'kind 에서 유도'}
              </span>
            </>
          ) : (
            <span className="muted">기록되지 않음</span>
          )}
        </div>
        {profile.detail && <p className="muted small">{profile.detail}</p>}
        {profile.definition && (
          <>
            <p className="muted small">{profile.definition.purpose}</p>
            <p className="small">
              <strong>정상 완료의 의미:</strong> {profile.definition.completion_meaning}
            </p>
            <p className="muted small">
              <strong>최소 증거 기대:</strong> {profile.definition.minimum_evidence}
            </p>
            <p className="muted small">
              <strong>초안에서 고정하지 않는 것:</strong> {profile.definition.not_fixed_in_draft}
            </p>
            <p className="muted small">
              의도 항목: {profile.definition.common_fields.join(', ')} +{' '}
              {profile.definition.semantic_fields.map((f) => f.field).join(', ')}
            </p>
          </>
        )}
      </div>

      {/* --- 깊이와 확인 경계 ---------------------------------------- */}
      <div className="task">
        <div className="task-head">
          <strong>깊이 (WorkDepth)</strong>
          <span className="tag">{policy.work_depth ?? '아직 판단되지 않음'}</span>
          <span className="muted small">출처: 수준 판단</span>
        </div>
        <p className="muted small">
          깊이와 확인 경계는 <strong>다른 축</strong>이다. 심층 분석을 자동 진행으로 할 수
          있다(D-59).
        </p>
      </div>

      <div className="task">
        <div className="task-head">
          <strong>확인 경계 (Autonomy)</strong>
          {policy.autonomy_recorded ? (
            <span className="tag">{AUTONOMY_LABEL[policy.autonomy as Autonomy]}</span>
          ) : (
            // 미기록을 기본값으로 칠하지 않는다. 이 Case 에 적용된 값이 없다.
            <span className="muted">기록되지 않음</span>
          )}
          <span className="muted small">
            {AUTONOMY_SOURCE_LABEL[policy.autonomy_source] ?? policy.autonomy_source} · 정책{' '}
            v{policy.policy_version}
          </span>
          <EnforcementTag note={policy.enforcement.autonomy} />
        </div>
        {!policy.autonomy_recorded && (
          <p className="muted small">
            이 업무는 v0.6 기준으로 진행했다. 시스템 기본값은{' '}
            {AUTONOMY_LABEL[policy.default_autonomy]} 이지만 <strong>이 업무에 적용된
            값은 아니다.</strong>
          </p>
        )}
        {/* **적용되는 값과 기록된 값을 구별한다**(P3-R4). 미기록 Case 는
            controlled 로 취급되지만 그 값이 기록된 것은 아니다. */}
        {policy.is_treatment && (
          <p className="muted small">
            지금 적용되는 확인 경계는{' '}
            <strong>{AUTONOMY_LABEL[policy.effective_autonomy]}</strong> 이다 —
            Autonomy 가 기록되지 않아 <strong>이행 정책으로 그렇게 취급</strong>하고
            있으며, 사람이 고른 설정이 아니다. 값을 기록하면 그때부터 그 설정을
            따른다.
          </p>
        )}
        <p className="muted small">
          완료: <strong>{policy.completion_mode}</strong> ·{' '}
          {COMPLETION_SOURCE_LABEL[policy.completion_mode_source] ??
            policy.completion_mode_source}
        </p>
        <div className="row">
          <input
            placeholder="바꾸는 이유 (짧은 요약)"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
          <button
            type="button"
            onClick={() =>
              guard(async () => {
                await policyApi.setAutonomy(policy.case_id, 'ask_on_decision', reason)
              })
            }
          >
            기본 자율 진행으로
          </button>
          <button
            type="button"
            onClick={() =>
              guard(async () => {
                await policyApi.setAutonomy(policy.case_id, 'controlled', reason)
              })
            }
          >
            확인 경계로
          </button>
        </div>
      </div>

      {/* --- 요청 정합성 확인 방식 (P3-R4) --------------------------- */}
      <div className="task">
        <div className="task-head">
          <strong>요청 정합성 확인</strong>
          {policy.conformance.method ? (
            <span className="tag ok">
              {policy.conformance.verdict === 'pass' ? '통과' : policy.conformance.verdict}
            </span>
          ) : (
            // **아직 하지 않은 것을 통과로 칠하지 않는다.**
            <span className="tag">아직 확인하지 않음</span>
          )}
        </div>
        {/* **방식을 반드시 함께 적는다.** 두 방식이 같은 `통과` 로 보이면
            "미실행을 통과로 표시하지 않는다"(D-25)가 화면에서 깨진다. */}
        {policy.conformance.method && (
          <p className="small">
            방식:{' '}
            <strong>
              {CONFORMANCE_METHOD_LABEL[policy.conformance.method] ??
                policy.conformance.method}
            </strong>
          </p>
        )}
        {policy.conformance.unverified_scope && (
          <p className="muted small">
            확인하지 않은 범위: {policy.conformance.unverified_scope}
          </p>
        )}
        <p className="muted small">
          이 업무가 요구하는 방식:{' '}
          {CONFORMANCE_METHOD_LABEL[policy.conformance.required_method] ??
            policy.conformance.required_method}
          {policy.conformance.reasons.length > 0 && (
            <> — {policy.conformance.reasons.map((r) => r.detail).join(', ')}</>
          )}
        </p>
        {/* Fast Lane 여부와 그렇지 않은 이유. **이탈은 사람 확인 요구가 아니라
            준비 추가다**(autonomy-budget-policy 4절). */}
        <p className="muted small">
          Fast Lane:{' '}
          {policy.fast_lane.eligible ? (
            <strong>적용 (결합 기록 하나로 진행)</strong>
          ) : (
            <>
              <strong>해당 없음</strong> — 설계·개발계획을 갖춘 일반 진행으로
              전환한다 ({policy.fast_lane.blockers.map((b) => b.detail).join(', ')})
            </>
          )}
        </p>
      </div>

      {/* --- 누적 변경 (P3-R4) --------------------------------------- */}
      {policy.material_delta.all.length > 0 && (
        <div className="task">
          <div className="task-head">
            <strong>마지막 위임 기준 대비 변경</strong>
            {policy.material_delta.pending.length > 0 ? (
              <span className="tag">{policy.material_delta.pending.length}건 확인 필요</span>
            ) : (
              <span className="tag ok">확인할 변경 없음</span>
            )}
          </div>
          <ul className="list">
            {policy.material_delta.all.map((row) => (
              <li key={row.id} className="small">
                {row.target_key} ·{' '}
                <span className={`tag ${row.state === 'pending' ? '' : 'ok'}`}>
                  {MATERIALITY_LABEL[row.materiality] ?? row.materiality}
                </span>{' '}
                <span className="muted">{row.detail}</span>
                {/* **AI 의 평가는 근거가 아니다.** 보이되 해소로 읽히지 않게
                    따로 적는다(D-60). */}
                {row.ai_assessment && (
                  <span className="muted"> · AI 평가(근거 아님): {row.ai_assessment}</span>
                )}
                {row.state === 'pending' && (
                  <button
                    type="button"
                    onClick={() =>
                      guard(async () => {
                        await progressionApi.confirmDelta(policy.case_id, row.id)
                      })
                    }
                  >
                    이 변경을 확인
                  </button>
                )}
              </li>
            ))}
          </ul>
          {policy.material_delta.blocks_all_tasks && (
            <p className="muted small">
              어떤 작업을 막는지 연결되지 않은 변경이 있어 <strong>전부 막는다.</strong>
            </p>
          )}
          <p className="muted small">{policy.material_delta.detail}</p>
        </div>
      )}

      {/* --- controlled 확인 지점 ------------------------------------ */}
      {policy.checkpoints.length > 0 && (
        <div className="task">
          <div className="task-head">
            <strong>확인 지점</strong>
            <EnforcementTag note={policy.enforcement.controlled_checkpoint} />
          </div>
          <ul className="list">
            {policy.checkpoints.map((point) => (
              // 취급으로 도출된 요구는 아직 행이 없어 `id` 가 없다(P3-R4).
              <li key={point.id ?? `${point.checkpoint}:${point.state}`} className="small">
                {CHECKPOINT_LABEL[point.checkpoint] ?? point.checkpoint} ·{' '}
                <span className={`tag ${point.state === 'confirmed' ? 'ok' : ''}`}>
                  {point.state}
                </span>
                {point.confirmed_by && (
                  <span className="muted">
                    {' '}
                    {point.confirmed_by} · {point.confirmed_at} · 대상 {point.subject_id}
                  </span>
                )}
                {point.state === 'required' && (
                  <button
                    type="button"
                    onClick={() =>
                      guard(async () => {
                        await policyApi.confirmCheckpoint(
                          policy.case_id,
                          point.checkpoint,
                          point.checkpoint === 'start_scope'
                            ? policy.case_id
                            : props.detail.result?.candidate?.id ?? policy.case_id,
                          reason,
                          point.checkpoint === 'start_scope'
                            ? null
                            : props.detail.result?.candidate?.snapshot_hash ?? null,
                        )
                      })
                    }
                  >
                    확인했다고 기록
                  </button>
                )}
              </li>
            ))}
          </ul>
          <p className="muted small">
            이 확인은 <strong>push·게시 권한을 만들지 않는다</strong>(D-65).
            각각 별도 기록이다. 결과 후보 확인 뒤에는 남은 조건이 갖춰지면 시스템이
            종료를 확정한다 — 같은 내용을 두 번 확인시키지 않는다.
          </p>
          {policy.is_treatment && (
            <p className="muted small">
              이 요구는 <strong>사람이 고른 설정이 아니다.</strong> Autonomy 가
              기록되지 않아 이행 정책으로 controlled 로 취급하고 있다.
            </p>
          )}
        </div>
      )}

      {/* --- 예산 ---------------------------------------------------- */}
      <div className="task">
        <div className="task-head">
          <strong>예산</strong>
          <span className="tag">{budget.unlimited ? '무제한 (기본값)' : '한도 설정됨'}</span>
          <EnforcementTag note={budget.enforcement} />
        </div>
        <ul className="list">
          {budget.limits.map((row) => (
            <li key={row.id} className="small">
              {row.metric} · {row.threshold_kind} · {row.limit_value} {row.unit} ·{' '}
              <span className="muted">측정 {row.measurement}</span> ·{' '}
              <span className="muted">{guaranteeLabel(row.guarantee)}</span>
              <button
                type="button"
                onClick={() =>
                  guard(async () => {
                    await policyApi.clearBudget(policy.case_id, row.metric, row.threshold_kind)
                  })
                }
              >
                해제
              </button>
            </li>
          ))}
        </ul>
        {/* --- 정지 ------------------------------------------------
            hard 도달은 **완료도 취소도 아니다.** 무엇이 막히고 무엇이 계속되는지,
            그리고 어떻게 재개하는지를 같은 자리에 둔다(D-61). */}
        {budget.stop.stopped && (
          <div className="notice">
            <strong>예산으로 새 실행이 중지됐다</strong>
            <ul className="list">
              {budget.stop.metrics.map((row) => (
                <li key={row.metric} className="small">
                  {row.metric} · 노출 {row.exposure} / 한도 {row.limit_value} {row.unit}
                  {row.guarantee === 'no_absolute_cap' && (
                    <span className="muted">
                      {' '}
                      — 새 배정만 막는다. 진행 중 실행의 초과 노출이 있을 수 있다
                    </span>
                  )}
                  {!row.complete && <span className="muted"> — 이 수는 소비 전부가 아니다</span>}
                </li>
              ))}
            </ul>
            <p className="muted small">{budget.stop.detail}</p>
            {budget.stop.resume && <p className="muted small">{budget.stop.resume}</p>}
          </div>
        )}

        {/* --- 경고선 ----------------------------------------------- */}
        {budget.warnings.map((row) => (
          <p key={row.metric} className="muted small">
            경고선 도달: {row.metric} {row.exposure} / {row.limit_value} {row.unit} — {row.detail}
          </p>
        ))}

        {/* --- 사용량 ------------------------------------------------
            **`exposure` 를 앞에 둔다.** 확정 사용량만 보이면 진행 중 실행과 결과
            불명이 공짜처럼 보인다. 모르는 것은 "미확정"으로 드러내고 0으로 채우지
            않는다(D-61). */}
        <ul className="list">
          {Object.values(budget.usage)
            .filter((row) => row.exposure > 0 || row.runs_unknown > 0 || row.runs_in_flight > 0)
            .map((row) => (
              <li key={row.metric} className="small">
                {row.metric} · 노출 <strong>{round2(row.exposure)}</strong> {row.unit}
                <span className="muted">
                  {' '}
                  (확정 {round2(row.settled)} · 진행 중 {round2(row.held)} · 미확정{' '}
                  {round2(row.unresolved)})
                </span>
                {!row.complete && (
                  <span className="muted">
                    {' '}
                    — 미확정 {row.runs_unknown}건, 진행 중 {row.runs_in_flight}건.{' '}
                    <strong>이 수는 소비 전부가 아니다</strong>
                  </span>
                )}
              </li>
            ))}
        </ul>
        <p className="muted small">{budget.usage_detail}</p>

        {/* --- 역할별 -------------------------------------------------
            표시용 축이다. **판정은 언제나 Case 하나로 한다** — 역할별 계산으로 Case
            한도를 우회하지 못하게 하기 위해서다(autonomy-budget-policy 8절). */}
        {Object.entries(budget.by_role).length > 0 && (
          <p className="muted small">
            역할별 실행 수:{' '}
            {Object.entries(budget.by_role)
              .map(([role, metrics]) => `${role} ${metrics.run_count?.rows ?? 0}`)
              .join(' · ')}{' '}
            — 표시용이며 한도 판정은 Case 전체로 한다
          </p>
        )}
        <p className="muted small">{budget.repair_limit_note}</p>
        <div className="row">
          <select value={metric} onChange={(event) => setMetric(event.target.value)}>
            {Object.entries(budget.reservation_contract).map(([name, contract]) => (
              <option key={name} value={name}>
                {name} (측정 {contract.measurement} · hard {guaranteeLabel(contract.hard_guarantee)})
              </option>
            ))}
          </select>
          <select value={threshold} onChange={(event) => setThreshold(event.target.value)}>
            <option value="warn">경고선</option>
            <option value="hard">hard 한도</option>
          </select>
          <input value={limit} onChange={(event) => setLimit(event.target.value)} />
          <button
            type="button"
            onClick={() =>
              guard(async () => {
                await policyApi.setBudget(policy.case_id, metric, threshold, Number(limit))
              })
            }
          >
            한도 설정
          </button>
        </div>
        <p className="muted small">
          정확히 측정할 수 없는 지표의 hard 한도는 <strong>설정이 거부된다</strong> —
          지킬 수 없는 상한을 있는 것처럼 표시하지 않는다(D-61).
        </p>
        {/* **같은 "hard" 가 지표마다 다른 것을 약속한다.** 그 차이를 숨기면 시간
            한도를 건 사람이 절대 상한을 믿게 된다. */}
        <p className="muted small">
          {budget.reservation_contract[metric]?.reason}
        </p>
      </div>

      {/* --- 저장소 -------------------------------------------------- */}
      <div className="task">
        <div className="task-head">
          <strong>저장소</strong>
          <EnforcementTag note={policy.enforcement.repository_selection} />
        </div>
        <ul className="list">
          {policy.repositories.selected.map((row) => (
            <li key={row.repository_id} className="small">
              {row.repository_name} · <code>{row.repo_path}</code> ·{' '}
              <span className="muted">선택 {row.selection_source}</span> ·{' '}
              <span className={`tag ${row.code_write_allowed ? 'ok' : ''}`}>
                코드 쓰기 {row.code_write_allowed ? '허용' : '불허'}
              </span>{' '}
              <span className={`tag ${row.publish_allowed ? 'ok' : ''}`}>
                게시 {row.publish_allowed ? '허용' : '불허'}
              </span>
            </li>
          ))}
          {policy.repositories.selected.length === 0 && (
            <li className="muted small">
              {policy.repositories.implicit_single_repository
                ? policy.repositories.implicit_single_repository.detail
                : '선택된 저장소가 없다'}
            </li>
          )}
        </ul>
        {policy.repositories.excluded.length > 0 && (
          <ul className="list">
            {policy.repositories.excluded.map((row) => (
              <li key={row.repository_id} className="small warn">
                {row.repository_name} · <strong>명시 제외</strong> — 허용 내 자동 추가가
                넘지 못하는 경계다(D-63)
              </li>
            ))}
          </ul>
        )}
        <p className="muted small">
          선택·쓰기 허용은 <strong>작업공간을 실제로 정한다</strong>(P3-R2). 쓰기 허용은
          여전히 게시 허용이 아니고(D-64), 실제 push·PR 은 구현되지 않았다. 기록 저장소는
          코드 대상에 자동으로 들어가지 않는다(D-17).
        </p>
      </div>

      {/* --- 위임 근거 ----------------------------------------------- */}
      <div className="task">
        <div className="task-head">
          <strong>위임 근거</strong>
          {policy.delegation_basis.current ? (
            <span className="tag">{policy.delegation_basis.current.basis_kind}</span>
          ) : (
            <span className="muted">기록되지 않음</span>
          )}
        </div>
        {policy.delegation_basis.current && (
          <p className="small">{policy.delegation_basis.current.summary}</p>
        )}
        <p className="muted small">{policy.delegation_basis.detail}</p>
      </div>
    </section>
  )
}
