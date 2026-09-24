"""제어부 **메모리** 값 저장소(UI-04d).

`RelayBuffer`(원문 바이트 중계)와 같은 자리에 두는, 짧은 수명의 **값**(JSON 으로 만들 수 있는 것) 저장소다.
검색 요청·후보·발췌(D-84)와 미커밋 변경 목록(D-77)이 여기 산다 — data-boundary 1·3절: 제어부는 그런 것을
**잠시 취급**할 수 있지만 영구 보관하지 않는다. 그래서 프로세스 메모리에만 두고 TTL 이 지나면 버린다.
제어부가 재시작하면 사라진다 — 결함이 아니라 요구다. 사라진 것은 `expired`/`available = False` 로 드러내고
사람이 다시 요청한다.

DB·로그에는 이 값이 가지 않는다. 검색어도 여기에만 있다.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable


class TransientStore:
    """key → (값, 만료 시각). 프로세스 메모리에만 존재한다."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._items: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()
        self._clock = clock or time.monotonic

    def put(self, key: str, value: Any, ttl_seconds: float) -> None:
        with self._lock:
            self._items[key] = (value, self._clock() + float(ttl_seconds))

    def get(self, key: str) -> Any | None:
        """값. 만료됐으면 지우고 `None`."""
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            value, expires = item
            if self._clock() >= expires:
                self._items.pop(key, None)
                return None
            return value

    def touch(self, key: str, ttl_seconds: float) -> bool:
        """만료 시각을 지금부터 다시 센다. 없으면(만료 포함) 거짓."""
        with self._lock:
            item = self._items.get(key)
            if item is None or self._clock() >= item[1]:
                self._items.pop(key, None)
                return False
            self._items[key] = (item[0], self._clock() + float(ttl_seconds))
            return True

    def drop(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)

    def items(self, prefix: str = "") -> list[tuple[str, Any]]:
        """살아 있는 항목(만료된 것은 지운다). 넣은 순서."""
        with self._lock:
            now = self._clock()
            dead = [k for k, (_, exp) in self._items.items() if now >= exp]
            for k in dead:
                self._items.pop(k, None)
            return [(k, v) for k, (v, _) in self._items.items() if k.startswith(prefix)]

    def __len__(self) -> int:
        return len(self.items())
