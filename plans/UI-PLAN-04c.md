# UI-PLAN-04c

UI-04(남은 업무·화면 연결)의 **셋째 하위 plan** — 활성 목적·Profile 이행(D-86) + 실행시간 합계(D-88) + 외부 편집·작업 PC
열기(D-89). 범위는 **사용자 결정(2026-09-24, S-030): 남은 네 항목을 두 단계로 묶는다 — UI-04c = D-86 + D-88 + D-89,
UI-04d = D-84 + D-77**. 기준: 설계 v0.8 2차 / D-01~90 / **D-86**(미완료 업무의 목적 확장·유형 변경 — 같은 대화·Case 의
의도/Profile 개정, 이전 기준·결정·증거·참조와 새 항목의 대응 보존, 누적 소비·실패·repair 초기화 없음, controlled·새 권한·
미결 판단 유지, 목적 선언만으로 조사 Profile 의 제품 쓰기 제한 우회 없음, 종료 뒤 수정은 새 Case) / **D-88**(시간 한도
선택 시 실행시간 합계를 기본으로 — 논의·업무·재시도·종료 후 설명의 실제 실행시간 합계, 사람 대기 제외, 병렬 각각 합산,
경과시간은 별도, 기존 한도·소비의 의미 소급 변경 없음, 즉시 강제 종료 약속 없음) / **D-89**(직접 파일 편집은 외부 편집기 —
작업 PC 이름·작업공간 경로·경로 복사, 폴더·편집기 열기는 지원을 확인한 환경의 작업 PC 만, 다음 AI 실행 전 외부 변경 확인·
보존, 새 쓰기 권한 없음) / [대화 중심 UI](../ui-conversation-design.md) 4.1·5.1·10.1절 / [case-profiles](../case-profiles.md)
5절·수용 10 / [review-acceptance-matrix](../review-acceptance-matrix.md) AC-07·51·53·54. 선행: P4-03(Profile 정의 v2·
목적 의무·혼합 목적 — 선언 목적은 의도에 있다), P4-05(진행기·의도 동의 카드), UI-03(준비 단계의 AI 해석 업무화), UI-04a
(결정 사항 패널), UI-04b(상세 설정 탭·예산 폼), UI-02(Runner 제어 루프·heartbeat 제어), P3-R2(작업공간·트리 지문).
세션 S-031.

기준선(S-031 시작, 변경 전, `scripts\run-tests.ps1`): 5절 끝에 있다. 시작 상태 `main`/`84252ce`, 작업 트리 clean,
`git fetch` 뒤 `origin/main` 과 같음.

범위는 **UI-04c 하나**다. UI-04d(대화 검색 D-84, 미커밋 포함 시작 D-77)·P5·P6 은 넣지 않는다.

## 0. 제품 판단 — 새로 내리지 않는다

이 plan 이 정하는 것은 D-86 의 **기술 이행 모양**(개정 기록·항목 유지·기준 승계·진행기 연결·해석 경로), D-88 의 **화면
기본값과 표시**(지표 자체는 이미 있다), D-89 의 **열기 명령 경로와 외부 변경 확인 지점**이며 D-86·88·89 와 case-profiles
5절 안이다. S-030 인계가 "새 의도 버전의 동의 규칙·진행 중 실행의 처리에 새 제품 판단이 필요하면 그 plan 에서 묻는다" 고
남긴 두 가지는 **기존 정책을 그대로 적용해 새 판단을 만들지 않는다**(아래) — 사용자가 다르게 정하면 인계에서 바꾼다.

상세 설계 선택(제품 정책이 아니다, 9절에도 적는다):

- **개정은 기록이며 되돌림은 또 하나의 개정이다.** `case_profile_revision` 표(이력)에 `from → to`·유지 목적·추가 목적·
  결정 주체·근거를 남기고 Case 행의 `profile`·`kind` 를 바꾼다(`profile_source = revised`). 이전 의도 버전·기준·판정·
  결정·증거·예산 예약·시도 수·위임 근거·확인 지점은 **어느 것도 지우거나 바꾸지 않는다.** 잘못 바꿨으면 이전 Profile 로
  다시 개정한다(개정 n+1).
- **이전 Profile 의 의미 항목은 새 문서에 남는다("유지 항목").** RCA → defect_fix 로 바꾸면 새 의도 버전의 항목은
  공통 여섯 + defect_fix 다섯 + **RCA 다섯(유지)** 이다. 그래서 `cause_questions` 를 가리키던 기준의 `relates_to` 가
  대상을 잃지 않는다(P4-03 이 미룬 문제의 답). 유지 항목은 개정 행에 적히고 그 뒤 의도 버전마다 `retained_fields` 로
  기록된다. 옛 버전은 자기 항목 집합으로 읽는다(버전 행에 `profile`·`profile_version`·`retained_fields` — 지금은 Case
  행만 보므로 개정 뒤 옛 버전이 새 Profile 의 항목을 빠뜨린 문서로 읽힌다).
- **유지 항목의 기준은 그 항목을 가진 Profile 의 의무다.** `cause_questions` 기준의 도출 의무는 defect_fix 계약의 주
  의무(`restoration`)가 아니라 RCA 계약의 `cause` 다(`derive_obligation` 의 소유 Profile 규칙). 그래서 기준 지문이
  같고(P4-02 `_criterion_fingerprint`), 항목이 바뀌지 않았으면 판정이 승계된다(`carried_from`). 승계 규칙 자체는
  P4-02 그대로다 — 새 대응표를 만들지 않고 **같은 키·같은 지문**이 대응이다. 개정 조회가 "이전 기준 → 새 기준(승계/
  재검사/없음)" 의 대응을 도출해 보인다.
- **이전 목적은 기본으로 유지한다("목적 확장").** 개정은 `keep_previous_objectives`(기본 참)로 이전 Profile 의 필수
  의무(예: `cause`)를 **새 의도 버전의 선언 목적(`objectives_json`)에 합친다** — P4-03 이 선언 목적을 Profile 이 아니라
  의도에 둔 이유가 바로 이것이다. 그러면 `required_objectives` 가 `cause ∪ restoration` 이 되어 "원인 확정+수정은 양쪽
  충족"(AC-07)이 기존 완료 계약으로 판정된다. 유형 정정(잘못 분류)은 사람이 폼에서 유지를 끄는 것이며 AI 해석 경로는
  항상 유지다.
- **새 의도 버전의 동의 규칙은 기존 그대로다.** 개정 뒤 진행기가 의도 재작성 실행(AI)을 만들고 그 버전은 QG-01·질문·
  material delta·**사람의 의도 동의**(`agreed_current`)를 지나야 다음으로 간다 — P4-05 의 의도 단계 그대로이며 "같은
  의미의 변경을 다시 승인받는 별도 절차"(case-profiles 5절)를 더한 것이 아니다. 새 제품 판단이 아니다.
- **진행 중 실행이 있으면 개정을 거부한다(409 `runs_unfinished`).** 끝나지 않은 실행의 고정 문맥과 결과가 어느 버전의
  것인지 모호해지지 않게 한다. 업무 단계의 사용자 메시지는 사람 대기에서만 열리므로(P4-05) AI 해석 경로는 이 조건에
  걸리지 않는다. 새 제품 판단이 아니라 "실행 사이 잠금 유지" 의 적용이다.
- **AI 해석 경로는 UI-03 과 같은 모양이다.** 업무 단계 논의 응답에도 해석 규칙을 붙이되 종류는 `discussion`(기본) /
  `profile_change`(같은 문제에 대해 목적을 더하거나 유형을 바꾸라고 **명시적으로** 요청) 둘이다. 위임 근거는 사용자
  메시지 원문(`request_message_id`)이고 해석 글은 근거가 아니다(UI-03 규칙). 다른 문제의 새 작업·질문·동의·제한 표명은
  `discussion` 이며 애매하면 `discussion` 이다. 규칙을 좁게 두는 이유도 UI-03 과 같다(오판의 비용이 비대칭).
- **v1·Profile 미기록 Case 는 개정하지 않는다**(409 `profile_definition_not_current`). 완료 계약이 없는 Case 에 개정을
  허용하면 v2 규칙이 그 Case 에 들어간다(D-62). 지금 만들어지는 모든 Case 는 v2 다.
- **D-88 은 지표를 새로 만들지 않는다.** `execution_seconds` 는 이미 실행별 `assigned_at ~ finished_at` 의 Case 합계
  (논의·업무·재시도·종료 후 설명 실행 모두, 병렬 각각 합산, 대기열 대기 제외, 실행 안에 사람 대기는 없다)이고
  `elapsed_seconds` 는 이미 `Case.created_at ~ 지금` 이다. 두 지표의 뜻을 바꾸지 않는다(소급 없음). 이 plan 은 (1)
  시간 한도를 걸 때 화면이 실행시간 합계를 **기본으로 제안**하고, (2) 두 값을 화면에 사람 말로 보이고, (3) 재배정 뒤 옛
  세대의 시간 행이 벽시계로 영원히 자라는 계측 결함을 고친다(옛 세대 행은 재배정 시점까지 관측한 값으로 `unresolved`).
  Runner 준비·보고 시간이 실행시간에 포함되는 것은 지금 지표의 정의이며 그대로다.
- **D-89 열기는 Runner 명령이다.** 브라우저는 경로를 열지 못하고 작업 PC 가 다를 수 있다. 화면의 요청은 제어부 표
  (`workspace_open_request`)에 남고 Runner 가 heartbeat 제어(UI-02 의 `runner_controls`)로 받아 **자기 소유 worktree 인
  경로만** 연다(브라우저가 준 경로를 열지 않는다 — 경로는 `case_workspace` 행에서 온다). 지원은 Runner 가 능력 행으로
  보고한다(`runner-host/desktop`: `open_folder` = Windows `os.startfile`, `open_editor` = PATH 의 `code`). 확인되지 않은
  환경·미연결 PC 는 요청을 거부하고 화면이 사유를 보인다. 열기는 쓰기 권한이 아니다.
- **외부 변경 확인은 다음 쓰기 실행 직전 Runner 에서 한다.** 제어부는 트리를 보지 못한다. 배정에 그 저장소의 **직전
  실행이 남긴 트리 지문**(`workspace_effect_json.tree_digest_after`)을 실어 주고 Runner 가 CLI 를 부르기 전 관측한
  지문과 대조해 실행 효과에 `external_change_before_run` 을 남긴다. 보존은 worktree 를 초기화하지 않는 기존 규칙이다
  (FR-26). 조회의 `unexpected_external_change` 도 지문을 함께 비교한다(지금은 HEAD·항목 수만 비교해 같은 파일의 내용
  수정을 놓친다).

## 1. 현재 구현과 차이 (코드 대조)

1. **Profile 은 Case 행에만 있고 변경 경로가 없다.** `case.profile/profile_version/profile_source/kind`, 최초 배정은
   `case_work_start`(한 행) — 표 주석이 "업무 단계의 Profile 변경은 D-86 이며 이 표가 아니다" 라 적는다. `start_work`
   (`controller/repository.py:11896`)는 업무 단계 Case 를 `CASE_NOT_IN_DISCUSSION_STAGE` 로 거부한다.
   `tests/test_policy.py:867` 은 `PUT /api/cases/{id}/profile` 이 없음을 단언한다.
2. **의도 버전은 Profile 을 모른다.** `intent_version` 에 profile 컬럼이 없고 `list_intent_fields`·`get_intent_detail`·
   `required_intent_fields`·`completion_contract`·`completion_meaning`·`assignment_payload` 가 전부 Case 행을 본다.
   `apply_intent_structure`(`:1861`) 는 항목 집합이 **정확히** Case 의 필수 항목과 같아야 받는다. `intent_doc.compose`
   의 `_field_name` 은 이 문서의 `field_order` 밖 `relates_to` 를 거부한다. `structure()` 는 이전 문서에만 있던 항목을
   보고하지 않는다.
3. **의무 도출은 현재 계약뿐이다.** `completion_meaning.derive_obligation` → `contract.obligation_for_field` → 대응표에
   없는 항목은 주 의무. 기준 지문에 의무가 들어가므로 계약이 바뀌면 지문이 바뀌어 승계되지 않는다.
4. **업무 단계 응답은 해석하지 않는다.** `assignment_payload` 는 `conversation_stage` 를 주지만 Runner
   (`_produce_discussion_reply`)는 준비 단계·종료 Case 만 해석하고 `prompts.build` 도 그때만 규칙을 붙인다.
   `conversation_interpretation.kind` 는 CHECK 로 `discussion|work_request` 뿐이며 `objectives` 자리가 없다.
   `request_processor.apply_interpretation` 은 `start_work` 만 부른다. 두 시험(`test_request_processor.py:506`,
   `test_work_progressor.py:545`)이 "업무 단계 응답에 해석 없음" 을 고정한다.
5. **진행기에 Profile 변경 훅이 없다.** `work_flow._intent_phase` 는 최신 버전이 없을 때만 초안 실행을 만든다.
   `_investigation` 은 Case 의 현재 Profile 로 판단하고 `attempts` 는 초기화되지 않는다(그대로 둔다).
6. **화면.** 결정 사항 패널 "업무" 절이 `work_start.profile`(최초)만 보인다. `api.ts` 의 `IntentVersion` 에 Profile 이
   없다. `case_not_in_discussion_stage` 문구가 "목적·유형 변경은 다른 경로다" 라 적혀 있다.
7. **D-88.** `BudgetMetric` 에 `execution_seconds`(합계)·`elapsed_seconds`(Case 시계)가 있고 `_metric_exposure` 가 둘을
   계산한다. 화면(`CaseSettings`·`ProjectSettings`·`PolicyPanel`)의 예산 폼은 기본 지표가 `run_count` 이고 지표 이름을
   날것으로 보이며 시간 값을 어디에도 보이지 않는다. `bump_generation`(`:1584`) 은 옛 세대의 `HELD` 행을 두고 새 세대
   예약을 잡으며 `_settle_budget` 은 현재 세대만 정산한다 → 옛 세대 시간 행이 현재 `assigned_at` 기준으로 계속 자란다.
8. **D-89.** `case_workspace` 에 `runner_id`·`worktree_path` 가 있고 `list_workspaces` 가 준다. `ReviewPanel` "코드 변경"
   절에 작업 PC·경로·`경로 복사` 가 있으나 (a) 변경 실행이 있을 때만 그리고 (b) PC 를 `ws.runner_id` 가 아니라 대화의
   연결 Runner 에서 찾는다. 열기는 없다("아직 지원하지 않는다"). Runner 능력은 도구별 행뿐이고 OS·데스크톱 능력 행이
   없다. 트리 지문은 쓰기 실행 전후에 `workspace.observe` 로 계산돼 `workspace_effect_json` 에 남지만 실행 사이 대조는
   조회 때 HEAD·항목 수뿐이다. Runner 명령은 heartbeat 응답의 `controls`(중단·잔류 재확인)와 열람 요청 표 두 모양이다.

## 2. 범위

| 넣는 것 | 넣지 않는 것 (담당) |
|---|---|
| **D-86 서버**: 스키마 **v26** — `case_profile_revision`(이력), `intent_version.profile/profile_version/retained_fields_json`(기존 행은 Case 값으로 채움 — 당시 사실), `conversation_interpretation` 재구성(`kind` 에 `profile_change`, `objectives_json`). `ProfileSource.REVISED`, `InterpretationKind.PROFILE_CHANGE`. `revise_profile`(거부: 종료·준비 단계·v1·같은 Profile 에 추가 목적 없음·끝나지 않은 실행), 유지 항목·유지 목적의 계산, 버전별 항목 집합 조회, `derive_obligation` 소유 Profile 규칙, 구조 보고의 필수 항목 = 현재 Profile + 유지 항목, `objectives_json` 에 유지 목적 합치기, `intent_state.profile_stale`, 진행기의 의도 개정 실행(`intent_revision`), 개정 조회(대응 목록) | 새 완료 규칙(P4-03 계약 그대로). 위임 근거·예산·시도 수·확인 지점·저장소 선택의 변경(없음). 조사 Profile 의 제품 쓰기 가드 완화(없음 — 진입 검사 그대로). Profile 정의 v3(없음) |
| **D-86 해석**: 업무 단계 논의 응답의 해석 규칙(`discussion`/`profile_change`), Runner 의 분리·보고, 처리기의 적용(`revise_profile`, 근거 = 사용자 메시지), 가짜 codex 표지 `HADS_FAKE_PROFILE_CHANGE` | 종료 Case 의 규칙(P4-05 그대로 — 수정 요청은 새 대화). 준비 단계 규칙(UI-03 그대로) |
| **D-86 API·화면**: `POST /api/cases/{id}/profile-revisions`, `GET /api/cases/{id}/profile-revisions`; 결정 사항 패널 "업무" 절의 현재 Profile·개정 이력·대응·개정 폼(Profile·추가 목적·이전 목적 유지·사유), 대화 타임라인 표식, `IntentVersion` 형 확장, 라벨 | 의도 초안 화면의 목적 입력(P4-03 그대로 없음). 관리 화면 변경(없음) |
| **D-88**: `BUDGET_METRIC_LABEL`(사람 말), 예산 폼의 "시간 한도 추가"(기본 `execution_seconds`)·지표 설명, 상세 설정 탭의 시간 절(실행시간 합계·경과시간, 확정/진행 중/미확정, `complete`), 입력창 요약 라벨, 관리 화면 라벨; `bump_generation` 의 옛 세대 정산(`SettleSource.REASSIGNED`)과 `_metric_exposure` 의 옛 세대 보호 | 새 지표(없음). 시간 도달 자동 중단(없음, `enforced_no_absolute_cap` 그대로). 재배정 자체의 정산 의미(P6-03) |
| **D-89**: Runner 데스크톱 능력 행(`runner-host`/`desktop`: `open_folder`·`open_editor`), `workspace_open_request` 표(v26), `POST /api/cases/{id}/workspaces/{repository_id}/open`·`POST /api/runner/open-requests/{id}/result`, heartbeat 제어 `open_requests`, Runner 의 소유 확인·열기·보고(주입 가능한 opener), 요청 만료(60초), `workspace_view` 의 PC·연결·지원·요청 이력; 배정의 `last_tree_digest` 와 Runner 의 실행 전 대조(`external_change_before_run`), 조회의 지문 비교; 결과물 패널의 작업공간 절(항상, PC 는 `ws.runner_id`, 복사·열기·지원 상태·외부 변경 표시) | 앱 내부 편집기·diff 본문 열람(없음). 임의 경로 열기(없음). 읽기 전용 실행의 트리 관측(없음 — 9절). 미커밋 포함 시작(UI-04d) |
| 자동 시험(순수·서버·처리기+진행기·이행·웹 단위·브라우저 2), 문서 | 실제 codex 라이브는 선택 사항(3·5절 — 해석 규칙의 실제 AI 판단은 라이브에서만 보이지만 시스템 규칙은 가짜 CLI 로 같은 경로를 지난다) |

## 3. 설계

### 3.1 D-86 — 순수 규칙 (`domain/profiles.py`·`domain/intent_doc.py`·`domain/completion_meaning.py`·`domain/conversation.py`)

- `profiles.FIELD_OWNER: dict[str, CaseProfile]`(의미 항목 → 그 항목을 가진 Profile, v1 정의에서 도출).
  `profiles.retained_fields(previous: list[tuple[profile, version]], current: (profile, version)) -> tuple[str, ...]`
  — 이전 Profile 들의 의미 항목 중 현재 Profile 에 없는 것을 **이전 순서대로**. `profiles.field_order(profile, version,
  retained=())` 가 공통 여섯 + 현재 의미 항목 + 유지 항목을 돌려준다(`required_fields` 도 같은 인자).
- `completion_meaning.derive_obligation(contract, relates_to, reported, version=None)`: 보고값 우선(그대로). 없으면
  `relates_to` 의 소유 Profile 이 있고 그 Profile 의 같은 판 계약이 `contract` 와 다르면 **그 계약**의 대응으로 도출,
  아니면 지금처럼 `contract.obligation_for_field`. 출처는 그대로 `derived_from_field`.
- `intent_doc.compose(..., retained_fields=())`: `field_order = profiles.field_order(profile, version, retained)`;
  문서에 `retained_fields` 를 적는다(**DOC_VERSION 6** — v1~5 문서는 `[]` 로 읽는다). `_criterion_obligation` 이
  `version` 을 넘긴다. `structure()` 는 그대로다(유지 항목이 문서 안에 있으므로 이전 문서의 항목이 사라지지 않는다).
- `conversation.parse_interpretation`: `profile_change` 는 Profile 이 있어야 하고 `objectives`(선택)는
  `CriterionObligation` 값 목록이어야 한다(아니면 `invalid`). `Interpretation.objectives`. `interpretation_refusal` 은
  `discussion` 만 `not_a_work_request` 로 거른다(`profile_change` 는 시도).

### 3.2 D-86 — 저장 (`controller/schema.sql` v26, `controller/db.py`)

```
case_profile_revision (id PK, case_id FK, revision, from_profile, from_profile_version, to_profile, to_profile_version,
                       retained_fields_json(<=400), carried_objectives_json(<=200), added_objectives_json(<=200),
                       decided_by person|ai_interpretation, actor, request_message_id NULL, interpretation_run_id NULL,
                       reason_summary(<=200), intent_version_id_before NULL, created_at, UNIQUE(case_id, revision))
intent_version + profile, profile_version, retained_fields_json   -- 기존 행: Case 의 profile/version, retained NULL
conversation_interpretation 재구성: kind IN ('discussion','work_request','profile_change'), objectives_json(<=200),
                       applied CHECK: kind IN ('work_request','profile_change') AND profile IS NOT NULL ...
workspace_open_request (id PK, case_id, repository_id, runner_id, target folder|editor, requested_by, state
                       pending|done|failed|expired, result_reason(<=200), requested_at, delivered_at, finished_at)
```

`SCHEMA_VERSION = 26`. `case.profile_source` 에 CHECK 가 없어 `revised` 는 값만 더한다. 본문 컬럼 없음(데이터 경계
시험). 기존 의도 버전의 profile 채움은 **당시에 참이었던 사실**(변경 경로가 없었으므로 Case 의 값과 같다)이며 Profile
미기록 Case 는 NULL 그대로다.

### 3.3 D-86 — 저장 계층 (`controller/repository.py`)

- `revise_profile(case_id, *, profile, added_objectives, keep_previous_objectives, decided_by, actor, reason_summary,
  request_message_id=None, interpretation_run_id=None)`: 거부 — 종료(`case_already_closed`), 준비 단계
  (`case_not_in_work_stage` — 새 코드), Profile 미기록·v1(`profile_definition_not_current`), 같은 Profile 이고 추가
  목적 없음(`profile_revision_empty`), 끝나지 않은 실행(`runs_unfinished`), AI 해석이면 `start_work` 와 같은 메시지·
  요청·실행 검사. 한 트랜잭션: Case 행(`profile`·`profile_version = 현재판`·`kind`·`profile_source = revised`), 개정 행
  (유지 항목 = 이전 유지 ∪ 이전 Profile 의미 항목 − 새 Profile 항목, 유지 목적 = `keep` 이면 이전 유지 ∪ 이전 Profile
  필수 의무(계약 `requirements` 의 `when_field_filled` 없는 것), 추가 목적). **바꾸지 않는 것**: 위임 근거·예산·
  `case_progress.attempts`·확인 지점·저장소 선택·의도 버전·기준·판정·결정. 돌려주는 값은 `conversation_view`.
- `retained_intent_fields(case_id) -> tuple[str, ...]`·`carried_objectives(case_id) -> list[str]`(현재 개정 행들의 합).
  `required_intent_fields`·`case_profile`(`revisions`·`retained_fields`·`carried_objectives`·`source`)·`assignment_payload`
  (`intent_retained_fields`·`intent_carried_objectives`)·`submit_intent_draft`(API)가 쓴다.
- `create_intent_version` 이 버전 행에 Case 의 `profile`·`profile_version`·`retained_fields_json` 을 적는다.
  `list_intent_fields`·`get_intent_detail`(`profile`·`profile_version`·`retained_fields`·`required_fields`)은 **버전 행**을
  본다(NULL 이면 Case 값 — Profile 미기록 Case). `apply_intent_structure` 의 필수 집합 = `required_intent_fields(case)`
  (현재 Profile + 유지 항목); `objectives_json` = 보고된 목적 ∪ `carried_objectives`(합쳤으면 `objectives_source`
  없이 값만 — 선언은 개정 요청이 했다). `apply_success_criteria` 가 `derive_obligation(..., version=case 판)` 을 쓴다.
- `intent_state.profile_stale`: 최신 버전의 `(profile, profile_version, retained)` ≠ Case 의 값. `flow_state` 가 그대로
  넘긴다.
- `profile_revisions_view(case_id)`: 개정마다 위 값 + `request_message_seq` + `criteria_mapping`(개정 직전 버전의 기준마다
  `{key, summary, before_verdict, after: {id, verdict, carried}|null}` — 개정 뒤 첫 버전이 있을 때) + `intent_version_after`.
  `conversation_view.profile_revisions` 에 같은 목록(대응 없이 요약)과 `profile_source`.
- `record_interpretation`(결과 보고)이 `objectives_json` 을 적는다. `request_processor.apply_interpretation`: `kind ==
  profile_change` → `revise_profile(decided_by=AI_INTERPRETATION, keep_previous_objectives=True, added_objectives=
  parsed.objectives, request_message_id=opening, interpretation_run_id=run)`; 거부 코드는 해석 행의 `refusal` 로.
  종료 Case 는 그대로 `_move_to_follow_up`.

### 3.4 D-86 — 진행기·Runner

- `work_flow._intent_phase`: 최신 버전이 있고 `intent.profile_stale` 이면 `Step("run", "intent_revision", "목적·유형이
  바뀌어 의도를 새 버전으로 다시 쓴다", purpose=INTENT_AUTHORING, attempt_key="intent_revision")`. 그 다음은 기존
  순서(구조 대기 → 질문 → 답 반영 → QG-01 → delta → **동의** → 피드백 → 수준). `progress_run_inputs` 는 이 걸음에
  직전 의도 원문을 `previous_intent` 참조로 싣고(답 반영 재작성과 같은 방법) 지시 원문은 원래 업무 요청 + 개정 사유
  한 줄(짧은 요약)이다.
- 조사 → 제품 Profile 로 바뀌면 `_investigation` 이 거짓이 되어 준비 → 그래프 → 구현으로 간다(기존 분석 실행·판정은
  승계된 기준에 남는다). 제품 → 조사면 `attempts["analysis"]` 가 0 일 때만 분석이 돈다. 같은 조사 Profile 안의 목적
  추가는 분석을 다시 돌리지 않는다(9절).
- `runner/prompts.py`: `_intent_field_list(profile, version, retained)` 가 유지 항목을 "(이전 목적에서 이어지는 항목 —
  잃지 말고 갱신한다)" 절로 붙이고, `_intent_profile_note` 가 유지 목적을 "이 업무는 이전 목적 X 도 계속 충족해야 한다 —
  objectives 에 넣는다" 로 적는다. `parse_intent_draft(retained_fields=)`. `WORK_STAGE_INTERPRETATION_RULE`(업무 단계
  논의 응답, `conversation_stage == "work"` 이고 종료 아님): 블록 하나, `discussion` 기본, `profile_change` 조건·예·
  규칙(다른 문제의 새 작업은 discussion + 새 대화 권유, 애매하면 discussion, 이 실행에서 바꿨다고 말하지 않음).
- `runner/agent.py`: `_produce_discussion_reply` 가 `conversation_stage in (discussion, work)` 또는 종료면 해석을 뗀다.
  `_produce_intent_draft` 가 `assignment["intent_retained_fields"]` 를 파서·`compose` 에 넘긴다.
- `tests/fake_cli/fake_codex.py`: 마지막 메시지의 `HADS_FAKE_PROFILE_CHANGE=<profile>[:<obligation>,...]` → 업무 단계
  규칙을 받은 응답이 `{"kind":"profile_change","profile":...,"objectives":[...]}` 를 붙인다(없으면 `discussion`). 의도
  초안은 지시문의 항목 목록(유지 항목 포함)을 그대로 채운다(지금도 목록에서 읽는다 — 확인).

### 3.5 D-86 — API·화면

- `POST /api/cases/{id}/profile-revisions` `{profile, added_objectives: [..], keep_previous_objectives: true, actor,
  reason_summary}` → `profile_revisions_view`(409 = 거부 코드·문구), 기록 뒤 `progressor.on_human_input` 과 같은 방법으로
  진행기를 한 번 부른다(P4-05b 의 `PUT /progress/limits` 와 같다). `GET /api/cases/{id}/profile-revisions`.
- `web/src/api.ts`: `ProfileRevision`·`ProfileRevisionsView`·`caseApi.profileRevisions/reviseProfile`, `IntentVersion.
  profile/profile_version/retained_fields`, `ConversationView.profile_revisions/profile_source`, `OBLIGATION_LABEL`,
  `PROFILE_SOURCE_LABEL.revised`, 거부 문구(`case_not_in_work_stage`·`profile_revision_empty`·`runs_unfinished`·
  `profile_definition_not_current`), `case_not_in_discussion_stage` 문구를 "이미 업무 단계다 — 목적·유형 변경은 결정 사항
  패널의 개정" 으로.
- `shell/ReviewPanel.tsx` `Decisions` "업무" 절(`decisions-work`): 현재 Profile(`conv.profile`, `data-profile`) · 처음
  (`work_start`) · 개정 목록 `profile-revision-{n}`(from → to · 유지 목적 · 추가 목적 · 주체 · 근거 메시지 `#seq` 또는
  사유 · 대응: 기준 키마다 승계/재검사/대상 없음) · 개정 폼 `profile-revision-form`(Profile 선택 `revision-profile`, 추가
  목적 체크 `revision-objective-{o}`, 이전 목적 유지 `revision-keep`, 사유 `revision-reason`(필수), 제출 `revision-submit`,
  거부 문구 `revision-refusal`). 종료 Case 는 폼 대신 "종료 뒤 수정은 새 대화" 안내. "목표·기준" 절은 기준마다 승계
  표시(`carried_from`)를 덧붙인다.
- `shell/ConversationView.tsx`: 개정의 근거 메시지 뒤에 타임라인 표식 "목적·유형 변경됨 · A → B (이전 목적 유지)"
  (`profile-revision-marker`). 머리의 Profile 은 이미 `conv.profile`.

### 3.6 D-88 — 시간 (`domain/budget.py`·`controller/repository.py`·화면)

- `SettleSource.REASSIGNED`. `bump_generation`: 같은 트랜잭션에서 옛 세대의 `HELD` 행을 `UNRESOLVED` 로 닫는다 — 시간은
  `elapsed(old assigned_at, now)`(없으면 `None`), 정확 지표는 예약값 그대로, `settle_source = reassigned`. `_metric_exposure`:
  `HELD` 이면서 `generation < run.assignment_generation` 인 행(v26 이전 데이터)은 시간을 더하지 않고 `runs_unknown` 으로
  센다(`complete = False`). `RESERVATION_REASON[EXECUTION_SECONDS]` 에 합계의 정의 한 줄을 덧붙인다(기존 문구 유지).
- `budget_state` 의 `usage` 는 그대로(둘 다 이미 있다). 화면이 읽는다.
- `web/src/api.ts` `BUDGET_METRIC_LABEL`·`BUDGET_METRIC_NOTE`(실행시간 합계: "실행별 배정~종료 시각의 합 — 논의·업무·
  재시도·설명 실행, 병렬은 각각, 사람 대기 제외, 절대 상한 아님"; 경과시간: "대화 생성 후 벽시계 — 별도 선택"),
  `lib/duration.ts`(순수 `formatSeconds`). `CaseSettings` 예산 절: 시간 절 `case-time`(`case-time-execution` 값·확정/진행 중/
  미확정·`data-complete`, `case-time-elapsed`), `시간 한도 추가`(`case-budget-add-time` → 폼의 지표 = `execution_seconds`),
  지표 select 의 라벨·기본 순서(실행 수 다음에 실행시간 합계), 선택 지표의 설명. `ProjectSettings`·`PolicyPanel`·
  `Composer` 요약은 라벨만.

### 3.7 D-89 — 작업 PC (`runner/desktop.py` 새, `runner/agent.py`, `controller/repository.py`·`api.py`, 화면)

- `runner/desktop.py`: `capabilities()` → `runner-host`/`desktop` 행 둘 — `open_folder`: Windows 면 `verified`(source
  "os.startfile"), 아니면 `unsupported`; `open_editor`: `shutil.which("code")` 가 있으면 `verified`(source "code on PATH"),
  없으면 `unsupported`. `open_path(target, path)`: folder → `os.startfile(path)`, editor → `subprocess.Popen(["code",
  path])`. `default_capabilities()` 가 합친다. `RunnerAgent(opener=)` 로 주입(시험은 기록만 하는 opener).
- 제어부: `request_workspace_open(case_id, repository_id, target, requested_by)` — 작업공간 `ready`·`runner_id` 있음, Runner
  연결(`guard_runner_connected`), 그 Runner 의 `runner-host/desktop/open_*` 행이 `verified`(아니면 409 `open_unsupported`
  + 상태·근거) → `pending` 행. `runner_controls()` 에 `open_requests: [{id, case_id, repository_id, target, worktree_path,
  requested_at}]`(이 Runner 의 `pending`, 60초 안). 60초를 넘긴 `pending` 은 `expired` 로 닫는다(제어·조회 때).
  `report_open_result(id, runner_id, state done|failed, reason)`. `workspace_view` 의 workspace 마다 `runner: {runner_id,
  host, connection}`, `open_support: {open_folder: {state, source}, open_editor: {...}}`, `open_requests`(최근 5).
- Runner `handle_controls`: `open_requests` 마다 경로가 **자기 worktree 인지** 확인(`workspace.ownership(path) is
  SYSTEM_OWNED` 또는 `worktree_for(case, repo)` 와 같음) → 아니면 `failed`/`path_not_owned`; 능력이 없으면
  `failed`/`unsupported`; 열면 `done`; 예외는 `failed`/`repr`. 결과를 `POST /api/runner/open-requests/{id}/result`.
- 외부 변경: `assignment_payload` 의 `run["workspace"]["last_tree_digest"]`·`last_effect_run_id`(같은 Case×저장소의 가장
  최근 `workspace_effect_json` 이 있는 실행의 `tree_digest_after`; 없으면 `None`). `_execute_with_cli` 가 `watching` 일 때
  `before.digest` 와 대조해 `compose_effect(..., external_change_before_run=bool|None, external_change_basis_run_id)` →
  효과 JSON. `workspace_view` 의 `unexpected_external_change` 가 `tree_digest_after != tree_digest_before` 도 본다(HEAD·항목
  수 규칙 유지) 와 `external_change_before_run` 그대로 노출.
- API: `POST /api/cases/{id}/workspaces/{repository_id}/open {target, requested_by}` → 요청 행(409 문구 그대로);
  `POST /api/runner/open-requests/{id}/result`.
- 화면 `ReviewPanel` 결과 목록: 작업공간 절 `workspaces`(작업공간이 있으면 항상): 저장소 · 브랜치 · 작업 PC
  `ws-runner-{repo}`(host·연결) · 경로 `ws-path-{repo}` · `경로 복사` `ws-copy-{repo}` · `작업 PC 에서 폴더 열기`
  `ws-open-folder-{repo}` · `편집기 열기` `ws-open-editor-{repo}`(지원 `verified` 이고 연결일 때만 활성, 아니면 사유 문구
  `ws-open-support-{repo}`) · 최근 요청 결과 `ws-open-result-{repo}`(전달 대기/열림/실패 사유/만료). 실행 효과 행에
  "직전 실행 뒤 외부 변경 있음 — 보존됨(되돌리지 않음)" `effect-external-{run}`. 안내 문구를 "직접 편집은 외부 편집기로 —
  열기는 지원을 확인한 작업 PC 에서만, 외부 변경은 다음 쓰기 실행 전에 확인·보존" 으로. `api.ts` 형(`RepositoryWorkspace.
  runner/open_support/open_requests/runner_id`, `RunEffectRow.external_change_before_run`, `workspaceApi.open`).

### 3.8 문서

ui-conversation-design 4.1·5.1·10.1·12절(구현 기록), decisions D-86·D-88·D-89(구현 기록), case-profiles 5절·머리(구현
상태), README, DEVELOPMENT(1절 요약 표·1.11절·3절·4절·9절·인계), review-acceptance-matrix AC-07·51·53·54,
autonomy-budget-policy(시간 지표 문단에 D-88 표시).

## 4. 성공 기준

| AC | 기준 |
|---|---|
| AC-1 | **개정 기록**: 업무 단계 v2 Case(RCA)에 `defect_fix`+유지로 개정하면 Case 행이 `defect_fix`/`bug`/`revised`, 개정 행이 from/to·유지 항목(RCA 다섯)·유지 목적(`cause`)·주체·근거를 갖고, 위임 근거·예산 예약·시도 수·확인 지점·저장소 선택·이전 의도 버전·기준·판정·결정은 **바뀌지 않는다**(값 대조) |
| AC-2 | **거부**: 종료 Case·준비 단계·v1/미기록 Case·같은 Profile 에 추가 목적 없음·끝나지 않은 실행은 409 코드로 거부되고 아무 것도 저장되지 않는다. 종료 Case 의 수정 요청은 P4-05 그대로 새 대화다 |
| AC-3 | **항목 유지**: 개정 뒤 구조 보고의 필수 항목 = defect_fix 항목 + RCA 항목(유지)이고 그 집합이 아니면 거부; 옛 버전은 자기 항목 집합(RCA)으로 조회·게이트 검사된다(`required_field_missing` 없음); `intent_doc.compose` 가 유지 항목의 `relates_to` 를 받고 문서에 `retained_fields` 를 적는다(v6, v1~5 읽기 그대로) |
| AC-4 | **기준 승계·의무**: 유지 항목(`cause_questions`)을 가리키는 기준의 도출 의무가 `cause` 로 남고(defect_fix 계약의 `restoration` 이 아니다), 항목이 바뀌지 않았으면 새 버전의 같은 키 기준에 판정이 승계된다(`carried_from`); 바뀐 항목의 기준은 `needs_recheck`; 개정 조회의 대응 목록이 승계/재검사/대상 없음을 그대로 보인다. 개정 전 기준 행은 `superseded` 로 남고 승계된 판정의 옛 행은 그대로다(승계되지 않은 옛 판정이 `needs_recheck` 가 되는 것은 P4-02 규칙 그대로) |
| AC-5 | **완료 의미**: 유지 목적이 새 버전의 `objectives_json` 에 합쳐져 `required_objectives` 가 `cause ∪ restoration` 이며 수정만 충족하면 닫히지 않는다(AC-07 "양쪽 충족"); 유지를 끄면 `restoration` 만 요구된다. 기존 P4-03 시험 전부 통과 |
| AC-6 | **쓰기 가드**: 목적 선언만으로는 여전히 구현 실행이 열리지 않고(기존 시험), 개정 뒤에도 구현 실행은 준비 작업공간·저장소 쓰기 허용·controlled 확인·동의 등 진입 검사를 그대로 지난다(개정 직후 구현 실행 시도 → 진입 거부 코드 그대로) |
| AC-7 | **진행기**: 개정 뒤 진행기가 의도 개정 실행(`intent_revision`, 직전 원문 참조)을 만들고, 새 버전은 QG-01·delta·**사람 동의** 를 지나야 다음 걸음(defect_fix 면 준비 산출물)으로 간다; `attempts` 는 초기화되지 않는다; 조사 → 제품이면 분석 판정이 승계된 기준에 남는다 |
| AC-8 | **AI 해석**: 업무 단계 논의 응답에 규칙이 붙고 `discussion` 은 아무것도 바꾸지 않으며(기존 두 시험을 그 뜻으로 고침), `profile_change`(가짜 표지)는 처리기가 사용자 메시지를 근거로 개정 → 진행기가 이어 간다; 형식이 틀린 블록은 `invalid` 로 남고 개정하지 않는다; 준비 단계·종료 Case 규칙은 그대로 |
| AC-9 | **화면(D-86)**: 결정 사항 패널이 현재 Profile·처음·개정 목록·대응을 서버 값 그대로 보이고 개정 폼이 409 문구를 그대로 보이며, 타임라인에 표식이 있고, 개정 뒤 의도 동의 카드가 새 버전을 가리킨다(브라우저 시험) |
| AC-10 | **D-88 표시·기본값**: 상세 설정의 시간 절이 `budget.usage` 의 `execution_seconds`·`elapsed_seconds` 를 확정/진행 중/미확정·`complete` 와 함께 사람 말로 보이고, "시간 한도 추가" 가 `execution_seconds` 를 기본으로 채우며, 지표 라벨이 모든 `BudgetMetric` 값을 덮는다(웹 단위). 기존 한도·소비 값은 바뀌지 않는다 |
| AC-11 | **D-88 계측**: 재배정 뒤 옛 세대의 시간 행이 `unresolved`/`reassigned` 로 닫혀 값이 더 자라지 않고 `complete = False` 이며, 새 세대의 시간은 정상 정산된다; v26 이전의 옛 세대 `HELD` 행은 노출에 시간을 더하지 않는다. 기존 예산 시험 전부 통과 |
| AC-12 | **D-89 지원·열기**: Runner 가 데스크톱 능력 행을 보고하고, 요청은 (a) 미연결 PC 409 `runner_disconnected`, (b) 미지원 409 `open_unsupported`, (c) 지원·연결이면 `pending` → heartbeat 제어로 전달 → Runner 가 **자기 worktree 만** 열고(다른 경로는 `failed`/`path_not_owned`, 시험 opener 기록) → `done`/`failed` 기록; 60초 무응답은 `expired`. 열기는 쓰기 허용·진입 검사를 바꾸지 않는다 |
| AC-13 | **D-89 외부 변경**: 쓰기 실행 A 뒤 사람이 worktree 파일을 고치고 쓰기 실행 B 가 돌면 B 의 효과에 `external_change_before_run = true`(근거 실행 A)가 남고 그 수정은 되돌려지지 않으며, 조회의 `unexpected_external_change` 가 내용만 바뀐 경우도 참이다; 직전 실행이 없으면 `null` |
| AC-14 | **화면(D-88·89)**: 결과물 패널의 작업공간 절이 작업 PC(`ws.runner_id` 의 host)·연결·경로·복사·열기 버튼(지원·연결일 때만)·지원 사유·요청 결과·외부 변경 표시를 서버 값 그대로 보인다(브라우저 시험, 시험 opener) |
| AC-15 | **스키마 v26·경계**: 옛 DB(v25) 이행 뒤 의도 버전 행의 profile 이 Case 값(미기록은 NULL), 개정·열기 요청 0건, 해석 표 재구성 뒤 기존 행 보존, 멱등, 본문 컬럼 없음. 강제 축 넷 그대로, `enforcement` 그대로. 기존 시험 전부 통과, 시험 수는 늘기만 한다 |
| AC-16 | 실제 codex·Edge 라이브: **선택 사항** — 하지 않으면 미수행으로 적는다 |

## 5. 검증

- 순수·서버·처리기(`tests/test_profile_revision.py` 새): 3.1 순수 셋, AC-1~8 서버(`harness`·`processing_harness`, 가짜
  codex `HADS_FAKE_WORK=root_cause_analysis` → 분석 완료 → `HADS_FAKE_PROFILE_CHANGE=defect_fix:restoration` 메시지 →
  개정 → 의도 개정 실행 → 동의 대기), 이행(`tests/test_migration.py`: v25 → v26).
- 기존 시험의 의미 검토: `test_policy.py::test_a_profile_change_does_not_reset_history`(404 단언 → 새 끝점으로 이력
  보존 단언), `test_request_processor.py::test_work_stage_replies_get_no_rule_and_no_interpretation` 과
  `test_work_progressor.py::test_a_work_stage_message_gets_a_read_only_reply_and_nothing_else_moves`(해석 없음 → 해석
  `discussion`·적용 없음·아무것도 안 움직임). 검사를 지우지 않는다.
- D-88(`tests/test_budget.py` 추가): 재배정 옛 세대 정산·노출 보호. 웹 단위 `duration.test.ts`·`budget-labels.test.ts`.
- D-89(`tests/test_workspace_open.py` 새): 능력 행, 거부 둘, 전달·열기·소유 확인·결과·만료, 외부 변경(AC-13),
  조회 지문 비교.
- 브라우저(`tests/test_web_shell.py` 끝의 UI-04c 절 2건): (1) D-86 — RCA 업무 → 개정 폼 → 표식·개정 목록·동의 카드;
  (2) D-88·D-89 — 상세 설정 시간 절·시간 한도 추가 기본값, 결과물 패널 작업공간 절·열기 요청(스택의 Runner 에 기록
  opener 주입 가능한지 확인, 아니면 미지원 사유 표시만 검증하고 적는다).
- 전체 `scripts\run-tests.ps1`.

기준선(S-031 시작, 변경 전, `pwsh -File scripts\run-tests.ps1`): 웹 빌드 성공, 웹 단위 **27**, pytest **704 통과·1 실패·2
건너뜀**(12분 31초), P1 계약 **18**(스크립트가 pytest 실패로 멈춰 따로 실행). 실패 1건은 DEVELOPMENT 9절의 기존 시계 해상도
흔들림 시험(`test_quality_changes.py::test_the_reservation_lands_when_the_verification_ends_even_on_a_failure`)이며 단독 3회
실행에서 2회 통과·1회 실패 — 이 세션의 변경 전이고 무관하다. 건너뜀 2건은 이행 시험의 옛 스키마 커밋 창. S-030 최종 수치와
같다(704·1·2).

**최종**(모든 변경 뒤, 같은 스크립트): 웹 빌드 성공, 웹 단위 **31**(+4), pytest **724 통과·0 실패·2 건너뜀**(13분 27초, +19), P1 계약
**18**, "전체 시험 통과". 근거·AC 대조는 [UI-04c 결과](../ui/evidence/UI-04c-results.md) 2·3절.

## 6. 경계

- 개정·해석·열기는 **권한·동의·인수·준수가 아니다.** 진입 검사·예산 강제·확인 지점·게시 규칙·저장소 쓰기 허용은
  그대로다(`enforcement` 넷 `enforced`, `publish` 는 P5). 목적 선언·Profile 개정만으로 조사 Profile 의 제품 쓰기가 열리지
  않는다 — 열리는 것은 실제 Profile·작업공간·쓰기 허용·동의·controlled 를 갖춘 실행뿐이다.
- 소급 없음 — 개정은 그 뒤의 의도 버전·실행에 적용된다. 이전 버전·기준·판정·결정·예약·시도 수는 그대로이고 옛
  버전은 자기 항목 집합으로 읽힌다. 이행이 채우는 의도 버전의 profile 은 당시 사실이다.
- 원문 경계 그대로 — 개정 행의 값은 열거값·짧은 사유·메시지 참조이고 본문이 아니다. 열기 요청은 경로를 브라우저에서
  받지 않고 결과 사유는 짧은 코드다. 트리 지문은 해시다.
- 스키마 v26 — 새 표 둘, 컬럼 셋, 해석 표 재구성(기존 행 보존).
- 시간 지표의 뜻·보장(`enforced_no_absolute_cap`)은 그대로다. 재배정의 정산 의미(옛 세대의 소비가 실제인가)는 P6-03
  그대로이며 이 plan 은 자라는 결함만 멈춘다(관측한 값으로 `unresolved`).

## 9. 알려진 한계·설계 선택

- **개정은 현재 정의판으로만 간다**(v2). v1·미기록 Case 는 개정할 수 없다(D-62).
- **같은 조사 Profile 안의 목적 추가는 분석을 다시 돌리지 않는다**(분석 1회 규칙 그대로). 새 목적의 기준은
  `unverified` 로 남아 사람 대기(예외 수용 또는 새 대화)다 — 필요해지면 그 규칙을 다루는 작업에서.
- **AI 해석의 되돌림은 또 하나의 개정이다.** UI-03 과 같은 좁은 규칙(명시적 요청만, 애매하면 논의)이며 오판은 폼에서
  이전 Profile 로 개정해 바로잡는다. 해석 글은 근거가 아니다.
- **진행 중 실행이 있으면 개정을 거부한다.** 끝난 뒤(사람 대기)에 한다.
- **D-88 은 지표를 바꾸지 않았다.** 실행시간에는 Runner 의 준비·보고 시간이 들어가고(배정~결과 보고), 대기열 대기는
  빠진다. 절대 상한이 아니다. 화면의 값은 5초 조회의 값이다.
- **D-89 열기는 Windows 폴더(`os.startfile`)와 PATH 의 `code` 만 확인한다.** 다른 편집기·비 Windows 는 `unsupported`
  로 보고되고 버튼이 비활성이다. 열기가 실제로 창을 띄웠는지는 Runner 의 호출 성공(예외 없음)으로만 안다.
- **외부 변경 확인은 쓰기 실행 전에만 한다.** 읽기 전용 실행(검증·분석)은 트리를 관측하지 않으므로 그 사이의 외부
  변경은 다음 쓰기 실행이 드러낸다. 제어부는 트리를 보지 못하므로 화면이 "지금" 외부 변경이 있는지는 모른다.
- **열기 요청은 60초 안에 전달되지 않으면 만료된다.** Runner 가 뒤늦게 재시작해 예전 요청을 여는 일을 막는다.
