# P3-01 수준·설계·계획 — 실행 결과

수행일: 2026-09-21. 계획: [`P3-PLAN-01`](../../plans/P3-PLAN-01.md).

이 문서는 **실제로 실행한 것만** 적는다. 자동 시험(가짜 실행기)과 실제 코딩 CLI 실행을
구분하고, 검증하지 않은 항목은 9절에 미검증으로 남긴다.

## 1. 실행 환경

| 항목 | 값 | 확인 방법 |
|---|---|---|
| OS | Windows 11 Home 10.0.26200 | P2-04와 동일 |
| 셸 | PowerShell 7 | 〃 |
| Python(고정) | 3.12.10 — 저장소 로컬 `.venv` | `.venv\Scripts\python.exe --version` |
| Node / npm | v22.15.1 | `npm run build` 출력 |
| 제어부 스키마 | **v5** | `GET /api/health` → `schema_version=5` |
| Codex CLI | **codex-cli 0.154.0** | 실행마다 결과에 남은 관측 버전 |
| Claude Code | **2.1.278 (Claude Code)** | 〃 |
| 브라우저 | Microsoft Edge | Playwright `channel="msedge"` |
| OpenCode | **없음** | P1-04와 같음 |

두 CLI 모두 자동 업데이트가 켜져 있어 실행 시점의 관측 버전을 함께 남긴다.
시스템은 두 CLI의 **자격증명을 읽지도 주입하지도 않았다.**

브라우저는 **이 PC에 이미 있는 Edge 를 썼다.** 검증을 위해 브라우저를 내려받지 않았다.

라이브 실행 데이터는 `%LOCALAPPDATA%\Temp\hads-p3-01-live` 에 두어 저장소 `var\` 를
건드리지 않았다. CLI의 작업공간도 같은 곳의 별도 임시 git 저장소(`workspace\`, 파일
`reader.py` 와 `sample.log`)이며 **이 설계 저장소를 CLI에 노출하지 않았다.**

## 2. 만든 것

**"이 정도 준비가 필요한 이유"가 먼저 보이고, 그 준비가 실제로 갖춰진 뒤에만 기능
구현이 배정된다.** P2까지 `feature_implementation` 은 늘 거부됐고 여기서 처음으로
허용되는 경로가 생겼다.

| 조각 | 무엇을 하는가 |
|---|---|
| `controller/sizing.py` | 일곱 축에서 수준을 도출한다. **평균을 내지 않는다.** 근거 부족을 낮음으로 읽지 않는다 |
| 의도 문서 v3 (`domain/intent_doc.py`) | 축별 `근거 / 판단 / 미확인 / 영향`이 의도 문서 안에 들어왔다. v1·v2 문서의 축은 0건이고 그 Case 는 **수준 미결정** |
| `sizing_assessment` / `sizing_axis` | AI 제안·사람 판단·사람 조정을 `source` 로 구별한다. 제안·도출·적용 수준을 **셋 다** 남긴다 |
| `domain/prep_doc.py` | 설계·계획의 정규 문서. 수준별 필수 항목 표가 여기 있다. 요구하지 않는 항목도 삭제하지 않고 `undecided` 로 남는다 |
| `preparation_artifact` / `preparation_section` | 두 산출물이 각각의 버전·항목 상태·검토를 갖는다. 어느 의도 버전 위에 세웠는지가 함께 남는다 |
| `stage_review_setting` / `stage_review` | 단계별 검토 방식과 기록. **자동 진행은 `decision` 행을 만들지 않는다** |
| `run_context_ref` | 작성 실행에 고정한 참조 목록. P2-04가 남긴 위험 1의 해소 |
| `controller/admission.py` | `prerequisite_not_implemented` 한 줄 거부를 **실제 선행 조건 검사 10가지**로 바꿨다 |
| `web/src/PreparationPanel.tsx` | 축별 판단 표·수준 조정·두 단계의 산출물·원문 열람·검토 |

### 세 종류의 기록을 합치지 않는다

P2-04가 인수·예외·종료를 나눈 것과 같은 이유다.

| 기록 | 답하는 질문 |
|---|---|
| `sizing_assessment` | 이 업무에 **어느 정도 준비**가 필요한가 |
| `preparation_artifact` | 설계안·개발계획이 **실제로 존재**하는가 |
| `stage_review` | 그 산출물을 **사람이 검토**했는가, 또는 자동 조건이 충족됐는가 |

FR-05가 요구하는 "산출물 존재, 품질 판정, 사람 검토는 구분한다"를 표 수준에서 지킨다.
그리고 **`decision` 표에 행을 만드는 것은 사람 검토 경로뿐이다.**

## 3. 자동 시험

`scripts\run-tests.ps1` → **pytest 169건 통과** + P1 OpenCode 문서 계약 unittest 18건 통과.
P2-04의 기준선은 123건이었고 **46건이 늘었다.**

| 파일 | 무엇을 보는가 |
|---|---|
| `tests/test_sizing.py` (신규 12건) | 축 도출 규칙(평균 아님·근거 부족·빠진 축), 조용한 하향 차단, 사람 조정의 필수 입력과 **부작용 없음** |
| `tests/test_preparation.py` (신규 30건) | 기본값·각각 조회·자동 진행의 구별·수준별 필수 항목·**수준 상향이 기존 산출물을 부족하게 만드는 것**·오래된 승인·이월 질문·구현 배정 개방·쓰기 권한 차단·고정 컨텍스트·실행 경로 없는 목적의 깨끗한 실패 |
| `tests/test_data_boundary.py` (+3) | 축별 근거·설계 본문의 바이트 비보관, v5 표의 본문 컬럼 없음, 제어부가 산출물 본문을 해석하지 않음 |
| `tests/test_migration.py` (+) | v5 표 생성, **설정·수준 판단 행을 만들지 않음**, 질문 표의 새 컬럼 |
| `tests/test_restart_recovery.py` (+1) | 실제 uvicorn `taskkill /F /T` 후 수준·조정 이력·검토 모드·검토 기록 복원 |
| `tests/test_admission.py`·`test_completion.py`·`test_idempotency.py` (수정) | P2 시절 기대를 새 동작으로 옮김(3절 끝 참고) |

**자동 시험은 실제 CLI를 부르지 않는다.** `tests/conftest.py` 의 `FakeCliExecutor` 를 쓴다.

수정한 세 시험은 기준을 **느슨하게 한 것이 아니다.**

- `test_admission.py`: 한 줄 거부 대신 `design_missing`·`plan_missing` 을 각각 확인하고
  `prerequisite_not_implemented` 가 **더 이상 발급되지 않는다**는 것까지 본다.
- `test_completion.py`: 준비 부족 사유와 쓰기 권한 사유가 **서로 다른 것**임을 확인한다.
- `test_idempotency.py`: 결과 보고 유실이 예외로 루프를 죽이는 대신 **행동 기록에
  남는다**는 것을 확인한다. 핵심 보장(실행 부수효과 1회, 재배정 시 저장된 결과 재전송)은
  그대로다.

## 4. 라이브 검증 — 실제 CLI로 수준·설계·계획

증거: [`P3-01-live.log`](P3-01-live.log)(전 구간),
[`P3-01-preparation.json`](P3-01-preparation.json),
[`P3-01-admission-checks.json`](P3-01-admission-checks.json),
[`P3-01-case.json`](P3-01-case.json).

원문은 [`P3-01-intent-original.txt`](P3-01-intent-original.txt),
[`P3-01-intent-v2-original.txt`](P3-01-intent-v2-original.txt),
[`P3-01-design-original.txt`](P3-01-design-original.txt),
[`P3-01-plan-original.txt`](P3-01-plan-original.txt).

시험용 Case: "로그에서 오류 줄만 뽑는 기능". 작업공간의 `reader.py` 에 ERROR 줄만
돌려주는 함수를 더하는 작은 기능이다.

### 4.1 실제로 실행한 CLI

| 실행 | 목적 | 도구 | 결과 |
|---|---|---|---|
| `run-draft-1` | `intent_authoring` | codex 0.154.0 | completed |
| `run-review-1` | `intent_gate_review` | claude 2.1.278 | completed |
| `run-design-1` | `design_authoring` | claude 2.1.278 | completed |
| `run-plan-1` | `plan_authoring` | codex 0.154.0 | completed |
| `run-draft-stale` | `intent_authoring` (재작성) | codex 0.154.0 | completed |
| `run-review-v2` | `intent_gate_review` | claude 2.1.278 | completed |
| `run-design-v2` | `design_authoring` (자동 진행 경로) | claude 2.1.278 | completed |

**코딩 CLI 실행 7회**(codex 3회, claude 4회). 그 밖에 `feature_implementation` 실행
3건이 배정됐고 **CLI를 부르지 않고 실패로 보고했다**(4.7절).

### 4.2 AI가 제안한 수준을 시스템이 올렸다

**이번 라이브의 가장 중요한 결과다.**

실제 codex 가 일곱 축을 모두 채우고 `recommended_level` 을 **`simple`** 로 제안했다.
그런데 두 축을 스스로 `insufficient_evidence` 로 적었다.

| 축 | 영향 | 판단(요약) |
|---|---|---|
| `intent_clarity` | medium | 핵심 동작은 명확하지만 일부 입력의 기대 결과는 사람의 결정이 필요하다 |
| `change_scope` | low | 국소적인 단일 모듈 변경 |
| `compatibility_and_data` | **insufficient_evidence** | 기존 함수의 반환 형태를 바꿀 경우 호출자에 미치는 영향을 판단할 근거가 없다 |
| `permission_and_security` | **insufficient_evidence** | 로그 데이터·권한에 대한 판단 근거가 없다 |
| `reversibility` | low | 되돌리기 쉽고 데이터 변환을 요구하지 않는다 |
| `uncertainty` | low | 해법의 불확실성이 낮다 |
| `verification_difficulty` | low | 기본 동작은 표본으로 확인 가능하다 |

제어부가 축에서 도출한 수준은 **`standard`** 이고 적용된 수준도 `standard` 다.
`recommended_level=simple` 은 기록에 남았지만 **쓰이지 않았다.** 이것이
sizing-and-review-ux 3절의 "AI가 진행을 위해 수행 수준을 묵시적으로 낮추는 것은 허용하지
않는다"의 실제 동작이다.

그리고 **작성과 별도 세션의 claude 가 같은 문제를 독립적으로 지적했다** — QG-01 의미
검토가 `축 2개가 insufficient_evidence인데 recommended_level이 근거 없이 낮은 simple로
확정되어 있다` 를 발견 사항으로 올렸다. 이 지적은 **권고로** 기록됐다(AI가 목록에 없는
기준으로 새 필수 요구를 만들지 않는다는 quality-gates 규칙 그대로). 막은 것은 규칙 쪽이고
AI가 같은 결론을 따로 확인해 준 형태다.

같은 일이 v2 초안에서도 반복됐다 — 재작성한 초안도 `simple` 을 제안했고 도출값
`standard` 가 적용됐다.

### 4.3 QG-01과 의도 동의

QG-01은 **v1에서 한 번에 통과**했다(규칙 pass + AI pass). 발견 사항 다섯 건은 모두
권고였고 그중 넷이 claude 의 지적이다. 의도 동의는 **처음에 거부됐다** —
`open_intent_questions`(q1: 대소문자 정책). 질문에 답한 뒤 원문을 받아 보고 동의했다.

**게이트를 느슨하게 만들지 않았고, 동의 거절도 우회하지 않았다.**

### 4.4 설계안 — AI가 쓰고 사람이 검토했다

claude 가 쓴 설계안(표준 수준)의 결과:

- 표준이 요구하는 다섯 항목을 모두 채웠고 **심층 항목(대안·복구)까지 채웠다.**
  빠진 필수 항목은 0건이다.
- 작업공간을 실제로 읽었다 — `reader.py:4-6` 같은 실제 위치를 인용했다.
- **사람이 정해야 할 것을 대신 정하지 않았다.** 설계 단계 질문 셋(`d1` 제공 형태,
  `d2` 외부 호출자 존재 여부, `d3` 함수 이름)을 새로 올리고, 원문에
  "이 설계는 판정 지점을 한 곳에 모아두는 것까지만 하고 값을 정하지 않는다"고 적었다.
- 고정 컨텍스트 `agreed_intent` 를 **읽었다**(`"read": true` 가 산출물 원문에 남아 있다).

그 뒤 사람 검토를 기록했고 `decision` 표에 `design_review` 행 1건(actor=owner)이
생겼다.

### 4.5 개발계획 — 검토된 설계 위에서만

설계 검토 **전에** 계획 작성을 요청했더니 `design_review_missing` 으로 거부됐다.
검토를 기록한 뒤 codex 가 계획을 썼고, 고정 컨텍스트로 `agreed_intent` 와
`current_design` 을 둘 다 읽었다.

계획의 표준 필수 여섯 항목이 모두 채워졌다. 계획도 사람이 정할 지점을 스스로 남겼다 —
`human_decision_points` 에 "q1 — T2 완료 전 대소문자 정책을 정해야 한다", "d1 — 별도
함수 추가안을 채택하는지 확인해야 한다"를 적고 계획 단계 질문 넷을 올렸다.
`experiments`(심층 전용)는 비워 `undecided` 로 남았다 — 표준에서는 필수가 아니다.

### 4.6 기능 구현 배정이 열렸다

이월 질문이 **8건**(의도 초안의 q2 + 설계가 낳은 셋 + 계획이 낳은 넷) 남아 있는 동안은
`deferred_questions_unresolved` 로 막혔다. 여덟 건에 모두 답한 뒤:

```
준비 완료 후 구현 요청 status=201 사유=[]
  진입 판정=admitted
```

**P2까지 늘 거부됐던 목적이 처음으로 허용됐다.** 허용 기록도 `admission_check` 표에
남는다.

같은 상태에서 권한만 `workspace_write` 로 바꾸면:

```
쓰기 권한 요청 status=409 사유=['permission_not_allowed_in_stage']
```

**검토를 마쳤다는 사실이 쓰기 권한을 만들지 않는다.**

거부 사유가 단계마다 정확히 달라진 순서는 다음과 같다.

| 시점 | 사유 |
|---|---|
| 준비 전 | `design_missing`, `plan_missing`, `deferred_questions_unresolved` |
| 설계만 있음(검토 전) | `design_review_missing` |
| 설계 검토 후, 계획 검토 전 | `plan_review_missing`, `deferred_questions_unresolved` |
| 두 검토 완료, 질문 남음 | `deferred_questions_unresolved` |
| 질문까지 해결 | **허용** |
| 쓰기 권한 요청 | `permission_not_allowed_in_stage` |
| 수준을 심층으로 올린 뒤 | `plan_incomplete_for_level` (4.8절) |
| 새 의도 버전 뒤 | `design_stale`, `plan_stale` + 의도 조건들 |

### 4.7 허용된 실행은 어떻게 끝났는가

**진입 조건과 실행 경로는 서로 다른 것이다.** P3-01은 배정 조건을 열었고 구현 실행기는
P3-03이다. 배정된 `feature_implementation` 실행 3건은 **CLI를 부르지 않고 `failed` 로
보고됐다.** 처음에는 Runner 가 예외로 죽어 실행이 `assigned` 로 멈췄고, 그것을 고쳐
지금은 깨끗하게 실패한다(10절 결함 1).

### 4.8 오래된 승인과 수준 상향

**새 의도 버전이 생기면** 두 산출물이 곧바로 오래된 것이 됐다.

```
새 의도 후 설계 stale=True 상태=needs_recheck / 계획 stale=True 상태=needs_recheck
오래된 산출물로 구현 요청 → ['intent_not_agreed', 'open_intent_questions',
  'intent_gate_not_passed', 'design_stale', 'plan_stale', 'deferred_questions_unresolved']
```

수준 판단도 같은 규칙으로 대체됐고, v2 초안의 새 판단이 그 자리를 채웠다.

**사람이 수준을 심층으로 올리면** 이미 있는 산출물이 부족해졌다.

```
조정 전: 적용=standard 설계 부족=[] 계획 부족=[]
조정 후: 적용=deep 설계 작성 시점 수준=standard 설계 부족=[] 계획 부족=['experiments']
  계획 experiments: 지금 필수=True 보고 시점 필수=False 상태=undecided
→ 구현 요청 사유에 plan_incomplete_for_level 추가
```

설계는 claude 가 심층 항목까지 미리 채워 뒀으므로 부족하지 않았다. **계획은
`experiments` 가 비어 있어 부족해졌다.** 되돌리면 다시 충분해지고 기록은 남는다.
이 동작은 처음에 틀렸고 라이브에서 드러나 고쳤다(10절 결함 2).

**조정이 다른 조건을 해제하지 않는다**는 것도 같은 자리에서 확인했다.

```
조정 뒤 동의=agreed_current 게이트=pass
  기준=4건(['user_confirmed','user_confirmed','user_confirmed','user_confirmed'])
  설계 검토 모드=human_review
```

이유나 남는 위험이 없는 조정은 거부됐다(422). 이유 없는 자동 진행 설정도 거부됐다(409).

### 4.9 자동 진행 경로 — 사람 승인이 아니다

최신 의도(v2)에 동의하고 **설계 단계만** 자동 진행으로 바꾼 뒤 claude 가 설계를 다시
썼다. 두 단계가 서로 독립임이 여기서 드러난다 — 계획 단계의 설정은 그대로였다.

```
설계 v2 상태=awaiting_auto_conditions stale=False 부족=[]
자동 진행 조건 충족 기록 status=201
  {"mode":"auto_proceed","state":"auto_conditions_met","decision_id":null, ...}
기록 후 설계 상태=auto_conditions_met review.decision_id=None
  actor=stage-auto-proceed-policy
decision 표의 design_review 행 1건 (자동 진행은 늘리지 않는다)
```

셋이 핵심이다.

- **산출물은 그대로 필요했다.** 자동 진행 설정만으로는 `awaiting_auto_conditions` 이고
  산출물과 필수 항목이 갖춰진 뒤에 조건 충족이 기록된다.
- `decision_id` 가 `null` 이고 주체가 사람 이름이 아니라 정책 식별자다.
- `decision` 표의 `design_review` 행은 **1건 그대로** — 앞서 사람이 검토한 그 한 건이며
  자동 진행이 새 사람 승인 기록을 만들지 않았다.

사람 검토 모드인 단계에 자동 진행을 기록하려는 요청은 409로 거부됐다.

### 4.10 재작성이 퇴화하지 않았다 — P2-04 위험 1의 해소

P2-04에서는 재작성 실행에 요청 원문 하나만 들어가 AI가 의도를 처음부터 다시 썼고
**목표 미정·기준 0건으로 퇴화**했다. 이번에는 이전 버전이 참조로 고정됐다.

```
재작성 고정 컨텍스트: [('previous_intent', 'available')]
재작성 v2: 미정 항목=['exclusions'] 기준=5건 축=7개 질문=3건
```

여섯 항목 중 다섯이 채워졌고 기준은 4건 → **5건으로 늘었다.** 축도 일곱 개가 그대로
왔다. 설계 재작성도 같았다 — `[('agreed_intent', 'available'), ('previous_design',
'available')]`.

## 5. 화면 확인

증거: [`P3-01-ui.log`](P3-01-ui.log), 화면 캡처 `P3-01-ui-01`~`05`.

| 확인한 것 | 결과 |
|---|---|
| 준비 패널·축 표·수준 조정 폼·설계/계획 단계 표시 | 모두 보인다 |
| "축을 점수로 합산하지 않는다" 문구 | 보인다 |
| 조정 이유·남는 위험이 비면 조정 버튼이 **비활성** | 확인(둘 중 하나만 채워도 비활성) |
| 화면에서 심층으로 조정 → `현재 수준이 요구하는 항목이 미정이다` 표시 | 확인 |
| 표준으로 되돌림 + `수준 판단 이력` 표시 | 확인 |
| 설계 원문 열람(일시 중계) | 확인 — 원문 창에 `hads.preparation` 문서가 보인다 |
| 기능 구현 요청의 거부 사유가 **사람 말로** 보인다 | 확인 — `설계안이 대체된 의도 버전 위에…`, `설계·계획으로 이월한 질문이 남아 있다`, `최신 의도에 대한 사람의 동의가 없다` |
| `workspace_write` 요청의 거부 문구 | 확인 — `이 단계에서 배정하지 않는 권한이다` |
| `설계안 — 자동 조건 충족 (사람 승인 아님)` 상태 문구 | 확인 |
| `사람 승인 기록 없음 (자동 조건 충족)` 와 정책 주체 표시 | 확인 — `stage-auto-proceed-policy` |

**화면에서 찾아 고친 것이 하나 있다** — 원문 열람이 한 번만 물어보고 "아직 오지 않았다"로
끝났다(10절 결함 3).

## 6. 재시작 복원

**제어부를 `taskkill /F /T` 로 죽이고 다시 띄운 뒤** 모두 복원됐다.

```
복원: 수준 적용=standard source=ai_recommendation 제안=simple 도출=standard 축=7개 이력=4건
복원: 설계=needs_recheck 모드=human_review(project_default) decision=dec-fc6f39e8ff005c8b
     / 계획=needs_recheck 모드=auto_proceed(case_setting) decision=dec-9c97e43bc1224b3b
복원: 설계 stale=True 계획 stale=True
```

수준 이력 4건, 축 7개, 단계별 검토 모드와 그 **출처**(기본값/Case 설정), 검토 기록의
`decision_id` 까지 그대로다. 자동 시험(`tests/test_restart_recovery.py`)도 같은 확인을
실제 uvicorn 자식 프로세스 강제 종료로 한다. 그 시험은 추가로 **준비가 갖춰진 판단이
재시작으로 되살아나지도 사라지지도 않는지**(준비 관련 사유가 다시 나타나지 않는지)까지
본다.

## 7. 데이터 경계 (바이트 검사)

증거: [`P3-01-boundary.log`](P3-01-boundary.log). 원문에서 **실제 문장 조각**을 뽑아
제어부 파일 바이트에서 찾았다(우리가 만든 표식이 아니다).

| 대상 | 제어부 DB/WAL/SHM | 제어부 로그 | Runner 저장소 |
|---|---|---|---|
| 축별 **근거 서술** | 없음 | 없음 | **있음** |
| 축별 **판단 한 줄**(요약으로 올라가는 값) | **있음** | 없음 | 있음 |
| 설계 본문(`change_summary`) | 없음 | 없음 | **있음** |
| 계획 본문(`tasks`) | 없음 | 없음 | **있음** |

경계는 "본문은 없고 요약은 있다"이다. 두 번째 줄이 그 경계를 보여 준다 — 판단 한 줄은
제어부가 목록에 보이려고 받는 요약이므로 **있어야 한다.** 셋 다 없으면 애초에 저장되지
않은 것이라 검사가 무의미하므로 Runner 쪽 존재도 함께 확인했다.

자동 시험은 여기에 두 가지를 더한다 — v5 표에 본문 컬럼이 없다는 것과, 제어부 코드가
`prep_doc.parse`/`structure` 를 **부르지 않는다**는 것(본문을 해석하는 쪽은 원문을 가진
Runner 뿐이다).

## 8. 성공 기준별 결과 (AC-1~15)

| ID | 결과 | 근거 |
|---|---|---|
| AC-1 두 단계 기본값이 사람 검토 | **통과** | 자동 시험(새 Case·v4 DB 모두), 라이브 `설계=human_review(project_default) 계획=human_review(project_default)` |
| AC-2 축별 판단이 의도 버전에 묶임, 합산 없음 | **통과** | 자동 시험 4건, 라이브 축 7개 기록·새 의도 버전에서 대체 |
| AC-3 AI가 수준을 조용히 낮추지 못함 | **통과** | 자동 시험 2건, **라이브 2회**(v1·v2 모두 `simple` 제안 → `standard` 적용) |
| AC-4 사람 조정에 이유·남는 위험 필수, 부작용 없음 | **통과** | 자동 시험 3건, 라이브 422 거부 + 조정 뒤 동의·게이트·기준·검토 모드 불변 |
| AC-5 설계·계획을 각각 조회, 간소도 둘 다 필요 | **통과** | 자동 시험 3건, 라이브 단계별 목록 조회 |
| AC-6 자동 진행이 산출물을 보존하고 사람 승인이 아님 | **통과** | 자동 시험 5건, **라이브 4.9절**(`auto_conditions_met`·`decision_id=null`·정책 주체, `decision` 행 늘지 않음, 사람 검토 모드에서 409) + 화면 문구 |
| AC-7 산출물 없음/항목 미정이 배정을 막음 | **통과** | 자동 시험 4건 + 수준 상향 1건, 라이브 `design_missing`·`plan_missing`·`plan_incomplete_for_level` |
| AC-8 사람 검토 미완이 배정을 막음 | **통과** | 자동 시험 3건, 라이브 `design_review_missing`·`plan_review_missing` |
| AC-9 오래된 승인 재사용 없음 | **통과** | 자동 시험 3건, 라이브 새 의도 버전 뒤 `design_stale`·`plan_stale` |
| AC-10 이월 질문 미해결이 배정을 막음 | **통과** | 자동 시험 2건, 라이브 8건(의도·설계·계획이 각각 낳은 질문) |
| AC-11 조건을 갖추면 허용, 쓰기 권한은 계속 거부 | **통과** | 자동 시험 3건, 라이브 `admitted` + `permission_not_allowed_in_stage` |
| AC-12 작성 실행이 이전 버전을 봄 | **통과** | 자동 시험 4건, 라이브 재작성 v2가 **퇴화하지 않음**(기준 4→5건) |
| AC-13 데이터 경계 유지 | **통과** | 자동 시험 3건 + 라이브 바이트 검사 4항목 |
| AC-14 재시작 복원, v5 마이그레이션 | **통과** | 자동 시험(실제 프로세스 강제 종료·v2→v5 이행) + 라이브 제어부 강제 종료 |
| AC-15 화면으로 한 바퀴 | **통과** | 5절 |

**AC-1~15 전부 통과.** 기준을 완화하거나 새 수용 제한을 만들지 않았다.

## 9. 라이브로 하지 않은 것

| 항목 | 어디까지 확인했나 |
|---|---|
| 자동 진행 모드에서 **설계·계획 둘 다** 자동으로 끝까지 가는 조합 | 설계 한 단계만 라이브(4.9절). 두 단계 조합은 자동 시험 |
| 자동 진행만으로 기능 구현까지 배정되는 한 바퀴 | 라이브에서는 사람 검토로 한 바퀴를 돌았고 자동 진행은 설계 한 단계에서 조건 충족까지만 확인했다. 자동 진행만으로 배정이 열리는 것은 자동 시험 |
| `design_incomplete_for_level` 의 라이브 발생 | claude 가 심층 항목까지 채워 라이브에서는 계획 쪽만 걸렸다. 설계 쪽은 자동 시험 |
| 사람이 화면에서 **직접 입력한** 설계·계획 | 만들지 않았다. 이번 산출물은 AI 작성 경로뿐이며 사람 작성 경로는 P3-02 이후 필요해지면 만든다 |
| 원문 열람 중 제어부 재시작(`expired`) | 의도 원문으로 P2-04에서 확인했고 준비 산출물로는 하지 않았다. 같은 중계 경로다 |
| 계획이 낳은 질문의 `blocks` 연결 | 자유 문자열로만 기록된다. Task ID 로 잇는 것은 P3-02 |

## 10. 검토·시험 중 발견해 고친 것

라이브에서 실제로 드러난 결함 셋과 스스로 검토하다 찾은 둘이다.

| # | 무엇 | 어떻게 고쳤나 |
|---|---|---|
| 1 | **배정은 허용됐는데 Runner 가 실행 경로를 몰라 루프가 죽었다.** `feature_implementation` 이 처음 허용된 순간 Runner 가 `ValueError` 로 죽고 실행이 `assigned` 로 멈췄다. 사람은 왜 아무 일도 일어나지 않는지 알 수 없다 | `prompts.has_prompt()` 로 실행 경로 유무를 먼저 보고, 없으면 **CLI를 부르지 않고 `failed` 로 보고**한다. 한 배정의 실패가 다른 배정을 건너뛰지 않도록 루프도 감쌌다. 시험 1건 + 라이브 재확인 |
| 2 | **수준을 올려도 이미 있는 산출물이 부족해지지 않았다.** 필수 항목을 산출물 작성 시점의 수준으로 판단해, 사람이 심층으로 올려도 얕게 쓴 산출물로 "준비 완료"가 됐다 — 조정이 겉치레가 된다 | `effective_required_sections()` 가 **Case 의 현재 수준**으로 판단한다. 항목 표에 `지금 필수`와 `보고 시점 필수`를 따로 보인다. 시험 1건 + 라이브 재확인 |
| 3 | **준비 산출물 원문 열람이 한 번만 물어보고 끝났다.** Runner 가 폴링으로 가져가므로 사람은 늘 "아직 오지 않았다"만 본다 | 의도 원문 열람과 같은 방식으로 잠깐 기다렸다 다시 확인한다. 브라우저에서 재확인 |
| 4 | **`plan_not_for_current_design` 이 닿을 수 없는 분기였다.** 설계를 새로 만들면 그 위의 계획이 곧바로 대체되므로 이 검사는 절대 실행되지 않는다. 닿을 수 없는 검사는 시험할 수도 없다 | 사유 코드와 분기를 지웠다. 그 상태는 `plan_missing` 으로 드러나고, 대체된 계획은 목록에 `superseded` 로 남아 조회된다. plan 의 수정 기록에 남겼다 |
| 5 | **자동 진행 단계에 산출물이 있는데 "산출물 준비 전"으로 보였다.** 두 상태를 합치면 사람이 무엇을 해야 하는지 알 수 없다 | `awaiting_auto_conditions` 상태를 따로 만들었다. 시험 1건 |

시험 도우미에서도 하나 고쳤다. `intent_versions` 는 revision **내림차순**인데 목록의
마지막을 최신으로 집고 있었다. 지금은 한 버전짜리 Case 라 결과가 같았지만 버전이 늘면
조용히 엉뚱한 것을 시험한다.

## 11. 남은 위험

1. **구현 실행 경로가 없다.** 배정 조건은 열렸고 실행하면 `failed` 다. 작업공간·브랜치·
   기준 커밋과 쓰기 권한은 P3-03이다. 이것은 결함이 아니라 단계 경계이며 화면과 결과에
   그대로 드러난다.
2. **시스템은 산출물의 내용이 충분한지 판정하지 않는다.** 필수 항목이 미정인지까지만
   본다. 항목에 한 줄만 써도 통과한다 — 그 판단은 사람의 검토와 (P4의) QG-02·QG-03의
   몫이다. P2-04의 9.2절이 기록한 경계와 같은 성질이다.
3. **이월 질문의 `blocks` 가 자유 문자열이다.** "어느 작업이 이 결정을 기다리는가"가
   Task 로 이어지지 않는다(P3-02).
4. **AI가 낳는 질문이 많다.** 라이브에서 설계·계획이 질문 7건을 새로 올려 이월 질문이
   8건이 됐다. 시스템은 전부 해결을 요구하므로 큰 기능에서는 사람의 부담이 커질 수 있다.
   질문의 중요도 구분은 이번 범위에 없다.
5. **수준 도출 규칙은 구현 제안이다.** 높은 축 하나가 심층을 만들고 근거 부족이 표준을
   만든다는 규칙은 sizing-and-review-ux 2절의 초기 추천 규칙을 옮긴 것이며 실측으로
   조정한 값이 아니다.
6. `residual_activity` 가 항상 `unknown`, 안전 중지 미연결, 열람 요청의 만료·크기 한도
   없음 — P1·P2에서 넘어온 위험 그대로다.

## 12. 외부 전송·남은 자원

**외부 AI 전송은 있었다** — 사용자 계정의 codex 3회, claude 4회를 실행했고 각 CLI의 기존
사용자 설정을 따랐다. 시스템은 두 CLI의 자격증명을 읽지도 주입하지도 않았다.
GitHub 이슈·PR 등 외부 게시는 없다.

라이브 시험 데이터 `%LOCALAPPDATA%\Temp\hads-p3-01-live` 는 지워도 된다(저장소 밖).
작업공간의 임시 git 저장소도 같은 곳에 있다. 이전 세션의 `hads-p2-0*-live`,
`hads-playwright`, `hads-p1\testrepo` 도 그대로 두었다.
