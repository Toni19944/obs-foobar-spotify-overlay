"""Managed child-process orchestration (data-model E3; orchestration-contract).

Owns the carried servers as tracked ``Popen`` handles for the active source.
Spawns them with NO visible console by default (FR-004), computes the launch
matrix (FR-008/009), injects Spotify creds + ports via the env block (FR-018b/
FR-032), and tears everything down cleanly with port-release verification and a
Windows Job Object so a GUI crash never orphans children (FR-007/SC-007).

Framework-agnostic: no Qt imports. Status is reported via an optional callback.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import appdata_dir
from .settings import AppSettings
from .sources import FOOBAR, SPOTIFY, get_source

# Windows process-creation flags.
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010

# ── Job Object (best-effort; via pywin32 if available) ──────────────
try:  # pragma: no cover - depends on pywin32 presence
    import win32job
    import win32api
    import win32con

    _HAVE_WIN32JOB = True
except Exception:  # pragma: no cover
    _HAVE_WIN32JOB = False


@dataclass
class ManagedService:
    kind: str               # "overlay" | "spectrum"
    source: str             # "foobar" | "spotify"
    port: int
    handle: Optional[subprocess.Popen] = None
    state: str = "starting"  # starting | running | stopped | failed
    no_window: bool = True
    log_file: Optional[object] = field(default=None, repr=False)


def _port_listening(port: int, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    """True if something accepts a TCP connection on ``host:port``."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


class Orchestrator:
    def __init__(
        self,
        settings: AppSettings,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.settings = settings
        self.on_status = on_status or (lambda _msg: None)
        self.services: List[ManagedService] = []
        self._job = None
        if _HAVE_WIN32JOB:
            self._init_job_object()

    # ── status helper ──────────────────────────────────────────────
    def _status(self, msg: str) -> None:
        try:
            self.on_status(msg)
        except Exception:
            pass

    # ── Job Object (crash safety, O4 step 3) ───────────────────────
    def _init_job_object(self) -> None:  # pragma: no cover
        try:
            self._job = win32job.CreateJobObject(None, "")
            info = win32job.QueryInformationJobObject(
                self._job, win32job.JobObjectExtendedLimitInformation
            )
            info["BasicLimitInformation"]["LimitFlags"] |= (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            win32job.SetInformationJobObject(
                self._job, win32job.JobObjectExtendedLimitInformation, info
            )
        except Exception:
            self._job = None

    def _assign_to_job(self, handle: subprocess.Popen) -> None:  # pragma: no cover
        if not self._job:
            return
        try:
            hproc = win32api.OpenProcess(
                win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE,
                False,
                handle.pid,
            )
            win32job.AssignProcessToJobObject(self._job, hproc)
            win32api.CloseHandle(hproc)
        except Exception:
            pass

    # ── spawn (O2) ─────────────────────────────────────────────────
    def _spawn(self, cmd: List[str], env: Optional[dict], kind: str) -> tuple:
        """Spawn a child per the debug/window rules. Returns (Popen, log_file)."""
        debug = self.settings.debug
        full_env = dict(os.environ)
        if env:
            full_env.update(env)

        creationflags = 0
        startupinfo = None
        stdout = stderr = None
        log_file = None

        if debug.showTerminals:
            # A real, visible console for the child.
            creationflags = CREATE_NEW_CONSOLE
        else:
            # No visible window or taskbar button (SC-002).
            creationflags = CREATE_NO_WINDOW
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        if debug.logToFile:
            log_path = appdata_dir() / f"{kind}-{int(time.time())}.log.txt"
            log_file = open(log_path, "ab")
            stdout = log_file
            stderr = log_file
            # A new console can't also redirect handles cleanly; prefer the log.
            if debug.showTerminals:
                creationflags = CREATE_NO_WINDOW
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE

        handle = subprocess.Popen(
            cmd,
            env=full_env,
            creationflags=creationflags,
            startupinfo=startupinfo,
            stdout=stdout,
            stderr=stderr,
            cwd=str(Path(cmd[-1]).parent) if cmd and Path(cmd[-1]).exists() else None,
        )
        self._assign_to_job(handle)
        return handle, log_file

    def _spectrum_cmd(self, source: str, device: str, port: int) -> List[str]:
        base = [sys.executable]
        if not getattr(sys, "frozen", False):
            base += ["-m", "launcher"]
        base += ["--run-spectrum", source, "--device", device, "--port", str(port)]
        return base

    def _overlay_cmd(self, ps1: Path) -> List[str]:
        return [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps1),
        ]

    # ── start (O1 / O4 step 1) ─────────────────────────────────────
    def start(
        self,
        source_id: str,
        requires_spectrum: bool,
        spotify_env: Optional[dict] = None,
    ) -> bool:
        """Launch exactly the services the active source needs. Returns success."""
        if self.services:
            self.stop()
        if source_id is None:
            self._status("No source selected — nothing to start.")
            return False

        src = get_source(source_id)
        ports = self.settings.ports
        ok = True

        # Overlay env (ports always; Spotify creds only for spotify).
        overlay_env = {
            "OVERLAY_PORT": str(ports.overlayHttp),
            "BEEFWEB_TARGET": f"http://localhost:{ports.beefwebTarget}",
            "OAUTH_CALLBACK_PORT": str(ports.spotifyCallback),
        }
        if source_id == SPOTIFY and spotify_env:
            overlay_env.update(spotify_env)

        # 1) overlay (always for the active source).
        overlay = ManagedService(kind="overlay", source=source_id, port=ports.overlayHttp)
        try:
            overlay.handle, overlay.log_file = self._spawn(
                self._overlay_cmd(src.overlay_server), overlay_env, "overlay"
            )
        except Exception as exc:
            overlay.state = "failed"
            self._status(f"Overlay failed to start: {exc}")
            ok = False
        self.services.append(overlay)

        # 2) spectrum (only when glow OR background-motion — FR-008a).
        if requires_spectrum:
            spectrum = ManagedService(
                kind="spectrum", source=source_id, port=ports.spectrumWs
            )
            try:
                spectrum.handle, spectrum.log_file = self._spawn(
                    self._spectrum_cmd(source_id, self.settings.audioDevice, ports.spectrumWs),
                    None,
                    "spectrum",
                )
            except Exception as exc:
                spectrum.state = "failed"
                self._status(f"Spectrum failed to start: {exc}")
                ok = False
            self.services.append(spectrum)

        # Transition starting → running once each port is listening.
        ok = self._await_running() and ok
        return ok

    def _await_running(self, timeout: float = 6.0) -> bool:
        deadline = time.time() + timeout
        pending = [s for s in self.services if s.state == "starting"]
        all_ok = True
        while pending and time.time() < deadline:
            for s in list(pending):
                if s.handle is not None and s.handle.poll() is not None:
                    s.state = "failed"
                    self._status(
                        f"{s.kind} ({s.source}) exited early "
                        f"(port {s.port} — in use or backend unreachable?)"
                    )
                    pending.remove(s)
                    all_ok = False
                elif _port_listening(s.port):
                    s.state = "running"
                    self._status(f"{s.kind} running on port {s.port}.")
                    pending.remove(s)
            if pending:
                time.sleep(0.2)
        for s in pending:
            # Never reported as listening within the window.
            s.state = "failed"
            self._status(f"{s.kind} ({s.source}) did not come up on port {s.port}.")
            all_ok = False
        return all_ok

    # ── stop / teardown (O4 step 2) ────────────────────────────────
    def stop(self) -> bool:
        for s in self.services:
            h = s.handle
            if h is None:
                continue
            try:
                if h.poll() is None:
                    h.terminate()
            except Exception:
                pass
        # Grace wait, then hard kill any survivors.
        deadline = time.time() + 4.0
        for s in self.services:
            h = s.handle
            if h is None:
                continue
            try:
                remaining = max(0.0, deadline - time.time())
                h.wait(timeout=remaining)
            except Exception:
                try:
                    h.kill()
                except Exception:
                    pass
            if s.log_file is not None:
                try:
                    s.log_file.close()
                except Exception:
                    pass
            s.state = "stopped"

        released = self._verify_ports_released()
        self.services = []
        if released:
            self._status("Stopped — all ports released, no orphans.")
        else:
            self._status("Stopped — WARNING: a port is still held.")
        return released

    def _verify_ports_released(self, timeout: float = 4.0) -> bool:
        ports = {s.port for s in self.services}
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not any(_port_listening(p) for p in ports):
                return True
            time.sleep(0.2)
        return not any(_port_listening(p) for p in ports)

    @property
    def is_running(self) -> bool:
        return any(
            s.handle is not None and s.handle.poll() is None for s in self.services
        )

    def states(self) -> Dict[str, str]:
        return {f"{s.kind}:{s.port}": s.state for s in self.services}
