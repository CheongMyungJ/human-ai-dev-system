# UI-04a 실행 결과 — 결정 사항 패널·프로젝트 규칙 화면

상태: **완료**
기준: 설계 v0.8 2차 / D-01~90 / **D-80** / 2026-09-24
계획: [UI-PLAN-04a](../../plans/UI-PLAN-04a.md). 세션 S-028. 선행 [P4-07 결과](../../p4/evidence/P4-07-results.md)(v24) ·
[P4-06 결과](../../p4/evidence/P4-06-results.md) · [UI-03 결과](UI-03-results.md).

**제품 판단은 새로 내리지 않았다.** 참고 후보의 자동 활성화 조건은 그대로 사용자 판단 대기이며(자동 활성화 없음), 첫
하위 plan 의 범위는 S-027 인계의 제안을 그대로 잡았다(plan 0절). 화면 자리·수동 등록의 출처는 상세 설계 선택이다
(plan 9절). **스키마는 v24 그대로다**(새 표·컬럼·이행 없음).

## 1. 구현 결과

- **결정 사항 패널**(`web/src/shell/ReviewPanel.tsx` `Decisions`, 오른쪽 `결정 사항` 탭). 이 대화의 것을 **보고 이동**하는
  자리다(변경은 프로젝트 규칙 화면). 절은 값이 있을 때만 생긴다 —
  1. **업무**: 업무화·Profile·결정 주체·위임 근거(UI-03 그대로).
  2. **목표·기준**: 의도 최신 버전(버전·상태·동의 상태·작성 방식)과 `원문 열기`(결과물 패널의 그 버전), 기준별 판정.
     "목표·범위·제약의 본문은 PC 의 의도 원문에 있다" — 서버가 아는 것만 보인다.
  3. **결정**: `decision` 행의 종류를 사람 말로(`DECISION_KIND_LABEL` — 서버 `DecisionKind` 와 같은 목록), 대상이 의도
     버전이면 `의도 vN` 열기, 주체·시각, `evidence_ref` 가 이 대화의 메시지 원문이면 `근거 메시지 #n`, "이 버전에만
     적용된다".
  4. **이 대화에서 정한 프로젝트 규칙·후보**: `knowledge_registrations` 를 출처별로(사용자 말 → 활성 등록 / AI 제안 /
     실행이 남긴 후보 / 근거로 이음 / 등록하지 않음), 키·버전·**지금 상태**(현재 버전)·효력·종류·요약, `메시지 #n`(권위
     메시지 또는 응답 메시지 — 그 메시지로 스크롤·강조), `프로젝트 규칙에서 보기`(그 항목을 펼쳐 연다). 활성화 버튼은
     없다("활성화·개정은 프로젝트 규칙 화면에서, 무효화는 대화의 카드에서").
  5. **이 업무에 적용된 프로젝트 규칙**: 새 조회 `GET /api/cases/{id}/knowledge-use` 의 버전별 집계 — 제공 실행 수·마지막
     실행(목적·id)·넣지 않은 사유별 수, 제공 당시 상태와 지금 상태가 다르면 `(지금 대체됨)`, Manifest 기록 전 실행 수.
     머리에 "주입은 제공 기록이며 준수의 증거가 아니다".
  6. 답한 질문 · AI 해석 기록 · 진행 이력(UI-03·P4-05 그대로). 꼬리에 프로젝트 규칙 화면 링크.
- **프로젝트 규칙 화면**(`web/src/shell/ProjectRules.tsx`, 주소 `?project=P&screen=rules[&item=K-001]`, 왼쪽 목록의
  `프로젝트 규칙`). 등록부 전체를 **활성 필수 / 활성 참고 / 후보 / 대체·무효(접힘)** 로 보이고 항목마다 키·버전·상태·
  효력·종류·요약·범위·활동·권위·**출처(대화 제목 · 메시지 #n → 그 메시지로)** 를, 펼치면 관계·관측·채택 기록·근거(출처
  실행·대화로)·저장 위치·`내용 보기`(열람 경로의 서버 본문)·이력(`v1 → v2`)을 보인다. 동작은 전부 기존 API 다 —
  후보의 **채택 확인**(QG-08 항목 목록·근거 수·독립 검토 없음) → **활성화**(효력·활동·저장소로 좁히기·`K-00x 의 새
  버전으로`, 409 는 코드를 그대로), **개정**(새 내용·제목·종류·효력·범위·활동·사유 → 새 버전; 새 내용은 출처 대화와 출처
  PC), **무효**(사유 필수), **충돌 기록·해소**, **수동 등록**(출처 대화 선택 — 기본값은 마지막으로 연 대화, 서버 저장·비밀값
  금지 안내, `AI 제안(후보로만)` 체크). 관리 화면의 지식 패널은 그대로 남았다(`readBody` 를 `lib/knowledgeBody.ts` 로
  옮겨 같이 쓴다).
- **원래 대화·메시지로 이동**: 주소 규칙 `web/src/lib/address.ts`(`project`·`case`·`screen`·`item`·`seq`, 순수 함수 —
  웹 단위 시험 3건). `&seq=N` 은 대화를 연 뒤 **한 번** 소비한다 — 그 메시지로 스크롤·`data-focus="1"`·강조(6초), 주소에서
  지운다, 읽던 위치 기억보다 우선한다, 그 순번의 메시지가 아직 없으면 다음 조회에서 다시 본다. 패널 안의 `메시지 #n` 은
  사건 `hads:focus-message` 로 같은 동작을 한다. 본문은 기존 열람 경로 그대로(PC 미연결이면 "연결 필요").
- **카드 링크**(`ProgressCards.tsx`): 후보·제안·등록·거부 카드의 "관리 화면에서 …" 가 프로젝트 규칙 화면(해당 항목
  펼침)으로 바뀌었다. 무효화 동작은 그대로.
- **서버 조회**(본문 없음, 정책·진입·권위 규칙 변경 없음):
  - `knowledge_view`·`get_knowledge_version` 의 버전에 `source_case_title`·`source_message_seq`(`_knowledge_version_row`),
    근거 행에 `source_case_title`.
  - `knowledge_registrations_view` 에 `source_message_seq`(권위 메시지)·`reply_seq`(그 실행이 붙인 응답 메시지, 작업
    실행은 null).
  - `case_knowledge_use_view(case_id)` → `GET /api/cases/{case_id}/knowledge-use`: `run_knowledge` 를 이 Case 실행으로
    묶어 버전별로 센다 — `provided_runs`(`provided` 만), `skipped`(사유별 수), `last_run_id`·`last_run_purpose`·`first_at`,
    제공 당시 `state` 와 지금 `state_now`, `runs_recorded`·`runs_unrecorded`(v22 이전 실행 — "지식 없음"이 아니다).
- **화면 부품**: `Shell.tsx`(주소 읽기·쓰기, `screen`·`rulesItem`·`focusSeq`, 규칙 화면에서는 오른쪽 패널 닫힘),
  `Sidebar.tsx`(`프로젝트 규칙` 진입), `ConversationView.tsx`(`focusSeq`·`onFocused`, `sh-message-focus`), `events.ts`
  (`hads:focus-message`), `api.ts`(`CaseKnowledgeUse`·`knowledgeApi.caseUse/revise`·`adoptionCheck` 의 범위 인자·
  `DECISION_KIND_LABEL`·`Decision.evidence_ref`), `shell.css`.

## 2. 성공 기준 근거

| 기준 | 근거 |
|---|---|
| AC-1 | 브라우저 `test_a_rule_registered_on_the_rules_screen_reaches_the_work_and_a_candidate_is_activated_there`(`decisions-goal` 에 "의도 v1"·"의도 동의됨", `decision-intent_agreement` 가 "의도 v1"). 준비 단계 대화의 빈 패널 문구는 UI-03 시험 그대로 |
| AC-2 | 브라우저 `test_the_decisions_panel_and_the_rules_screen_lead_back_to_the_message`(`decisions-rule-K-001`: "K-001 v1"·"지금 활성"·"이 대화에서 한 말"·`data-state=active`, `메시지 #3` 클릭 → `message-3` 강조, `프로젝트 규칙에서 보기` 링크, 패널에 `rule-activate-*` 없음)와 두 번째 시험(실행 후보 `decisions-rule-K-002` `candidate`·"실행이 남긴 후보") |
| AC-3 | 서버 `test_the_case_knowledge_use_counts_provided_manifests_per_version`(집계 = 실행별 Manifest 의 `provided` 수·사유별 수·마지막 실행, 필수(모든 활동) > 참고(검증만), `runs_unrecorded = 0`, 논의 대화는 빈 목록, 404), `test_the_use_view_keeps_the_version_that_was_provided_after_a_revision`(개정 뒤에도 당시 v1·`state_now = superseded`, 새 대화는 v2); 브라우저 두 번째 시험(`applied-K-001` 의 `data-provided` = API 값, "준수의 증거가 아니다") |
| AC-4 | 브라우저 두 시험(`rules-required`·`rules-reference`·`rules-candidates`·`rules-history-toggle "대체·무효 1"`, 항목의 `data-state`·`data-obligation`, `rule-origin`(관측: 저장소)·`rule-storage`(서버 저장)·`rule-history`, `rule-body` 는 `내용 보기` 뒤에만) |
| AC-5 | 브라우저 첫 시험(`rule-source-link-K-001` = `?project&case&seq=3` · "메시지 #3" → 클릭 → `message-3` `data-focus=1` → 주소에서 `seq` 사라짐 · `case=` 유지). 개정 뒤(권위 메시지 없는 `user_registration` 버전) `source_message_seq = None` — 대화만 연다 |
| AC-6 | 브라우저 두 번째 시험(`rule-check-K-002` → "막는 항목 없음"·"독립 AI 검토는 돌리지 않았다" → `rule-activate-K-002` → `active`, `rule-adoption-K-002`, K-002 `[(1, superseded, ai_proposal), (2, active, user_decision)]`, `adoption.by = owner`, 효력 `reference`). 409 코드·축소·`into` 의 서버 규칙은 P4-07 시험 그대로이고 화면은 같은 API 를 부른다 |
| AC-7 | 브라우저 첫 시험(`rule-revise-K-001` → 제목·사유 → v2 `user_registration`, v1 `superseded`, 이력 "v1 대체됨 … 표현을 다듬음"; `rule-invalidate-K-001` → 사유 → `invalid`·`invalid_reason`, 활성 필수 절에서 사라지고 대체·무효 1). 충돌 기록·해소는 P4-06 API 그대로(관리 패널과 같은 호출) |
| AC-8 | 브라우저 두 번째 시험(`rules-register-case` 선택 → 내용·제목 → `rules-register-done "K-001 v1"`, `rule-K-001` `active`, 출처 링크 "새 대화", API `user_registration`·`server`·`source_case_id` = 그 대화; 그 뒤 업무 실행에 제공됨) |
| AC-9 | 브라우저 두 시험(`knowledge-card-rules`·`knowledge-candidate-rules` 의 `href` = `?project&screen=rules&item=K-00n`; 관리 화면 지식 패널 `knowledge-K-002` "활성"·채택 기록). 기존 브라우저 시험 8건 통과 |
| AC-10 | 서버 `test_the_registry_and_the_cards_point_back_to_the_source_conversation_and_message`(사용자 말: `source_message_seq 1`·`reply_seq 2`·제목 "규칙 이야기"; AI 제안: 응답 순번만; 실행 후보: 순번 없음·제목 "필터 기능"; 근거 행의 제목; 조회 넷에 원문 표식 없음·표식은 `knowledge_body` 에만). 스키마 v24 그대로(이행 시험 변경 없음) |
| AC-11 | 코드 대조 — 진입 검사·정책·권위 코드 미변경(`controller/admission.py`·`domain/knowledge.py`·`schema.sql` diff 없음). 화면 문구("실행 권한·동의·인수가 아니다", "주입은 준수의 증거가 아니다", "AI 제안은 후보로만"). 활성 필수 AI 제안은 DB CHECK 그대로(P4-07 시험) |
| AC-12 | 아래 3절 — 서버 3건 + 브라우저 2건 + 웹 단위 3건, 기존 시험 전부 통과 |
| AC-13 | 아래 3절 — 실제 codex·실제 Edge |
| AC-14 | 기존 브라우저 시험(관리 화면·카드·초안·검토 버전)과 전체 시험 통과(3절). 시험 수는 기준선 대비 늘기만 했다 |

## 3. 검증

### 자동 시험

최종 `pwsh -File scripts\run-tests.ps1` → 웹 빌드 성공, 웹 단위 **21** 통과(+3 `address.test.ts`), pytest **693 통과·2
건너뜀·0 실패**(10분 37초, 기준선 688 통과·2 건너뜀 에서 +5), P1 계약 unittest **18** 통과. 경고 2건은 기존 deprecation
이다. 새 pytest 5건 = `tests/test_decisions_view.py` 3(조회의 출처 표시, `knowledge-use` 집계 = Manifest, 개정 뒤 당시
버전 유지) + `tests/test_web_shell.py` 2(UI-04a 절). 건너뜀 2건은 이행 시험의 옛 스키마 커밋 창(DEVELOPMENT 9절)
그대로다.

새 브라우저 시험 하나는 처음 두 번 실패했다 — (1) 가짜 codex 가 대화의 **첫** 메시지에서 말한 규칙을 지시문 머리로 옮겨
`내용 보기` 가 규칙 문장을 보이지 않았다(시험 도구의 특성, 4절), (2) 응답 뒤 빈 입력창의 보내기 버튼을 "열림" 으로
기다렸다(시험 결함). 둘 다 시험을 고쳤고(두 번째 메시지에서 규칙을 말한다, `send-refusal` 없음을 기다린다) 제품은 바꾸지
않았다. 기존 시험은 바꾸지 않았고 전부 통과했다(관리 화면 지식 패널 시험 포함).

### 실제 CLI·실제 브라우저 (AC-13)

`ui/live/ui04a_rules.py`(제품 코드 import 없음, 실제 `codex-cli 0.156.1`·설치된 Edge, Runner 하나, 요청 처리기·진행기
켜짐). 회차 `092723318` **통과 — 제품 규칙 26/26, 관찰 7, 남은 프로세스 0**(`UI-04a-live.log`·`UI-04a-live-results.json`·
화면 6장). 첫 시도(`092249006`)는 하네스 결함(응답 뒤 빈 입력창의 보내기 버튼을 "열림" 으로 기다림)으로 시작도 못 하고
끝났다 — 제품과 무관하며 로그는 둘째 회차가 덮어썼다.

| 단계 | 관찰(AI 판단) | 제품 규칙(전부 OK) |
|---|---|---|
| A 규칙 | 짧은 논의(96초) 뒤 "이 프로젝트에서는 앞으로 … docstring …" 을 codex 가 **12초** 만에 옮겨 등록했다 — K-001 필수·제약, 저장소 범위(P4-06 라이브와 같이 "이 프로젝트" 를 저장소로 좁혀 적었다), 적용 내용은 사용자 문장 그대로(로그 14행) | 등록 조회의 `source_message_seq 3`·`reply_seq 4`. 카드 링크 = `?project&screen=rules&item=K-001`. 결정 사항 패널의 행("K-001 v1 · 지금 활성 · 필수 · 제약", "이 대화에서 한 말"), 활성화 버튼 없음, `메시지 #3` → 강조. 규칙 화면: 주소 `screen=rules`·오른쪽 패널 닫힘, 활성 필수 절, 출처 링크 `?project&case&seq=3` "메시지 #3", `내용 보기` 가 서버 본문(`storage=server`)을 연다. **'원래 대화로' → 메시지 #3 강조 → 주소의 `seq` 소비**(`A-focus.png`) |
| B 정리 | "재사용할 사실을 후보로 정리해줘" 에 codex 가 **48초** 뒤 `proposal: true` 항목 **둘**을 붙였다 — K-002 "시험 실행 위치와 명령", K-003 "시험용 표본 로그 지정"(운영 사실·참고·저장소 범위·활동 `verification`, 근거 "README 의 시험 안내와 tests/test_app.py 를 직접 확인했다") | 사용자 말(활성 규칙)이 생기지 않음. 후보는 `candidate`·`ai_proposal`·`source_message_seq None`·`reply_seq 6`. 패널이 후보로 보이고 `프로젝트 규칙에서 보기` 가 항목을 펼쳐 연다. 화면의 채택 확인 = 서버(`blocked []`, `independent_review_not_run` 경고, 근거 1). 활성화 → K-002 `[(1, superseded, ai_proposal), (2, active, user_decision)]`·채택 기록, 활성 참고 절로 이동(`B-activated.png`) |
| C 적용 | 다른 대화의 구현 요청 → 업무화 → 동의 → 결합 기록(계획 실행이 한 번 실패한 뒤 다시 완료 — 재작성) → 구현 → `criteria_unresolved` 대기(검증 Task 없이 멈춤 — 계획의 판단). 실행 5개 | `knowledge-use` 집계 = 실행별 Manifest: **K-001 v1 제공 4**(의도·계획×2·구현, 논의 응답 1은 활동 비적용), K-002 v2·K-003 는 제공 0·`not_applicable_activity 5`(활동 `verification` 인데 검증 실행이 없었다 — "넣지 않음" 으로 보인다), `runs_unrecorded 0`. 패널의 `data-provided` 가 서버 값과 같고 "준수의 증거가 아니다" 문구, 목표·기준 절("의도 v1 · agreed · 의도 동의됨 · AI 초안", 기준 "ERROR 수준만"), 결정 절("의도 동의 · 대상 의도 v1 · owner")(`C-applied.png`) |

AC-13 의 관찰 부분(실제 AI 가 규칙을 옮기는가·제안을 붙이는가)은 이번 회차에 둘 다 **그렇다** 였고, 제품 규칙 부분(패널·
규칙 화면·이동·채택 확인·활성화·집계)은 전부 통과했다. 사람의 활성화는 라이브에서도 화면(규칙 화면의 버튼)으로 했다.

## 4. 경계와 남은 것

- **결정 사항 패널·프로젝트 규칙 화면은 보고·이동·사람의 변경 자리다.** 등록·활성화·개정·무효·충돌 기록은 기존 API 의 규칙
  그대로이며 권한·동의·인수·준수가 아니다. 적용 집계도 "제공했다" 일 뿐이다(영수증·판정은 세지 않는다).
- **목표·범위·제약의 본문은 보이지 않는다.** 서버는 의도의 버전·동의·기준 요약·판정만 알고 본문은 PC 다. 항목별 표시는
  원문 열람과 함께 뒤 작업에서 본다.
- **프로젝트 규칙의 자리는 임시다.** 프로젝트 설정 화면(UI-04 의 뒤 하위 plan)이 생기면 그 안으로 옮긴다. 수동 등록은 출처
  대화를 고른다 — 대화 없는 등록 경로는 만들지 않았다.
- **원래 메시지로 이동은 순번이다.** 본문은 열람 경로로 오며 PC 미연결이면 "연결 필요" 다. 검색(D-84)이 아니다.
- **참고 후보의 자동 활성화는 없다.** 이 작업 시점에는 사용자 판단 대기였고, 작업 보고 뒤 사용자가 **반자동**(조건 충족을
  표시하고 사람이 한 번에 활성화)으로 정했다 — 후속 작업 P4-07b(DEVELOPMENT 1.12절). QG-08 독립 AI 검토도 없다.
- **가짜 codex 의 특성:** `HADS_FAKE_RULE` 은 고정 컨텍스트 뒤의 마지막 메시지에서 규칙을 옮기므로 대화의 **첫** 메시지에서
  말하면 지시문 머리를 적용 내용으로 적는다(시험 도구의 특성 — 제품 규칙이 아니다). 브라우저 시험은 두 번째 메시지에서
  규칙을 말한다.
