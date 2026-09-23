"""UI-03 — 요청 스레드들이 공유하는 제어부 연결을 **문장 단위로 직렬화한다.**

기본 대화 화면이 조회를 여러 개 겹쳐 보내자(대화·상세·목록·PC 연결·원문 열람 여러 개) 방금
만든 열람 요청을 곧바로 읽으면 "없다"(404)가 나왔다. 원인은 제어부의 공유 연결이었다 — 쓰기
트랜잭션만 잠갔고, 같은 SQL 을 두 스레드가 동시에 실행하면 파이썬 sqlite3 의 준비된 문장
캐시를 함께 써서 한쪽의 매개변수가 다른 쪽 실행을 덮었다(`InterfaceError: bad parameter or other
API misuse` 도 났다). 이 시험은 실제 uvicorn(스레드 풀)에 같은 모양의 부하를 짧게 걸어, 만든
것을 곧바로 읽으면 **언제나 있고** 오류가 없는지 본다. 고치기 전에는 몇 초 안에 수십 건이 틀렸다.
"""

from __future__ import annotations

import threading
import time

import httpx

from controller import db as dbmod
from tests.test_restart_recovery import ControllerProcess, _free_port

SECONDS = 6


def test_rows_are_read_inside_the_lock_and_behave_like_a_cursor(tmp_path):
    """직렬화한 연결의 결과는 잠금 안에서 다 읽힌 뒤 커서처럼 쓰인다."""
    conn = dbmod.SerializedConnection(dbmod.connect(tmp_path / "c.sqlite3"))
    try:
        conn.execute("CREATE TABLE t (n INTEGER)")
        inserted = conn.execute("INSERT INTO t (n) VALUES (1), (2), (3)")
        assert inserted.rowcount == 3
        rows = conn.execute("SELECT n FROM t ORDER BY n")
        assert rows.fetchone()["n"] == 1
        assert [r["n"] for r in rows.fetchall()] == [2, 3]
        assert rows.fetchone() is None
        assert [r["n"] for r in conn.execute("SELECT n FROM t ORDER BY n")] == [1, 2, 3]
        with dbmod.transaction(conn):
            conn.execute("DELETE FROM t WHERE n = 1")
        assert conn.execute("SELECT COUNT(*) AS c FROM t").fetchone()["c"] == 2
    finally:
        conn.close()


def test_what_was_just_created_is_always_there_under_concurrent_requests(tmp_path):
    controller = ControllerProcess(tmp_path / "controller", _free_port())
    controller.start()
    base = controller.base_url
    try:
        c = httpx.Client(base_url=base, timeout=30)
        c.post("/api/runner/register", json={"runner_id": "r1", "name": "r1", "host": "h", "capabilities": []})
        c.post("/api/runner/r1/heartbeat")
        project = c.post(
            "/api/projects", json={"name": "p", "repo_path": "C:/tmp", "default_tool_id": "codex"}
        ).json()
        case_id = c.post(f"/api/projects/{project['id']}/conversations", json={"title": "t"}).json()[
            "case_id"
        ]
        c.post(
            "/api/runner/artifacts",
            json={"runner_id": "r1", "case_id": case_id, "kind": "run_output", "artifact_id": "art-x",
                  "revision": 1, "content_hash": "sha256:00", "byte_size": 1, "summary": "s"},
        )
        # 요청 하나를 열어 둔다 — 이후 전송은 트랜잭션 **안에서** 거부되어 되돌려진다.
        c.post(
            f"/api/cases/{case_id}/messages",
            json={"client_message_id": "m0", "content": "x", "summary": "s", "target_runner_id": "r1"},
        )
        stop = threading.Event()
        stats = {"created": 0, "missing": 0, "errors": 0, "refused": 0, "polls": 0}
        lock = threading.Lock()

        def reader() -> None:
            client = httpx.Client(base_url=base, timeout=30)
            while not stop.is_set():
                created = client.post("/api/artifacts/art-x/1/read-requests", json={"requested_by": "owner"})
                if created.status_code != 201:
                    with lock:
                        stats["errors"] += 1
                    continue
                fetched = client.get(f"/api/read-requests/{created.json()['id']}")
                with lock:
                    stats["created"] += 1
                    stats["missing"] += fetched.status_code == 404
                    stats["errors"] += fetched.status_code >= 500

        def poller() -> None:
            client = httpx.Client(base_url=base, timeout=30)
            while not stop.is_set():
                for path in (f"/api/cases/{case_id}", f"/api/cases/{case_id}/conversation",
                             "/api/projects", "/api/runners"):
                    response = client.get(path)
                    if response.status_code >= 500:
                        with lock:
                            stats["errors"] += 1
                with lock:
                    stats["polls"] += 1

        def refuser() -> None:
            client = httpx.Client(base_url=base, timeout=30)
            n = 0
            while not stop.is_set():
                n += 1
                response = client.post(
                    f"/api/cases/{case_id}/messages",
                    json={"client_message_id": f"m{n}x", "content": "y", "summary": "s",
                          "target_runner_id": "r1"},
                )
                with lock:
                    stats["refused"] += response.status_code == 409
                    stats["errors"] += response.status_code >= 500

        threads = [threading.Thread(target=f) for f in [reader] * 4 + [poller] * 2 + [refuser]]
        for thread in threads:
            thread.start()
        time.sleep(SECONDS)
        stop.set()
        for thread in threads:
            thread.join(timeout=60)
        assert stats["created"] > 100 and stats["polls"] > 5 and stats["refused"] > 10, stats
        assert (stats["missing"], stats["errors"]) == (0, 0), stats
    finally:
        controller.kill_hard()
