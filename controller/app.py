"""제어부 애플리케이션 조립.

로그 규칙: 요청 로그에 **본문을 쓰지 않는다.** 메서드·경로·상태 코드·소요 시간만 남긴다.
data-boundary-review.md 3절이 "요청 본문 로그"를 원문이 남는 경로로 지목하기 때문이다.
tests/test_data_boundary.py 가 로그 파일에서 표식 문자열을 찾아 이를 확인한다.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from controller import db as dbmod
from controller.api import router
from controller.config import ControllerConfig, load_config
from controller.relay import RelayBuffer
from controller.repository import Repository
from controller.request_processor import RequestProcessor
from controller.search import SearchRegistry
from controller.transient import TransientStore
from controller.work_progressor import WorkProgressor

LOGGER_NAME = "hads.controller"


def _setup_logging(config: ControllerConfig) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    handler = logging.FileHandler(config.log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def create_app(config: ControllerConfig | None = None) -> FastAPI:
    config = config or load_config()
    config.ensure_dirs()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # UI-03. 요청 스레드들이 공유하는 연결은 **문장 단위로 직렬화한다**(`SerializedConnection`).
        conn = dbmod.SerializedConnection(dbmod.connect(config.db_path))
        dbmod.migrate(conn)
        app.state.conn = conn
        app.state.config = config
        app.state.relay = RelayBuffer()
        # UI-04d. 검색 요청·발췌(D-84)와 미커밋 변경 목록(D-77)은 **이 프로세스의 메모리**에만 있다 —
        # data-boundary 1·3절. 재시작하면 사라지고 사람이 다시 요청한다. DB 에 표가 없다.
        app.state.searches = SearchRegistry(TransientStore())
        app.state.uncommitted = TransientStore()
        app.state.logger = _setup_logging(config)

        # 이전 프로세스가 중계 중이던 원문은 이 프로세스의 메모리에 없다.
        # 저장 완료로 응답한 적이 없는 입력이므로 사라진 사실을 상태로 드러낸다.
        repo = Repository(conn)
        recovered = 0
        for runner in repo.list_runners():
            for intake in repo.list_pending_intakes(runner["id"]):
                repo.mark_intake_lost(intake["id"])
                recovered += 1

        # 같은 이유로 중계 중이던 **열람 응답**도 이 프로세스에 없다.
        # 원문이 사라진 것이 아니라 중계가 끊긴 것이므로 요청만 expired 로 닫고
        # 사람은 다시 요청하면 된다(data-boundary-review 3절).
        expired = 0
        for pending in repo.list_unfinished_read_requests():
            repo.mark_read_expired(pending["id"])
            expired += 1

        # UI-03. **처리 중인 요청에서 빠진 단계를 잇는다.** 저장 보고나 결과 보고를 받은 뒤
        # 처리기가 돌기 전에 이전 프로세스가 끝났을 수 있다 — 응답 실행이 없는 요청은 만들고,
        # 실행이 전부 끝난 요청은 끝낸다. 유실된 여는 메시지는 위의 복구가 이미 닫았다.
        repo = Repository(
            conn,
            context_inline_limit=config.context_inline_limit_bytes,
            runner_stale_seconds=config.runner_stale_seconds,
            auto_process_requests=config.auto_process_requests,
            progress_limits=config.progress_limits,
        )
        progressor = WorkProgressor(repo, enabled=config.progress_enabled)
        processed = RequestProcessor(
            repo, enabled=config.auto_process_requests, progressor=progressor
        ).recover()
        # P4-05. **업무 단계 진행에서 빠진 걸음을 잇는다.** 요청이 끝나 있으면 스스로 재개하지 않고
        # 멈춤으로 표시한다 — 사람이 계속 진행을 누른다(D-76).
        progressed = progressor.recover()

        app.state.logger.info(
            "startup db=%s lost_pending_intakes=%d expired_read_requests=%d"
            " auto_process_requests=%s auto_progress_work=%s requests_started=%d"
            " requests_finished=%d progress_advanced=%d progress_paused=%d"
            " repair_limit=%d task_retry_limit=%d",
            config.db_path,
            recovered,
            expired,
            config.auto_process_requests,
            config.progress_enabled,
            processed["started"],
            processed["finished"],
            progressed["advanced"],
            progressed["paused"],
            config.progress_limits.repair_limit,
            config.progress_limits.task_retry_limit,
        )
        try:
            yield
        finally:
            app.state.logger.info("shutdown")
            conn.close()

    app = FastAPI(title="human-ai-dev-system controller", version="p2-01", lifespan=lifespan)

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        # 본문·쿼리 문자열 값은 남기지 않는다.
        request.app.state.logger.info(
            "%s %s -> %d (%.1f ms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    app.include_router(router)

    if config.web_dist and Path(config.web_dist).is_dir():
        # 빌드된 웹 UI를 제어부가 그대로 서빙한다.
        # 일반 설치 사용자가 Node로 화면을 직접 빌드하지 않게 하기 위함이다.
        app.mount("/", StaticFiles(directory=str(config.web_dist), html=True), name="web")

    return app


app = create_app()
