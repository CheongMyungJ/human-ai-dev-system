# P4-PLAN-10d

**상태: 완료(S-038, 2026-09-25)** — AC-1~9 충족, [P4-10d 결과](../p4/evidence/P4-10d-results.md). 구현 중 바꾼 것: 관리 화면(`ResultPanel`)은
바꾸지 않고 새 화면(카드·작업 탭)만 고쳤다(관리 화면은 UI-05b 에서 걷어 낸다); 대기의 실행 목록은 앞 8건 + 전체 수(대기 기록 4000자 제한);
잔류 재확인 보고 뒤 자동 완료 시도를 저장 계층에도 더했다(결과 보고와 같은 자리). 커밋·push 는 사용자 지시를 기다린다.

**결과 모름(`unknown`)으로 끝난 실행이 업무 종료를 영원히 막지 않게 한다** — 이슈 #10, 사용자 결정 **D-98**(2026-09-25, S-037: 권장안
B + A, UI-05b 앞). 재현 사례: Case `case-e484766d9fec98a7` 의 검증 작업 T2 가 `unknown` 두 번(T2-1·T2-2, 둘 다 트리 종료 확인
`residual_activity = none`) 뒤 T2-3 에서 `completed` 로 기준 C-01~C-03 을 적었는데, 진행기가 `busy/runs_unsettled` 에서 진행 요청
`req-539044a647b2cb84` 를 `processing` 으로 열어 둔 채 멈췄다(화면 "처리 중" 영구).

## 0. 기준선과 코드 대조

- 시작 `main`/`15cb44f` clean, `origin/main` 과 같음(fetch 로 확인). 기준선 `scripts\run-tests.ps1` 은 S-038 에서 변경 전에 돌렸다(수치는 결과
  문서).
- `domain/work_flow._completion_phase` 가 `state.unsettled_runs` 면 `Step("busy", "runs_unsettled")` 를 낸다. `WorkProgressor.advance` 는
  `busy` 면 돌아가고 요청 유지(`keep_request`)는 `gate_review_pending`·`quality_gate_review_pending` 만이다. 진행 요청(여는 메시지 없음)은
  `RequestProcessor.finish` 가 스스로 닫지 않으므로 영구히 `processing` 이다.
- `Repository.unsettled_runs` 는 끝나지 않은 실행과 `unknown` 을 센다. 빠지는 것은 트리 종료가 확인된 `cancelled`·시간 초과
  `unknown`(P4-10) 뿐이다. 같은 작업을 다시 해 성공해도 앞 `unknown` 이 남는다.
- 사용자의 로컬 DB 사본(읽기 전용 백업, 스크래치)은 스키마 v28(제어부가 P4-10 이전 코드로 떠 있음)이고 T2-1·T2-2 는 `finished`/`unknown`/
  잔류 `none` 이다 → B 의 대상.
- **뒤따를 보고가 없는 다른 `busy` 점검:** `runs_unfinished`(결과 보고가 뒤따른다 — 다만 요청 없는 실행의 결과 뒤 `advance(case, None)`
  은 열린 진행 요청을 끝내지 못한다), `intent_structure_pending`(Runner 의 구조 보고 `/api/runner/intent-structure` 가 뒤따르지만 그 끝점은
  진행기를 부르지 않는다 — 구조가 결과 뒤에 오면 요청이 열린 채 남는다), `gate_review_pending`·`quality_gate_review_pending`(검토 보고가
  이어 준다 — 이미 요청 유지), `workspace_pending`(작업공간 보고가 진행기를 부른다 — 그대로).

## 1. 상세 설계 선택

1. **버그 — `runs_unsettled` 는 사람 대기다.** `busy` 대신 새 대기 사유 `unsettled_runs`("결과를 모르는 실행 확인 필요")로 멈춘다 —
   진행기의 `_wait` 가 요청을 끝내고(처리 중 표시가 사라진다) Case 는 `waiting_human` 이다. 대기 사유에 실행 목록(실행·작업·목적·결과·
   끊긴 이유·끝난 시각·트리 종료 확인 여부·사람 확인 가능 여부)을 싣는다.
2. **B 자동 대체(저장하지 않고 도출).** 끝난 `unknown` 실행 R 은 다음이 모두 맞으면 종료를 막지 않는다: (a) R 의 트리 종료가 확인됐다
   (`execution_unconfirmed` 아님), (b) 같은 Case·같은 `task_id`·같은 목적의 실행 중 R 보다 **뒤에 만든** 것이 `completed` 로 끝났다,
   (c) 목적이 논의 응답(`discussion_reply`)이 아니다 — 논의 응답은 요청마다 다른 답이지 같은 작업의 재시도가 아니다. 규칙은 순수 함수
   (`domain/run_control.py`)이고 `unsettled_runs`·실행 조회·대기 카드가 같은 함수를 본다. 결과는 `unknown` 그대로다. 진행기가 처음 볼 때
   진행 이력에 한 줄(`unknown_run_superseded`, 대체한 실행 포함)을 남긴다 — 기록.
3. **A 사람 확인(저장).** B 로 풀리지 않은 끝난 `unknown` 실행은 사람이 카드에서 "작업공간 영향을 확인했다"(필수 표시) + 사유(1~200자)로
   확인을 기록하면 종료를 막지 않는다. 새 표 `run_unknown_confirmation`(스키마 **v30**, 실행당 하나)과 결정 기록(`decision.kind =
   unknown_run_confirmation`, 대상 = 실행)을 한 트랜잭션에 적는다. 결과는 `unknown` 그대로이고 그 실행의 기준 보고는 여전히 판정에 쓰지
   않는다. 확인은 인수·예외·다른 실행의 허용이 아니다. 거부: 종료된 Case, 다른 Case 의 실행, 끝나지 않은 실행, `unknown` 이 아닌 실행,
   B 로 이미 풀린 실행, 표시 없음·사유 없음. 같은 실행의 재전송은 처음 기록을 돌려준다.
   - **트리 종료가 확인되지 않은 실행(`execution_unconfirmed`)은 A 의 대상이 아니다.** D-98 은 "끝났지만 결과를 모르는 실행" 이고,
     UI-02 규칙("사람이 종료 확인을 대신 선언하지 않는다 — Runner 가 근거를 보내야 풀린다")을 그대로 둔다. 카드는 그 실행을 "PC 의 종료
     확인을 기다린다" 로 보이고 기존 재확인 경로(잠긴 요청의 `다시 확인`)를 안내한다. 확인이 오면 풀린다.
4. **풀린 뒤 이어 가기.** 자동 완료는 지금 결과 보고·기준 판정 때만 시도된다. A·B·잔류 재확인·재시작 복구에서 조건이 갖춰질 수 있으므로
   **진행기의 `advance` 가 처음에 `maybe_auto_complete` 를 한 번 부른다**(조건이 안 되면 아무 것도 하지 않는 기존 함수). A 기록 뒤와
   잔류 재확인 보고 뒤에 진행기를 부른다(사람 입력·보고 뒤 훅과 같은 경계). 그러면 이미 걸린 Case 는 제어부 재시작 복구(`recover`: 진행
   `running` + 처리 중 요청 + 실행 모두 끝남 → `advance`)에서 B 로 풀려 자동 완료 → 진행 `done` → 요청 종료까지 간다.
5. **다른 `busy` 의 보강(점검 결과).** (a) 의도 구조 보고 끝점 뒤에 진행기를 부른다(작업공간 보고와 같은 훅 — 구조가 결과 뒤에 와도 잇는다).
   (b) 요청 없는 실행의 결과 뒤 진행기가 Case 의 열린 **진행 요청**을 넘겨받아 사람 대기·완료면 그것을 끝낸다. 나머지 `busy` 는 뒤따르는
   보고가 있어 그대로다.
6. **보이는 곳.** 대기 카드 `unsettled_runs`(실행별: 실행 보기, 종료 확인 여부, A 입력 — 표시·사유·버튼), 실행 조회 `unknown_settlement`
   (`superseded`(대체한 실행) | `confirmed`(주체·사유·시각) | 없음), 작업 탭 실행 상세의 한 줄, 결과 패널의 미정리 실행 목록 옆 "풀린 결과
   모름 실행" 목록. 후보 스냅샷(해시)의 모양은 바꾸지 않는다 — 미정리 목록에서 빠질 뿐이다.
7. **소급·경계.** 옛 실행·Case 에 데이터 이행 없음(B 는 도출이므로 옛 Case 에도 곧바로 적용된다 — 이슈 #10 의 사례가 그 경우). 진입 검사·
   권한·인수·예외·완료 규칙·게시(P5) 무변경. completion-lifecycle 5절에 D-98 의 두 해소 경로를 적는다.

## 2. 성공 기준

| AC | 기준 | 근거 |
|---|---|---|
| AC-1 | 진행 요청에서 미정리 `unknown` 실행이 남으면 요청이 `processing` 으로 남지 않고 끝나며, 진행은 `waiting_human`/`unsettled_runs`(실행 목록 포함)다 | 제어부 시험 |
| AC-2 | B: 같은 작업의 앞 시도 `unknown`(종료 확인) 뒤 시도 `completed` 면 미정리에서 빠지고 자동 완료된다. 결과는 `unknown` 그대로, 실행 조회에 `superseded`, 진행 이력에 한 줄 | 제어부 시험 |
| AC-3 | B 가 적용되지 않는 경우: 트리 종료 미확인, 뒤 시도 없음·`failed`, 다른 작업, 논의 응답 | 순수 규칙 시험 |
| AC-4 | A: 카드 경로 API 로 확인하면 풀리고 자동 완료까지 간다. 결정·확인 기록이 남고 결과는 `unknown` 그대로. 거부 경우(표시·사유 없음, 종료 미확인, `unknown` 아님, 이미 풀림, 종료된 Case)는 409/422, 재전송은 같은 기록 | 제어부 시험 |
| AC-5 | 이슈 #10 모양(요청 `processing`·진행 `running`·T2-1/T2-2 `unknown` 종료 확인·T2-3 `completed`)의 Case 가 제어부 재시작 복구(`recover`)에서 종료되고 요청이 끝난다 | 제어부 시험 + 사용자 DB **사본**에 이행·복구를 돌린 관찰(원본 무변경) |
| AC-6 | 의도 구조가 결과 뒤에 와도 진행이 이어지고, 요청 없는 실행 뒤의 사람 대기가 열린 진행 요청을 끝낸다 | 제어부 시험 |
| AC-7 | 화면: 대기 카드가 실행 목록을 보이고 확인 입력으로 풀면 완료된다(실제 Edge·실제 Runner·가짜 codex) | 브라우저 시험 |
| AC-8 | 스키마 v30 이행이 옛 DB(v29)를 행 보존으로 올린다 | 이행 시험 |
| AC-9 | 기존 시험 전부 통과(뜻이 바뀌는 시험은 결과 문서에 적는다) | 전체 시험 |

## 3. 변경 범위(예상)

- 제품: `domain/run_control.py`(B 규칙)·`domain/work_flow.py`(대기 사유)·`domain/models.py`(결정 종류), `controller/repository.py`
  (`unsettled_runs`·확인 기록·조회)·`work_progressor.py`(자동 완료 시도·이력·요청 넘겨받기)·`api.py`(확인 끝점·훅 둘)·`db.py`·`schema.sql`(v30),
  `web/src/api.ts`·`shell/ProgressCards.tsx`·실행 상세·결과 패널.
- 시험: 새 `tests/test_unknown_runs.py`, `test_web_shell.py` +1, 웹 단위(필요하면), 가짜 codex/`FakeCliExecutor` 에 `unknown` 결과 표지(없으면).
- 문서: `decisions.md`(D-98 구현 표시)·`completion-lifecycle.md` 5절·`p4/evidence/P4-10d-results.md`(새)·`DEVELOPMENT.md`·`README.md`.

## 4. 경계

- UI-05b·P5 로 넓히지 않는다. 사용자의 제어부·Runner·DB 원본은 건드리지 않는다(사본만 읽고 이행해 본다). 커밋·push·이슈 닫기는 사용자
  지시가 있을 때만.
- 실제 codex 라이브는 하지 않는다(규칙이 제어부 판정이고 실제 트리 종료 경로는 UI-02·P4-10 에서 실증됨).
