"""Runner 로컬 원문 저장소.

여기가 원문의 영속 위치다. 제어부에는 참조만 올라간다(D-51, NFR-12).
경로는 `artifact_id/revision` 으로만 결정한다. 호출자가 임의 경로를 지정할 수 없다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def content_hash(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


@dataclass(frozen=True)
class StoredArtifact:
    artifact_id: str
    revision: int
    content_hash: str
    byte_size: int
    path: Path


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, artifact_id: str, revision: int) -> Path:
        if not _SAFE_ID.fullmatch(artifact_id):
            raise ValueError(f"unsafe artifact id: {artifact_id!r}")
        if revision < 1:
            raise ValueError(f"invalid revision: {revision}")
        return self.root / artifact_id / f"{revision}.bin"

    def put(self, artifact_id: str, revision: int, body: bytes) -> StoredArtifact:
        """원문을 영속 저장한다. 디스크에 내려간 것을 확인한 뒤 돌아온다.

        `fsync` 를 쓰는 이유는 저장 완료 응답의 내구성 때문이다(NFR-01).
        """
        path = self._path(artifact_id, revision)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "wb") as fh:
            fh.write(body)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        digest = content_hash(body)
        meta = {
            "artifact_id": artifact_id,
            "revision": revision,
            "content_hash": digest,
            "byte_size": len(body),
            "stored_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        }
        meta_path = path.with_suffix(".meta.json")
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return StoredArtifact(artifact_id, revision, digest, len(body), path)

    def get(self, artifact_id: str, revision: int) -> bytes:
        path = self._path(artifact_id, revision)
        if not path.exists():
            raise FileNotFoundError(f"artifact not stored here: {artifact_id}@{revision}")
        return path.read_bytes()

    def path_for(self, artifact_id: str, revision: int) -> Path:
        """이 원문이 저장된 경로. 소유 Runner 안에서만 뜻이 있다.

        제어부는 이 경로를 모른다 — 참조로만 원문을 가리킨다
        (data-boundary-review 1절).
        """
        return self._path(artifact_id, revision)

    def exists(self, artifact_id: str, revision: int) -> bool:
        return self._path(artifact_id, revision).exists()
