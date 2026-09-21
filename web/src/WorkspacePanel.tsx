// 작업공간 — **어느 저장소의 어떤 코드 위에서, 어디에, 무엇이 바뀌었는가**
// (P3-03 + P3-R2).
//
// 이 화면이 지키는 것 여섯.
//
//   **요청을 준비됨으로 보이지 않는다.** `requested` 는 "만들어 달라고 적었다"이고
//   그 상태에서 쓰기는 `workspace_not_ready` 로 거부된다. 둘을 같은 색으로 칠하면
//   사람은 왜 구현이 시작되지 않는지 알 수 없다.
//
//   **부분 준비를 완전 준비로 보이지 않는다**(P3-R2). 저장소 둘 중 하나가 실패하면
//   그 사실이 맨 위에 있어야 한다. 준비된 하나만 보이면 나머지는 없는 것이 된다.
//
//   **허용의 출처를 그대로 말한다.** `implicit_single_repository` 는 "선택했다"가
//   아니라 "선택 기록 없이 이행된 Case 다"이며, 화면이 그것을 선택으로 보여 주면
//   없던 결정이 있는 것처럼 된다.
//
//   **격리 한계를 서버가 준 문장 그대로 보인다.** 화면이 지어내면 언젠가
//   "격리됨"으로 바뀐다. worktree 는 파일 배치의 분리이며 OS 격리가 아니다(D-44).
//
//   **"관측하지 않았다"와 "바뀌지 않았다"를 구별한다.** `workspace_effect` 가 없는
//   실행은 변경 없음이 아니라 **모른다**이다. 조합의 `snapshot_incomplete` 도 같다.
//
//   **개별 저장소의 통과를 통합의 통과로 보이지 않는다.** 조합이 코드 대상을 전부
//   담지 않았으면 통합은 검증되지 않은 것이다(execution-workspace-review 2.1절).

import { useState } from 'react'

import {
  ApiError,
  WORKSPACE_STATE_LABEL,
  workspaceApi,
  type CaseDetail,
  type CodeComposition,
  type RepositoryWorkspace,
  type RunEffectRow,
  type WorkspaceEffect,
  type WorkspaceView,
} from './api'

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (typeof err.detail === 'string') return err.detail
    if (err.detail && typeof err.detail === 'object') {
      const detail = err.detail as { message?: unknown; refusals?: unknown }
      // 정책 거절은 **사유 코드**로 온다. 화면이 그것을 그대로 보여야 사람이
      // 무엇을 고쳐야 하는지 안다(선택하지 않았다 / 제외했다 / 쓰기를 허용하지
      // 않았다 / 기록 저장소다는 서로 다른 조치를 부른다).
      if (Array.isArray(detail.refusals)) return detail.refusals.join(', ')
      if (detail.message) return String(detail.message)
    }
  }
  return err instanceof Error ? err.message : String(err)
}

function short(sha: string): string {
  return sha ? sha.slice(0, 10) : '기록되지 않음'
}

const ALLOWANCE_LABEL: Record<string, string> = {
  case_repository: '이 업무가 그 저장소를 선택하고 코드 쓰기를 허용했다',
  implicit_single_repository:
    '선택 기록이 없는 업무다. 등록된 단일 저장소에서 동작하며 그것은 이행된 가정이지 기록된 선택이 아니다',
}

function EffectRow(props: { row: RunEffectRow }) {
  const { row } = props
  const effect: WorkspaceEffect = row.effect
  return (
    <li className="task">
      <div className="task-head">
        <code>{row.run_id}</code>
        <span className="muted">{row.task_id}</span>
        <span className={`tag ${row.outcome === 'completed' ? 'ok' : ''}`}>
          {row.outcome ?? '진행 중'}
        </span>
      </div>
      <div className="task-head">
        {effect.changed ? (
          // **이 실행이 무엇인가 바꿨다.** 옆의 수는 기준 커밋 대비 누적이며
          // 이 실행만의 것이 아니다 — 둘을 같은 말로 쓰면 앞선 실행의 변경이
          // 이 실행의 성과처럼 보인다.
          <span>이 실행이 작업공간을 바꿨다</span>
        ) : (
          <span className="warn">이 실행은 작업공간을 바꾸지 않았다</span>
        )}
        <span className="muted">
          기준 커밋 대비 누적: 파일 {effect.files_changed}개 · +{effect.insertions} / −
          {effect.deletions}
        </span>
        <span className="muted">
          HEAD {short(effect.head_before)} → {short(effect.head_after)}
        </span>
      </div>
      {row.repository_recorded === false && (
        <p className="warn">
          이 실행이 <strong>어느 저장소의 것인지 기록되지 않았다</strong>. 작업공간이
          여럿이므로 아무 저장소에나 붙이지 않는다.
        </p>
      )}
      {row.unexpected_external_change && (
        <p className="warn">
          직전 실행이 남긴 상태와 다른 자리에서 시작했다. 사람이 직접 고쳤을 수 있으며
          시스템은 그 변경을 <strong>되돌리지 않는다</strong>.
        </p>
      )}
      {effect.outside_workspace_changed && (
        <p className="warn">
          이 실행 중에 <strong>작업공간 밖</strong>의 저장소 상태가 바뀌었다. 감지한
          것이며 막은 것이 아니다.
        </p>
      )}
      {!effect.outside_workspace_observed && (
        <p className="muted">작업공간 밖은 관측하지 않았다 — 바뀌지 않았다는 뜻이 아니다.</p>
      )}
    </li>
  )
}

function RepositoryWorkspaceCard(props: { workspace: RepositoryWorkspace }) {
  const { workspace } = props
  return (
    <section className="panel">
      <h3>
        저장소 <code>{workspace.repository_name}</code>{' '}
        <span className={`tag ${workspace.state === 'ready' ? 'ok' : ''}`}>
          {WORKSPACE_STATE_LABEL[workspace.state]}
        </span>
      </h3>

      <dl className="task-detail">
        <dt>브랜치</dt>
        <dd>
          <code>{workspace.branch}</code>
        </dd>
        <dt>기준 커밋</dt>
        <dd>
          <code>{short(workspace.base_commit)}</code>{' '}
          <span className="muted">({workspace.base_ref || 'ref 기록 없음'})</span>
        </dd>
        <dt>worktree</dt>
        <dd>
          <code>{workspace.worktree_path || '아직 없음'}</code>
        </dd>
        <dt>저장소 경로</dt>
        <dd>
          <code>{workspace.repo_path || '아직 확인되지 않음'}</code>
        </dd>
        <dt>허용 근거</dt>
        <dd>
          <span className="muted">
            {ALLOWANCE_LABEL[workspace.allowance_source] ?? workspace.allowance_source ?? '기록 없음'}
          </span>
        </dd>
      </dl>

      {workspace.state === 'failed' && (
        <p className="warn">
          준비하지 못했다: {workspace.failure_reason || '사유가 기록되지 않음'}
        </p>
      )}

      {workspace.user_tree_dirty && (
        <p className="muted">
          준비 시점에 <strong>이 저장소의</strong> 사용자 작업 트리에 변경{' '}
          {workspace.user_tree_entries}건이 있었다.{' '}
          <strong>시스템은 그것을 커밋·stash·삭제하지 않았고</strong> 기준 커밋에도
          담지 않았다.
        </p>
      )}

      <h4>이 저장소에서 실행이 바꾼 것</h4>
      {workspace.run_effects.length === 0 ? (
        <p className="muted">
          이 작업공간에서 관측된 실행이 아직 없다. 관측이 없다는 것은 변경이 없다는
          뜻이 아니다.
        </p>
      ) : (
        <ul className="tasks">
          {workspace.run_effects.map((row) => (
            <EffectRow key={row.run_id} row={row} />
          ))}
        </ul>
      )}
    </section>
  )
}

function CompositionCard(props: { composition: CodeComposition }) {
  const { composition } = props
  return (
    <section className="panel">
      <h3>코드 조합 (revision {composition.revision})</h3>
      <p className="muted">
        검증의 대상을 <strong>저장소별 정확한 스냅샷</strong>으로 고정한 것이다. 움직이는
        브랜치 이름이나 파일 경로로는 "무엇을 검증했는가"를 말할 수 없다.
      </p>

      {!composition.integration_verified && (
        <p className="warn">
          <strong>통합은 검증되지 않았다.</strong>{' '}
          {composition.integration_detail ??
            '이 조합이 이 업무의 코드 대상 저장소를 전부 담지 않았다.'}
        </p>
      )}
      {composition.matches_current_state === false && (
        <p className="warn">
          기록된 조합과 <strong>지금 상태가 다르다</strong>. 이 조합을 가리키는 근거는
          다시 평가해야 한다 — 화면이 조용히 갱신하지 않는다.
        </p>
      )}

      <ul className="tasks">
        {composition.entries.map((entry) => (
          <li key={entry.repository_id} className="task">
            <div className="task-head">
              <code>{entry.repository_name}</code>
              <span className="muted">기준 {short(entry.base_commit)}</span>
              {entry.head_commit && (
                <span className="muted">HEAD {short(entry.head_commit)}</span>
              )}
            </div>
            {entry.snapshot_incomplete ? (
              <p className="warn">
                이 저장소는 <strong>관측된 실행이 없다</strong>. 기준 커밋만 있고 지금
                미커밋 상태는 모른다 — 기준 커밋만으로 실제 입력을 설명할 수 없다.
              </p>
            ) : (
              <p className="muted">
                미커밋 {entry.dirty_entries}건 · 트리 지문{' '}
                <code>{entry.tree_digest.slice(0, 12)}</code>{' '}
                (실행 <code>{entry.observed_run_id}</code> 가 관측)
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

export function WorkspacePanel(props: {
  detail: CaseDetail
  onChanged: () => void | Promise<void>
}) {
  const { detail } = props
  const view: WorkspaceView | null = detail.workspace
  const [baseRef, setBaseRef] = useState('HEAD')
  const [repositoryId, setRepositoryId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function prepare() {
    setBusy(true)
    setError(null)
    try {
      await workspaceApi.prepare(
        detail.id,
        baseRef.trim() || 'HEAD',
        repositoryId.trim() || undefined,
      )
      await props.onChanged()
    } catch (err) {
      setError(describeError(err))
    } finally {
      setBusy(false)
    }
  }

  async function fixComposition() {
    setBusy(true)
    setError(null)
    try {
      await workspaceApi.buildComposition(detail.id)
      await props.onChanged()
    } catch (err) {
      setError(describeError(err))
    } finally {
      setBusy(false)
    }
  }

  const prepareForm = (
    <div className="notice">
      <label>
        기준으로 삼을 ref
        <input value={baseRef} onChange={(e) => setBaseRef(e.target.value)} />
      </label>
      <label>
        저장소 id <span className="muted">(비우면 모호하지 않은 경우에만 해석한다)</span>
        <input value={repositoryId} onChange={(e) => setRepositoryId(e.target.value)} />
      </label>
      <p className="muted">
        기준 커밋은 <strong>커밋된 상태</strong>다. 저장소에 미커밋 변경이 있어도
        그것을 가져오지 않으며, 시스템이 커밋·stash·reset 하지도 않는다.{' '}
        <strong>저장소마다 별도의 브랜치·worktree·기준 커밋</strong>을 갖는다.
      </p>
      <button onClick={prepare} disabled={busy}>
        작업공간 준비 요청
      </button>
    </div>
  )

  return (
    <section className="panel">
      <h2>작업공간</h2>

      {view === null ? (
        <>
          <div className="notice">
            <p>
              이 업무에는 아직 전용 작업공간이 없다.{' '}
              <strong>쓰기 권한은 열리지 않는다</strong> (<code>workspace_not_ready</code>)
              — 전용 브랜치와 기준 커밋 없이 코드를 바꾸면 사용자의 미커밋 변경을
              보호할 수단이 없다.
            </p>
          </div>
          {prepareForm}
        </>
      ) : (
        <>
          <p className="muted">
            저장소 {view.repository_count}개 중 {view.ready_count}개 준비됨.
          </p>
          {!view.all_ready && (
            <p className="warn">
              <strong>아직 전부 준비되지 않았다.</strong> 준비되지 않은 저장소의 쓰기는
              열리지 않으며, 준비된 저장소의 결과만으로 업무 전체가 끝났다고 보지 않는다.
            </p>
          )}

          {/* 한계 문구는 **서버가 준 값**이다. 화면이 지어내지 않는다. */}
          <p className="notice">
            <strong>격리 한계</strong>: {view.isolation_note}
          </p>

          {view.workspaces.map((workspace) => (
            <RepositoryWorkspaceCard key={workspace.repository_id} workspace={workspace} />
          ))}

          {view.unattributed_run_effects.length > 0 && (
            <section className="panel">
              <h3>대상 저장소가 기록되지 않은 실행</h3>
              <p className="warn">
                아래 실행은 어느 저장소의 것인지 <strong>기록되지 않았다</strong>. 숨기지
                않고 따로 보인다 — 아무 저장소에 붙이면 그 저장소의 이력이 거짓이 된다.
              </p>
              <ul className="tasks">
                {view.unattributed_run_effects.map((row) => (
                  <EffectRow key={row.run_id} row={row} />
                ))}
              </ul>
            </section>
          )}

          {view.composition ? (
            <CompositionCard composition={view.composition} />
          ) : (
            <p className="muted">
              코드 조합이 아직 고정되지 않았다. 준비된 작업공간이 있어야 만들 수 있다.
            </p>
          )}
          <button onClick={fixComposition} disabled={busy}>
            지금 상태로 코드 조합 고정
          </button>

          {prepareForm}

          <h3>실행한 명령</h3>
          <ul className="tasks">
            {detail.runs
              .filter((run) => (run.commands ?? []).length > 0)
              .flatMap((run) =>
                (run.commands ?? []).map((command) => (
                  <li key={`${run.run_id}-${command.seq}`}>
                    <code>{run.run_id}</code> {command.command_summary}{' '}
                    <span className={`tag ${command.exit_code === 0 ? 'ok' : ''}`}>
                      {command.exit_code === null ? '종료 미확인' : `exit ${command.exit_code}`}
                    </span>
                  </li>
                )),
              )}
          </ul>
          <p className="muted">
            명령 원문과 출력은 이 제어부에 없다. 상세는 원문 조회로 본다.
            <strong> 종료 코드가 0이 아닌 것은 검증의 결과이지 실행의 실패가 아니다.</strong>
          </p>
        </>
      )}

      {error && <p className="error">{error}</p>}
    </section>
  )
}
