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

import { useState } from 'react'

import {
  ApiError,
  AUTONOMY_LABEL,
  AUTONOMY_SOURCE_LABEL,
  CHECKPOINT_LABEL,
  policyApi,
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

      {/* --- controlled 확인 지점 ------------------------------------ */}
      {policy.checkpoints.length > 0 && (
        <div className="task">
          <div className="task-head">
            <strong>확인 지점</strong>
            <EnforcementTag note={policy.enforcement.controlled_checkpoint} />
          </div>
          <ul className="list">
            {policy.checkpoints.map((point) => (
              <li key={point.id} className="small">
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
            이 확인은 <strong>push·게시 권한이나 최종 인수를 만들지 않는다</strong>(D-65).
            각각 별도 기록이다.
          </p>
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
              <span className="muted">측정 {row.measurement}</span>
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
        {/* 사용량을 0으로 보이지 않는다. 미측정과 0은 다르다(D-61). */}
        <p className="muted small">사용량: 측정하지 않음 — {budget.usage_detail}</p>
        <p className="muted small">{budget.repair_limit_note}</p>
        <div className="row">
          <select value={metric} onChange={(event) => setMetric(event.target.value)}>
            {Object.entries(budget.measurement_contract).map(([name, measurement]) => (
              <option key={name} value={name}>
                {name} (측정 {measurement})
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
