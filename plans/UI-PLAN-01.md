# UI-PLAN-01

대화·요청 기반. 기준: 설계 v0.8 2차 / D-01~90 / 2026-09-23.
선행: P4-03 완료(스키마 v15, Profile 정의 v2). 이 세션에서 `scripts\run-tests.ps1` 로
pytest **481**, P1 계약 unittest **18** 통과를 다시 확인했다.
범위는 **UI-01 하나**다. P4-04 문맥·재개, UI-02 입력·실행 제어, UI-03 기본 화면,
활성 Profile 이행(D-86), 종료 후 설명(D-87)은 포함하지 않는다.

## 1. 현재 구현과 이 작업이 메울 차이

코드를 대조해 확인한 사실이다([DEVELOPMENT.md](../DEVELOPMENT.md) 1.2절의 시작점).

1. **목표·Profile 없이 Case 를 만들 수 없다.** `"case".kind` 가 `NOT NULL` 이고 API 는
   둘 다 없으면 `feature` 를 기본으로 넣는다(`api.py create_case`). 준비 단계가 없다.
2. **대화가 없다.** 원문 접수(`intake`)는 있으나 메시지 단위·순서·정정 관계가 없다.
   접수 경로 넷(`/artifacts`·`/intent-drafts`·`/feedback`·`/questions/{id}/answer`)
   모두 멱등 키가 없어 재전송마다 새 intake·새 artifact 가 생긴다.
3. **"현재 요청"이 없다.** Case 상태는 `received`→`waiting_final_acceptance`→`closed`
   셋만 실제로 쓰이고 Run 은 각자 끝난다. 한 요청이 여러 Run 을 포함하는 동안의 처리
   중을 표현할 수 없고, 서버가 동시·중복 일반 전송을 막을 근거가 없다.
4. **질문 답변의 대상이 느슨하다.** `answer_question` 은 대체된 의도 버전의 질문에도
   답을 기록한다. 이미 답한 질문에 답하면 intake 가 먼저 커밋돼 고아 원문이 남는다.
5. **접수 경합.** `open_intake` 커밋 뒤 `relay.put` 전에 Runner 폴링이 끼면 본문이 없는
   접수가 `lost_before_persist` 로 표시된다(`api.py runner_intakes`).
6. **보관이 없다.** 목록 가시성과 종료 상태를 구분할 자리가 없다.
7. **논의 실행 목적이 없다.** 기존 목적은 전부 의도 초안·동의·준비 흐름에 묶여 있다.

## 2. 범위

| 넣는 것 | 넣지 않는 것 (담당) |
|---|---|
| 준비 단계 Case 생성. 단계·보관을 Case 종료 상태와 분리 | 브라우저 초안 저장·복구(D-83) — UI-03 |
| 대화 메시지(사용자 일반·정정·카드 답변, AI 논의 응답)·순서·원문 참조·자료 참조 | PC 단절 시 전송 거부·재연결 대조, Runner 수신/실행 분리, 중단 — UI-02 |
| 현재 요청(처리 중/완료/실패/불명), Run 연결, 서버 잠금 | 요청 `unknown` 의 해제(실제 종료·잔류 확인) — UI-02 |
| 멱등 접수(`client_message_id`), 접수 불명 대조 조회, 새 경로의 접수 경합 제거 | 활성 Case 의 Profile 이행(D-86) — UI-04 |
| 카드 답변의 대상 질문·버전 한정, 유실된 답변의 질문 재개 | 종료 후 설명 전용 실행(D-87) — P4-05 |
| 논의 응답 실행 목적 `discussion_reply` 의 진입·권한·사용량 | 자연어 요청을 AI 가 스스로 분류해 업무화하는 흐름 — UI-03 (UI-01 은 기록 계약) |
| 최초 업무화: 최초 Profile(v2) 배정, 위임 근거, 기존 정책·소비 계승 | 대화 검색·결과물 목록·실행시간 합계 — UI-04 이후 |
| 대화의 고정 컨텍스트(논의 응답·의도 작성·QG-01 검토) | 문맥 크기 한도·분할·새 세션 복원 — P4-04 |
| 기존 사용자 입력 경로(피드백·사람 의도 초안)의 요청 잠금 | GitHub 기록 이슈 — P5 |
| API·최소 관리 화면, 스키마 v16·이행, 자동 시험·실제 CLI 확인 | 새 기본 대화 화면·알림·테마 — UI-03 |

## 3. 설계

### 3.1 Case 의 세 축 — 종료·단계·보관

- **종료 상태**(`case.status`)는 그대로다. 준비 Case 도 `received` 로 시작한다.
- **단계**(`case.stage`, 새 컬럼): `discussion` | `work`. **NULL 은 UI-01 이전에 만든
  Case** 이며 업무 단계로 도출한다(출처 `created_before_stage`). 그 시절에는 kind 없이
  Case 를 만들 경로가 없었으므로 업무 단계 외의 다른 해석이 없다. 값을 채워 넣지 않고
  도출하는 이유는 이행이 데이터를 쓰지 않게 하기 위해서다. 기존 생성 API 로 만든 새
  Case 는 `work`(출처 `created_as_work`), 대화 생성은 `discussion`
  (`created_as_discussion`), 업무화된 Case 는 `work`(`work_started`).
- **보관**은 `case_visibility_event`(보관/복원 이력)의 최신 행에서 도출한다. 종료·요청·
  실행을 바꾸지 않는다. 목록은 `archived = include | exclude | only` 로 거른다.
- **준비 Case 의 `kind` 는 `undecided`** 다(`CaseKind.UNDECIDED`). `kind` 가 `NOT NULL`
  이라 NULL 을 넣을 수 없고, 표를 재구성하면 40여 표가 참조하는 중심 표를 다시 만들게
  된다. `feature` 로 채우지 않는다 — 가짜 분류가 곧 기능 개발 조건표를 고른다
  (`choose_profile`). `profile`·`profile_version`·`profile_source` 는 NULL 이다.
  기존 생성 API 에 `undecided` 를 주면 거부한다.
- **"답변 필요"는 열린 질문에서만 도출한다.** 질문 없는 휴식을 답변 필요로 표시하지 않는다.

### 3.2 대화 메시지

`conversation_message` 표. 본문 컬럼은 없다.

| 필드 | 뜻 |
|---|---|
| `seq` | Case 안의 연속 순번. `UNIQUE(case_id, seq)` |
| `author` | `user` \| `assistant` |
| `message_kind` | `general` \| `correction` \| `card_answer` \| `assistant_reply` |
| `client_message_id` | 사용자 메시지의 전송 식별자. `UNIQUE(case_id, client_message_id)` |
| `artifact_id`·`artifact_rev`·`content_hash`·`intake_id` | 원문 참조. 본문은 Runner |
| `request_id` | 일반·정정: 연 요청. 카드 답변: 그때 처리 중이던 요청(없으면 NULL). AI: 실행의 요청 |
| `corrects_message_id` | 정정 대상 |
| `question_id`·`question_intent_version_id` | 카드 답변의 대상 질문과 카드가 보인 의도 버전 |
| `run_id` | AI 응답을 만든 실행. 부분 유일 색인으로 실행당 하나 |
| `summary` | ≤200자 목록용 요약 |

**접수 상태**(`receipt`)는 저장하지 않고 intake 에서 도출한다 — `pending`(중계됨·PC 저장
전), `stored`(**접수됨**), `lost_before_persist`. AI 응답은 Runner 가 이미 저장한 실행
출력이므로 `stored` 다. 해시 불일치는 Runner 가 저장하지 않으므로 `pending` 에 머문다 —
저장되지 않은 원문을 접수로 표시하지 않는다.

**자료 참조**(`conversation_message_ref`): 산출물(`artifact_id`·`revision`·그 시점 해시·
위치) 또는 프로젝트 파일(`repository_id`·경로·위치·관측 해시). 산출물은 이 Case 에
있어야 하고 파일의 저장소는 이 Project 에 등록돼 있어야 한다. 경로·위치는 식별 정보이며
파일 본문이 아니다. 이미지·외부 파일 업로드는 받지 않는다(D-81).

### 3.3 현재 요청과 서버 잠금

`conversation_request` 표와 `run.request_id` 컬럼.

| 전이 | 조건 |
|---|---|
| 열림 → `processing` | 일반·정정 메시지 접수와 **같은 트랜잭션** |
| `processing` → `completed` | 명시 종료. 여는 메시지가 `stored`, 연결 Run 전부 종료, 불명 Run 없음 |
| `processing` → `failed` | 명시 종료. 연결 Run 전부 종료. 불명 Run 이 있으면 대신 `unknown` |
| `processing` → `unknown` | 종료 시 연결 Run 중 `outcome = unknown` 이 있음 |
| `processing` → `failed`(시스템) | 여는 메시지가 `lost_before_persist` 이고 연결 Run 이 없음 (`original_lost_before_persist`) |
| `unknown` → | **UI-01 에는 없다.** 실제 종료·잔류 활동 확인은 UI-02 |

- **잠금은 `processing` 과 `unknown`** 이다. 이 동안 같은 Case 의 일반·정정 메시지,
  피드백(`/feedback`), 사람 의도 초안(`/intent-drafts`)은 409 다(`request_in_progress`,
  `request_state_unknown`). 대기열을 만들지 않는다. 다른 Case 는 영향이 없다.
- **Run 이 끝나도 요청은 끝나지 않는다.** 종료는 명시 기록이고 미종료 Run 이 있으면
  거부한다(`request_runs_unfinished`). 그래서 내부 Run 사이에 잠금이 풀리지 않고,
  종료 뒤에는 Case 가 닫히지 않았어도 전송이 열린다.
- **DB 가 마지막 방어선이다.** 활성 요청(`processing`·`unknown`)에 Case 당 하나만 허용하는
  부분 유일 색인을 둔다. 접수·요청 생성은 `BEGIN IMMEDIATE` 한 트랜잭션이다.
- 시스템 입력 경로(`/api/runner/*`, 지시 원문을 올리는 `/artifacts`)는 잠그지 않는다 —
  사용자의 일반 전송이 아니라 요청을 처리하는 쪽의 경로다.
- Run 을 요청에 연결하면(`RunIn.request_id`) 그 요청이 이 Case 의 `processing` 이어야
  하고 여는 메시지가 `stored` 여야 한다. **Run 생성 트랜잭션 안에서 다시 확인한다** —
  종료 기록과 경합해도 종료된 요청에 Run 이 붙지 않는다.

### 3.4 접수·멱등·대조

- 전송은 **검사를 먼저 끝내고** 원문을 연다(닫힘·단계·잠금·정정 대상·질문 대상·참조).
  그래서 거부된 전송은 intake 를 남기지 않는다.
- **새 경로는 중계 본문을 먼저 넣는다.** intake id 를 먼저 만들어 버퍼에 넣은 뒤 한
  트랜잭션으로 참조·intake·메시지·요청을 기록하고, 실패하면 버퍼에서 뺀다 — 커밋과
  중계 사이의 Runner 폴링이 접수를 유실시키지 않는다(1절 5).
- 같은 `client_message_id` 재전송: 같은 해시면 새 intake·메시지·요청 없이 기존 것을
  **200**(`created: false`)으로 돌려준다. 잠금 검사보다 **먼저** 본다 — 이미 요청을 연
  메시지의 재전송이 자기 요청 때문에 409 가 되지 않는다. 다른 해시면 409
  (`client_message_id_conflict`).
- 접수 불명 대조: `GET /api/cases/{id}/messages/by-client-id/{client_message_id}` 가
  메시지와 접수 상태를 주고, 받은 적 없으면 404 다. 유실(`lost_before_persist`)된 전송은
  새 `client_message_id` 로 다시 보낸다.
- 전송 응답은 202(접수 대기)다. **`stored` 만 접수 완료**다(D-83 의 초안 비우기 기준).

### 3.5 카드 답변

- 새 경로의 `card_answer` 는 `question_id` 와 카드가 보인 `intent_version_id` 를 받는다.
  질문이 그 버전에 속하고 그 버전이 최신이어야 한다(`question_target_stale`). 이미 답한
  질문·열려 있지 않은 질문은 거부한다(`question_already_answered`·`question_not_open`).
- 요청 처리 중에도 받는다. **요청을 열지도 닫지도 않고**, 동의·결정·위임 근거를 만들지
  않는다. 질문 하나의 답은 그 질문의 답일 뿐이다.
- 기존 `/questions/{id}/answer` 도 같은 대상 검사(대체된 버전 거부)를 **원문 접수 전에**
  한다 — 고아 intake 를 남기지 않는다. 즉시 `answered` 로 기록하는 기존 의미는 유지한다.
- **답변 원문이 유실되면 질문을 다시 연다.** 답했다고 기록된 질문의 원문이 PC 에 닿지
  않았다면 그 답을 입력으로 쓸 수 없고 질문이 해결된 것이 아니다. 누가 언제 답했는지는
  대화 메시지에 남는다.

### 3.6 정정

- 대상은 같은 Case 의 사용자 일반·정정 메시지뿐이다(`correction_target_invalid`).
- 원본·원본이 연 요청·그 Run·효과는 그대로다. 정정은 새 메시지이고 **새 요청을 열며**
  잠금 규칙을 따른다. 조회는 `corrected_by` 로 관계를 보인다.
- 종료된 Case 는 기존 guard 로 거부된다(실제 수정은 연결된 새 Case, D-33).

### 3.7 논의 응답 실행 `discussion_reply`

| 항목 | 규칙 |
|---|---|
| 역할·권한 | author, `read_only` 만 |
| 도구 | 코딩 CLI 필요(골격 실행기는 응답을 쓰지 않으면서 정상 종료한다) |
| 단계 | 준비·업무 단계 모두(종료 Case 는 기존대로 거부). 의도·Profile 불필요 |
| 요청 | 연결 필수(`request_required`), `processing`, 여는 메시지 `stored` |
| 지시 | **그 요청의 여는 메시지 원문**이어야 한다(`request_instruction_mismatch`) |
| controlled | 읽기 전용이라 시작 확인 대상이 아니다(`NEEDS_CONTROLLED_START` 밖) |
| 예산 | 기존 예약·정산을 그대로 지난다. 소비는 같은 Case 에 누적되고 hard 한도에 막힌다 |
| 결과 | `completed` + 출력이면 AI 메시지(`assistant_reply`)로 대화에 붙는다. 실행당 하나 |

**준비 단계에서는 이 목적만 열린다.** 의도 작성·검토·준비·구현·검증·실험은
`case_in_discussion_stage` 로 거부되고, 의도 버전 생성도 거부된다 — Profile 없는 의도
문서를 만들지 않는다. Runner 지시문: 읽기 전용, 대화 문맥을 읽고 마지막 사용자 메시지에
답한다, 요청받지 않은 작업을 시작했거나 끝냈다고 말하지 않는다, 결정이 필요하면 묻는다.
출력은 글이며 JSON 계약이 없다.

### 3.8 최초 업무화 `work-start`

입력: `profile`, 근거 메시지(`request_message_id`), 누가 정했는가(`decided_by`:
`person` \| `ai_interpretation`), AI 해석이면 그 실행(`interpretation_run_id`, 같은 요청의
실행), 행위자, 요약.

- **준비 단계 Case 만.** 업무 단계(기존·업무화된 Case)는 `case_not_in_discussion_stage`
  — 활성 Profile 이행(D-86)과 섞지 않는다.
- 근거 메시지는 이 Case 의 사용자 일반·정정 메시지이고 `stored` 이며, 그 메시지가 연
  요청이 지금 `processing` 이어야 한다 — 업무화는 그 요청을 처리하는 동작이다.
- 한 트랜잭션: `stage = work`, `kind = KIND_FOR_PROFILE[profile]`, `profile`,
  `profile_version = CURRENT_PROFILE_VERSION`("2"), `profile_source = work_start`,
  `case_work_start` 행, **위임 근거 `original_request` = 그 메시지 원문**.
- **앞선 논의·동의 메시지는 위임 근거가 아니다**(D-60·D-69). 문맥으로만 쓰인다.
  사용자 결정(`user_decision`)을 만들지 않으므로 조사 Profile 의 제품 수정 차단(D-66)이
  업무화로 풀리지 않는다.
- **바뀌지 않는 것:** 메시지·요청·Run·예산 예약/정산·예산 한도·Autonomy 정책·저장소
  선택·확인 지점. 같은 Case ID 이므로 옮길 것이 없다. controlled 면 시작 확인이 여전히
  필요하다.

### 3.9 대화 고정 컨텍스트

- 새 참조 역할 `conversation_user_message`·`conversation_assistant_message`. 저장된
  (`stored`) 메시지만, 순번대로, 그 실행의 지시 원문은 제외한다. 유실·미저장 메시지는
  접수되지 않은 입력이므로 넣지 않는다.
- `discussion_reply`: 그 요청을 연 메시지 **이전**의 대화. `intent_authoring`·
  `intent_gate_review`: 실행 생성 시점까지의 대화 전체.
- 업무화된 Case 의 QG-01 검토에 주는 `original_request` 는 **업무 요청 메시지**다(첫 초안
  실행의 지시가 아니다). 업무화 기록이 없는 Case 는 기존 규칙 그대로다.
- 지시문 표지: 사용자 메시지는 사용자의 말이며, AI 메시지는 **AI 의 이전 제안이지
  사용자의 요구가 아니다**(D-60).

## 4. 저장·API

스키마 **v16**. 새 표 다섯과 컬럼 둘.

- `case.stage` (CHECK `discussion`/`work`, NULL = 이전 Case), `run.request_id`
- `conversation_message`, `conversation_message_ref`, `conversation_request`,
  `case_work_start`, `case_visibility_event`
- 요약 ≤200, 경로 ≤512, 위치 ≤200. 값은 열거형 `CHECK`. 본문 컬럼 없음.

이행 v15→v16 은 컬럼·표만 더한다. 기존 Case 의 단계·보관·메시지·요청을 **지어내지 않고**
Profile 판·정책·판정·후보를 바꾸지 않는다. 반복 이행이 멱등이다.

API:

| 경로 | 내용 |
|---|---|
| `POST /api/projects/{pid}/conversations` | 준비 Case 생성(`Idempotency-Key` 지원) |
| `GET /api/projects/{pid}/conversations?archived=` | 대화 목록(단계·보관·현재 요청·답변 필요) |
| `GET /api/cases/{id}/conversation` | 대화 조회(메시지·요청·업무화·전송 가능 여부와 사유) |
| `POST /api/cases/{id}/messages` | 일반·정정·카드 답변 전송(202 / 재전송 200) |
| `GET /api/cases/{id}/messages/by-client-id/{cid}` | 접수 불명 대조 |
| `POST /api/cases/{id}/requests/{rid}/settle` | 요청 종료 기록(`completed`·`failed`) |
| `POST /api/cases/{id}/work-start` | 최초 업무화 |
| `POST /api/cases/{id}/archive`·`/restore` | 보관·복원 |
| `POST /api/cases/{id}/runs` | `request_id` 추가 |
| `GET /api/cases/{id}`·`/api/projects/{pid}/cases` | `conversation`·`stage`·보관 표시 추가 |

거부는 409 + `{"refusals": [...], "message": ...}` 이다(정책 거절과 같은 모양).

## 5. 성공 기준

| 기준 | 내용 |
|---|---|
| AC-1 | 대화 생성은 목표·Profile 없는 `discussion` Case(kind `undecided`, Profile·판 NULL, 기본 Autonomy 행)를 만든다. feature 로 채우지 않는다. 기존 생성 API 는 업무 단계 Case 를 그대로 만들고 `undecided` 는 거부한다 |
| AC-2 | 보관·복원이 종료 상태·요청·실행을 바꾸지 않고 이력을 남긴다. 목록이 보관 필터를 지원한다. 질문 없는 휴식은 답변 필요가 아니다 |
| AC-3 | 메시지가 Case 안의 연속 순번과 원문 참조·해시·요약만 가진다(본문은 Runner). 자료 참조의 id·버전·해시·위치를 보존하고 없는/다른 Case 산출물·미등록 저장소 참조를 거부한다 |
| AC-4 | 전송 응답은 접수 대기이고 Runner 저장 보고 뒤에만 `stored` 다. 해시 불일치·유실은 접수가 아니다. 새 경로에서 커밋과 중계 사이의 Runner 폴링이 접수를 유실시키지 않는다 |
| AC-5 | 같은 `client_message_id` 재전송은 새 intake·메시지·요청 없이 같은 결과(200), 다른 내용은 409. client id 조회로 접수 여부를 대조하고 받지 않은 전송은 404 |
| AC-6 | 요청 처리 중(`processing`·`unknown`) 같은 Case 의 일반·정정 메시지, 피드백, 사람 의도 초안이 API 직접 호출에서도 409 다. 다른 Case 는 막히지 않고 대기열이 없다 |
| AC-7 | 두 연결의 동시 일반 전송 중 하나만 요청을 연다 |
| AC-8 | 연결 Run 이 끝나도 요청 종료 기록 전까지 잠금이 유지되고, 미종료 Run 이 있으면 종료 기록이 거부된다. 종료 뒤 Case 가 닫히지 않아도 전송이 열린다 |
| AC-9 | `completed` 는 여는 메시지 저장·연결 Run 종료·불명 없음일 때만이다. 불명 Run 이면 `unknown` 으로 잠금 유지. 여는 원문 유실·Run 없음이면 `failed(original_lost_before_persist)`. 종료된 요청에 Run 을 연결할 수 없다(트랜잭션 안 재확인) |
| AC-10 | 카드 답변은 처리 중에도 가능하고 대상 질문·버전에 한정된다(대체된 버전·이미 답함·다른 Case 거부, 검사가 원문 접수보다 먼저). 요청을 열거나 닫지 않고 동의·결정·위임 근거를 만들지 않는다. 답변 원문이 유실되면 질문이 다시 열린다 |
| AC-11 | 정정은 같은 Case 사용자 메시지만 대상이며 원본·그 요청·실행을 보존하고 새 요청을 열어 잠금 규칙을 따른다 |
| AC-12 | `discussion_reply` 는 읽기 전용·요청 연결 필수·지시 = 여는 메시지·원문 저장 뒤에만 열린다. 준비 단계에서 다른 목적과 의도 버전 생성은 거부된다. 예산 예약·정산이 같은 Case 에 누적되고 hard 한도에 막힌다. 완료 응답은 AI 메시지로 한 번만 붙는다 |
| AC-13 | 업무화는 준비 Case 만, 처리 중 요청을 연 저장된 사용자 메시지에 근거하며 같은 Case ID 에 Profile v2·kind·출처와 위임 근거(그 메시지)를 남긴다. 앞선 메시지·요청·Run·예산 소비·한도·Autonomy·저장소 선택이 보존된다. 업무 단계 Case 는 거부된다 |
| AC-14 | 업무화 뒤 기존 경계가 그대로다 — controlled 시작 확인, 조사 Profile 의 제품 수정 차단, v2 완료 계약(방식 없는 `met` 거부), 예산·게이트 |
| AC-15 | 논의 응답·의도 작성·QG-01 검토가 저장된 대화를 역할·순번대로 고정 참조로 받고, 업무화 Case 의 QG-01 요청 원문은 업무 요청 메시지다. 대화 메시지가 없는 Case 의 문맥은 바뀌지 않는다 (구현 중 문구 수정 — 10절) |
| AC-16 | v15→v16 이행이 기존 Case·정책·Profile 판·판정·후보를 바꾸지 않고 메시지·요청을 지어내지 않으며 멱등이다. 기존 Case 는 업무 단계로 도출된다. 기존 시험이 전부 통과한다 |
| AC-17 | 파일 DB 재개 뒤 준비 Case·메시지·요청·잠금·업무화 기록이 복원되고, 제어부 재시작으로 중계 중이던 메시지는 유실로 표시되며 요청이 거짓 완료되지 않는다 |
| AC-18 | 대화 조회가 단계·보관·메시지(접수 상태·정정 관계·참조)·요청·전송 가능 여부와 사유를 보이고 관리 화면이 이를 표시하며 서버 거부를 그대로 보인다 |
| AC-19 | 실제 CLI: 새 논의 지시문과 대화 문맥으로 실제 codex 가 파일을 바꾸지 않고 응답하며 앞선 논의를 반영한다. 업무화 뒤 의도 초안이 논의에서 명시한 금지를 제약으로 옮기는지 관찰한다 |
| AC-20 | 기존 경계 유지: `enforcement` 네 축·게시 미강제, 새 기능이 권한·동의·위임을 만들지 않음, 본문 비저장(데이터 경계 시험) |

## 6. 검증

1. 순수 규칙 단위 시험(`domain/conversation.py`): 단계 도출, 전송 가능 판정, 요청 종료 판정.
2. API 하네스 시험(`tests/test_conversation.py`): AC-1~15·18 의 대표·거부 경로.
3. 경쟁: 두 연결·두 스레드의 동시 전송(AC-7), 종료 기록과 Run 연결 경합(AC-9).
4. 이행: 커밋된 v15 스키마로 만든 DB 를 v16 으로 두 번 연다(AC-16).
5. 재시작: 파일 DB 재개, 중계 중 재시작의 유실 처리(AC-17).
6. 전체 `scripts\run-tests.ps1`(pytest 수와 P1 계약 18 을 따로 보고), 웹 `npm run build`.
7. 실제 CLI(AC-19): 새 지시문이므로 실제 `codex` 로 논의 응답 2회(첫 응답, 앞선 논의를
   참조하는 후속 응답)와 업무화 뒤 의도 초안 1회. 스크립트 `ui/live/ui01_conversation.py`,
   라이브 데이터 `%LOCALAPPDATA%\Temp\hads-ui-01-live`, 저장소 `var\` 를 건드리지 않는다.
   판정은 AI 가 지시를 따랐는가를 **관찰로** 기록하고 제품 규칙 위반만 실패로 멈춘다.

기존 시험이 새 규칙과 충돌하면 의미를 검토해 고치고 검사를 지우지 않는다.

## 7. 구현 순서

1. `domain`: 열거형·거부 사유, 순수 규칙(`domain/conversation.py`)과 단위 시험.
2. 스키마 v16·이행.
3. 저장 계층: 대화 생성·메시지·요청·잠금·업무화·보관, 접수 유실 연동, 카드 답변 검사,
   Run 연결, 대화 문맥.
4. 진입 검사: 단계·요청 조건, `discussion_reply`.
5. API, Runner 지시문·문맥 표지, 관리 화면.
6. 시험(대표·거부·경쟁·이행·재시작), 전체 검증, 실제 CLI, diff 검토.
7. `ui/evidence/UI-01-results.md`, 이 plan 완료 기록, `DEVELOPMENT.md` 갱신.

## 8. 시작 관측

- `main`, HEAD `a8ee278`, 작업 트리 clean, 로컬 추적 ref `origin/main` 과 같다(원격을 새로
  조회하지 않았다).
- 기준선: `scripts\run-tests.ps1` → pytest **481**, P1 계약 unittest **18** 통과(이 세션,
  약 4분 9초). `.venv` Python 3.12.10 정상.
- 외부 쓰기·commit·push·PR 허용은 받지 않았다. 결과는 작업 트리에 남겨 인계한다.

## 9. 완료 기록

- **상태: 완료(2026-09-23).** 범위는 UI-01 에 머물렀다. 강제 축은 넷 그대로이며 이 작업이
  더한 것은 **대화·현재 요청이라는 네 번째 축과 그 잠금**이다. 2절의 넣지 않는 것은 그대로
  넣지 않았다.
- AC-1~20 을 구현·시험으로 확인했다. 상세 연결은
  [UI-01 실행 결과](../ui/evidence/UI-01-results.md)에 있다.
- 최종 검증은 `scripts\run-tests.ps1` 로 제품 pytest **513**, P1 계약 unittest **18**, 웹 `npm run build` 통과다(기준선 481 → +32). 새 시험 32건(`tests/test_conversation.py` 30, v15→v16 이행
  1, 실제 uvicorn 강제 종료 재시작 1)을 포함한다.
- 실제 CLI: `codex-cli 0.154.0` 으로 논의 응답 2회·업무화 뒤 의도 작성 1회를 **두 번**
  돌렸다(1회차는 하네스 요약 문제로 증거에서 뺐다 — 결과 3절). 제품 규칙 20건 통과, 지시와
  다른 관찰 없음. 자동 판정 밖에서 의도 초안의 출처 오기 하나를 관찰했다(결과 3절).
- 외부 쓰기·commit·push·PR 은 하지 않았다. 결과는 작업 트리에 남겨 인계한다.

## 10. 구현 중 plan 에서 바꾼 것

- **AC-15 문구.** "업무화 기록이 없는 Case 의 문맥은 바뀌지 않는다" → "대화 메시지가 없는
  Case 의 문맥은 바뀌지 않는다". 3.9절대로 의도 작성·QG-01 검토는 대화가 있으면 받는다 —
  업무화 전의 업무 Case(기존 API 로 만들고 메시지를 보낸 Case)도 대화가 있으면 그것이
  입력이다. 원래 문구는 3.9절과 어긋났다.
- **논의 응답은 확인되지 않은 누적 변경에 막히지 않는다.** 3.7절은 controlled 시작 확인만
  적었다. `_check_material_delta` 는 목적과 무관하게 `blocks_all_tasks` 면 전부 막는데, 그러면
  사람이 그 변경을 **논의할** 수단이 없어진다. 논의 응답은 읽기 전용이고 기준·항목을 바꾸지
  않으므로 제외했다. 같은 상태에서 작업 목적은 그대로 막힌다(시험으로 고정).
- **Profile 조회의 준비 단계 표시.** 준비 Case 가 "R1 이전 Case"로 보였다. 조회에만 쓰는
  도출값 `not_yet_decided` 를 더했다(저장하지 않는다).
- **메시지 요약은 본문이 아니다.** 화면·하네스가 본문 앞부분을 요약으로 보내던 것을 자기
  검토에서 잡아 고쳤다(결과 4절). API 모델에 규칙을 적었다.
- **답변 유실 시 질문 재개를 기존 답변 경로에도 적용했다.** 3.5절은 새 경로로 적었지만 같은
  유실 처리가 intake 에 걸려 있어 두 경로에 함께 적용된다. 기존 시험은 영향이 없었다.
