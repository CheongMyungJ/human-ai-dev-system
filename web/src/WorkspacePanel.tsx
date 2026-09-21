// 작업공간 — **어떤 코드 위에서 어디에 만들고, 무엇이 실제로 바뀌었는가** (P3-03).
//
// 이 화면이 지키는 것 넷.
//
//   **요청을 준비됨으로 보이지 않는다.** `requested` 는 "만들어 달라고 적었다"이고
//   그 상태에서 쓰기는 `workspace_not_ready` 로 거부된다. 둘을 같은 색으로 칠하면
//   사람은 왜 구현이 시작되지 않는지 알 수 없다.
//
//   **격리 한계를 서버가 준 문장 그대로 보인다.** 화면이 지어내면 언젠가
//   "격리됨"으로 바뀐다. worktree 는 파일 배치의 분리이며 OS 격리가 아니다(D-44).
//
//   **"관측하지 않았다"와 "바뀌지 않았다"를 구별한다.** `workspace_effect` 가 없는
//   실행은 변경 없음이 아니라 **모른다**이다.
//
//   **경계 밖 변경과 예상하지 못한 외부 편집은 드러내되 되돌리지 않는다**(FR-26).
//   사용자가 직접 고친 것일 수 있고, 그 변경을 보존하는 것이 요구다.

import { useState } from 'react'

import {
  ApiError,
  WORKSPACE_STATE_LABEL,
  workspaceApi,
  type CaseDetail,
  type RunEffectRow,
  type WorkspaceEffect,
  type WorkspaceView,
} from './api'

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (typeof err.detail === 'string') return err.detail
    if (err.detail && typeof err.detail === 'object') {
      const detail = err.detail as { message?: unknown }
      if (detail.message) return String(detail.message)
    }
  }
  return err instanceof Error ? err.message : String(err)
}

function short(sha: string): string {
  return sha ? sha.slice(0, 10) : '기록되지 않음'
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

export function WorkspacePanel(props: {
  detail: CaseDetail
  onChanged: () => void | Promise<void>
}) {
  const { detail } = props
  const workspace: WorkspaceView | null = detail.workspace
  const [baseRef, setBaseRef] = useState('HEAD')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function prepare() {
    setBusy(true)
    setError(null)
    try {
      await workspaceApi.prepare(detail.id, baseRef.trim() || 'HEAD')
      await props.onChanged()
    } catch (err) {
      setError(describeError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <h2>작업공간</h2>

      {workspace === null ? (
        <div className="notice">
          <p>
            이 업무에는 아직 전용 작업공간이 없다. <strong>쓰기 권한은 열리지 않는다</strong>
            (<code>workspace_not_ready</code>) — Case 전용 브랜치와 기준 커밋 없이 코드를
            바꾸면 사용자의 미커밋 변경을 보호할 수단이 없다.
          </p>
          <label>
            기준으로 삼을 ref
            <input value={baseRef} onChange={(e) => setBaseRef(e.target.value)} />
          </label>
          <p className="muted">
            기준 커밋은 <strong>커밋된 상태</strong>다. 저장소에 미커밋 변경이 있어도
            그것을 가져오지 않으며, 시스템이 커밋·stash·reset 하지도 않는다.
          </p>
          <button onClick={prepare} disabled={busy}>
            작업공간 준비 요청
          </button>
        </div>
      ) : (
        <>
          <dl className="task-detail">
            <dt>상태</dt>
            <dd>
              <span className={`tag ${workspace.state === 'ready' ? 'ok' : ''}`}>
                {WORKSPACE_STATE_LABEL[workspace.state]}
              </span>
            </dd>
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
            <dt>저장소</dt>
            <dd>
              <code>{workspace.repo_path || '아직 확인되지 않음'}</code>
            </dd>
          </dl>

          {workspace.state === 'failed' && (
            <p className="warn">
              준비하지 못했다: {workspace.failure_reason || '사유가 기록되지 않음'}
            </p>
          )}

          {workspace.user_tree_dirty && (
            <p className="muted">
              준비 시점에 사용자의 원래 작업 트리에 변경 {workspace.user_tree_entries}건이
              있었다. <strong>시스템은 그것을 커밋·stash·삭제하지 않았고</strong> 기준
              커밋에도 담지 않았다.
            </p>
          )}

          {/* 한계 문구는 **서버가 준 값**이다. 화면이 지어내지 않는다. */}
          <p className="notice">
            <strong>격리 한계</strong>: {workspace.isolation_note}
          </p>

          <h3>실행이 바꾼 것</h3>
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
