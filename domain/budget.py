"""예산의 예약 계약과 사용량 정규화(P3-R3).

**여기에는 DB도 HTTP도 없다.** 순수 함수만 두는 이유는 제어부와 시험이 같은 계약을
쓰게 하기 위해서다. 제품 기대값을 구현 코드에서 복제한 시험은 아무 것도 확인하지
않으므로(DEVELOPMENT.md 10절), 계약 자체를 한 곳에 두고 양쪽이 그것을 참조한다.

R1 의 `BUDGET_MEASUREMENT` 는 **"그 값을 어떻게 아는가"** 를 말한다. 이 파일은 그
옆에 **"실행 전에 얼마를 잡을 수 있는가"** 를 더한다. 두 질문의 답이 다르기 때문에
표가 둘이다 — 실행 시간은 끝나면 정확히 잴 수 있지만(`exact`) 시작 전에 얼마가 될지는
모른다. 그 차이가 hard 한도로 약속할 수 있는 것과 없는 것을 가른다(D-61).
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from domain.models import (
    BUDGET_MEASUREMENT,
    BudgetMeasurement,
    BudgetMetric,
    BudgetThreshold,
    RunRole,
)


class ReservationKind(str, Enum):
    """실행 **전에** 그 지표의 소비량을 얼마나 아는가.

    `EXACT_PER_RUN`      배정 전에 정확히 안다. 실행 수는 1, 컨텍스트는 만들어 둔
                         패키지의 바이트 수다. 이 지표만 절대 상한을 약속할 수 있다
    `OPEN_ENDED_PER_RUN` 끝나야 안다. 진행 중에는 지금까지의 노출만 관측된다.
                         돌고 있는 CLI 를 초 단위로 끊을 능력이 없으므로(P1-03
                         `cancel_confirmed = unknown`) **절대 상한이 아니다**. UI-02 가
                         사람의 중단으로 트리를 끝내는 능력을 만들었지만 한도 도달에
                         연결하지 않았다 — 여전히 절대 상한이 아니다
    `CASE_CLOCK`         Case 시작 시각에서 도출한다. 예약이라는 개념이 없다 —
                         벽시계는 배정을 줄인다고 느려지지 않는다
    `POST_HOC_REPORTED`  어댑터가 사후에 주거나 주지 않는다. 예약할 수 없다
    """

    EXACT_PER_RUN = "exact_per_run"
    OPEN_ENDED_PER_RUN = "open_ended_per_run"
    CASE_CLOCK = "case_clock"
    POST_HOC_REPORTED = "post_hoc_reported"


class BudgetGuarantee(str, Enum):
    """그 한도로 **무엇을 약속할 수 있는가.**

    `ABSOLUTE`          한도를 넘는 배정이 생기지 않는다
    `NO_ABSOLUTE_CAP`   새 배정은 막지만 진행 중 실행의 초과 노출이 있을 수 있다.
                        노출값과 이유를 함께 표시한다
    `DISPLAY_ONLY`      경고선. 표시이며 보장이 아니다
    `NOT_ENFORCEABLE`   설정을 받지 않는다

    **세 값을 하나로 합치지 않는 것이 이 단계의 요점이다.** hard 한도를 건 사람은
    "이제 초과하지 않는다"고 믿는다. 실행 수에는 그 약속을 지킬 수 있고 실행 시간에는
    지킬 수 없는데, 같은 모양으로 표시하면 없는 보장을 판 것이 된다(D-61).
    """

    ABSOLUTE = "absolute"
    NO_ABSOLUTE_CAP = "no_absolute_cap"
    DISPLAY_ONLY = "display_only"
    NOT_ENFORCEABLE = "not_enforceable"


class ReservationState(str, Enum):
    """예약 한 건의 상태.

    `HELD`       실행이 아직 끝나지 않았다. 노출로 계산한다
    `SETTLED`    실제 사용량이 확정됐다
    `UNRESOLVED` 실행은 끝났는데 **얼마를 썼는지 모른다.** 결과가 `unknown` 이거나
                 어댑터가 사용량을 주지 않은 경우다. **예약을 해제하지 않는다** —
                 "확인 전에 잔여량을 낙관적으로 복구하지 않는다"
                 (autonomy-budget-policy 7절)
    """

    HELD = "held"
    SETTLED = "settled"
    UNRESOLVED = "unresolved"


class ReservationSource(str, Enum):
    """그 예약 행이 어디서 왔는가.

    `MIGRATED_FROM_RUN` 은 v10 이행이 만든 행이다. R3 이전에 실제로 돈 실행의 소비를
    0 으로 두면 스키마를 올리는 것만으로 소비가 초기화된다 — "세션·Task 분할로
    초기화하지 않는다"(D-61)는 이행에도 적용된다. 다만 그 행은 실행 시점에 실제로
    예약을 거친 것이 아니므로 출처를 구별해 남긴다.
    """

    RESERVED = "reserved"
    MIGRATED_FROM_RUN = "migrated_from_run"


class SettleSource(str, Enum):
    """정산값이 어디서 왔는가. **왜 모르는지**를 남기는 자리다."""

    RESERVED_EXACT = "reserved_exact"
    OBSERVED_CLOCK = "observed_clock"
    #: 배정 시각이 없어 실행 시간을 도출할 수 없다. **어댑터의 문제가 아니다** —
    #: 둘을 같은 값으로 적으면 "CLI 가 안 줬다"와 "우리가 재지 않았다"가 섞인다.
    CLOCK_UNAVAILABLE = "clock_unavailable"
    ADAPTER_REPORTED = "adapter_reported"
    ADAPTER_NOT_REPORTED = "adapter_not_reported"
    OUTCOME_UNKNOWN = "outcome_unknown"
    RESIDUAL_ACTIVITY = "residual_activity"
    #: P4-04. Runner 가 CLI 를 부르기 **전에** 멈췄다. 호출이 없었으므로 0 이 확정이다 —
    #: 예약값을 그대로 확정하면 없던 호출이 소비로 남는다.
    NOT_STARTED = "not_started"
    #: P4-09(e), 이슈 #4. 업무 취소 시점에 아직 열려 있던 예약(끝나지 않은 실행이 없으므로 보통 없다). 값을
    #: 모르는 채 닫는다 — `unresolved` 이며 0 이 아니다.
    CASE_CANCELLED = "case_cancelled"
    #: P4-04. Runner 가 재시작 뒤 **자기 원시 출력에서** 되찾은 사용량이다. 어댑터가
    #: 결과로 보고한 값과 출처가 같지만(같은 CLI 출력) 경로가 다르므로 구분해 둔다.
    RECOVERED_FROM_RUNNER_LOG = "recovered_from_runner_log"
    #: UI-04c(D-88). 재배정으로 **옛 세대**가 된 예약이다. 그 호출이 언제 끝났는지(끝났는지)는
    #: 모르므로 재배정 시점까지 관측한 값으로 `unresolved` 에 둔다 — 벽시계로 계속 자라게 두면
    #: 실행시간 합계가 거짓이 되고, 0 으로 풀면 있었던 호출이 공짜가 된다(P3-R3 7절).
    REASSIGNED = "reassigned"


#: 사용량 묶음에 이 표시가 있으면 Runner 가 재시작 뒤 원시 출력에서 되찾은 값이다.
USAGE_RECOVERED_FROM = "recovered_from"
USAGE_RECOVERED_FROM_RAW_LOG = "runner_raw_log"


def usage_was_recovered(usage: Any) -> bool:
    return isinstance(usage, dict) and usage.get(USAGE_RECOVERED_FROM) == USAGE_RECOVERED_FROM_RAW_LOG


#: 지표별 예약 계약. **`BUDGET_MEASUREMENT` 와 짝이지 같은 표가 아니다.**
#:
#: `execution_seconds` 가 `exact` 측정인데 `open_ended` 예약인 것이 이 표가 따로
#: 필요한 이유 전체다. 끝나면 정확히 잴 수 있지만 시작 전에는 얼마가 될지 모르고,
#: 모르는 양은 예약할 수 없다.
RESERVATION_KIND: dict[BudgetMetric, ReservationKind] = {
    BudgetMetric.RUN_COUNT: ReservationKind.EXACT_PER_RUN,
    BudgetMetric.REVIEW_RUN_COUNT: ReservationKind.EXACT_PER_RUN,
    BudgetMetric.CONTEXT_BYTES: ReservationKind.EXACT_PER_RUN,
    BudgetMetric.EXECUTION_SECONDS: ReservationKind.OPEN_ENDED_PER_RUN,
    BudgetMetric.ELAPSED_SECONDS: ReservationKind.CASE_CLOCK,
    BudgetMetric.INPUT_TOKENS: ReservationKind.POST_HOC_REPORTED,
    BudgetMetric.OUTPUT_TOKENS: ReservationKind.POST_HOC_REPORTED,
    BudgetMetric.ESTIMATED_COST: ReservationKind.POST_HOC_REPORTED,
}

#: 그 지표를 왜 그렇게 예약하는가. 화면과 조회가 그대로 보여 준다 — 사람이 "왜 이
#: 한도는 절대 상한이 아닌가"를 물었을 때 코드를 읽게 하지 않는다(FR-14).
RESERVATION_REASON: dict[BudgetMetric, str] = {
    BudgetMetric.RUN_COUNT: "시스템이 시작한 호출을 센다. 배정 전에 정확히 1 이다",
    BudgetMetric.REVIEW_RUN_COUNT: "검토 역할의 실행만 센다. 전체 실행 수에서 중복"
    " 차감하지 않는다",
    BudgetMetric.CONTEXT_BYTES: "제어부가 만들어 전달한 입력 패키지의 크기다."
    " CLI 가 내부에서 더 읽은 자료는 관측 범위 밖이다",
    BudgetMetric.EXECUTION_SECONDS: "끝나야 실제 시간을 안다. 진행 중에는 지금까지의"
    " 노출만 보이고, 돌고 있는 실행을 초 단위로 끊을 수 없다(P1-03)."
    " 실행별 배정~종료 시각의 합계다 — 논의·업무·재시도·종료 후 설명 실행 전부, 병렬은 각각,"
    " 사람의 답변 대기는 실행 밖이라 들어가지 않는다(D-88)",
    BudgetMetric.ELAPSED_SECONDS: "Case 시작부터의 벽시계다. 배정을 멈춰도 줄지 않는다."
    " 시간 한도의 기본은 실행시간 합계이며 이것은 별도 선택이다(D-88)",
    BudgetMetric.INPUT_TOKENS: "어댑터가 주면 알고 주지 않으면 모른다. 미제공을 0 으로"
    " 적지 않는다",
    BudgetMetric.OUTPUT_TOKENS: "같음",
    BudgetMetric.ESTIMATED_COST: "가격·모델·측정 범위에 따른 추정이며 실제 청구액의"
    " 상한이 아니다",
}


def guarantee_for(metric: BudgetMetric, threshold_kind: BudgetThreshold) -> BudgetGuarantee:
    """그 설정으로 무엇을 약속할 수 있는가.

    `warn` 은 언제나 표시일 뿐이다. `hard` 는 셋으로 갈린다.

    - 측정이 정확하지 않으면 **설정 자체를 받지 않는다**(R1 그대로, D-61).
    - 측정이 정확하고 예약도 정확하면 절대 상한을 약속한다.
    - 측정은 정확한데 예약이 열려 있으면(시간) 새 배정만 막는다. 이 경우를
      절대 상한으로 표시하지 않는 것이 R3 의 핵심 구분이다.
    """
    if threshold_kind is BudgetThreshold.WARN:
        return BudgetGuarantee.DISPLAY_ONLY
    if BUDGET_MEASUREMENT[metric] is not BudgetMeasurement.EXACT:
        return BudgetGuarantee.NOT_ENFORCEABLE
    if RESERVATION_KIND[metric] is ReservationKind.EXACT_PER_RUN:
        return BudgetGuarantee.ABSOLUTE
    return BudgetGuarantee.NO_ABSOLUTE_CAP


def reservation_contract() -> dict[str, dict[str, Any]]:
    """지표별 계약 전체. 조회에 그대로 실려 나간다."""
    return {
        metric.value: {
            "measurement": BUDGET_MEASUREMENT[metric].value,
            "reservation": RESERVATION_KIND[metric].value,
            "hard_guarantee": guarantee_for(metric, BudgetThreshold.HARD).value,
            "reason": RESERVATION_REASON[metric],
        }
        for metric in BudgetMetric
    }


def planned_reservation(
    role: RunRole, context_bytes: int
) -> dict[BudgetMetric, float | None]:
    """이 실행 하나가 잡는 양.

    `None` 은 **"잡기는 하는데 얼마인지 모른다"** 이다. 0 이 아니다 — 0 으로 적으면
    그 실행이 시간을 쓰지 않는 것처럼 보이고 잔여량이 실제보다 커진다(D-61).

    `CASE_CLOCK` 과 `POST_HOC_REPORTED` 는 예약 행을 만들지 않는다. 벽시계는 실행이
    잡는 것이 아니고, 사후 보고 지표는 실행 전에 잡을 근거가 전혀 없다. 사후 보고는
    정산 시점에 행이 생긴다.
    """
    planned: dict[BudgetMetric, float | None] = {
        BudgetMetric.RUN_COUNT: 1.0,
        BudgetMetric.CONTEXT_BYTES: float(context_bytes),
        # 끝나야 안다. 진행 중 노출은 `now - assigned_at` 로 따로 관측한다.
        BudgetMetric.EXECUTION_SECONDS: None,
    }
    if role is RunRole.REVIEWER:
        # **검토 실행은 두 축에 한 번씩 잡힌다.** 전체 실행 수에서 빼지 않는다 —
        # 검토는 전체 AI 실행의 부분집합이며, 빼면 전체 한도가 검토만큼 늘어난다
        # (autonomy-budget-policy 7절).
        planned[BudgetMetric.REVIEW_RUN_COUNT] = 1.0
    return planned


#: 어댑터가 준 토큰 묶음에서 이 이름들을 찾는다. codex 의 `turn.completed.usage` 와
#: claude 의 `result.usage` 에서 실측한 이름이다(P1-02 결과 문서). 없는 이름을
#: 추측해 채우지 않는다 — 찾지 못하면 `unavailable` 이다.
_TOKEN_KEYS: dict[BudgetMetric, tuple[str, ...]] = {
    BudgetMetric.INPUT_TOKENS: ("input_tokens",),
    BudgetMetric.OUTPUT_TOKENS: ("output_tokens",),
}


def normalize_usage(usage: Any) -> dict[BudgetMetric, float | None]:
    """어댑터 사용량 → 지표값.

    입력은 `{"tokens": {...}, "cost_usd": ... }` 또는 `"not_reported"` 다
    (`runner.cli_events` 가 만드는 모양).

    **`None` 은 "모른다" 이며 0 이 아니다.** 미제공을 0 으로 기록하면 한도가 영원히
    남아 있는 것처럼 보인다(D-61). 그래서 값을 찾지 못한 지표는 키를 두되 `None` 으로
    돌려주고, 집계가 그것을 "확정되지 않음"으로 센다.

    `cached_input_tokens` 같은 추가 항목은 더하지 않는다. 무엇을 합산해야 공급자의
    청구와 맞는지 실측하지 않았고, 추측한 합계에 한도를 걸면 그 한도가 무엇을 뜻하는지
    아무도 말할 수 없다.
    """
    result: dict[BudgetMetric, float | None] = {
        BudgetMetric.INPUT_TOKENS: None,
        BudgetMetric.OUTPUT_TOKENS: None,
        BudgetMetric.ESTIMATED_COST: None,
    }
    if not isinstance(usage, dict):
        return result

    tokens = usage.get("tokens")
    if isinstance(tokens, dict):
        for metric, keys in _TOKEN_KEYS.items():
            for key in keys:
                value = tokens.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    result[metric] = float(value)
                    break

    cost = usage.get("cost_usd")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        result[BudgetMetric.ESTIMATED_COST] = float(cost)
    return result


def measurement_for_settlement(metric: BudgetMetric, value: float | None) -> BudgetMeasurement:
    """정산된 값의 측정 방식.

    값을 얻지 못했으면 `UNAVAILABLE` 이다. 지표의 정적 계약(`estimated`)을 그대로
    적으면, 받은 적 없는 추정값이 있는 것처럼 보인다.
    """
    if value is None:
        return BudgetMeasurement.UNAVAILABLE
    return BUDGET_MEASUREMENT[metric]
