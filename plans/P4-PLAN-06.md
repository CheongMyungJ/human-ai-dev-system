# P4-PLAN-06

프로젝트 지식 관리·적용의 첫 버전. 기준: 설계 v0.8 2차 / D-01~90 / [프로젝트 지식](../project-knowledge.md)
/ D-67·D-80 / 사용자 결정 2026-09-24(아래 0절). 선행: P4-05b(스키마 v21, 같은 세션 S-025), P4-05(v20).

기준선은 [P4-PLAN-05b](P4-PLAN-05b.md) 5.1 과 같다(S-025 시작, 변경 전: 웹 단위 18, pytest 633, P1 18).

범위는 **P4-06 하나**다. P4-07(선택적 지식 추출 — 완료·문제 해결 결과에서 후보 만들기, 근거 추가·대체
정리), UI-04(대화 상단 `결정 사항` 패널·프로젝트 설정의 `프로젝트 규칙` 화면·검색), P5·P6 은 넣지
않는다.

## 0. 사용자 결정 (2026-09-24, 이 plan 을 쓰기 전에 물었다)

**대화에서 사용자가 "이 프로젝트에서는 앞으로 …"처럼 프로젝트 공통 규칙을 말하면 자동으로 활성
등록한다.** 논의 응답의 AI 가 옮겨 적은 짧은 적용 내용을 **사용자 메시지를 권위로** 바로 활성 등록하고
재승인하지 않는다(D-80 "기존 권위의 충실한 등록은 재승인하지 않는다"). 대신 (1) 주입할 때 원래 사용자
메시지도 함께 넣어 실행하는 AI 가 대조할 수 있게 하고, (2) 대화에 "프로젝트 규칙으로 등록됨" 카드와
수정·무효화 경로를 둔다. 알려진 위험: AI 가 옮기며 뜻을 바꾸면 틀린 필수 규칙이 주입될 수 있다(원문이
옆에 있다). 옮겨 적기의 충실성은 시스템이 판정하지 않는다 — 9절 한계로 남긴다.

## 1. 현재 구현과 차이 (코드 대조)

1. **지식이 없다.** 표·API·화면이 없다. 컨텍스트 구성기(`Repository.compose_context_refs`)는 목적별로
   의도·준비 산출물·대화·피드백·질문 답만 고정한다.
2. **P4-04 의 문맥 계약은 그대로 쓸 수 있다.** 참조는 `(role, artifact_id, revision)` 이고 본문은
   Runner 가 읽는다. 등급(핵심/보조)은 역할에서 정해지고(`domain.context.tier_for`), 핵심은 한도로
   생략되지 않고(넘으면 보류) 읽지 못하면 실행을 시작하지 않는다(영수증·해시 대조). **필수 지식을
   핵심 역할로 넣으면 "필수 내용을 조용히 빼지 않는다·원문 불가면 의존 작업 보류"가 새 코드 없이
   성립한다.**
3. **실행 구성은 저장소를 모른다.** `plan_context_package(case, purpose, request, instruction)` 은
   실행의 `repository_id` 를 받지 않는다 — 저장소 범위의 지식을 고르려면 넘겨야 한다.
4. **원문은 Case 에 묶인다.** `artifact_ref.case_id` 가 `NOT NULL` 이다. 지식 원문은 그것을 등록한
   Case(출처 대화)의 원문으로 둔다 — 출처가 곧 그 Case 다. 프로젝트 공통이 되는 것은 적용 관계이지
   원문의 소유가 아니다.
5. **논의 응답은 해석 블록을 이미 뗀다**(`split_interpretation`, 준비 단계·종료 Case 만). 업무 단계
   응답은 블록 처리를 하지 않는다. 등록 블록은 모든 논의 응답에서 떼야 한다.

## 2. 범위

| 넣는 것 | 넣지 않는 것 (담당) |
|---|---|
| **지식 등록부**(v22): 항목(Project 안 키 `K-001`)과 버전 — 원본 참조(Runner 원문 = 짧은 적용 내용·조건·예외), 종류(결정·제약·알려진 문제·운영 사실), 효력(필수/참고), 상태(후보/활성/대체/무효), 범위(Project 전체 또는 저장소 + 경로), 활동, 권위(사람 등록·사용자 발언·사람 결정·AI 제안)와 출처(Case·메시지·실행), 변경 이유·대체 관계. 서버에는 요약·메타데이터·참조만 | 외부 검색·RAG·RRF·MCP, 전체 심볼 그래프 |
| **수동 등록**(API·관리 화면): 사람이 대화(Case)에서 원문과 메타데이터를 등록 — 권위 승계, 재승인 없음. 개정(새 버전)·후보 활성화(새 버전)·무효화·충돌 기록/해소 | 대화 상단 `결정 사항`·`프로젝트 규칙` 새 화면(UI-04) |
| **자동 등록**(0절): 논의 응답의 `hads-knowledge` 블록 → Runner 가 원문 저장 → 처리기가 사용자 발언 권위로 활성 등록(대체 지정 시 그 항목의 새 버전). 대화에 등록 카드(무효화 버튼) | 완료·문제 해결 결과에서의 후보 추출(P4-07) |
| **자동 주입**: 실행의 활동(목적에서 도출)과 범위(실행 저장소 또는 Case 선택 저장소)에 맞는 현재 버전을 고정 문맥에 더함. 필수 = 핵심(조건·예외 원문 + 권위 메시지), 참고·후보 = 보조 | 실행 중 동적 주입(지원하지 않는다고 표시) |
| **Manifest**(`run_knowledge`): 실행마다 선택·제공·생략(한도)·비적용(활동/저장소)·범위 미확정을 버전과 함께 기록. 조회·배정·지시문에 드러냄 | 준수 판정(주입은 준수 증거가 아니다) |
| **보류**: 필수 원문 불가·한도 초과(기존 핵심 규칙), 적용되는 필수 지식의 **미해결 충돌**(새 진입 거부 → 진행기 사람 대기) | 충돌의 자동 해소 |

## 3. 설계

### 3.1 모델 (`domain/knowledge.py`, 순수)

- 종류 `KnowledgeKind`: `decision`·`constraint`·`known_problem`·`operation`.
- 효력 `KnowledgeObligation`: `required`·`reference`. 상태 `KnowledgeState`: `candidate`·`active`·
  `superseded`·`invalid`. 권위 `KnowledgeAuthority`: `user_registration`(사람이 직접 등록)·
  `user_statement`(사용자 메시지를 AI 가 옮겨 등록 — 0절)·`user_decision`(사람이 후보를 활성화)·
  `ai_proposal`(AI 제안).
- **권위 규칙**(D-67·D-80): `ai_proposal` 은 후보로만 등록된다(P4-06). **활성 필수는 사람의 권위(`user_*`)
  에서만** — DB CHECK 로도 막는다. 후보를 활성으로 바꾸는 것은 사람이며 새 버전(`user_decision`)이다.
- 활동 `ACTIVITIES` = `discussion`·`intent`·`design`·`plan`·`implementation`·`verification`·
  `investigation`·`review`. 목적 → 활동 표(`activity_for(purpose)`): 논의 응답 `discussion`, 의도 작성
  `intent`, QG-01·QG-02~07 검토 `review`, 설계 `design`, 계획(결합 기록 포함) `plan`, 구현
  `implementation`, 검증 `verification`, 분석·실험 `investigation`. **빈 활동 목록 = 논의를 뺀 모든
  작업 활동**(논의 응답에는 활동에 `discussion` 을 적은 항목만 간다 — 대화 응답마다 필수 원문 가용성에
  묶이지 않게). 모르는 목적은 모든 항목을 받는다(모르는 것을 비적용으로 읽지 않는다).
- **선택 `select(items, activity, repositories)`** → 결정 목록. 각 현재 버전(후보·활성)에 대해:
  활동 불일치 `not_applicable_activity`, Project 범위는 적용, 저장소 범위는 실행 저장소 집합에 있으면
  적용(경로가 있으면 `scope_resolution = paths_unresolved` — 실행이 경로를 미리 말하지 않으므로 조건으로
  주고 비적용으로 읽지 않는다), 집합에 없으면 `not_applicable_repository`, **집합을 모르면
  `scope_undetermined`**(제공하지 않되 비적용으로도 적지 않는다 — "공통 필수 제약을 먼저 제공하고 범위가
  드러나면 보완", 4절). 순서: 필수 → 참고 → 후보, 같은 효력 안에서는 키 순.
- **충돌 `blocking_conflicts(conflicts, applied)`**: 열린 충돌 중 두 항목이 모두 이 실행에 적용되고 하나
  이상이 활성 필수면 막는다. 참고끼리의 충돌은 막지 않는다(둘 다 참고로 준다).

### 3.2 저장 (스키마 v22)

```
knowledge_item(id, project_id, knowledge_key, created_by, created_at)          UNIQUE(project_id, knowledge_key)
knowledge_version(id, knowledge_id, version, artifact_id, artifact_rev,         -- 원문은 Runner
    kind, obligation, state, summary ≤200, scope_kind(project|repository), repository_id,
    paths_json, activities_json, authority_kind, source_case_id, source_message_id, source_run_id,
    source_report_index, created_by, reason_summary, created_at,
    superseded_by, superseded_at, invalidated_at, invalidated_by, invalid_reason)
    UNIQUE(knowledge_id, version), UNIQUE(source_run_id, source_report_index),
    CHECK NOT (state='active' AND obligation='required' AND authority_kind='ai_proposal')
knowledge_conflict(id, project_id, knowledge_a, knowledge_b, state(open|resolved), recorded_by,
    reason_summary, created_at, resolved_at, resolved_by, resolution_summary)
knowledge_intake(run_id, report_index, case_id, state(registered|refused), knowledge_version_id,
    refusal, created_at)                                                        PK(run_id, report_index)
run_knowledge(run_id, version_id, knowledge_id, activity, obligation, state, decision,
    scope_resolution, context_seq, source_seq)                                  PK(run_id, version_id)
run.knowledge_report_json  -- 논의 응답이 보고한 등록 블록(메타데이터와 원문 참조, 본문 없음)
```

**데이터 이행 없음.** 옛 실행에는 Manifest 가 없다 — 조회는 "기록 전"(`knowledge_recorded = false`)으로
보이고 "지식 없음"으로 적지 않는다.

### 3.3 등록·변경 (`Repository`, API)

- `POST /api/cases/{case_id}/knowledge` — 수동 등록. 원문은 기존 접수 경로(`open_intake`, 종류
  `knowledge`)로 Runner 에 가고 버전은 그 참조를 가리킨다(저장 보고 전에는 `pending` — 필수면 그 사이
  주입이 보류된다). 권위 `user_registration`(또는 요청이 `ai_proposal` 로 적으면 후보). 출처 메시지를
  주면 그 메시지가 권위 원문이다. **종료된 Case 에서도 등록할 수 있다**(지식은 Project 의 것이고 그
  Case 의 기록·판정을 바꾸지 않는다).
- `POST /api/knowledge/{id}/versions` — 개정(새 버전, 원문을 주지 않으면 이전 원문 재사용). 이전 현재
  버전은 `superseded`(대체 관계 기록).
- `POST /api/knowledge/{id}/activate` — 후보 → 활성(사람, 새 버전 `user_decision`).
- `POST /api/knowledge/{id}/invalidate` — 무효(사유 필수). **조회 실패·미확정을 무효로 적지 않는다** —
  사람의 명시 행동뿐이다.
- `POST /api/projects/{pid}/knowledge-conflicts`·`POST /api/knowledge-conflicts/{id}/resolve`.
- `GET /api/projects/{pid}/knowledge` — 항목·현재 버전·이력·가용성(원문 `availability`)·열린 충돌.
- 원문 열람은 기존 열람 중계(`/api/artifacts/.../read`)를 쓴다.

### 3.4 자동 등록 (0절)

- **Runner 지시문**: 모든 논의 응답에 등록 규칙을 붙인다 — 사용자의 **마지막 메시지**가 이 프로젝트에서
  **앞으로** 지킬 규칙·결정·알려진 문제·운영 사실을 명시할 때만 `hads-knowledge` 블록(항목 목록: 종류·
  효력·요약·옮겨 적은 내용·범위(저장소 이름·경로)·활동·대체할 키). "이번 업무에서는" 은 붙이지 않는다.
  범위가 모호하면 붙이지 않고 묻는다. 사용자가 말하지 않은 의무·금지·예외를 더하지 않는다. 배정에
  **현재 지식 목록(키·요약·효력·범위)**과 등록 저장소 이름을 싣는다 — 대체할 키를 지어내지 않게.
- **Runner**: 블록을 글에서 떼고(대화에는 글만), 항목마다 `content` 를 원문으로 저장·등록(종류
  `knowledge`)하고 결과 보고에 메타데이터와 원문 참조만 싣는다(`knowledge_report`). 형식이 틀리면
  항목을 버리고 이유를 보고한다(지어내지 않는다).
- **제어부**: 결과 기록 때 `run.knowledge_report_json` 에 남기고, 처리기가 응답이 **완료**됐을 때만
  항목마다 한 번 등록한다(`knowledge_intake` 로 멱등). 권위 `user_statement`, 출처 = 요청을 연 사용자
  메시지. 저장소 이름이 이 Project 에 없거나 대체할 키가 없으면 **등록하지 않고 거부 사유를 남긴다**.
  대체 키가 있으면 그 항목의 새 버전이다.
- **대화 조회**에 `knowledge_registrations`(이 Case 에서 온 등록·거부, 요약·키·버전·상태). 화면이
  응답 아래 카드("프로젝트 규칙으로 등록됨 · K-003 v1 · 필수 · 제약" + 무효화 + 관리 화면 링크).

### 3.5 주입

- `compose_context(case, purpose, request, instruction, repository_id)` → (참조, 지식 결정). 기존
  참조 **뒤에** 지식 참조를 붙인다(보조 생략은 앞에서부터라 오래된 AI 발언이 먼저 빠진다):
  `knowledge_required`(핵심) → 권위가 `user_statement` 인 필수는 이어서 그 사용자 메시지
  `knowledge_source`(핵심, 이미 대화 참조로 들어갔으면 다시 넣지 않는다) → `knowledge_reference`(보조)
  → `knowledge_candidate`(보조).
- 실행 저장소 집합: 실행의 `repository_id` 가 있으면 그것, 없으면 Case 의 코드 저장소(선택 또는 암묵
  단일), 둘 다 없으면 모름.
- `plan_context_package` 가 `repository_id` 를 받고 결정 목록을 계획(`ContextPlan.knowledge`)에 싣는다.
  **진입 검사·생성·예약이 같은 계획을 쓴다**(P4-04 규칙). 생성 트랜잭션 안에서 `run_knowledge` 를
  넣고, 제공 항목은 계획의 `inclusion`(인라인/한도 생략)을 결정으로 적는다.
- 진입 검사: 적용되는 필수의 미해결 충돌 → `knowledge_conflict_unresolved`(사람 사유 → 진행기
  `knowledge_conflict` 대기, 카드는 관리 화면으로). 필수 원문 불가·한도 초과는 기존 `required_context_
  unavailable`·`context_over_inline_limit` 그대로(환경 사유 → 막힘).
- 배정: `context_refs` 의 지식 참조에 메타데이터(키·버전·효력·상태·종류·범위·경로·활동·권위)를 붙인다.
  Runner 지시문은 참조 머리에 그것을 적고, 고정 컨텍스트 앞에 **지식 안내**를 둔다 — 필수는 조건·예외
  안에서 지킨다, 참고는 의무가 아니다, 후보는 확정되지 않았다, **제공은 준수의 증거가 아니다**, 규칙을
  넓히거나 새로 만들지 마라, 권위 메시지와 적용 내용이 다르면 권위 메시지가 앞선다.
- 최신성: 고정 뒤 새로 생긴 지식 버전은 P4-04 의 `drift` 로 드러난다(결과 시점 표시). 기존 실행의
  입력 기록을 바꾸지 않는다.

### 3.6 화면

- 관리 화면: Project 단위 **지식 패널**(목록·상태·가용성·등록·개정·활성화·무효화·충돌), 실행 문맥
  보기에 Manifest.
- 새 화면: 자동 등록 카드(무효화 버튼, 관리 화면 링크). 결정 사항 패널·프로젝트 규칙 화면은 UI-04.

## 4. 성공 기준

| AC | 기준 |
|---|---|
| AC-1 | 수동 등록: 원문은 Runner, 서버에는 요약·메타데이터·참조. 사람 권위는 **재승인 없이** 활성 필수가 된다 |
| AC-2 | AI 제안(`ai_proposal`)은 후보로만 등록되고 필수로 주입되지 않는다. 활성 필수 AI 제안은 API·DB 모두 거부 |
| AC-3 | 후보 활성화·개정은 새 버전이며 이전 버전은 `superseded`(대체 관계)로 남는다. 무효화는 사유와 함께 상태만 바꾸고 이력을 지우지 않는다. 대체·무효는 주입되지 않는다 |
| AC-4 | 활동+범위로 고른다: 활동 불일치·다른 저장소는 비적용으로 Manifest 에 남고, 같은 경로 이름이라도 다른 저장소의 항목은 주입되지 않는다 |
| AC-5 | Fast Lane(결합 기록)·구현·검증에서 필수 내용이 **실제 원문으로** 지시문에 들어간다(영수증 `read`). 링크만으로 제공 완료로 적지 않는다 |
| AC-6 | 필수 원문을 읽을 수 없거나(가용성·Runner 누락) 필수만으로 한도를 넘으면 그 실행은 보류·시작하지 않음이다. 참고 원문 불가는 부분 문맥이며 막지 않는다 |
| AC-7 | 적용되는 필수 지식에 미해결 충돌이 있으면 진입 거부(`knowledge_conflict_unresolved`)이고 진행기는 사람 대기다. 무관한 업무는 막지 않는다. 해소(또는 한쪽 무효) 뒤 이어 간다 |
| AC-8 | Case 가 저장소를 더하면(범위 확대) 다음 실행이 그 저장소의 항목을 받는다. 저장소를 모르면 저장소 항목은 `scope_undetermined` 이고 Project 항목은 제공된다 |
| AC-9 | Manifest: 실행마다 선택·제공(인라인/한도 생략)·비적용·범위 미확정·버전·문맥 순번. 배정·조회에 드러나고 옛 실행은 "기록 전" |
| AC-10 | 자동 등록: 사용자 메시지의 프로젝트 규칙 → 응답 완료 뒤 활성 등록(권위 `user_statement`, 출처 메시지), 대화에는 글만, 카드가 보인다. 같은 보고의 재처리는 두 번 등록하지 않는다 |
| AC-11 | 자동 등록 거부: 없는 저장소·없는 대체 키·형식 오류는 등록하지 않고 사유를 남긴다. 응답이 실패한 실행의 블록은 등록하지 않는다 |
| AC-12 | 자동 등록된 필수 항목을 주입할 때 권위 사용자 메시지가 함께 들어간다(같은 원문이 이미 대화로 들어갔으면 한 번) |
| AC-13 | 다른 Case 가 지식을 갱신해도 기존 실행의 입력 기록(Manifest·참조)은 바뀌지 않고, 다음 실행이 새 버전을 받으며, 진행 중 실행의 결과에는 최신성 차이로 드러난다 |
| AC-14 | 주입은 준수 판정을 만들지 않는다 — 기준 판정·완료 조건이 지식 제공으로 바뀌지 않는다 |
| AC-15 | 데이터 경계: 서버 DB·로그에 지식 원문이 없다(표식 문자열 검사) |
| AC-16 | v21 → v22 이행: 표가 생기고 비어 있으며 옛 실행은 "기록 전"이다. 멱등 |
| AC-17 | 화면: 관리 화면 지식 패널에서 등록·무효화, 새 화면의 자동 등록 카드와 무효화(브라우저 시험) |
| AC-18 | 실제 CLI 라이브: 실제 `codex` 로 대화에서 프로젝트 규칙을 말해 자동 등록 → 같은 Project 의 **다른 대화**에서 업무를 진행해 그 규칙이 실제 지시문·영수증·Manifest 에 있음을 확인 |

## 5. 검증

- 순수: `domain/knowledge.py` 의 활동 표·선택·충돌·권위 규칙.
- 제어부: `harness`/`processing_harness` — 수동 등록→주입(의도·결합 기록·구현·검증의 참조·영수증·
  지시문), 비적용·다른 저장소 동명 경로, 범위 확대, 후보·대체·무효, 원문 불가(Runner 저장소에서 원문을
  지운 뒤 영수증 `missing` → 시작하지 않음)·한도 초과 보류, 충돌 → 진행기 대기 → 해소 → 이어감, 자동 등록
  (가짜 CLI 응답에 블록)·거부·멱등·권위 메시지 동반, 다른 Case 갱신과 최신성, 데이터 경계(DB·로그에 표식
  없음), 이행.
- 브라우저: 자동 등록 카드·무효화, 관리 화면 등록.
- 전체 `scripts\run-tests.ps1`.
- **실제 CLI 라이브**(`p4/live/p406_knowledge.py`, 제품 코드 import 없음): 실제 `codex` 로 AC-18.

## 6. 경계

- 등록·활성화는 실행 권한을 만들지 않는다. 주입은 준수의 증거가 아니다 — 준수는 기존 기준 판정·검토가
  본다.
- 모든 관련 지식을 발견했다는 보장이 아니다 — 등록된 적용 관계 중 현재 범위에 해당하는 필수를 제공하고
  누락·불확실성을 드러내는 것까지다.
- 실행 중 범위가 넓어져도 그 실행에 지식을 다시 넣지 못한다(CLI 한 번의 호출 = 한 입력). 다음 실행이
  받는다. 동적 주입을 지원한다고 표시하지 않는다.
- 지식 원문은 등록한 Case 의 원문이며 소유 Runner 에만 있다. 다른 PC 의 실행은 그 원문을 읽지 못하면
  (영수증 `missing`) 필수면 보류다 — 원문을 복제하지 않는다.
