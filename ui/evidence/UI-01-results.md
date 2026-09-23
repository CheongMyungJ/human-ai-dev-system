# UI-01 실행 결과 — 대화·요청 기반

상태: **완료**  
기준: 설계 v0.8 2차 / D-01~90 / 2026-09-23  
계획: [UI-PLAN-01](../../plans/UI-PLAN-01.md)

## 1. 구현 결과

- **목표·Profile 없이 대화를 시작한다.** `POST /api/projects/{pid}/conversations` 가
  준비 단계(`case.stage = discussion`) Case 를 만든다. `kind` 는 `undecided` 이고 Profile·
  정의판·출처는 NULL 이다. **feature 로 채우지 않는다** — 그 값이 곧 기능 개발 조건표를
  고른다. `kind` 가 `NOT NULL` 이라 NULL 대신 "정하지 않았다"를 값으로 남겼고, 40여 표가
  참조하는 중심 표를 재구성하지 않았다. 기존 생성 API 는 그대로 업무 단계 Case 를 만들고
  `undecided` 를 받지 않는다.
- **Case 의 종료·단계·보관·현재 요청을 서로 다른 축으로 뒀다.** 종료는 `status` 그대로,
  단계는 `case.stage`(NULL = UI-01 이전 Case 이며 업무 단계로 **도출**, 출처
  `created_before_stage`), 보관은 `case_visibility_event` 이력의 최신 행, 현재 요청은
  `conversation_request` 다. 보관은 종료·요청·실행을 바꾸지 않는다. "답변 필요"는 열린
  질문에서만 나온다 — 질문 없는 휴식은 답변 필요가 아니다.
- **대화 메시지.** `conversation_message` 가 Case 안의 연속 순번·작성자(사용자/AI)·종류
  (일반·정정·카드 답변·AI 응답)·원문 참조·해시·요약·관계만 갖는다. **본문 컬럼이 없다.**
  접수 상태는 intake 에서 도출한다 — `pending`(중계됨, 접수 아님)·`stored`(**접수 완료**)·
  `lost_before_persist`. 해시가 다른 저장 보고는 409 이고 메시지는 `pending` 에 머문다.
- **자료 참조**(`conversation_message_ref`)가 산출물의 id·버전·**그 시점 해시**·위치, 또는
  등록 저장소의 경로·위치·관측 해시를 고정한다. 다른 Case 의 산출물·없는 산출물·미등록
  저장소·빈 경로는 원문 접수 **전에** 거부된다. 이미지·외부 업로드는 없다(D-81).
- **현재 요청과 서버 잠금.** 일반·정정 메시지가 접수와 **같은 트랜잭션**에서 요청을 연다.
  요청이 `processing`·`unknown` 이면 같은 Case 의 일반·정정 메시지, 피드백
  (`/feedback`), 사람 의도 초안(`/intent-drafts`)이 409 다 — 피드백 경로가 잠금의
  우회로가 되지 않는다. 활성 요청은 Case 당 하나이며 **DB 부분 유일 색인**이 마지막
  방어선이다. 대기열이 없고 막힌 입력은 어디에도 남지 않는다. 다른 Case 는 막히지 않는다.
- **요청 종료는 명시 기록이다.** 연결된 Run 이 끝났다는 사실로 잠금을 풀지 않는다(내부
  Run 사이). 종료 기록은 미종료 Run 이 있으면 거부되고(`request_runs_unfinished`), 결과를
  모르는 Run 이 있으면 요청이 `unknown` 으로 남아 잠금을 유지하며, 여는 메시지가 저장되지
  않았으면 `completed` 로 적지 않는다. 여는 메시지가 유실되고 연결 Run 이 없으면 **시스템이**
  `failed(original_lost_before_persist)` 로 닫는다. `unknown` 의 해제 경로는 UI-02 다.
  요청 종료 뒤에는 Case 가 닫히지 않아도 전송이 열린다.
- **멱등 접수와 대조.** `client_message_id` 재전송은 같은 내용이면 새 intake·메시지·요청
  없이 **200** 과 기존 결과, 다른 내용이면 409 다. 재전송 판정은 잠금보다 먼저다 — 요청을
  연 메시지의 재전송이 자기 요청 때문에 거부되지 않는다.
  `GET …/messages/by-client-id/{cid}` 가 접수 여부를 대조하고 받지 않은 전송은 404 다.
- **새 경로는 중계 본문을 기록보다 먼저 넣는다.** P2 경로는 커밋 뒤 버퍼에 넣어, 그 사이
  Runner 폴링이 끼면 접수가 유실로 표시됐다. 메시지 경로는 intake id 를 먼저 만들어 본문을
  넣고 기록하며, 기록되지 않으면 뺀다. 기존 네 경로는 바꾸지 않았다(DEVELOPMENT.md 9절).
- **카드 답변.** `card_answer` 는 질문과 **카드가 보인 의도 버전**을 받고, 그 버전이 최신이
  아니면 `question_target_stale`, 이미 답했으면 `question_already_answered` 다. 검사가 원문
  접수보다 먼저라 거부된 답은 intake 를 남기지 않는다. 처리 중에도 받고, **요청을 열지도
  닫지도 않으며**, 동의·결정·위임 근거를 만들지 않는다. 기존 `/questions/{id}/answer` 도
  대체된 버전의 질문을 원문 접수 전에 거부한다. **답변 원문이 저장 전에 유실되면 질문이
  다시 열린다** — PC 에 닿지 않은 답은 해결이 아니다(기존 경로에도 적용).
- **정정**은 같은 Case 의 사용자 일반·정정 메시지만 대상이며 새 메시지·새 요청이다.
  원본·원본의 요청·Run 은 그대로이고 `corrected_by` 로 관계가 보인다.
- **논의 응답 실행 `discussion_reply`.** 읽기 전용뿐, 코딩 CLI 필요, 요청 연결 필수,
  **지시 = 그 요청을 연 메시지 원문**, 여는 메시지가 저장된 뒤에만. 준비 단계에서는 이
  목적만 열리고 다른 목적은 `case_in_discussion_stage` 다. 예산 예약·정산을 그대로 지나
  소비가 같은 Case 에 쌓이고 hard 한도에 막힌다. 완료 응답의 실행 출력이 **AI 메시지**로
  대화에 붙는다(실행당 하나, 재전송 중복 없음). 결과를 모르는 실행은 AI 메시지가 되지
  않는다. 읽기 전용이라 controlled 시작 확인과 확인되지 않은 누적 변경에 막히지 않는다
  (plan 10절).
- **최초 업무화 `work-start`.** 준비 단계 Case 만, 처리 중 요청을 연 **저장된** 사용자
  메시지에 근거해 같은 Case ID 에 `stage = work`, `kind`, Profile, **정의판 "2"**,
  `profile_source = work_start` 를 한 트랜잭션으로 남긴다. **위임 근거는 그 메시지 하나**
  (`original_request`)이며 앞선 논의·동의는 근거가 아니다. 사용자 결정을 만들지 않으므로
  조사 Profile 의 제품 수정 차단(D-66)이 업무화로 풀리지 않는다. 메시지·요청·Run·예산
  소비·한도·Autonomy·저장소 선택·확인 지점은 옮길 것이 없다 — 같은 Case 다. 업무 단계
  Case 는 거부된다(활성 Profile 이행 D-86 은 별도).
- **대화 고정 컨텍스트.** 새 역할 `conversation_user_message`·
  `conversation_assistant_message`. 저장된 메시지만 순번대로, 지시 원문과 이미 다른 역할로
  들어간 말은 빼고 넣는다. 논의 응답은 그 요청 **이전**의 대화, 의도 작성·QG-01 검토는
  실행 생성 시점까지의 대화 전체를 받는다. 업무화된 Case 의 QG-01 요청 원문은 **업무 요청
  메시지**다. 대화가 없는 Case 의 문맥은 바뀌지 않는다. Runner 표지가 "AI 의 말은 이전
  제안일 뿐 사용자의 요구·결정이 아니다"를 적는다.
- **화면.** 관리 화면에 `ConversationPanel` 을 더했다 — 단계·보관·메시지와 접수 상태·현재
  요청과 실행·전송 가능 여부와 사유(서버 값 그대로)·논의 응답 실행·요청 종료 기록·업무
  시작·보관. 입력은 `stored` 가 될 때만 비우고 같은 입력의 재전송은 같은 식별자를 쓴다.
  새 기본 대화 화면·브라우저 초안 복구는 UI-03 이다.
- 스키마 **v16**: 새 표 다섯(`conversation_request`·`conversation_message`·
  `conversation_message_ref`·`case_work_start`·`case_visibility_event`)과 컬럼 둘
  (`case.stage`·`run.request_id`). 값은 열거형 `CHECK`, 요약 ≤200, 경로 ≤512, 본문 없음.

## 2. 성공 기준 근거

시험 이름은 `tests/test_conversation.py`(표시 없음), `tests/test_migration.py`,
`tests/test_restart_recovery.py` 의 것이다.

| 성공 기준 | 결과·근거 |
|---|---|
| AC-1 준비 Case | `test_a_conversation_starts_without_a_goal_or_a_profile` — `stage=discussion`·`kind=undecided`·Profile/판/출처 NULL·기본 Autonomy 행, Profile 조회 출처 `not_yet_decided`(R1 이전의 `not_recorded` 와 구별), 기존 API 는 `work`/`created_as_work`, `undecided` 409 |
| AC-2 보관 | `test_archiving_is_list_visibility_and_changes_nothing_else` — 보관 뒤에도 `received`·요청 `processing`·전송 409, 같은 보관 재전송이 이력을 늘리지 않음, `include`/`exclude`/`only` 필터, 복원 이력 2건 |
| AC-3 순번·참조·본문 없음 | `test_a_message_keeps_order_and_a_reference_but_never_the_body`(DB·WAL 바이트에 본문 표식 없음, Runner 에는 있음), `test_references_pin_the_version_and_refuse_what_is_not_this_case`(해시 고정·네 가지 거부·intake 수 불변), `test_new_ui01_tables_have_no_body_columns` |
| AC-4 접수 상태 | 위 시험의 `pending → stored`, `test_a_hash_mismatch_is_not_a_received_message`, `test_the_body_is_relayed_before_the_intake_becomes_visible`(커밋 순간 intake `pending` 이고 버퍼에 본문 있음) |
| AC-5 멱등·대조 | `test_resending_the_same_client_message_id_creates_nothing_new` — 200·같은 메시지/요청·intake 수 불변·요청 1건, 다른 내용 409, 대조 `pending→stored`, 미수신 404 |
| AC-6 서버 잠금 | `test_general_input_is_locked_on_the_server_while_a_request_is_processing` — 일반·정정·피드백·사람 초안 모두 409 `request_in_progress`, 거부 뒤 intake·메시지 수 불변, `send.general` 이 같은 사유, 다른 Case 202 |
| AC-7 동시 경쟁 | `test_two_simultaneous_sends_open_exactly_one_request` — 두 연결·두 스레드, 하나 생성·하나 409, 요청·메시지 1건, 활성 요청 둘을 표에 직접 넣으면 `IntegrityError` |
| AC-8 Run 사이 잠금 | `test_the_lock_holds_between_runs_and_opens_only_on_an_explicit_settle` — 첫 Run 종료 뒤에도 409, 두 번째 Run 미종료 시 종료 기록 409 `request_runs_unfinished`, 종료 뒤 Case `received` 인 채 전송 202, 같은 종료 재전송 멱등·다른 결과 거부 |
| AC-9 요청 전이 | `test_request_transitions_do_not_turn_unknown_or_unreceived_into_success`(미저장 완료 거부·그 요청의 Run 거부·실패 기록, 불명 Run → `unknown`·잠금 유지·재종료 거부·AI 메시지 없음), `test_a_lost_opening_message_fails_its_request_instead_of_holding_the_lock`, `test_a_run_cannot_join_a_request_that_ended`(끝난 요청 거부, **검사와 생성 사이 종료 경합**을 재현해 트랜잭션 안 재확인이 거부·기록, 저장 계층 `RequestNotProcessing`) |
| AC-10 카드 답변 | `test_a_card_answer_is_scoped_to_its_question_and_version`(처리 중 202·요청 불변·결정/위임 근거 없음·동의 `never_agreed`, 재답·대상 없음·옛 버전 거부, intake 수로 고아 없음 확인, 기존 경로의 옛 질문 거부), `test_a_lost_answer_reopens_its_question` |
| AC-11 정정 | `test_a_correction_is_a_new_message_and_keeps_the_original` — 원본·원본 요청(`completed`)·Run 보존, `corrected_by`, 처리 중 409, AI 메시지·다른 대화·없는 메시지 대상 거부 |
| AC-12 논의 응답 | `test_a_read_only_discussion_is_not_blocked_by_the_start_check_or_pending_deltas`(controlled 시작 미확인·미확인 누적 변경 상태에서 논의 응답은 허용, 같은 상태의 실험은 두 사유로 거부), `test_the_discussion_stage_opens_only_the_discussion_reply`(다섯 목적 `case_in_discussion_stage`, `request_required`, 쓰기 권한 거부, 지시 불일치, 골격 실행기 거부, 준비 단계 사람 초안 거부·intake 불변), `test_a_discussion_reply_becomes_one_assistant_message_and_counts_on_the_case`(조건표 `conversation`, AI 메시지 1건·재전송 불변, run_count hard 1 도달, `by_purpose.discussion_reply`), `test_the_discussion_prompt_forbids_claiming_work_and_labels_who_spoke` |
| AC-13 최초 업무화 | `test_work_starts_in_the_same_case_and_carries_everything_over`(같은 Case·v2·`work_start`, 메시지·Run·저장소 선택·예산 소비와 한도·Autonomy 보존, 위임 근거 1건 = 업무 요청 메시지·해시, 재업무화·기존 업무 Case 거부), `test_work_start_needs_a_stored_user_message_of_the_current_request`(끝난 요청·AI 메시지·미저장·해석 실행 없음/다른 요청 거부, 같은 요청의 완료 실행으로 AI 해석 업무화) |
| AC-14 기존 경계 | `test_after_work_start_the_existing_gates_still_apply` — 논의 중 정한 controlled 유지·`controlled_start_not_confirmed`, RCA 업무화 뒤 `purpose_outside_case_objective`, feature 업무화 뒤 의도 작성 허용·기준 의무 도출·방식 없는 `met` 409 `satisfaction_required` |
| AC-15 대화 문맥 | `test_runs_receive_the_conversation_as_fixed_context_with_roles`(논의 응답이 앞선 사용자·AI 메시지를 역할대로, 유실 메시지 제외, 지시문 표지·본문 포함, 의도 작성의 지시 메시지 중복 없음, QG-01 `original_request` = 업무 요청 메시지), `test_a_case_without_a_conversation_keeps_its_old_context` |
| AC-16 이행 | `test_a_v15_database_gets_no_conversation_it_never_had` — 커밋된 v15 스키마 DB 의 v1·v2·R1 이전 Case 가 `stage` NULL·Profile 판 불변, 새 표 0행·위임 근거 0행, 조회가 `work`/`created_before_stage`, `stage` CHECK, 반복 이행 멱등. 기존 시험 전부 통과(3절) |
| AC-17 재시작 | `test_conversation_requests_and_lock_survive_a_forced_kill` — **실제 uvicorn 강제 종료**(`taskkill /F /T`) 뒤 단계·업무화·접수·요청 `processing`·보관·잠금 409·재전송 200 복원, 중계 중이던 메시지는 `lost_before_persist`·요청 `failed(original_lost_before_persist)`·자동 재전송 없음·새 식별자 202 |
| AC-18 조회·화면 | `conversation_view` 를 위 시험들이 직접 검사(`send.general` 의 사유·활성 요청 id, `needs_response`, 요청별 Run·미종료·불명 수). 관리 화면 `ConversationPanel` — `npm run build` 성공 |
| AC-19 실제 CLI | 3절 — 실제 `codex-cli 0.154.0` 논의 응답 2회·업무화 뒤 의도 작성 1회, 제품 규칙 20건 통과, 지시와 다른 관찰 없음(2회 실행) |
| AC-20 경계 | `test_the_conversation_grants_nothing`(`enforcement` 불변, 쓰기 허용≠게시, 위임 근거에 결정 없음), `test_new_ui01_tables_have_no_body_columns`, 데이터 경계 표식 시험 |

## 3. 검증

### 자동 시험

- 기준선(이 세션 시작, 변경 전): `scripts\run-tests.ps1` → pytest **481**, P1 계약 unittest
  **18** 통과.
- 최종: `scripts\run-tests.ps1` → pytest **513**, P1 계약 unittest **18** 통과. 새 시험
  32건(`test_conversation.py` 30, 이행 1, 강제 종료 재시작 1). 알려진 deprecation warning
  2건 외 실패 없음.
- 웹: `npm run build` 성공.
- **기존 시험 한 건의 의미를 검토해 고쳤다.** `test_a_v14_database_keeps_its_criteria_and_
  invents_no_obligation` 이 `SCHEMA_VERSION == 15` 를 고정하고 있었다. 이 시험의 뜻은
  "v14 DB 가 **현재 판**으로 이행되고 v15 규칙이 적용된다"이며 앞선 이행 시험들은 모두
  `== db.SCHEMA_VERSION` 만 본다. `>= 15` 로 바꾸고 v16 고정은 새 이행 시험이 맡는다.
  검사를 지우지 않았다.

### 실제 CLI (AC-19)

`ui/live/ui01_conversation.py` 로 실제 `codex-cli 0.154.0` 을 불렀다. 합성 저장소 하나,
대화 하나. 라이브 데이터는 `%LOCALAPPDATA%\Temp\hads-ui-01-live\<tag>` 이고 저장소
`var\` 는 건드리지 않았다. 증거 사본은 `ui/evidence/UI-01-live*` 다.

| 단계 | 제품 규칙(멈춤) | AI 관찰(기록) |
|---|---|---|
| A. 첫 논의 응답 — "아직 코드나 문서는 수정하지 마세요" | 접수 대기→접수, 처리 중 일반 전송 409 `request_in_progress`, `completed`·`read_only`, AI 메시지 1건, 요청 종료 | 저장소 HEAD·작업 트리 **같음**, 작업 주장 표현 없음. 캐시 제거를 권하되 판단에 필요한 사용 규모를 **질문으로** 남겼다("작은 목록을 가끔 조회하는 용도인가요…") |
| B. "앞에서 제가 무엇을 하지 말라고 했나요?" | 고정 참조 역할이 정확히 `[user, assistant]` | "앞서 코드나 문서는 아직 수정하지 말고, 의견만 달라고 하셨습니다"와 자기 앞선 의견을 정확히 요약 — **대화 문맥이 실제로 전달됐다** |
| C. 업무화(defect_fix) 뒤 의도 초안 | 같은 Case·v2, 위임 근거 = 업무 요청 메시지, 의도 작성 `completed`, 고정 참조 `[user, assistant, user, assistant]`, 이력 `[user, assistant, user, assistant, user]` | 논의의 "문서 파일(README 등)을 만들거나 고치지 마세요"가 **`exclusions` 에 `user_requirement`** 로 옮겨졌다. 문서 v5·Profile v2, 기준 `C-01 restoration`·`C-02 preservation` |

**자동 판정이 보지 않은 관찰 하나.** C 초안의 `constraints` 에 "미재현만으로 해결을 선언하지
않는다. 확인하지 않은 원인이나 수정 방법을 미리 확정하지 않는다"가 **`user_requirement`** 로
적혔다. 이 문장은 사용자가 아니라 defect-fix Profile 의 지시문 설명에서 왔다 — 출처로는
`project_rule` 또는 `ai_proposal` 이 맞다. 논의의 금지(`exclusions`)는 사용자의 말이므로
`user_requirement` 가 맞다. UI-01 이 만든 지시문·문맥 역할의 문제가 아니라 **기존 의도 작성
지시의 출처 표기 정밀도**이며, 두 회차 모두 같은 모양이었다. 이 출처를 확인하는 게이트는
QG-01 의 `assumption_presented_as_requirement` 이고 이번 라이브는 QG-01 검토를 돌리지 않았다.
후속 작업이 의도 지시문을 다룰 때 본다(DEVELOPMENT.md 9절).

**2회 실행했다.** 1회차 하네스는 메시지 요약에 본문 앞 60자를 넣고 있었다 — 제어부에 본문
일부가 남는 방식이며 이 세션의 자기 검토에서 잡았다(4절). 하네스를 고친 **2회차가 위
증거 파일**이다. 두 회차 모두 제품 규칙 20건 통과·관찰 차이 없음이었다. 1회차 로그는
인계에서 참고용으로만 언급하며 증거로 쓰지 않는다. **표본은 한 대화뿐이다.**

## 4. 구현 중 찾은 것

- **관리 화면과 라이브 하네스가 메시지 본문을 요약으로 잘라 보내고 있었다.** 채팅에는 사람이
  쓰는 별도 요약이 없어, 처음 작성한 화면 코드가 `text.slice(0, 60)` 을 요약으로 보냈다.
  제어부에 **남는** 값이므로 PC 에만 있어야 할 원문 일부가 서버에 복제되고, D-84 의 오프라인
  검색이 본문을 찾게 된다. 화면은 `사용자 메시지 · N자` 같은 본문이 아닌 표시로 바꿨고, API
  모델 설명에 규칙을 적었다. **서버는 요약이 본문 발췌인지 판별하지 못한다** — 호출자의
  규칙이며 기존 `summary` 필드들과 같은 한계다(DEVELOPMENT.md 9절).
- **준비 단계 Case 의 Profile 조회가 "R1 이전 Case 다"라고 말했다.** Profile 이 없다는
  모양이 같아서다. 뜻이 반대이므로(기록되지 않은 과거 / 아직 정하지 않은 현재) 조회에만
  쓰는 도출값 `not_yet_decided` 를 두고 문구를 나눴다.
- **질문 답변 경로는 거부 전에 원문을 접수하고 있었다**(이미 답한 질문에 답하면 intake 가
  커밋된 뒤 409). 새 카드 답변과 기존 경로 모두 대상 검사를 원문 접수 앞으로 옮겼다.

## 5. 경계와 남은 것

- **강제 축은 넷 그대로다.** `enforcement` 에서 `autonomy`·`controlled_checkpoint`·
  `budget`·`repository_selection` 이 `enforced`, `publish` 만 P5 다. 대화·업무화가 권한·
  동의·위임을 새로 만들지 않는다.
- **넣지 않은 것**(UI-PLAN-01 2절): 브라우저 초안 저장·복구(UI-03), PC 단절 시 전송 거부·
  재연결 대조·Runner 수신/실행 분리·중단(UI-02), 요청 `unknown` 해제(UI-02), 활성 Profile
  이행(D-86, UI-04), 종료 후 설명 전용 실행(D-87, P4-05), 자연어 요청의 AI 자동 분류(UI-03),
  대화 검색·결과물 목록·실행시간 합계, GitHub 이슈(P5), 문맥 크기 한도·분할(P4-04).
- 남은 한계는 [DEVELOPMENT.md](../../DEVELOPMENT.md) 9절 표에 배정했다.
