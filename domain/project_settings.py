"""프로젝트 기본값 — 설정 키의 검사와 층 합치기(UI-04b, D-72 · autonomy-budget-policy 5절).

**여기에는 DB 도 HTTP 도 없다.** 저장 계층·API·시험이 같은 규칙을 본다.

정책 문서 5절의 우선순위는 `Task 명시 → Case 명시 → Project 기본값 → Profile 기본값 → 시스템
기본값` 이다. 이 파일이 만드는 것은 그중 **Project 기본값** 층 하나다 — Task 층·Profile 기본값
층은 없고, 조회에 그 출처가 나타나지 않는다(없는 설정 화면을 찾게 만들지 않는다).

이 파일이 지키는 것:

    설정은 권한이 아니다        Autonomy·예산·상한·한도의 기본값을 정하는 것은 실행 허용·동의·인수가
                                아니다. 진입 검사·예산 강제·확인 지점은 값을 읽을 뿐이다
    지킬 수 없는 한도를 받지 않는다   예산 기본값의 hard 한도는 Case 한도와 같은 검사를 지난다
                                (`domain.budget.guarantee_for`) — 강제 불가한 지표는 거부한다
    모르는 키를 저장하지 않는다  키 목록은 여기 고정이다. 화면이 새 키를 지어내면 422 다
"""

from __future__ import annotations

from typing import Any

from domain.budget import BudgetGuarantee, guarantee_for
from domain.models import Autonomy, BudgetMetric, BudgetThreshold
from domain.work_flow import LIMIT_KEYS, check_limit

#: 값 하나짜리 설정 키. `budget:{metric}:{threshold}` 는 조합 키다(`budget_key`).
KEY_DEFAULT_TOOL = "default_tool_id"
KEY_DEFAULT_AUTONOMY = "default_autonomy"
KEY_INLINE_LIMIT = "context_inline_limit_bytes"
BUDGET_PREFIX = "budget:"

#: 단순 키 목록(진행 상한 둘 포함). 순서는 화면 표시 순서다.
SIMPLE_KEYS: tuple[str, ...] = (
    KEY_DEFAULT_TOOL,
    KEY_DEFAULT_AUTONOMY,
    *LIMIT_KEYS,
    KEY_INLINE_LIMIT,
)

#: 출처 값. Case 층·시스템 층의 이름은 P4-05b 의 것을 그대로 쓴다.
SOURCE_CASE = "case_setting"
SOURCE_PROJECT = "project_setting"
SOURCE_SYSTEM = "system_default"

#: 값 문자열의 상한(도구 id). 본문이 아니다.
MAX_TOOL_ID = 60


def budget_key(metric: BudgetMetric | str, threshold_kind: BudgetThreshold | str) -> str:
    """예산 기본값의 조합 키."""
    metric_value = metric.value if isinstance(metric, BudgetMetric) else str(metric)
    threshold_value = (
        threshold_kind.value if isinstance(threshold_kind, BudgetThreshold) else str(threshold_kind)
    )
    return f"{BUDGET_PREFIX}{metric_value}:{threshold_value}"


def parse_budget_key(key: str) -> tuple[BudgetMetric, BudgetThreshold]:
    """`budget:{metric}:{threshold}` → 지표·경계. 아니면 `ValueError`."""
    if not key.startswith(BUDGET_PREFIX):
        raise ValueError(f"not a budget key: {key!r}")
    parts = key[len(BUDGET_PREFIX):].split(":")
    if len(parts) != 2:
        raise ValueError(f"budget key must be budget:{{metric}}:{{threshold}}: {key!r}")
    try:
        metric = BudgetMetric(parts[0])
        threshold = BudgetThreshold(parts[1])
    except ValueError:
        raise ValueError(f"unknown budget metric or threshold in {key!r}") from None
    return metric, threshold


def is_known_key(key: str) -> bool:
    if key in SIMPLE_KEYS:
        return True
    try:
        parse_budget_key(key)
    except ValueError:
        return False
    return True


def check_setting(key: str, value: Any) -> Any:
    """설정 값 하나를 검사해 정규화한 값을 돌려준다. 모르는 키·잘못된 값은 `ValueError`.

    `None` 은 여기로 오지 않는다 — "기본값 복귀" 는 저장 계층이 현재 행을 닫는 것이지 값이
    아니다.
    """
    if key == KEY_DEFAULT_TOOL:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("default_tool_id must be a non-empty string")
        tool = value.strip()
        if len(tool) > MAX_TOOL_ID:
            raise ValueError(f"default_tool_id must be at most {MAX_TOOL_ID} characters")
        return tool
    if key == KEY_DEFAULT_AUTONOMY:
        try:
            return Autonomy(value).value
        except ValueError:
            raise ValueError(
                "default_autonomy must be one of " + ", ".join(a.value for a in Autonomy)
            ) from None
    if key in LIMIT_KEYS:
        return check_limit(key, value)
    if key == KEY_INLINE_LIMIT:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("context_inline_limit_bytes must be an integer")
        if value <= 0:
            raise ValueError("context_inline_limit_bytes must be a positive number of bytes")
        return value
    if key.startswith(BUDGET_PREFIX):
        metric, threshold = parse_budget_key(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be a number")
        if float(value) <= 0:
            raise ValueError(f"{key} must be greater than zero")
        # Case 한도와 같은 규칙(D-61): 강제할 수 없는 정확한 hard 한도는 받지 않는다.
        if guarantee_for(metric, threshold) is BudgetGuarantee.NOT_ENFORCEABLE:
            raise ValueError(
                f"{key}: a hard limit on {metric.value} cannot be enforced and is refused"
            )
        return float(value)
    raise ValueError(f"unknown project setting {key!r}")


def resolve(case_value: Any, project_value: Any, system_value: Any) -> tuple[Any, str]:
    """`Case 명시 → Project 기본값 → 시스템 기본값`. 값과 출처를 함께 돌려준다."""
    if case_value is not None:
        return case_value, SOURCE_CASE
    if project_value is not None:
        return project_value, SOURCE_PROJECT
    return system_value, SOURCE_SYSTEM
