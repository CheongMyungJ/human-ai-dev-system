"""식별자 생성과 검증.

ID는 사람이 읽을 수 있는 접두사 + 무작위 부분으로 만든다. 접두사는 로그·증거를 볼 때
어떤 종류의 기록인지 바로 알기 위한 것이며 권한이나 의미를 만들지 않는다.
"""

from __future__ import annotations

import re
import secrets

_RANDOM_BYTES = 8
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,15}-[0-9a-f]{16}$")


def new_id(prefix: str) -> str:
    """`prefix-<16 hex>` 형태의 새 식별자를 만든다."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,15}", prefix):
        raise ValueError(f"invalid id prefix: {prefix!r}")
    return f"{prefix}-{secrets.token_hex(_RANDOM_BYTES)}"


def is_system_id(value: str) -> bool:
    """이 시스템이 만든 형태의 ID인지 확인한다."""
    return bool(_ID_PATTERN.fullmatch(value))


def new_owner_id() -> str:
    return new_id("own")


def new_project_id() -> str:
    return new_id("prj")


def new_case_id() -> str:
    return new_id("case")


def new_run_id() -> str:
    return new_id("run")


def new_artifact_id() -> str:
    return new_id("art")


def new_decision_id() -> str:
    return new_id("dec")


def new_intake_id() -> str:
    return new_id("intake")
