// Spectrum WebSocket broadcaster (R3/E2, contracts/spectrum-websocket.md):
// CivetWeb context on 127.0.0.1:<spectrum_port>, upgrades on any path,
// drift-compensated 30 fps tick, per-client sender thread with a single-slot
// latest-frame mailbox — a stalled client can never delay the tick or peers.
#pragma once
#include <string>

struct mg_context; // CivetWeb

namespace obs_overlay { namespace net {

class WsBroadcaster {
public:
    WsBroadcaster() = default;
    ~WsBroadcaster() { stop(); }
    WsBroadcaster(const WsBroadcaster&) = delete;
    WsBroadcaster& operator=(const WsBroadcaster&) = delete;

    // Binds 127.0.0.1:port and starts the tick thread. Bind failure is
    // logged + recorded, never fatal (FR-007).
    bool start(unsigned port);
    void stop();

    bool running() const { return m_ctx != nullptr; }
    std::string status() const { return m_status; }

private:
    mg_context* m_ctx = nullptr;
    std::string m_status = "not started";
};

}} // namespace obs_overlay::net
