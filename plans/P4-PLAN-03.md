# P4-PLAN-03

여섯 Profile. 기준: 설계 v0.7 / D-01~67 / 2026-09-23.
선행: P4-02 완료(스키마 v14). 이 세션에서 `scripts\run-tests.ps1` 로 pytest **451**,
P1 계약 unittest **18** 통과를 다시 확인했다.
범위는 **P4-03 하나**다. 컨텍스트 재개(P4-04)·완료 경로 전반(P4-05)·지식(P4-06·07)·
외부 게시(P5)는 포함하지 않는다.

## 1. 현재 구현과 이 작업이 메울 차이

P3-R1이 여섯 Profile의 **의도 항목**을, P3-R4가 조사 Profile의 목적 경계(D-66)·로컬
실험·`satisfaction` 세 값을 만들었다. 그러나 **완료 판정은 Profile을 보지 않는다.**
`check_acceptance` 는 여섯 Profile 모두에 "현재 기준이 전부 `met`" 하나를 적용한다.
그래서 다음이 구현되어 있지 않다.

1. **목적별 완료 의미.** `ProfileDefinition.completion_meaning` 은 문장일 뿐 어떤 판정도
   그것을 읽지 않는다. refactoring 이 개선 기준만 갖고 보존 기준이 하나도 없어도,
   maintenance 가 목표 상태 기준 없이도 완료된다.
2. **충족 방식 생략 우회.** `satisfaction` 은 선택 값이다. `not_reproduced` 로 적으면
   `met` 이 거부되지만 **아무것도 적지 않으면** 받아들여진다 — "미재현만으로 해결을
   선언하지 않는다"가 생략 한 번으로 우회된다.
3. **판단 불가 결론.** RCA·research 의 결론이 확정인지 판단 불가인지, 그 Case 가 판단
   불가를 정상 결과로 허용하는지가 값으로 없다. "원인 확정이 필수면 미확정은 성공이
   아니다"와 "합의된 종료조건이면 판단 불가도 정상 결과"를 구별할 수 없다.
4. **혼합 목적.** "원인 확정과 수정"을 함께 요청해도 대표 Profile 하나만 남고, 원인 쪽
   기준이 하나도 없어도 수정 기준만으로 완료된다.
5. **실험과 제품 증거의 구분.** `run.is_experiment` 는 기록만 되고 어디서도 쓰이지
   않는다(모델 주석은 "결과 후보에서 제품 변경과 구별된다"고 적었지만 구현이 없다).
   실험 실행을 근거로 `changed_and_verified` 를 적을 수 있고, 실험이 작업공간에 임시
   변경을 남겼는지도 보지 않는다(DEVELOPMENT.md 9절 "P4-03 에서 다시 본다").

## 2. 범위

| 넣는 것 | 넣지 않는 것 (담당) |
|---|---|
| Profile 정의 **v2** — 목적별 완료 계약(필수 목적 의무, 항목→의무 대응) | v1 정의 수정(공개한 버전은 고치지 않는다) |
| 기준의 목적 의무(`obligation`)·출처, RCA/research 기준의 결론 요구(`conclusion_rule`) | 기준 본문의 의미 판정(제어부는 본문을 읽지 않는다) |
| 기준 결과의 충족 방식 필수화(v2)와 의무별 허용 방식·근거 실행 목적 | v1 기준의 규칙 변경(소급 없음) |
| 결론(`determined`/`inconclusive`)과 판단 불가의 허용 조건 | 예외 수용의 적절성 판정(P4-05) |
| 선언된 목적(혼합 목적)과 목적별 기준 커버리지, 완료 거부 사유 | **Profile 재분류 경로**(아래 3절 마지막) |
| 실험 근거의 사용 제한, 실험 정리 상태의 관측 도출, 잔여가 있으면 자동 완료 보류 | 실행 중 안전 정지·작업공간 밖 변경 차단(P6-03·D-44) |
| 의도 문서 v5, AI 지시문·파서, 결과 조회·후보·화면, 스키마 v15·이행 | 컨텍스트 고정·분할 검토(P4-04), 지식(P4-06·07), push·PR(P5) |
| 여섯 Profile 대표 흐름·혼합 목적·실패 경로의 자동 시험, 실제 CLI 의도 초안 확인 | 구현 실행의 판정 변경(무변경 구현 실행은 여전히 실패 — 3.4절) |

## 3. 설계

### 3.1 Profile 정의 v2와 완료 계약

`domain/profiles.py` 에 **정의판 "2"** 를 더하고 `CURRENT_PROFILE_VERSION = "2"` 로 올린다.
의미 항목은 v1과 같다. 달라지는 것은 `completion`(완료 계약) 하나이며 v1 정의에는 없다.
**새 Case 만 v2 를 받는다.** 기존 Case 는 기록된 `profile_version = "1"` 그대로이고 v1
규칙(계약 없음)을 따른다 — 새 정의를 조용히 소급하지 않는다(D-62).

목적 의무(`CriterionObligation`)는 일곱이다.

| 의무 | 뜻 | 허용 충족 방식(`met`) | 근거 |
|---|---|---|---|
| `behavior` | 합의한 동작·결과 | `changed_and_verified`, `already_satisfied` | 실험 실행 불가 |
| `restoration` | 근거 있는 기대 동작 복원 | `changed_and_verified`, `already_satisfied` | 실험 실행 불가. `not_reproduced` 는 어느 경우에도 `met` 불가 |
| `cause` | 원인 질문에 요구 수준으로 답함 | `investigated` | 조사 목적 실행(분석·실험·검증) 또는 사람 판단. 결론 필수 |
| `answer` | 조사 질문에 종료조건대로 답함 | `investigated` | 같음. 결론 필수 |
| `improvement` | 개선 목표 달성 | `changed_and_verified`, `already_satisfied` | 실험 실행 불가 |
| `preservation` | 보존 계약·조건 유지 | `preserved` | 검증 실행 또는 사람 판단. 실험 불가 |
| `target_state` | 유지 대상의 목표 상태 | `changed_and_verified`, `already_satisfied` | 실험 실행 불가 |

`already_satisfied` 는 기존대로 실행 근거를 요구하고, v2 에서는 그 실행이 **검증 실행**
이어야 한다 — "이미 목표 상태임을 관측했다"는 주장의 근거가 임시 변경 위의 관측이면 안
된다.

Profile 별 필수 의무:

| Profile | 필수 의무 | 조건부 |
|---|---|---|
| feature | `behavior` | — |
| defect-fix | `restoration` | — |
| root-cause-analysis | `cause` | — |
| research | `answer` | — |
| refactoring | `improvement`, `preservation` | — |
| maintenance | `target_state` | `preserved_conditions` 항목이 채워졌으면 `preservation` |

항목→의무 대응: 공통 여섯 항목은 그 Profile 의 **주 의무**(표의 첫째), 의미 항목은
정의가 정한 의무다(refactoring 의 `preserved_contracts`, maintenance 의
`preserved_conditions` 는 `preservation`, 나머지는 주 의무).

### 3.2 기준의 의무와 결론 요구

- 의도 문서 **v5** 는 기준마다 `obligation`(선택)과, `cause`/`answer` 기준에
  `conclusion_rule`(`definitive_required` | `bounded_report_allowed`, 선택)을 적는다.
- 제어부는 v2 Case 기준의 의무를 **보고값이 있으면 그것으로, 없으면 연결 항목에서
  정의로 도출**하고 출처(`reported` | `derived_from_field`)를 남긴다. 도출은 공개된
  정의의 대응표를 적용하는 것이지 본문을 읽는 것이 아니다.
- `conclusion_rule` 이 없으면 **값은 NULL 로 두고 `definitive_required` 로 취급**한다 —
  모르는 것을 느슨한 쪽으로 읽지 않는다.
- 기준 지문에 의무·결론 요구를 **값이 있을 때만** 더한다. 결론 요구를 약화하거나 의무를
  바꾸면 지문이 달라져 material delta 가 된다. v1 기준(둘 다 NULL)의 지문은 그대로다.

### 3.3 결과 기록 규칙 (v2 기준의 `met`)

1. 충족 방식이 필수다 — 생략하면 `satisfaction_required`.
2. 의무에 허용되지 않은 방식은 거부한다.
3. `cause`/`answer` 는 결론(`determined` | `inconclusive`)이 필수다. `inconclusive` 로
   `met` 을 적으려면 그 기준의 결론 요구가 `bounded_report_allowed` 여야 한다. 원인
   확정이 필수인 RCA 의 판단 불가는 `not_met`(결론 `inconclusive`)이며, 닫으려면 사람의
   예외 수용이다 — 원래 판정은 보존된다.
4. 실험 실행(`is_experiment`)은 `investigated` 의 근거로만 쓴다. 제품 의무의 근거가 되지
   않는다 — "증거와 임시 변경을 구분한다"(D-66).
5. 결론은 `cause`/`answer` 기준에만 붙는다. 새 방식(`investigated`·`preserved`)과 결론은
   v1 기준에서 받지 않는다 — v1 기준은 v1 규칙 그대로다.

### 3.4 무변경 성공

- defect-fix·feature·maintenance: **구현 실행 없이** 검증 실행이 목표 상태를 관측하면
  `already_satisfied` 로 완료할 수 있다. 구현 실행 자체의 판정("변경도 명령도 없으면
  실패")은 바꾸지 않는다 — 무변경 완료는 구현 실행의 성공이 아니라 검증 실행의 관측이
  근거다.
- RCA·research: 코드 산출물 없이 조사 실행의 근거로 완료한다(`investigated`).

### 3.5 선언된 목적과 커버리지

- 의도 문서 v5 에 `objectives`(요청이 명시한 목적 의무 목록)를 둔다. 구조 보고는 목록만
  올린다. v2 에서 요구 의무 = Profile 필수 ∪ 조건부 ∪ 선언된 목적.
- **요구 의무마다 현재 기준이 하나 이상 있어야 한다.** 없으면 완료 후보의 미해결 항목
  `objective_without_criteria` 이며 자동·사람 인수 모두 거부된다. 기준이 아니므로 예외
  수용 대상도 아니다 — 목적을 빼려면 의도·기준 변경(material delta) 경로를 탄다.
- 목적의 기준이 `met` 이 아니면 기존 미해결 기준 규칙으로 막힌다. 그래서 "원인 확정과
  수정" 중 수정만 성공하면 완료되지 않는다.
- 조사 Profile 의 제품 수정 차단(D-66)은 그대로다. 선언된 목적이 차단을 풀지 않는다.

### 3.6 실험의 정리 상태

실험 실행마다 작업공간 관측으로 정리 상태를 **도출한다**(저장하지 않는다).

| 상태 | 조건 |
|---|---|
| `restored_in_run` | 실행 전후 트리 지문·HEAD 가 같다 |
| `restored_later` | 같은 저장소의 뒤 실행이 실험 전 지문에서 시작하거나 그 지문으로 끝났다 |
| `left_changes` | 위 둘이 아니다 |
| `unobserved` | 쓰기 권한 실행인데 관측이 없다 |
| `no_write_permission` | 읽기 권한 실행이다 |
| `not_finished` | 아직 끝나지 않았다 |

`left_changes`·`unobserved` 가 **잔여**다. 요구 의무에 제품 의무가 있는 v2 Case 에서
잔여가 있으면 자동 완료하지 않는다(`experiment_residue_unresolved`). 사람 인수는 막지
않되 후보에 잔여가 드러난다 — 미정리 실행과 같은 모양이다. 조사 목적만 있는 Case 는
표시만 한다. 작업공간 밖 변경 감지(`outside_workspace_changed`)도 함께 보인다.
관측은 격리가 아니다(D-44) — "임시 변경만 했다"를 증명한다고 표시하지 않는다.

### 3.7 조회·후보·화면

- 결과 조회에 `completion_meaning`(계약 유무·요구 의무별 기준·충족 수·누락·실험 정리)을
  더하고 기준마다 의무·출처·결론 요구(유효값)·결론을 보인다.
- 완료 후보는 v2 Case 에서만 `meaning` 을 스냅샷에 담는다. **v1 Case 의 후보 내용·해시는
  바뀌지 않는다** — 바뀌면 controlled 결과 확인이 소급으로 낡는다.
- 화면: 목적별 충족 현황, 기준의 의무·결론, 실험 정리 상태, 결과 기록 폼의 의무별 방식·
  결론 선택.

### 3.8 넣지 않는 것 — Profile 재분류

인수 매트릭스 AC-07 의 "재분류" 부분은 이번에 만들지 않는다. 재분류는 다음 의도 버전의
**항목 집합**을 바꾸고(기준의 `relates_to` 가 가리킬 항목이 사라진다), 그것을 어떻게
이을지는 의도 구조의 결정이다. 지금은 재분류 경로가 없으므로 "재분류로 한도·실패·기준을
초기화하지 않는다"는 여전히 성립한다. 이번 설계는 재분류가 생겨도 느슨해지지 않게
**선언된 목적을 Profile 이 아니라 의도에 둔다.** AC-07 의 "원인 확정+수정은 양쪽을
충족" 부분은 3.5절이 맡는다.

## 4. 저장·API

스키마 **v15**.

- `success_criterion` + `obligation`·`obligation_source`·`conclusion_rule`
- `criterion_result` + `conclusion`
- `intent_version` + `objectives_json`(NULL = 보고되지 않음)
- `completion_candidate` + `meaning_json`(v1 Case 는 NULL)
- 값은 열거형 `CHECK`, 본문 컬럼 없음.

이행 v14→v15 는 컬럼만 더한다. 기존 기준의 의무를 **지어내지 않고**(NULL), 기존 Case 의
`profile_version` 을 올리지 않으며, 후보·판정을 바꾸지 않는다. 반복 이행이 멱등이다.

API: 결과 기록에 `conclusion`, 구조 보고에 `objectives`, 사람 입력 초안에
`objectives`·기준 `obligation`·`conclusion_rule`, 결과 조회에 `completion_meaning`.

## 5. 성공 기준

| 기준 | 내용 |
|---|---|
| AC-1 | 새 Case 는 Profile 정의 v2 에 고정되고, v1 Case 는 v1 규칙 그대로다(충족 방식 없는 `met` 허용, 계약 거부 없음, 후보 해시 불변) |
| AC-2 | 여섯 Profile 의 완료 계약(필수·조건부 의무, 허용 방식)이 정의·조회된다 |
| AC-3 | v2 기준이 의무를 가진다. 보고값과 항목 도출을 출처로 구분한다 |
| AC-4 | v2 기준의 `met` 은 충족 방식을 요구하고 의무에 허용된 방식만 받는다 — 생략으로 미재현 차단을 우회할 수 없다 |
| AC-5 | defect-fix: 구현 실행 없이 검증 실행의 관측(`already_satisfied`)으로 완료할 수 있고, 미재현은 `met` 이 되지 않는다 |
| AC-6 | RCA: 원인 확정 필수(또는 결론 요구 미기록)이면 판단 불가로 `met` 불가, 자동 완료 없음, 사람 예외 수용 뒤에도 원래 판정 보존 |
| AC-7 | research: 판단 불가 허용 기준은 근거 있는 판단 불가로 `met` 이 되어 코드 변경 없이 자동 완료된다. 조사 근거 실행 목적이 제한된다 |
| AC-8 | refactoring: 개선·보존 기준이 모두 있어야 완료되고 보존은 검증 실행·사람 판단으로만 충족된다 |
| AC-9 | maintenance: 목표 상태 기준이 필수이고, 보존 조건 항목이 채워졌으면 보존 기준도 필수다 |
| AC-10 | 혼합 목적: 선언된 목적마다 기준이 필요하고, 일부 목적만 충족하면 완료되지 않는다 |
| AC-11 | 목적 누락은 자동·사람 인수 모두 거부하며 예외 수용 대상이 아니다 |
| AC-12 | 실험 실행은 조사 근거로만 쓰이고 제품 의무의 근거가 되지 않는다 |
| AC-13 | 실험 정리 상태가 관측에서 도출되고 작업공간 밖 변경 감지가 함께 보인다 |
| AC-14 | 제품 목적 v2 Case 에 잔여 실험이 있으면 자동 완료하지 않고 사람 인수 후보에 드러난다. 조사 목적만이면 표시만 한다 |
| AC-15 | 결론 요구 약화·의무 변경은 material delta 이고, v1 기준 지문은 바뀌지 않는다 |
| AC-16 | 의도 문서 v5 가 목적·의무·결론 요구를 담고 구조 보고는 열거값만 올린다. v1~v4 문서를 계속 읽는다 |
| AC-17 | v2 Profile 의 AI 지시문이 목적·의무·결론 요구를 요구하고 파서가 읽는다. 실제 CLI 로 확인한다 |
| AC-18 | 결과 조회·후보·화면이 목적별 충족 현황·결론·실험 정리를 구분해 보인다 |
| AC-19 | v14→v15 이행이 기존 기준·판정·후보·Profile 버전을 보존하고 의무를 지어내지 않으며 멱등이다 |
| AC-20 | 재시작 뒤 의무·결론·목적·후보 meaning 이 복원된다 |
| AC-21 | 기존 경계 유지: `enforcement` 네 축·게시 미강제·조사 Profile 의 제품 수정 차단. 새 기능이 권한을 만들지 않는다 |

## 6. 검증

1. 순수 규칙 단위 시험: 의무 도출, 방식 허용표, 결론 규칙, 커버리지, 실험 정리 도출.
2. 여섯 Profile 대표 흐름 시험(API 하네스): feature, defect-fix(무변경·미재현·생략 우회),
   RCA(확정 필수 판단 불가 → 예외 종료), research(판단 불가 정상 완료), refactoring
   (보존 누락·보존 충족), maintenance(조건부 보존), 혼합 목적, 실험 근거·잔여.
3. v1 호환 시험: v1 Case 의 기존 동작과 후보 해시 불변.
4. 이행 시험: 커밋된 v14 스키마 DB 를 v15 로 두 번 연다.
5. 재시작: 파일 DB 재개로 의무·결론·목적·meaning 복원.
6. 전체 제품 시험 `scripts\run-tests.ps1`(pytest 수와 P1 계약 18 을 따로 보고), 웹
   `npm run build`.
7. 실제 CLI: 새 지시문 계약이므로 실제 `codex` 로 의도 초안을 쓰게 해 v5 문서의 목적·
   의무·결론 요구를 확인한다(혼합 목적 defect-fix 1건, research 1건, 그리고 보존 기준이
   개선 기준과 따로 적히는지 보는 refactoring 1건 — 구현 중 더함). 스크립트는
   `p4/live/profile_intents.py`. 라이브 데이터는 `%LOCALAPPDATA%\Temp\hads-p4-03-live` 에
   두고 저장소 `var\` 를 건드리지 않는다.

기존 시험이 v2 새 Case 에서 충족 방식 없이 `met` 을 적고 있으면 **의미를 검토해** 방식을
명시하도록 고치고, v1 동작은 새 호환 시험으로 따로 고정한다. 검사를 지우지 않는다.

## 7. 구현 순서

1. `domain` 순수 규칙(`completion_meaning.py`, profiles v2, 열거형)과 단위 시험.
2. 의도 문서 v5·지시문·파서.
3. 스키마 v15·이행.
4. 저장 계층: 기준 의무 반영, 결과 기록 규칙, 후보 meaning·거부 사유, 실험 정리 도출.
5. API·화면.
6. 기존 시험 의미 검토·갱신, 대표 흐름·호환·이행·재시작 시험.
7. 전체 검증, 실제 CLI, diff 검토.
8. `p4/evidence/P4-03-results.md`, 이 plan 완료 기록, `DEVELOPMENT.md` 갱신.

## 8. 시작 관측

- `main`, HEAD `f6145f4`(P4-02 커밋), `origin/main` 과 같다. 작업 트리 clean.
- 기준선: `scripts\run-tests.ps1` → pytest **451**, P1 계약 unittest **18** 통과(이 세션).
- 외부 쓰기·commit·push·PR 허용은 받지 않았다. 결과는 작업 트리에 남겨 인계한다.

## 9. 완료 기록

- **상태: 완료(2026-09-23).** 범위는 P4-03 에 머물렀다. 강제 축은 넷 그대로이며 이 작업이
  더한 것은 **완료가 무엇을 뜻하는가**다. Profile 재분류는 3.8절대로 만들지 않았다.
- AC-1~21 을 구현·시험으로 확인했다. 상세 연결은
  [P4-03 실행 결과](../p4/evidence/P4-03-results.md)에 있다.
- **구현 중 plan 에서 바꾼 것:** 7절 실제 CLI 에 refactoring 1건을 더했다(보존 기준이 개선
  기준과 따로 적히는지 보려고). 3.3절의 근거 규칙을 `already_satisfied`·`preserved` 모두
  "검증 실행의 관측"으로 통일했다(`observation_needs_verification_run`). 결과 화면에
  충족 방식 선택이 **아예 없었다**는 것을 구현 중 발견해 7번 단계에서 함께 넣었다.
- 최종 검증은 제품 pytest **481**, P1 계약 unittest **18**, 웹 `npm run build` 통과다.
  P4-03 집중 **29**, 이행 집중 **10**(v14→v15 신규 1건)을 포함한다.
- 실제 CLI: `codex-cli 0.154.0` 으로 의도 작성 3회, 세 건 모두 새 출력 계약을 지켰다
  (결과 3절). 표본은 세 건뿐이다.
- 결과는 `main`/`f6145f4` 위에 **사용자 지시로 커밋·push** 했다(`bf86590`). 그 허용은 이
  변경에만 적용되며 다음 변경은 다시 확인받는다. PR 은 만들지 않았고 제품의 외부 게시는 P5다.
