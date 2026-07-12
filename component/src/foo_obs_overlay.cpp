// foo_obs_overlay — component entry point (T007 skeleton, T022 lifecycle).
// Feature 013: in-process replacement for the legacy overlay-server.ps1 /
// spectrum-server.py runtime.
#include <SDK/foobar2000.h>

#include "assets/asset_extract.h"
#include "audio/vis_source.h"
#include "net/http_server.h"
#include "net/ws_broadcaster.h"
#include "server_control.h"
#include "settings.h"

DECLARE_COMPONENT_VERSION(
    "OBS Overlay Server",
    "0.2.0",
    "Serves the OBS now-playing overlay (HTTP) and 64-band spectrum "
    "(WebSocket) directly from foobar2000 — no external processes.\n\n"
    "Replaces overlay-server.ps1 + spectrum-server.py + foo_beefweb.");

VALIDATE_COMPONENT_FILENAME("foo_obs_overlay.dll");

namespace obs_overlay {

namespace {
net::HttpServer g_http;
net::WsBroadcaster g_ws;
} // namespace

// Server lifecycle helpers — also used by the Preferences page (T032):
// Apply/enable/disable restart or stop both servers without a fb2k restart.
void start_servers() {
    // Independent starts: one bind failing must not stop the other (FR-007).
    g_http.start(settings::overlay_port());
    g_ws.start(settings::spectrum_port());
}

void stop_servers() {
    // R12 shutdown order: WS first (tick -> senders -> context), then HTTP.
    g_ws.stop();
    g_http.stop();
}

void restart_servers() {
    stop_servers();
    if (settings::cfg_enabled.get()) start_servers();
}

std::string http_status() { return g_http.status(); }
std::string ws_status() { return g_ws.status(); }

namespace {

class obs_overlay_initquit : public initquit {
public:
    void on_init() override {
        // Main thread. play_callback is a static service (auto-registered).
        assets::extract_default_backgrounds();
        audio::VisSource::start(); // vis stream + pull thread
        if (settings::cfg_enabled.get()) {
            start_servers();
        } else {
            console::print("foo_obs_overlay: disabled in Preferences — servers not started");
        }
    }

    void on_quit() override {
        // R12 order: tick -> senders -> contexts (inside stop_servers)
        // -> pull thread -> visualisation stream (inside VisSource::stop).
        stop_servers();
        audio::VisSource::stop();
    }
};

FB2K_SERVICE_FACTORY(obs_overlay_initquit);

} // namespace

} // namespace obs_overlay
