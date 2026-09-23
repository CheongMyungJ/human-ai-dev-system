# P4-07 실행 결과 — 선택적 지식 추출

기준: [P4-PLAN-07](../../plans/P4-PLAN-07.md) / D-67 / [프로젝트 지식](../../project-knowledge.md) 3절 / QG-08 /
스키마 **v24**. 세션 S-027. 선행 [P4-06 결과](P4-06-results.md)(v22)·[P4-06b 결과](P4-06b-results.md)(v23).

**제품 판단은 새로 내리지 않았다.** 참고 후보의 자동 활성화 조건은 사용자 판단 대기이며 이 판은 자동 활성화가
없다(plan 0절). 그 밖의 선택(추출 자리·관계·확인 수준·관측 문맥·예산 표시)은 D-67 안의 상세 설계다(plan 9절).

## 1. 구현 결과

- **순수 규칙**(`domain/knowledge.py`): 관계 `Relation`(supports·supersedes·contradicts), 추출 목적
  `EXTRACTION_PURPOSES`(검증·분석·실험·구현), 한 실행 후보 상한 3, `parse_report_item` 의 `relates_to`·`relation`·
  `basis`·`proposal`(대상 없는 관계·모르는 관계 거부), **QG-08 채택 확인 `adoption_check`**(막음: 후보 아님·원문
  없음·열린 충돌·반증 대상 활성·`into` 대상 무효·범위 확대 / 경고: 근거 없음·관측보다 넓은 범위·필수 승격·관계
  대상 버전 변경·독립 검토 없음).
- **저장**(v24): `knowledge_version` 에 `relates_to_knowledge_id`·`relation`·`observed_json`(≤ 1000)·
  `adoption_json`(≤ 2000), 표 `knowledge_evidence`(근거 — supports·duplicate, 출처 실행·근거 원문 참조·요약 200),
  `knowledge_intake` 를 상태 `evidence`+`evidence_id` 로 재구성(행 보존). **데이터 이행 없음**(옛 버전은 NULL).
  `_rebuild_table` 의 외래 키 검사를 **다시 만든 표로 한정**했다(v21 이행 시험의 고정 자료가 다른 표의 옛 어긋남을
  가져 재구성이 멈췄다 — 재구성이 만든 어긋남이 아니다).
- **보고·처리**: `report_result` 가 네 작업 목적의 `knowledge_report` 를 받는다(다른 목적 409 그대로). 결과 뒤
  훅 `apply_extraction_report`(처리기 설정과 무관, `knowledge_intake` 멱등). 공유 처리 `_apply_report` —
  완료되지 않은 실행 `run_not_completed`, 4건째부터 `too_many_items`, 모르는 관계 키 `unknown_related_key`,
  서버 본문 없음 `content_not_stored`; 같은 원문(해시) → 근거(duplicate), `supports` → 대상의 근거, 그 밖에는
  **새 후보 항목**(`ai_proposal`·`candidate`, `source_run_id`, `reason_summary = 추출 근거: …`, 관계·관측 문맥).
  논의 응답의 `proposal: true` 항목은 같은 길로 후보(권위 메시지 없음 — 사용자 말 항목이 하나도 없으면 권위 본문
  삭제, P4-06b 규칙 그대로).
- **관측 문맥** `_observed_context`: 실행·목적·Case·저장소(실행 → 작업공간 → 유일한 후보)·기준 커밋(작업공간)·
  도구 판. 반증·대체 제안 후보에는 관계 대상의 당시 버전(`relates_to_version`)도 남긴다.
- **활성화** `activate_knowledge`: 채택 확인 → 막는 항목이면 `KnowledgeAdoptionRefused`(API 409, 코드·항목 목록)
  → 새 버전(`user_decision`, `adoption` 기록, 축소 반영). `into_knowledge_id` 면 대상의 새 버전(원문 = 후보의 것)
  이고 후보 버전은 `superseded_by` 로 닫힌다. `GET /api/knowledge/{id}/adoption-check` 가 활성화 없이 같은 확인.
- **주입**: 후보는 P4-06 그대로 보조(`knowledge_candidate`). 지시문 머리에 관계(`← K-001 반증`)와 관측(`관측:
  저장소 app@abc1234 (Case 브랜치)`). `assignment_payload` 가 네 작업 목적에도 `knowledge_index`(+ 이 실행의
  저장소 이름)를 싣는다.
- **Runner**: `KNOWLEDGE_EXTRACTION_RULE`(계기 목록·상한·근거·일반화 금지·관계·서버 저장·비밀값 금지, 지식 목록이
  실린 실행에만), 등록 규칙의 `proposal: true` 항목, `_detach_knowledge`(작업 실행의 응답에서 블록을 떼고 결과
  원문에서도 뗀다), `_store_knowledge(with_authority)` — 권위 메시지는 논의 응답의 사용자 말 항목에만.
- **조회·화면**: `knowledge_view` 에 항목별 근거, 버전의 관계·관측·채택; `knowledge_registrations_view` 에
  `origin`(statement/proposal/extraction)·`basis`·`evidence`·`observed`. 새 화면 — 후보 카드(`KnowledgeCandidateCards`:
  이 업무의 실행이 남긴 후보·근거·거부, "후보이며 규칙이 아니다", 관리 화면 링크), 제안 카드, 근거 카드. 관리
  화면 지식 패널 — 관계·관측·근거·채택 기록, **채택 확인** 버튼(항목 목록), 활성화 폼(효력·활동 축소·`K-00x 의
  새 버전으로`), 자동 활성화 없음 안내.
- **시험 도구**: 가짜 codex 표지 `HADS_FAKE_CANDIDATE`(검증 실행의 후보 블록, `HADS_FAKE_CANDIDATE_SUPPORTS=K-001`)·
  `HADS_FAKE_PROPOSAL`(논의 응답의 제안 항목).

## 2. 성공 기준 근거

| 기준 | 근거 (`tests/test_knowledge_extraction.py` 등) |
|---|---|
| AC-1 | `test_a_verification_run_leaves_a_candidate_and_a_run_without_a_block_leaves_nothing`(K-001 후보·`ai_proposal`·`reference`·`source_run_id`·근거·`ai:codex`, 원문 표식은 `knowledge_body` 에만·로그·Runner 저장소 없음, 결과 원문에 블록 없음, 기준 판정 `policy:work_progressor`·종료 `completed`, DB CHECK `IntegrityError`, 재처리 `[]`) |
| AC-2 | 같은 시험(둘째 대화: 블록 없음 → 등록 없음·종료 그대로), `test_the_extraction_rule_is_attached_only_to_work_runs_that_got_an_index` |
| AC-3 | `test_supports_and_duplicates_become_evidence_and_supersedes_contradicts_become_related_candidates`(`supports` → 근거 행·intake `evidence`·항목 없음, 같은 내용 재보고 → `duplicate` 근거, 항목 셋 그대로) |
| AC-4 | 같은 시험(K-002 `supersedes`·K-003 `contradicts`, K-001 버전 사슬 `[(1, active)]` 그대로, 다음 검증 실행에 필수 + 후보 둘, 머리에 `← K-001 반증`·`← K-001 대체 제안`) |
| AC-5 | `test_the_adoption_check_blocks_on_state_content_conflict_and_widening_and_warns_otherwise`(순수), `test_activation_passes_the_adoption_check_narrows_only_and_can_apply_into_another_item`(409 `contradicts_active`·`scope_widened`·`content_unavailable`·`open_conflict`, `GET adoption-check` 같은 결과, 경고만이면 활성·`adoption.findings` 기록) |
| AC-6 | 같은 시험(`into` → K-001 v2 `user_decision`·후보 원문·효력·활동 축소, v1 `superseded`, K-002 후보 `superseded_by` = v2, 다음 검증 실행에 v2 제공·K-002 없음, 구현 실행은 활동 비적용) |
| AC-7 | `test_the_knowledge_head_shows_relation_and_observed_context`(순수), AC-1 시험(`observed` 의 실행·저장소·기준 커밋·도구, 참조 메타데이터·지시문 `관측: 저장소 primary@`), 이행 시험(옛 버전 NULL) |
| AC-8 | `test_a_proposal_in_a_discussion_reply_is_only_a_candidate_without_an_authority_message`(후보·`source_message_id` 없음·`knowledge_body` 에 `knowledge` 만·사용자 말 표식 없음; 말 + 제안 → 활성 + 후보·권위 메시지 남음) |
| AC-9 | `test_report_items_carry_relation_basis_and_proposal_and_bad_relations_are_refused`(순수), `test_reports_from_other_purposes_incomplete_runs_and_too_many_or_unknown_keys_are_refused`(의도 초안 보고 409, `unknown_related_key`·`too_many_items`, 실패한 검증 실행 `run_not_completed`, 거부 intake 기록) |
| AC-10 | `test_a_v23_database_gets_the_evidence_table_and_new_columns_empty`(v23 스키마 → v24, 근거 표 비어 있음, 새 컬럼 NULL, intake 행 보존·새 CHECK·`evidence` 상태 검사, 멱등) |
| AC-11 | `tests/test_data_boundary.py::test_the_knowledge_body_table_is_the_only_body_table_and_is_bounded`(`knowledge_evidence` 추가 — 본문 컬럼 없음, 유일한 본문 표 그대로), AC-1 시험의 표식 검사, `register_knowledge` 의 길이 검사(`MAX_OBSERVED_JSON`·`MAX_ADOPTION_JSON`, 스키마 CHECK) |
| AC-12 | 브라우저 `test_a_work_run_leaves_a_candidate_card_and_the_admin_panel_checks_and_activates_it`(후보 카드 K-001·"후보이며 규칙이 아니다"·관측, 종료 그대로, 제안 카드 K-002, 관리 패널 채택 확인 "막는 항목 없음"·"독립 AI 검토는 돌리지 않았다" → 활성화 → v2 `user_decision`·채택 기록) |
| AC-13 | 3절 — 실제 codex |
| AC-14 | AC-1·4·6 시험(기준 판정 `policy:work_progressor`, 종료 `completed`, 필수 활성 버전 그대로 주입). 강제 축·권한 변경 없음(코드 대조 — 진입 검사·정책 코드 미변경) |

## 3. 검증

### 자동 시험

최종 `pwsh -File scripts\run-tests.ps1` → 웹 빌드 성공, 웹 단위 **18** 통과, pytest **688 통과·2 건너뜀·0 실패**
(8분 46초, 기준선 677 통과·2 건너뜀 에서 +11), P1 계약 unittest **18** 통과. 경고 2건은 기존 deprecation 이다.
새 pytest 11건 = `test_knowledge_extraction.py` 10(순수 4 + 제어부·Runner 5 + 이행 1) + 브라우저 1
(`test_a_work_run_leaves_a_candidate_card_and_the_admin_panel_checks_and_activates_it`).

건너뜀 2건은 `tests/test_migration.py` 의 v1·v2 이행 시험 — `controller/schema.sql` 을 바꾼 최근 20 커밋 안에서
옛 스키마 커밋을 찾지 못하면 건너뛴다(S-026 인계 시점 1건 → 이 세션 시작 시 2건, 제품 무관·시험 창의 문제).

첫 전체 실행에서 브라우저 시험 하나가 실패했다 — 세션 공유 제어부의 `knowledge_body` 전체를 단언했기 때문(다른
시험의 행이 있다). 이 대화의 원문으로 좁혀 고쳤고(제품 결함 아님) 다시 돌린 것이 위 수치다. 기존 시험의 의미
검토: `tests/test_data_boundary.py` 의 지식 표 목록에 `knowledge_evidence` 를 더했다(검사를 지우지 않았다).
`db._rebuild_table` 의 외래 키 검사를 다시 만든 표로 한정한 것은 시험이 아니라 이행 도우미의 변경이다(1절).

### 실제 CLI (AC-13)

`p4/live/p407_extraction.py`(제품 코드 import 없음, 실제 `codex-cli 0.156.1`·설치된 Edge, Runner 하나)로 두 번
돌렸다. 라이브 로그 파일은 회차마다 새로 쓰이므로(`Log`) 첫 회차는 결과 JSON 사본으로 남겼다.

| 회차 | 결과 | 요지 |
|---|---|---|
| `061616170`(첫째, `P4-07-live-results-061616170.json`) | **통과 — 제품 규칙 5/5, 관찰 8, 남은 프로세스 0** | 기본 저장소(README·`app.py` 만). 구현 1·검증 2 실행 모두 후보 규칙을 받았지만 **후보를 남기지 않았다**(관찰). 정리 응답도 "재사용할 만한 관찰 사실이 없다"고 답했다 — 논의 응답은 대화만 보고 실행 결과를 보지 않으므로 정직한 답이다(관찰). 후보가 없어 C 를 건너뛰었다 |
| `062331187`(둘째, `P4-07-live-results.json`·로그·화면 2장) | **통과 — 제품 규칙 13/13, 관찰 15, 남은 프로세스 0** | 저장소에 비자명한 시험 조건(README 의 시험 절, `tests/test_app.py`, `samples/app.log`, `LOGTOOL_SAMPLES`)을 둔 회차(`enrich_repo`). 아래 표 |

| 단계 | 제품 규칙(전부 OK) | 관찰(AI 판단) |
|---|---|---|
| A 업무 | 구현 실행이 끝났고 Manifest 가 기록됐다(후보 규칙과 지식 목록이 실렸다). 기준 판정은 지식과 무관 | 업무화 → 동의 → 결합 기록 → 작업공간 → 구현 → `criteria_unresolved` 대기(검증 Task 없이 멈춤 — 계획의 판단). **구현 실행은 후보 블록을 붙이지 않았다** — 두 회차 네 작업 실행 모두 그랬다. 실제 codex 는 작업 실행에서 후보를 내지 않는 쪽으로 판단했다 |
| B 정리 | 대화의 AI 말에 등록 블록 없음. 정리 응답이 사용자 말(활성 규칙)을 만들지 않음. 등록된 것은 **후보(`ai_proposal`)뿐**·원문 `storage = server`·권위 메시지 없음(`source_message_id = None`) | "저장소를 읽고 직접 확인한 사실만 후보(proposal)로" 청하자 codex 가 **84초** 뒤 `proposal: true` 항목 **둘**을 붙였다 — K-001 "시험 실행 방법과 현재 검사 범위"(운영 사실·참고, 근거 "README.md 의 시험 절과 tests/test_app.py 의 두 시험 함수를 직접 확인했다"), K-002 "표본 로그 경로와 형식"(운영 사실·참고). 둘 다 저장소 범위·활동 `verification` 으로 적었다(관찰). 글에는 같은 내용을 사람이 읽을 말로 적고 "파일은 바꾸지 않았고 시험도 실행하지 않았다"고 밝혔다 |
| C 활성화 → 다른 대화 | 채택 확인 `blocked = []`, 항목 `independent_review_not_run`(경고), 근거 1. 활성화(API, 사람의 결정) → **K-001 v2 활성·`user_decision`·`adoption` 기록**. 다른 대화(경고 줄 함수)의 실행 6개 중 **검증 실행 2개**에 `knowledge_reference` 로 들어가고 영수증 `read`, Manifest `provided` v2 — 의도·설계·계획·구현 실행은 `not_applicable_activity`(후보가 `verification` 활동으로 적혔으므로) | 둘째 대화도 업무화 → 동의 → 설계·계획 → 구현 → 검증 → 이월 질문("Python 검증 환경 결정") 답 → 검증 → `criteria_unresolved` 대기. 활성화한 적용 내용(관찰): "README 에는 저장소 루트에서 `python -m pytest -q` 로 시험을 실행한다고 적혀 있다. 현재 tests/test_app.py 는 … `error_lines` 검사는 없다" |

AC-13 의 첫 문장(작업 실행이 후보를 남기는가)은 **관찰: 남기지 않음**이고, 둘째 문장(후보 → 사람의 활성화 → 다른
대화 주입)은 정리 응답의 제안 경로로 **제품 규칙 통과**다. 작업 실행 경로의 제품 규칙(후보 등록·관측 문맥·카드)은
가짜 CLI 시험(AC-1~4·12)이 본다.

## 4. 경계와 남은 것

- **후보는 AI 의 판단이다.** 무엇이 의미 있는 사건인지 시스템이 판정하지 않는다. 후보를 안 남긴 실행이 "재사용할
  것이 없었다"는 뜻이 아니다. 중복 판정은 원문 해시라 같은 뜻의 다른 문장은 다른 후보다.
- **참고 후보의 자동 활성화는 없다**(사용자 판단 대기). 활성화는 전부 사람이 하며 채택 확인은 값일 뿐 판정이
  아니다. 독립 AI 검토 실행(QG-08 선택 사항)도 없다 — `adoption.independent_review = not_run`.
- **반증은 대상을 자동으로 바꾸지 않는다.** 관계로만 남고 사람이 무효·개정·`into` 로 정리한다. 자동 충돌 기록도
  없다.
- **별도 추출 실행이 없다.** 예산 부족은 그 작업 실행의 진입 거부이지 별도 미처리 상태가 아니다.
- **관측 문맥은 실행이 아는 만큼이다.** 분석 실행은 저장소만 알고 기준 커밋은 작업공간이 있는 실행에서 온다.
- 결정 사항 패널·프로젝트 규칙 새 화면(UI-04)은 넣지 않았다 — 새 화면의 후보 카드는 관리 화면으로 보낸다.
