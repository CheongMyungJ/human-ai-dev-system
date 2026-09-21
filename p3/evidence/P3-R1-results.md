# P3-R1 정책·Profile·영속 모델 — 실행 결과

수행일: 2026-09-21. 계획: [`P3-PLAN-R1`](../../plans/P3-PLAN-R1.md).

이 문서는 **실제로 실행한 것만** 적는다. 자동 시험과 실제 코딩 CLI 실행을 구분하고,
검증하지 않은 항목은 9절에 미검증으로 남긴다. **이 단계가 만든 것은 기록이고 강제가
아니다** — 그 경계를 6절과 8절에 명시한다.

## 1. 실행 환경

| 항목 | 값 | 확인 방법 |
|---|---|---|
| OS | Windows 11 Home 10.0.26200 | P3-03과 동일 |
| 셸 | PowerShell 7 / Git Bash | 〃 |
| Python(고정) | 3.12.10 — 저장소 로컬 `.venv` | `.venv\Scripts\python.exe --version` |
| Node / npm | v22.15.1 / 10.9.2 | `npm run build` 출력 |
| Git | 2.52.0.windows.1 | `git --version` |
| 제어부 스키마 | **v8** | `GET /api/health` → `schema_version=8` ([라이브 로그](P3-R1-live.log) 첫 줄) |
| Codex CLI | **codex-cli 0.154.0** | 실행 결과에 남은 관측 버전 |
| Claude Code | 이번 작업에서 **실행하지 않음** | 9절 |
| OpenCode | **없음** | P1-04와 같음 |

라이브 실행 데이터는 `%LOCALAPPDATA%\Temp\hads-p3-r1-live` 에 두어 저장소 `var\` 와
기존 증거를 건드리지 않았다. CLI에 노출한 작업공간도 같은 곳의 별도 임시 git 저장소이며
**이 설계 저장소를 CLI에 쓰기로 노출하지 않았다.** 실행 권한은 `read_only` 였다.

## 2. 만든 것

v0.7의 정책 축을 **영속 모델로** 만들었다. P3-03까지의 구현은 v0.6 정책을 코드로
고정하고 있었다 — 의도 초안은 여섯 칸 하나, Case당 저장소 하나, 예산 개념 없음.

| 새 이름 | 무엇인가 |
|---|---|
| `CaseProfile` + `domain/profiles.py` | 여섯 목적의 **의미 계약**과 버전. 목적별 의도 항목·최소 증거·완료 의미·초안에서 고정하지 않는 것 |
| `case.profile` / `profile_version` / `profile_source` | 이 Case의 대표 목적, 어느 정의판, **사람이 골랐는가 유도했는가** |
| `case_policy` | `Autonomy`(기본 `ask_on_decision`)와 출처·정책 버전·설정 주체. 이전 값은 `superseded` 로 보존 |
| `delegation_basis` | 지금 무엇을 근거로 자동 진행하는가. 값에 `ai_draft` 가 **없다** |
| `controlled_checkpoint` | controlled의 시작 범위·결과 후보 확인 지점과 실제 확인(주체·시점·대상 해시) |
| `budget_setting` | 지표별 경고/hard 한도와 **측정 방식·강제 가능성·강제 담당** |
| `project_repository` / `case_repository` | 등록 저장소와 Case의 선택·**코드 쓰기 허용·게시 허용**(세 집합 분리) |
| `project.journal_repository_id` | 기록 이슈를 만들 저장소. **코드 대상이 아니다** |
| `PolicyRefusal` | 네 번째 독립 거절 목록 — "이 설정을 받아도 되는가" |
| `intent_field` 의 Profile 의미 항목 | 목적별 항목이 공통 여섯 항목과 **같은 표**에 상태·출처와 함께 들어간다 |
| 의도 문서 v4 | 문서가 자기 `profile` 과 **항목 순서**를 적는다. v1~v3은 계속 읽히며 Profile은 없음 |
| `web/src/PolicyPanel.tsx` | 목적·깊이·확인 경계·예산·저장소와 **각 축의 강제 여부** |

### 기록과 강제를 구별한다

조회 응답에 `enforcement` 표가 함께 나간다. 값이 저장된다는 사실과 값이 동작을 바꾼다는
사실이 다르기 때문이다. hard 예산을 설정한 사람이 "이제 초과하지 않는다"고 믿으면 그것은
우리가 지원하지 않는 보장을 표시한 것이다.

```text
autonomy              recorded_not_enforced  → P3-R4
controlled_checkpoint recorded_not_enforced  → P3-R4
budget                recorded_not_enforced  → P3-R3
repository_selection  recorded_not_enforced  → P3-R2
publish               not_implemented        → P5
```

`tests/test_policy.py::test_a_hard_budget_does_not_yet_change_admission` 이 **강제가 아직
없다는 사실 자체를 시험으로 고정한다.** R3가 실제 강제를 붙일 때 그 시험은 바뀌어야 한다.

### 강제할 수 없는 hard 한도는 설정을 받지 않는다

D-61의 "정확한 hard 한도를 요구했는데 보장할 수 없다면 해당 설정/실행을 허용하지
않는다"를 설정 시점에 적용했다. 저장해 두고 나중에 못 지키는 것보다, 받지 않는 것이
정직하다.

| 지표 | 측정 | hard 한도 |
|---|---|---|
| `run_count`, `review_run_count`, `context_bytes`, `execution_seconds`, `elapsed_seconds` | `exact` | 받는다 |
| `input_tokens`, `output_tokens`, `estimated_cost` | `estimated` | **거부**(`hard_limit_not_enforceable`). 경고선은 받는다 |

라이브 실행이 이 구분의 근거를 그대로 보여 준다 —
[실행 원장](P3-R1-run-ledger.json)의 `usage` 는 토큰을 주었지만
`cost_usd` 는 `"not_reported"` 다. 사후에 오고, 어떤 실행은 아예 주지 않는다.

### 마이그레이션은 없던 결정을 만들지 않는다

v7 DB에 v8을 적용할 때 두 가지만 한다.

1. Project의 `repo_path` 를 `project_repository` 한 건으로 옮긴다(같은 값,
   `source=migrated_from_project`). `repo_path` 컬럼은 **지우지 않는다** — 기존
   배정·작업공간 경로가 그 값을 쓴다.
2. 기존 Case에 `case_policy` 행을 **명시로** 넣되 `autonomy` 는 **NULL** 이다.

둘째가 이 작업의 가장 중요한 경계다. 여기에 `ask_on_decision` 을 적으면 v0.6에서 사람이
설계·계획을 검토하고 결과를 인수하기로 하고 진행한 업무가 조용히 자동 진행 대상이 된다.
가장 가까운 값인 `controlled` 로 적는 것도 안 된다 — v0.6에는 controlled의 시작·결과
확인 체크포인트가 없었고, 있지도 않은 사람의 확인을 기록하는 일이 된다. `policy_version`
은 당시 규칙판인 `"0.6"` 으로 남는다.

Profile도 `kind` 에서 유도해 채우지 않는다. 채우면 그 Case의 기존 의도 버전이 갑자기
Profile 필수 항목을 빠뜨린 문서가 된다.

## 3. 자동 시험

```text
pytest                                  286 passed  (P3-03 시점 242 → +44)
python -m unittest (P1 OpenCode 계약)    18 passed   (변화 없음, CLI 미실행)
npm run build (web)                      성공
```

새로 만든 `tests/test_policy.py` 42건 외에, 기존 시험 다섯 건의 **기대값을 검토해
바꿨다.** v0.6에서 "의도 항목은 여섯 개"를 고정하던 단정들이며, 지금은 "그 Case의
Profile이 요구하는 항목 전부"를 본다. 규칙 자체(정보가 없는 항목을 지우지도 채우지도
않는다)는 그대로다. 검사를 지우지 않고 의미를 옮겼고, Profile이 기록되지 않은 Case가
여섯 항목을 유지한다는 시험을 **새로 더했다**.

| 파일 | 고친 단정 |
|---|---|
| `tests/test_intent.py` | 세 건. `_required(harness, case_id)` 로 그 Case의 필수 항목을 조회해 비교 |
| `tests/test_ai_draft.py` | 한 건. 같은 방식 |
| `tests/test_restart_recovery.py` | 한 건. 재시작 후에도 필수 항목 목록이 복원되는지로 바꿨다 |

## 4. 라이브 검증 — 실제 CLI가 Profile 초안을 썼다 (AC-16)

`refactoring` Profile의 Case를 만들고 실제 codex로 의도 초안을 쓰게 했다. 확인하려는
것은 하나다 — **지시문·문서 형식·구조 검사가 실제 AI 출력과 맞물리는가.**

```text
health: {"status": "ok", "schema_version": 8, "relay_buffered": 0}
case: case-780ae44f48246930 refactoring explicit refactoring
policy autonomy: ask_on_decision system_default
required fields: [goal, expected_outcome, scope, exclusions, constraints,
                  open_questions, improvement_target, improvement_reason,
                  target_boundary, preserved_contracts, improvement_criteria]
run outcome: completed exit 0
observed tool version: codex-cli 0.154.0
session: 01a0c3e4-bb2c-7d11-8435-f0e6dc9bd119
MISSING REQUIRED FIELDS: []
```

codex가 쓴 [의도 원문](P3-R1-intent-original.txt)은 `doc_version 4`, `profile
refactoring`, `profile_version 1` 이고 **열한 항목을 모두** 채웠다. 목적별 항목이 실제로
리팩터링의 의미를 담았다.

```text
improvement_target    load와 load_strict 사이에 중복된 내부 처리
preserved_contracts   load와 load_strict의 공개 함수 이름 및 기존 동작을 보존한다.
                      두 함수는 앞으로도 같은 결과를 내야 한다
improvement_criteria  동일 작업의 내부 중복이 정리되고, 공개 함수 이름과 기존 동작 및
                      두 함수의 결과 동일성이 함께 유지된다
```

성공 기준 세 건 중 **둘이 Profile 의미 항목을 가리켰다**(`improvement_target`,
`preserved_contracts`). 그리고 그것이 이 라이브가 찾아낸 결함이다 — 10절을 보라.

미정 질문 한 건(`결과 동일성의 적용 범위`)을 숨기지 않고 냈고, QG-01 규칙 판정은
`pass`, 게이트 전체는 `not_run` 이다. **규칙 통과를 게이트 통과로 승격하지 않는다.**
수준 판단은 일곱 축을 채우고 `standard` 를 제안했다.

전체 응답은 [정책·라이브 결과](P3-R1-policy-live.json), 실행 기록은
[실행 원장](P3-R1-run-ledger.json), 화면 출력은 [라이브 로그](P3-R1-live.log)에 있다.

## 5. 재시작 복원 (AC-13)

두 가지로 확인했다.

- **실제 프로세스 강제 종료.** `tests/test_restart_recovery.py::
  test_policy_profile_budget_and_repositories_survive_a_forced_kill` 가 제어부를 띄워
  controlled 설정·확인 기록·hard 한도·저장소 선택·위임 근거를 만들고 `taskkill /F` 로
  죽인 뒤 다시 띄운다. 값과 함께 **강제 상태(`recorded_not_enforced`)도 그대로 복원된다**
  — 재시작이 "이제 강제한다"로 바뀌지 않는다.
- **연결 재개.** `tests/test_policy.py::test_policy_records_survive_a_reopened_database`.

## 6. 마이그레이션 (AC-5·AC-8·AC-13)

`tests/test_migration.py::test_a_v7_database_keeps_its_records_and_marks_the_policy_as_unrecorded`
는 **커밋된 v7 스키마를 git 에서 꺼내** 실제 v7 DB를 만들고, v0.6 시절의 사람 결정
(의도 동의 `decision`, `completion_policy=human_acceptance`,
`stage_review_setting=human_review`)을 넣은 뒤 v8을 적용한다.

| 확인 | 결과 |
|---|---|
| 기존 동의·완료 정책·단계 검토 기록 | 그대로 |
| `case.profile` / `profile_version` | **NULL**(유도해 채우지 않는다) |
| `case.kind` | `feature` 보존 |
| `case_policy.autonomy` | **NULL**, 출처 `migrated_unknown`, 정책 버전 `0.6`, 주체 `migration` |
| `project_repository` | 같은 경로 1건, 출처 `migrated_from_project` |
| `project.repo_path` | 그대로(지우지 않는다) |
| `project.journal_repository_id` | NULL(미지정) |
| `case_repository`·`budget_setting`·`controlled_checkpoint`·`delegation_basis` | **0건**(이행이 만들지 않는다) |
| 재실행 | 행이 늘지 않는다(`migrate()` 는 연결마다 돈다) |

## 7. 데이터 경계 (바이트 검사, AC-14)

라이브 데이터로 확인했다. 의도 항목 본문·질문 본문·수준 판단의 근거 서술이
**제어부 DB·WAL·SHM·로그 바이트에 없고 Runner에만 있다.**

```text
제어부에 없음 / Runner에 있음 :: load와 load_strict 사이에 중복된 내부 처리
제어부에 없음 / Runner에 있음 :: load와 load_strict의 공개 함수 이름 및 기존 동작을 보존한
제어부에 없음 / Runner에 있음 :: 두 함수가 같은 결과를 내야 하는 입력 범위는 무엇이며 …
제어부에 없음 / Runner에 있음 :: 내부 중복 제거, 공개 이름과 기존 동작 보존 …
제어부 2,022,421 bytes / Runner 26,729 bytes
목록 표시용 짧은 요약("결과 동일성의 적용 범위")은 제어부에 있다
```

새 표 여섯 개에 본문 컬럼이 없고 모든 요약에 200자 상한이 스키마에 걸려 있다
(`tests/test_policy.py::test_new_p3_r1_tables_have_no_body_columns`). 정책 변경 이유를
길게 밀어 넣으려는 요청은 입력 계약에서 422로 막힌다.

## 8. 성공 기준별 결과 (AC-1~16)

| AC | 결과 | 근거 |
|---|---|---|
| AC-1 여섯 Profile 정의·버전 | **통과** | 자동 시험 4건(정의 전수·버전 조회·출처 구별·모순 거부) + `GET /api/profiles`([사본](P3-R1-profiles.json)) |
| AC-2 Profile별 의도 항목 강제 | **통과** | 자동 시험 4건(6 Profile 전수·누락 거부·기준의 대상 항목·Profile 없는 Case) + 라이브 4절 |
| AC-3 QG-01 규칙이 Profile 항목을 본다 | **통과** | 자동 시험 1건(`required_field_missing`/`target_state`, 규칙 판정 `fail`) + 기존 게이트 시험 회귀 |
| AC-4 새 Case 기본 ask-on-decision | **통과** | 자동 시험 3건(기본값·출처·revision 보존) + 라이브 4절 |
| AC-5 기존 Case에 소급하지 않음 | **통과** | 6절 마이그레이션 + 자동 시험 3건(미기록 표시·기존 기록 불변·여섯 항목 유지) |
| AC-6 controlled 체크포인트 영속화 | **통과** | 자동 시험 6건(생성·확인 기록·명시 요구·요구되지 않은 확인 거부·권한 미생성·대체 후 기록 보존) |
| AC-7 쓰기/게시 허용 분리 | **통과** | 자동 시험 4건(분리·기록 저장소 거부·다른 Project 거부·제외 저장소는 선택 목록에 없음) |
| AC-8 단일 저장소 보존 | **통과** | 6절 + 자동 시험 2건(생성 시 등록·암묵적 단일 저장소 표시) + 기존 `test_workspace` 회귀 |
| AC-9 예산 설정 계약 | **통과** | 자동 시험 6건(무제한 기본·측정 가능 hard·강제 불가 hard 거부·추정 지표 경고선·0 이하 거부·이력 보존) |
| AC-10 미구현을 지원으로 표시하지 않음 | **통과** | 자동 시험 2건(`enforcement` 표·hard 예산이 진입 검사를 바꾸지 않음) + 화면 문구 |
| AC-11 기존 조건을 느슨하게 만들지 않음 | **통과** | 자동 시험 3건(새 kind의 거부 사유가 기존 비기능 Case와 동일·Profile 변경 경로 없음·후속 Case가 Profile·정책·확인 기록을 승계하지 않음) |
| AC-12 직접 API 우회 차단 | **통과** | 자동 시험 6건(모순 입력·종료 Case·다른 Project·0 이하·명시 아님·모르는 항목 이름) |
| AC-13 재시작·이행 | **통과** | 5절·6절 |
| AC-14 데이터 경계 | **통과** | 7절 |
| AC-15 화면에 현재 정책 | **통과(빌드·문구)** | `npm run build` 성공, `PolicyPanel.tsx` 가 미기록·기본값·강제 여부를 구별해 표시. **브라우저 조작은 하지 않았다**(9절) |
| AC-16 라이브 1건 | **통과** | 4절. 실제 codex가 11항목·기준 3건·질문 1건을 냈고 필수 항목 누락 0 |

## 9. 라이브로 하지 않은 것

- **여섯 Profile 전수 라이브.** `refactoring` 한 건만 실제 CLI로 봤다. 나머지 다섯의
  지시문·항목은 자동 시험으로만 확인했다. 전수는 P4-03의 몫이다.
- **브라우저 조작·화면 캡처.** 이번 작업에서는 `npm run build` 와 화면 문구 검토까지만
  했다. P3-03에 쓴 Playwright 환경을 이 세션에서 다시 설치하지 않았고, 화면 없이도
  같은 검사를 서버가 한다는 것은 자동 시험이 본다.
- **Claude Code 실행.** 이번 작업에 의미 검토 실행이 없었다. QG-01 AI 검토는 이 단계의
  범위가 아니며 라이브 게이트는 `not_run` 으로 남았다.
- **Autonomy·예산·저장소 선택이 실행을 바꾸는 것.** **바꾸지 않는 것이 이 단계의
  결과다.** R2~R4가 붙인다.
- **기존 v7 DB의 실제 사용자 데이터 이행.** 시험이 만든 v7 DB로 확인했다. 이
  저장소에는 라이브용 임시 DB만 있었고 보존해야 할 운영 DB가 없었다.

## 10. 검토·시험 중 발견해 고친 것

| 무엇 | 왜 문제인가 | 어떻게 고쳤나 |
|---|---|---|
| **성공 기준이 Profile 의미 항목을 가리킬 수 없었다** | `apply_success_criteria` 가 대상 항목을 공통 여섯 항목으로만 검증했다. 라이브에서 codex가 `improvement_target` 에 걸린 기준을 쓰자 구조 보고가 **500으로 죽고 초안 전체가 사라졌다** — Profile 항목을 만들면서 기준의 대상 집합을 함께 넓히지 않은 빈틈이다 | 저장 계층은 `_field_name`(공통 또는 Profile 항목)으로 검증하고, 입력 계약의 `relates_to` 도 열거형에서 문자열로 바꿨다. 모르는 이름은 여전히 저장하지 않으며 이제 **409와 사유**로 답한다. 회귀 시험을 더했다 |
| `_field_name` 이 `ValueError` 로 죽었다 | 모르는 항목 이름이 500이 됐다. 화면이 "무엇이 잘못됐는가"를 말할 수 없다 | `ConflictError` 로 바꿔 409 + `unknown intent field: …` |
| 정책 거절이 문자열로만 나갔다 | `PolicyRefusal` 코드를 화면과 직접 호출이 같은 근거로 받지 못한다 | `_handle` 이 `PolicyRefused` 를 구조(`{"refusals": [...]}`)로 돌려준다 — 인수 거절과 같은 방식 |
| `case.kind` 에 `refactoring`·`maintenance` 대응이 없었다 | 여섯 Profile 중 둘은 v0.6 유형에 대응 값이 없다. `refactoring` 을 `feature` 로 적으면 기록이 거짓이 된다 | `CaseKind` 에 두 값을 더하고 Profile→kind 유도를 한 곳(`KIND_FOR_PROFILE`)에 뒀다. 새 값이 기존 진입 조건을 느슨하게 하지 않음을 시험으로 고정 |
| **제외한 저장소가 선택 목록에도 나왔다** | 한 목록에 함께 두면 화면이 제외를 선택으로 보여 주고, R2 의 허용 내 자동 추가가 제외 경계를 읽을 근거가 흐려진다. 그리고 기록이 **있는데도** "암묵적 단일 저장소"라는 가정이 붙었다 | 선택과 제외를 나눠 돌려주고, 암묵적 단일 저장소는 `case_repository` 기록이 **하나도 없을 때만** 표시한다. 제외에는 쓰기·게시 허용을 붙일 수 없다. 시험 1건 추가 |
| 후속 Case 가 Profile 을 받을 경로가 없었다 | 완료한 기능의 수정 요청이 결함 수정일 수도 유지보수일 수도 있는데 `kind` 기본값(`feature`)으로 고정됐다. 원래 Case 의 목적을 승계하는 것도 아니어서 목적이 시스템이 고른 값이 된다 | `POST /successor` 가 `profile` 을 받는다. 승계는 여전히 없다 — Autonomy·확인 기록도 새 Case 의 기본값에서 시작함을 시험으로 고정 |

## 11. 남은 위험

- **모델이 강제를 앞질렀다.** 정책·예산·저장소 허용이 기록되지만 아직 아무 것도 막지
  않는다. 조회의 `enforcement` 와 화면 문구, 그리고 "강제가 없다"를 고정한 시험이 그
  경계를 지킨다. R2~R4가 붙일 때 그 시험들을 **갱신해야 한다** — 통과한 채로 남으면
  강제를 붙이지 않은 것이다.
- **`autonomy = NULL` 인 Case 를 R4가 어떻게 다룰지는 정해지지 않았다.** 미기록이므로
  자동 진행 대상으로 올릴 수 없고, 그 결정은 사람의 것이다. R4 plan에서 질문할 항목이다.
- **Project·Task 단위 정책 조정이 없다.** `autonomy-budget-policy` 5절의 우선순위 중
  Case 명시와 시스템 기본값만 구현했다. 없는 계층을 출처 값으로도 만들지 않았다.
- **Profile 재분류 경로가 없다.** D-62는 재분류가 범위·권한·이력·예산을 초기화하지
  않아야 한다고 요구한다. 경로를 만들지 않았으므로 그 보존 규칙도 아직 시험되지 않았다.
  필요해지면 그 작업에서 보존 규칙과 함께 만든다.
- **`repo_path` 와 `project_repository` 에 같은 값이 두 곳에 있다.** 정본을
  `project_repository` 로 옮기는 것은 R2다. 그 사이에 둘이 어긋날 수 있다.
- **repair 한도 모델이 없다.** 예산과 별개라는 사실만 표시했다(P4-01).

## 12. 외부 전송·남은 자원

- 외부로 보낸 것은 **codex 실행 한 번**이며 그 전송은 codex의 기존 사용자 설정을 따른다.
  시스템은 CLI의 자격증명을 읽지도 주입하지도 않았다.
- GitHub 게시·push·PR은 하지 않았다. 이 단계에 그 경로가 없다.
- 라이브 프로세스(제어부·Runner)는 종료했다. `%LOCALAPPDATA%\Temp\hads-p3-r1-live` 는
  증거 사본을 이 저장소로 옮긴 뒤 남겨 두었으며 저장소 `var\` 는 건드리지 않았다.
