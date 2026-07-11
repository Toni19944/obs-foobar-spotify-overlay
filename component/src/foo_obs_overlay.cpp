// foo_obs_overlay — component entry point.
// Feature 013: in-process replacement for the legacy overlay-server.ps1 /
// spectrum-server.py runtime. Skeleton (T007): version declaration +
// initquit shell; servers are wired in T022.
#include <SDK/foobar2000.h>

DECLARE_COMPONENT_VERSION(
    "OBS Overlay Server",
    "0.2.0",
    "Serves the OBS now-playing overlay (HTTP) and 64-band spectrum "
    "(WebSocket) directly from foobar2000 — no external processes.\n\n"
    "Replaces overlay-server.ps1 + spectrum-server.py + foo_beefweb.");

VALIDATE_COMPONENT_FILENAME("foo_obs_overlay.dll");

namespace {

class obs_overlay_initquit : public initquit {
public:
    void on_init() override {
        // T022: extract default backgrounds, register play callback,
        // start vis pull thread, start HTTP + WS servers.
    }
    void on_quit() override {
        // T022: shutdown in R12 order (tick -> senders -> contexts ->
        // pull thread -> vis stream -> callbacks).
    }
};

FB2K_SERVICE_FACTORY(obs_overlay_initquit);

} // namespace
