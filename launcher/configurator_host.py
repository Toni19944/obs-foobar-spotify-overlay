"""Configurator host (gui-state-contract G4–G7; FR-010..015).

Hosts the carried ``configurator.html`` UNCHANGED in a QtWebEngine view with a
persistent, on-disk profile so its ``localStorage`` named profiles survive
restarts (G7). The live preview is the heavyweight QtWebEngine renderer: gating it
on ``previewEnabled`` and TEARING DOWN the view (not hiding) stops both its JS
render loop and its spectrum WebSocket — zero duplicate cost while OBS is live
(FR-012/SC-005). The configurator (sliders + preview) can pop out into its own
window with a "return to main window" control (FR-013/014). The launcher reads the
active profile's ``glow``/``backgroundMotion`` from the view to gate the spectrum
server (FR-008a launch-matrix bridge).
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QUrl, Qt
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

from . import appdata_dir, asset_path
from .settings import AppSettings


# JS that reads the configurator's current glow/bg-motion flags.
_READ_FLAGS_JS = (
    "(function(){try{return JSON.stringify("
    "{glow: !!state.visEnabled, backgroundMotion: !!state.bgMotion});}"
    "catch(e){return null;}})();"
)


def _apply_profile_js(name: str) -> str:
    # Drive the configurator's OWN apply logic (no HTML edit), then return flags.
    safe = name.replace("\\", "\\\\").replace("'", "\\'")
    return (
        "(function(){try{"
        "var p=JSON.parse(localStorage.getItem('nowplaying_profiles')||'{}');"
        f"if(p['{safe}']){{Object.assign(state,p['{safe}']);"
        "syncAllInputs();applyToMock();renderProfileList('" + safe + "');}"
        "return JSON.stringify({glow:!!state.visEnabled,backgroundMotion:!!state.bgMotion});"
        "}catch(e){return null;}})();"
    )


class ConfiguratorHost(QWidget):
    def __init__(
        self,
        settings: AppSettings,
        on_flags_changed: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.on_flags_changed = on_flags_changed or (lambda: None)
        self._view: Optional[QWebEngineView] = None
        self._popout: Optional[QWidget] = None

        # Persistent, on-disk profile under %APPDATA%\FoobarOverlay\QtWebEngine
        # (named profile ⇒ non-off-the-record ⇒ localStorage persists). (G7/T028)
        storage = str(appdata_dir() / "QtWebEngine")
        self._profile = QWebEngineProfile("FoobarOverlay", self)
        self._profile.setPersistentStoragePath(storage)
        self._profile.setCachePath(storage)
        self._profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )

        self._layout = QVBoxLayout(self)

        # Toolbar: pop the configurator out into its own window (FR-013/014/G6).
        self._btn_popout = QPushButton("⇱ Pop out into its own window")
        self._btn_popout.clicked.connect(self.pop_out)
        self._btn_popout.setVisible(False)  # only useful once the view exists
        self._layout.addWidget(self._btn_popout)

        self._placeholder = QLabel(
            "Live preview disabled.\n\n"
            "Enable “Configurator / live preview” to open the configurator.\n"
            "(Kept off by default so it adds zero render cost while streaming.)"
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._layout.addWidget(self._placeholder)

        if settings.previewEnabled:
            self.set_preview_enabled(True)

    # ── preview gating (FR-012 / G5) ───────────────────────────────
    def set_preview_enabled(self, enabled: bool) -> None:
        self.settings.previewEnabled = enabled
        self.settings.save()
        if enabled and self._view is None:
            self._create_view()
        elif not enabled and self._view is not None:
            self._destroy_view()

    def _create_view(self) -> None:
        self._placeholder.hide()
        page = QWebEnginePage(self._profile, self)
        self._view = QWebEngineView(self)
        self._view.setPage(page)
        self._view.load(QUrl.fromLocalFile(str(asset_path("configurator.html"))))
        self._layout.addWidget(self._view)
        self._btn_popout.setVisible(True)
        # Pull current flags once the page is ready.
        self._view.loadFinished.connect(lambda ok: self.refresh_flags() if ok else None)

    def _destroy_view(self) -> None:
        if self._popout is not None:
            self.return_to_main()
        view = self._view
        self._view = None
        if view is not None:
            # Read flags before teardown, then stop render loop + WS by navigating
            # to about:blank and deleting the view (true teardown, not hide).
            self.refresh_flags(view=view)
            view.stop()
            view.setUrl(QUrl("about:blank"))
            view.setParent(None)
            view.deleteLater()
        self._btn_popout.setVisible(False)
        self._placeholder.show()

    # ── pop-out sliders window (FR-013/014 / G6) ───────────────────
    def pop_out(self) -> None:
        if self._view is None or self._popout is not None:
            return
        win = QWidget()
        win.setWindowTitle("Overlay Configurator — sliders")
        win.resize(520, 800)
        lay = QVBoxLayout(win)
        btn = QPushButton("⤺ Return to main window")
        btn.clicked.connect(self.return_to_main)
        lay.addWidget(btn)
        self._view.setParent(None)
        lay.addWidget(self._view)
        self._popout = win
        self._btn_popout.setVisible(False)
        win.show()
        win.raise_()

    def return_to_main(self) -> None:
        if self._popout is None or self._view is None:
            return
        self._view.setParent(None)
        self._layout.addWidget(self._view)
        self._popout.close()
        self._popout.deleteLater()
        self._popout = None
        self._btn_popout.setVisible(self._view is not None)
        w = self.window()
        w.showNormal()
        w.raise_()
        w.activateWindow()

    # ── profiles + launch-matrix bridge (FR-015 / FR-008a / G7) ────
    def apply_profile(self, name: str) -> None:
        self.settings.activeProfile = name
        self.settings.save()
        if self._view is not None:
            self._view.page().runJavaScript(_apply_profile_js(name), self._store_flags)

    def refresh_flags(self, view: Optional[QWebEngineView] = None) -> None:
        v = view or self._view
        if v is not None:
            v.page().runJavaScript(_READ_FLAGS_JS, self._store_flags)

    def _store_flags(self, result) -> None:
        if not result:
            return
        try:
            import json

            data = json.loads(result)
        except Exception:
            return
        self.settings.profileFlags.glow = bool(data.get("glow", True))
        self.settings.profileFlags.backgroundMotion = bool(
            data.get("backgroundMotion", False)
        )
        self.settings.save()
        self.on_flags_changed()
