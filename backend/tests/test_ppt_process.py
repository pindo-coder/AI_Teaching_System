from pathlib import Path
import os
import subprocess
import sys

import pytest

from app.core.config import settings
from app.services import ppt_process_service as runner


def test_explicit_isolation_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, 'ppt_render_isolation', 'systemd')
    monkeypatch.setattr(runner, 'systemd_available', lambda: False)
    with pytest.raises(RuntimeError, match='资源隔离不可用'):
        runner.render_mode()
    monkeypatch.setattr(settings, 'ppt_render_isolation', 'auto')
    assert runner.render_mode() == 'process'
    monkeypatch.setattr(runner, 'systemd_available', lambda: True)
    assert runner.render_mode() == 'systemd'


def test_adaptive_memory_budget_reserves_web_headroom(monkeypatch):
    monkeypatch.setattr(settings, 'ppt_render_memory_limit_mb', 512)
    monkeypatch.setattr(settings, 'ppt_render_min_memory_mb', 256)
    monkeypatch.setattr(settings, 'ppt_render_reserve_mb', 256)
    monkeypatch.setattr(runner, 'available_memory_mb', lambda: 620)
    assert runner.memory_budget_mb() == 364
    monkeypatch.setattr(runner, 'available_memory_mb', lambda: 1200)
    assert runner.memory_budget_mb() == 512
    monkeypatch.setattr(runner, 'available_memory_mb', lambda: 500)
    with pytest.raises(RuntimeError, match='可用内存不足'):
        runner.memory_budget_mb()
    monkeypatch.setattr(runner, 'available_memory_mb', lambda: None)
    assert runner.memory_budget_mb() == 512
    monkeypatch.setattr(settings, 'ppt_render_min_memory_mb', 600)
    with pytest.raises(RuntimeError, match='不能超过'):
        runner.memory_budget_mb()


def test_lightweight_tools_keep_reserve_without_requiring_office_minimum(monkeypatch):
    monkeypatch.setattr(runner, 'available_memory_mb', lambda: 450)
    monkeypatch.setattr(settings, 'ppt_render_min_memory_mb', 256)
    monkeypatch.setattr(settings, 'ppt_render_reserve_mb', 256)
    assert runner.memory_budget_mb(128) == 194
    with pytest.raises(runner.RenderCapacityUnavailable):
        runner.memory_budget_mb()


def test_transient_capacity_pressure_waits_then_recovers(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(settings, 'ppt_render_min_memory_mb', 256)
    monkeypatch.setattr(settings, 'ppt_render_reserve_mb', 256)
    clock = [0.0]
    available = iter([480, 480, 620])
    monkeypatch.setattr(runner, 'available_memory_mb', lambda: next(available))
    monkeypatch.setattr(runner, 'time', SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda seconds: clock.__setitem__(0, clock[0]+seconds)))
    assert runner.wait_for_memory_budget() == 364
    assert clock[0] == 1
    monkeypatch.setattr(settings, 'ppt_render_memory_wait_seconds', 0)
    monkeypatch.setattr(runner, 'available_memory_mb', lambda: 480)
    with pytest.raises(runner.RenderCapacityUnavailable):
        runner.wait_for_memory_budget()


def test_linux_capacity_respects_cgroup_ancestor_limits(monkeypatch):
    real_read = Path.read_text
    files = {
        '/proc/meminfo': 'MemAvailable: 2048000 kB\n',
        '/proc/self/cgroup': '0::/system.slice/test.service\n',
        '/sys/fs/cgroup/system.slice/test.service/memory.max': 'max',
        '/sys/fs/cgroup/system.slice/test.service/memory.current': '1000',
        '/sys/fs/cgroup/system.slice/memory.max': str(1024 * 1048576),
        '/sys/fs/cgroup/system.slice/memory.current': str(600 * 1048576),
    }
    monkeypatch.setattr(runner.sys, 'platform', 'linux')
    monkeypatch.setattr(Path, 'is_file', lambda self: str(self) in files)
    monkeypatch.setattr(Path, 'read_text', lambda self, *a, **kw: files[str(self)] if str(self) in files else real_read(self, *a, **kw))
    assert runner.available_memory_mb() == 424


def test_linux_capacity_cannot_silently_ignore_unreadable_meminfo(monkeypatch):
    monkeypatch.setattr(runner.sys, 'platform', 'linux')
    def denied(*args, **kwargs):
        raise PermissionError('not available')
    monkeypatch.setattr(Path, 'read_text', denied)
    with pytest.raises(RuntimeError, match='无法读取'):
        runner.available_memory_mb()


def test_lock_contention_does_not_overwrite_and_releases_after_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'ppt_render_lock_wait_seconds', 0)
    monkeypatch.setattr(runner, 'render_mode', lambda: 'process')
    monkeypatch.setattr(runner, 'memory_budget_mb', lambda *args: 512)
    with pytest.raises(ValueError, match='failed export'):
        with runner.export_slot(tmp_path):
            with pytest.raises(RuntimeError, match='其他课件正在导出'):
                with runner.export_slot(tmp_path):
                    pytest.fail('must not acquire a held lock')
            raise ValueError('failed export')
    with runner.export_slot(tmp_path):
        pass


def test_kernel_lock_also_excludes_another_process(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'render_mode', lambda: 'process')
    monkeypatch.setattr(runner, 'memory_budget_mb', lambda *args: 512)
    code = ('import fcntl,sys; f=open(sys.argv[1], "r+"); '
            'fcntl.flock(f, fcntl.LOCK_EX|fcntl.LOCK_NB)')
    with runner.export_slot(tmp_path):
        result = subprocess.run([sys.executable, '-c', code, str(tmp_path / '.ppt-export.lock')],
                                capture_output=True, timeout=5)
        assert result.returncode != 0
        assert b'BlockingIOError' in result.stderr
    assert subprocess.run([sys.executable, '-c', code, str(tmp_path / '.ppt-export.lock')], timeout=5).returncode == 0


@pytest.mark.skipif(not hasattr(os, 'O_NOFOLLOW'), reason='requires POSIX no-follow')
def test_lock_cannot_follow_symlink(tmp_path):
    target = tmp_path / 'private'
    target.write_text('preserve')
    (tmp_path / '.ppt-export.lock').symlink_to(target)
    with pytest.raises(OSError):
        with runner.export_slot(tmp_path):
            pytest.fail('symlink lock accepted')
    assert target.read_text() == 'preserve'


def test_process_runner_preserves_argument_boundaries(tmp_path):
    result = runner.run_bounded_program(
        [sys.executable, '-c', 'import sys; print(sys.argv[1])', 'a; $(echo not-a-shell)'],
        cwd=tmp_path, env={'PATH': os.environ.get('PATH', '')}, timeout=5)
    assert result.strip() == 'a; $(echo not-a-shell)'


def test_process_runner_timeout_is_bounded_and_reaped(tmp_path):
    with pytest.raises(RuntimeError, match='渲染超时'):
        runner.run_bounded_program([sys.executable, '-c', 'import time; time.sleep(20)'],
            cwd=tmp_path, env={}, timeout=.1)


@pytest.mark.parametrize('outcome', ['success', 'failure', 'timeout', 'interrupt', 'spawn_error'])
def test_systemd_limits_deadline_and_cleanup_are_independent(tmp_path, monkeypatch, outcome):
    monkeypatch.setattr(runner, 'render_mode', lambda: 'systemd')
    monkeypatch.setattr(runner, 'memory_budget_mb', lambda: 350)
    calls, stopped = [], []
    monkeypatch.setattr(runner, '_stop_unit', stopped.append)
    monkeypatch.setattr(runner.os, 'killpg', lambda *args: None)
    monkeypatch.setattr(runner.shutil, 'which', lambda name: '/usr/bin/' + name)
    class Process:
        pid = 12345
        returncode = 0 if outcome == 'success' else 9
        count = 0
        def communicate(self, timeout):
            self.count += 1
            if self.count == 1:
                assert timeout == 315
                if outcome == 'timeout':
                    raise subprocess.TimeoutExpired('systemd-run', timeout)
                if outcome == 'interrupt':
                    raise KeyboardInterrupt()
            return ('tool output', 'memory limit')
    def start(args, **kwargs):
        calls.append((args, kwargs))
        if outcome == 'spawn_error':
            raise OSError('cannot spawn')
        return Process()
    monkeypatch.setattr(runner.subprocess, 'Popen', start)
    expected = {'failure': RuntimeError, 'timeout': RuntimeError, 'interrupt': KeyboardInterrupt, 'spawn_error': OSError}
    def execute():
        return runner.run_bounded_program(['/trusted/soffice', '--convert-to', 'pdf', '课件.pptx'],
            cwd=tmp_path, env={'PATH': '/trusted/bin', 'FONTCONFIG_FILE': '/private/fonts.conf'},
            timeout=300, resource_limited=True)
    if outcome == 'success':
        assert execute() == 'tool output'
    else:
        with pytest.raises(expected[outcome]):
            execute()
    args, kwargs = calls[0]
    assert '--property=MemoryMax=350M' in args
    assert '--property=MemorySwapMax=0' in args
    assert '--property=CPUQuota=100%' in args
    assert '--property=RuntimeMaxSec=300s' in args
    assert '--property=KillMode=control-group' in args
    assert '--setenv=FONTCONFIG_FILE=/private/fonts.conf' in args
    assert args[-4:] == ['/trusted/soffice', '--convert-to', 'pdf', '课件.pptx']
    unit = next(arg.split('=', 1)[1] for arg in args if arg.startswith('--unit='))
    assert stopped == [unit]
    assert kwargs['start_new_session'] is True


def test_native_runner_does_not_pass_secrets_to_render_unit(tmp_path, monkeypatch):
    from app.services import ppt_native_service as native
    monkeypatch.setenv('LLM_API_KEY', 'do-not-inherit')
    monkeypatch.setenv('DATABASE_URL', 'do-not-inherit')
    monkeypatch.setenv('PATH', '/trusted/bin')
    captured = {}
    def capture(args, **kwargs):
        captured.update(kwargs)
        return 'ok'
    monkeypatch.setattr(native, 'run_bounded_program', capture)
    assert native.run_program(['tool'], cwd=tmp_path, timeout=300, resource_limited=True) == 'ok'
    assert captured['env']['PATH'] == '/trusted/bin'
    assert 'LLM_API_KEY' not in captured['env']
    assert 'DATABASE_URL' not in captured['env']
    assert captured['env']['OPENBLAS_NUM_THREADS'] == '1'
    assert captured['resource_limited'] is True


def test_low_memory_does_not_start_tools_or_replace_previous_artifact(tmp_path, monkeypatch):
    from app.services.ppt_native_service import PptNativeService
    old = tmp_path / 'previous.pptx'
    old.write_bytes(b'preserve previous verified artifact')
    monkeypatch.setattr(settings, 'generated_artifact_directory', str(tmp_path))
    monkeypatch.setattr(settings, 'ppt_render_memory_wait_seconds', 0)
    monkeypatch.setattr(runner, 'available_memory_mb', lambda: 100)
    monkeypatch.setattr(runner, 'render_mode', lambda: 'process')
    monkeypatch.setattr(runner.subprocess, 'Popen', lambda *a, **kw: pytest.fail('low memory must not start a tool'))
    with pytest.raises(RuntimeError, match='可用内存不足'):
        PptNativeService(42).export({}, [])
    assert old.read_bytes() == b'preserve previous verified artifact'


def test_small_server_admission_matches_each_stage_instead_of_office_at_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'ppt_render_memory_limit_mb', 512)
    monkeypatch.setattr(settings, 'ppt_render_min_memory_mb', 192)
    monkeypatch.setattr(settings, 'ppt_render_reserve_mb', 128)
    monkeypatch.setattr(settings, 'ppt_render_memory_wait_seconds', 0)
    monkeypatch.setattr(runner, 'render_mode', lambda: 'process')
    # Reproduce the production failure: 496 MiB could not meet the old 512
    # admission threshold even though a protected renderer fits comfortably.
    monkeypatch.setattr(runner, 'available_memory_mb', lambda: 496)
    with runner.export_slot(tmp_path):
        assert runner.memory_budget_mb() == 368
    # 300 MiB can run the compiler but must not start Office yet.
    monkeypatch.setattr(runner, 'available_memory_mb', lambda: 300)
    with runner.export_slot(tmp_path):
        assert runner.memory_budget_mb(128) == 172
        with pytest.raises(runner.RenderCapacityUnavailable, match='当前 300 MiB'):
            runner.wait_for_memory_budget()
    monkeypatch.setattr(runner, 'available_memory_mb', lambda: 200)
    with pytest.raises(runner.RenderCapacityUnavailable):
        with runner.export_slot(tmp_path):
            pytest.fail('must retain the minimum safe compiler budget')


def test_native_export_really_renders_with_separate_budget_and_guarded_tools(tmp_path, monkeypatch):
    from app.services import ppt_native_service as native
    from app.schemas.presentation import PptPage
    from app.services.ppt_workflow_service import PptWorkflowService
    monkeypatch.setattr(settings, 'generated_artifact_directory', str(tmp_path))
    monkeypatch.setattr(settings, 'ppt_render_timeout_seconds', 300)
    design = {'background': 'FFFFFF', 'text': '162033', 'accent': 'B32135'}
    slides = []
    for index in range(2):
        page = PptPage(layout='title' if index == 0 else 'summary', title='渲染隔离检查',
            takeaway='核验中文正文与成品预览', bullets=['保留原有课件与字体'], speaker_notes='运行检查。', evidence_refs=[])
        slides.append({**page.model_dump(), 'svg': PptWorkflowService._fixture_svg(page, design)})
    real = native.run_program
    calls = []
    def recorded(args, **kwargs):
        calls.append((args, kwargs))
        return real(args, **kwargs)
    monkeypatch.setattr(native, 'run_program', recorded)
    artifact, data = native.PptNativeService(42).export({'title': '渲染隔离检查', 'design': design, 'slides': slides}, [])
    assert data['quality_report']['passed']
    assert artifact['slide_count'] == 2
    office = next((args, kw) for args, kw in calls if '--convert-to' in args)
    assert office[1]['timeout'] == 300
    assert office[1]['resource_limited'] is True
    compiler = next(kw for args, kw in calls if any(arg.endswith('/svg_to_pptx.py') for arg in args))
    assert compiler['resource_limited'] is True
    assert compiler['min_memory_mb'] == 128
    raster = next(kw for args, kw in calls if Path(args[0]).name == 'pdftoppm')
    assert raster['resource_limited'] is True
    assert raster['min_memory_mb'] == 128


def test_cleanup_stops_only_named_unit_and_has_its_own_timeout(monkeypatch):
    captured = []
    monkeypatch.setattr(runner.shutil, 'which', lambda name: '/usr/bin/' + name)
    monkeypatch.setattr(runner.subprocess, 'run', lambda args, **kwargs: captured.append((args, kwargs)))
    runner._stop_unit('ai-ppt-render-unique.service')
    args, kwargs = captured[0]
    assert args == ['/usr/bin/systemctl', '--no-ask-password', 'stop', 'ai-ppt-render-unique.service']
    assert kwargs['timeout'] == 10
