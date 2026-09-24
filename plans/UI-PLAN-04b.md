# UI-PLAN-04b

UI-04(남은 업무·화면 연결)의 **둘째 하위 plan** — 프로젝트 설정·상세 설정 화면 + 알림. 범위는 **사용자 동의
(2026-09-24, S-028)**다. 기준: 설계 v0.8 2차 / D-01~90 / **D-72**(프로젝트 기본값과 명확한 확인 동작 — 프로젝트
기본 도구·모델·깊이·자율성·예산을 주로 사용, 입력창의 간결한 적용 요약, Case 조정은 펼쳐서 변경·출처·적용 시점·
기본값 복귀) / **D-82**(필요한 상황의 PC 알림 — 답변·결과 확인 필요, 의미 있는 차단·오류·예산 문제, 완료; 일상
진행은 알리지 않음; 보고 있는 대화는 중복 팝업 억제; 다른 프로젝트는 선택기에 표시하고 자동 이동 없음) /
**D-29 보충**(진행 상한의 Project 층은 UI-04) / P4-04(인라인 한도의 Case·Project 조정·화면은 UI-04 상세 설정) /
[대화 중심 UI](../ui-conversation-design.md) 3·4·11절 / [autonomy-budget-policy](../autonomy-budget-policy.md) 5절의
우선순위 `Task 명시 → Case 명시 → Project 기본값 → Profile 기본값 → 시스템 기본값`. 선행: UI-04a(결정 사항 패널·
프로젝트 규칙 화면), P4-07b(규칙 화면의 한 번에 활성화), P4-05b(진행 상한 Case 층), P4-04(인라인 한도). 세션 S-030.

기준선(S-030 시작, 변경 전, `scripts\run-tests.ps1`): 5절 끝에 있다. 시작 상태 `main`/`750af52`, 작업 트리 clean,
`git fetch` 뒤 `origin/main` 과 같음.

범위는 **UI-04b 하나**다. UI-04 의 나머지(활성 목적·Profile 이행 D-86, 대화 검색 D-84, 미커밋 포함 시작 D-77,
외부 편집 D-89, 실행시간 합계 계측 D-88)는 뒤 하위 plan 이다. P5·P6 은 넣지 않는다.

## 0. 제품 판단 — 새로 내리지 않는다

이 plan 이 정하는 것은 **설정 층의 저장 모양·적용 시점·화면의 자리·알림의 기술**이며 D-72·D-82·D-29·정책 문서
5절 안이다. S-029 인계가 사용자에게 물으라고 남긴 항목 — **참고 후보 자동 활성 조건의 Project 설정화** — 은
새 제품 판단이라 이 세션에서 **넣지 않고**(조건은 코드 고정 그대로) 인계에 다시 적는다. 사용자 답이 없어 가장
좁은 쪽이다.

상세 설계 선택(제품 정책이 아니다, 9절에도 적는다):

- **Project 층은 다섯 층 중 하나만 만든다.** 정책 문서 5절의 `Task 명시 → Case 명시 → Project 기본값 → Profile
  기본값 → 시스템 기본값` 에서 이 plan 은 **Project 기본값** 층만 만든다. Task 층·Profile 기본값 층은 없고 만들지
  않는다(조회에 그 출처 값이 나타나지 않는다).
- **Project 설정은 이력이다.** `project_setting` 표(키·값·주체·사유·`current`/`superseded`). 바뀐 값을 덮어쓰지
  않는다(Case 정책·예산·상한 행과 같은 모양). "기본값 복귀" 는 현재 행을 `superseded` 로 닫고 새 행을 만들지
  않는 것이다 — 그러면 시스템 기본값이 유효하다.
- **적용 시점은 새 대화·새 실행이다.** 프로젝트 기본값은 **그 뒤에 만든** 대화(Case)의 기본 Autonomy·기본 예산
  행과, **그 뒤에 만든** 실행의 인라인 한도, 그리고 조회 때 계산하는 진행 상한 유효값에 적용된다. 기존 Case 의
  정책 행·예산 행·실행의 한도 기록은 바뀌지 않는다(DEVELOPMENT 3절 "새 정책을 기존 승인·동의·권한에 소급 적용하지
  않는다"). 진행 상한만 Case 설정이 없는 **기존 Case 에도** 조회 때 Project 층이 보인다 — 그 값은 저장된 적이 없고
  "시스템 기본값" 이라는 출처도 저장된 것이 아니었기 때문이다(P4-05b 의 view 가 매번 계산한다). 화면이 출처를
  `project_setting` 으로 보인다.
- **모델·깊이의 프로젝트 기본값은 없다.** 시스템에 "모델" 설정이 없고(CLI 가 스스로 정한다) 깊이(WorkDepth)는
  업무마다 수준 판단(AI 제안 + 사람 조정)이 정한다. 화면은 그 사실을 그대로 보인다 — "모델: CLI 기본값(시스템이
  정하지 않는다)", "깊이: 업무마다 수준 판단". 프로젝트 기본 깊이를 만드는 것은 수준 판단의 의미를 바꾸는 제품
  판단이라 하지 않는다.
- **도구는 프로젝트 기본값이며 바꿀 수 있다.** `project.default_tool_id`(D-45)를 설정 화면에서 바꾸고 이력 행을
  남긴다. 어느 PC 가 그 도구를 확인했는지(`runner_capability`)를 옆에 보인다. 바꾼 도구는 **그 뒤의 실행**에
  적용된다(진행 중 실행은 그대로).
- **Case 의 "기본값 복귀" 는 새 기록이다.** Autonomy 는 새 정책 리비전(값 = 프로젝트/시스템 기본값, 출처
  `project_default`/`system_default`, `set_by` 사람)이고, 진행 상한은 Case 설정 행을 닫는 것(상위 층이 유효), 예산은
  프로젝트 기본 예산을 다시 적용하는 것(`set_by = project_default`, 같은 지표·경계의 현재 행을 대체)이다. 어느
  것도 이전 값을 지우지 않는다.
- **상세 설정의 자리.** 입력창 위 적용 요약(UI-03 `SettingsSummary`)을 누르면 오른쪽 패널의 새 `설정` 탭이 열린다
  (결과물·결정 사항과 같은 자리). 관리 화면 `?view=admin` 은 그대로 둔다.
- **프로젝트 규칙의 자리.** 프로젝트 설정 화면(`?screen=settings`)의 탭 `기본값` / `프로젝트 규칙` / `저장소`.
  `?screen=rules`(+`item`)는 그 화면의 규칙 탭이다 — 카드 링크·주소 규칙·P4-07b 버튼·기존 브라우저 시험이 그대로
  동작한다. 왼쪽 목록의 `프로젝트 규칙` 진입은 `프로젝트 설정` 아래로 옮긴다.
- **알림은 브라우저 조회 위에 만든다.** 서버 푸시(SSE 등)는 만들지 않는다 — 화면이 5초 조회로 가진 상태의
  **전이**를 계산해 브라우저 `Notification` 을 띄운다. 켬·끔은 이 브라우저의 설정(테마와 같은 자리, 업무 정책이
  아니다 — 설계 4절 "테마·앱 알림은 업무 정책과 구분"). 권한은 사람이 켤 때 브라우저에 청한다. 첫 조회(비교할
  이전 상태 없음)에는 알리지 않는다. 화면 안 `알림 기록`(최근 20건, 억제된 것도 표시)을 둔다 — 팝업은 브라우저
  밖이라 시험이 볼 수 없고, 사람이 놓친 알림을 다시 보는 자리이기도 하다.
- **알림 사건**은 서버 도출 값의 전이다: `needs_response` 거짓→참(답변 필요), `progress_state → waiting_human`
  (확인 필요), `→ blocked`(막힘), `current_request_state → unknown`(실행 상태 확인 필요), `status → closed/cancelled`
  또는 `progress_state → done`(완료), 다른 프로젝트의 `attention.needs_response`/`request_unknown` 증가. `running`·
  `processing`·`paused`(사람이 멈춘 것) 전이는 알리지 않는다. 예산 도달은 목록 행에 값이 없어 이 plan 에서는 알리지
  않는다(9절).

## 1. 현재 구현과 차이 (코드 대조)

1. **Project 설정 층이 없다.** `project` 표는 `default_tool_id`(D-45)·`journal_repository_id` 뿐이고
   `effective_policy`(`controller/repository.py`)는 "우선순위는 `Case 명시 → 시스템 기본값`" 이라 적고 있다.
   `AutonomySource` 는 `system_default`·`case_explicit`·`migrated_unknown` 셋이다(`case_policy.autonomy_source` 에
   CHECK 는 없다). `effective_progress_limits` 는 Case 설정 → `self.progress_limits`(환경 변수) 둘이다.
   인라인 한도는 `Repository.context_inline_limit` 하나이며 실행 생성(`plan_inline`)이 그것을 쓰고
   `run.context_inline_limit` 에 적는다. 기본 예산은 없다(설정이 없으면 무제한, D-56).
2. **Case 조정의 화면은 관리 화면뿐이다.** `PolicyPanel.tsx`(Autonomy·예산·진행 상한·저장소 표시), `PreparationPanel`
   (수준 조정 `sizing-adjustment`), `WorkspacePanel`(저장소 선택). QG-02~07 은 `App.tsx` 의 `QualityGatesPanel` 이
   **표시만** 한다 — 설정 API(`PUT /api/cases/{id}/quality-gates/{gate}/policy`)를 부르는 화면이 없다. 새 화면의
   `SettingsSummary`(`Composer.tsx`)는 읽기 전용이고 "대화별 설정 변경은 관리 화면에서 한다 — 입력창의 상세 설정은
   이후 작업(UI-04)" 이라고 적혀 있다.
3. **기본값 복귀 경로가 없다.** Autonomy 는 `PUT /autonomy`(명시)뿐, 진행 상한은 `PUT /progress/limits`(값)뿐, 예산은
   `DELETE`(해제 = 무제한)뿐이다.
4. **알림이 없다.** `web/src` 에 `Notification` 사용이 없다. `Shell.tsx` 가 프로젝트·PC 5초, 대화 목록 5초로 조회하고
   `ProjectWithAttention.attention` 이 다른 프로젝트의 수를 준다(선택기에 표시, D-68). `useCaseData.ts` 머리에
   "푸시·알림은 UI-04" 라 적혀 있다.
5. **화면 주소.** `lib/address.ts` 의 `Screen` 은 `conversation | rules` 다.
6. **시험 도구.** 브라우저 시험은 세션 공유 제어부(`tests/test_web_shell.py`)이며 단언은 프로젝트·대화로 좁힌다.
   가짜 codex 의 `HADS_FAKE_WORK=research` 는 의도 질문 하나를 남겨 `needs_response` 를 만든다.

## 2. 범위

| 넣는 것 | 넣지 않는 것 (담당) |
|---|---|
| **Project 설정 층**(스키마 **v25**, 새 표 `project_setting` 하나): 키 `default_tool_id`·`default_autonomy`·`repair_limit`·`task_retry_limit`·`context_inline_limit_bytes`·`budget:{metric}:{threshold_kind}`(값·주체·사유·이력). 순수 규칙 `domain/project_settings.py`(키·값 검사, 층 합치기). `AutonomySource.PROJECT_DEFAULT`, `ProgressLimits.sources` 의 `project_setting` | Task 층·Profile 기본값 층. 자동 활성 조건의 설정화(코드 고정 그대로 — 사용자에게 물을 항목). 모델·깊이의 프로젝트 기본값(없음을 표시) |
| **적용 지점**: 새 Case/대화의 기본 Autonomy 행(`project_default`)·기본 예산 행(`set_by = project_default`), 진행 상한 유효값의 Project 층, 새 실행의 인라인 한도(Project → 시스템, `run.context_inline_limit` 기록), 도구 변경 | 기존 Case·실행의 소급 변경(없음). 실행 중 실행의 고정 입력·검증 중 예약 설정의 변경(서버 규칙 그대로) |
| **API**: `GET/PUT /api/projects/{id}/settings`(값·출처·적용 시점·이력·시스템 기본값·범위, `null` = 복귀), `POST /api/cases/{id}/autonomy/reset`, `DELETE /api/cases/{id}/progress/limits/{key}`, `POST /api/cases/{id}/budget/project-defaults`; `effective_policy`·`progress_limits_view` 의 출처 확장 | 정책·진입 검사·권위·게시 규칙 변경(없음). 새 강제 축(없음) |
| **프로젝트 설정 화면**(`?screen=settings`, 탭 기본값·프로젝트 규칙·저장소): 도구(PC 확인 상태)·모델(없음)·깊이(업무별)·Autonomy·예산·진행 상한·인라인 한도의 값·출처·적용 시점(이력)·시스템 기본값·변경·복귀; 규칙 탭 = UI-04a 화면 그대로; 저장소 탭 = 등록 저장소·기록 저장소 지정·등록(등록≠선택≠허용) | 프로젝트 이름·경로 변경, 프로젝트 삭제(경로 없음). GitHub 연결(P5) |
| **Case 상세 설정**(오른쪽 패널 `설정` 탭, 입력창 요약에서 열기): 적용 값·출처·적용 시각, Autonomy 변경·복귀, 예산 설정·해제·프로젝트 기본값 적용, 진행 상한 변경·복귀, 수준 조정(판단 있을 때), 저장소 선택(허용 명시), QG-02~07 설정(사유 필수·예약 표시), 인라인 한도(읽기 전용), 종료 Case 는 예산만 | 관리 화면 패널의 삭제(그대로). D-86 목적·Profile 변경. QG 자동 실행 |
| **알림**(D-82): 순수 전이 계산 `lib/notify.ts`, 브라우저 알림 `shell/notifier.ts`(권한·`Notification`·클릭 → 그 대화), 왼쪽 아래 `PC 알림` 켬/끔(브라우저 설정), 화면 안 알림 기록(억제 표시), 보고 있는 대화 억제, 다른 프로젝트 주의 증가 | 서버 푸시·이메일·모바일. 예산 도달 알림(목록에 값 없음, 9절). 소리·배지 |
| 자동 시험(순수·서버·이행·웹 단위·브라우저 2), 문서 | 실제 codex 라이브는 선택 사항(3·5절 — 화면·설정 규칙이라 가짜 CLI 로 같은 경로를 지난다) |

## 3. 설계

### 3.1 순수 규칙 (`domain/project_settings.py`)

- `SETTING_KEYS`: `default_tool_id`(비어 있지 않은 짧은 문자열), `default_autonomy`(`Autonomy` 값), `repair_limit`·
  `task_retry_limit`(`work_flow.check_limit`, 0~10), `context_inline_limit_bytes`(양의 정수), `budget:{metric}:{threshold}`
  (`BudgetMetric`·`BudgetThreshold` 조합, 값 > 0, hard 가 강제 불가한 지표는 거부 — `domain.budget.guarantee_for`
  그대로). `check_setting(key, value) -> normalized`(모르는 키·잘못된 값은 `ValueError`).
- `resolve(key, case_value, project_value, system_value) -> (value, source)` — `case_setting` → `project_setting` →
  `system_default`. 진행 상한·인라인 한도가 쓴다.

### 3.2 저장 (`controller/schema.sql` v25, `controller/db.py`)

```
project_setting (id PK, project_id FK, revision, setting_key, value_json(<=200), set_by, reason_summary(<=200),
                 state current|superseded, created_at, superseded_at, UNIQUE(project_id, revision))
```

새 표만 더한다(`CREATE TABLE IF NOT EXISTS`). `SCHEMA_VERSION = 25`. 옛 DB 는 행이 없고 그것은 "설정 없음 = 시스템
기본값" 이다. 본문 컬럼 없음(데이터 경계 시험이 표 이름과 무관하게 본다). `case_policy.autonomy_source` 의 새 값
`project_default` 는 CHECK 가 없어 표 재구성이 없다.

### 3.3 저장 계층 (`controller/repository.py`)

- `project_settings_view(project_id)`: `{project_id, name, default_tool_id, tool: {value, source, setting, verified_on:
  [{runner_id, host, state}]}, model: {note}, depth: {note}, settings: {key: {value, source, setting|null,
  system_default}}, budget_defaults: [{metric, threshold_kind, limit_value, unit, guarantee, setting}], budget_metrics, ranges,
  history, applies_to, note}` — 등록 저장소는 기존 조회(`GET /api/projects/{id}/repositories`)를 화면이 따로 읽는다.
- `set_project_settings(project_id, values: {key: value|None}, set_by, reason)`: 키마다 검사 → 현재 행 `superseded`
  → 값이 있으면 새 행. `default_tool_id` 는 `project` 컬럼도 갱신(이력은 표에). 하나라도 잘못되면 전부 거부(원자).
- `_project_setting(project_id, key)`(현재 값 하나) · `_project_budget_defaults(project_id)`.
- 적용: `create_case`·`create_conversation` 의 `_insert_default_policy(case_id, now, project_id)` — 프로젝트 기본
  Autonomy 가 있으면 그 값·`project_default`·`set_by = project`, 없으면 그대로; 이어서 `_apply_project_budget_defaults
  (case_id, project_id, now)`(행마다 `set_budget_limit` 와 같은 검사·같은 컬럼, `set_by = project_default`).
  `effective_progress_limits` 에 Project 층. 실행 생성의 인라인 한도: `plan_inline(..., self._inline_limit_for(case_id))`
  (Project 값 → `self.context_inline_limit`), 조회 `run_context_view.limit` 은 실행 기록 그대로.
- `effective_policy`: `default_autonomy`·`default_autonomy_source`(`project_default`/`system_default`)를 더하고
  머리 주석의 "Project 단위 조정은 아직 없으므로" 를 고친다. `progress_limits_view`: `project_default: {key: value|null}`.
- `reset_autonomy(case_id, set_by, reason)`: 종료 Case 거부(`_guard_policy_change`), 새 리비전(값 = 프로젝트/시스템
  기본값, 출처 그것), controlled 확인 지점 규칙은 `set_autonomy` 와 같다(공통 내부 함수로).
- `clear_progress_limit(case_id, key, set_by, reason)`: 현재 Case 행을 `superseded` 로. 종료 Case 거부. 이력 행에
  `cleared` 표시는 두지 않는다 — 현재 행이 없다는 사실이 곧 복귀다(view 의 `setting = null`·출처 상위 층).
- `apply_project_budget_defaults(case_id, set_by)`: 프로젝트 기본 예산을 다시 적용(같은 지표·경계 현재 행 대체,
  `set_by = project_default`, `reason_summary` 에 주체). 종료 뒤에도 받는다(예산은 D-87).

### 3.4 API (`controller/api.py`)

- `GET /api/projects/{id}/settings` → view. `PUT /api/projects/{id}/settings` `{values: {key: value|null}, set_by,
  reason_summary}` → view(422 잘못된 키·값 — 사유를 그대로).
- `POST /api/cases/{id}/autonomy/reset` `{set_by, reason_summary}` → `CasePolicy`. `DELETE /api/cases/{id}/progress/limits/{key}`
  → limits view + 진행 상태(사람 입력 뒤 진행기 호출은 `PUT` 과 같다). `POST /api/cases/{id}/budget/project-defaults`
  `{set_by}` → 예산 상태.

### 3.5 화면

- `lib/address.ts`: `Screen = 'conversation' | 'rules' | 'settings'`, `settingsLink(projectId, tab?)`. `rules` 는 설정
  화면의 규칙 탭.
- `shell/ProjectSettings.tsx`(새): 머리(프로젝트 이름 · `← 대화로` `settings-back`), 탭(`settings-tab-defaults`·
  `settings-tab-rules`·`settings-tab-repositories`). 기본값 탭(`settings-defaults`): 행마다 `setting-{key}`(값·출처
  `data-source`·적용 시점·시스템 기본값), 변경 폼(사유), `기본값으로 복귀`(`setting-reset-{key}`), 예산 기본값 행 추가·
  해제, 이력(`settings-history`). 안내: "여기 값은 **이 뒤에 만드는 대화·실행**에 적용된다. 기존 대화의 설정은 그
  대화의 상세 설정에서 바꾼다. 설정은 권한·동의·인수가 아니다". 규칙 탭 = `ProjectRules`(머리 없이, `rules-screen`·
  `rules-back` 그대로). 저장소 탭(`settings-repositories`): 목록·기록 저장소 지정·등록 폼.
- `Shell.tsx`·`Sidebar.tsx`: `프로젝트 설정`(`open-settings`) 아래 `프로젝트 규칙`(`open-rules`, 규칙 탭). `screen`
  `settings|rules` 면 가운데가 설정 화면, 패널은 닫힌다.
- `shell/CaseSettings.tsx`(새, `ReviewPanel` 의 `settings` 탭, `data-testid="case-settings"`): 절 — 적용 값
  (`case-setting-autonomy` 등, `data-source`, 적용 시각) · Autonomy(두 버튼 + 사유, `case-autonomy-reset`) · 예산
  (현재 한도·해제·추가 폼·`case-budget-project-defaults`) · 진행 상한(변경·`case-limit-reset-{key}`) · 수준(현재 판단
  또는 "수준 판단 없음 — 의도 초안이 먼저", 조정 폼) · 저장소 선택(등록 저장소마다 선택 상태, 선택 폼 — 코드 쓰기·
  게시 허용 체크, 기록 저장소 표시) · QG-02~07(게이트마다 적용·요구 검사·수정 한도·출처·적용/요청 시각·예약, 설정
  폼 on/off/inherit·검사 강도·한도·사유) · 인라인 한도(이 프로젝트 값·출처, 읽기 전용) · 종료 Case 안내. 409/422 는
  서버 문구 그대로.
- `Composer.tsx` `SettingsSummary`: 펼친 곳의 "관리 화면에서 한다" 문장을 `상세 설정 열기`(`open-case-settings`,
  `hads:open-panel` `settings`)로 바꾸고 출처를 사람 말(`이 업무에서 정함`·`프로젝트 기본값`·`시스템 기본값`)로.
- `lib/notify.ts`(순수, import 없음): `diffConversations(prev, next, ctx) -> Notice[]`, `diffProjects(prev, next,
  currentProjectId) -> Notice[]`, `suppressed(notice, ctx)`. `Notice = {key, kind, title, body, caseId|null,
  projectId, suppressed}`.
- `shell/notifier.ts`: `permissionState()`, `requestPermission()`, `show(notice, onOpen)`(권한 `granted` 일 때만
  `new Notification`, `tag = key`, 클릭 → `onOpen`). `Prefs.notifications: boolean`(기본 `false` — 브라우저 권한이
  사람의 행동을 요구한다), `Sidebar` 의 `PC 알림` 토글(`notify-toggle`, 상태 문구 켜짐/권한 필요/브라우저가 차단),
  `Shell` 이 조회 결과마다 전이를 계산해 기록(`notice-log`, `notice-{n}`, `data-kind`·`data-case`·`data-suppressed`)
  하고 억제되지 않은 것만 띄운다. 알림 클릭은 그 프로젝트·대화를 **사람이** 여는 것이다(자동 전환 없음).
- `api.ts`: `ProjectSettingsView`·`projectSettingsApi`(`get`·`set`), `policyApi.resetAutonomy`, `progressApi.clearLimit`,
  `policyApi.applyProjectBudgetDefaults`, `qualityGateApi.setPolicy`, `AUTONOMY_SOURCE_LABEL` 의 `project_default`,
  `PROGRESS_LIMIT_SOURCE_LABEL` 의 `project_setting`, `PanelTab` 에 `settings`.

### 3.6 문서

ui-conversation-design 3·4·11·12절(구현 기록), decisions D-72·D-82(구현 기록)·D-29 보충, autonomy-budget-policy 5절
(Project 층 구현 표시), README, DEVELOPMENT(1절 요약 표·1.11절·3절·4절·9절·인계), review-acceptance-matrix AC-46·47.

## 4. 성공 기준

| AC | 기준 |
|---|---|
| AC-1 | 프로젝트 설정 화면 기본값 탭: 도구(값·출처·이 도구를 확인한 PC)·모델(없음 표시)·깊이(업무별 판단 표시)·Autonomy·예산 기본값·진행 상한·인라인 한도의 값·출처(`project_setting`/`system_default`)·적용 시점(설정 행의 시각)·시스템 기본값이 서버 값 그대로. 변경은 사유와 함께 이력 행이 되고 복귀는 현재 행을 닫는다(이력 보존) |
| AC-2 | 적용 시점: 설정 **뒤** 만든 대화가 `autonomy_source = project_default`·기본 예산 행(`set_by = project_default`)을 받고, 그 뒤의 실행이 프로젝트 인라인 한도를 `run.context_inline_limit` 에 기록한다. 설정 **전**의 Case 정책 행·예산 행·실행 기록은 그대로다(소급 없음) |
| AC-3 | 우선순위 `Case 명시 → Project → 시스템`: 진행 상한 view 의 값·출처 세 경우, 인라인 한도 두 경우(Case 층 없음), Autonomy 세 출처. 잘못된 키·값(0 이하 한도, 강제 불가 hard 예산, 모르는 Autonomy)은 422 로 거부되고 아무 것도 저장되지 않는다 |
| AC-4 | Case 복귀: `autonomy/reset` → 새 리비전(값·출처 프로젝트 또는 시스템, 이전 행 `superseded`, controlled 확인 지점 규칙은 `set_autonomy` 와 같다); 진행 상한 해제 → view 출처 상위 층·이력 보존; 예산 프로젝트 기본값 적용 → 같은 지표·경계 대체. 종료 Case 는 Autonomy·상한 변경이 409, 예산은 된다(D-87) |
| AC-5 | Case 상세 설정 패널: 적용 값·출처·적용 시각이 서버 값이고, Autonomy 변경·복귀, 예산 설정·해제·기본값 적용, 진행 상한 변경·복귀가 서버 규칙 그대로 반영된다. 수준 조정은 판단이 있을 때만 폼(이유·남는 위험 필수), 저장소 선택은 코드 쓰기·게시 허용을 명시로 받는다(기본값 없음), QG-02~07 설정은 사유 필수·강도 낮추기 거부(409 문구)·예약 표시가 그대로다 |
| AC-6 | 프로젝트 규칙의 이동: `?screen=rules[&item=]`·카드 링크·`open-rules`·`rules-back`·P4-07b 한 번에 활성화가 설정 화면의 규칙 탭에서 그대로 동작한다(UI-04a·P4-07b 브라우저 시험 통과) |
| AC-7 | 저장소 탭: 등록 저장소 목록·기록 저장소 지정·등록이 되고 "등록은 선택도 허용도 아니다" 가 보인다 |
| AC-8 | 알림: (a) 순수 전이 — 답변 필요·확인 필요·막힘·실행 상태 확인 필요·완료·다른 프로젝트 주의 증가는 알림, `running`·`processing`·`paused`·첫 조회는 아니다; (b) 보고 있는 대화(문서 보임·포커스·같은 대화)는 억제되고 기록에 남는다; (c) 브라우저 — 켜면 권한을 청하고, 다른 대화의 답변 필요가 기록·팝업(권한 허용 시)이 되며, 보고 있는 대화의 사건은 억제로 기록된다; 클릭은 그 대화를 연다 |
| AC-9 | 스키마 v25: 새 표 하나, 옛 DB(v24) 이행 뒤 설정 없음 = 시스템 기본값, 멱등, 본문 컬럼 없음(데이터 경계 시험) |
| AC-10 | 경계: 설정·복귀는 권한·동의·인수·준수가 아니다(문구·코드 — 진입 검사·정책 코드 미변경, `enforcement` 넷 그대로). 실행 중 실행의 고정 입력과 검증 중 예약은 바뀌지 않는다(서버 규칙, 기존 시험). 기존 시험 전부 통과, 기준선 대비 시험 수는 늘기만 한다 |
| AC-11 | 자동 시험: 순수(설정 검사·층 합치기·알림 전이), 서버(`tests/test_project_settings.py`: AC-2·3·4·9), 이행(v24 → v25), 웹 단위(`notify.test.ts`·`address.test.ts`), 브라우저 2건(설정 화면·상세 설정 / 알림) |
| AC-12 | 실제 codex·실제 Edge: **선택 사항** — 이 작업의 규칙은 화면·설정·알림이며 AI 응답 내용에 의존하지 않는다. 하지 않으면 미수행으로 적는다 |

## 5. 검증

- 순수(`tests/test_project_settings.py` 앞부분): `check_setting`·`resolve`.
- 서버(같은 파일, `harness`·`processing_harness`): 설정 전 대화 → 설정(Autonomy controlled·예산 run_count hard 3·
  상한·인라인 한도) → 설정 뒤 대화·업무 실행 → 두 Case 의 정책·예산·상한·실행 한도 대조; 잘못된 값 422; 복귀 셋;
  종료 Case; `effective_policy` 출처; 도구 변경 뒤 새 실행의 도구.
- 이행(`tests/test_migration.py`): v24 DB(현재 이행에서 `project_setting` 을 빼고 표식 24) → 이행 → 표·행 0·멱등.
- 웹 단위(`web/src/lib/notify.test.ts`·`address.test.ts`).
- 브라우저(`tests/test_web_shell.py`): (1) 설정 화면 — 기본값 변경·이력·새 대화의 출처·상세 설정 패널의 변경·복귀·
  QG 설정·규칙 탭·저장소 탭; (2) 알림 — 켜기(권한 허용) → 다른 대화의 답변 필요 알림 기록·보고 있는 대화 억제.
- 전체 `scripts\run-tests.ps1`.

기준선(S-030 시작, 변경 전, `pwsh -File scripts\run-tests.ps1`): 웹 빌드 성공, 웹 단위 **21**, pytest **696 통과·2 건너뜀·0
실패**(11분 39초), P1 계약 **18**. S-029 인계의 수치와 같다. 건너뜀 2건은 이행 시험의 옛 스키마 커밋 창(DEVELOPMENT 9절)이다.

## 6. 경계

- 프로젝트 기본값·Case 조정·복귀는 **설정**이며 권한·동의·인수·준수가 아니다. 진입 검사·예산 강제·확인 지점·
  게시 규칙은 그대로다(`enforcement` 넷 `enforced`, `publish` 는 P5).
- 소급 없음 — 프로젝트 기본값은 그 뒤에 만든 대화·실행에만 적용되고 기존 기록은 바뀌지 않는다. 진행 상한만 조회
  때 계산되는 유효값이라 Case 설정 없는 기존 Case 에도 보인다(저장된 값이 없었다).
- 원문 경계 그대로 — 설정 값은 짧은 값(도구 id·Autonomy·정수·지표 한도)이며 본문이 아니다. 알림 본문은 제목·상태
  코드의 사람 말이며 메시지 본문을 담지 않는다.
- 스키마 v25 — 새 표 하나, 기존 표·CHECK 변경 없음.

## 9. 알려진 한계·설계 선택

- **Project 층만 있다.** Task 층·Profile 기본값 층은 없다(정책 5절의 다섯 층 중 셋 — Case·Project·시스템).
- **모델·깊이의 프로젝트 기본값이 없다.** 시스템에 모델 설정이 없고 깊이는 업무별 수준 판단이다. 화면은 그 사실을
  보인다.
- **알림은 조회 위의 전이다.** 5초 조회 간격 안의 두 전이는 마지막 것만 보이고, 탭이 닫혀 있으면 알림이 없다(서버
  푸시 없음). 예산 도달·오류는 목록 행에 값이 없어 이 plan 에서 알리지 않는다 — 예산 정지는 그 대화의 카드·관리
  화면에 보인다.
- **팝업은 브라우저 밖이다.** 시험은 화면 안 알림 기록으로 본다. 권한이 거부되면 기록만 남는다.
- **참고 후보 자동 활성 조건의 설정화는 넣지 않았다**(사용자에게 물을 항목, 코드 고정 그대로).
- **도구 변경은 확인이 아니다.** 어느 PC 도 확인하지 않은 도구를 기본값으로 두면 그 뒤 실행이 진입 검사에서
  `tool_not_available` 로 거부된다 — 화면이 확인 상태를 보이지만 막지 않는다.

## 10. 보충 — 예산 도달 알림 (2026-09-24, 사용자 결정, 구현 전에 기록)

**변경 이유:** 이 plan 의 0·9절은 "예산 도달은 목록 행에 값이 없어 이 plan 에서는 알리지 않는다" 였다. 작업 보고 뒤 사용자가
예산 도달 알림을 **지금 UI-04b 보충으로 넣기로** 정했다(D-82 "의미 있는 … 예산 문제" 의 범위 안). 같은 자리에서 사용자가
정한 다른 둘 — (1) UI-04 의 남은 네 항목은 두 단계로 묶는다(1.11절), (2) 참고 후보 자동 활성 조건의 Project 설정화는 나중에
필요하면 한다 — 는 문서에만 반영한다(코드 없음).

**넣는 것:**

- 서버: 대화 목록 행(`list_cases` → `_with_conversation_summary`)에 `budget_stopped`(hard 한도 도달로 새 실행이 중지됐는가 —
  `budget_stop(...)["stopped"]`). **현재 hard 한도가 있는 대화만 계산한다**(무제한이 기본값이라 대부분 0 비용). `project_attention`
  에 `budget_stopped` 수(다른 프로젝트의 주의).
- 화면: `lib/notify.ts` 의 종류 `budget_stop`(거짓→참 전이, "예산 한도에 닿아 새 실행이 중지됐다"), `diffProjects` 가
  `attention.budget_stopped` 증가도 알린다. 왼쪽 목록 행 배지 `예산 도달`, 선택기의 다른 프로젝트 수. 억제 규칙은 같다.
- 시험: 순수(전이·다른 프로젝트), 서버(`test_project_settings.py` — hard 한도 있는 대화만 `budget_stopped`, 없는 대화 `False`,
  `project_attention.budget_stopped`), 브라우저(알림 시험에 예산 도달 단계 추가 — 프로젝트 기본 예산 `run_count hard 1` 을 다른
  대화에 다시 적용 → 기록 `budget_stop`·팝업·행 배지).

**AC-13:** 예산 hard 도달 대화가 목록 행 `budget_stopped = true` 이고(한도 없는 대화는 `false`, 계산하지 않음), 그 전이가 `budget_stop`
알림이 되며(보고 있는 대화는 억제), 다른 프로젝트의 도달 수 증가가 한 건으로 알려진다. 예산 판정 자체는 R3 그대로다(설정·알림은
강제가 아니다).
