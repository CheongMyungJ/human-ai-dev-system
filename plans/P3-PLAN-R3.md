# P3-PLAN-R3

예산 예약·집계·정지. 기준: 설계 v0.7 / D-01~67 / 2026-09-22.
선행: P3-R2 완료(스키마 v9, pytest 313 + P1 계약 18 통과). 다음: [P3-R4 자동 실행](../DEVELOPMENT.md).

## 1. 이 작업이 답해야 하는 것

R1은 **예산 한도를 기록**했다. 기록만 했다. 지금 조회의 `enforcement.budget` 은
`recorded_not_enforced / P3-R3` 이고, `budget_state()` 는 `usage: None` 을 돌려주며
`tests/test_policy.py::test_a_hard_budget_does_not_yet_change_admission` 이 "hard 한도를
걸어도 진입 검사가 달라지지 않는다"를 시험으로 고정해 두었다.

R2는 그 옆에서 `repository_selection` 을 강제로 바꿨다. 예산은 아직 아무 것도 막지 않는다.

R3는 그 위에 예산 강제를 붙인다. 네 가지다.

1. **배정 전에 원자적으로 예약한다.** `이미 사용한 양 + 진행 중 예약 + 새 실행 예약
   ≤ 설정 한도` 를 Run 을 만드는 **같은 트랜잭션 안에서** 검사한다(D-61,
   autonomy-budget-policy 8절). 검사와 생성이 떨어져 있으면 마지막 한 칸을 두 실행이
   함께 통과한다.
2. **소비를 Case 하나로 누적한다.** 역할·Task·저장소·세션·Runner·Profile 을 바꿔도
   초기화되지 않는다. 검토 실행은 전체 실행의 부분집합이며 같은 실행을 두 축에서
   중복 차감하지 않는다(7절).
3. **hard 도달은 새 비용 실행을 막고 기존 결과는 보존한다.** 완료도 취소도 아니다.
   `continue` 로 우회하는 경로를 만들지 않으며, 재개는 한도 변경으로만 한다(8절).
4. **강제할 수 있는 것과 없는 것을 구분해 표시한다.** 어떤 지표는 실행 전에 소비량을
   알 수 있고(실행 수), 어떤 지표는 끝나야 알 수 있고(실행 시간), 어떤 지표는 어댑터가
   주지 않으면 영원히 모른다(토큰·비용). 이 셋에 같은 보장을 표시하지 않는다.

가장 위험한 것은 4번이다. **hard 한도를 건 사람은 "이제 초과하지 않는다"고 믿는다.**
실행 수에는 그 약속을 지킬 수 있고 실행 시간에는 지킬 수 없다 — 이미 돌고 있는 CLI 를
초 단위로 끊을 능력이 없기 때문이다(`cancel_confirmed = unknown`, P1-03). 같은 화면에
같은 모양으로 표시하면 없는 보장을 판 것이 된다(D-61 "표시만 추정으로 바꾸어 계속
실행하지 않는다").

두 번째로 위험한 것은 2번의 **반대 방향**이다. 집계를 새로 만들면서 R3 이전에 실제로
돈 실행들을 0으로 두면, 스키마를 올리는 것만으로 소비가 초기화된다. "세션·Task 분할로
초기화하지 않는다"(D-61)는 이행에도 똑같이 적용된다.

## 2. 범위

| 넣는 것 | 넣지 않는 것 (담당) |
|---|---|
| `budget_reservation` 표와 스키마 v10, 기존 실행의 이행 | 예산 preset(`low/normal/high`) UI (범위 밖, 1절 경계만 유지) |
| Run 생성과 같은 트랜잭션의 원자적 예약 검사 | Autonomy 기반 자동 실행 경로·진입 조건 (R4) |
| 지표별 예약 계약(예약 가능·사후 관측·미제공)과 hard 보장 범위 표시 | 실제 CLI 실행의 초 단위 중단 (하지 않는다. P1-03 한계) |
| 종료 후 정산, 미보고·결과 불명의 예약 보존 | `RemediationCycle`·repair 한도 모델 (P4-01) |
| 역할별·목적별 집계와 Case 단일 누적 | 지식 추출 실행 (P4-07 — 생기면 같은 예약 경로를 탄다) |
| warn 경계 표시, hard 도달 시 새 실행 배정 차단 | Project·Task 단위 예산 조정 (계층이 없다. 만들지 않는다) |
| 재배정(`bump_generation`)의 추가 예약 | 사용자 알림·메일 (범위 밖) |
| 화면의 사용량·노출·정지 사유 표시 | 실제 push·PR·게시 (P5) |
| `tests/test_policy.py` 의 budget 축 시험 갱신 | 실제 수직 통합 기능 개발 (P3-04) |

**게이트·권한·성공 기준은 예산으로 완화되지 않는다.** hard 도달이 검사를 끄거나
미검증을 완료로 바꾸는 경로를 만들지 않는다(autonomy-budget-policy 8절 마지막).

## 3. 지표별 예약 계약 — 이 작업의 중심 표

R1의 `BUDGET_MEASUREMENT` 는 **"그 값을 어떻게 아는가"** 를 말한다. R3는 그 옆에
**"실행 전에 얼마를 잡을 수 있는가"** 를 더한다. 두 질문의 답이 다르기 때문에 표가 둘이다 —
실행 시간은 정확히 잴 수 있지만(`exact`) 실행 전에 얼마가 될지는 모른다.

| 지표 | 측정(R1) | 예약(R3) | hard 한도 | 근거 |
|---|---|---|---|---|
| `run_count` | exact | `exact_per_run` = 1 | **절대 상한 보장** | 시작한 호출을 시스템이 센다 |
| `review_run_count` | exact | `exact_per_run` = 1 (reviewer 역할만) | **절대 상한 보장** | 같음. 전체에서 중복 차감하지 않는다 |
| `context_bytes` | exact | `exact_per_run` = 지시 원문 + 고정 컨텍스트의 `byte_size` 합 | **절대 상한 보장** | 제어부가 **만들어 전달한** 패키지 크기. CLI 내부 추가분은 관측 범위 밖 |
| `execution_seconds` | exact | `open_ended_per_run` — 진행 중 노출은 `now − assigned_at` 로 관측 | 새 배정 차단. **절대 상한 아님** | 돌고 있는 CLI 를 초 단위로 끊을 수 없다(P1-03 `cancel_confirmed = unknown`) |
| `elapsed_seconds` | exact | `case_clock` — 예약이 없고 Case 시작 시각에서 도출 | 새 배정 차단. **절대 상한 아님** | 벽시계는 배정으로 줄지 않는다 |
| `input_tokens` | estimated | `post_hoc_reported` | **설정 거부**(R1 그대로) | 어댑터가 주지 않거나 사후에만 준다 |
| `output_tokens` | estimated | `post_hoc_reported` | **설정 거부** | 같음 |
| `estimated_cost` | estimated | `post_hoc_reported` | **설정 거부** | 실제 청구액의 상한이 아니다 |

세 가지 강제 상태를 구별해 `budget_setting.enforcement` 와 조회에 남긴다.

- `enforced_absolute` — 예약이 정확하고 한도를 넘는 배정이 생기지 않는다.
- `enforced_no_absolute_cap` — 새 배정은 막지만 **진행 중 실행의 초과 노출이 있을 수
  있다.** 노출값과 이유를 함께 표시한다.
- `not_enforceable` — 설정을 받지 않는다(hard + 추정 지표). R1 그대로.

`warn` 은 모든 지표에 받는다. 경고는 표시이며 보장이 아니고, 경고 자체로 사람 응답을
기다리지 않는다(8절).

## 4. 새 표 (스키마 v10)

기존 표의 컬럼은 **하나도 바꾸지 않는다.** 새 표 하나와 그 표를 채우는 이행이 전부다.

```
budget_reservation
  id            이 예약 한 건
  case_id       누적 단위. **Case 하나다** — 역할·Task·저장소로 나뉘지 않는다
  run_id        어느 실행의 예약인가
  generation    몇 번째 배정인가. 재배정된 실행의 두 번째 호출은 **새 소비**다
  metric        무엇을 잡았는가
  reserved_value  실행 전에 잡은 양. `open_ended` 는 NULL(=모름)
  actual_value    정산된 실제 사용량. NULL = 아직 모른다. **0 으로 적지 않는다**
  measurement     정산 시점의 측정 방식. exact | estimated | unavailable
  reservation_kind exact_per_run | open_ended_per_run | post_hoc_reported
  role, purpose 역할별·목적별 집계의 축
  state         held | settled | unresolved
  source        reserved | migrated_from_run  ← 이행으로 만든 행을 구별한다
  reserved_at, settled_at, settle_source
  UNIQUE (run_id, generation, metric)
```

**집계의 출처는 이 표 하나다.** `run` 표에서 따로 세고 여기서도 세면 두 수가 갈라지고,
갈라지면 어느 쪽이 한도인지 아무도 모른다. 그래서 v10 이행이 **기존 실행에도 행을 만든다** —
`source = migrated_from_run` 이고, 값은 `run` 표가 실제로 아는 것만 담는다. 토큰을 보고하지
않은 옛 실행은 `measurement = unavailable`·`actual_value = NULL` 이며 **0 이 아니다**.

`state` 셋의 뜻:

- `held` — 실행이 아직 끝나지 않았다. 노출로 계산한다.
- `settled` — 실제 사용량이 확정됐다.
- `unresolved` — 실행은 끝났는데 **얼마를 썼는지 모른다.** 결과가 `unknown` 이거나
  어댑터가 사용량을 주지 않은 경우다. **예약을 해제하지 않는다** — "확인 전에 잔여량을
  낙관적으로 복구하지 않는다"(7절). 노출에는 남고 확정 사용량에는 들어가지 않는다.

## 5. 예약·검사·정산의 자리

### 예약 (Run 생성)

`create_run()` 의 `transaction()` **안에서** 한다. `BEGIN IMMEDIATE` 가 쓰기를
직렬화하므로 "읽고 → 판단하고 → 넣는" 사이에 다른 연결이 끼어들 수 없다.

```
with transaction(conn):            # BEGIN IMMEDIATE
    limits  = 현재 hard 한도
    exposure = settled + held + unresolved      (지표별)
    want     = 이 실행의 예약                    (3절 표)
    if any(exposure[m] + want[m] > limit[m]): → BudgetExhausted
    INSERT run
    INSERT budget_reservation × want
```

검사는 **두 층**이다. `evaluate_admission()` 도 같은 판정을 해서 `budget_hard_limit_reached`
를 진입 검사 기록에 남긴다(FR-14: 왜 실행이 열리지 않았는지 사람이 봐야 한다). 트랜잭션
안의 검사는 그 뒤의 **경쟁**만 막는다. 둘 중 하나만 두면 안 된다 — 앞의 것만 두면 마지막
한 칸을 둘이 통과하고, 뒤의 것만 두면 거부 사유가 기록되지 않는다.

`bump_generation()` 도 같은 검사를 지난다. 재배정된 실행은 CLI 를 다시 부르고 그것은
새 소비다(7절 "재시작된 실제 AI 호출은 새 소비"). 예산이 남지 않으면 재배정하지 않는다.

### 정산 (결과 보고)

`report_result()` 의 같은 트랜잭션에서 한다.

| 예약 종류 | 정산 |
|---|---|
| `exact_per_run` | `actual = reserved`. 실패·취소도 소비다 — 호출은 실제로 있었다 |
| `open_ended_per_run` | `actual = finished_at − assigned_at`, `measurement = exact` |
| `post_hoc_reported` | 어댑터가 준 값 또는 **`unresolved`·`unavailable`**. 0 으로 적지 않는다 |

**결과가 `unknown` 이면 어느 것도 `settled` 로 내리지 않는다.** `unresolved` 로 두고
노출을 보존한다. `residual_activity` 가 `none` 이 아닌 경우도 같다 — 프로세스가 남아
있으면 소비가 끝났다는 근거가 없다.

> **이 문단은 구현 중 바뀌었다.** 실행 단위로 묶으면 실제 어댑터가 보고한 값까지
> 버리게 된다. 판단을 지표 단위로 옮긴 이유와 실제 규칙은 **10절**에 있다.

같은 결과의 재전송은 이미 `report_result()` 가 멱등하게 막는다(`status == finished` 면
그대로 돌려준다). **중복 청구가 생기지 않는 자리가 거기다** — 정산을 그 가드 뒤에 둔다.

### 정지

`budget_state()` 가 `stop` 을 **도출한다.** `case.status` 를 바꾸지 않고 저장 컬럼도
만들지 않는다. hard 도달은 완료도 취소도 아니며(8절), 한도를 올리면 그 순간 다시
진행할 수 있어야 하기 때문이다 — 저장해 두면 되돌리는 경로가 또 필요해진다.

정지 중에도 **막지 않는 것**: 결과 보고, 이벤트 수신, 산출물 저장, 작업공간 관측,
기존 기록 조회. 막는 것은 **새 실행 생성과 재배정** 하나다. 정리라는 이름의 새 AI
실행도 막는다(8절 "정리라는 이름으로 새 유료 AI 요약·수정 실행을 시작하지 않는다").

## 6. 소급하지 않는 것

| 대상 | R3 이후 | R3 이전에 만들어진 것 |
|---|---|---|
| 한도 없는 Case | 그대로 무제한. 예약 행은 만들되 **어떤 검사도 하지 않는다** | 같음 |
| 기존 실행 | 생성 시 예약 | 이행이 `migrated_from_run` 행을 만든다. **소비가 0으로 초기화되지 않는다** |
| 기존 `budget_setting` 행 | 새 `enforcement` 값 | `recorded_not_enforced` 로 남은 옛 행은 **그대로 두고** 조회가 현재 강제 상태를 따로 말한다 |
| 토큰 미보고 실행 | `unresolved`·`unavailable` | 같음. **0 이 아니다** |
| 이미 hard 한도를 넘긴 Case | — | 이행 직후 정지 상태가 될 수 있다. **진행 중 실행은 그대로 끝나고 결과는 받는다** |

마지막 줄이 중요하다. 이행이 곧 중단이 되면 안 된다 — 막는 것은 **새 실행**이고,
이미 도는 실행의 결과를 버리는 것은 "기존 결과 보존"(8절)에 어긋난다.

## 7. 작업 순서

1. `domain/budget.py` — 예약 계약표(3절), 사용량 정규화(`{"tokens": {...}, "cost_usd": ...}`
   → 지표값), 노출 계산. **순수 함수로 두고** 제어부·시험이 같은 것을 쓴다
2. 스키마 v10 + 이행. **v9 DB로 실제 이행 시험부터 만든다** (R2와 같은 방식)
3. `set_budget_limit()` — 세 강제 상태 구분, `enforced_no_absolute_cap` 표시
4. 예약·검사를 `create_run()` 트랜잭션 안으로. `BudgetExhausted` 와 거부 사유
5. `evaluate_admission()` 의 `budget_hard_limit_reached` — 기록되는 거부
6. `bump_generation()` 의 추가 예약과 검사
7. `report_result()` 의 정산 — 결과 불명·미보고의 예약 보존
8. `budget_state()` — 지표별 노출·역할별·목적별 집계·warn·stop 도출
9. 화면 — 사용량·노출·경고·정지 사유와 **보장 범위** 표시
10. **`tests/test_policy.py` 의 budget 축 시험 갱신.** `enforcement.budget` 이 강제로
    바뀌어야 하고 `test_a_hard_budget_does_not_yet_change_admission` 은 반대를 확인하는
    시험으로 바뀐다. 통과한 채로 남으면 강제를 붙이지 않은 것이다
11. 전체 시험·빌드·재시작 복원·실제 CLI 라이브 확인

## 8. 성공 기준 (AC)

| # | 기준 | 검증 |
|---|---|---|
| AC-1 | 한도를 설정하지 않은 Case 는 예산으로 아무 실행도 막히지 않는다 | 기존 전체 시험이 그대로 통과. 무제한 Case 의 연속 실행 |
| AC-2 | `run_count` hard 한도에 도달하면 새 실행이 `budget_hard_limit_reached` 로 거부되고 그 사유가 진입 검사에 기록된다 | 한도 2에서 세 번째 요청 |
| AC-3 | 마지막 한 칸을 두 요청이 동시에 노려도 정확히 하나만 만들어진다 | **두 연결·두 스레드**로 동시 생성. 성공 1·거부 1, Run 표에 1건 |
| AC-4 | 정지 중에도 진행 중 실행의 결과 보고·이벤트·산출물 저장이 받아들여진다 | 한도를 채운 뒤 진행 중 실행 보고 |
| AC-5 | hard 도달이 Case 를 완료·취소로 바꾸지 않고 남은 작업·미검증 상태가 보존된다 | `case.status` 와 작업 그래프·기준 결과 비교 |
| AC-6 | 한도를 올리면 새 실행이 다시 배정된다. `continue` 류의 우회 경로가 없다 | 한도 변경 후 재요청. API 표면에 예외 인자 없음 |
| AC-7 | 검토 실행은 `run_count` 와 `review_run_count` 에 각각 한 번씩만 잡히고, 두 축을 함께 걸어도 같은 실행이 중복 차감되지 않는다 | reviewer 실행 2건의 집계 |
| AC-8 | Task 를 나누거나 저장소·역할·세션을 바꿔도 소비가 이어진다 | 두 Task·두 저장소에 걸친 실행의 Case 단일 집계 |
| AC-9 | 제어부를 강제 종료해도 사용량·예약이 그대로 복원된다 | 프로세스 종료 후 재기동 |
| AC-10 | 같은 결과의 재전송이 소비를 두 번 세지 않는다 | 동일 보고 2회 |
| AC-11 | 재배정된 실행의 두 번째 호출이 새 소비로 잡히고, 예산이 없으면 재배정되지 않는다 | `bump_generation` 전후 집계 |
| AC-12 | 결과가 `unknown` 인 실행의 예약이 해제되지 않고 노출에 남는다 | `unresolved` 상태와 노출값 |
| AC-13 | 어댑터가 토큰을 주지 않으면 `unavailable` 로 남고 0 으로 집계되지 않는다 | 미보고 실행의 집계와 `complete = false` |
| AC-14 | 추정 지표의 hard 한도는 여전히 거부되고, 시간 지표의 hard 한도는 받되 `enforced_no_absolute_cap` 으로 표시된다 | 설정 응답과 조회 |
| AC-15 | 진행 중 실행 때문에 실제 초과가 생기면 값·원인·미확인 범위가 기록된다 | 시간 한도 초과 실행의 정산 기록 |
| AC-16 | `context_bytes` 가 제어부가 **전달한** 패키지 크기로 잡히고 CLI 내부 추가분을 측정했다고 주장하지 않는다 | 고정 컨텍스트가 있는 실행의 예약값과 표시 문구 |
| AC-17 | v9 DB 를 올리면 기존 실행의 소비가 집계에 들어오고 0으로 초기화되지 않는다 | 커밋 이력의 v9 스키마로 실제 DB 를 만들어 이행 |
| AC-18 | 예산 소진이 게이트·성공 기준·권한을 완화하지 않고 미검증을 완료로 바꾸지 않는다 | 정지 상태에서 완료·기준 판정 경로 확인 |
| AC-19 | repair 한도와 예산이 분리된 채 남는다. 예산 모델이 repair 횟수로 쓰이지 않는다 | `repair_limit_note` 유지와 P4-01 표시 |
| AC-20 | `enforcement.budget` 이 강제로 바뀌고 R1 이 고정한 "강제 없음" 시험이 갱신된다. `autonomy`·`controlled_checkpoint` 는 여전히 R4, `publish` 는 P5 | `tests/test_policy.py` |
| AC-21 | 제어부 DB 에 본문이 들어가지 않는다 | `tests/test_data_boundary.py` 바이트 검사 |
| AC-22 | 실제 CLI 실행 1회 이상이 실제 사용량을 보고하고 집계·정산된다 | 라이브 확인 |

## 9. 복구·인계

- 이 작업은 **기존 표를 바꾸지 않는다.** 새 표 하나와 그 표를 채우는 이행뿐이므로
  되돌리기는 R2보다 쉽다. 그래도 이행 전 DB 사본을 남긴다
- 이행이 실패하면 `budget_reservation` 이 없고 예산 강제는 동작하지 않는다.
  **반쯤 채운 집계를 사용량으로 표시하지 않는다**
- 시험은 임시 경로에서만 돌고 저장소의 `var\` 는 건드리지 않는다
- 외부 쓰기(push·PR·이슈)는 이 작업에 없다. 커밋·push 는 사용자 확인 뒤에만 한다
- R4 는 READY 로 인계하고 착수하지 않는다. R1·R2 의 모델을 재설계하지 않는다

## 10. 수정 기록

### 정산 판단을 실행 단위에서 **지표 단위**로 옮겼다 (라이브가 찾음, AC-13·AC-22)

계획 5절은 "결과가 `unknown` 이거나 잔류 활동이 `none` 이 아니면 `settled` 로 내리지
않는다"를 **실행 단위 규칙**으로 적었다. 그대로 구현했더니 첫 라이브에서 codex 가
`input_tokens: 30600` 을 보고했는데 **집계의 확정값이 0 이었다.**

실제 codex 어댑터는 `residual_activity` 를 **항상** `unknown` 으로 보고한다(P1-03의
프로세스 잔류 관측). 그것을 확정 조건으로 쓰면 모든 실제 실행의 토큰이 영원히
`unresolved` 가 되고, 받은 관측을 전부 버린다.

잔류 프로세스가 **더 늘릴 수 있는 것**과 **이미 보고된 것**은 다르다. 그래서 지표마다
다르게 판정한다.

- `exact_per_run`(실행 수·검토 수·컨텍스트 크기) — 언제나 확정. 결과가 불명해도 호출은
  있었고 전달한 패키지의 크기도 정해졌다. 잔류 프로세스가 이 값을 키우지 않는다.
- `open_ended_per_run`(실행 시간) — 결과 불명·잔류 활동이면 값은 남기되 `unresolved`.
  프로세스가 남아 있으면 관측값이 최종이라는 근거가 없다.
- `post_hoc_reported`(토큰·비용) — 어댑터가 준 값을 확정한다. 추정이라는 사실은
  `measurement` 가 따로 말한다. 주지 않았으면 `unavailable` 이며 0 이 아니다.

**반대 방향도 함께 막았다.** 확정 조건을 느슨하게 묶으면 잔류 프로세스가 있는데 실행
시간을 최종으로 적게 된다. 회귀 시험은 실제 어댑터와 같은 보고를 쓴다
(`test_a_reported_usage_is_settled_even_when_residual_activity_is_unknown`).

### `SettleSource.CLOCK_UNAVAILABLE` 을 더했다

배정 시각이 없어 실행 시간을 도출하지 못한 경우를 `adapter_not_reported` 로 적고
있었다. **어댑터의 문제가 아니다** — 둘을 같은 값으로 두면 "CLI 가 안 줬다"와 "우리가
재지 않았다"가 섞여 원인을 물을 수 없다.

### 고정 컨텍스트 참조를 Run 생성 트랜잭션 안으로 옮겼다

계획 5절은 예약만 트랜잭션에 넣을 생각이었다. 그러면 예약한 `context_bytes` 와 실제로
들어간 참조가 어긋날 수 있다(그 사이에 실패하면 참조 없는 Run 이 남는다). 판정은
바뀌지 않으며 원자성만 좁혔다.

### 예약값 계산을 `_planned_reservation_for()` 하나로 모았다

진입 검사와 Run 생성이 각각 계산하고 있었다. 한쪽만 고쳐지면 "검사는 통과했는데 생성이
막히는" 상태가 조용히 생긴다.
