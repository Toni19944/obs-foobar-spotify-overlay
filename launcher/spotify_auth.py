"""Spotify credentials: PKCE first-run + DPAPI store (credential-store-contract).

Hard guarantees (CR5): no client secret exists anywhere (PKCE); the refresh token
at rest is DPAPI-encrypted under ``%APPDATA%``; the access token is memory-only;
decrypted values reach the server ONLY via the env block (handled by the
orchestrator). Stdlib-only HTTP (no ``requests`` dependency added to the server).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable, Optional

from . import appdata_dir, asset_path

STORE_FILE = "spotify.dat"
SCOPES = "user-read-currently-playing user-read-playback-state"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

# ── DPAPI (CurrentUser) via pywin32 ─────────────────────────────────
try:  # pragma: no cover - depends on pywin32 presence
    import win32crypt

    _HAVE_DPAPI = True
except Exception:  # pragma: no cover
    _HAVE_DPAPI = False


def _protect(data: bytes) -> bytes:
    if not _HAVE_DPAPI:
        raise RuntimeError("DPAPI (pywin32 win32crypt) is required to store credentials.")
    # CryptProtectData CurrentUser scope (no entropy, no description).
    return win32crypt.CryptProtectData(data, None, None, None, None, 0)


def _unprotect(blob: bytes) -> bytes:
    if not _HAVE_DPAPI:
        raise RuntimeError("DPAPI (pywin32 win32crypt) is required to read credentials.")
    _desc, out = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
    return out


class _CallbackHandler(BaseHTTPRequestHandler):
    code_holder: dict = {}

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        qs = urllib.parse.parse_qs(parsed.query)
        type(self).code_holder["code"] = (qs.get("code") or [None])[0]
        type(self).code_holder["error"] = (qs.get("error") or [None])[0]
        body = (
            b"<!DOCTYPE html><html><head><meta charset='utf-8'><style>"
            b"body{font-family:sans-serif;display:flex;align-items:center;"
            b"justify-content:center;height:100vh;margin:0;background:#111;color:#fff}"
            b".box{text-align:center}.c{font-size:48px;margin-bottom:16px}</style></head>"
            b"<body><div class='box'><div class='c'>&#10003;</div><h2>All done!</h2>"
            b"<p>You can close this tab and return to streaming.</p></div></body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):  # silence the default stderr logging
        pass


class SpotifyAuth:
    def __init__(self) -> None:
        self.access_token: Optional[str] = None  # memory-only (I5)

    # ── store (CR1) ────────────────────────────────────────────────
    @staticmethod
    def store_path() -> Path:
        return appdata_dir() / STORE_FILE

    def load(self) -> Optional[dict]:
        p = self.store_path()
        if not p.exists():
            return None
        try:
            return json.loads(_unprotect(p.read_bytes()).decode("utf-8"))
        except Exception:
            return None

    def save(self, client_id: str, refresh_token: str, scopes: str = SCOPES) -> None:
        payload = json.dumps(
            {"clientId": client_id, "refreshToken": refresh_token, "scopes": scopes}
        ).encode("utf-8")
        self.store_path().write_bytes(_protect(payload))

    def delete(self) -> None:
        p = self.store_path()
        if p.exists():
            p.unlink()
        self.access_token = None

    def is_connected(self) -> bool:
        return self.load() is not None

    # ── PKCE first-run (CR2) ───────────────────────────────────────
    @staticmethod
    def _redirect_uri(callback_port: int) -> str:
        # 127.0.0.1 is intentional and MUST NOT be normalized to localhost.
        return f"http://127.0.0.1:{callback_port}/callback"

    def connect(
        self,
        client_id: str,
        callback_port: int = 8082,
        open_browser: Callable[[str], None] = webbrowser.open,
    ) -> dict:
        """Run the full PKCE browser flow (blocking — run off the UI thread).

        Returns the decrypted store dict on success; raises on cancel/error with
        no partial/plaintext residue (CR4).
        """
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        redirect_uri = self._redirect_uri(callback_port)

        params = urllib.parse.urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
                "scope": SCOPES,
            }
        )

        _CallbackHandler.code_holder = {}
        server = HTTPServer(("127.0.0.1", callback_port), _CallbackHandler)
        server.timeout = 1.0

        done = threading.Event()

        def serve():
            while not done.is_set():
                server.handle_request()
                if _CallbackHandler.code_holder.get("code") or _CallbackHandler.code_holder.get(
                    "error"
                ):
                    break

        t = threading.Thread(target=serve, daemon=True)
        t.start()

        open_browser(f"{AUTH_URL}?{params}")

        # Wait for the callback (up to ~3 minutes), then close the listener.
        t.join(timeout=180)
        done.set()
        try:
            server.server_close()
        except Exception:
            pass

        code = _CallbackHandler.code_holder.get("code")
        err = _CallbackHandler.code_holder.get("error")
        if err or not code:
            raise RuntimeError(f"Spotify authorization was cancelled or failed ({err or 'no code'}).")

        token = self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": verifier,
            }
        )
        self.access_token = token.get("access_token")
        refresh = token.get("refresh_token")
        if not refresh:
            raise RuntimeError("Spotify did not return a refresh token.")
        self.save(client_id, refresh, token.get("scope", SCOPES))
        return self.load() or {}

    # ── refresh + rotation (CR3) ───────────────────────────────────
    def refresh_access_token(self) -> Optional[str]:
        store = self.load()
        if not store:
            return None
        token = self._token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": store["refreshToken"],
                "client_id": store["clientId"],
            }
        )
        self.access_token = token.get("access_token")
        # Persist a rotated refresh token back to the encrypted store (I6).
        new_refresh = token.get("refresh_token")
        if new_refresh and new_refresh != store["refreshToken"]:
            self.save(store["clientId"], new_refresh, store.get("scopes", SCOPES))
        return self.access_token

    @staticmethod
    def _token_request(form: dict) -> dict:
        data = urllib.parse.urlencode(form).encode("utf-8")
        req = urllib.request.Request(
            TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # ── legacy import + teardown (CR4) ─────────────────────────────
    def import_legacy(self, client_id: Optional[str] = None) -> bool:
        """Import a pre-existing plaintext ``spotify-token.txt`` once, then delete it.

        Needs a client_id (PKCE refresh requires one); uses the one already in the
        store if present, else the supplied value. Returns True if an import ran.
        """
        legacy = asset_path("Now-Playing-Spotify", "spotify-token.txt")
        if not legacy.exists():
            return False
        try:
            refresh = legacy.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        if refresh:
            existing = self.load() or {}
            cid = client_id or existing.get("clientId") or ""
            self.save(cid, refresh, existing.get("scopes", SCOPES))
        # Delete the plaintext file regardless — no plaintext credential remains.
        try:
            legacy.unlink()
        except OSError:
            pass
        return True

    def env_block(self) -> Optional[dict]:
        """Decrypted creds for the Spotify overlay server's env block (O3)."""
        store = self.load()
        if not store:
            return None
        return {
            "SPOTIFY_CLIENT_ID": store["clientId"],
            "SPOTIFY_REFRESH_TOKEN": store["refreshToken"],
        }
