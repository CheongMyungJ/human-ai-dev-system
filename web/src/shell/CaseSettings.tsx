// 대화의 상세 설정(UI-04b, D-72). 입력창의 적용 요약을 펼치면 오른쪽 패널의 이 탭이 열린다.
//
//   **적용 값·출처·적용 시점은 서버 값 그대로다.** 이 업무에서 정한 것, 프로젝트 기본값, 시스템 기본값을 같은
//   모양으로 보이지 않는다.
//   **기본값 복귀는 새 기록이다.** Autonomy 는 새 리비전, 진행 상한은 Case 설정을 닫는 것, 예산은 프로젝트
//   기본값을 다시 적용하는 것이다. 어느 것도 이전 값을 지우지 않는다.
//   **설정은 권한·동의·인수가 아니다.** 진입 검사·예산 강제·확인 지점은 관리 화면·카드의 것 그대로다.
//   **서버가 거부하면 그 문구를 보인다**(종료 Case 의 정책 변경, 검사 강도 낮추기, 강제 불가한 hard 한도).
//   실행 중 실행의 고정 입력과 검증 중 예약은 화면이 아니라 서버 규칙이 지킨다(P4-02·P4-04).

import { useState } from 'react'

import {
  ApiError,
  AUTONOMY_LABEL,
  AUTONOMY_SOURCE_LABEL,
  BUDGET_METRIC_NOTE,
  COMPLETION_SOURCE_LABEL,
  DEFAULT_TIME_METRIC,
  GATE_VERDICT_LABEL,
  metricLabel,
  orderMetrics,
  policyApi,
  timeSummary,
  preparationApi,
  progressApi,
  PROGRESS_LIMIT_LABEL,
  PROGRESS_LIMIT_SOURCE_LABEL,
  qualityGateApi,
  repositoryApi,
  SIZING_SOURCE_LABEL,
  WORK_LEVEL_LABEL,
  type Autonomy,
  type ProgressLimitKey,
  type ProjectRepository,
  type QualityGatePolicy,
  type WorkLevel,
} from '../api'
import { settingsLink } from '../lib/address'
import type { ShellCaseDetail } from './useCaseData'

function describe(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = err.detail as { refusals?: string[]; message?: string } | string | undefined
    if (detail && typeof detail === 'object' && Array.isArray(detail.refusals) && detail.refusals.length) {
      return `${err.status}: 거부 — ${detail.refusals.join(', ')}`
    }
    if (detail && typeof detail === 'object' && typeof detail.message === 'string') return `${err.status}: ${detail.message}`
    return `${err.status}: ${typeof detail === 'string' ? detail : err.message}`
  }
  return err instanceof Error ? err.message : String(err)
}

function when(iso: string | null | undefined): string {
  return iso ? iso.replace('T', ' ').slice(0, 19) : '—'
}

const GUARANTEE_LABEL: Record<string, string> = {
  absolute: '절대 상한',
  no_absolute_cap: '새 배정만 차단',
  display_only: '표시만',
  not_enforceable: '강제 불가',
}

const INSPECTION_LABEL: Record<string, string> = {
  rule: '규칙 검사',
  light: '가벼운 확인',
  independent: '독립 의미 검토',
}

const GATE_SETTING_LABEL: Record<string, string> = {
  required: '필수',
  on: '켬',
  off: '끔',
  not_applicable: '미적용',
}

type Guard = (fn: () => Promise<unknown>) => Promise<void>

export function CaseSettings(props: {
  caseId: string
  projectId: string
  detail: ShellCaseDetail
  repositories: ProjectRepository[]
  onChanged: () => void
}) {
  const { detail } = props
  const policy = detail.policy
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const guard: Guard = async (fn) => {
    setError(null)
    setNotice(null)
    try {
      await fn()
    } catch (err) {
      setError(describe(err))
    }
    props.onChanged()
  }
  if (!policy) return <p className="sh-muted">정책을 아직 불러오지 못했다</p>
  const closed = ['closed', 'cancelled'].includes(policy.case_status)
  return (
    <div className="sh-case-settings" data-testid="case-settings">
      <p className="sh-muted sh-rules-note">
        이 대화에 <strong>지금 적용되는 값</strong>과 그 출처다. 설정은 실행 허용·동의·인수가 아니다. 실행 중인 실행의
        고정 입력과 검증 중 예약 설정은 바뀌지 않는다(서버 규칙). 프로젝트 공통 기본값은{' '}
        <a href={settingsLink(props.projectId)} data-testid="case-settings-project-link">
          프로젝트 설정
        </a>
        에서 바꾼다 — 그 값은 이 뒤에 만드는 대화에 적용된다.
      </p>
      {error && <div className="sh-banner sh-error" data-testid="case-settings-error">{error}</div>}
      {notice && <div className="sh-banner sh-info" data-testid="case-settings-notice">{notice}</div>}
      {closed && (
        <p className="sh-muted sh-rules-note" data-testid="case-settings-closed">
          종료된 업무 — 예산 한도만 바꿀 수 있다(D-87). 다른 설정 변경은 서버가 거부한다.
        </p>
      )}
      <AutonomySection policy={policy} caseId={props.caseId} guard={guard} closed={closed} />
      <BudgetSection policy={policy} caseId={props.caseId} guard={guard} onNotice={setNotice} />
      <LimitsSection policy={policy} caseId={props.caseId} guard={guard} closed={closed} />
      <LevelSection detail={detail} caseId={props.caseId} guard={guard} closed={closed} />
      <RepositorySection policy={policy} caseId={props.caseId} repositories={props.repositories} guard={guard} closed={closed} />
      <GatesSection detail={detail} caseId={props.caseId} guard={guard} closed={closed} />
      <section data-testid="case-setting-inline-limit">
        <h3 className="sh-section-title">실행당 인라인 한도</h3>
        <p className="sh-muted sh-rule-line">
          이 프로젝트의 값이 새 실행마다 기록된다(실행별 값은 `작업` 탭의 실행 상세 — 고정 입력). 조정은 프로젝트 설정에서 한다 —
          대화별 조정은 없다.
        </p>
      </section>
    </div>
  )
}

// ------------------------------------------------------------------ Autonomy

function AutonomySection(props: {
  policy: NonNullable<ShellCaseDetail['policy']>
  caseId: string
  guard: Guard
  closed: boolean
}) {
  const { policy } = props
  const [reason, setReason] = useState('')
  const defaultSource = policy.default_autonomy_source ?? 'system_default'
  const set = (autonomy: Autonomy) => props.guard(() => policyApi.setAutonomy(props.caseId, autonomy, reason))
  return (
    <section data-testid="case-setting-autonomy" data-source={policy.autonomy_source} data-value={policy.autonomy ?? ''}>
      <h3 className="sh-section-title">확인 경계(Autonomy)</h3>
      <div className="sh-rule-line">
        <strong>{policy.autonomy_recorded ? AUTONOMY_LABEL[policy.effective_autonomy] : '기록되지 않음'}</strong>
        {' · '}
        <span data-testid="case-autonomy-source">{AUTONOMY_SOURCE_LABEL[policy.autonomy_source] ?? policy.autonomy_source}</span>
        {policy.is_treatment ? ' · 이행 취급(controlled)' : ''}
        {' · 정책 r'}
        {policy.revision}
      </div>
      <div className="sh-rule-line sh-muted">
        완료 {policy.completion_mode} ({COMPLETION_SOURCE_LABEL[policy.completion_mode_source] ?? policy.completion_mode_source}) ·
        깊이 {policy.work_depth ?? '미정'} (수준 판단)
      </div>
      <div className="sh-rule-line sh-muted">
        복귀하면: {AUTONOMY_LABEL[policy.default_autonomy]} ({AUTONOMY_SOURCE_LABEL[defaultSource] ?? defaultSource})
      </div>
      {!props.closed && (
        <div className="sh-composer-bar sh-rule-actions">
          <input
            className="sh-rule-input"
            placeholder="바꾸는 이유(선택)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            data-testid="case-autonomy-reason"
          />
          <button type="button" onClick={() => void set('ask_on_decision')} data-testid="case-autonomy-ask">
            기본 자율 진행으로
          </button>
          <button type="button" onClick={() => void set('controlled')} data-testid="case-autonomy-controlled">
            확인 경계로
          </button>
          <button
            type="button"
            className="sh-link"
            disabled={policy.autonomy_source !== 'case_explicit'}
            onClick={() => void props.guard(() => policyApi.resetAutonomy(props.caseId, reason))}
            data-testid="case-autonomy-reset"
          >
            기본값으로 복귀
          </button>
        </div>
      )}
    </section>
  )
}

// -------------------------------------------------------------------- 예산

function BudgetSection(props: {
  policy: NonNullable<ShellCaseDetail['policy']>
  caseId: string
  guard: Guard
  onNotice: (text: string) => void
}) {
  const budget = props.policy.budget
  const current = budget.limits.filter((l) => l.state === 'current')
  const [metric, setMetric] = useState('run_count')
  const [threshold, setThreshold] = useState('hard')
  const [value, setValue] = useState('5')
  // UI-04c(D-88). 시간 값은 서버 조회 그대로다 — 실행시간 합계(실행별 배정~종료의 합)와 대화 생성 후 경과시간.
  const execution = budget.usage?.execution_seconds ?? null
  const elapsed = budget.usage?.elapsed_seconds ?? null
  const metrics = orderMetrics(Object.keys(budget.reservation_contract))
  return (
    <section data-testid="case-setting-budget">
      <h3 className="sh-section-title">예산 한도</h3>
      {current.length === 0 && <p className="sh-muted sh-rule-line">한도 없음(무제한이 기본값, D-56)</p>}
      <ul className="sh-result-list">
        {current.map((row) => (
          <li key={row.id} className="sh-rule-line" data-testid={`case-budget-${row.metric}-${row.threshold_kind}`} data-set-by={row.set_by}>
            {metricLabel(row.metric)} {row.threshold_kind} <strong>{row.limit_value}</strong> {row.unit} ·{' '}
            {GUARANTEE_LABEL[row.guarantee ?? ''] ?? row.guarantee} · 설정{' '}
            {row.set_by === 'project_default' ? '프로젝트 기본값' : row.set_by} · {when(row.created_at)}
            <button
              type="button"
              className="sh-link"
              onClick={() => void props.guard(() => policyApi.clearBudget(props.caseId, row.metric, row.threshold_kind))}
              data-testid={`case-budget-clear-${row.metric}-${row.threshold_kind}`}
            >
              해제
            </button>
          </li>
        ))}
      </ul>
      {budget.stop.stopped && (
        <p className="sh-rule-line sh-warn">예산으로 새 실행이 중지됐다 — {budget.stop.detail}</p>
      )}
      <div data-testid="case-time">
        <p className="sh-rule-line" data-testid="case-time-execution" data-complete={String(execution?.complete ?? '')}>
          실행시간 합계: <strong>{timeSummary(execution)}</strong>
        </p>
        <p className="sh-rule-line" data-testid="case-time-elapsed">
          대화 생성 후 경과시간: <strong>{timeSummary(elapsed)}</strong>
        </p>
        <p className="sh-muted sh-rule-line">
          {BUDGET_METRIC_NOTE.execution_seconds}. {BUDGET_METRIC_NOTE.elapsed_seconds}.
        </p>
        <button
          type="button"
          className="sh-link"
          onClick={() => {
            setMetric(DEFAULT_TIME_METRIC)
            setThreshold('hard')
            setValue('1800')
          }}
          data-testid="case-budget-add-time"
        >
          시간 한도 추가(기본: 실행시간 합계)
        </button>
      </div>
      <div className="sh-composer-bar sh-rule-actions">
        <select value={metric} onChange={(e) => setMetric(e.target.value)} data-testid="case-budget-metric">
          {metrics.map((name) => {
            const contract = budget.reservation_contract[name]
            return (
              <option key={name} value={name}>
                {metricLabel(name)} (hard {GUARANTEE_LABEL[contract?.hard_guarantee ?? ''] ?? contract?.hard_guarantee ?? '?'})
              </option>
            )
          })}
        </select>
        <select value={threshold} onChange={(e) => setThreshold(e.target.value)} data-testid="case-budget-threshold">
          <option value="warn">경고선</option>
          <option value="hard">hard 한도</option>
        </select>
        <input size={6} value={value} onChange={(e) => setValue(e.target.value)} data-testid="case-budget-value" />
        <button
          type="button"
          onClick={() => void props.guard(() => policyApi.setBudget(props.caseId, metric, threshold, Number(value)))}
          data-testid="case-budget-set"
        >
          한도 설정
        </button>
        <button
          type="button"
          className="sh-link"
          onClick={() =>
            void props.guard(async () => {
              const state = await policyApi.applyProjectBudgetDefaults(props.caseId)
              props.onNotice(
                state.applied > 0 ? `프로젝트 기본 예산 ${state.applied}건을 적용했다` : '프로젝트 기본 예산이 없다 — 바뀐 것 없음',
              )
            })
          }
          data-testid="case-budget-project-defaults"
        >
          프로젝트 기본 예산 적용
        </button>
      </div>
      {BUDGET_METRIC_NOTE[metric] && (
        <p className="sh-muted sh-rule-line" data-testid="case-budget-metric-note">
          {metricLabel(metric)}: {BUDGET_METRIC_NOTE[metric]}
        </p>
      )}
      <p className="sh-muted sh-rule-line">
        정확히 측정할 수 없는 지표의 hard 한도는 거부된다(D-61). 시간 한도는 새 배정만 막는다(절대 상한 아님).
      </p>
    </section>
  )
}

// ---------------------------------------------------------------- 진행 상한

function LimitsSection(props: {
  policy: NonNullable<ShellCaseDetail['policy']>
  caseId: string
  guard: Guard
  closed: boolean
}) {
  const limits = props.policy.progress_limits
  const [values, setValues] = useState<Record<ProgressLimitKey, string>>({
    repair_limit: String(limits?.repair_limit.value ?? ''),
    task_retry_limit: String(limits?.task_retry_limit.value ?? ''),
  })
  const [reason, setReason] = useState('')
  if (!limits) return null
  const keys: ProgressLimitKey[] = ['repair_limit', 'task_retry_limit']
  return (
    <section data-testid="case-setting-limits">
      <h3 className="sh-section-title">진행 상한(재작성·재시도)</h3>
      <ul className="sh-result-list">
        {keys.map((key) => (
          <li key={key} className="sh-rule-line" data-testid={`case-limit-${key}`} data-source={limits[key].source}>
            {PROGRESS_LIMIT_LABEL[key]} <strong>{limits[key].value}</strong> ·{' '}
            <span data-testid={`case-limit-source-${key}`}>{PROGRESS_LIMIT_SOURCE_LABEL[limits[key].source]}</span>
            {limits[key].setting ? ` · ${when(limits[key].setting?.created_at)}` : ''}
            {' · 프로젝트 기본값 '}
            {limits.project_default?.[key] ?? '없음'} · 시스템 기본값 {limits.system_default[key]}
            {!props.closed && limits[key].source === 'case_setting' && (
              <button
                type="button"
                className="sh-link"
                onClick={() => void props.guard(() => progressApi.clearLimit(props.caseId, key))}
                data-testid={`case-limit-reset-${key}`}
              >
                기본값으로 복귀
              </button>
            )}
          </li>
        ))}
      </ul>
      {!props.closed && (
        <div className="sh-composer-bar sh-rule-actions">
          {keys.map((key) => (
            <label key={key} className="sh-muted">
              {PROGRESS_LIMIT_LABEL[key]}{' '}
              <input
                size={3}
                value={values[key]}
                onChange={(e) => setValues({ ...values, [key]: e.target.value })}
                data-testid={`case-limit-input-${key}`}
              />
            </label>
          ))}
          <input className="sh-rule-input" placeholder="사유(선택)" value={reason} onChange={(e) => setReason(e.target.value)} />
          <button
            type="button"
            onClick={() =>
              void props.guard(async () => {
                const changed: Partial<Record<ProgressLimitKey, number>> = {}
                for (const key of keys) {
                  if (Number(values[key]) !== limits[key].value) changed[key] = Number(values[key])
                }
                if (Object.keys(changed).length === 0) return
                await progressApi.setLimits(props.caseId, changed, reason)
              })
            }
            data-testid="case-limit-set"
          >
            상한 변경
          </button>
        </div>
      )}
      <p className="sh-muted sh-rule-line">범위 {limits.range.min}~{limits.range.max}. 한도를 올리면 한 번 더 시도하고 다시 실패하면 새 한도에서 멈춘다.</p>
    </section>
  )
}

// ------------------------------------------------------------------- 수준

function LevelSection(props: { detail: ShellCaseDetail; caseId: string; guard: Guard; closed: boolean }) {
  const sizing = props.detail.preparation?.sizing ?? null
  const [level, setLevel] = useState<WorkLevel>(sizing?.level ?? 'standard')
  const [reason, setReason] = useState('')
  const [risk, setRisk] = useState('')
  return (
    <section data-testid="case-setting-level">
      <h3 className="sh-section-title">작업 수준(깊이)</h3>
      {sizing === null ? (
        <p className="sh-muted sh-rule-line" data-testid="case-level-none">
          수준 판단 없음 — 의도 초안의 축별 판단이 먼저다. 미결정을 간소로 읽지 않는다.
        </p>
      ) : (
        <>
          <div className="sh-rule-line" data-testid="case-level-current">
            <strong>{WORK_LEVEL_LABEL[sizing.level]}</strong> · {SIZING_SOURCE_LABEL[sizing.source] ?? sizing.source} · 제안{' '}
            {WORK_LEVEL_LABEL[sizing.recommended_level]}
            {sizing.adjusted_from ? ` · 이전 ${WORK_LEVEL_LABEL[sizing.adjusted_from]}` : ''}
          </div>
          {!props.closed && (
            <div className="sh-composer-bar sh-rule-actions">
              <select value={level} onChange={(e) => setLevel(e.target.value as WorkLevel)} data-testid="case-level-select">
                {(['simple', 'standard', 'deep'] as WorkLevel[]).map((l) => (
                  <option key={l} value={l}>
                    {WORK_LEVEL_LABEL[l]}
                  </option>
                ))}
              </select>
              <input className="sh-rule-input" placeholder="조정 이유(필수)" value={reason} onChange={(e) => setReason(e.target.value)} data-testid="case-level-reason" />
              <input className="sh-rule-input" placeholder="남는 위험(필수)" value={risk} onChange={(e) => setRisk(e.target.value)} data-testid="case-level-risk" />
              <button
                type="button"
                disabled={!reason.trim() || !risk.trim()}
                onClick={() => void props.guard(() => preparationApi.adjustLevel(props.caseId, level, reason, risk))}
                data-testid="case-level-adjust"
              >
                수준 조정
              </button>
            </div>
          )}
          <p className="sh-muted sh-rule-line">수준 조정은 검토 방식·성공 기준·의도 동의를 건드리지 않는다.</p>
        </>
      )}
    </section>
  )
}

// ----------------------------------------------------------------- 저장소

function RepositorySection(props: {
  policy: NonNullable<ShellCaseDetail['policy']>
  caseId: string
  repositories: ProjectRepository[]
  guard: Guard
  closed: boolean
}) {
  const state = props.policy.repositories
  const [chosen, setChosen] = useState('')
  const [codeWrite, setCodeWrite] = useState(false)
  const [publish, setPublish] = useState(false)
  const [reason, setReason] = useState('')
  const selected = new Map(state.selected.map((r) => [r.repository_id, r]))
  return (
    <section data-testid="case-setting-repositories">
      <h3 className="sh-section-title">저장소 선택</h3>
      <ul className="sh-result-list">
        {props.repositories.map((repo) => {
          const row = selected.get(repo.id)
          const journal = state.journal_repository_id === repo.id
          return (
            <li key={repo.id} className="sh-rule-line" data-testid={`case-repo-${repo.id}`} data-selected={row ? '1' : '0'}>
              {repo.name} <span className="sh-mono sh-muted">{repo.repo_path}</span>
              {journal ? ' · 기록 저장소(코드 대상 아님)' : ''}
              {row ? (
                <>
                  {' · 선택됨 · 코드 쓰기 '}
                  {row.code_write_allowed ? '허용' : '불허'} · 게시 {row.publish_allowed ? '허용' : '불허'} · {row.selection_source}
                </>
              ) : (
                ' · 선택 안 함'
              )}
            </li>
          )
        })}
        {props.repositories.length === 0 && <li className="sh-muted sh-rule-line">등록된 저장소가 없다</li>}
      </ul>
      {state.selected.length === 0 && state.implicit_single_repository && (
        <p className="sh-muted sh-rule-line">{state.implicit_single_repository.detail}</p>
      )}
      {!props.closed && props.repositories.length > 0 && (
        <div className="sh-composer-bar sh-rule-actions">
          <select value={chosen} onChange={(e) => setChosen(e.target.value)} data-testid="case-repo-select">
            <option value="">저장소</option>
            {props.repositories.map((repo) => (
              <option key={repo.id} value={repo.id}>
                {repo.name}
              </option>
            ))}
          </select>
          <label className="sh-muted">
            <input type="checkbox" checked={codeWrite} onChange={(e) => setCodeWrite(e.target.checked)} data-testid="case-repo-write" /> 코드 쓰기 허용
          </label>
          <label className="sh-muted">
            <input type="checkbox" checked={publish} onChange={(e) => setPublish(e.target.checked)} data-testid="case-repo-publish" /> 게시 허용(기록)
          </label>
          <input className="sh-rule-input" placeholder="사유(선택)" value={reason} onChange={(e) => setReason(e.target.value)} />
          <button
            type="button"
            disabled={!chosen}
            onClick={() => void props.guard(() => repositoryApi.select(props.caseId, chosen, codeWrite, publish, reason))}
            data-testid="case-repo-submit"
          >
            선택 기록
          </button>
        </div>
      )}
      <p className="sh-muted sh-rule-line">
        선택·쓰기 허용·게시 허용은 서로 다른 기록이다(D-63·D-64). 쓰기 허용은 게시 허용이 아니고 실제 push·PR 은 아직 없다.
      </p>
    </section>
  )
}

// ------------------------------------------------------------ QG-02~07

function GatesSection(props: { detail: ShellCaseDetail; caseId: string; guard: Guard; closed: boolean }) {
  const gates = props.detail.quality_gates?.gates ?? []
  const [open, setOpen] = useState<string | null>(null)
  return (
    <section data-testid="case-setting-gates">
      <h3 className="sh-section-title">품질 게이트 QG-02~07</h3>
      <ul className="sh-result-list">
        {gates
          .filter((g) => g.gate !== 'QG-01')
          .map((gate) => (
            <li key={gate.gate} className="sh-rule-line" data-testid={`case-gate-${gate.gate}`} data-setting={gate.setting}>
              <span className="sh-mono">{gate.gate}</span> {gate.label} · <strong>{GATE_SETTING_LABEL[gate.setting] ?? gate.setting}</strong> ·{' '}
              {INSPECTION_LABEL[gate.inspection_required] ?? gate.inspection_required} · 수정 한도 {gate.repair_limit} ·{' '}
              <span className="sh-muted">{gate.source}</span>
              {gate.applied_at ? ` · 적용 ${when(gate.applied_at)}` : ''}
              {gate.latest_run ? ` · 판정 ${GATE_VERDICT_LABEL[gate.latest_run.verdict]}` : ''}
              {gate.remediation
                ? ` · 수정 ${gate.remediation.used_attempts + gate.remediation.reserved_attempts}/${gate.remediation.repair_limit}`
                : ''}
              {gate.reserved.length > 0 && (
                <span className="sh-warn" data-testid={`case-gate-reserved-${gate.gate}`}>
                  {' '}· 예약 {gate.reserved.length}건(검증 1회 종료 뒤 반영)
                </span>
              )}
              {!props.closed && (
                <button type="button" className="sh-link" onClick={() => setOpen(open === gate.gate ? null : gate.gate)} data-testid={`case-gate-edit-${gate.gate}`}>
                  {open === gate.gate ? '닫기' : '설정'}
                </button>
              )}
              {open === gate.gate && <GateForm gate={gate} caseId={props.caseId} guard={props.guard} onDone={() => setOpen(null)} />}
            </li>
          ))}
      </ul>
      <p className="sh-muted sh-rule-line">
        QG-01 은 필수라 끌 수 없다. 여기서 <strong>켬</strong>으로 고른 게이트는 진행기가 스스로 검토하고(별도 세션), 실패면 수정
        한도 안에서 고친 뒤 다시 검토한다 — 지금 실행 조건인 것은 QG-02(계획·구현 전)·QG-03(구현 전)·QG-04(검증 전)다. 한도 뒤에만
        사람 카드가 뜬다. 기본값 따름은 기존 구조 검사가 목적을 대신한다. 검사 강도는 낮출 수 없고 진행 중 검증이 있으면 변경은
        예약된다.
      </p>
    </section>
  )
}

function GateForm(props: { gate: QualityGatePolicy; caseId: string; guard: Guard; onDone: () => void }) {
  const [setting, setSetting] = useState<'on' | 'off' | 'inherit'>(props.gate.setting === 'off' ? 'off' : 'on')
  const [inspection, setInspection] = useState<string>(props.gate.inspection_required)
  const [limit, setLimit] = useState(String(props.gate.repair_limit))
  const [reason, setReason] = useState('')
  return (
    <div className="sh-rule-form">
      <div className="sh-composer-bar sh-rule-actions">
        <select value={setting} onChange={(e) => setSetting(e.target.value as 'on' | 'off' | 'inherit')} data-testid={`case-gate-setting-${props.gate.gate}`}>
          <option value="on">켬</option>
          <option value="off">끔</option>
          <option value="inherit">기본값 따름</option>
        </select>
        <select value={inspection} onChange={(e) => setInspection(e.target.value)} data-testid={`case-gate-inspection-${props.gate.gate}`}>
          {(['rule', 'light', 'independent'] as const).map((m) => (
            <option key={m} value={m}>
              {INSPECTION_LABEL[m]}
            </option>
          ))}
        </select>
        <label className="sh-muted">
          수정 한도 <input size={3} value={limit} onChange={(e) => setLimit(e.target.value)} data-testid={`case-gate-limit-${props.gate.gate}`} />
        </label>
        <input className="sh-rule-input" placeholder="사유(필수)" value={reason} onChange={(e) => setReason(e.target.value)} data-testid={`case-gate-reason-${props.gate.gate}`} />
        <button
          type="button"
          disabled={!reason.trim()}
          onClick={() =>
            void props.guard(async () => {
              await qualityGateApi.setPolicy(props.caseId, props.gate.gate, {
                setting,
                inspection: inspection || null,
                repair_limit: limit.trim() === '' ? null : Number(limit),
                reason,
              })
              props.onDone()
            })
          }
          data-testid={`case-gate-submit-${props.gate.gate}`}
        >
          적용
        </button>
      </div>
    </div>
  )
}
