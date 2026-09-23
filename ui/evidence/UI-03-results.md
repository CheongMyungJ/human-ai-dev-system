# UI-03 실행 결과 — 기본 대화 화면

상태: **완료**  
기준: 설계 v0.8 2차 / D-01~90 / 2026-09-23  
계획: [UI-PLAN-03](../../plans/UI-PLAN-03.md)

## 1. 구현 결과

- **요청 처리기**(`controller/request_processor.py`). 일반·정정 메시지가 연 요청의 여는 원문이 PC 에
  **저장됐다는 보고**를 받으면, 제어부가 그 요청에 **읽기 전용 논의 응답 실행 하나**
  (`reply-{요청}`, 프로젝트 기본 도구 — 그 PC 가 코딩 CLI 로 확인한 경우만)를 만든다. 응답 결과가
  오면 (해석을 적용하고) 요청을 끝낸다 — 응답이 완료되고 대화에 붙었으면 `completed`, 아니면
  `failed`(`reply_not_completed`). 결과를 모르는 실행은 UI-02 판정 그대로 `unknown`·`interrupted` 다.
  응답 실행을 만들 수 없으면(도구 없음·진입 거부) 요청을 사유와 함께 `failed` 로 끝낸다 — 잠금이
  남지 않는다. 중단된 요청은 건드리지 않는다(UI-02 가 확인 뒤 끝낸다). 제어부 기동 때 빠진 단계를
  잇는다(응답 실행 없는 요청은 만들고, 실행이 끝난 요청은 끝낸다). **판정은 하지 않는다** — 진입
  검사·요청 종료·업무화 조건은 기존 경로가 하고 처리기는 순서만 정한다. 설정
  `HADS_AUTO_PROCESS_REQUESTS`(기본 `1`)로 끄면 UI-01 의 명시 계약 그대로다. 처리기의 실패는 Runner
  보고를 실패시키지 않고 로그(본문 없음)에 남는다.
- **AI 해석에 의한 최초 업무화**(D-69). 준비 단계 대화의 응답에만 배정 내용이 `conversation_stage =
  discussion` 을 싣고, Runner 가 논의 지시문에 **해석 규칙**을 붙인다: 답 끝에 기계용 블록
  ```` ```hads-interpretation ```` 하나 — `discussion` 또는 `work_request` + 여섯 Profile 중 하나.
  사용자의 마지막 메시지가 구체적인 작업을 **명시적으로** 요청할 때만 `work_request` 이고, 동의·생각
  나누기·질문·금지는 `discussion`, 모호하면 `discussion` 으로 두고 글로 묻는다. Runner 는 블록을 떼어
  **글만** 응답 원문으로 저장하고 해석을 결과에 싣는다(`reported`·`missing`·`invalid`). 제어부는 해석을
  결과와 같은 트랜잭션으로 `conversation_interpretation` 에 남기고(**본문·요약 없음**) 다시 검사한다.
  처리기는 요청을 끝내기 전에 `work_request` + 유효 Profile + 응답 완료이면 `start_work(decided_by =
  ai_interpretation, interpretation_run_id = 응답 실행)` 을 부른다. **위임 근거는 사용자 메시지
  원문**이다(UI-01 그대로). 업무화 요약은 본문이 아닌 표시(`AI 해석 · research 업무 요청 · 메시지 #n`)
  다. 업무화는 실행을 시작하지 않는다. 적용이 거부되면(이미 업무 단계 등) 사유를 해석 행에 남긴다.
  업무 단계 응답은 해석하지 않는다(D-86 은 UI-04).
- **기본 대화 화면**(`web/src/shell`, `/`). 왼쪽 목록(프로젝트 선택 — 다른 프로젝트의 답변 필요·확인
  필요 수, 새 대화, 답변이 필요한 대화, 최근 대화, 보관된 대화, PC 연결, 테마, 관리 화면), 가운데 대화
  (단계·Profile, 메시지 본문, 업무화 카드, AI 해석 줄, 요청 진행과 중단·상태 다시 확인, 질문 카드,
  입력창), 누를 때만 여는 오른쪽 검토 패널(결과물·결정 사항). **라이트 기본**, 다크·시스템 선택,
  패널 접기·끌어서 폭 조절, 테마·폭·마지막 대화·읽던 위치를 이 브라우저에 기억한다. 관리 화면은
  `?view=admin` 으로 그대로다(스타일을 따로 불러 섞이지 않는다).
- **서버 판정 그대로.** 전송 가능·사유(`send.general`·`card_answer`), 요청 상태, 실행별 실제 상태
  (`execution_state`), PC 연결(목록 조회에도 서버 도출 `connection` 을 더했다), 원문 가용성을 그대로
  보인다. 진행률·예상 시간을 지어내지 않는다.
- **대화 본문.** 메시지 본문을 원문 열람 중계로 불러와 **탭 메모리에만** 둔다(브라우저 저장소에
  쓰지 않는다). 소유 PC 가 미연결이면 새 열람 요청을 만들지 않고 "연결 필요"를 보이며, 연결되면
  불러온다. 한 번 불러온 본문은 단절 뒤에도 보인다. AI 응답은 실행 정보 머리와 최종 메시지를 나눠
  보인다. **의도 원문은 사람이 결과물 패널에서 열 때만** 불러온다(그 전달이 열람 기록을 남긴다).
- **초안 복구**(D-83, `web/src/lib/drafts.ts`). 대화별 텍스트·참조·정정 대상과 질문별 카드 답변을 이
  브라우저에 자동 저장한다. 보낼 때 스냅샷과 전송 식별자를 **보냄 기록**으로 함께 저장하고, `stored`
  가 확인되면 **지금 초안이 그 스냅샷과 같을 때만** 비운다(보낸 뒤 고친 내용은 남는다). 거부·유실·
  받지 않음에는 초안이 남는다. 새로 고침·대화 전환 뒤 보냄 기록은 `by-client-id` 로 **대조만** 한다 —
  자동 전송이 없다. "초안 저장됨"과 "메시지 접수됨"을 따로 보이고, 저장소가 없거나 쓰기가 실패하면
  저장됨으로 보이지 않는다.
- **결과물·결정 사항**(D-85·D-71·D-89). 있는 것만 나열한다(의도 버전, 설계·계획 개정, 논의 응답을
  뺀 실행 출력, 코드 변경 요약, 검증 실행·기준 판정). 목록에서 열면 최신, 과거 메시지 참조로 열면 **그
  버전**이다. 열람 버전은 고정되고 새 버전이 생기면 "새 버전 vN · 변경 내용 보기(줄 비교) · 최신으로
  전환"을 안내한다. `대화에 참조`가 열람 중인 버전을 입력창 초안에 붙인다. 메시지의 참조는 최신이
  아니면 "최신 아님"을 보인다. 코드 diff 본문은 작업 PC 에 있으므로 작업 PC·경로·경로 복사만 보이고
  diff 열람·폴더 열기는 지원하지 않는다고 말한다. 결정 사항은 업무화·기록된 결정·답한 질문·AI 해석
  기록이다.
- **기본값 요약**(D-72). 입력창 위 한 줄: 응답 도구(프로젝트 기본 도구와 PC 확인 여부), 처리기
  켜짐, 적용 Autonomy·출처, 작업 깊이, 예산, 대상 저장소 수. 펼치면 출처. 변경은 관리 화면(상세 설정은
  UI-04).
- **업무 단계 안내.** 업무 단계 대화는 서버 상태(의도 동의·QG-01·Case 상태)와 함께 "업무 단계의 다음
  작업을 **아직 자동으로 진행하지 않는다** — 관리 화면에서 진행"을 보인다(UI-PLAN-03 3.11).
- **기존 접수 네 경로의 중계 순서.** `/artifacts`·`/intent-drafts`·`/feedback`·`/questions/{id}/answer`
  가 접수 식별자를 먼저 정해 본문을 **기록 전에** 중계하고, 기록되지 않으면 뺀다(`open_intake` 가
  식별자를 받는다). 멱등 키는 더하지 않았다.
- **조회 보강.** 목록 행의 `last_activity_at`·`current_request_stopping`, `GET /api/projects` 의
  `attention`, `GET /api/runners` 의 `connection`, 대화 조회의 `processing`·`interpretations`.
- **제어부 공유 연결의 문장 단위 직렬화**(범위 밖이던 결함 수정, 4절). 앱의 연결을
  `SerializedConnection` 으로 감싸 문장 하나(실행과 결과 읽기)를 쓰기 트랜잭션과 같은 잠금 안에서
  끝낸다(`controller/db.py`).
- 스키마 **v19**: 새 표 `conversation_interpretation` 하나(실행·Case·요청·여는 메시지·보고 상태·
  종류·Profile·적용 여부·거부 코드·시각, 적용은 보고된 업무 요청만 CHECK). 기존 표는 바꾸지 않는다.

## 2. 성공 기준 근거

시험은 `tests/test_request_processor.py`(26)·`tests/test_intake_order.py`(5)·
`tests/test_web_shell.py`(5, 실제 브라우저)·`tests/test_shared_connection.py`(2)·
`web/src/lib/*.test.ts`(18, Node)와 표시한 기존 파일이다.

| 기준 | 근거 |
|---|---|
| AC-1 시작 | `test_a_stored_request_gets_exactly_one_read_only_reply_run`(저장 전 없음·재보고 중복 없음), `test_a_card_answer_opens_no_request_and_starts_nothing` |
| AC-2 끝 | `test_the_reply_is_attached_and_the_request_completes`, `test_a_failed_reply_fails_the_request_and_unlocks`, `test_an_unknown_reply_keeps_the_lock_as_before`, `test_another_unfinished_run_defers_the_settlement`, 순수 규칙 `test_the_processor_asks_completed_only_for_an_answer_the_person_can_see` |
| AC-3 만들 수 없음 | `test_no_reply_tool_closes_the_request_with_a_reason`, `test_an_admission_refusal_closes_the_request_and_is_recorded`(예산 hard) |
| AC-4 중단·복구·끄기 | `test_a_stopped_request_is_left_to_the_controller`, `test_startup_recovery_creates_missing_replies_and_settles_finished_requests`(실제 앱 재기동), `test_turning_the_processor_off_keeps_the_manual_contract`, `test_the_processor_can_be_driven_directly_on_a_repository` |
| AC-5 해석 보고 | `test_the_interpretation_block_is_split_from_the_reply`, `test_a_reported_interpretation_is_rechecked_on_the_controller`, `test_the_rule_is_added_only_to_discussion_stage_replies`, `test_a_broken_block_starts_nothing_but_keeps_the_reply`, `test_a_reply_that_is_only_a_block_fails`, `test_an_interpretation_cannot_ride_on_another_run` |
| AC-6 업무화 | `test_a_clear_work_request_starts_work_in_the_same_case`(위임 근거 = 여는 메시지, 실행 추가 없음, 글에 블록 없음), `test_a_discussion_keeps_the_discussion_stage`, `test_work_stage_replies_get_no_rule_and_no_interpretation`, `test_a_case_that_already_started_work_refuses_the_ai_start`, 순수 규칙 `test_only_a_completed_reported_work_request_is_applied` |
| AC-7 해석 기록 | `test_the_interpretation_record_keeps_no_body`(컬럼 목록·제어부 데이터 전체에 본문 표지 없음) |
| AC-8 네 경로 | `test_the_body_is_relayed_before_the_intake_is_committed[artifacts·intent-drafts·feedback·answer]`, `test_a_refused_intake_leaves_nothing_in_the_relay` |
| AC-9 조회 | `test_lists_carry_activity_attention_and_derived_connection`, 위 시험들의 `processing`·`interpretations` |
| AC-10 이행 | `test_migration.py::test_a_v18_database_gets_no_interpretation_it_never_had`(새 표만·옛 요청 처리 안 함·CHECK·멱등) |
| AC-11 화면 구성 | `test_the_conversation_shell_is_the_default_screen`(라이트 기본·다크 기억·목록 접기 기억·패널은 누를 때만·프로젝트 전환 시 마지막 대화·관리 화면 유지), `prefs` 단위 시험 |
| AC-12 서버 판정 | `test_a_conversation_gets_answered_locks_while_processing_and_starts_work`(처리 중 사유·비활성·편집 가능·직접 API 409 같은 사유), `test_a_disconnected_pc_keeps_what_was_loaded_and_sends_nothing`(미연결 사유·비활성) |
| AC-13 본문 | `test_a_disconnected_pc_keeps_what_was_loaded_and_sends_nothing`(단절 뒤 본문 유지·"연결 필요"·새 열람 요청 0·재연결 뒤 불러옴), `test_drafts_live_in_this_browser_and_only_stored_sends_are_cleared`(저장소에 본문 없음), `test_question_cards_and_results_keep_the_version_being_read`(의도 열람 기록은 사람이 연 뒤에만 1) |
| AC-14 초안 | `drafts.test.ts` 9건(스냅샷만 비움·뒤 편집 보존·거부/유실/받지 않음 유지·같은 내용 같은 식별자·늦은 결말·저장 실패), 브라우저 `test_drafts_live_in_this_browser_and_only_stored_sends_are_cleared`(새로 고침·대화 전환 복구, 접수된 것만 비움, 받지 않은 보냄 기록은 대조만·자동 전송 없음, 다른 브라우저에는 없음) |
| AC-15 진행·중단 | `test_a_conversation_gets_answered_locks_while_processing_and_starts_work`(실행 중 문장·화면 중단 → 중단됨 → 전송 열림) |
| AC-16 질문 카드 | `test_question_cards_and_results_keep_the_version_being_read`(카드 → 답변 → 카드 사라짐, 동의 아님) |
| AC-17 결과물 | 같은 시험(v1 고정 중 v2 → 안내·줄 비교·전환, `대화에 참조` → 메시지 참조 v1·"최신 아님", 과거 참조가 v1 을 엶), `versions.test.ts`·`textDiff.test.ts` |
| AC-18 안내·요약 | 브라우저 시험의 업무 단계 배너(관리 화면 링크), 설정 요약 줄 |
| AC-19 실제 사용 | 3절 — 실제 Edge·실제 codex |
| AC-20 경계 | `test_the_interpretation_record_keeps_no_body`, 기존 데이터 경계 시험 통과, 강제 축 넷 그대로(아래 5절) |
| (범위 밖 결함) 공유 연결 | `test_what_was_just_created_is_always_there_under_concurrent_requests`(실제 uvicorn 에 6초 부하 — 고치기 전 코드에서 실패, 고친 뒤 0건·0 오류), `test_rows_are_read_inside_the_lock_and_behave_like_a_cursor` |

## 3. 검증

### 자동 시험

- 기준선(이 세션 시작, 변경 전): `scripts\run-tests.ps1` → pytest **575**, P1 계약 unittest **18**
  통과(5분 20초 — 이전부터 흔들리던 P4-02 시험도 이번에는 통과).
- 최종: `scripts\run-tests.ps1` → 웹 빌드 성공, 웹 단위 **18** 통과, pytest **614** 통과, P1 계약
  unittest **18** 통과(6분 30초). 새 pytest 39건(`test_request_processor` 26, `test_intake_order` 5,
  `test_web_shell` 5, `test_shared_connection` 2, v18→v19 이행 1). 알려진 deprecation warning 2건 외
  실패 없음. 그 뒤 화면의 사소한 두 곳(질문 카드 전송 식별자의 대체 경로, 주석)을 고쳐 웹 빌드·웹 단위
  18·브라우저 5·연결 2 를 다시 돌려 통과했다.
- **기존 시험 둘을 고쳤다. 검사를 지우지 않았다.**
  - `test_migration.py::test_a_v17_database_is_rebuilt_without_losing_rows_or_inventing_stops` 가
    `SCHEMA_VERSION == 18` 을 고정했다 → `>= 18`(뜻은 "현재 판으로 이행", v19 고정은 새 시험).
  - 공통 하네스(`tests/conftest.py`)는 **처리기를 끈다** — 기존 시험은 사람·하네스가 요청을 처리하는
    UI-01 명시 계약을 본다. 켜면 같은 요청에 응답이 둘 생긴다. 처리기 시험은 `processing_harness` 를
    쓴다. 실제 제어부를 띄우는 `tests/test_restart_recovery.py` 의 `ControllerProcess` 와 옛 라이브
    하네스(`p3/live/driver.py`·`ui/live/ui02_control.py`)도 같은 이유로 끈다.
- 브라우저 시험은 실제 uvicorn(빌드된 `web/dist` 서빙)·실제 Runner 프로세스·PATH 앞 가짜 `codex`·
  설치된 Edge(Playwright `msedge`, 내려받지 않음)다. 가짜 `codex` 에 해석 블록 표지
  (`HADS_FAKE_WORK=<Profile>`)와 UTF-8 출력을 더했다. `scripts\run-tests.ps1` 은 웹 빌드·웹 단위 시험을
  먼저 돌린다(`-SkipWeb`).

### 실제 CLI·실제 브라우저 (AC-19)

`ui/live/ui03_shell.py` 로 실제 `codex-cli 0.156.1`(UI-02 때의 0.154.0 에서 바뀜)과 설치된 Edge 를 썼다.
작은 저장소(README·`app.py`) 하나, 새 대화 하나. **제품 코드를 import 하지 않고** HTTP·브라우저·OS 로만
본다. 라이브 데이터는 `%LOCALAPPDATA%\Temp\hads-ui-03-live\{213304202,215304164}`, 저장소 `var\` 는
건드리지 않았다. 증거 사본(`ui/evidence/UI-03-live*`: 로그·결과 JSON·화면 8장)은 **최종 코드로 돈
2회차(215304164)** 다.

| 단계 | 제품 규칙(멈춤) | 관찰 |
|---|---|---|
| A 논의 | 라이트 기본, 처리 중 전송이 서버 사유로 막힘·초안 편집 가능, 요청 처리기가 읽기 전용 응답 하나로 처리·`request-processor` 종료, 응답 본문이 보이고 해석 블록은 없음, 해석과 단계 일치, 막혀 있던 동안의 초안이 자동 전송되지 않음 | 첫 응답 50.1초(1회차 52.1초). codex 는 논의 메시지를 `discussion` 으로 보고했다 |
| B 초안 | 새로 고침 뒤 초안 복구, 복구가 전송을 만들지 않음, 브라우저 저장소에 대화 본문 없음 | — |
| C 업무화 | AI 해석 업무화(같은 Case·`ai_interpretation`·근거 실행), 위임 근거 = 사용자 메시지 원문, 업무화가 실행을 시작하지 않음, 화면이 업무 단계와 미지원 자동 진행을 보임 | codex 는 분석 요청을 `work_request`/`research` 로 보고했고 글에 현재 형식의 문제와 개선안(표)을 정리했다 |
| D 중단 | 화면의 중단 버튼 → `interrupted(stopped_by_request)`, **OS 목록에 그 셸 대기(`Start-Sleep -Seconds 93`)가 없음** | — |
| E 결과물 | 질문 카드 답변이 그 질문만 닫고 동의가 되지 않음(`never_agreed`), 읽는 동안 v2 가 생겨도 본문은 v1, 전환은 사람이 고른 뒤 | 사람이 쓴 의도 초안(API)으로 v1·v2 를 만들었다 — AI 가 쓴 초안이 아니다 |
| F PC 단절 | Runner 프로세스만 내림 → 불러온 본문 유지, 전송 비활성·사유, **새 열람 요청 0**(10→10), 재기동 뒤 본문을 불러오고 초안 유지·자동 전송 없음 | 종료 뒤 이 라이브의 남은 프로세스 0 |

**두 회차 모두 제품 규칙 24/24 통과**, AI 판단(논의 → 논의, 분석 요청 → `research`)도 같았다. 1회차는
공유 연결 수정·화면의 작은 수정 전 코드였고 결과는 같다(1회차 증거 파일은 2회차가 덮어써 저장소에 없고,
데이터 폴더는 남아 있다). **표본은 회차마다 대화 하나·해석 둘·중단 하나·단절 하나다.** codex 의 답은 Markdown(표·굵게·
작업공간 절대 경로의 링크)이며 화면은 글 그대로 보인다(DEVELOPMENT.md 9절). claude 로는 돌리지 않았다.

## 4. 구현 중 찾은 것

- **제어부 공유 연결의 동시 사용 결함(P2 부터 있던 것).** 브라우저 시험이 가끔 "AI 응답을 불러오지
  못했다 — 404 read request not found" 로 실패했다. 제어부는 요청 스레드들과 sqlite 연결 하나를
  공유하면서 **쓰기 트랜잭션만** 잠갔다. 같은 SQL 을 두 스레드가 동시에 실행하면 파이썬 sqlite3 의
  준비된 문장 캐시를 함께 써서 한쪽의 매개변수가 다른 쪽 실행을 덮는다 — 방금 커밋한 열람 요청이
  "없다"로 읽혔다. 실제 uvicorn 에 부하를 걸어 재현했다: 25초에 만든 것 8,423건 중 367건이 없다고
  나오고 1,663건이 오류(`sqlite3.InterfaceError: bad parameter or other API misuse`)였으며 조회 반복은
  2바퀴밖에 돌지 못했다. 관리 화면은 조회를 거의 겹쳐 보내지 않아 드러나지 않았다.
  `SerializedConnection` 으로 **문장 하나(실행·결과 읽기)를 쓰기 트랜잭션과 같은 잠금 안에서** 끝내게
  하자 같은 부하에서 9,088건·0건·0 오류, 조회 192바퀴였다. 회귀 시험은 고치기 전 코드에서 실패했다.
- **초안 표시가 앞선 저장을 보였다.** 저장 뒤 새로 편집하면 300ms 저장 지연 동안에도 "초안 저장됨"이
  남아 있었다(브라우저 시험이 그 표시를 믿고 다른 탭을 열었다가 초안을 못 봤다). 지금 초안을 **마지막으로
  실제 저장한 초안**과 렌더 때 비교해 다르면 "초안 저장 중…"을 보인다.
- **목록 상태가 최대 5초 늦었다**(라이브 화면에서 봄). 대화는 "처리 끝"인데 목록 행은 "처리 중"이었다.
  열린 대화의 요청 상태·단계가 바뀌면 목록을 바로 다시 묻는다.
- **거부 문구가 겹쳤다.** 서버 사유 문구("초안은 편집할 수 있고 …")에 화면이 같은 말을 덧붙였다.
- **가짜 codex 의 한글이 깨졌다.** 파이프에 쓰는 파이썬이 콘솔 코드 페이지로 냈다 — 실제 codex 는
  UTF-8 이다. 가짜가 UTF-8 로 내게 했다(시험 도구).
- **Playwright 동기 API 의 `page.url` 은 이벤트를 처리할 때만 갱신된다.** 주소가 바뀌기를 기다리는
  시험 도우미가 옛 주소를 봤다. 페이지에 `location.href` 를 묻는다.
- **해석 규칙은 좁게 두었다.** 논의를 업무로 잘못 읽으면 되돌릴 경로가 없어서(D-86 은 UI-04) 명시적
  작업 요청만 `work_request` 이고 모호하면 논의로 두고 글로 묻게 했다. 라이브의 두 판단은 기대대로였다.

## 5. 경계와 남은 것

- **강제 축은 넷 그대로다.** 처리기·해석·업무화가 권한·동의·위임을 만들지 않는다 — 위임 근거는
  사용자 메시지 원문이고, 해석은 "누가 Profile 을 정했는가"의 근거일 뿐이다. 조사 Profile 의 제품
  쓰기 차단(D-66)은 그대로다.
- **넣지 않은 것**(UI-PLAN-03 2절·3.11절): **업무 단계 자동 진행**(업무화 뒤 의도 초안~완료를 제품이
  잇는 흐름 — 미지원 표시·관리 화면), 확인 카드(의도 동의·controlled·권한 확대·예외·단계 검토·material
  delta), 대화 검색·알림·상세 설정·프로젝트 규칙·작업 PC 열기·미커밋 포함 시작·활성 Case 목적 변경
  (UI-04), 종료 후 설명 전용 진입(P4-05), 코드 diff 본문 열람, 이미지 첨부, 네 접수 경로의 멱등 키.
- **업무 단계 자동 진행의 자리:** 사용자 결정(2026-09-23)으로 **P4-05 에 포함**한다([DEVELOPMENT.md](../../DEVELOPMENT.md) 1.6절).
- 남은 한계는 [DEVELOPMENT.md](../../DEVELOPMENT.md) 9절 표에 배정했다.
