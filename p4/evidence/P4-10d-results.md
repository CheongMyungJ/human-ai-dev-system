# P4-10d 결과 — 결과 모름(`unknown`) 실행의 종료 막힘 해소 (이슈 #10, D-98)

세션 S-038(2026-09-25). plan: [P4-PLAN-10d](../../plans/P4-PLAN-10d.md). 사용자 결정 **D-98**(2026-09-25, S-037 — 권장안 B + A, UI-05b 앞):
끝났지만 결과를 모르는 실행이 업무 종료를 영원히 막지 않게 한다. 함께 고칠 버그: 진행기가 뒤따를 보고가 없는 `busy`(`runs_unsettled`)에서
진행 요청을 "처리 중" 으로 영구히 열어 두던 것.

## 1. 지금 제품이 하는 일

- **버그 — 미정리 실행은 사람 대기다.** 진행기가 종료 단계에서 결과를 확정할 수 없는 실행을 만나면 `busy/runs_unsettled` 로 돌아가지 않고
  새 대기 사유 **`unsettled_runs`**("결과를 모르는 실행 확인 필요")로 멈춘다 — 진행 요청이 끝나고(화면의 "처리 중" 이 사라진다) Case 는
  `waiting_human` 이다. 대기에 실행 목록(실행·작업·목적·결과·끊긴 이유·끝난 시각·요청·트리 종료 확인 여부·사람 확인 가능 여부, 앞 8건 +
  전체 수)을 싣는다.
- **B 자동 대체(도출, 저장 없음).** 끝난 `unknown` 실행은 (a) 트리 종료가 확인됐고(`execution_unconfirmed` 아님) (b) 같은 Case·같은
  작업(`task_id`)·같은 목적의 **뒤에 만든** 실행이 `completed` 로 끝났고 (c) 논의 응답이 아니면 종료를 막지 않는다
  (`domain/run_control.superseding_run` — `unsettled_runs`·실행 조회·카드가 같은 함수). 결과는 `unknown` 그대로다. 진행기가 처음 볼 때
  진행 이력에 한 줄(`unknown_run_superseded`, 대체한 실행 포함)을 남긴다. 도출이라 옛 Case 에도 곧바로 적용된다.
- **A 사람 확인(스키마 v30 `run_unknown_confirmation`).** B 로 풀리지 않은 끝난 `unknown` 실행은 카드에서 "작업공간 영향을 확인했다"(필수
  표시) + 사유(1~200자)로 확인을 적으면 종료를 막지 않는다 — `POST /api/cases/{case}/runs/{run}/unknown-confirmation`(새로 적으면 201,
  재전송은 200·처음 기록). 결정 기록(`decision.kind = unknown_run_confirmation`, 대상 = 실행)과 한 트랜잭션. 결과는 `unknown` 그대로이고
  그 실행의 기준 보고는 판정에 쓰지 않는다. 인수·예외·다른 실행의 허용이 아니다. 거부: 종료된 Case(409)·다른 Case 의 실행(404)·표시/사유 없음
  (422)·끝나지 않은 실행·`unknown` 이 아닌 실행·이미 대체된 실행(409), **트리 종료가 확인되지 않은 실행**(409 `execution_unconfirmed`).
- **트리 종료를 모르는 실행은 사람이 대신 확인하지 않는다**(UI-02 규칙 유지 — D-98 은 "끝났지만 결과를 모르는 실행"). 카드는 그 실행을 "PC 가
  아직 확인하지 않았다" 로 보이고 확인 입력을 열지 않는다. PC 의 잔류 재확인이 오면(`/api/runner/runs/{run}/residual`) 제어부가 자동 완료를
  시도하고 그 대기에서 멈춘 진행기를 다시 부른다.
- **풀린 뒤 이어 가기.** 진행기의 `advance` 가 처음에 `maybe_auto_complete` 를 한 번 부른다(조건이 안 되면 아무 것도 하지 않는 기존 함수).
  A 기록 뒤에는 자동 완료 시도 + 사람 입력 훅, 잔류 재확인 뒤에는 자동 완료 시도 + `on_runs_settled`. 그래서 **고치기 전에 걸린 Case 는
  제어부 재시작 복구(`recover`)에서 닫힌다**(아래 3절).
- **다른 `busy` 점검 결과.** `runs_unfinished`·`gate_review_pending`·`quality_gate_review_pending`·`workspace_pending` 은 뒤따르는 보고가
  잇는다. 보강 둘: (a) **의도 구조 보고 끝점**이 진행기를 부른다 — 구조가 결과 보고 뒤에 오면(보고 실패 뒤 재전송 등) 진행이 `running` 에
  머물던 자리; (b) **요청 없는 실행**(관리 화면·API)의 결과 뒤 진행기가 Case 의 열린 진행 요청을 넘겨받아 사람 대기·완료면 그것도 끝낸다.
- **화면.** 대기 카드 `결과를 모르는 실행`(실행별 실행 보기·종료 확인 여부·확인 표시·사유·"확인했다 — 종료를 막지 않음"), 작업 탭 실행 목록의
  `대체됨`/`사람이 확인함` 표시와 실행 상세의 한 줄(`unknown_settlement`). 관리 화면(`ResultPanel`)은 바꾸지 않았다 — UI-05b 에서 걷어 낼
  화면이라 plan 의 "결과 패널 목록" 은 새 화면(카드·작업 탭)으로 대신했다.

## 2. 검증

| AC | 결과 | 근거 |
|---|---|---|
| AC-1 요청이 처리 중으로 남지 않고 `unsettled_runs` 대기 | 충족 | `tests/test_unknown_runs.py::test_an_unknown_run_without_a_later_attempt_waits_for_a_person_and_a_confirmation_closes` |
| AC-2 B 대체 → 자동 완료, 결과 그대로, 조회·이력 | 충족 | 같은 파일 `test_a_retried_unknown_attempt_is_superseded_and_the_case_closes` |
| AC-3 B 가 적용되지 않는 경우 | 충족 | 같은 파일 `test_supersession_needs_a_later_completed_attempt_of_the_same_work_and_a_confirmed_end`(순수 규칙) |
| AC-4 A 확인·거부·재전송, 결과 그대로 | 충족 | AC-1 의 시험 + `test_a_person_cannot_confirm_a_run_whose_end_is_not_confirmed`(종료 미확인 409 → PC 재확인 뒤 확인 가능 → 완료) |
| AC-5 이슈 #10 모양의 복구 | 충족 | `test_a_case_stuck_on_runs_unsettled_closes_on_restart_recovery` + 사용자 DB **사본** 관찰(아래 3절) |
| AC-6 다른 `busy` 보강 | 충족 | `test_the_intent_structure_report_arriving_after_the_result_continues_progress`(구조 보류 → 늦은 보고로 이어짐), 요청 없는 실행 → AC-1 시험 |
| AC-7 화면 | 충족 | `tests/test_web_shell.py::test_unknown_runs_are_superseded_or_confirmed_on_a_card_and_the_work_closes`(실제 Edge·실제 Runner·가짜 codex `HADS_FAKE_VERIFY_UNKNOWN`·`HADS_FAKE_REPLY_UNKNOWN`) |
| AC-8 v30 이행 | 충족 | `test_migration_to_v30_keeps_rows_and_adds_the_confirmation_table` + 사용자 DB 사본 v28 → v30 |
| AC-9 전체 시험 | 충족 | 아래(종료 코드 0) |

### 전체 실행

| 실행 | 웹 빌드 | 웹 단위 | pytest | P1 계약 | 종료 코드 |
|---|---|---|---|---|---|
| S-038 기준선(변경 전, `15cb44f`) | 성공 | 42 | 814 통과·0 실패·2 건너뜀(20분 53초) | 18 | 0 |
| P4-10d 최종 | 성공 | **44** | **822 통과·0 실패·2 건너뜀(21분 10초)** | 18 | 0 |

늘어난 시험 = `tests/test_unknown_runs.py` 7 · `tests/test_web_shell.py` +1 · 웹 단위 `unknownRuns.test.ts` 2. 기존 시험의 뜻은 바뀌지 않았다
(`runs_unsettled` 를 `busy` 로 고정한 시험은 없었다).

## 3. 이미 걸린 Case 의 확인 (이슈 #10 사례)

사용자의 제어부 DB(`var/controller/controller.sqlite3`)를 **읽기 전용 백업으로 스크래치에 복사**해(원본·사용자의 제어부·Runner 는 건드리지
않음) 이 코드로 이행(v28 → v30)하고 `WorkProgressor.recover()` 를 돌렸다.

| | 전 | 후 |
|---|---|---|
| Case `case-e484766d9fec98a7` | `in_progress` | `closed`(종료 `completed`) |
| 진행 | `running` / `task:T2` | `done` / `closed` |
| 요청 `req-539044a647b2cb84` | `processing` | 끝남 |
| 미정리 실행 | T2-1·T2-2 (고치기 전 규칙) | 없음 — 둘 다 `superseded` by T2-3(결과는 `unknown` 그대로) |

복구 결과 `{'advanced': 1, 'paused': 0}`, 진행 이력 끝: `unknown_run_superseded` ×2 → `closed/done`. 사용자의 제어부를 이 코드로 다시 띄우면
기동 복구가 같은 일을 한다(이행 v28 → v30 포함 — 그 DB 는 P4-10 이전 코드로 떠 있어 아직 v28 이다). **사용자 결정(2026-09-25): 이 Case 는
버린다** — 원본에서 닫을 필요가 없고, 위 관찰은 수정의 증거로만 남는다.

## 사용자 지시로 한 일

"커밋푸시하고 이슈10 닫고 이 케이스는 버릴거니까 신경안써도돼" — 변경 커밋 **`fcfd9be`** 와 인계 기록 커밋을 `origin/main` 에 push 했고(push 전
fetch 로 원격 `15cb44f` 확인), 이슈 #10 에 결과 댓글을 달고 닫았다.

## 4. 한계·넘기는 것

- B 의 "같은 작업" 은 같은 `task_id`·같은 목적이다. 수정 사이클의 `FIX<n>` 처럼 다른 작업 키로 다시 한 일은 대체가 아니다 — 그런 `unknown` 은
  A 로 푼다.
- A 는 사람의 판단 기록이다. 제품은 "작업공간 영향을 확인했다" 는 표시가 사실인지 검사하지 않는다(실행 상세의 출력·명령·작업공간 효과를 보여
  줄 뿐이다).
- 트리 종료를 모르는 실행은 PC 가 다시 연결돼 확인할 때까지 풀리지 않는다(UI-02 규칙) — PC 를 영영 쓸 수 없으면 그 업무는 취소(P4-09(e))
  로 끝낸다. 사람이 종료를 대신 선언하는 경로는 새 제품 판단이다.
- 실제 codex 라이브는 하지 않았다 — 판정은 제어부 규칙이고 실제 트리 종료 경로는 UI-02·P4-10 이 실증했다.
