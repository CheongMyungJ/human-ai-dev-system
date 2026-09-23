# P4-06b 실행 결과 — 지식 원문의 서버 저장

기준: [P4-PLAN-06b](../../plans/P4-PLAN-06b.md) / D-67 보충(사용자 결정 2026-09-24: 지식만 원문 PC 경계의 예외) /
스키마 **v23**. 세션 S-026. 선행 [P4-06 결과](P4-06-results.md)(v22, 원문은 Runner 에만).

## 1. 구현 결과

- **저장**(v23 `knowledge_body`): `(artifact_id, revision)` 별 본문·해시·크기·목적(`knowledge` / `authority_message`)·
  올린 주체. **이 DB 의 유일한 본문 표**이며 지식 원문과 자동 등록 규칙의 권위 사용자 메시지 한 건만 들어간다
  (CHECK: 목적 둘, ≤ 256 KiB). `artifact_ref` 는 그대로 — 서버 보관 원문의 소유 PC 는 등록한 대화의 PC(출처)이고
  가용성은 저장한 순간 `available` 이다. **데이터 이행 없음** — v22 의 지식 원문은 소유 PC 가 연결될 때 올라온다.
- **수동 등록·개정**(`POST /api/cases/{id}/knowledge`, `/api/knowledge/{id}/versions`): 중계·접수 없이
  `Repository.store_knowledge_original` 이 참조 + 본문을 한 트랜잭션으로 넣는다. 내용 ≤ 4,000 자(422). 출처 PC
  (`target_runner_id`)는 등록된 Runner 면 되고 **연결돼 있을 필요가 없다**. 종료된 Case 에서도 등록된다.
- **자동 등록**(Runner `_store_knowledge`): 항목마다 `POST /api/runner/knowledge-originals` 로 본문을 올린다(해시
  동봉·대조, 같은 해시 재전송은 그대로, 다른 해시 409). Runner 는 새 지식 원문의 **사본을 두지 않는다**(집은
  서버). 이어 **그 응답의 지시 원문(요청을 연 사용자 메시지)** 을 `kind = message` 로 올린다 — 참조가 이미 있고
  사용자 메시지이며 해시가 같고 소유 Runner 일 때만 받는다. 처리기(`apply_knowledge_report`)는 그 보고에서 하나도
  등록되지 않으면 권위 메시지 본문을 지운다(`drop_unused_authority_body`, 다른 버전이 가리키면 남긴다).
- **배정 싣기**(`assignment_payload`): 서버 본문이 있는 인라인 참조에 `body_b64` 를 붙인다(역할 무관 — 같은
  사용자 메시지가 대화 참조로 들어가는 실행에도 같은 본문·같은 해시). Runner `load_context` → `_read_verified`
  가 실린 본문을 참조의 해시와 대조한다: 맞으면 `read`, 다르면 `hash_mismatch` — **자기 저장소로 대신하지 않는다**.
  실린 본문이 없으면 지금처럼 자기 저장소다. 영수증 형식·`check_receipt` 는 그대로다. 조회(`list_context_refs`)에
  `body_source`(server / runner).
- **이행**(`GET /api/runner/{id}/knowledge-uploads`, Runner `upload_knowledge_originals`, 제어 루프의 열람 다음):
  이 Runner 가 소유하고 `available` 인데 서버 본문이 없는 지식 원문(모든 버전)·권위 메시지를 참조·해시로 내려주고
  Runner 가 자기 저장소에서 읽어 해시가 맞는 것만 올린다. 없거나 다르면 건너뛴다(`storage = runner` 로 남는다).
  출처 메시지를 준 수동 등록도 같은 길이다.
- **열람**(`open_read_request`): 서버 본문이 있으면 본문을 중계 버퍼에 먼저 넣고 요청을 `relayed` 로 만든다 —
  소유 PC 의 열람 대기열에 넣지 않고 받아 가는 경로는 그대로다.
- **조회·화면**: 버전·등록 카드 조회에 `storage`·`source_storage`(server / runner). 관리 화면 지식 패널 —
  "서버에 저장된다 · 비밀값을 적지 말 것" 안내, 버전마다 `서버 저장` / `PC 에만(이행 대기)`, **"내용 보기"**(열람
  경로, PC 연결 무관). 새 화면 등록 카드 — "적용 내용과 이 대화에서 한 그 말 한 건은 서버에 저장된다" 한 줄.
  등록 규칙(`KNOWLEDGE_REGISTRATION_RULE`) — 서버 저장 사실과 "비밀값이 있으면 블록을 붙이지 말고 글로 알린다".
- **시험 도구**: `Harness.second_runner()`(별도 저장소·원장·가짜 CLI 의 둘째 PC), `marker_tables`(DB 표 단위
  표식 검색), `forget_server_body`.

## 2. 성공 기준 근거

| 기준 | 근거 (`tests/test_knowledge_server.py` 등) |
|---|---|
| AC-1 | `test_manual_registration_stores_on_the_server_without_the_pc_and_reads_come_from_the_server`(접수 행 없음, 바로 `available`·`storage = server`, 해시 = 참조 해시, PC 미연결에서도 201). `test_knowledge.py::test_an_unreadable_required_rule…`(저장 보고 없이 `available`, 진입 검사의 핵심 미확인에 걸리지 않음) |
| AC-2 | `test_a_rule_from_one_pc_reaches_work_on_another_pc_even_while_the_first_is_disconnected`(본문 둘 = knowledge + authority_message, 해시 = 참조 해시, `run.knowledge_report_json`·다른 표에 본문 없음, 등록 결과 P4-06 그대로) |
| AC-3 | 같은 시험 — PC B 의 의도 초안·결합 기록·구현·검증 전부 `knowledge_required`+`knowledge_source` 핵심·`read`·`body_source = server`, 지시문에 두 원문, Manifest 제공·`source_seq`, PC B 저장소에 원문 없음, `assigned_runner_id = B` |
| AC-4 | 같은 시험 — PC A 의 heartbeat 를 오래된 값으로 두어 미연결 상태에서 PC B 를 돌렸다(`/api/runners` 가 미연결로 보임) |
| AC-5 | `test_a_server_body_is_used_only_when_its_hash_matches`(서버 본문 변조 → `hash_mismatch`·`required_context_unavailable`·CLI 호출 없음 — 이 PC 에 올바른 사본이 있어도 대신하지 않음; 서버 본문이 없어지면 소유 PC 의 사본이 다음 제어 루프에서 다시 올라와 복구됨; 둘 다 없으면 `missing`). `test_knowledge.py::test_an_unreadable_required_rule…`(서버 본문 삭제 → 필수 `missing`·참고 `partial`) |
| AC-6 | 수동 등록 시험 — Runner 를 돌리지 않고 `read_original(serve=False)` 로 본문·해시, 소유 PC 의 열람 대기열 비어 있음 |
| AC-7 | `test_old_knowledge_held_only_by_the_owning_pc_is_uploaded_when_that_pc_connects`(v22 방식 원문 + 출처 메시지 → `storage = runner`·올릴 것 둘·본문 없음, 다른 PC 는 `missing`, 소유 PC 한 바퀴 → 둘 다 `server`·올릴 것 비움·두 번째는 올릴 것 없음, 다른 PC 가 둘 다 `read`) |
| AC-8 | `test_the_authority_message_is_kept_only_when_something_was_registered`(전부 거부 → 메시지 본문 삭제·지식 원문은 남음; 하나 등록 → 둘 다 남음; 재처리 그대로) |
| AC-9 | 수동 등록 시험 — 4,001 자 422, Runner 끝점의 해시 불일치·다른 종류(`intent`)·다른 해시의 기존 참조·다른 Runner 의 권위 메시지 전부 409 |
| AC-10 | 두 PC 시험 — `marker_tables` 로 지식 표식·권위 메시지 표식이 `knowledge_body` 에만, 같은 대화의 다른 말·PC B 의 업무 요청은 어느 표에도 없음, 로그에 셋 다 없음. `test_data_boundary.py::test_the_knowledge_body_table_is_the_only_body_table_and_is_bounded`(본문 컬럼을 가진 표는 `knowledge_body` 뿐, CHECK 둘, 지식 나머지 표·`artifact_ref`·`intake`·열람 요청 표에 본문 컬럼 없음). 기존 경계 시험 전부 그대로 통과 |
| AC-11 | `test_a_v22_database_gets_the_body_table_empty_and_wants_uploads`(v22 스키마 + 지식 버전 → v23, 표 비어 있음, `storage = runner`, 올릴 것에 나옴, 본문 없음, 멱등) |
| AC-12 | 브라우저 `test_a_rule_said_in_the_conversation_gets_a_card_and_can_be_invalidated`(카드 "서버에 저장", `knowledge_body` 둘, 패널 안내 "서버에 저장"·"비밀값", `K-002` `서버 저장`, "내용 보기" → 본문) |
| AC-13 | 3절 — 실제 codex 두 Runner |
| AC-14 | 두 PC 시험 — 기준은 `policy:work_progressor` 가 검증 보고로 적음. 강제 축·권한 변경 없음(코드 대조) |

## 3. 검증

### 자동 시험

최종 `pwsh -File scripts\run-tests.ps1` → 웹 빌드 성공, 웹 단위 **18** 통과, pytest **678 통과·1 건너뜀·0 실패**
(8분 5초, 기준선 671 통과·1 건너뜀 에서 +7 — 건너뜀은 기준선과 같은 한 건), P1 계약 unittest **18** 통과. 경고 2건은
기존 deprecation 이다. 새 pytest 7건 = `test_knowledge_server.py` 6(두 PC, 수동 등록·열람·거부, 해시 대조, 이행, 권위
메시지 정리, v22→v23) + `test_data_boundary.py` 1. 브라우저 시험은 기존 지식 시험을 확장했다(카드·패널 안내·저장
표시·내용 보기).

기존 시험의 **의미 검토** 셋 — 검사를 지우지 않았다: `test_knowledge.py` AC-15 "서버 DB 에 원문 없음" →
"`knowledge_body` 에만 있고 로그·Runner 저장소에 없음"; AC-6 "Runner 파일 삭제" → "서버 본문 삭제"(같은 뜻),
"저장 전 `pending`" 하위 사례 → "저장 보고 없이 바로 `available`"(서버 저장에는 접수가 없다); v21→v22 이행 시험은
그대로(v23 절은 뒤에 붙였다).

### 실제 CLI (AC-13)

`p4/live/p406b_two_pcs.py`(제품 코드 import 없음, 실제 `codex-cli 0.156.1`·설치된 Edge, **같은 호스트의 두
Runner 프로세스**)로 **통과 — 제품 규칙 29/29, 관찰 8, 종료 뒤 남은 프로세스 0**. 회차 `051313997`(셋째 시도),
데이터 `%LOCALAPPDATA%\Temp\hads-p4-06b-live\051313997`, 증거 `p4/evidence/P4-06b-live*`(로그·결과 JSON·화면 3장).
첫 시도는 스크립트 결함(`wait_until` 안의 `next()` StopIteration), 둘째 시도는 **배정 경로의 한계 발견**(두 Runner
를 동시에 켜자 PC A 의 대화 응답을 먼저 폴링한 PC B 가 맡아 지시 원문 `missing` 으로 실패 — 4절) 으로 끝났고,
셋째 시도는 Runner 를 차례로(A → A 종료 → B) 돌렸다.

| 단계 | 제품 규칙(전부 OK) | 관찰(AI 판단) |
|---|---|---|
| A 규칙(PC A) | 업무화되지 않음. 자동 등록 활성·`user_statement`·`ai:codex`. **`storage = server`·`source_storage = server`**. 열람이 PC 없이 서버에서 옴(소유 PC 열람 대기열 비어 있음). 사용자의 말 표식·옮긴 적용 내용 모두 DB 의 **`knowledge_body` 에만**. 서버 로그에 본문 없음. AI 말에 등록 블록 없음. 응답 본문(지식 아닌 원문)은 DB 에 없음. 카드가 "서버에 저장" 을 알림 | codex 가 등록 블록을 붙였고 옮긴 내용이 사용자 말과 **글자 그대로**(표식 포함), 범위 프로젝트 전체·필수·제약. 응답 15초 안팎 |
| A 종료 → B 기동 | PC A 미연결로 보임. PC B 연결. PC B 저장소 비어 있음 | — |
| B 업무(PC B) | 의도 초안·설계·계획·구현·검증 2 — **실행 6개 전부** `assigned_runner_id = B`, `knowledge_required`(핵심)·`knowledge_source` 둘 다 영수증 `read`·`body_source = server`, Manifest `K-001 provided`. PC B 원문 저장소에 권위 원문 없음. 논의 응답은 `not_applicable_activity`. 기준은 `policy:work_progressor`(C-01 `unverified`, C-02~04 `met`) | 업무화 → 동의 → 설계·계획 → 구현 → 검증 → 이월 질문("Python 검증 환경 제공") 답 → 검증 → 예외 카드 대기에서 멈춤(라이브 범위 밖) |
| C 준수(관찰) | — | 구현된 `error_lines` 에 한 줄 docstring 이 있다(**AI 의 행동이며 시스템이 강제·판정한 것이 아니다**) |

## 4. 경계와 남은 것

- **비밀값은 시스템이 검사하지 않는다.** 패널·카드·등록 규칙이 알릴 뿐이다. 등록 뒤 알게 되면 무효화(상태만,
  본문은 이력)이며 본문 삭제 경로는 없다.
- **권위 메시지는 응답 시점에 올라간다.** AI 가 블록을 붙인 응답의 지시 원문을 Runner 가 결과 전에 올리고,
  처리기가 하나도 등록하지 못하면 지운다 — 그 사이 짧은 창에 DB 에 있다. 중계 버퍼에 잡아 두는 대안은 제어부
  재시작의 기동 복구에서 본문을 잃어 권위 원문 없는 등록을 만든다.
- **Runner 는 새 지식 원문의 사본을 두지 않는다.** 서버 백업이 지식 본문을 맡는다(P6-04 에서 문서화).
- **옛 지식의 이행은 소유 PC 연결에 달렸다.** 연결되지 않는 PC 의 원문은 `storage = runner` 로 남고 다른 PC 는
  여전히 읽지 못한다(P4-06 그대로). 진입 검사는 이것을 미리 알지 못한다.
- **배정은 원문 소유 PC 를 보지 않는다**(이 세션에서 발견, 라이브 둘째 시도). Runner 가 둘이면 대기 실행을
  먼저 폴링한 쪽이 가져가 다른 PC 의 대화 응답을 맡고 지시 원문 `missing` 으로 실패한다. P4-06b 의 범위 밖
  (지식 원문만 서버로 옮겼고 지시·대화 원문은 소유 PC 만 읽는다) — P6-01 의 몫으로 DEVELOPMENT.md 9절에 적었다.
  두 PC 시험·라이브는 Runner 를 차례로 돌린다.
- 지식 외 원문의 경계는 그대로다. P4-07(선택 추출)·UI-04·QG-08 은 넣지 않았다.
