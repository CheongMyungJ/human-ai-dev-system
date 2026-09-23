# P4-06 실행 결과 — 프로젝트 지식 관리·적용

기준: [P4-PLAN-06](../../plans/P4-PLAN-06.md) / D-67·D-80 / 사용자 결정 2026-09-24(자동 활성 등록, D-80 보충) /
스키마 **v22**. 세션 S-025. 같은 세션에서 먼저 한 P4-05b 는 [P4-05b 결과](P4-05b-results.md)다.

## 1. 구현 결과

- **순수 규칙**(`domain/knowledge.py`): 종류(결정·제약·알려진 문제·운영 사실), 효력(필수·참고), 상태(후보·
  활성·대체·무효), 권위(사람 등록·대화의 사용자 말·사람의 활성화·AI 제안), 목적 → 활동 표(빈 활동 = 논의를 뺀
  모든 작업, 모르는 목적은 모든 항목), 선택 `select`(활동 불일치·다른 저장소·**범위 미확정**을 나눔, 경로 조건은
  `paths_unresolved` 로 주되 비적용으로 읽지 않음, 필수 → 참고 → 후보 순서), 막는 충돌(두 항목이 모두 적용되고
  하나 이상이 필수), 권위 검사(AI 제안은 후보로만), 등록 블록 분리·항목 검사.
- **저장**(v22): `knowledge_item`(Project 안 키 `K-001`)·`knowledge_version`(원문 참조·메타데이터·권위·출처·
  대체·무효, **활성 필수 AI 제안을 막는 CHECK**)·`knowledge_conflict`·`knowledge_intake`(자동 등록의 멱등·거부
  사유)·`run_knowledge`(Manifest)·`run.knowledge_report_json`. 원문은 등록한 Case 의 `artifact_ref`(종류
  `knowledge`)로 소유 Runner 에만 있다. 데이터 이행 없음 — 옛 실행의 Manifest 는 "기록 전".
- **등록·변경 API**: `POST /api/cases/{id}/knowledge`(원문을 기록 전에 중계 → Runner 저장, 사람 권위는 재승인
  없이 활성), `POST /api/knowledge/{id}/versions`(개정 = 새 버전, 이전은 `superseded`·대체 관계, 무효였던
  버전은 무효 그대로 대체 관계만), `/activate`(후보 → 새 버전 `user_decision`), `/invalidate`(사유 필수, 상태만),
  `POST /api/projects/{id}/knowledge-conflicts`·`POST /api/knowledge-conflicts/{id}/resolve`,
  `GET /api/projects/{id}/knowledge`, `GET /api/runs/{id}/knowledge`. 충돌 해소·무효 뒤 그 충돌로 기다리던 진행을
  사람 입력으로 다시 본다.
- **주입**: `compose_context` 가 기존 참조 **뒤에** 지식 참조를 더한다 — `knowledge_required`(핵심) → 권위가
  사용자 말이면 `knowledge_source`(그 사용자 메시지, 핵심, 이미 대화·지시로 들어갔으면 생략) →
  `knowledge_reference`·`knowledge_candidate`(보조). 실행 저장소 = 실행의 저장소 / Case 가 고른 코드 저장소 /
  암묵 단일 저장소 / 모름. `plan_context_package` 가 저장소를 받고 결정·충돌을 **같은 계획**에 싣는다 — 진입
  검사·생성·Manifest 가 한 목록을 쓴다. 생성 트랜잭션 안에서 Manifest 를 넣는다(한도 생략은 그대로 적음).
  최신성 계산도 실행 저장소로 구성한다.
- **진입 검사·진행기**: 새 거부 `knowledge_conflict_unresolved`(사람 사유 → 진행기 `knowledge_conflict` 대기).
  필수 원문 불가·한도 초과는 기존 P4-04 경로(`required_context_unavailable`·`context_over_inline_limit`, Runner
  영수증 `missing` → 시작하지 않음) 그대로다.
- **Runner**: 배정의 지식 참조 메타데이터로 머리(`{K-001 v1 · 필수 · 제약 · 범위 · 활동 · 제목}`)를 적고, 지식이
  있으면 고정 컨텍스트 앞에 **지식 안내**(필수는 조건·예외 안에서, 참고는 의무 아님, 후보는 규칙 아님, 권위 원문이
  앞선다, 넓히거나 만들지 말 것, **제공은 준수의 증거가 아님**, 충돌은 결과에 적을 것). **모든 논의 응답**에 등록
  규칙(현재 지식 목록·등록 저장소 이름 포함)을 붙이고, 응답에서 `hads-knowledge` 블록을 떼어 옮겨 적은 내용을
  이 Runner 에 원문으로 저장·등록한 뒤 결과 보고에 메타데이터·원문 참조만 싣는다(원장에도 남아 재전송이 같다).
- **자동 등록**(사용자 결정): 처리기가 응답이 완료된 요청에서 해석보다 **먼저** 등록한다 — 권위 `user_statement`,
  출처 = 요청을 연 사용자 메시지, 주체 `ai:<도구>`, 대체 키가 있으면 그 항목의 새 버전. 없는 저장소·없는 키·
  틀린 종류·형식 오류·완료되지 않은 응답은 거부 사유를 남긴다. 대화 조회에 `knowledge_registrations`.
- **화면**: 새 화면 — 응답 아래 "프로젝트 규칙으로 등록됨" 카드(키·버전·효력·종류·범위·활동·권위, **무효로**,
  관리 화면 링크)와 거부 카드. 관리 화면 — **지식 패널**(목록·상태·권위·원문 가용성·이력·등록·활성화·무효화·충돌
  기록/해소), 실행 목록의 문맥 칸에 제공한 지식(`K-001 v1`, 생략·범위 미확정·기록 전).
- **시험 도구**: 가짜 codex 표지 `HADS_FAKE_RULE`(논의 응답이 사용자 말을 등록 블록으로 옮김).

## 2. 성공 기준 근거

| 기준 | 근거 (`tests/test_knowledge.py` 등) |
|---|---|
| AC-1 | `test_registered_rules_reach_every_work_run_as_originals_and_the_manifest_says_so`(사람 등록 = `user_registration`·활성·재승인 없음, 원문 가용성 `available`) |
| AC-2 | `test_an_ai_proposal_is_only_a_candidate`, `test_candidates_activation_invalidation_and_revision_keep_history`(API 409, 후보는 `knowledge_candidate`·보조, DB CHECK `IntegrityError`) |
| AC-3 | 같은 생애 시험(활성화 v2 `user_decision`·v1 대체, 무효 사유 필수(빈 사유 422)·주입 없음, 개정 v3·무효 v2 는 무효 그대로 대체 관계) |
| AC-4 | `test_selection_follows_activity_and_scope_…`(순수), `test_repository_scope_does_not_mix_repositories_and_follows_scope_expansion`(같은 `src/api` 경로의 두 저장소) |
| AC-5 | 대표 시험(의도 초안·결합 기록·구현·검증 실행마다 필수 1·참고 1, 필수는 핵심·영수증 `read`, 지시문에 원문 표식·`K-001 v1`·안내문) |
| AC-6 | `test_an_unreadable_required_rule_stops_the_run_and_a_reference_does_not`(참고 원문 삭제 → `partial`·응답 완료, 필수 원문 삭제 → `failed`·`required_context_unavailable`·CLI 호출 없음·영수증 `missing`, 저장 전 `pending` → 핵심 미확인), `test_required_rules_over_the_inline_limit_hold_the_run`(참고는 한도 생략, 필수로 넘으면 `over_limit`) |
| AC-7 | `test_only_conflicts_between_applied_required_items_block`, `test_a_conflict_between_applied_required_rules_waits_for_a_person`(의도 초안 전 `knowledge_conflict` 대기·전송 열림·논의 응답은 막히지 않음 → 해소 → 진행 요청 `knowledge_conflict:…` → 동의 대기) |
| AC-8 | 범위 시험(선택 없음·저장소 둘 → 저장소 항목 `scope_undetermined`·Project 항목 제공, A 선택 → A 만, B 더함 → 둘 다) |
| AC-9 | 대표 시험(Manifest `recorded`·제공, 논의 응답은 `not_applicable_activity`), 이행 시험(옛 실행 `recorded = false`) |
| AC-10 | `test_a_rule_said_in_conversation_is_registered_and_injected_with_the_users_words`(등록 `K-001 v1` 필수·활성·`user_statement`·출처 메시지·`ai:` 주체, 대화 원문에 블록 없음, 재처리 `[]`·버전 1), 브라우저 시험 |
| AC-11 | `test_bad_registration_items_are_refused_with_a_reason`(`unknown_repository`·`unknown_supersedes_key`·`invalid_kind_or_obligation`·정상·`format_error`, 실패한 응답 `reply_not_completed`) |
| AC-12 | 자동 등록 시험(다른 대화의 의도 초안: `knowledge_required`·`knowledge_source` 가 끝 둘, 원문 둘 다 지시문에, Manifest `source_seq`; 같은 대화에서는 권위 원문을 다시 넣지 않고 참조 중복 없음) |
| AC-13 | `test_an_update_elsewhere_keeps_the_old_input_and_shows_up_as_drift`(고정 뒤 개정 → 그 실행 Manifest v1·결과 시점 `drifted`·추가 역할 `knowledge_required` → 다음 실행 v2), 자동 등록 시험의 대체 뒤 기존 실행 Manifest v1 |
| AC-14 | 대표 시험(종료 `completed`, 기준은 `policy:work_progressor` 가 검증 보고로 적음 — 지식 제공이 판정을 만들지 않음) |
| AC-15 | 대표 시험(제어부 데이터 폴더의 DB·WAL·로그 파일 어디에도 원문 표식이 없고 Runner 저장소에만 있음) |
| AC-16 | `test_a_v21_database_gets_no_manifest_it_never_had`(v21 스키마 → v22 이상, 표 다섯 비어 있음, 새 컬럼, 옛 실행 기록 전, 멱등) |
| AC-17 | 브라우저 `test_a_rule_said_in_the_conversation_gets_a_card_and_can_be_invalidated`(카드 `K-001 v1`·필수·블록 없는 글 → 무효 사유 → `invalid`, 관리 화면 지식 패널 등록 → `K-002` 활성·`user_registration`) |
| AC-18 | 3절 — 실제 codex |

## 3. 검증

### 자동 시험

최종 `pwsh -File scripts\run-tests.ps1` → 웹 빌드 성공, 웹 단위 **18** 통과, pytest **672 통과**(8분 54초,
기준선 633 에서 +39), P1 계약 unittest **18** 통과. 경고 2건은 기존 deprecation 이다. 새 pytest 39건 = P4-05b
23(`test_progress_limits.py`) + 브라우저 1, P4-06 14(`test_knowledge.py`) + 브라우저 1. 기존 시험의 의미 검토 셋 —
v19→v20 이행의 `== 20` → `>= 20`(판 고정은 각 판의 이행 시험), P4-05 재시도 시험의 마지막 단언(실제 동작:
같은 대기·구현 2), 새로 쓴 v21 이행 시험의 `== 21` → `>= 21`. 검사를 지우지 않았다.

### 실제 CLI (AC-18)

`p4/live/p406_knowledge.py`(제품 코드 import 없음, 설치된 Edge·실제 `codex-cli 0.156.1`)로 **통과 — 제품 규칙
21/21, 관찰 8, 종료 뒤 남은 프로세스 0**. 회차 `014343060`, 데이터 `%LOCALAPPDATA%\Temp\hads-p4-06-live\014343060`,
증거 `p4/evidence/P4-06-live*`(로그·결과 JSON·화면 3장). 첫 시도는 라이브 스크립트가 콘솔 인코딩(cp949)으로
로그를 찍다 죽었다(제품 무관) — `PYTHONUTF8=1` 로 다시 돌렸다.

| 단계 | 제품 규칙(전부 OK) | 관찰(AI 판단) |
|---|---|---|
| A 규칙 | 규칙 대화는 업무화되지 않음. 등록 카드가 응답 아래 보임. 자동 등록은 활성·`user_statement`·출처 = 그 사용자 메시지·`ai:codex`. 적용 내용 원문을 PC 에서 읽을 수 있음. 대화의 AI 말에 등록 블록 없음. 서버 DB 에 적용 내용 원문 없음 | codex 가 등록 블록을 붙였고(응답 15초) **옮긴 내용이 사용자 말과 글자 그대로 같았다**. 다만 "이 프로젝트에서는" 이라고 했는데 범위를 **저장소**(이 Project 의 유일한 저장소)로 적었다 — 저장소가 하나라 적용은 같지만 AI 가 범위를 좁혀 옮길 수 있다는 관찰이다. 필수·제약·모든 활동 |
| B 다른 대화의 업무 | 의도 초안·설계·계획·구현·검증 2 — **실행 6개 전부** 고정 문맥에 `knowledge_required`(핵심)와 `knowledge_source`(권위 원문)가 있고 Runner 영수증이 둘 다 `read`, Manifest `K-001 provided`. 그 대화의 논의 응답에는 `not_applicable_activity`. 기준 판정은 검증 실행 보고(`policy:work_progressor`)이거나 미검증 | 업무화 → 동의 → 설계·계획(이월 질문 "검증용 Python 환경" 하나에 답) → 구현 → 검증 2. C-02~04 `met`, C-01 `unverified` → 예외 카드 대기에서 멈춤(라이브 범위 밖이라 종료하지 않았다) |
| C 준수(관찰) | — (제품 규칙이 아니다: 주입은 준수의 증거가 아니다) | 구현된 `error_lines` 에 **한 줄 docstring 이 있다**(결과 JSON 의 `app.py` 관찰). 같은 회차의 "docstring 이 있는가" 관찰 값 `False` 는 **라이브 스크립트의 검사 결함**이었다(함수 머리 뒤 셋째 줄부터 찾았다) — 검사를 고쳤고 이 회차 값은 파일 내용으로 바로잡는다. 따른 것은 AI 의 행동이며 시스템이 강제·판정한 것이 아니다 |

## 4. 경계와 남은 것

- **옮겨 적기의 충실성은 판정하지 않는다**(사용자 결정의 알려진 위험). 대화의 사용자 말을 AI 가 옮긴 필수 규칙이
  뜻을 바꿨어도 시스템은 모른다 — 주입할 때 권위 원문을 함께 넣고, 카드·관리 화면에서 무효·개정할 수 있을 뿐이다.
- **주입은 준수가 아니다.** 실행이 규칙을 지켰는지는 기존 기준 판정·검토가 보고, 지식을 준 것으로 판정이 바뀌지
  않는다. 규칙 준수를 따로 검사하는 게이트(QG)는 없다.
- **경로 조건은 조건으로 줄 뿐이다.** 실행이 어떤 경로를 다룰지 미리 말하지 않으므로 저장소가 맞으면 경로 조건을
  적어 준다(`paths_unresolved`). 실행 중 범위가 넓어져도 그 실행에 다시 넣지 못한다(CLI 호출 하나 = 입력 하나).
- **논의 응답에는 `discussion` 활동을 적은 항목만 간다.** 대화 응답마다 필수 원문 가용성에 묶이지 않게 한 선택이다.
- **다른 PC 의 실행**은 지식 원문을 읽지 못하면(영수증 `missing`) 필수면 보류다 — 원문을 복제하지 않는다. 한
  PC 기준으로만 시험했다. 진입 검사가 이것을 미리 알지 못해 실행이 늦게 실패한다. **사용자 결정(2026-09-24)으로
  지식만 원문 PC 경계의 예외로 서버에 저장한다 — P4-06b**(DEVELOPMENT.md 1.9절, D-67 보충).
- **충돌은 사람이 기록한다.** 자동 충돌 탐지는 없다. 대화에서 기존 규칙을 바꾸는 말은 AI 가 `supersedes` 로 옮길
  때만 새 버전이 된다.
- 결정 사항 패널·프로젝트 규칙 새 화면·검색(UI-04), 완료·문제 해결 결과의 후보 추출(P4-07), QG-08 은 넣지 않았다.
- 자동 등록은 요청 처리기가 켜져 있을 때만 일어난다(`HADS_AUTO_PROCESS_REQUESTS=0` 이면 보고만 남는다).
