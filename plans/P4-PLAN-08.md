# P4-PLAN-08 — 여섯 Profile 대표 흐름의 진행기 경유 재현(defect-fix·refactoring·maintenance) + 혼합 목적의 완료

상태: **READY — 기록만, 착수하지 않음**(S-033, 2026-09-24). [P4 수용 확인](../p4/evidence/P4-ACCEPT-results.md) 1.1·1.2·4절이 "빠진 것" 으로
가른 묶음이다. 착수 여부는 사용자의 결정이다(P4 수용 결과 7절). 기준: 설계 v0.8 2차 / D-47·62·66·86 / [case-profiles](../case-profiles.md)
4·5·6절 / [DEVELOPMENT](../DEVELOPMENT.md) 6절 "P4 완료 조건". 선행: P4-03(완료 계약), P4-05(진행기), UI-04c(개정), 시험 도구
`tests/conftest.py`(`processing_harness`·`FakeCliExecutor`·`met_satisfaction_for`).

**이 plan 의 목표는 시험이다.** 제품 코드는 시험이 결함을 드러낼 때만 고친다(그 경우 결과 문서에 결함·수정을 적는다). 새 기능·새 정책·
스키마 변경·새 화면은 없다. 완료된 plan 을 다시 열지 않는다.

## 0. 제품 판단 — 새로 내리지 않는다

정할 것은 "무엇을 대표 흐름으로 삼는가" 뿐이며 case-profiles 4절의 완료 의미와 6절 시나리오 6·7·8·10 을 그대로 쓴다. 상세 설계 선택:
대표 흐름은 진행기의 실제 경로(업무화 → 의도 초안 → QG-01 → 동의 → 결합 기록/설계·계획 → 작업 그래프·작업공간 → 구현·검증 →
기준 판정 → 완료/미완료)를 가짜 CLI(`FakeCliExecutor`)의 정해진 응답으로 지난다 — 실제 codex 는 선택 사항이다.

## 1. 현재 구현과 차이(코드 대조)

- `domain/work_flow.py`: 조사 Profile 둘만 `_analysis_phase`, 제품 변경 Profile 넷은 준비·그래프·완료 단계 공용. `decide_criteria` 가
  `preservation` → `preserved`, 변경 미관측 → `already_satisfied`, `cause`/`answer` → `investigated` 를 정한다. 이 분기 중 진행기 시험이
  지나는 것은 `changed_and_verified`·`investigated` 뿐이다.
- `domain/completion_meaning.py`(P4-03)의 `check_result` 와 `domain/models.py` 의 `CriterionObligation`: refactoring 은 `improvement` +
  `preservation`, defect-fix 는 `restoration`(+ 선언 목적 `cause`), maintenance 는 `target_state` + 조건부 `preservation`(`profile_conditional`)
  — API 시험(`tests/test_profile_completion.py`)이 고정.
- `tests/conftest.py` 의 가짜 CLI: 검증 실행의 기준 보고에 `met_satisfaction_for(obligation)` 로 의무별 방식을 적는다(`preservation` →
  `preserved`). 구현 실행은 쓰기 권한 실행에서만 파일을 쓴다(UI-04d) — "변경 없음" 시나리오는 구현 실행이 파일을 쓰지 않게 하거나
  계획이 구현 Task 를 두지 않는 응답이 필요하다(`HADS_FAKE_*` 표지 또는 응답 재사용 규칙 확장 — 시험 도구 변경, 제품 아님).

## 2. 범위

1. **defect-fix 대표 둘**: (a) 증상 재현 → 수정 → 검증으로 `restoration` 이 `changed_and_verified` 로 닫힘, (b) 이미 고쳐진 결함 —
   구현 실행 없이(또는 변경 없이) 검증 실행이 관측해 `already_satisfied` 로 닫힘; 미재현 보고는 `met` 이 되지 않음(구조 검사).
2. **refactoring 대표**: 개선 기준과 보존 기준이 각각 검증 실행의 근거로 `changed_and_verified`·`preserved` 가 되어 닫힘; 보존 기준의
   판정이 없으면 닫히지 않음(`objective_without_criteria` 또는 미해결 → 예외 카드).
3. **maintenance 대표**: 목표 상태 기준으로 닫힘; 보존 조건을 적은 Case 는 보존 기준 없이는 닫히지 않음(`profile_conditional`).
4. **혼합 목적의 완료**: (a) RCA → defect_fix 개정(UI-04c) 뒤 동의 → `cause`(유지 목적)와 `restoration` 이 각각 판정돼 닫힘; (b) 한쪽만
   충족(예: 수정만)이면 닫히지 않고 예외 카드; (c) 처음부터 defect_fix + 선언 목적 `cause` 인 Case 도 같은 규칙.
5. 브라우저 시험 하나(선택 — 새 화면의 결정 사항 패널이 목적별 완료 의미·판정을 그대로 보이는지)는 기존 화면 시험이 충분하면 생략.
6. **넣지 않는 것**: 분석 재실행 규칙 변경, QG-02~07 진행기 실행, 실제 검증 환경(인터프리터) 문제, Profile 재분류의 새 경로, 새 화면.

## 3. 방법

- `tests/test_profile_flows.py`(새) 또는 `tests/test_work_progressor.py` 에 Profile 별 진행기 시험을 더한다. `processing_harness` 로 업무화 →
  동의 → 자동 진행을 돌리고 종료 상태·`completion_meaning`·기준별 `satisfaction`·`recorded_by = policy:work_progressor` 를 단언한다.
- 가짜 CLI 응답: 검증 보고에 기준별 판정(`preserved`·`already_satisfied` 는 `decide_criteria` 가 정하므로 보고는 `met` 만)과 명령 기록
  (종료 코드 0)을 싣는다. "변경 없음" 은 구현 Task 없이 검증 Task 만 두는 계획 응답(`HADS_FAKE_WORK` 확장) 또는 파일을 쓰지 않는 구현
  응답으로 만든다 — 어느 쪽이든 시험 도구의 변경이며 제품 규칙이 아니다.
- 기존 시험의 의미는 바꾸지 않는다(검사를 지우지 않는다). 시험이 제품 결함을 드러내면 고치고 결과 문서 4절에 적는다.
- 선택 사항: `p4/live/profile_intents.py` 를 재사용해 실제 codex 의 maintenance·RCA 의도 작성 표본을 남긴다(관찰).

## 4. 성공 기준

| AC | 기준 |
|---|---|
| AC-1 | defect-fix (a): 진행기 경유로 `restoration` 이 검증 실행 근거·`changed_and_verified` 로 `met` 이 되고 자동 완료된다 |
| AC-2 | defect-fix (b): 구현 변경 없이 검증 실행이 관측해 `already_satisfied` 로 닫힌다; 구현·실험 실행만 있으면 닫히지 않는다; `not_reproduced` 보고는 `met` 이 되지 않는다 |
| AC-3 | refactoring: 개선·보존 기준이 각각 `changed_and_verified`·`preserved` 로 닫힌다; 보존 기준의 판정이 없으면 예외 카드에서 멈춘다(자동 완료 없음) |
| AC-4 | maintenance: 목표 상태 기준으로 닫힌다; 보존 조건이 있는 Case 는 보존 기준 없이는 닫히지 않는다 |
| AC-5 | 혼합 목적: (a) 양쪽 판정 → 종료, (b) 한쪽만 → 예외 카드(원래 판정 보존), (c) 개정 경로와 처음부터 선언 경로가 같은 결과 |
| AC-6 | 여섯 Profile 모두 강제 축·진입 검사·정책이 그대로다(조사 Profile 의 쓰기 가드·controlled·예산 — 기존 시험 통과), 새 시험은 늘기만 한다 |
| AC-7 | 전체 `scripts\run-tests.ps1` 통과, 결과 문서에 Profile 별 근거 표(계약·흐름·라이브)를 P4 수용 결과 1.1절과 같은 모양으로 갱신 |
| AC-8 | 실제 codex 의도 작성(maintenance·RCA): **선택 사항** — 하지 않으면 미수행으로 적는다 |

## 5. 검증

새 시험 파일 + 기존 `tests/test_profile_completion.py`·`test_work_progressor.py`·`test_profile_revision.py` 통과, 전체 `scripts\run-tests.ps1`.
기준선은 착수하는 세션의 시작에 다시 잡는다(이 plan 을 쓴 S-033 의 기준선은 P4 수용 결과 5절).

## 6. 경계

- 강제 축 넷·`enforcement`·진입 검사·정책·스키마 v27 은 그대로다. 시험이 결함을 드러내 제품을 고치면 그 diff 만이며 정책 변경이 아니다.
- 이 plan 이 끝나도 실제 codex 가 검증 실행에서 시험을 돌리는 문제(DEVELOPMENT 9절)는 그대로다 — 별도 질문(P4 수용 결과 7절 2).

## 9. 알려진 한계·선택

- 대표 흐름은 가짜 CLI 의 정해진 응답이므로 "제품이 그 판정을 어떻게 적는가" 를 고정할 뿐 AI 가 실제로 그렇게 보고하는가는 라이브의
  관찰이다. maintenance 의 실제 codex 표본은 지금까지 없다.
