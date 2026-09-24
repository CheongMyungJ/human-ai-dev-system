# UI-05a 실행 결과 — 관리 화면 전수 대조 + 필수 셋 옮기기(이슈 #7 1단계)

기준: [UI-PLAN-05a](../../plans/UI-PLAN-05a.md) / 이슈 #7 / DEVELOPMENT 1.11절 / [대화 중심 UI](../../ui-conversation-design.md) /
**D-94**(명시로 켠 품질 게이트는 진행기가 스스로 검토·수정한다 — 사용자 결정 2026-09-24). 세션 S-036. 선행
[P4-09 결과](../../p4/evidence/P4-09-results.md) · [UI-04 결과](UI-04-results.md).

**판정: 완료.** 전수 대조(2절)·작업 그래프 수정·실행 상세·QG-02~07 진행 전부 구현·검증(AC-1~14). 스키마 무변경(v28). 최종 전체
시험 795·0·2(웹 37·P1 18), 실제 codex 라이브 통과(15/15). 사람에게 물은 것의 답 — QG-02~07 의 길(진행기가 스스로 돌림, D-94), 실행 중
취소 2단계의 시점(UI-05b 에 붙임), 세션 중 등록된 이슈 #8·#9 의 시점(다음 세션 P4-10, UI-05b 앞)과 실행 제한 시간 기본값(1시간, D-95).
관리 화면은 이번에 지우지 않았다(UI-05b).

## 1. 구현 결과

### 작업 그래프 수정·실행 상세 — 새 화면 `작업` 탭

- **자리.** 오른쪽 패널의 넷째 탭 `작업`(`web/src/shell/WorkPanel.tsx`, 새). 대화 머리의 `작업` 버튼, 대기 카드(일반·상한·품질 게이트)의
  `작업·실행 보기`, 요청 진행 `실행 세부` 의 실행 id, 결정 사항 패널 진행 이력의 실행 id(`hads:open-run` — 그 실행 상세를 연다), 이월
  질문 카드의 `기다리는 작업 고치기` 에서 온다. 사람이 탭을 고르면 목록부터(지난번 실행을 다시 열지 않는다).
- **작업 그래프.** 서버 값 그대로(`preparation.work_graph` — 진입 검사와 같은 값): 리비전·출처·사유, 오래됨 경고, 연결 없는 질문
  경고, 해석 못 한 참조; 작업마다 종류·상태·배정 가능·막힌 이유·저장소·산출물·완료 조건·선행·기준(관계)·그 작업의 실행(리비전을
  가로지름); 기준 대응 표(판정하지 않음); 그래프가 없으면 없다고(준비됨으로 보이지 않음).
- **수정.** 작업 추가(키·종류·목적·산출물·완료 조건·선행·저장소, 이유 필수), 작업별 취소(이유 필수), 기다리는 결정마다 기다리는 작업
  고르기(이유 필수, "답이 아니다" 문구) — 질문↔Task 연결은 **이번에 처음 화면에 생겼다**. 종료·취소된 업무는 보기만.
- **서버 보강.** 세 끝점이 기록 뒤 진행기를 부른다(`_after_human_input`, 출처 `replan:<리비전>`) — 그 전에는 사람이 막힌 작업을
  취소하거나 연결을 고쳐도 `다시 시도`·다음 사건 전까지 아무 일도 없었다. 종료된 업무의 질문 연결은 거부한다
  (`Repository.set_question_blocks` 첫머리 `guard_open_case`) — 그 전에는 새 리비전 쪽이 409 를 돌려주기 **전에** 연결 표를 지우고 다시
  썼다(거부하면서 기록이 바뀜). Task 추가·취소는 원래도 새 리비전 쪽(`create_work_graph_revision`)이 막았다.
- **실행 상세.** `GET /runs/{id}`(이벤트·잔류 관찰·명령·문맥·작업공간 효과) + `GET /runs/{id}/context-refs`: 기본(목적·역할·도구·
  버전·모드·권한·상태·결과·종료 코드·배정 세대·PC·세션·시각·시작하지 않은 이유·사용량·잔류), 고정 입력(참조별 역할·버전·등급·인라인·
  크기·영수증 + 문맥 요약·최신성·지식), 이 run_id 의 진입 검사, 이벤트, 명령, 작업공간 효과, 출력 원문 열기(결과물 뷰어 — PC 에서).
  관리 화면에도 없던 고정 입력 참조 목록·이벤트·명령을 더했다. 읽기뿐이다.

### QG-02~07 — 진행기가 켠 게이트를 스스로 돌린다(D-94)

- **사실(2.1절):** 관리 화면도 QG-02~07 판정을 기록하지 못했다. 명시로 켠 게이트는 켜는 순간 멈추고 끄는 것 말고는 풀 수 없었다.
- **순수 규칙** `domain/work_flow.py` `quality_gate_step`(+ `Step.gate`, `GATED_PURPOSES`): 진행기가 계획 작성·구현·검증 걸음 직전에
  `Repository.quality_gate_progress`(진입 검사 `quality_gate_blockers_for_run` 과 같은 판단에서 시작)를 보고 — 검토 중이면 기다림, 대상
  없으면 사람 대기, 이 버전의 판정이 없으면 **독립 검토 실행**(`quality_gate_review`·검토자·읽기 전용, 작업 id `qg:<게이트>:<Task>`,
  QG-04 는 그 저장소 작업공간에서), 실패·보류면 게이트 수정 한도 안에서 **repair 실행**(QG-02 설계 또는 결합 기록 재작성, QG-03 계획
  재작성, QG-04 구현 다시), 한도가 다 되면 `quality_gate` 사람 대기(게이트·판정·지적·사용/한도), 검토가 실패(`blocked`)면 재시도 한도
  안에서 다시 검토.
- **제어부** `controller/repository.py`: `gate_subject`(대상 — `design`·`plan:<Task>`·`impl:<Task>` 는 고치는 동안 같은 이름, 버전은
  `input_hash`), `quality_gate_progress`, `open_gate_review`(검토 실행을 만들면 검증 1회를 연다 — 시작 당시 정책 고정), `apply_gate_run_effects`
  (결과 보고 뒤·진행기 앞 — 검토면 그 검증을 닫고(독립 검사, 근거 `run:<id>`; 발견을 못 읽었으면 `blocked`), repair 면 예약한 수정
  차수를 사용으로), 배정의 `quality_gate`(게이트·이름·대상·기준 키)·`quality_gate_findings`(repair 실행의 그 게이트 지적 요약).
  `complete_quality_gate_run(blocked=True)` 는 검사 강도·세션을 따지지 않는다(아무 것도 검사하지 않았다). 결합 기록 경로: 설계 산출물이
  없으면 계획 작성에 QG-02 를 요구하지 않는다(지금까지는 영원히 막았다) — 그 경로의 QG-02 는 구현 전에 결합 기록을 본다. 게이트 설정
  변경(`PUT …/policy`)은 기록 뒤 진행기를 부른다.
- **진행기** `controller/work_progressor.py`: 걸음 치환, 검토·repair 실행을 만든 뒤 `_link_gate`(검증 열기·수정 차수 예약, 이력에 남김).
- **Runner·지시문**: 결과 보고에 `quality_gate_findings`; 검토 지시문에 게이트·목적·대상·기준 식별자 블록(`build_quality_gate_block`),
  repair 실행 지시문 끝에 "품질 게이트의 지적" 블록(`build_quality_findings_block`, "기준·시험을 약하게 바꿔 지적을 없애지 마라").
- **화면**: `quality_gate` 대기 카드(`ProgressCards.tsx` `QualityGateCard`) — 판정·수정 사용/한도·지적·대상, 사유 입력, `수정 한도를 올리고
  계속`(게이트 설정의 한도 +1, 그 작업 범위)·`재시도 한도를 올리고 다시 검토`(검토 실패일 때)·`이 게이트 끄기`·`작업·실행 보기`.
  설정 탭 게이트 줄에 수정 사용/한도, 설명 문구를 D-94 로(관리 화면 언급 제거). 대기 문구(`WAIT_DETAIL`)도 고쳤다.

## 2. 전수 대조 분류 (이슈 #7 단계 1 — 결정 기록)

관리 화면(`web/src/App.tsx`·`*Panel.tsx`)의 버튼·폼·표시 전부를 새 화면(`web/src/shell/*`)·진행기(`controller/work_progressor.py`·
`domain/work_flow.py`)·요청 처리기(`controller/request_processor.py`)와 대조했다(S-036, 코드 대조). 분류: **옮김**(사람이 해야 하는데
새 화면·자동 경로 어디에도 없다) / **대신함**(같은 일을 하는 곳이 있다 — 위치) / **개발자 전용**(처리기·진행기를 끈 운영
`HADS_AUTO_PROCESS_REQUESTS=0` 이나 진단에서만) / **버림**(옛 흐름). `옮김` 에는 배정(UI-05a·UI-05b)을 적는다. `개발자 전용` 을 주소로만
들어가는 숨은 화면에 남길지는 UI-05b 가 정한다(이슈 단계 4).

### 2.1 핵심 사실 — QG-02~07 판정은 어느 화면에서도 기록되지 않는다

이슈의 1차 조사("켠 게이트가 막으면 관리 화면에서만 풀린다")와 다르다. 관리 화면 실행 폼의 `QG-02~07 의미 검토` 는
`quality_gate_review` 실행을 만들지만, Runner 가 결과에서 꺼낸 발견(`runner/agent.py` `produced["quality_gate_findings"]`)은 결과
보고에 실리지 않고 제어부도 읽지 않는다. 판정 기록(`Repository.record_quality_gate_run`·`start_/complete_quality_gate_run`)을 부르는
곳은 `POST /api/cases/{id}/quality-gate-runs`(`/open`·`/complete`) 끝점과 시험뿐이며 `web/src/api.ts` 에 그 클라이언트 함수가 없다.
그래서 사람이 게이트를 명시적으로 켜면(`policy_revision > 0`) 계획·구현·검증이 `quality_gate_not_passed` 로 거부되고 진행기는
`quality_gate` 대기에 들어가는데, 그 대기의 문구("관리 화면에서 진행")와 달리 **풀 수 있는 길은 새 화면 설정 탭에서 그 게이트를
끄거나 기본값으로 돌리는 것뿐**이다. 관리 화면의 그 선택지는 결과가 아무 데도 남지 않으므로 `버림`, 판정 기록 경로는 새로
만들어야 한다(plan 3.4 — 사용자 판단).

### 2.2 분류 표

| 영역 | 관리 화면 기능 (파일) | 부르는 API | 새 화면·자동 경로 | 분류 |
|---|---|---|---|---|
| 프로젝트·Case | 프로젝트 목록·열기·추가, 연결된 Runner (App `ProjectPanel`) | `api.listProjects`·`createProject`·`listRunners` | 왼쪽 패널(`Sidebar.tsx`)·`shellApi.projects`·`runners` | 대신함 |
| 프로젝트·Case | Case 목록 행(종류·상태·단계·보관·요청) (App `CasePanel`) | `api.listCases` | 대화 목록 배지(`Sidebar.tsx`)·`shellApi.conversations` | 대신함 |
| 프로젝트·Case | 종류를 골라 Case 추가 (App `CasePanel`) | `api.createCase` | 없음 — 진행기는 이렇게 만든 Case 를 잇지 않는다. 대화 → 업무화가 대신한다 | 버림(API 는 시험용으로 남음) |
| 프로젝트·Case | 새 대화, 주소 기억 | `conversationApi.create` | `Shell.tsx` 새 대화·`lib/address.ts` | 대신함 |
| 대화 | 단계·Profile·처리 방식·PC 연결, 메시지·수신 상태·정정, 중단 요약 (`ConversationPanel`) | `conversationApi.get` | `ConversationView.tsx` | 대신함 |
| 대화 | 보내기(일반·정정)·중단·상태 다시 확인·보관/해제 | `conversationApi.send`·`stop`·`reconcile`·`archive`·`restore` | `Composer.tsx`·`ConversationView.tsx` | 대신함 |
| 대화 | 논의 응답 실행 만들기·처리 완료/실패 기록 | `api.createRun`(`discussion_reply`)·`conversationApi.settle` | 요청 처리기 `start`·`finish` | 개발자 전용 |
| 대화 | Profile 골라 업무로 전환 | `conversationApi.startWork` | 처리기의 AI 해석 → `start_work` | 개발자 전용 |
| 원문 | 원문 참조 표(종류·요약·상태·해시·소유 Runner) (App) | `api.getCase` | 결과물 목록·메시지 수신 상태 | 개발자 전용 |
| 원문 | 원문 제출(instruction)·새로 고침 | `api.submitArtifact` | 메시지 보내기·자동 갱신 | 버림 |
| 의도 | 의도 버전 목록·결정 목록 (App) | — | 결과물 뷰어의 버전·결정 사항 패널 `decisions-list` | 대신함 |
| 의도 | 동의 상태 배너·AI 초안 요청 (`IntentPanel`) | `intentApi.state`·`createRun`(`intent_authoring`) | 단계 요약·동의 카드·진행기의 의도 단계 | 대신함 |
| 의도 | 항목 표·버전 차이 | `intentApi.diff` | 뷰어 차이 보기·delta 카드 | 대신함 |
| 의도 | 미정 질문 답하기 | `intentApi.answerQuestion` | 질문 카드(`card_answer` 메시지) | 대신함 |
| 의도 | 원문 받아 보기·성공 기준 목록 | `intentApi.openRead`·`fetchRead` | 뷰어·`decisions-goal` | 대신함 |
| 의도 | **피드백 보내기** | `intentApi.submitFeedback` | **없음** — 새 화면은 들어온 피드백을 닫는 카드(`FeedbackCard`)만 있다 | **옮김 → UI-05b** (대화의 말로 대신할지 함께 판단) |
| 의도 | 피드백 반영/미반영 닫기·동의 | `intentApi.resolveFeedback`·`agree` | 피드백 카드·동의 카드 | 대신함 |
| 의도 | 사람이 직접 초안 작성 | `intentApi.submitDraft` | 없음(시험은 HTTP 로 직접) | 개발자 전용 |
| 정책 | 대표 목적·정의, 요청 정합성, 위임 근거, 저장소 선택 표시 (`PolicyPanel`) | — | 결정 사항 패널 업무 절·업무 시작 카드·설정 탭 | 대신함 |
| 정책 | Autonomy·예산·진행 상한·확인 지점·delta 확인 | `policyApi.setAutonomy`·`setBudget`·`clearBudget`·`progressApi.setLimits`·`policyApi.confirmCheckpoint`·`progressionApi.confirmDelta` | 설정 탭(`CaseSettings.tsx`)·확인 카드·delta 카드 | 대신함 |
| 지식 | 목록·채택 확인·활성화·무효·충돌·등록 (`KnowledgePanel`) | `knowledgeApi.*` | 프로젝트 규칙 화면(`ProjectRules.tsx`, UI-04a) — `activateReady`·`revise` 는 새 화면에만 | 대신함(브라우저 시험 3곳이 이 패널에 의존 — UI-05b 가 규칙 화면으로 대체) |
| QG-01 | 종합 판정, AI 의미 검토 시작 (App `GatePanel`) | 실행 폼 | 단계 요약·진행기 `_gate_phase`(검토·repair) | 대신함 |
| QG-01 | 규칙·AI·세션 분리 세부 표, 규칙 검사 다시 실행 | `gateApi.runRules` | 구조 보고 때 자동 실행 | 개발자 전용 |
| QG-01 | **발견 사항 목록** | — | **없음** — `gate_repair_exhausted` 대기 카드에 발견이 보이지 않는다 | **옮김 → UI-05b** |
| QG-02~07 | 게이트별 적용·요구 검사·판정·예약 표 (App `QualityGatesPanel`) | — | 설정 탭 `GatesSection`(UI-04b) — repair 사용 수·늦게 온 결과 열은 없음 | 대신함(두 열은 3.4 결정에 따라 UI-05a/05b) |
| QG-02~07 | 실행 폼의 `QG-02~07 의미 검토` | `api.createRun`(`quality_gate_review`) | 결과가 기록되지 않는다(2.1) | 버림 |
| QG-02~07 | **판정 기록(막힘 해소)** | (관리 화면에도 없음) | 없음 — 끄기/기본값만 | **옮김(새로 만듦) → UI-05a, 사용자 판단 뒤**(plan 3.4) |
| 준비 | 작업 수준 표시·조정 (`PreparationPanel`) | `preparationApi.adjustLevel` | 설정 탭 | 대신함 |
| 준비 | 수준 판단 이력 | — | 없음 | 개발자 전용 |
| 준비 | **단계별 검토 방식(사람 검토/자동 진행) 설정** | `preparationApi.setMode` | **없음** — Autonomy 에서 도출된 기본값만 | **옮김 → UI-05b** |
| 준비 | 검토 기록·산출물 원문·이월 질문 표시 | `preparationApi.review`·`openRead` | 단계 검토 카드·뷰어·질문 카드 | 대신함 |
| 준비 | 자동 진행 기록 | `preparationApi.autoProceed` | 산출물 저장 때 자동 | 개발자 전용 |
| 작업 그래프 | **작업 카드(막힌 이유·저장소·기준·선행), 기준 대응 표** (`WorkGraphPanel`) | `preparation.work_graph` | 없음 — 대기 카드의 사유 한 줄뿐 | **옮김 → UI-05a**(`작업` 탭) |
| 작업 그래프 | **작업 취소·작업 추가** | `workGraphApi.cancelTask`·`addTask` | 없음 | **옮김 → UI-05a** |
| 작업 그래프 | 기다리는 사람 결정 목록 | — | 질문 카드(답만) | 대신함(답) — **연결 고치기는 옮김 → UI-05a**(`setQuestionBlocks` 는 어느 화면에도 없었다) |
| 작업공간 | 작업공간 준비(저장소 id 직접 입력) (`WorkspacePanel`) | `workspaceApi.prepare` | 진행기 작업공간 단계·시작 기준 카드 | 대신함 — **다른 브랜치·커밋 기준은 옮김 → UI-05b**(시작 기준 카드) |
| 작업공간 | 코드 조합 고정 | `workspaceApi.buildComposition` | 기준 보고 때 자동 | 개발자 전용(UI-05b 가 확인) |
| 작업공간 | 저장소 카드·실행이 바꾼 것 | — | 결과물 패널 작업공간 절(`WorkspaceRow`)·코드 변경 | 대신함 |
| 작업공간 | 대상 저장소 미기록 실행·조합 카드 | — | 없음 | 개발자 전용 |
| 작업공간 | **실행한 명령과 종료 코드** | `run.commands` | 없음 | **옮김 → UI-05a**(실행 상세) |
| 결과·완료 | 완료 모드 전환 (`ResultPanel`) | `resultApi.setCompletionMode` | Autonomy 에서 도출·표시(설정 탭). 명시로 덮으면 확인 지점이 빠져 진행이 막힐 수 있다 | 버림 |
| 결과·완료 | 목적별 완료 의미 표시 | — | 없음 | 옮김 → UI-05b(낮은 우선) |
| 결과·완료 | **사람 판단으로 기준 판정 기록** | `resultApi.recordVerdict` | **없음** — 진행기는 실행 근거만 적고, 사람은 예외 수용 카드만 있다 | **옮김 → UI-05b** |
| 결과·완료 | 근거 원문·미확정 실행·후보 만들기·예외 수용·최종 인수·자동 완료·후속 Case | `openRead`·`buildCandidate`·`acceptException`·`accept`·`autoComplete`·`createSuccessor` | 뷰어·진행 배너·진행기 `candidate`·예외 카드·확인 카드·`maybe_auto_complete`·처리기 `_move_to_follow_up` | 대신함 |
| 실행 폼 | 제한 분석·QG-01 검토·설계·계획·구현·검증 실행 만들기 (App) | `api.createRun` | 진행기 `_create_run` | 개발자 전용 |
| 실행 폼 | 진입 거부 안내 | — | 대기·막힘 카드 | 대신함 |
| 실행 표 | **실행 표(목적·도구·상태·결과·세션·사용량·잔류·문맥)·문맥 칸(영수증·생략·지식·최신성)·진입 검사 기록** (App `RunContextCell`·`AdmissionLog`) | `detail.runs`·`admission_checks` | 없음 — 요청의 `실행 세부` 한 줄뿐 | **옮김 → UI-05a**(실행 상세 — 이슈 #2 진단 정보; 고정 입력 참조 목록·이벤트는 관리 화면에도 없던 것을 더한다) |

### 2.3 UI-05b 로 넘기는 `옮김`

의도 피드백 보내기, QG-01 발견 사항, 단계별 검토 방식 설정, 사람 판단 기준 판정 기록, 목적별 완료 의미 표시, 다른 브랜치·커밋
기준 시작(시작 기준 카드). 그리고 관리 화면 링크·문구 정리 — 링크 `ProgressCards.tsx`(진행 배너·일반·상한 대기 카드)·
`Sidebar.tsx`, 문구 `ConversationView.tsx`(처리기 꺼짐)·`CaseSettings.tsx`(실행 문맥·게이트)·`domain/work_flow.py`(대기 문구
"관리 화면에서 진행"), 시험 `tests/test_web_shell.py` 의 관리 화면 의존 5곳.

## 3. 검증

| AC | 결과 | 근거 |
|---|---|---|
| AC-1 전수 대조 | 충족 | 2절 표(영역 14, `옮김` 은 UI-05a/05b 배정), 2.1절 핵심 사실 |
| AC-2 작업 탭 보기 | 충족 | 브라우저 `test_the_work_tab_links_a_blocking_question_edits_the_graph_and_shows_a_run` |
| AC-3 추가·취소(이유) | 충족 | 같은 브라우저 시험 + `tests/test_work_graph_edit.py` 둘째(리비전·사유) + 기존 `test_replanning_without_a_reason_is_refused` |
| AC-4 질문 연결 | 충족 | 브라우저(연결 저장 → T1 진행, 질문 `open`) + 제어부 첫째 |
| AC-5 수정 뒤 진행기 | 충족 | `test_work_graph_edit.py` 첫째(`replan:<rev>` 진행 요청·T1 구현)·둘째(호출마다 다시 판정) — 서버 변경을 되돌리면 둘 다 실패함을 확인 |
| AC-6 종료 업무 거부 | 충족 | `test_work_graph_edit.py` 셋째(409·리비전·연결 표 불변 — 가드를 빼면 연결 표가 `['T2']` 로 바뀌어 실패) + 브라우저(폼 없음) |
| AC-7 실행 상세 | 충족 | 브라우저(고정 입력 행 수 = API, `agreed_intent` 읽음, 이벤트 > 0, "이 실행이 바꿨다", 출력 뷰어) |
| AC-8 이동 | 충족 | 브라우저(이월 질문 카드 → 작업 탭, 진행 이력 실행 id → 그 실행 상세, 탭을 고르면 목록부터) |
| AC-9 켠 게이트 자동 검토·통과 | 충족 | `tests/test_quality_gate_progress.py` 첫째(검토 → 통과(독립·근거·검토자) → 검증 → 자동 완료, 지시문 블록) + 브라우저 |
| AC-10 실패 → repair → 재검토 | 충족 | 같은 파일 둘째(지적이 repair 지시문에, 수정 차수 사용 1 → 대기 1/1) |
| AC-11 한도 올림·끄기 | 충족 | 둘째(한도 올림 → 한 번 더 → 통과 → 완료, 사용 2·`passed`)·셋째(끄기 → 완료) + 브라우저 `test_an_explicit_quality_gate_is_reviewed_by_itself_and_the_card_raises_the_limit_or_turns_it_off` |
| AC-12 검토 실패·기본 게이트 | 충족 | 셋째(형식 오류 → `blocked` → 한 번 재검토 → 대기)·넷째(끈 게이트는 검토 없음) + 기존 진행기 시험의 실행 목적 순서(기본 적용 게이트는 검토 없음) |
| AC-13 결합 기록 경로 | 충족 | 다섯째(결합 기록 작성 막지 않음 → 구현 전 QG-02(`design`, 결합 기록 참조)·QG-03(`plan:T1`) 검토 → 구현) |
| AC-14 전체 시험 | 충족 | 아래 "최종 전체 실행" |

관련 모듈 묶음(게이트·진행기·준비·그래프·진입 검사·취소·시작 기준 등 15개 파일, 257건)을 구현 중간에 따로 돌려 전부 통과했다.

### 기준선과 최종 전체 실행

| 실행 | 웹 빌드 | 웹 단위 | pytest | P1 계약 | 종료 코드 |
|---|---|---|---|---|---|
| 기준선(S-036 시작, 변경 전) | 성공 | 37 | 785 통과·0 실패·2 건너뜀(14분 29초) | 18 | 0 |
| 최종(S-036, 모든 변경 뒤) | 성공 | 37 | **795 통과·0 실패·2 건너뜀**(14분 45초) | 18 | 0 "전체 시험 통과" |

늘어난 10건 = `tests/test_work_graph_edit.py` 3 · `tests/test_quality_gate_progress.py` 5 · `tests/test_web_shell.py` +2(실제 Edge·가짜 codex).
작업 그래프·실행 상세만 반영한 시점의 중간 전체 실행은 81% 까지 실패 없이 돌다가 QG 작업을 시작하며 멈췄다(섞인 결과를 남기지 않으려고).

### 실제 codex 라이브 — QG-04 명시 ON(관찰)

`ui/live/p405_progress.py` 에 `HADS_LIVE_GATE`(업무화 직후 게이트를 켬, 자동 진행까지만)·`HADS_LIVE_OUT` 을 더해
`HADS_LIVE_GATE=QG-04 HADS_LIVE_PREFIX=UI-05a-live-gate HADS_LIVE_OUT=ui/evidence` 로 돌렸다(codex-cli 0.156.1, 제품 경유, 실제 Edge).
**결과: passed · 제품 규칙 15/15 · 관찰 19**([UI-05a-live-gate.log](UI-05a-live-gate.log)·[결과 JSON](UI-05a-live-gate-results.json)).

- 업무화(feature) → QG-01 독립 검토 통과 → 동의 → 설계·계획(수준 standard) → 이월 질문 둘에 답 → 구현 T1·T2 → **검증 실행 셋(T3 통합·T4·T5)
  앞마다 진행기가 QG-04 검토를 스스로 만들었다**(`qg:QG-04:T3`·`T4`·`T5`, 사람 없이). 실제 codex 가 발견 JSON 을 냈고 셋 다 발견 없음 →
  `pass`·독립 검사로 기록, 근거 연결. repair 는 없었다(실패 경로는 가짜 CLI 시험이 고정한다).
- 기준 셋이 모두 `met` 으로 적혔고 사람 인수 없이 자동 완료했다(실행 13, 검토 실행 4 = QG-01 1 + QG-04 3, 실행 시간 합 8분).
- **UI-05a 와 무관한 관찰 둘(P4-10 에서 함께 본다):** (1) 검증 Task T6 가 `planned` 로 남은 채 기준 셋이 모두 충족된 시점에 자동
  완료됐다 — 기존 완료 규칙(기준 충족 = 완료 조건)이며 남은 Task 를 보지 않는다. (2) 세 번째 검증은 "정상 종료했으나 출력이 없어 첫 줄을
  확인할 수 없었다"를 종료 코드 0 명령으로 보고했고 기준은 `met` 이 됐다 — 명령·종료 코드의 진위는 자기보고라는 기존 한계(9절). 라이브
  스크립트가 이월 질문 답을 두 번 보냈다(카드가 아직 보일 때 다시 돈 것 — 스크립트의 대기 방식, 제품 결과에 영향 없음).

## 4. 경계

- 새 권한·동의·인수 없음. 그래프 수정은 기존 사람 재계획(FR-07)이고, 질문 연결은 답이 아니며, 실행 상세는 읽기다. 진행기의 게이트
  검토는 읽기 전용 검토자 실행이고 repair 는 기존 목적의 실행으로 진입 검사를 그대로 거친다. 게이트 통과는 권한·인수가 아니고 게이트를
  끄는 것은 통과가 아니다(판정 기록은 남는다 — 브라우저 시험이 `fail` 이 남는 것을 본다).
- 진입 검사의 변경은 하나(결합 기록 경로의 QG-02). 강제 축·게시 규칙(P5)·스키마(v28) 무변경. 관리 화면은 그대로 있다(UI-05b).

## 5. 알려진 한계

- QG-05·06·07 은 명시로 켜도 어느 실행의 조건도 아니다(P4-01 이 기록만 연결) — 진행기는 막는 셋(QG-02·03·04)만 돌린다.
- 통과한 게이트의 대상이 그 뒤 바뀌면 재검토는 P4-02 변경 사건의 몫이다(진행기는 진입 검사가 막을 때만 돈다).
- QG-04 의 repair 는 그 검증 Task 가 기다리는 구현 Task(없으면 마지막 구현)의 다시 실행이다. 여러 구현 Task 중 어느 것을 고칠지 고르지 않는다.
- 실제 codex 의 게이트 검토는 통과 경로만 관찰했다(3절 — 발견 없음 셋). 실패 → repair 경로는 가짜 CLI 시험뿐이다.
- 작업 추가 폼은 기준 연결(`criteria`)을 받지 않는다(관리 화면도 받지 않았다).
- 이슈 #7 은 UI-05b 뒤에 닫는다(관리 화면 삭제·링크 제거·시험 대체가 남았다).
- 세션 중 등록된 이슈 #8(실행 제한 시간 고정 10분·시간 초과 미구분)·#9(검증 미충족 → 수정 구현 사이클 없음)는 사용자 결정으로 다음 세션의
  **P4-10**(UI-05b 앞)에 배정했다. 제한 시간 기본값은 1시간(D-95). 이번에는 구현하지 않았다.
