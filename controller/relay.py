"""원문 일시중계 버퍼.

data-boundary-review.md 3절: 제어부는 원문을 **잠시 취급**할 수 있지만 영구 보관하지
않는다. 그래서 접수한 본문은 이 프로세스의 메모리에만 두고, 소유 Runner가 영속 저장을
보고하면 즉시 버린다.

의도한 결과가 하나 있다. **제어부가 그 사이에 재시작하면 본문은 사라진다.**
이는 결함이 아니라 요구다 — 저장 완료로 응답한 적이 없는 입력이고,
서버에 영구 저장해서 우회하지 않는다(NFR-01). 사라진 접수는
`lost_before_persist` 상태로 드러낸다.

메모리 중계가 "서버로 전송되지 않음"을 뜻하지 않는다는 점도 그대로 유지한다.
"""

from __future__ import annotations

import hashlib
import threading


def content_hash(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


class RelayBuffer:
    """intake_id → 원문 바이트. 프로세스 메모리에만 존재한다."""

    def __init__(self) -> None:
        self._items: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def put(self, intake_id: str, body: bytes) -> None:
        with self._lock:
            self._items[intake_id] = body

    def get(self, intake_id: str) -> bytes | None:
        with self._lock:
            return self._items.get(intake_id)

    def drop(self, intake_id: str) -> None:
        with self._lock:
            self._items.pop(intake_id, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
