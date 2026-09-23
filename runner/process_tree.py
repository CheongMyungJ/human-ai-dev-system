"""CLI 프로세스 트리 제어 (UI-02).

P1-03 이 남긴 결론을 구현한다.

    (가) 프로세스 트리 단위 종료   PATH 진입점(`codex.CMD`) 하나를 끝내면 `codex.exe →
                                  명령 실행기 → pwsh` 가 남는다(P1-03 #6)
    (나) 종료 확인 후에만 다음으로  "종료 신호를 보냈다"와 "끝났다"는 다르다
    (다) 확인 전에는 불명 유지      확인하지 못한 것을 `none` 으로 적지 않는다

**Windows job object 를 쓴다.** 실행마다 이름 있는 job 을 만들고 `KILL_ON_JOB_CLOSE` 를
걸며 이탈(breakaway)을 허용하지 않는다. CLI 는 **일시 정지 상태로 만들어** job 에 넣은
뒤에 재개한다 — 넣기 전에 자식이 생기면 그 자식은 job 밖에 남는다. 재개 전에 시작
기록을 원장에 남기는 것은 호출자(`runner.agent`)의 몫이며, 이 모듈은 그 순서가 가능하도록
"만들기 → 넣기 → (기록) → 재개"를 따로 연다.

**확인의 근거를 값으로 남긴다.** `none` 은 아래 중 하나가 있을 때만이다.

    job_empty                 job 의 활성 프로세스가 0 이다(조회)
    job_terminated            job 을 종료했고 활성 0 을 확인했다(종료한 수와 함께)
    job_closed_kill_on_close  job 이 이미 없고 시작 기록이 KILL_ON_JOB_CLOSE 다 — 마지막
                              핸들이 닫힐 때(Runner 가 죽었거나 실행기가 정리했다) OS 가
                              남은 트리를 끝냈다. 루트가 살아 있으면 이 근거를 쓰지 않는다
    host_rebooted             호스트가 그 실행 착수 뒤에 다시 부팅됐다
    in_process                Runner 프로세스 안의 실행기였고 그 프로세스가 끝났다

비 Windows 는 트리 제어를 지원하지 않는다(`not_observable`). 지원하지 않는 것을 지원한다고
보고하지 않는다.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

IS_WINDOWS = os.name == "nt"

#: 중단 뒤 활성 프로세스 0 을 기다리는 기본 시간. 상세 설계 제안값이다.
DEFAULT_CONFIRM_TIMEOUT = 15.0

# 잔류 확인 근거. 값은 제어부 `ResidualBasis` 와 같다.
BASIS_JOB_EMPTY = "job_empty"
BASIS_JOB_TERMINATED = "job_terminated"
BASIS_JOB_CLOSED_KILL_ON_CLOSE = "job_closed_kill_on_close"
BASIS_HOST_REBOOTED = "host_rebooted"
BASIS_IN_PROCESS = "in_process"
BASIS_NOT_LAUNCHED = "not_launched"
BASIS_NOT_OBSERVABLE = "not_observable"
BASIS_ROOT_PROCESS_ALIVE = "root_process_alive"
BASIS_TERMINATE_UNCONFIRMED = "terminate_unconfirmed"
BASIS_OWNER_RUNNER_ALIVE = "owner_runner_alive"


class TreeControlUnavailable(RuntimeError):
    """job 을 만들거나 프로세스를 넣지 못했다. **더 약한 방식으로 대신 실행하지 않는다.**"""


@dataclass(frozen=True)
class ResidualObservation:
    """잔류 활동 관측 하나. `residual` 은 `none` 또는 `unknown` 이다."""

    residual: str
    basis: str
    terminated: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"residual": self.residual, "basis": self.basis, "terminated": self.terminated}


# ====================================================================== Win32

if IS_WINDOWS:
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _JobObjectBasicAccountingInformation = 1
    _JobObjectExtendedLimitInformation = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_QUERY = 0x0004
    _JOB_OBJECT_TERMINATE = 0x0008
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _THREAD_SUSPEND_RESUME = 0x0002
    _TH32CS_SNAPTHREAD = 0x00000004
    _STILL_ACTIVE = 259
    _ERROR_FILE_NOT_FOUND = 2
    _ERROR_INVALID_PARAMETER = 87
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    CREATE_SUSPENDED = 0x00000004

    class _BasicLimit(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class _ExtendedLimit(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimit),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _BasicAccounting(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_int64),
            ("TotalKernelTime", ctypes.c_int64),
            ("ThisPeriodTotalUserTime", ctypes.c_int64),
            ("ThisPeriodTotalKernelTime", ctypes.c_int64),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    class _ThreadEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]

    _k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    _k32.OpenJobObjectW.restype = wintypes.HANDLE
    _k32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD
    ]
    _k32.SetInformationJobObject.restype = wintypes.BOOL
    _k32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, wintypes.LPDWORD
    ]
    _k32.QueryInformationJobObject.restype = wintypes.BOOL
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.AssignProcessToJobObject.restype = wintypes.BOOL
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.TerminateJobObject.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.CloseHandle.restype = wintypes.BOOL
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    _k32.GetProcessTimes.restype = wintypes.BOOL
    _k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, wintypes.LPDWORD]
    _k32.GetExitCodeProcess.restype = wintypes.BOOL
    _k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _k32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)]
    _k32.Thread32First.restype = wintypes.BOOL
    _k32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)]
    _k32.Thread32Next.restype = wintypes.BOOL
    _k32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.OpenThread.restype = wintypes.HANDLE
    _k32.ResumeThread.argtypes = [wintypes.HANDLE]
    _k32.ResumeThread.restype = wintypes.DWORD
    _k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.TerminateProcess.restype = wintypes.BOOL
    _k32.GetTickCount64.argtypes = []
    _k32.GetTickCount64.restype = ctypes.c_uint64
else:  # pragma: no cover - 비 Windows 는 트리 제어를 지원하지 않는다
    CREATE_SUSPENDED = 0


def _last_error() -> int:
    return ctypes.get_last_error()


def _winerror(what: str) -> TreeControlUnavailable:
    return TreeControlUnavailable(f"{what} 실패 (winerror {_last_error()})")


def job_name_for(runner_id: str, run_id: str, generation: int) -> str:
    """실행 하나의 job 이름. **세션 이름공간(`Local\\`)** 이며 재시작한 Runner 가 이름으로 찾는다."""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in f"{runner_id}-{run_id}-{generation}")
    return f"Local\\hads-run-{safe}"[:240]


# ================================================================ 프로세스 조회


def _filetime(ft: Any) -> int:
    return (int(ft.dwHighDateTime) << 32) | int(ft.dwLowDateTime)


def _creation_time_of_handle(handle: int) -> int | None:
    created = wintypes.FILETIME()
    exited = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    if not _k32.GetProcessTimes(
        handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)
    ):
        return None
    return _filetime(created)


def process_identity(pid: int) -> dict[str, Any] | None:
    """`{pid, created}` — pid 는 재사용되므로 **생성 시각과 짝으로** 기록한다."""
    if not IS_WINDOWS:
        return {"pid": pid, "created": None}
    handle = _k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        return {"pid": pid, "created": _creation_time_of_handle(handle)}
    finally:
        _k32.CloseHandle(handle)


def process_alive(pid: int | None, created: int | None) -> bool | None:
    """그 프로세스(pid + 생성 시각)가 아직 살아 있는가. 모르면 `None`.

    같은 pid 라도 생성 시각이 다르면 **다른 프로세스**다 — 재사용된 pid 를 살아 있다고
    읽으면 끝난 실행이 영원히 불명이 되고, 반대로 읽으면 살아 있는 트리를 놓친다.
    """
    if not IS_WINDOWS or pid is None:
        return None
    handle = _k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        err = _last_error()
        # 없는 pid 는 ERROR_INVALID_PARAMETER 다. 권한 부족 등은 모른다.
        return False if err == _ERROR_INVALID_PARAMETER else None
    try:
        if created is not None and _creation_time_of_handle(handle) != int(created):
            return False
        code = wintypes.DWORD()
        if not _k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return None
        return code.value == _STILL_ACTIVE
    finally:
        _k32.CloseHandle(handle)


def host_boot_time() -> datetime | None:
    """이 호스트가 부팅된 시각(UTC). 모르면 `None`."""
    if not IS_WINDOWS:
        return None
    uptime_ms = int(_k32.GetTickCount64())
    return datetime.now(timezone.utc) - timedelta(milliseconds=uptime_ms)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def rebooted_since(started_at: str | None, margin_seconds: float = 5.0) -> bool:
    """그 시각 **뒤에** 호스트가 다시 부팅됐는가. 모르면 False(확인 근거로 쓰지 않는다)."""
    started = _parse_ts(started_at)
    boot = host_boot_time()
    if started is None or boot is None:
        return False
    return boot > started + timedelta(seconds=margin_seconds)


# ====================================================================== job


class JobTree:
    """실행 하나의 프로세스 트리. Windows job object 하나를 감싼다."""

    def __init__(self, name: str, handle: int) -> None:
        self.name = name
        self._handle = handle

    # ------------------------------------------------------------ 만들기·열기

    @classmethod
    def create(cls, name: str) -> "JobTree":
        """이름 있는 job 을 만들고 `KILL_ON_JOB_CLOSE` 를 건다. 이탈은 허용하지 않는다."""
        if not IS_WINDOWS:
            raise TreeControlUnavailable("프로세스 트리 제어는 Windows 에서만 지원한다")
        handle = _k32.CreateJobObjectW(None, name)
        if not handle:
            raise _winerror("CreateJobObjectW")
        info = _ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _k32.SetInformationJobObject(
            handle, _JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
        ):
            error = _winerror("SetInformationJobObject")
            _k32.CloseHandle(handle)
            raise error
        return cls(name, handle)

    @classmethod
    def open_existing(cls, name: str) -> "JobTree | None | str":
        """이미 있는 job 을 이름으로 연다. 없으면 `None`, 확인할 수 없으면 `"unknown"`."""
        if not IS_WINDOWS:
            return "unknown"
        handle = _k32.OpenJobObjectW(_JOB_OBJECT_QUERY | _JOB_OBJECT_TERMINATE, False, name)
        if not handle:
            return None if _last_error() == _ERROR_FILE_NOT_FOUND else "unknown"
        return cls(name, handle)

    # ------------------------------------------------------------ 프로세스

    def spawn_suspended(self, command: list[str], **popen_kwargs: Any) -> subprocess.Popen:
        """CLI 를 **일시 정지 상태로** 만들고 job 에 넣는다. 재개는 `resume()` 이다.

        넣지 못하면 정지된 프로세스를 끝내고 올린다 — 그 프로세스는 한 줄도 실행하지
        않았다.
        """
        flags = popen_kwargs.pop("creationflags", 0) | CREATE_SUSPENDED
        proc = subprocess.Popen(command, creationflags=flags, **popen_kwargs)
        if not _k32.AssignProcessToJobObject(self._handle, int(proc._handle)):  # noqa: SLF001
            error = _winerror("AssignProcessToJobObject")
            _k32.TerminateProcess(int(proc._handle), 1)  # noqa: SLF001
            proc.wait()
            raise error
        return proc

    @staticmethod
    def launch_identity(proc: subprocess.Popen) -> dict[str, Any]:
        """원장에 남길 루트 프로세스의 정체(pid + 생성 시각)."""
        return {
            "pid": proc.pid,
            "pid_created": _creation_time_of_handle(int(proc._handle)),  # noqa: SLF001
        }

    @staticmethod
    def resume(proc: subprocess.Popen) -> None:
        """정지된 루트 프로세스의 스레드를 재개한다. 재개하지 못하면 올린다."""
        snapshot = _k32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
        if not snapshot or snapshot == _INVALID_HANDLE_VALUE:
            raise _winerror("CreateToolhelp32Snapshot")
        resumed = 0
        try:
            entry = _ThreadEntry()
            entry.dwSize = ctypes.sizeof(_ThreadEntry)
            ok = _k32.Thread32First(snapshot, ctypes.byref(entry))
            while ok:
                if entry.th32OwnerProcessID == proc.pid:
                    thread = _k32.OpenThread(_THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                    if thread:
                        try:
                            if _k32.ResumeThread(thread) != 0xFFFFFFFF:
                                resumed += 1
                        finally:
                            _k32.CloseHandle(thread)
                ok = _k32.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            _k32.CloseHandle(snapshot)
        if resumed == 0:
            raise TreeControlUnavailable(f"재개할 스레드를 찾지 못했다 (pid {proc.pid})")

    # ------------------------------------------------------------ 상태·종료

    def active_processes(self) -> int | None:
        info = _BasicAccounting()
        if not _k32.QueryInformationJobObject(
            self._handle,
            _JobObjectBasicAccountingInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        ):
            return None
        return int(info.ActiveProcesses)

    def terminate(self, exit_code: int = 1) -> bool:
        return bool(_k32.TerminateJobObject(self._handle, exit_code))

    def wait_empty(self, timeout: float = DEFAULT_CONFIRM_TIMEOUT) -> bool:
        """활성 프로세스가 0 이 될 때까지 기다린다. **0 을 본 때만 True 다.**"""
        deadline = time.monotonic() + timeout
        while True:
            active = self.active_processes()
            if active == 0:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def terminate_and_confirm(
        self, timeout: float = DEFAULT_CONFIRM_TIMEOUT
    ) -> ResidualObservation:
        """남은 프로세스를 끝내고 **0 을 확인한다.** 처음부터 0 이면 종료하지 않는다."""
        active = self.active_processes()
        if active == 0:
            return ResidualObservation("none", BASIS_JOB_EMPTY, 0)
        self.terminate()
        if self.wait_empty(timeout):
            return ResidualObservation("none", BASIS_JOB_TERMINATED, active)
        return ResidualObservation("unknown", BASIS_TERMINATE_UNCONFIRMED, active)

    def close(self) -> None:
        """핸들을 닫는다. **남은 프로세스가 있으면 OS 가 끝낸다**(`KILL_ON_JOB_CLOSE`)."""
        if self._handle:
            _k32.CloseHandle(self._handle)
            self._handle = 0


# ================================================================ 잔류 확인


def check_residual(
    launch: dict[str, Any] | None,
    started_at: str | None,
    *,
    confirm_timeout: float = DEFAULT_CONFIRM_TIMEOUT,
) -> ResidualObservation:
    """**끝난 Runner 프로세스가 남긴** 실행의 잔류 활동을 확인한다(재시작 대조·재확인).

    지금 이 프로세스가 돌리고 있는 실행에는 쓰지 않는다 — 그 실행의 job 은 여기서 연
    핸들과 같은 것이며, 종료하면 진행 중인 실행을 끊는다. 호출자(`runner.agent`)가 실행
    중 표로 그것을 거른다.

    `launch` 는 원장의 시작 기록이다. job 이 아직 있으면 **남은 것을 종료하고** 확인한다 —
    끝난 실행의 잔류이기 때문이다.
    """
    if launch and launch.get("in_process"):
        return ResidualObservation("none", BASIS_IN_PROCESS)
    if not IS_WINDOWS:
        return ResidualObservation("unknown", BASIS_NOT_OBSERVABLE)
    if not launch or not launch.get("job_name"):
        # 시작 기록이 없는 옛 원장(v1) 이다. 재부팅만 근거가 된다.
        if rebooted_since(started_at):
            return ResidualObservation("none", BASIS_HOST_REBOOTED)
        return ResidualObservation("unknown", BASIS_NOT_OBSERVABLE)
    opened = JobTree.open_existing(launch["job_name"])
    if opened == "unknown":
        if rebooted_since(started_at):
            return ResidualObservation("none", BASIS_HOST_REBOOTED)
        return ResidualObservation("unknown", BASIS_NOT_OBSERVABLE)
    if opened is None:
        # job 이 없다. 시작 기록이 KILL_ON_JOB_CLOSE 이면 마지막 핸들이 닫힐 때 OS 가
        # 트리를 끝냈다. **루트가 같은 생성 시각으로 살아 있으면** 그 전제가 깨졌다.
        alive = process_alive(launch.get("pid"), launch.get("pid_created"))
        if alive:
            return ResidualObservation("unknown", BASIS_ROOT_PROCESS_ALIVE)
        if rebooted_since(started_at):
            return ResidualObservation("none", BASIS_HOST_REBOOTED)
        if launch.get("kill_on_close") and alive is False:
            return ResidualObservation("none", BASIS_JOB_CLOSED_KILL_ON_CLOSE)
        return ResidualObservation("unknown", BASIS_NOT_OBSERVABLE)
    assert isinstance(opened, JobTree)
    try:
        return opened.terminate_and_confirm(confirm_timeout)
    finally:
        opened.close()
