# P4-PLAN-07b

참고 후보의 자동 활성 조건 표시 — **반자동**. 기준: 설계 v0.8 2차 / D-01~90 / **D-67**(AI 새 규칙 제안은 후보,
중복은 근거 추가·버전 대체) / **사용자 결정 2026-09-24(S-028): 반자동** — 시스템이 조건 충족을 계산해 프로젝트 규칙
화면에 표시하고 사람이 한 번에 활성화한다. **사람의 클릭 없이 활성화하지 않는다.** 필수로 올리지 않는다 /
[프로젝트 지식](../project-knowledge.md) 2·3절 / [품질 게이트](../quality-gates.md) QG-08 / DEVELOPMENT.md 1.12절.
선행: P4-07(스키마 v24, 후보·근거·채택 확인·활성화), UI-04a(프로젝트 규칙 화면). 세션 S-029.

기준선(S-029 시작, 변경 전, `scripts\run-tests.ps1`): 5절 끝에 있다. 시작 상태 `main`/`6f33867`, 작업 트리 clean,
`git fetch` 뒤 `origin/main` 과 같음.

범위는 **P4-07b 하나**다(작은 작업). UI-04b(프로젝트 설정·상세 설정·알림 — 조건의 Project 설정화 포함), QG-08 의
**독립 AI 검토 실행**, 완전 자동(클릭 없는 활성화), 필수 승격, P5·P6 은 넣지 않는다.

## 0. 제품 판단 — 사용자가 정했고 이 세션은 새로 내리지 않는다

- 조건 여섯(1.12절, S-027 제안 **그대로**)을 계산해 표시하고, **사람이 "한 번에 활성화"를 눌러야** 활성이 된다. 시스템이
  스스로 활성화하는 경로는 만들지 않는다(요청 처리기·결과 뒤 훅·기동 복구 어디에도).
- 한 번에 활성화는 **각 후보마다 기존 `activate_knowledge`** 를 지나므로 QG-08 채택 확인(막는 항목 → 거부)을 그대로
  지난다. 효력은 **참고 그대로**, 범위·활동은 후보 그대로(좁히지 않는다 — 좁히려면 항목의 활성화 폼을 쓴다).
- 아래는 상세 설계 선택이다(9절): 조건 코드의 이름·표시 문구, 근거 실행을 세는 법(출처 실행 + `supports`/`duplicate`
  근거 행의 실행 id, 중복 제거), "종료 코드 0 명령이 있는 검증·분석 실행"을 그 실행의 명령 기록(`run_command.exit_code`)
  으로 보는 것(자기보고라는 한계 그대로), 화면이 본 것만 활성화하도록 `knowledge_ids` 를 보내는 것, 논의 응답의 제안
  (관측 문맥 없음)은 조건 (4)를 만족하지 못한다는 것.

## 1. 현재 구현과 차이 (코드 대조)

1. **조건을 계산하는 자리가 없다.** `domain.knowledge.adoption_check` 는 활성화의 막음/경고만 낸다. 효력·종류·근거 실행
   수·검증 실행의 종료 코드·관측 저장소 범위·반증 후보의 존재를 함께 보는 함수가 없다.
2. **근거는 수로만 있다.** `adoption_check_for` 의 `evidence_count` 는 `source_run_id`(1) + 근거 행 수다 — **서로 다른
   실행**인지, 그 실행이 검증·분석 실행이고 종료 코드 0 명령이 있는지 보지 않는다. 명령 기록은 `run_command`
   (`list_run_commands`)에 있다.
3. **"그 항목을 대상으로 한 반증 후보"를 찾는 조회가 없다.** `knowledge_version.relates_to_knowledge_id`·`relation` 은
   후보 쪽에만 있고 대상 쪽에서 되짚는 조회가 없다.
4. **한 번에 활성화하는 API 가 없다.** `POST /api/knowledge/{id}/activate` 는 항목 하나다. `activate_knowledge` 의
   `adoption` 기록에 "충족 항목"을 더할 자리가 없다(내부에서 만든다).
5. **화면.** 프로젝트 규칙 화면(`ProjectRules.tsx`)의 후보 절 머리는 수만 보이고, 항목 행에 조건 배지가 없다. 대화의
   후보 카드(`ProgressCards.tsx` `KnowledgeCandidateCards`)·관리 화면 지식 패널(`KnowledgePanel.tsx`)도 같다. 세 곳의 안내
   문구가 "자동 활성화 없음"이라 반자동을 설명하지 못한다.
6. **조회.** `knowledge_view` 항목·`knowledge_registrations_view` 행에 조건 결과가 없다.
7. **시험 도구.** 가짜 codex 의 `HADS_FAKE_CANDIDATE` 는 고정 내용을 낸다 — 같은 프로젝트의 두 대화에서 쓰면 둘째는
   같은 원문(해시) → `duplicate` 근거가 된다. 그것으로 "서로 다른 실행 둘"이 된다(추가 표지 불필요).
8. **스키마.** `adoption_json` ≤ 2,000 자(CHECK). 충족 항목을 여기에 더하면 된다 — **스키마 변경 없음**(3.3절).

## 2. 범위

| 넣는 것 | 넣지 않는 것 (담당) |
|---|---|
| **순수 함수** `domain.knowledge.auto_reference_check`: 조건 여섯의 충족/미충족 항목 목록(`adoption_check` 와 같은 모양, `met` 표지) + `auto_reference_ready` | 조건의 Project 설정화(UI-04b 상세 설정) |
| **조회** `auto_reference_check_for(knowledge_id)`: 사실(근거 실행·명령·반증 후보·열린 충돌·채택 확인)을 모아 넘긴다. `knowledge_view` 항목의 `auto_reference`, `knowledge_registrations_view` 후보 행의 `auto_reference` | — |
| **한 번에 활성화** `activate_ready_knowledge(project_id, actor, knowledge_ids)` → `POST /api/projects/{id}/knowledge/activate-ready`: 조건 충족 후보를 각각 `activate_knowledge`(효력 참고·범위 그대로, 사유 고정, `adoption.by` = 누른 사람, `adoption.auto_reference` = 충족 항목·근거 실행)로. 하나가 거부되면 건너뛰고 결과에 적는다 | 클릭 없는 활성화(완전 자동), 필수 승격, `into`·축소(항목별 폼 그대로) |
| **화면**: 프로젝트 규칙 화면의 배지(`자동 활성 조건 충족` / `미충족: 남은 조건`)와 후보 절 머리의 `조건 충족 n건 한 번에 활성화(사람의 결정)` 버튼·결과 표시, 대화 후보 카드·관리 화면 지식 패널의 같은 배지, 안내 문구를 반자동으로 | 독립 AI 검토, 검색·알림·설정 화면 |
| **문서**: project-knowledge 3절, quality-gates QG-08, decisions D-67 구현 기록, README, DEVELOPMENT, 수용 표 AC-32 | — |

## 3. 설계

### 3.1 조건 (`domain.knowledge.auto_reference_check`)

입력: 후보의 현재 버전(`state`·`obligation`·`kind`·`scope_kind`·`repository_id`·`relation`·`observed`), **근거 실행**
목록(`[{run_id, purpose, ok_command}]` — 출처 실행 + 근거 행의 실행을 실행 id 로 중복 제거), 이 항목을 대상으로 한
반증 후보 수, 열린 충돌 수, 채택 확인의 막는 코드 목록. 출력: `AutoReferenceFinding(code, met, detail)` 목록.
**전부 `met` 이면 `ready`** 다.

| 코드 | 조건 | 미충족 표시 |
|---|---|---|
| `candidate` | 현재 버전이 후보다 | "후보가 아니다" |
| `reference` | (1) 효력 `reference` | "필수 제안은 사람이 정한다" |
| `observational_kind` | (2) 종류 `operation`·`known_problem` | "결정·제약은 사람이 정한다" |
| `two_runs` | (3a) 서로 다른 실행 둘 이상 | "근거 실행 n건 — 둘 이상 필요" |
| `verified_run` | (3b) 그중 하나는 종료 코드 0 명령이 있는 검증(`verification_run`)·분석(`limited_analysis`) 실행 | "종료 코드 0 명령이 있는 검증·분석 실행이 없다" |
| `observed_repository` | (4) `scope_kind = repository` 이고 `repository_id = observed.repository_id` | "관측 저장소로 좁혀지지 않았다" / "관측 문맥이 없다(논의 응답의 제안)" |
| `no_contradiction` | (5) `relation != contradicts`, 이 항목을 대상으로 한 `contradicts` 후보 없음, 열린 충돌 없음 | "반증 관계 / 반증 후보 n / 열린 충돌 n" |
| `adoption_clear` | (6) 채택 확인에 막는 항목 없음 | 막는 코드 목록 |

명령·종료 코드는 AI 자기보고다(DEVELOPMENT 9절) — 조건은 기록을 보는 것이지 실행 사실을 새로 증명하지 않는다.

### 3.2 조회·활성화 (`controller/repository.py`)

- `auto_reference_check_for(knowledge_id)`: 현재 버전 → 근거 실행 = `{source_run_id} ∪ {근거 행의 source_run_id}` 각각
  `get_run`(목적)·`list_run_commands`(`exit_code == 0` 하나라도) → 반증 후보 = 이 Project 의 현재 버전 중
  `relates_to_knowledge_id = 이 항목 AND relation = contradicts AND state = candidate` 수 → 열린 충돌 수 →
  `adoption_check_for(knowledge_id)["blocked"]`(요청 축소 없음 = 후보 그대로) → 순수 함수. 반환
  `{knowledge_id, version_id, ready, met: [코드], unmet: [코드], findings, evidence_runs}`.
- `knowledge_view`: 현재 버전이 후보인 항목에 `auto_reference`(다른 상태는 `null`). `knowledge_registrations_view`: 등록된
  행의 현재 상태가 후보이면 `auto_reference`.
- `activate_ready_knowledge(project_id, actor, knowledge_ids=None)`: 대상 = `knowledge_ids` 가 있으면 그 항목들(이
  Project 의 것), 없으면 이 Project 의 후보 전부. 각각 `auto_reference_check_for` → `ready` 가 아니면 `skipped`
  (`reason = not_ready`, `unmet`) → `ready` 면 `activate_knowledge(…, obligation="reference", reason_summary="자동 활성 조건
  충족 — 사람이 한 번에 활성화", extra_adoption={"auto_reference": {"met": […], "evidence_runs": [run_id…]}})` →
  `KnowledgeAdoptionRefused`·`ConflictError` 면 `skipped`(`reason = refused`, 코드). 반환 `{project_id, by, activated:
  [{knowledge_key, version_id, version}], skipped: [{knowledge_key, reason, unmet|refusals}]}`. **한 번에** 처리하되 항목마다
  독립이다(하나의 거부가 다른 것을 막지 않는다 — 각 활성화는 기존 트랜잭션 단위).
- `activate_knowledge` 에 `extra_adoption: dict | None` 을 더한다(있으면 `adoption` 에 합친다 — 2,000 자 상한은
  `register_knowledge` 가 그대로 본다).

### 3.3 저장

**스키마 변경 없음.** 충족 항목·근거 실행은 새 버전의 `adoption_json` 에 `auto_reference` 로 들어간다(코드 8개 + 실행
id 몇 개 — 상한 2,000 자 안이다; 넘으면 `register_knowledge` 가 거부하고 그 후보는 `skipped` 로 남는다). 조건 결과는
저장하지 않고 조회 때 계산한다 — 근거·충돌·상태가 바뀌면 표시도 바뀐다.

### 3.4 API (`controller/api.py`)

- `POST /api/projects/{project_id}/knowledge/activate-ready` — 본문 `{actor = "owner", knowledge_ids: [id] | null}` → 위
  반환값. 404 = Project 없음. 결과의 `skipped` 는 200 이다(하나가 거부돼도 나머지는 됐다).
- `GET /api/knowledge/{knowledge_id}/auto-reference` — 확인만(화면이 항목 하나를 다시 볼 때).

### 3.5 화면

- **프로젝트 규칙 화면**(`ProjectRules.tsx`): 후보 절 머리 오른쪽에 `조건 충족 n건 한 번에 활성화(사람의 결정)` 버튼
  (`rules-activate-ready`, n = 0 이면 비활성) — 화면이 지금 `ready` 로 보이는 항목 id 만 보낸다. 결과 줄
  (`rules-activate-ready-result`: "활성화 K-001 · 건너뜀 K-003(반증 대상 활성)"). 후보 행 머리에 배지(`rule-auto-{key}`,
  `data-ready`): 충족이면 `자동 활성 조건 충족 — 한 번에 활성화 대상`, 아니면 `자동 활성 조건 미충족: <남은 조건>`.
  펼친 상세에 조건 여덟의 충족/미충족 목록(`rule-auto-list-{key}`). 머리 안내를 "조건 충족은 표시일 뿐이고 활성화는
  사람이 한 번에 한다(클릭 없는 활성화 없음)" 로.
- **대화 후보 카드**(`ProgressCards.tsx`): 등록된 후보 행에 같은 배지(`knowledge-candidate-auto-{index}`).
- **관리 화면 지식 패널**(`KnowledgePanel.tsx`): 후보 행에 같은 배지(`knowledge-auto-{key}`), 안내 문구를 반자동으로.
- `api.ts`: `KnowledgeAutoReference`, `KNOWLEDGE_AUTO_REFERENCE_LABEL`, `KnowledgeItemView.auto_reference`,
  `KnowledgeRegistration.auto_reference`, `knowledgeApi.activateReady`.

### 3.6 문서

project-knowledge 3절(구현 사실), quality-gates QG-08 행, decisions D-67 구현 기록, README, DEVELOPMENT(1절·1.12절 →
보존본·3절·4절·6절·9절·인계), review-acceptance-matrix AC-32.

## 4. 성공 기준

| AC | 기준 |
|---|---|
| AC-1 | 순수 함수: 조건 여덟이 전부 충족이면 `ready`, 하나라도 아니면 `ready = false` 이고 그 코드가 `unmet` 에 있다(각 조건을 하나씩 깨는 표 시험) |
| AC-2 | 검증 실행 하나가 남긴 후보(저장소 범위·참고·운영 사실): `two_runs` 미충족(근거 실행 1). 다른 대화의 검증 실행이 같은 내용·`supports` 를 보고하면 근거 실행 2 → `ready`. **그래도 상태는 후보 그대로다**(클릭 전 활성화 없음) |
| AC-3 | 미충족 표시: 필수 제안 → `reference`, 종류 `decision` → `observational_kind`, 프로젝트 범위 후보 → `observed_repository`, 논의 응답의 제안(관측 없음) → `observed_repository`, `contradicts` 후보 → `no_contradiction`, 그 대상 항목도 `no_contradiction`(반증 후보 존재), 열린 충돌 → `no_contradiction`·`adoption_clear` |
| AC-4 | 한 번에 활성화: `ready` 후보만 새 버전(`active`·`reference`·`user_decision`·사유 고정·`adoption.by` = actor·`adoption.auto_reference.met` 8 코드·`evidence_runs`), 범위·활동은 후보 그대로. `ready` 가 아닌 것은 `skipped(not_ready, unmet)`. `knowledge_ids` 를 주면 그것만 본다 |
| AC-5 | 거부는 건너뛴다: 한 번에 활성화 직전에 막힌 후보(열린 충돌 등)는 `skipped(refused, 코드)` 이고 나머지는 활성화된다. 200 이다 |
| AC-6 | 활성화된 참고가 다음 실행(다른 대화의 검증 실행)에 `knowledge_reference` 로 주입되고 Manifest `provided` 다. 필수가 아니다(DB CHECK 그대로) |
| AC-7 | 조회: `knowledge_view` 후보 항목의 `auto_reference`(다른 상태 `null`), `knowledge_registrations_view` 후보 행의 `auto_reference`. 본문 없음, 스키마 v24 그대로 |
| AC-8 | 화면(브라우저): 두 대화의 검증 실행이 같은 후보를 남긴 뒤 규칙 화면의 배지가 `충족`, 상태는 후보 → `한 번에 활성화` 클릭 → 활성 참고 절로 이동·v2·채택 기록에 충족 항목. 클릭 전에는 활성화되지 않는다 |
| AC-9 | 강제 축·권한·준수 의미 그대로. 조건 충족·한 번에 활성화는 권한·동의·인수·준수가 아니다. 자동 활성화 경로(처리기·훅·기동)가 없다(코드 대조) |

## 5. 검증

- 순수(`tests/test_knowledge_extraction.py`): AC-1(표 시험).
- 제어부(같은 파일, `processing_harness`): AC-2~7 — 두 대화의 검증 실행(`_block` 으로 같은 내용·`supports`), 미충족 갈래,
  한 번에 활성화·`knowledge_ids`·거부 건너뜀, 다음 실행 주입.
- 브라우저(`tests/test_web_shell.py`): AC-8 한 건(가짜 codex `HADS_FAKE_CANDIDATE` 두 대화 → 규칙 화면).
- 전체 `scripts\run-tests.ps1`.
- 실제 codex 라이브: **선택 사항**(1.12절) — 실제 codex 가 작업 실행에서 후보를 남기지 않아(P4-07 두 회차) 근거 둘을
  만들 수 없다. 하지 않으면 미수행으로 적는다.

기준선(S-029 시작, 변경 전, `pwsh -File scripts\run-tests.ps1`): 결과 문서 3절에 적는다(실행 중에 plan 을 썼다 — 값은
결과 문서가 정본이다).

## 6. 경계

- **클릭 없는 활성화는 없다.** 조건 충족은 표시이며, 활성화는 사람의 결정(새 버전 `user_decision`)이다.
- **필수로 올리지 않는다.** 한 번에 활성화는 효력 `reference` 만 만든다. AI 제안은 어떤 경로로도 활성 필수가 되지
  않는다(DB CHECK).
- 조건 충족·활성화는 권한·동의·인수·준수가 아니다. 주입은 제공 기록이다.
- 스키마·원문 경계 그대로. 조회에 더한 것은 코드·실행 id·수뿐이다.

## 9. 알려진 한계·설계 선택

- **명령·종료 코드는 자기보고다.** 조건 (3b)는 실행의 명령 기록을 볼 뿐 실행 사실을 증명하지 않는다(9절 그대로).
- **논의 응답의 제안은 조건 (4)를 만족하지 못한다** — 관측 문맥이 없다. 그런 후보는 사람이 항목의 활성화 폼에서
  활성화한다(P4-07 라이브의 K-001·K-002 가 이 경우다). 근거 실행의 관측으로 대신하는 것은 조건을 넓히는 일이라 하지
  않았다(사용자 결정: S-027 조건 그대로).
- **같은 내용의 재보고(`duplicate`)도 근거 실행으로 센다** — 1.12절 그대로. 같은 실행이 두 번 세이지 않는다(실행 id).
- **조건 결과는 저장하지 않는다.** 화면이 볼 때 계산하고, 활성화 때 충족 항목만 `adoption` 에 남긴다.
- **화면이 본 것만 활성화한다**(`knowledge_ids`). 목록을 본 뒤 새로 충족된 후보는 다음에 다시 본다.
- 완전 자동은 후보가 실제로 쌓이면 다시 묻는다(사용자 결정).
