"""PySide6 control panel (gui-state-contract; FR-001..022/032).

One window with two mutually-exclusive source tabs (foobar / Spotify), a
configurator host tab, and a settings tab (audio device, lifecycle, pause-hide,
debug, ports). System-tray presence with Start/Stop/Exit. Start/Stop drive the
orchestrator; long operations run off the UI thread.
"""

from __future__ import annotations

import sys
import threading
import webbrowser
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, Qt, QSharedMemory, QTimer, Signal
from PySide6.QtGui import QAction, QFontDatabase, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import asset_path
from .audio_devices import list_capture_devices
from .configurator_host import ConfiguratorHost
from .orchestrator import Orchestrator
from .settings import AppSettings
from .sources import FOOBAR, SPOTIFY, requires_spectrum
from .spotify_auth import SpotifyAuth


class _Signals(QObject):
    """Thread → UI marshalling (signals are queued across threads)."""

    status = Signal(str)
    started = Signal(bool)
    stopped = Signal(bool)
    spotify_done = Signal(bool, str)  # (ok, message)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = AppSettings.load()
        self.spotify = SpotifyAuth()
        self.sig = _Signals()
        self.orchestrator = Orchestrator(self.settings, on_status=self.sig.status.emit)
        self._tray: Optional[QSystemTrayIcon] = None
        self._busy = False
        # True while pushing settings → widgets, so widget signals don't write
        # half-initialized values back into settings (the port-corruption bug).
        self._syncing = False

        self.setWindowTitle("Foobar / Spotify Overlay")
        self.resize(680, 720)
        icon = QIcon(str(asset_path("launcher", "resources", "tray.ico")))
        if icon.isNull():
            icon = QIcon(str(asset_path("tray.ico")))
        self._icon = icon
        self.setWindowIcon(icon)

        self.configurator = ConfiguratorHost(self.settings)

        self._build_ui()
        self._build_tray()
        self._wire_signals()
        self._sync_from_settings()

        # One-time legacy plaintext import (CR4), best-effort.
        try:
            if self.spotify.import_legacy():
                self._status("Imported legacy spotify-token.txt into the encrypted store.")
        except Exception:
            pass

    # ── UI construction ────────────────────────────────────────────
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_foobar_tab(), "foobar2000")
        self.tabs.addTab(self._build_spotify_tab(), "Spotify")
        self.tabs.addTab(self.configurator, "Configurator / Preview")
        self.tabs.addTab(self._build_settings_tab(), "Settings")
        root.addWidget(self.tabs)

        # Shared Start/Stop + status surface.
        controls = QHBoxLayout()
        # Sync LED — green when the overlay servers are running (presentation-only
        # running indicator; mirrors the configurator's sync-LED token).
        self.led = QLabel("●")
        self.led.setObjectName("syncLed")
        self.led.setProperty("on", "false")
        self.led.setToolTip("Overlay servers: stopped")
        self.btn_start = QPushButton("▶ Start")
        self.btn_start.setObjectName("primary")     # armed primary action (QSS accent)
        self.btn_stop = QPushButton("■ Stop")
        self.btn_start.clicked.connect(self.on_start)
        self.btn_stop.clicked.connect(self.on_stop)
        controls.addWidget(self.led)
        controls.addWidget(self.btn_start)
        controls.addWidget(self.btn_stop)
        root.addLayout(controls)

        self.status_view = QPlainTextEdit()
        self.status_view.setReadOnly(True)
        self.status_view.setProperty("role", "readout")
        self.status_view.setMaximumBlockCount(200)
        self.status_view.setFixedHeight(150)
        root.addWidget(QLabel("Status"))
        root.addWidget(self.status_view)

        self.setCentralWidget(central)

    def _build_foobar_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.chk_foobar = QCheckBox("Enable foobar2000 as the active source")
        self.chk_foobar.toggled.connect(lambda on: self._on_source_toggled(FOOBAR, on))
        lay.addWidget(self.chk_foobar)
        lay.addWidget(
            QLabel(
                "Serves the foobar overlay at the configured overlay port and proxies\n"
                "the Beefweb API. The spectrum server starts only when glow or\n"
                "background-motion is on (set in the Configurator)."
            )
        )
        lay.addStretch(1)
        return w

    def _build_spotify_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.chk_spotify = QCheckBox("Enable Spotify as the active source")
        self.chk_spotify.toggled.connect(lambda on: self._on_source_toggled(SPOTIFY, on))
        lay.addWidget(self.chk_spotify)

        box = QGroupBox("Connect Spotify (PKCE — Client ID only, no secret)")
        form = QFormLayout(box)
        self.txt_client_id = QLineEdit()
        self.txt_client_id.setPlaceholderText("Your Spotify app Client ID")
        form.addRow("Client ID", self.txt_client_id)

        self.lbl_redirect = QLabel()
        self.lbl_redirect.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("Register this Redirect URI", self.lbl_redirect)

        self.btn_connect = QPushButton("Connect Spotify")
        self.btn_connect.clicked.connect(self.on_connect_spotify)
        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.clicked.connect(self.on_disconnect_spotify)
        row = QHBoxLayout()
        row.addWidget(self.btn_connect)
        row.addWidget(self.btn_disconnect)
        form.addRow(row)

        self.lbl_spotify_state = QLabel("Not connected.")
        form.addRow("Status", self.lbl_spotify_state)
        lay.addWidget(box)
        lay.addStretch(1)
        return w

    def _build_settings_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        # Audio device (FR-022)
        dev_box = QGroupBox("Audio capture device")
        dev_form = QFormLayout(dev_box)
        self.cmb_device = QComboBox()
        self.cmb_device.setEditable(True)
        self.btn_refresh_devices = QPushButton("Refresh")
        self.btn_refresh_devices.clicked.connect(self._reload_devices)
        drow = QHBoxLayout()
        drow.addWidget(self.cmb_device, 1)
        drow.addWidget(self.btn_refresh_devices)
        dev_form.addRow("Device", drow)
        self.cmb_device.currentTextChanged.connect(self._on_device_changed)
        lay.addWidget(dev_box)

        # Lifecycle / pause-hide / debug
        opt_box = QGroupBox("Behaviour")
        opt = QVBoxLayout(opt_box)
        self.chk_minimize_tray = QCheckBox(
            "Minimize to tray (hide the taskbar button; servers keep running)"
        )
        self.chk_minimize_tray.toggled.connect(self._on_minimize_tray)
        self.chk_close_tray = QCheckBox(
            "Close to tray (X hides to tray, servers keep running; off = full shutdown)"
        )
        self.chk_close_tray.toggled.connect(self._on_close_tray)
        self.chk_hide_paused = QCheckBox("Hide overlay card when music is paused (foobar)")
        self.chk_hide_paused.toggled.connect(self._on_hide_paused)
        self.chk_show_terminals = QCheckBox("Debug: show server terminal windows")
        self.chk_show_terminals.toggled.connect(self._on_show_terminals)
        self.chk_log_file = QCheckBox("Debug: write server output to a .txt log")
        self.chk_log_file.toggled.connect(self._on_log_file)
        for c in (
            self.chk_minimize_tray,
            self.chk_close_tray,
            self.chk_hide_paused,
            self.chk_show_terminals,
            self.chk_log_file,
        ):
            opt.addWidget(c)
        lay.addWidget(opt_box)

        # Ports (FR-032)
        port_box = QGroupBox("Network ports (defaults match today's values)")
        pform = QFormLayout(port_box)
        self.spn_overlay = self._port_spin(self.settings.ports.overlayHttp)
        self.spn_spectrum = self._port_spin(self.settings.ports.spectrumWs)
        self.spn_callback = self._port_spin(self.settings.ports.spotifyCallback)
        self.spn_beefweb = self._port_spin(self.settings.ports.beefwebTarget)
        pform.addRow("Overlay HTTP", self.spn_overlay)
        pform.addRow("Spectrum WS", self.spn_spectrum)
        pform.addRow("Spotify OAuth callback", self.spn_callback)
        pform.addRow("Beefweb target (foobar)", self.spn_beefweb)
        for s in (self.spn_overlay, self.spn_spectrum, self.spn_callback, self.spn_beefweb):
            s.valueChanged.connect(self._on_ports_changed)
        self.lbl_obs_url = QLabel()
        self.lbl_obs_url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_obs_url.setWordWrap(True)
        pform.addRow("OBS browser-source URL", self.lbl_obs_url)
        lay.addWidget(port_box)

        # Preview enable (configurator)
        self.chk_preview = QCheckBox("Enable Configurator / live preview (off = zero render cost)")
        self.chk_preview.toggled.connect(self._on_preview_toggled)
        lay.addWidget(self.chk_preview)

        lay.addStretch(1)
        return w

    @staticmethod
    def _port_spin(value: int) -> QSpinBox:
        s = QSpinBox()
        s.setRange(1, 65535)
        s.setValue(value)  # sane initial value so an early signal reads truth
        return s

    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(self._icon, self)
        self._tray.setToolTip("Foobar / Spotify Overlay")
        menu = QMenu()
        act_show = QAction("Show window", self)
        act_show.triggered.connect(self._show_window)
        act_start = QAction("Start", self)
        act_start.triggered.connect(self.on_start)
        act_stop = QAction("Stop", self)
        act_stop.triggered.connect(self.on_stop)
        act_exit = QAction("Exit", self)
        act_exit.triggered.connect(self.on_exit)
        menu.addAction(act_show)
        menu.addSeparator()
        menu.addAction(act_start)
        menu.addAction(act_stop)
        menu.addSeparator()
        menu.addAction(act_exit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(
            lambda reason: self._show_window()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick
            else None
        )
        self._tray.show()

    def _wire_signals(self) -> None:
        self.sig.status.connect(self._status)
        self.sig.started.connect(self._on_started)
        self.sig.stopped.connect(self._on_stopped)
        self.sig.spotify_done.connect(self._on_spotify_done)

    # ── settings ↔ widgets sync ────────────────────────────────────
    def _sync_from_settings(self) -> None:
        s = self.settings
        self._syncing = True
        try:
            self.chk_foobar.setChecked(s.activeSource == FOOBAR)
            self.chk_spotify.setChecked(s.activeSource == SPOTIFY)
            self.chk_minimize_tray.setChecked(s.minimizeToTray)
            self.chk_close_tray.setChecked(s.closeToTray)
            self.chk_hide_paused.setChecked(s.hideCardWhenPaused)
            self.chk_show_terminals.setChecked(s.debug.showTerminals)
            self.chk_log_file.setChecked(s.debug.logToFile)
            self.chk_preview.setChecked(s.previewEnabled)
            self.spn_overlay.setValue(s.ports.overlayHttp)
            self.spn_spectrum.setValue(s.ports.spectrumWs)
            self.spn_callback.setValue(s.ports.spotifyCallback)
            self.spn_beefweb.setValue(s.ports.beefwebTarget)
            self._reload_devices()
        finally:
            self._syncing = False
        self._refresh_obs_url()
        self._refresh_redirect_uri()
        self._refresh_spotify_state()

    def _reload_devices(self) -> None:
        current = self.settings.audioDevice
        self.cmb_device.blockSignals(True)
        self.cmb_device.clear()
        devices = list_capture_devices()
        if devices:
            self.cmb_device.addItems(devices)
        if current and self.cmb_device.findText(current) < 0:
            self.cmb_device.insertItem(0, current)
        self.cmb_device.setCurrentText(current)
        self.cmb_device.blockSignals(False)
        if not devices:
            self._status("No capture devices enumerated — using the saved/typed name.")

    def _refresh_obs_url(self) -> None:
        p = self.settings.ports
        url = f"http://localhost:{p.overlayHttp}/?spectrumPort={p.spectrumWs}"
        if self.settings.hideCardWhenPaused:
            url += "&hideWhenPaused=1"
        self.lbl_obs_url.setText(url)

    def _refresh_redirect_uri(self) -> None:
        uri = f"http://127.0.0.1:{self.settings.ports.spotifyCallback}/callback"
        self.lbl_redirect.setText(uri + "   (must match your Spotify app)")

    def _refresh_spotify_state(self) -> None:
        if self.spotify.is_connected():
            store = self.spotify.load() or {}
            cid = store.get("clientId", "")
            self.lbl_spotify_state.setText(f"Connected (client {cid[:6]}…)." if cid else "Connected.")
            self.txt_client_id.setText(cid)
        else:
            self.lbl_spotify_state.setText("Not connected.")

    # ── source mutual exclusivity (FR-002 / G2) ────────────────────
    def _on_source_toggled(self, source_id: str, on: bool) -> None:
        if self._syncing:
            return
        if on:
            other = SPOTIFY if source_id == FOOBAR else FOOBAR
            other_chk = self.chk_spotify if source_id == FOOBAR else self.chk_foobar
            if other_chk.isChecked():
                other_chk.blockSignals(True)
                other_chk.setChecked(False)
                other_chk.blockSignals(False)
                if self.orchestrator.is_running:
                    self.on_stop()
            self.settings.activeSource = source_id
        else:
            if self.settings.activeSource == source_id:
                self.settings.activeSource = None
                if self.orchestrator.is_running:
                    self.on_stop()
        self.settings.save()

    # ── start / stop (O1 / O4) ─────────────────────────────────────
    def _compute_requires_spectrum(self) -> bool:
        f = self.settings.profileFlags
        return requires_spectrum(f.glow, f.backgroundMotion)

    def on_start(self) -> None:
        if self._busy:
            return
        source = self.settings.activeSource
        if not source:
            self._status("Select a source (foobar or Spotify) first.")
            return
        spotify_env = None
        if source == SPOTIFY:
            spotify_env = self.spotify.env_block()
            if not spotify_env:
                self._status("Connect Spotify before starting the Spotify source.")
                return
        # Pull fresh flags from the configurator if it's open (bridge).
        self.configurator.refresh_flags()
        requires = self._compute_requires_spectrum()
        self._set_busy(True)
        self._status(f"Starting {source} (spectrum: {'yes' if requires else 'no'})…")

        def work():
            ok = self.orchestrator.start(source, requires, spotify_env)
            self.sig.started.emit(ok)

        threading.Thread(target=work, daemon=True).start()

    def _on_started(self, ok: bool) -> None:
        self._set_busy(False)
        self._set_led(self.orchestrator.is_running)
        self._status("Running." if ok else "Start finished with errors — see above.")

    def on_stop(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._status("Stopping…")

        def work():
            ok = self.orchestrator.stop()
            self.sig.stopped.emit(ok)

        threading.Thread(target=work, daemon=True).start()

    def _on_stopped(self, ok: bool) -> None:
        self._set_busy(False)
        self._set_led(self.orchestrator.is_running)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.btn_start.setEnabled(not busy)
        self.btn_stop.setEnabled(not busy)

    # ── Spotify connect (US3) ──────────────────────────────────────
    def on_connect_spotify(self) -> None:
        client_id = self.txt_client_id.text().strip()
        if not client_id:
            self._status("Enter your Spotify Client ID first.")
            return
        port = self.settings.ports.spotifyCallback
        self._status("Opening browser for Spotify authorization…")
        self.btn_connect.setEnabled(False)

        def work():
            try:
                self.spotify.connect(client_id, callback_port=port, open_browser=webbrowser.open)
                self.sig.spotify_done.emit(True, "Connected to Spotify.")
            except Exception as exc:
                self.sig.spotify_done.emit(False, f"Spotify connect failed: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def _on_spotify_done(self, ok: bool, msg: str) -> None:
        self.btn_connect.setEnabled(True)
        self._status(msg)
        self._refresh_spotify_state()

    def on_disconnect_spotify(self) -> None:
        self.spotify.delete()
        self._status("Disconnected Spotify; encrypted store deleted.")
        self._refresh_spotify_state()

    # ── settings handlers ──────────────────────────────────────────
    def _on_device_changed(self, name: str) -> None:
        if self._syncing:
            return
        self.settings.audioDevice = name
        self.settings.save()

    def _on_minimize_tray(self, on: bool) -> None:
        if self._syncing:
            return
        self.settings.minimizeToTray = on
        self.settings.save()

    def _on_close_tray(self, on: bool) -> None:
        if self._syncing:
            return
        self.settings.closeToTray = on
        self.settings.save()

    def _on_hide_paused(self, on: bool) -> None:
        if self._syncing:
            return
        self.settings.hideCardWhenPaused = on
        self.settings.save()
        self._refresh_obs_url()
        self._status(
            "Pause-hide ON — point OBS at the updated URL below."
            if on
            else "Pause-hide OFF — overlay behaves exactly as before."
        )

    def _on_show_terminals(self, on: bool) -> None:
        if self._syncing:
            return
        self.settings.debug.showTerminals = on
        self.settings.save()

    def _on_log_file(self, on: bool) -> None:
        if self._syncing:
            return
        self.settings.debug.logToFile = on
        self.settings.save()

    def _on_ports_changed(self, *_a) -> None:
        if self._syncing:
            return
        p = self.settings.ports
        p.overlayHttp = self.spn_overlay.value()
        p.spectrumWs = self.spn_spectrum.value()
        p.spotifyCallback = self.spn_callback.value()
        p.beefwebTarget = self.spn_beefweb.value()
        self.settings.save()
        self._refresh_obs_url()
        self._refresh_redirect_uri()

    def _on_preview_toggled(self, on: bool) -> None:
        if self._syncing:
            return
        self.configurator.set_preview_enabled(on)
        if on:
            self.tabs.setCurrentWidget(self.configurator)

    # ── tray / lifecycle (G3 / FR-019) ─────────────────────────────
    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _status(self, msg: str) -> None:
        self.status_view.appendPlainText(msg)

    def _set_led(self, on: bool) -> None:
        # Toggle the sync-LED color via a dynamic property + style repolish.
        self.led.setProperty("on", "true" if on else "false")
        self.led.setToolTip("Overlay servers: running" if on else "Overlay servers: stopped")
        self.led.style().unpolish(self.led)
        self.led.style().polish(self.led)

    def changeEvent(self, event) -> None:  # noqa: N802
        # Minimize-to-tray: when minimizing with the toggle on and a tray present,
        # hide the window (removing its taskbar button) on the next event-loop tick
        # so we don't fight the native minimize animation. With the toggle off or no
        # tray, the ordinary taskbar minimize proceeds. NEVER stops servers
        # (tray-lifecycle invariant — FR-005/007).
        if event.type() == QEvent.Type.WindowStateChange:
            if (
                self.windowState() & Qt.WindowState.WindowMinimized
                and self.settings.minimizeToTray
                and self._tray is not None
            ):
                QTimer.singleShot(0, self.hide)
        super().changeEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        # Close-to-tray hides the window and leaves the app + servers running;
        # otherwise (toggle off, or no tray available) perform a full clean
        # shutdown. Going to the tray NEVER stops servers (FR-006/007/008/009).
        if self.settings.closeToTray and self._tray is not None:
            event.ignore()
            self.hide()
            self._tray.showMessage(
                "Still running",
                "The overlay launcher is in the system tray. Use Exit to quit.",
                self._icon,
                3000,
            )
        else:
            self._full_shutdown()
            event.accept()

    def _full_shutdown(self) -> None:
        # The only server-stopping path besides the explicit Stop button: stop all
        # managed services (which verifies ports are released), remove the tray
        # icon, then quit the application (FR-008 / clean-shutdown contract).
        if self.orchestrator.is_running:
            self.orchestrator.stop()
        if self._tray is not None:
            self._tray.hide()
        QApplication.instance().quit()

    def on_exit(self) -> None:
        # Tray Exit = full clean shutdown regardless of the toggles.
        self._full_shutdown()


class _SingleInstance:
    """Process-wide single-instance guard (feature 010, FR-006 / SC-007).

    A ``QSharedMemory`` segment is the atomic lock; a ``QLocalServer`` named pipe is
    the "raise the existing window" channel. The first launch creates both. A second
    launch (e.g. an impatient double-click during the startup window) finds the lock
    held, asks the running instance to surface its window, and exits — so there is
    never a second control panel or a duplicate set of overlay servers / held ports.

    Both primitives are PySide6/Qt built-ins (``QtCore`` / ``QtNetwork``) — no new
    dependency (Principle V) — and are ephemeral (nothing on disk). The
    ``--run-spectrum`` self-reinvocation never reaches ``app.main()``, so owned
    spectrum children bypass the guard entirely (research D5).
    """

    KEY = "FoobarOverlay/single-instance"
    PIPE = "FoobarOverlay/raise"
    _MSG = b"show"

    def __init__(self) -> None:
        self._shmem = QSharedMemory(self.KEY)
        self._server: Optional[QLocalServer] = None
        self._window: Optional["MainWindow"] = None

    def try_become_primary(self) -> bool:
        """Return True if this process is the primary instance; False if it handed
        a *show-window* request to an already-running instance (and should exit)."""
        if self._shmem.create(1):
            self._start_server()
            return True
        if self._shmem.error() == QSharedMemory.SharedMemoryError.AlreadyExists:
            if self._notify_existing():
                return False  # a live instance answered → we are the second launch
            # No live server answered → the segment is stale (prior crash). Reclaim
            # it and proceed as the primary rather than wedging the app permanently.
            self._shmem.attach()
            self._shmem.detach()
            if self._shmem.create(1):
                self._start_server()
                return True
        # Any other outcome: fail open (run as primary) rather than block startup.
        self._start_server()
        return True

    def bind(self, window: "MainWindow") -> None:
        """Route incoming 'show' requests from later launches to this window."""
        self._window = window

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        if self._shmem.isAttached():
            self._shmem.detach()

    # ── internals ──────────────────────────────────────────────────
    def _start_server(self) -> None:
        QLocalServer.removeServer(self.PIPE)  # clear any stale pipe from a crash
        self._server = QLocalServer()
        self._server.newConnection.connect(self._on_new_connection)
        self._server.listen(self.PIPE)

    def _on_new_connection(self) -> None:
        sock = self._server.nextPendingConnection() if self._server else None
        if sock is None:
            return
        # Any connection means "surface the window"; draining the payload is courtesy.
        sock.waitForReadyRead(100)
        sock.readAll()
        if self._window is not None:
            self._window._show_window()
        sock.disconnectFromServer()

    def _notify_existing(self) -> bool:
        """Connect to the running instance and ask it to show. True if it answered."""
        sock = QLocalSocket()
        sock.connectToServer(self.PIPE)
        if not sock.waitForConnected(300):
            return False
        sock.write(self._MSG)
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True


def _apply_theme(app: QApplication) -> None:
    """Load the bundled display/body fonts and apply the Meter-Bridge stylesheet.

    Fonts load from the carried TTFs when present; on absence Qt falls back to the
    nearest installed family, so the build never hard-depends on the fonts (FR-013).
    Styling is presentation-only — no control wording or layout changes (FR-015).
    """
    fonts_dir = asset_path("launcher", "resources", "fonts")
    for ttf in ("Oswald.ttf", "DMSans.ttf"):
        p = fonts_dir / ttf
        if p.exists():
            QFontDatabase.addApplicationFont(str(p))
    try:
        qss = asset_path("launcher", "resources", "style.qss").read_text(encoding="utf-8")
        app.setStyleSheet(qss)
    except OSError:
        pass  # missing stylesheet → default Qt look, app still fully functional


def main() -> int:
    # QtWebEngine requires this attribute set before the QApplication exists.
    QApplication.setApplicationName("FoobarOverlay")
    app = QApplication.instance() or QApplication(sys.argv)
    _apply_theme(app)

    # Single-instance guard (feature 010, FR-006 / SC-007): acquire the process-wide
    # lock before building the window. If another instance already holds it, forward
    # a "show" request to it and exit 0 — no second window, no duplicate servers.
    guard = _SingleInstance()
    if not guard.try_become_primary():
        guard.release()
        return 0

    win = MainWindow()
    guard.bind(win)
    win.show()
    # Dismiss the PyInstaller startup splash the moment the window is interactive
    # (feature 010, FR-005). pyi_splash exists only inside the frozen app; the
    # guarded import makes unfrozen dev runs a no-op.
    try:
        import pyi_splash  # type: ignore

        pyi_splash.close()
    except ImportError:
        pass
    try:
        return app.exec()
    finally:
        guard.release()


if __name__ == "__main__":
    raise SystemExit(main())
