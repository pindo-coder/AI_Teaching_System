"""Bounded presentation subprocesses, independent of the web service cgroup.

The host production deployment selects ``systemd`` explicitly (fail closed).
``process`` is the portable development/container mode, not a claim that a
shared container has per-renderer memory isolation.
"""
from __future__ import annotations

from contextlib import contextmanager
import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from uuid import uuid4

from app.core.config import settings

logger = logging.getLogger(__name__)


class RenderCapacityUnavailable(RuntimeError):
    """Transient resource pressure; safe to wait without starting a tool."""


def systemd_available() -> bool:
    return (sys.platform == "linux" and Path("/run/systemd/system").is_dir()
            and Path("/sys/fs/cgroup/cgroup.controllers").is_file()
            and bool(shutil.which("systemd-run")) and bool(shutil.which("systemctl")))


def render_mode() -> str:
    mode = settings.ppt_render_isolation
    if mode == "systemd" and not systemd_available():
        raise RuntimeError("PPT 渲染资源隔离不可用，已停止导出；请检查 systemd/cgroup，已有成果保持不变")
    return "systemd" if mode == "systemd" or mode == "auto" and systemd_available() else "process"


def available_memory_mb() -> int | None:
    if sys.platform != "linux":
        return None
    try:
        values = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
        available = int(values["MemAvailable"].split()[0]) // 1024
        # Containers may have much less memory than the host's MemAvailable.
        group = next((line.split(":", 2)[2] for line in Path("/proc/self/cgroup").read_text().splitlines()
                      if line.startswith("0::")), None)
        if group is not None:
            base = Path("/sys/fs/cgroup") / group.lstrip("/")
            for directory in [base, *base.parents]:
                if directory != Path("/sys/fs/cgroup") and Path("/sys/fs/cgroup") not in directory.parents:
                    break
                limit, usage = directory / "memory.max", directory / "memory.current"
                if limit.is_file() and usage.is_file():
                    maximum = limit.read_text().strip()
                    if maximum != "max":
                        available = min(available, max(0, int(maximum) - int(usage.read_text())) // 1048576)
        return available
    except (OSError, ValueError, KeyError, StopIteration):
        # Linux must not silently skip a safety check it was configured to use.
        raise RuntimeError("无法读取 PPT 渲染内存余量，已有成果保持不变") from None


def memory_budget_mb(minimum_mb: int | None = None) -> int:
    maximum = settings.ppt_render_memory_limit_mb
    minimum = settings.ppt_render_min_memory_mb if minimum_mb is None else minimum_mb
    if minimum > maximum:
        raise RuntimeError("PPT 渲染最小内存不能超过内存上限")
    available = available_memory_mb()
    if available is None:
        return maximum
    budget = min(maximum, available - settings.ppt_render_reserve_mb)
    if budget < minimum:
        logger.warning("ppt_capacity_wait available_mb=%s reserve_mb=%s minimum_mb=%s budget_mb=%s",
                       available, settings.ppt_render_reserve_mb, minimum, budget)
        raise RenderCapacityUnavailable(
            f"服务器可用内存不足（当前 {available} MiB，需预留 {settings.ppt_render_reserve_mb} MiB，"
            f"本阶段最低 {minimum} MiB），已保留课件进度，请稍后继续生成；不会重新生成已有插图")
    return budget


def wait_for_memory_budget(minimum_mb: int | None = None) -> int:
    deadline = time.monotonic() + settings.ppt_render_memory_wait_seconds
    while True:
        try:
            return memory_budget_mb() if minimum_mb is None else memory_budget_mb(minimum_mb)
        except RenderCapacityUnavailable:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.5)


@contextmanager
def export_slot(root: Path):
    """A kernel-owned cross-process lock. A crash cannot leave a stale lock."""
    import fcntl

    root.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(root / ".ppt-export.lock", os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    acquired = False
    try:
        deadline = time.monotonic() + settings.ppt_render_lock_wait_seconds
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("其他课件正在导出，等待已结束；进度已保留，请稍后继续生成") from None
                time.sleep(.25)
        render_mode()
        # The first tool is the lightweight SVG compiler, not LibreOffice.
        # Apply Office's own minimum only immediately before Office starts.
        wait_for_memory_budget(128)
        yield
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _stop_unit(unit: str) -> None:
    # Only this invocation's random, application-owned unit can be stopped.
    try:
        subprocess.run([shutil.which("systemctl") or "systemctl", "--no-ask-password", "stop", unit],
                       capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        logger.error("ppt_render_unit_cleanup_failed unit=%s; independent RuntimeMaxSec remains active", unit)


def run_bounded_program(args: list[str], *, cwd: Path, env: dict[str, str], timeout: int,
                        resource_limited: bool = False, min_memory_mb: int | None = None) -> str:
    unit = None
    command = args
    wait_budget = timeout
    if resource_limited:
        budget = wait_for_memory_budget(min_memory_mb)
        if render_mode() == "systemd":
            unit = f"ai-ppt-render-{uuid4().hex}.service"
            # No provider credentials or backend EnvironmentFile are inherited.
            # --pipe exposes the fixed tool's output, never a model-written program.
            command = [shutil.which("systemd-run") or "systemd-run", "--no-ask-password",
                "--quiet", "--wait", "--pipe", "--collect", "--service-type=exec", f"--unit={unit}",
                f"--working-directory={cwd}", f"--property=MemoryMax={budget}M",
                "--property=MemorySwapMax=0", f"--property=CPUQuota={settings.ppt_render_cpu_percent}%",
                f"--property=TasksMax={settings.ppt_render_tasks_max}", f"--property=RuntimeMaxSec={timeout}s",
                "--property=TimeoutStopSec=5s", "--property=KillMode=control-group", "--property=OOMPolicy=kill",
                "--property=Nice=10", "--property=IOWeight=20", "--property=NoNewPrivileges=yes",
                "--property=PrivateTmp=yes", "--property=UMask=0077",
                *[f"--setenv={key}={value}" for key, value in sorted(env.items())], "--", *args]
            # The unit owns the actual deadline; allow bounded startup/cleanup
            # time for the client without extending the renderer's runtime.
            wait_budget += 15
        logger.info("ppt_tool_start tool=%s isolation=%s memory_limit_mb=%s timeout_seconds=%s",
                    Path(args[0]).name, "systemd" if unit else "process", budget, timeout)
    process = None
    try:
        process = subprocess.Popen(command, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=os.name == "posix")
        try:
            stdout, stderr = process.communicate(timeout=wait_budget)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("课件导出或渲染超时，已有成果未被覆盖；已保留进度，可稍后继续生成") from exc
        if process.returncode:
            detail = (stderr or stdout)[-1800:]
            if unit:
                raise RuntimeError("课件隔离任务未完成（可能达到资源或时间上限），已有成果和插图已保留：" + detail)
            raise RuntimeError("课件工具检查失败：" + detail)
        return stdout
    finally:
        # Killing systemd-run's process group alone does not kill its service.
        # Always stop the exact unit, including on cancellation/interrupt/error.
        if unit:
            _stop_unit(unit)
        if process is not None:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.poll() is None:
                process.kill()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                # Do not wait forever for an escaped child holding a pipe.
                for pipe in (process.stdout, process.stderr):
                    if pipe:
                        pipe.close()
