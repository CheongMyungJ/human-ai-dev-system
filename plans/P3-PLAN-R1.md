# P3-PLAN-R1

정책·Profile·영속 모델 정합화. 기준: 설계 v0.7 / D-01~67 / 2026-09-21.
선행: P3-01~03 완료(스키마 v7, pytest 242 + P1 계약 18 통과). 다음: [P3-R2 복수 저장소](../DEVELOPMENT.md).

## 1. 이 작업이 답해야 하는 것

P3-03까지의 구현은 **v0.6 정책을 코드로 고정**해 두었다. 여섯 칸 의도 초안 하나,
Case당 저장소 하나, 설계·계획의 사람 검토 기본 필수, 완료의 사람 인수 기본, 예산 개념
없음이다. v0.7은 그 위에 여섯 Profile, WorkDepth와 분리된 Autonomy, 위임 근거와 정책
버전, Project의 복수 저장소와 쓰기/게시 허용의 분리, 선택적 예산을 요구한다.

R1은 **그 모델과 영속 계약, 그리고 기존 데이터의 이행**만 만든다. 자동 실행 경로·예산
강제·Case×Repo 작업공간은 각각 R4·R3·R2의 몫이며, R1이 만든 표가 그 권한을 미리 열지
않는다. 그래서 이 작업의 가장 중요한 성공 기준은 "모델이 생겼다"가 아니라
**"모델이 생겼다는 이유로 아직 없는 기능을 지원한다고 표시하지 않는다"** 다.

## 2. 범위

| 넣는 것 | 넣지 않는 것 (담당) |
|---|---|
| 여섯 Case Profile 정의·버전 고정, Case별 기록 | Profile별 실행 경로·Task seed (R4·P4-03) |
| Profile별 의도 초안 항목(공통 6항목 + 목적별 의미 항목)과 QG-01 규칙 반영 | 실제 여섯 Profile 라이브 초안 전수 (P4-03) |
| `Autonomy`(ask-on-decision / controlled) 설정·이력·정책 버전 | Autonomy 기반 진입 조건·Fast Lane·material delta 판단 (R4) |
| controlled 체크포인트와 확인 기록의 영속화 | 체크포인트로 실행·게시를 실제 차단 (R4·P5) |
| 위임 근거(원 요청·후속 결정·정책) 기록과 누적 비교의 기준점 | 누적 material delta 계산·질문 생성 (R4) |
| Project 등록 저장소·기록 저장소 지정, Case의 선택/쓰기허용/게시허용 모델 | 허용 내 자동 추가, Case×Repo 작업공간, 부분 실패 (R2) |
| 예산 설정 계약(지표·경고/hard·측정 방식·강제 가능성)과 무제한 기본값 | 예약·집계·정지·hard 이후 차단 (R3) |
| 기존 데이터 마이그레이션(스키마 v8)과 미기록의 표시 | 기존 Case에 새 기본값 소급 적용 (하지 않는다) |
| 정책·Profile·저장소·예산의 화면 표시와 "아직 강제하지 않음" 표기 | push·PR·게시 Grant의 대상·유효기간 모델 (P5) |
| repair 한도와 예산의 분리 선언 | `RemediationCycle` 모델 (P4-01) |

**진입 조건(FR-29)의 판정은 이번에 바꾸지 않는다.** `AdmissionProfile` 선택 규칙도
그대로다. 새 Profile 값이 생겼다고 조건표를 바꾸면, 아직 R4가 없는 상태에서 v0.7이
없애려는 "일괄 의도 동의 장벽"을 오히려 비기능 업무까지 넓히게 된다(D-14·D-22). 대신
**새 값이 기존 조건을 느슨하게 만들지 않는다**는 것을 시험으로 고정한다(AC-11).

## 3. 정책·데이터 영향과 마이그레이션 계약

이 작업에서 가장 위험한 것은 마이그레이션이다. "기본 ask-on-decision"을 기존 Case에
적용하면 v0.6에서 사람이 검토·인수하기로 하고 진행한 업무가 조용히 자동 진행 대상이
된다. 그것은 새 정책의 소급 적용이며 금지된다(DEVELOPMENT 3절).

| 대상 | 새 Case | R1 이전에 만들어진 Case |
|---|---|---|
| `Autonomy` | `ask_on_decision`, 출처 `system_default` | **기록하지 않는다.** `autonomy = NULL`, 출처 `migrated_unknown`, `policy_version = "0.6"` |
| Profile | 요청값 또는 `kind` 에서 유도(출처를 구별해 기록) | `profile = NULL`. `kind` 는 그대로 보존 |
| 의도 초안 항목 | 공통 6 + Profile 필수 항목 | 공통 6항목 그대로. 과거 게이트 판정도 그대로 |
| 완료·검토 정책 | 기존 `completion_policy`·`stage_review_setting` 규칙 유지 | **손대지 않는다** |
| 저장소 | 등록 저장소 중 선택 | `project.repo_path` 를 `project_repository` 한 건으로 이행. Case 선택은 비어 있고 **암묵적 단일 저장소**로 표시 |
| 예산 | 설정 없음 = 무제한 | 같음 |

`autonomy = NULL` 을 `ask_on_decision` 으로 읽지 않는다. 화면과 API는 그 Case를
`미기록(v0.6 기준으로 진행)`으로 표시하고, R4가 그 Case를 자동 진행 대상으로 바꿀지는
**그때 사람에게 묻는다.** v0.6의 동작을 `controlled` 로 번역해 적지도 않는다 — v0.6에는
controlled의 시작·결과 확인 체크포인트가 없었고, 가장 가까운 값으로 적는 것은 있지도
않은 결정을 기록하는 일이다.

`case_policy` 행이 없는 상태의 의미는 **표마다 다르며 각각 적어 둔다.** 완료 정책과
단계 검토 설정에서 "행 없음"은 사람 확인이라는 기본값이었다(D-31·D-14). 예산에서 "행
없음"은 무제한이다(D-56). Autonomy에서 "행 없음"은 R1 이후 만들어진 Case라면 기본값
`ask_on_decision` 이고, 이행된 Case에는 행을 **명시로** 넣어 미기록임을 남긴다.

## 4. 새 표와 컬럼 (스키마 v8)

기존 표의 컬럼은 세 개만 더하고 나머지는 모두 새 표다. 새 표에 본문 컬럼은 없고 요약은
200자 상한을 스키마에 둔다(NFR-12·D-51).

| 표·컬럼 | 답하는 질문 |
|---|---|
| `case.profile` / `case.profile_version` / `case.profile_source` | 이 업무의 **대표 목적은 무엇이고 어느 Profile 정의판**으로 기록됐는가. 사람이 정했는가 유도했는가 |
| `project.journal_repository_id` | 기록 이슈를 어디에 만드는가. **코드 대상이 아니다** |
| `case_policy` | 이 Case에 적용되는 Autonomy와 그 출처·정책 버전·설정 주체. 이전 값은 `superseded` 로 보존 |
| `delegation_basis` | 지금 무엇을 근거로 자동 진행하는가(원 요청 / 사용자 후속 결정 / 정책). 누적 비교의 기준점 |
| `controlled_checkpoint` | controlled가 요구하는 확인 지점과 **실제 확인 여부·대상 해시·주체** |
| `budget_setting` | 어떤 지표에 경고·hard 한도를 걸었고 그 지표를 **측정·강제할 수 있는가** |
| `project_repository` | Project에 등록된 저장소들. 단일 `repo_path` 가정을 대체한다 |
| `case_repository` | 이 Case가 **선택한** 저장소와 **쓰기·게시 허용**. 셋은 서로 다른 집합이다 |

`intent_field.field` 는 값 집합만 넓힌다(표 변경 없음). Profile 필수 항목이 그 표에
같은 방식으로 상태·출처·변화 여부와 함께 들어간다 — 별도 표를 만들면 한 초안의 항목이
두 곳에 나뉘어 "사실·제안·미정 구별"이 항목 종류마다 달라진다.

## 5. Profile 정의 (버전 1)

`domain/profiles.py` 에 정의를 두고 `(profile, version)` 으로 조회한다. **공개한 버전은
고치지 않고 새 버전을 더한다.** Case는 자기 버전을 기록하므로 새 정의가 기존 Case에
소급되지 않는다(D-62).

| Profile | 공통 6항목 위에 요구하는 의미 항목 | 정상 완료의 의미 |
|---|---|---|
| `feature` | `need`, `usage_context`, `desired_behavior`, `acceptance_cases` | 합의한 기능·수용 기준 충족 |
| `defect_fix` | `observed_behavior`, `expected_behavior`, `expectation_basis`, `occurrence_conditions`, `restore_scope` | 기대 동작 복원 + 필요한 검증 |
| `root_cause_analysis` | `phenomenon`, `observations`, `cause_questions`, `conclusion_requirement`, `analysis_end_condition` | 합의한 종료조건 충족. 원인 확정이 필수면 미확정은 성공이 아님 |
| `research` | `research_questions`, `decision_purpose`, `evaluation_criteria`, `required_evidence`, `research_end_condition` | 합의한 조사·판단 조건 충족. 조건이 허용하면 판단 불가도 정상 |
| `refactoring` | `improvement_target`, `improvement_reason`, `target_boundary`, `preserved_contracts`, `improvement_criteria` | 개선과 보존 조건을 **함께** 충족 |
| `maintenance` | `maintenance_target`, `current_state`, `target_state`, `work_reason`, `preserved_conditions` | 특정한 유지 목표와 보존 조건 충족 |

정의에는 최소 증거 기대와 "초안에서 고정하지 않는 실행 상세"도 함께 둔다(case-profiles
2·4절). 이것은 **검사 목록이 아니라 의미 계약**이며, R1이 강제하는 것은 "항목이 행으로
존재하고 상태·출처가 구별되는가"까지다. 내용의 충분함은 QG-01의 AI 의미 검토와 사람의
판단이 본다.

## 6. 작업 순서

1. 이 plan 기록·공유.
2. `domain/profiles.py` 신설, `domain/models.py` 에 `CaseProfile`·`Autonomy`·`AutonomySource`·`DelegationBasisKind`·`ControlledCheckpoint`·`CheckpointState`·`BudgetMetric`·`BudgetThreshold`·`BudgetMeasurement`·`BudgetEnforcement`·`RepositorySelectionSource`·`PolicyRefusal` 추가, `POLICY_VERSION` 상수, `CaseKind` 에 `refactoring`·`maintenance`.
3. `controller/schema.sql` v8 구획 + `controller/db.py` 마이그레이션(컬럼 3개, 기존 Case·Project 이행).
4. `controller/repository.py`: Profile 기록, `effective_policy`, Autonomy 설정·이력, 위임 근거, controlled 체크포인트, 예산 설정(강제 불가 hard 거부), 저장소 등록·기록 저장소·Case 선택.
5. `controller/api.py`: 정책·Profile·저장소·예산·체크포인트 엔드포인트와 `create_case` 의 `profile`.
6. 의도 초안 경로: `domain/intent_doc.py` 문서 v4(Profile 항목), `apply_intent_structure` 필수 항목 검사, `controller/gate.py` 규칙의 필수 항목 집합, `runner/prompts.py`·`runner/agent.py` 의 Profile별 지시문, `assignment_payload` 에 Profile 전달.
7. `web/src/PolicyPanel.tsx` + `App.tsx`·`api.ts`: Profile·WorkDepth·Autonomy·예산·저장소와 **강제 여부** 표시.
8. 시험: `tests/test_policy.py` 신설, `test_migration.py`·`test_data_boundary.py`·`test_intent.py`·`test_admission.py` 확장.
9. 전체 시험(pytest + P1 계약), 재시작·마이그레이션 실제 확인, `npm run build`.
10. 라이브 1건: 실제 코딩 CLI가 비기능 Profile의 초안을 Profile 필수 항목까지 채우는지.
11. 증거 `p3/evidence/P3-R1-results.md`, DEVELOPMENT.md 현재 상태·진행표·plan 표·인계 갱신, R2를 READY로 인계.

## 7. 성공 기준 (AC)

| ID | 기준 | 검증 방법 |
|---|---|---|
| AC-1 | **여섯 Profile이 버전과 함께 정의되고 Case에 기록된다.** 정의에 의미 항목·최소 증거 기대·완료 의미가 있고, Case는 자기 `profile_version` 으로 정의를 조회한다. 사람이 지정한 Profile과 `kind` 에서 유도한 Profile을 출처로 구별한다 | 자동 시험(정의 6건 전수·버전 조회·출처 구별) + `GET /api/profiles` |
| AC-2 | **Profile별 의도 초안 항목이 강제된다.** 구조 보고는 공통 6항목 + 그 Profile의 필수 의미 항목을 모두 가져야 하고, 하나라도 빠지면 거부한다. 각 항목은 상태(미정/제안/사용자확정)와 출처를 따로 갖는다. **Profile이 없는 기존 Case는 6항목 그대로다** | 자동 시험 6 Profile 각 1건 + 누락 거부 1건 + Profile 없는 Case 1건 |
| AC-3 | **QG-01 규칙이 Profile 필수 항목을 본다.** 빠진 Profile 항목은 `required_field_missing` 필수 발견으로 잡히고, 기존 의도 버전의 과거 판정·발견은 바뀌지 않는다 | 자동 시험 2건 + 기존 게이트 시험 회귀 |
| AC-4 | **새 Case의 기본은 ask-on-decision이다.** 설정 없이 만든 Case의 정책 조회가 `ask_on_decision` / 출처 `system_default` / 정책 버전 `0.7` 을 준다. 명시 설정은 새 revision을 만들고 **이전 값을 `superseded` 로 보존**한다 | 자동 시험 3건 + 직접 API |
| AC-5 | **기존 Case에 새 기본값을 소급하지 않는다.** R1 이전 Case는 `autonomy` 미기록·출처 `migrated_unknown`·정책 버전 `0.6` 으로 남고 어디서도 `ask_on_decision` 으로 표시되지 않는다. 기존 동의·결정·완료 정책·단계 검토·종료 기록은 바이트 단위로 그대로다 | 마이그레이션 시험(실제 v7 DB) + 기존 행 대조 |
| AC-6 | **controlled 체크포인트가 영속화된다.** controlled로 설정하면 시작 범위·결과 후보 확인 지점이 `required` 로 생기고, 확인 기록은 주체·시점·대상 해시·결정 ID를 갖는다. ask-on-decision Case에는 생기지 않는다. **체크포인트 확인이 push·게시 권한이나 최종 인수를 만들지 않는다** | 자동 시험 5건(생성·확인·ask 경로 없음·권한 미생성·인수 미생성) |
| AC-7 | **쓰기 허용과 게시 허용이 분리된다.** Case의 저장소 선택·코드 쓰기 허용·게시 허용을 각각 기록하고, 쓰기 허용만으로 게시 허용이 생기지 않는다. 지정한 기록 저장소는 Case의 코드 대상에 자동으로 들어가지 않는다 | 자동 시험 4건 |
| AC-8 | **단일 저장소 데이터가 보존된다.** 기존 Project의 `repo_path` 가 `project_repository` 한 건으로 이행되고 값이 같다. 기존 작업공간 준비·배정·실행 경로는 그대로 동작한다. Case 선택이 없는 상태는 **암묵적 단일 저장소**로 표시되며 "선택했다"로 적지 않는다 | 마이그레이션 시험 + 기존 `test_workspace` 회귀 |
| AC-9 | **예산 설정 계약이 성립한다.** 설정이 없으면 무제한이다. 지표별로 경고·hard, 측정 방식(exact/estimated/unavailable), 강제 가능성을 함께 기록한다. **측정을 보장할 수 없는 지표의 정확한 hard 한도는 설정을 거부한다**(사유 코드). repair 한도와 별개임을 표시한다 | 자동 시험 6건(무제한 기본·경고·hard 허용·hard 거부·0 이하 거부·이력 보존) |
| AC-10 | **아직 없는 기능을 지원으로 표시하지 않는다.** 정책 조회가 Autonomy·체크포인트 차단·예산 강제·저장소 자동 추가를 `recorded_not_enforced` 와 담당 하위 작업(R2/R3/R4)으로 표시한다. hard 예산을 설정해도 이번 단계에서는 실행 배정·진입 검사 결과가 달라지지 않는다는 사실을 시험이 **명시적으로** 고정한다 | 자동 시험 3건(표기·진입 검사 불변·화면 문구) |
| AC-11 | **새 값이 기존 조건을 느슨하게 만들지 않는다.** `refactoring`·`maintenance` Case의 구현 요청은 기존 비기능 Case와 같은 거부 사유를 받고, 의도 버전이 생기면 기능 조건표로 바뀐다. Profile·정책 변경으로 성공 기준·예산 설정·질문·실패 이력·결정이 초기화되지 않는다 | 자동 시험 4건 |
| AC-12 | **직접 API 우회가 막힌다.** 없는 Profile·Autonomy 값, 음수·0 한도, 다른 Case의 저장소, 종료된 Case의 정책 변경, Profile 필수 항목 없는 구조 보고가 각각 거부된다. 화면을 거치지 않아도 같은 검사를 받는다 | 자동 시험 6건(HTTP 직접 호출) |
| AC-13 | **재시작 복원과 이행.** 제어부를 강제 종료해도 Profile·정책 이력·체크포인트·예산·저장소 기록이 그대로 복원된다. 실제 v7 커밋 스키마 DB에 v8을 적용해도 행이 사라지지 않고 없던 값을 지어내지 않는다(`schema_version = 8`) | 자동 시험(재시작·마이그레이션) + 실제 프로세스 강제 종료 대조 |
| AC-14 | **데이터 경계 유지.** 새 표에 본문 컬럼이 없고 모든 요약에 200자 상한이 스키마에 걸려 있다. 정책 변경 이유·Profile 항목 본문이 제어부 DB·WAL·로그 바이트에 없다 | 자동 시험(바이트 검사 확장) |
| AC-15 | **화면에 현재 정책이 보인다.** Profile·WorkDepth·Autonomy·예산·선택 저장소와 각 항목의 출처·강제 여부가 한 화면에서 보인다. 미기록과 기본값을 구별해 표시한다 | `npm run build` + 화면 문구 확인 |
| AC-16 | **라이브 1건.** 실제 코딩 CLI가 비기능 Profile 요청에서 Profile 필수 항목을 포함한 초안을 만들고, 구조 보고가 통과한다 | 실제 CLI 실행 기록(관측 버전·세션·산출물) |

AC-16은 여섯 Profile 전수 실증이 아니다. 전수는 P4-03의 몫이고, 여기서는 **지시문·문서
형식·구조 검사가 실제 AI 출력과 맞물린다**는 것만 확인한다. 실행하지 못하면 미검증으로
적고 통과로 적지 않는다.

## 8. 복구·인계

- 작업공간은 `C:\git\human-ai-dev-system-design` 이 checkout 하나다. 라이브 실행 데이터는
  `%LOCALAPPDATA%\Temp\hads-p3-r1-live` 에 두어 저장소 `var\` 와 기존 증거를 건드리지 않는다.
- 완료된 plan(P3-PLAN-01~03)과 P1~P3-03 증거는 수정하지 않는다. 과거 수치를 이번 결과로
  덮어쓰지 않는다.
- 되돌리기: 이 작업은 새 표와 컬럼만 더하므로 v7 코드로 되돌려도 기존 경로가 동작한다.
  단 v8 DB에 남은 새 행은 v7 코드가 읽지 않는다 — 그 사실을 증거에 적는다.
- 인계에는 실제 HEAD·미커밋 소유·남은 프로세스·다음 작업(R2)과 R1이 **강제하지 않는
  것의 목록**을 함께 남긴다.

## 9. 수정 기록

| 시점 | 무엇을 고쳤나 | 이유 |
|---|---|---|
| 2026-09-21 구현 중 | **`AdmissionProfile` 선택 규칙을 건드리지 않기로 했다.** 계획 2절에 이미 적었지만, 새 Profile 값을 조건표에 연결하는 방향을 실제로 검토한 뒤 접었다 | `defect_fix`·`refactoring` 을 기능 조건표로 보내면 그 Case 의 조사 실행까지 **사람의 의도 동의**를 요구하게 된다. v0.7이 없애려는 "일괄 의도 동의 장벽"(D-14·D-22)을 오히려 비기능 업무로 넓히는 셈이고, 그 판단은 Autonomy 를 읽는 R4의 몫이다. 대신 새 값이 기존 조건을 느슨하게 만들지 않음을 시험으로 고정했다(AC-11) |
| 2026-09-21 구현 중 | **`CaseKind` 에 `refactoring`·`maintenance` 를 더했다.** 계획의 새 표 목록에 없던 변경이다 | 여섯 Profile 중 둘은 v0.6 유형에 대응하는 값이 없었다. `refactoring` 을 `feature` 로 적으면 기록이 거짓이 되고, `kind` 를 NULL 로 두면 기존 NOT NULL 계약이 깨진다. Profile→kind 유도를 한 곳에 두고 값을 더하는 것이 두 기록을 모두 참으로 두는 방법이었다 |
| 2026-09-21 구현 중 | **`case.profile_source` 컬럼을 더했다**(계획에는 `profile`·`profile_version` 둘만 있었다) | 지정한 Profile 과 `kind` 에서 유도한 Profile 을 구별해야 한다(FR-04). 유도는 사람의 선택이 아니며, 구별하지 않으면 나중에 "사용자가 이 목적을 골랐다"는 근거로 쓰인다 |
| 2026-09-21 라이브 중 | **성공 기준의 대상 항목(`relates_to`)을 Profile 의미 항목까지 넓혔다.** 계획의 작업 순서에 없던 수정이다 | 라이브에서 codex 가 `improvement_target` 에 걸린 기준을 쓰자 구조 보고가 500으로 죽고 **초안 전체가 사라졌다.** Profile 항목을 만들면서 기준의 대상 집합을 함께 넓히지 않은 빈틈이다. 저장 계층은 `_field_name` 으로, 입력 계약은 문자열로 바꾸고 모르는 이름에는 409 + 사유를 준다. 자동 시험이 이 조합을 보지 못한 이유는 시험의 기본 기준이 공통 항목만 가리켰기 때문이며, 회귀 시험을 더했다 |
| 2026-09-21 검증 중 | **정책 거절을 구조(`{"refusals": [...]}`)로 내보냈다** | 인수 거절과 같은 방식이어야 화면과 직접 API 호출이 같은 코드를 근거로 설명할 수 있다(FR-29) |
| 2026-09-21 자체 검토 중 | **제외한 저장소를 선택 목록에서 뺐고, 암묵적 단일 저장소는 기록이 없을 때만 표시한다** | 계획에는 세 집합을 분리한다고만 적었고 구현이 제외를 선택 목록에 함께 넣고 있었다. 화면이 제외를 선택으로 보여 주고, R2 의 자동 추가가 제외 경계를 읽을 근거가 흐려진다 |
| 2026-09-21 자체 검토 중 | **후속 Case(`POST /successor`)가 `profile` 을 받는다** | 계획의 작업 순서에 없던 경로다. 완료한 기능의 수정 요청이 결함 수정일 수도 유지보수일 수도 있는데 `kind` 기본값으로 고정되면 목적이 시스템이 고른 값이 된다. 승계는 여전히 없다 |
