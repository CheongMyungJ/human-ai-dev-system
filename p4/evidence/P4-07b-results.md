# P4-07b 실행 결과 — 참고 후보의 자동 활성 조건 표시(반자동)

기준: [P4-PLAN-07b](../../plans/P4-PLAN-07b.md) / D-67 / **사용자 결정 2026-09-24(S-028): 반자동** / [프로젝트 지식](../../project-knowledge.md)
2·3절 / QG-08 / 스키마 **v24 그대로**. 세션 S-029. 선행 [P4-07 결과](P4-07-results.md)(v24) · [UI-04a 결과](../../ui/evidence/UI-04a-results.md).

**제품 판단은 새로 내리지 않았다.** 사용자가 정한 반자동(조건 충족 표시 + 사람의 한 번에 활성화)과 S-027 조건을 그대로
구현했다. 조건 코드의 이름·표시 문구·근거 실행을 세는 법·"화면이 본 것만 활성화"·논의 응답의 제안이 조건 (4)를 만족하지
못한다는 것은 상세 설계 선택이다(plan 0·9절). **클릭 없는 활성화 경로는 없다** — `activate_ready_knowledge` 는 API 끝점에서만
불리고 결과 뒤 훅·요청 처리기·기동 복구 어디에도 없다(코드 대조: `controller/` 안의 호출은 `api.py` 의 끝점 하나뿐).

## 1. 구현 결과

- **순수 규칙**(`domain/knowledge.py`): `AutoReferenceFinding(code, met, detail)`, 조건 여덟 `AUTO_REFERENCE_CODES` —
  `candidate`(후보다) · `reference`(효력 참고) · `observational_kind`(운영 사실·알려진 문제) · `two_runs`(서로 다른 근거 실행
  둘 이상) · `verified_run`(그중 종료 코드 0 명령이 있는 검증·분석 실행) · `observed_repository`(저장소 범위 = 관측한 저장소) ·
  `no_contradiction`(반증 관계 아님·이 항목을 반증하는 후보 없음·열린 충돌 없음) · `adoption_clear`(채택 확인 막음 없음).
  `auto_reference_check(candidate, evidence_runs, contradicting_candidates, open_conflicts, adoption_blocked_codes)` →
  항목 목록, `auto_reference_ready`(전부 충족), `auto_reference_summary` → `{ready, met, unmet, findings}`. 고정 사유
  `AUTO_REFERENCE_REASON`. 계산만 하고 활성화하지 않는다.
- **조회**(`controller/repository.py`): `auto_reference_check_for(knowledge_id)` — 근거 실행 = 출처 실행 + 근거 행
  (`supports`·`duplicate`)의 실행을 실행 id 로 중복 제거, 각 실행의 목적과 명령 기록(`run_command.exit_code == 0` 하나라도);
  이 항목을 대상으로 한 `contradicts` 후보 수; 열린 충돌 수; `adoption_check_for` 의 막는 코드 → 순수 함수. 반환에 `evidence_runs`
  (`run_id`·`purpose`·`ok_command`). `knowledge_view` 의 후보 항목에 `auto_reference`(후보가 아니면 `null`),
  `knowledge_registrations_view` 의 지금도 후보인 등록 행에 `auto_reference`. 조건 결과는 저장하지 않는다.
- **한 번에 활성화**: `activate_ready_knowledge(project_id, actor, knowledge_ids)` — 대상은 `knowledge_ids`(화면이 본 것, 다른
  Project 의 항목이면 409) 또는 이 Project 의 후보 전부. 각각 조건을 다시 계산해 충족인 것만 `activate_knowledge(obligation =
  reference, reason = 고정 사유, extra_adoption = {auto_reference: {met, evidence_runs}})` — 채택 확인을 그대로 지난다. 충족이
  아니면 `skipped(not_ready, unmet)`, 거부(`KnowledgeAdoptionRefused`·`ConflictError`)면 `skipped(refused, 코드)`. 항목마다
  독립이다. `activate_knowledge` 에 `extra_adoption` 인자(`adoption` 에 합침, 2,000 자 상한은 `register_knowledge` 그대로).
- **API**(`controller/api.py`): `GET /api/knowledge/{id}/auto-reference`(확인만), `POST /api/projects/{id}/knowledge/activate-ready`
  (`{actor, knowledge_ids | null}` → `{project_id, by, activated, skipped}`, 200 — 하나가 거부돼도 나머지는 됐다).
- **화면**: 프로젝트 규칙 화면(`ProjectRules.tsx`) — 후보 절 머리의 조건 안내와 `조건 충족 n건 한 번에 활성화(사람의 결정)`
  버튼(`rules-activate-ready`, `data-count`, 0 이면 비활성, 화면이 `ready` 로 보이는 id 만 보냄), 결과 줄(`rules-activate-ready-result`),
  후보 행의 배지(`rule-auto-{key}`, `data-ready`: "자동 활성 조건 충족 — 한 번에 활성화 대상(사람의 결정)" / "미충족: 남은 조건"),
  펼친 상세의 조건 여덟 목록(`rule-auto-list-{key}`, `data-met`), 채택 기록 줄에 "자동 활성 조건 충족(n) 을 사람이 한 번에 활성화 —
  근거 실행 n건", 머리 안내를 반자동으로. 대화 후보 카드(`ProgressCards.tsx`)의 등록 행 배지(`knowledge-candidate-auto-{index}`),
  관리 화면 지식 패널(`KnowledgePanel.tsx`)의 후보 행 배지(`knowledge-auto-{key}`)와 안내. `api.ts` 의 `KnowledgeAutoReference`·
  `KNOWLEDGE_AUTO_REFERENCE_LABEL`·`KnowledgeActivateReadyResult`·`knowledgeApi.autoReference/activateReady`·`KnowledgeAdoption.auto_reference`.
- **스키마·Runner·지시문·시험 도구**: 바꾸지 않았다(v24 그대로, 가짜 codex 표지 추가 없음 — `HADS_FAKE_CANDIDATE` 두 대화가
  같은 내용을 내어 `duplicate` 근거로 근거 실행 둘이 된다).

## 2. 성공 기준 근거

| 기준 | 근거 (`tests/test_knowledge_extraction.py` 등) |
|---|---|
| AC-1 | `test_the_auto_reference_conditions_are_all_or_nothing_and_each_one_can_fail_alone`(전부 충족 → `ready`·`met` 8; 후보 아님·필수·결정/제약 종류·실행 하나·검증/분석 아님·종료 코드 0 없음·프로젝트 범위·다른 저장소·관측 없음("관측 문맥이 없다")·반증 관계·반증 후보·열린 충돌·채택 막음을 각각 하나씩 깨면 그 코드만 `unmet`; 검증 둘 중 하나만 종료 코드 0 이어도 충족, 분석 실행도 충족; 여럿이 깨지면 표 순서로 전부) |
| AC-2 | `test_a_candidate_is_ready_only_with_two_runs_and_is_activated_only_when_a_human_clicks`(검증 실행 하나 → K-001 `unmet == [two_runs]`·근거 실행 `[(verification_run, True)]`; 둘째 대화의 같은 내용 → 근거 실행 2 → `ready`·`met` 8·**상태는 후보 그대로**) |
| AC-3 | 같은 시험(필수 제안 K-002 `[reference, two_runs]`, 프로젝트 범위 K-003 `[two_runs, observed_repository]` → 뒷받침 뒤 `[observed_repository]`, 결정 종류 K-004 `[observational_kind, two_runs]`, 반증 후보 K-005 → K-001 `[no_contradiction]`·K-005 `[two_runs, no_contradiction]` → 무효 뒤 K-001 `ready`, 열린 충돌 → K-001 `[no_contradiction, adoption_clear]` → 해소 뒤 `ready`, 논의 응답의 제안 K-006 `[two_runs, verified_run, observed_repository]`·"관측 문맥이 없다") |
| AC-4 | 같은 시험(`activate-ready` → K-001 만 v2 `active`·`reference`·`user_decision`·`repository`/`primary`·활동 `verification` 그대로·사유 `AUTO_REFERENCE_REASON`·`adoption.by = tester`·`adoption.auto_reference.met` 8·`evidence_runs` 2; 나머지 `skipped(not_ready, unmet)`; `knowledge_ids = [K-002]` 면 그것만 보고 K-001 은 그대로; 활성 뒤 `auto_reference = null`; 다시 불러도 활성화 없음) |
| AC-5 | 같은 시험(활성화 함수를 끼워 넣어 K-001 을 `open_conflict` 로 거부 → `skipped(refused, [open_conflict])`, 나머지 `not_ready`, 200 — 같은 호출 안에서 조건 계산과 채택 확인 사이에 끼어들 실제 경로가 없어 끼워 넣기로 봤다) |
| AC-6 | 같은 시험(넷째 대화의 검증 실행에 K-001 v2 가 `knowledge_reference`·`supporting`·Manifest `provided` v2 `active`; 필수 제안 K-002 는 `reference` 미충족이라 이 길로 활성이 되지 않는다) |
| AC-7 | AC-2·3 시험(`knowledge_view` 항목의 `auto_reference`·`findings` 코드 순서, `knowledge_registrations_view` 후보 행의 `auto_reference`, `GET auto-reference` 가 같은 값, 활성 항목 `null`). 스키마 v24 그대로(`schema.sql`·`db.py` 미변경), 조회에 더한 것은 코드·실행 id·수뿐 |
| AC-8 | 브라우저 `tests/test_web_shell.py::test_a_candidate_seen_by_two_runs_shows_the_ready_badge_and_a_human_activates_it_at_once`(3절) |
| AC-9 | 코드 대조(`activate_ready_knowledge` 호출은 `api.py` 끝점뿐, 진입 검사·정책·권위 코드·DB CHECK 미변경), AC-4·6 시험(효력 참고만, 필수 제안 미충족), 기존 P4-06·07·UI-04a 시험 전부 통과(3절) |

## 3. 검증

### 자동 시험

최종 `pwsh -File scripts\run-tests.ps1` → 웹 빌드 성공, 웹 단위 **21** 통과, pytest **696 통과·2 건너뜀·0 실패**(11분 17초,
기준선 693 통과·2 건너뜀 에서 +3), P1 계약 unittest **18** 통과, "전체 시험 통과". 경고 2건은 기존 deprecation 이다. 새 pytest
3건 = `test_knowledge_extraction.py` 2(순수 `test_the_auto_reference_conditions_are_all_or_nothing_and_each_one_can_fail_alone`,
서버 `test_a_candidate_is_ready_only_with_two_runs_and_is_activated_only_when_a_human_clicks`) + 브라우저 1
(`test_web_shell.py::test_a_candidate_seen_by_two_runs_shows_the_ready_badge_and_a_human_activates_it_at_once` — 실제 제어부·
실제 Runner 프로세스·가짜 codex·설치된 Edge: 첫 대화의 후보 카드 배지 "미충족(서로 다른 실행 둘 이상의 근거)" → 둘째 대화의
같은 후보(근거) → 규칙 화면 배지 "충족"·상태 후보·버튼 "조건 충족 1건"·조건 목록 8 전부 충족 → 클릭 → 결과 "활성화 1건 —
K-001 v2"·활성 참고 절·버튼 0건 비활성·채택 기록 "사람이 한 번에 활성화"·배지 없음, 서버 v1 `superseded`/v2 `active`·
`user_decision`·`reference`·고정 사유·`adoption.auto_reference` 8/2).

건너뜀 2건은 `tests/test_migration.py` 의 v1·v2 이행 시험(옛 스키마 커밋 창 — S-027 부터 그대로, 제품 무관). 기존 시험은
바꾸지 않았고 전부 통과했다.

**기준선**(S-029 시작, `scripts\run-tests.ps1`): 웹 빌드 성공, 웹 단위 21, pytest 693 통과·2 건너뜀·0 실패(10분 38초), P1 계약
18 — S-028 인계 수치와 같다. **주의:** 기준선 실행이 41% 쯤일 때 서버 코드(`domain/knowledge.py`·`controller/{repository,api}.py`)
를 고치기 시작해, 하위 프로세스를 띄우는 마지막 시험들(브라우저·재시작·Runner 프로세스)은 고친 코드로 돌았을 수 있다. 고친
것은 추가 전용(새 함수·새 끝점·조회의 새 칸)이라 기존 시험의 의미가 바뀌지 않았고, 최종 실행이 같은 기존 시험 693건을 다시
전부 통과했다 — 기준선 수치는 변경 전 상태로 본다.

새 시험을 따로 돌린 첫 회차에서 둘이 실패했다 — 순수 시험의 도우미가 "충족" 경우를 "미충족" 단언으로 부른 것(시험 결함),
서버 시험이 옛 후보 버전(`superseded`)에 DB CHECK 위반을 기대한 것(옛 버전에는 해당 CHECK 가 없다 — 시험의 가정 오류, 필수
승격 없음은 `reference` 미충족·활성 버전의 효력으로 대신 본다), 브라우저 시험이 절을 옮긴 뒤에도 펼쳐진 항목을 다시 접은 것
(펼침 상태는 항목 키로 기억된다 — 시험 결함). 셋 다 시험을 고쳤고 제품은 바꾸지 않았다.

### 실제 CLI (선택 사항 — 하지 않았다)

plan 5절·DEVELOPMENT 1.12절대로 **실제 codex 라이브는 선택 사항**이며 이 세션은 하지 않았다. 이유: 실제 codex 는 P4-07 의 두
회차 네 작업 실행에서 후보를 남기지 않았고, 정리 응답의 제안(K-001·K-002)은 관측 문맥이 없어 조건 (4)를 만족하지 못한다 —
근거 실행 둘을 실제 codex 로 만들 수 있다는 근거가 없다. 조건 계산·표시·한 번에 활성화는 **제품 규칙**이며 가짜 CLI(실제
제어부·실제 Runner 프로세스·설치된 Edge)로 고정했다. 실제 codex 로 후보가 근거 둘을 갖는 경우가 생기면 그때 관찰로 적는다.

## 4. 경계와 남은 것

- **클릭 없는 활성화는 없다.** 조건 충족은 표시이며 활성화는 사람의 결정(새 버전 `user_decision`)이다. 한 번에 활성화는 효력
  `reference` 만 만든다 — AI 제안은 어떤 경로로도 활성 필수가 되지 않는다(DB CHECK).
- **명령·종료 코드는 자기보고다.** 조건 (3b)는 실행의 명령 기록을 볼 뿐 실행 사실을 증명하지 않는다(DEVELOPMENT 9절).
- **논의 응답의 제안은 조건 (4)를 만족하지 못한다** — 관측 문맥이 없다. 사람이 항목의 활성화 폼에서 활성화한다(P4-07 라이브의
  K-001·K-002 가 이 경우). 근거 실행의 관측으로 대신하는 것은 조건을 넓히는 일이라 하지 않았다.
- **같은 내용의 재보고(`duplicate`)도 근거 실행으로 센다.** 같은 뜻의 다른 문장은 아니다(원문 해시).
- **조건 결과는 저장하지 않는다.** 조회 때 계산한다(후보마다 실행·명령 조회 — 후보가 많아지면 비용을 본다). 활성화 때 충족
  항목·근거 실행 id 만 `adoption` 에 남는다.
- **화면이 본 것만 활성화한다**(`knowledge_ids`). 목록을 본 뒤 새로 충족된 후보는 다음에 다시 본다.
- 조건의 Project 설정화·완전 자동·독립 AI 검토는 넣지 않았다. 완전 자동은 후보가 실제로 쌓이면 사용자에게 다시 묻는다.
