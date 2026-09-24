"""대화 검색의 순수 규칙(UI-04d, D-84).

제어부(서버 필드)와 Runner(본문)가 **같은 일치 규칙**을 쓴다 — 서버 제목에서 찾은 낱말과 PC 본문에서
찾은 낱말이 다른 규칙으로 잡히면 "본문에는 없고 제목에만 있다" 를 사람이 설명할 수 없다.

규칙은 하나다: 공백으로 나눈 낱말 **전부**가 대소문자 무시로 들어 있어야 일치한다(AND). 정규식·형태소·
유사어는 없다. 한글 조사가 붙은 낱말은 부분 문자열로 잡힌다(`검색을` 은 `검색` 에 잡힌다).

여기에는 저장이 없다. 발췌는 본문의 일부이지만 **이 모듈이 어디에 남기지 않는다** — 제어부는 메모리로만
중계하고(data-boundary 1·3절) Runner 는 자기 원문에서 만든다.
"""

from __future__ import annotations

import re
from typing import Any

#: 검색어 길이 상한. 요약과 같은 자리의 짧은 값이다.
MAX_QUERY = 200
#: 한 검색에 쓰는 낱말 수 상한. 더 주면 앞의 것만 쓴다(사람에게 알린다).
MAX_TOKENS = 8
#: 본문 후보 상한(최신순). 넘으면 `truncated` 로 드러낸다 — 전부 찾았다고 말하지 않는다.
MAX_CANDIDATES = 2000
#: 발췌 너비(자). 첫 일치 낱말을 가운데 둔다.
SNIPPET_WIDTH = 160
#: Runner 가 목록에 올릴 미커밋 항목 수 상한(D-77 목록 — 검색이 아니지만 같은 "메모리 목록" 규칙).
MAX_ENTRIES = 500

_SPACE = re.compile(r"\s+")


def tokens(query: str) -> tuple[str, ...]:
    """검색어 → 낱말(소문자·중복 제거·순서 유지). 빈 검색어는 빈 튜플."""
    seen: list[str] = []
    for word in _SPACE.split((query or "").strip().lower()):
        if word and word not in seen:
            seen.append(word)
    return tuple(seen[:MAX_TOKENS])


def matches(text: str | None, words: tuple[str, ...]) -> bool:
    """모든 낱말이 들어 있는가(대소문자 무시). 낱말이 없으면 거짓 — 빈 검색은 전부 일치가 아니다."""
    if not words or not text:
        return False
    lowered = text.lower()
    return all(word in lowered for word in words)


def snippet(text: str, words: tuple[str, ...], width: int = SNIPPET_WIDTH) -> dict[str, Any]:
    """첫 일치 주변의 발췌와 일치 수. 줄바꿈은 공백으로 편다.

    `match_count` 는 낱말별 등장 수의 합이다(겹침 없이 왼쪽부터). 발췌는 **본문의 일부**이며 부르는 쪽이
    저장하지 않을 책임을 진다.
    """
    flat = _SPACE.sub(" ", text or "").strip()
    lowered = flat.lower()
    first = min((lowered.find(w) for w in words if w in lowered), default=-1)
    count = sum(lowered.count(w) for w in words)
    if first < 0:
        return {"snippet": flat[:width], "match_count": count}
    start = max(0, first - width // 3)
    end = min(len(flat), start + width)
    start = max(0, end - width)
    piece = flat[start:end]
    if start > 0:
        piece = "…" + piece
    if end < len(flat):
        piece = piece + "…"
    return {"snippet": piece, "match_count": count}
