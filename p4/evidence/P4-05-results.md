# P4-05 실행 결과 — 업무 단계 자동 진행과 완료·예외·후속

상태: **완료**  
기준: 설계 v0.8 2차 / D-01~90 / 2026-09-23  
계획: [P4-PLAN-05](../../plans/P4-PLAN-05.md)

## 1. 구현 결과

- **업무 단계 진행기**(`controller/work_progressor.py`, 판정은 `domain/work_flow.py`). 업무화된 Case 의
  다음 걸음 하나를 정해 실행 하나(또는 작업공간 요청·기록 하나)를 만들고 돌아온다. 순서: 의도 초안
  → (구조 보고) → 열린 의도 질문(사람 대기) → 답 반영 재작성 → QG-01(규칙 실패·검토 지적은 지적을
  배정에 실어 재작성, 상한 2회 뒤 사람 대기 / 요구 방식 `light` 면 실행 없는 가벼운 확인 기록 /
  `independent` 면 reviewer·새 세션 검토 실행) → material delta(사람 대기) → 의도 동의(사람 대기)
  → 미해결 피드백(사람 대기) → 수준 → controlled 시작 확인(사람 대기) → 조사 Profile 이면 분석 실행
  하나, 제품 변경 Profile 이면 Fast Lane 결합 기록 또는 설계·계획(사람 검토 설정이면 사람 대기,
  자동이면 필수 항목 미정 시 재작성 상한 2회) → 작업 그래프 순서대로 Task(종류 → 목적·권한, 쓰기
  Task 는 작업공간 요청 뒤 준비 보고를 기다림, 실패 1회 재시도 뒤 사람 대기) → 기준 판정 → 자동
  완료 / controlled 결과 확인(사람 대기) / 미충족·미검증 기준의 예외 수용(사람 대기). **진입 검사를
  우회하지 않는다** — 거부되면 사유를 사람 사유(대기)·일시 사유(다음 사건)·환경 사유(막힘)로 나눈다.
  진행기가 잇는 것은 **업무화 때 진행 행(`case_progress`)을 만든 Case 뿐**이다 — 관리 화면·API 로
  만든 Case 는 그대로 사람·하네스가 진행한다.
- **요청 잠금의 연장**(D-70). 한 요청 안에서 여러 실행이 이어지는 동안 잠금을 유지하고, 사람 대기·
  완료·막힘에서만 요청을 끝낸다(`note_summary` 에 `waiting: <코드>`·`blocked: <코드>`·`done`). 사람의
  결정(동의·확인·답변·검토·피드백 처리·예외·인수·예산 변경·계속 진행) 뒤에는 시스템이 **진행 요청**
  (`origin = human_decision | system_resume`, 여는 메시지 없음)을 열어 이어 간다. 중단·`unknown`·
  `interrupted`·재확인은 요청 기계 그대로이며, 진행 요청이 중단·불명으로 끝나면 진행은 **멈춤**이 되고
  스스로 재개하지 않는다(D-76) — 사람이 계속 진행을 누른다.
- **기준 판정의 제품 기록.** 검증 실행(`criteria`)과 조사 Profile 의 분석 실행(응답 끝 JSON 블록)이
  기준별 판정을 보고하면 결과와 같은 트랜잭션에 `run.criteria_report_json` 으로 남기고, 진행기가 **한
  번** 구조 검사로 걸러 적는다(`recorded_by = policy:work_progressor`, 근거 = 그 실행·`run_output`·현재
  코드 조합): 실행 완료, 검증 실행은 종료 코드 0 인 명령 하나 이상, 그 Task 에 `verifies` 로 연결된
  기준만(분석 실행은 그래프가 없으므로 현재 기준 전부), 의무별 충족 방식(제품 의무 → 구현 변경 관측
  시 `changed_and_verified` 아니면 `already_satisfied`, 원인·조사 → `investigated` + 결론, 보존 →
  `preserved`), 확정 필수 기준의 판단 불가는 `not_met`. 이미 다른 실행으로 충족된 기준은 덮지 않고,
  거부된 보고는 적지 않고 진행 이력에 남는다. 미충족·미검증 보고는 그대로 적힌다.
- **Runner·배정 내용.** 배정에 `task`(Task 요약·완료 조건·저장소·연결 기준 — 제어부가 이미 가진 짧은
  요약), 조사 Profile 분석 실행의 `criteria`, 의도 재작성의 `gate_findings`, 종료 Case 응답의
  `closed_case` 를 싣는다. 지시문은 "--- 이 실행의 작업 ---"·"--- 확인할 성공 기준 ---"·"요청 정합성
  확인(QG-01)의 지적" 블록을 붙이고, 검증·분석 응답 형식에 `criteria` 가 있다. 구현·검증·분석의 지시
  원문은 **업무 요청 메시지 원문**이다 — 제어부는 본문을 만들지 않는다.
- **완료 후 설명**(D-87). 종료 Case 의 일반 메시지를 **설명 전용**으로 받는다(`send.general.note =
  explanation_only`). 진입 검사는 요청에 묶인 읽기 전용 논의 응답에만 `case_already_closed` 를 묻지
  않는다 — 다른 모든 목적·정책 변경은 그대로 거부다. 종료 시점의 소비·한도를
  `closure_record.snapshot_json` 에 남기고 `budget_state` 가 `at_closure`·`since_closure`·
  `changes_after_closure` 를 나눠 보인다. 예산 한도만은 종료 뒤에도 바꿀 수 있다(이력, 판정 불변).
- **후속 Case**(D-33·D-78). 종료 Case 의 응답에 종료 판 해석 규칙(설명 / 수정 요청)이 붙고, AI 가
  `work_request` 로 읽으면 처리기가 **연결된 새 대화**를 만들어 그 메시지를 첫 메시지로 옮겨 적고
  (같은 원문 참조·같은 접수·새 요청) 새 대화의 응답 실행을 바로 만든다. 새 대화는 준비 단계이며
  이전 동의·Profile·권한을 승계하지 않는다. 원래 Case 의 메시지·응답·해석·연결은 남는다.
- **화면**(`web/src/shell/ProgressCards.tsx`). 진행 배너(진행 중·확인 필요·막힘 + 다시 시도·멈춤 +
  계속 진행·완료), 확인 카드(의도 동의 — 결과물 패널에서 그 버전 원문을 연 뒤 버튼이 열림,
  controlled 시작/결과 — 대상·해시, material delta, 단계 검토, 피드백 처리, 예외 수용 + 최종 인수 —
  기준 선택·범위 입력, 그 밖의 대기 — 다시 시도·관리 화면), 이월 질문의 질문 카드, 종료 Case 의 설명
  전용 안내, 후속 이동 카드·이전 업무 줄, 목록 배지(확인 필요·막힘·멈춤), 결정 사항의 진행 이력.
  진행 상태가 바뀌면 상세를 바로 다시 묻는다. 관리 화면은 그대로다.
- **설정.** `HADS_AUTO_PROGRESS_WORK`(기본 `1`) — 처리기가 켜져 있을 때만 유효하며 끄면 UI-03 계약
  (업무화까지, 업무 단계는 관리 화면·하네스)이다.
- 스키마 **v20**: `conversation_request` 재구성(`opened_by_message_id` NULL 허용, `origin`·
  `origin_ref`), 새 표 `case_progress`·`case_progress_event`, `run.criteria_report_json`,
  `closure_record.snapshot_json`. 이행은 표·컬럼만 만들고 옛 요청은 `user_message` 다.

## 2. 성공 기준 근거

시험은 `tests/test_work_progressor.py`(14)·`tests/test_closure_follow_up.py`(4)·
`tests/test_web_shell.py`(+1, 실제 브라우저)와 표시한 기존 파일이다.

| 기준 | 근거 |
|---|---|
| AC-1 | `test_a_clear_feature_request_runs_to_auto_completion_with_only_the_agreement`(업무화 뒤 `intent_authoring` 이 같은 요청·전송 잠금), `test_request_processor.py::test_a_case_that_already_started_work_refuses_the_ai_start`(사람의 `work-start` 도 같다) |
| AC-2 | `test_intent_questions_stop_the_flow_and_a_card_answer_resumes_it`(질문 대기·전송 열림·카드 답변 뒤 진행 요청·답 반영 재작성·고정 문맥의 답) |
| AC-3 | 같은 대표 시험의 가벼운 확인(`method = light`, 실행 없음), `test_gate_findings_are_repaired_with_the_findings_in_the_assignment_up_to_the_limit`(독립 검토 3회·재작성 2회·배정의 지적 블록·상한 뒤 사람 대기) |
| AC-4 | 대표 시험(동의 대기·`waiting: intent_agreement`·동의 뒤 `human_decision` 진행 요청), 브라우저 시험(원문을 열기 전에는 동의 버튼이 닫혀 있고 연 뒤 열림) |
| AC-5 | `test_admission_refusals_are_sorted_into_human_transient_and_environment`(`material_delta_unconfirmed` → 사람 대기), 진입 거부 경로 `_create_run` |
| AC-6 | `test_controlled_stops_at_the_start_and_at_the_result_candidate`(시작 확인 대기 — 대상 의도 버전·해시, 결과 확인 대기 — 후보·해시, 확인 뒤 시스템 종료·`mode = human`) |
| AC-7 | 대표 시험(결합 기록 하나·`auto_conditions_met`·설계 없음), `_stage_step` 의 사람 검토·재작성 상한 규칙 |
| AC-8 | 대표 시험(작업공간 요청 → 준비 보고 → 구현 → 검증 순서, 실행 전부 요청에 붙음), `test_a_failed_task_is_retried_once_and_then_waits_for_a_person` |
| AC-9 | `test_criteria_reports_are_filtered_by_structure_not_by_trust`(연결·성공 명령·미충족 유지·판단 불가), 대표 시험(`recorded_by`·근거 실행·`changed_and_verified`), `test_unresolved_criteria_wait_for_a_person_and_an_exception_closes`(`not_met` 그대로) |
| AC-10 | 대표 시험(자동 완료 `auto_policy`·사람 결정은 동의 하나), `test_unresolved_criteria_…`(후보·예외 카드 대기·자동 정책 거부·사람 예외+인수 → `closed_with_exceptions`) |
| AC-11 | `test_a_research_case_reports_its_conclusions_from_the_analysis_run[determined·inconclusive]`(분석 실행 하나·읽기 전용·기준 목록 지시·`investigated`·판단 불가 → `not_met` 대기) |
| AC-12 | `test_a_failed_task_is_retried_once_and_then_waits_for_a_person`(실패 2회 → 대기 → 계속 진행), 순수 규칙 시험의 환경 사유 분류 |
| AC-13 | `test_a_stopped_progress_request_pauses_and_resume_continues`(중단 → `interrupted` → 멈춤·자동 재개 없음 → 계속 진행 → `system_resume` 요청 → 종료), `test_recovery_pauses_a_running_progress_whose_request_already_ended` |
| AC-14 | `test_a_work_stage_message_gets_a_read_only_reply_and_nothing_else_moves`(해석 규칙 없음·응답만·대기 그대로·처리기가 끝냄) |
| AC-15 | `test_a_closed_case_answers_explanations_and_counts_them_after_the_closure`(설명 전용 열림·응답·종료 뒤 소비 1·snapshot 불변·진행 `done` 유지), `test_a_closed_case_still_refuses_work_runs_and_policy_changes_but_takes_a_budget_change` |
| AC-16 | `test_a_change_request_after_the_closure_moves_to_a_linked_new_conversation`(연결·옮긴 메시지·준비 단계·동의 없음·새 대화의 업무화) |
| AC-17 | `test_turning_the_processor_off_turns_the_progressor_off`, 기존 시험 전부 통과(3절) |
| AC-18 | `test_a_v19_database_gets_no_progress_it_never_had`(커밋된 v19 스키마로 만든 DB → v20, 재구성·색인·옛 요청 `user_message`·진행 표 비어 있음·CHECK·멱등) |
| AC-19 | 브라우저 `test_the_work_stage_runs_by_itself_and_stops_only_at_the_cards`(질문 카드 → 동의 카드(원문 열기 전 닫힘) → 자동 완료 → 진행 이력 → 설명 전용 입력 → 후속 이동 카드 → 새 대화의 업무화), 기존 `test_a_conversation_gets_answered_…` 의 진행 배너·전송 열림 |
| AC-20 | 3절 — 실제 Edge·실제 codex |
| AC-21 | `test_the_controller_keeps_no_bodies_in_the_new_tables`(기존 데이터 경계 시험 통과), 강제 축 넷 그대로(5절), 진행기가 만든 결정은 없음(대표 시험의 사람 결정 목록) |

## 3. 검증

### 자동 시험

- 기준선(이 세션 시작, 변경 전): `scripts\run-tests.ps1` → 웹 빌드 성공, 웹 단위 **18**, pytest
  **613 통과 + 1 실패**(알려진 P4-02 시계 해상도 흔들림), P1 계약 unittest **18** 통과(따로 실행).
- 최종: `scripts\run-tests.ps1` → 웹 빌드 성공, 웹 단위 **18**, pytest **633 통과·0 실패**(7분 38초, 기준선 614 에서 +19, 이번에는 흔들리는 P4-02 시험도 통과), P1 계약 unittest **18** 통과. 첫 전체 실행은 가짜 codex 의 저장소 밖 실패 2건(4절)과 흔들리는 시험 1건으로 실패했고, 고친 뒤 마지막 코드 변경 뒤에 다시 돌린 결과다.
- **기존 시험의 의미를 검토해 고친 것(검사를 지우지 않았다):**
  - `test_request_processor.py` 두 건 — "업무화는 실행을 시작하지 않는다(응답 하나뿐)"·"응답 뒤 요청
    `completed`" 를 "업무화 뒤 진행기가 같은 요청에 의도 초안 실행을 만들고 요청은 처리 중" 으로. UI-03
    계약이 P4-05 로 바뀐 자리다.
  - `test_conversation.py` 의 `send.general` 사전 비교에 `note: None` 추가(종료 뒤 설명 전용 표시).
  - `test_policy.py::test_policy_cannot_be_changed_after_closure` — 예산 한도만 종료 뒤에도 받는다
    (D-87). Autonomy 변경 거부는 그대로다.
  - `test_migration.py` v18→v19 시험의 `== 19` → `>= 19`(v20 고정은 새 시험).
  - `test_web_shell.py` 의 업무 단계 배너 단언 — "아직 자동으로 진행하지" → 진행 배너 상태·질문 카드
    대기.
- 브라우저 시험은 UI-03 그대로 실제 uvicorn·실제 Runner 프로세스·PATH 앞 가짜 `codex`·설치된 Edge 다.
  가짜 `codex` 가 업무 단계 목적(의도 초안·검토·결합 기록·설계·계획·구현(`reader.py` 실제 변경)·
  검증(기준 판정 포함)·분석)에 정해진 응답을 낸다(`tests.conftest` 의 응답 재사용).

### 실제 CLI·실제 브라우저 (AC-20)

`ui/live/p405_progress.py` 로 실제 `codex-cli 0.156.1` 과 설치된 Edge 를 썼다. 작은 저장소
(README·`app.py`) 하나, 새 대화 하나. **제품 코드를 import 하지 않고** HTTP·브라우저·OS 로만 본다.
라이브 데이터는 `%LOCALAPPDATA%\Temp\hads-p4-05-live\000941413`, 저장소 `var\` 는 건드리지 않았다.
증거 사본은 `p4/evidence/P4-05-live*`(로그·결과 JSON·화면)다.

**네 번째 시도에서 통과했다** — 태그 `000941413`, 제품 규칙 **16/16**, 관찰 15, 종료 뒤 이 라이브의
남은 프로세스 0. 앞선 세 시도는 제품 규칙 위반 하나(첫 시도: 동의 대기의 사용자 요청이 사유 없이 끝남 →
`keep_request`, 4절), 라이브 도구의 경합 하나(두 번째: 저장 순간의 조회, 4절), 라이브가 다루지 않은 대기
하나(세 번째: 이월 질문, 4절)로 끝났다. 라이브 안의 AI 판단은 관찰로만 적었다.

| 단계 | 제품 규칙(전부 OK) | 관찰(AI 판단·환경) |
|---|---|---|
| A 업무화 | 업무화 뒤 진행 행이 생기고 첫 걸음(`intent_authoring`)이 **같은 요청**에 붙음. 의도 초안이 도는 동안 전송 잠금(요청 유지) | 해석 `work_request`·`feature`·적용, 응답까지 15초 |
| B 카드 | 동의 대기에서 전송 열림·요청 종료, 종료 사유 `waiting: intent_agreement`. 동의 버튼은 원문을 열기 전에는 닫혀 있고 연 뒤 열림. 동의 뒤 시스템이 **진행 요청**(`human_decision`, `agreement:dec-…`, 여는 메시지 없음)을 열어 이어 감 | 이번에는 의도 질문 없음. QG-01 **독립 검토** 통과(`standard`) — 첫·세 번째 시도는 가벼운 확인(`simple`)이었다 |
| C 자동 진행 | 이월 질문 대기에서 전송 열림·요청 종료, 답 뒤 진행 요청(`human_decision`, `intake:…`). 실행 11개가 **전부 요청에 붙음**(실행 사이 잠금). 제품이 적은 기준 판정(`policy:work_progressor`)은 검증 실행을 근거로 함. 자동 정책이 예외를 스스로 수용하지 않음(`waiting_final_acceptance`, 종료 없음). 사람의 예외 수용으로 종료·원래 판정 보존(`closed_with_exceptions`, 예외 3), 종료 시점 소비 snapshot 있음 | 실제 AI 가 계획에 질문 하나를 이월("Python 검증 환경 지정"). 실행 순서 논의 응답→의도 초안→독립 검토→설계→계획×2→구현×2(T1·T2)→검증×3(T3~T5). 설계·계획 `auto_conditions_met`, 작업 5개 `done`. **기준 C-01~03 전부 `unverified`** — codex 의 샌드박스 셸이 `python`·`rg` 를 찾지 못해(종료 코드 1) AI 가 판단 불가로 보고했고 제품은 그대로 두었다. 사람 결정은 동의 하나뿐이었고 예외 수용은 라이브가 사람으로 했다. 종료 snapshot: 실행 11(검토 1), 입력 1,174,179·출력 26,664 토큰, 실행 702.8초·경과 723.0초 |
| D 종료 뒤 설명 | 설명 응답이 같은 대화에 붙고 종료 기록 불변. 설명 소비가 **종료 뒤 소비**로 나뉨(실행 1, 입력 16,797·출력 468 토큰, 16.4초). 설명이 새 대화를 만들지 않음 | 설명 내용은 AI 의 것이다 — "당시 실행에서는 파일 수정이나 명령 실행을 하지 않았습니다" 라고 답했는데 실제로는 구현 2·검증 3 실행이 있었다. 제품은 설명의 진위를 판정하지 않는다(5절) |
| E 후속 | 옮겨지지 않았으면 연결 없음 | AI 가 수정 요청("…ERROR 대신 WARN 도…")을 `discussion`(`not_a_work_request`)으로 읽어 후속 Case 가 생기지 않았다 — 제품 규칙 위반이 아니라 AI 판단. 후속 이동 경로는 브라우저 시험(가짜 codex)이 본다 |

화면: `P4-05-live-A-work.png`(진행 배너·잠금), `B-agreement.png`(동의 카드), `C-running.png`,
`C-exception.png`(예외 카드), `C-closed-with-exceptions.png`, `D-explanation.png`(설명 전용 안내·응답).

## 4. 구현 중 찾은 것

- **독립 검토의 보고는 결과 보고 뒤에 온다.** Runner 가 `send_result` 뒤에 `send_gate_review` 를 보내므로
  결과 보고 시점의 게이트는 아직 `not_run` 이고, 진행기가 그 자리에서 두 번째 검토를 만들었다. 완료된
  검토 실행이 있는데 판정이 붙지 않았으면 기다리고(`review_pending`), 검토 보고 경로에서 진행기를 다시
  부른다.
- **가짜 codex 가 앞선 대화의 표지를 다시 읽었다.** `HADS_FAKE_WORK` 를 고정 문맥에 남은 이전 메시지에서
  찾아 설명 질문을 업무 요청으로 읽었다(시험 도구). 사용자의 마지막 메시지(고정 문맥 뒤)에서만 읽게 했다
  — 실제 AI 에게 준 규칙("마지막 메시지가 명시적으로 요청할 때만")과 같은 자리다.
- **의도 동의 카드가 옛 상세를 보았다.** 상세 조회(5초)가 대기 기록보다 늦으면 카드가 이전 버전을
  가리켰다. 카드는 대기가 가리킨 버전을 `intent_versions` 에서 찾고, 진행 상태가 바뀌면 상세를 바로
  다시 묻는다.
- **처리기의 종료 기록과 진행기의 종료 기록.** 사람 대기에 이른 사용자 요청은 진행기가 대기 코드와 함께
  끝내고, 처리기의 뒤이은 종료 기록은 같은 결과의 재전송으로 흡수된다. 조건이 그대로인 같은 대기(업무
  단계의 대화 응답 뒤)에는 이력을 다시 적지 않고 처리기가 끝낸다.
- **대화 조회가 두 SELECT 사이에 열린 요청을 반쯤 보았다.** 라이브 두 번째 시도에서 브라우저의 메시지
  저장과 같은 순간의 조회가 `current_request: null` 과 처리 중 요청이 든 `requests` 를 함께 돌려줬다
  (현재 요청을 먼저, 목록을 나중에 읽었다). 한 벌의 판정은 한 번 읽은 행에서 나오게 했다 — 현재 요청도
  같은 목록에서 고른다. 라이브의 "처리됐다" 판정도 요청이 끝난 것으로만 보게 고쳤다(시험 도구).
- **실제 AI 는 설계·계획에 질문을 이월한다.** 라이브 세 번째 시도에서 진행기가 준비 뒤 작업 그래프 앞에서
  `deferred_questions` 사람 대기로 멈췄다 — 이월 질문이 막는 작업 앞에서 멈추는 제품 규칙 그대로였고
  가짜 codex 는 질문을 이월하지 않아 시험이 그 자리를 지나쳤다. 라이브 스크립트가 이월 질문 카드에
  답하고 이어 가게 했다(시험 도구, 제품 변경 없음).
- **가짜 codex 가 저장소 밖에서 죽었다.** 업무 단계 응답을 `tests.conftest`·`runner.prompts` 에서 가져오게
  하면서 저장소 루트를 잇지 않아, 임시 작업 디렉터리에서 부르는 어댑터 시험(`test_process_control` 2건)이
  실패했다(첫 전체 실행에서 드러남). 가짜가 자기 위치로 저장소 루트를 잇는다(시험 도구).

## 5. 경계와 남은 것

- **강제 축은 넷 그대로다.** 진행기·기준 기록·설명 응답·후속 대화가 권한·동의·인수를 만들지 않는다.
  사람의 결정은 사람 경로(동의·확인 지점·delta·검토·피드백·예외·인수)에서만 기록되고 진행기는 "필요하다"
  를 값으로 낼 뿐이다. 게시 허용은 여전히 기록뿐이다(P5).
- **넣지 않은 것**(P4-PLAN-05 2절·3.9절): QG-02~07 자동 실행·repair(명시 ON 게이트가 막으면 사람 대기·관리
  화면), 검증 1회 중단, 시간 예산 자동 중단, 활성 Case 목적·Profile 변경(D-86, UI-04), 상세 설정·알림·검색
  (UI-04), 권한 확대 카드(P5), AI 판정의 진위(구조 검사만).
- **사람에게 확인을 요청할 것**(plan 5절): (1) 기준 판정을 검증·분석 실행의 보고로 제품이 적는 규칙과
  구조 검사의 범위, (2) 자동 모드에서도 의도 동의를 사람이 하는 점(기존 계약 유지), (3) 재작성 2회·
  재시도 1회 상한. 셋 다 기존 결정·코드와 일치하는 쪽으로 정했다. **사용자의 답(2026-09-24):** (1)·(2)는
  그대로 간다. (3)은 설정으로 바꾸되 다음 작업과 함께 — 시스템 기본값(환경 변수) + Case 별 이력 조정,
  상한 대기 카드의 "한도를 올리고 계속", Project 층은 UI-04. `P4-05b` 로 P4-06 과 같은 세션에서 한다
  (DEVELOPMENT.md 1.8절).
- **검증은 CLI 의 셸 환경에 달려 있다.** 라이브의 실제 codex 는 샌드박스 셸에서 `python`·`rg` 를 찾지
  못해 기준 셋을 판단 불가로 보고했고, 제품은 그것을 `unverified` 로 두어 사람 예외 수용으로만 닫혔다.
  제품이 실행 환경(인터프리터·도구 경로)을 마련해 주는 일은 이 작업의 범위가 아니며 Project 별 환경
  설정은 뒤 작업(UI-04 상세 설정)의 후보다. 종료 Case 의 설명 응답 내용도 AI 의 것이며 제품은 진위를
  판정하지 않는다(3절 D).
- 남은 한계는 [DEVELOPMENT.md](../../DEVELOPMENT.md) 9절 표에 배정했다.
