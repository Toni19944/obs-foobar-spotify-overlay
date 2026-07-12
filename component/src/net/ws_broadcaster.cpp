#include "net/ws_broadcaster.h"

#include <SDK/foobar2000.h>

#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>

#include "civetweb.h"

#include "audio/vis_source.h"
#include "dsp/spectrum_pipeline.h"

namespace obs_overlay { namespace net {

namespace {

constexpr double kTickPeriod = 1.0 / 30.0; // 30 fps, drift-compensated

double steady_now() {
    using namespace std::chrono;
    return duration<double>(steady_clock::now().time_since_epoch()).count();
}

// Per-client sender thread + single-slot latest-frame mailbox (E2).
struct WsClient {
    mg_connection* conn = nullptr;
    std::mutex m;
    std::condition_variable cv;
    std::string mailbox;    // newest pending frame; overwritten, never queued
    bool closing = false;
    std::thread sender;
};

std::mutex g_clients_mutex;
std::vector<std::shared_ptr<WsClient>> g_clients;

std::atomic<bool> g_tick_stop{false};
std::thread g_tick_thread;

void sender_main(std::shared_ptr<WsClient> client) {
    for (;;) {
        std::string frame;
        {
            std::unique_lock<std::mutex> lk(client->m);
            client->cv.wait(lk, [&] {
                return client->closing || !client->mailbox.empty();
            });
            if (client->closing) return;
            frame = std::move(client->mailbox);
            client->mailbox.clear();
        }
        // Blocking per-socket write; a stall bounded by the context's
        // request timeout (~5 s) returns <= 0 => stop sending. The stalled
        // connection itself is reaped by the ping/pong read timeout.
        if (mg_websocket_write(client->conn, MG_WEBSOCKET_OPCODE_TEXT,
                               frame.data(), frame.size()) <= 0) {
            return;
        }
    }
}

// Legacy frame format: bare JSON array, 64 numbers rounded to 4 decimals,
// Python-style shortest form ("0.5" not "0.5000", zero as "0.0").
void serialize_frame(const double* levels, std::string& out) {
    out.clear();
    out.push_back('[');
    char buf[32];
    for (int b = 0; b < dsp::kBands; ++b) {
        if (b) out.push_back(',');
        std::snprintf(buf, sizeof(buf), "%.4f", levels[b]);
        size_t len = std::strlen(buf);
        while (len > 0 && buf[len - 1] == '0') --len;      // trim zeros...
        if (len > 0 && buf[len - 1] == '.') ++len;         // ...keep one ("0.0")
        out.append(buf, len);
    }
    out.push_back(']');
}

void tick_main() {
    double levels[dsp::kBands];
    std::string frame;
    frame.reserve(64 * 8);
    double next = steady_now() + kTickPeriod;

    while (!g_tick_stop.load(std::memory_order_relaxed)) {
        // Absolute-deadline schedule (next += 1/30) — long-run average is
        // exactly 30 Hz; reset only if we fell a full interval behind.
        const double now = steady_now();
        const double wait = next - now;
        if (wait > 0.0)
            std::this_thread::sleep_for(std::chrono::duration<double>(wait));
        next += kTickPeriod;
        if (next < steady_now()) next = steady_now() + kTickPeriod;

        std::lock_guard<std::mutex> reg(g_clients_mutex);
        if (g_clients.empty()) continue;

        // Serialize once per tick; fan out by overwriting each mailbox.
        audio::VisSource::copy_levels(levels);
        serialize_frame(levels, frame);
        for (auto& client : g_clients) {
            std::lock_guard<std::mutex> lk(client->m);
            client->mailbox = frame; // overwrite-on-new: bounded buffering
            client->cv.notify_one();
        }
    }
}

// --------------------------------------------------- CivetWeb WS callbacks

int ws_connect_handler(const mg_connection*, void*) {
    return 0; // accept plain upgrades on any path (FR-004)
}

void ws_ready_handler(mg_connection* conn, void*) {
    auto client = std::make_shared<WsClient>();
    client->conn = conn;
    client->sender = std::thread(sender_main, client);
    mg_set_user_connection_data(conn, client.get());
    std::lock_guard<std::mutex> reg(g_clients_mutex);
    g_clients.push_back(std::move(client));
}

int ws_data_handler(mg_connection*, int bits, char*, size_t, void*) {
    // Incoming client messages are ignored (the overlay sends none);
    // honoring CLOSE keeps the RFC handshake clean.
    return ((bits & 0x0F) != MG_WEBSOCKET_OPCODE_CONNECTION_CLOSE) ? 1 : 0;
}

void ws_close_handler(const mg_connection* conn, void*) {
    WsClient* raw = static_cast<WsClient*>(
        mg_get_user_connection_data(conn));
    if (!raw) return;

    std::shared_ptr<WsClient> client;
    {
        std::lock_guard<std::mutex> reg(g_clients_mutex);
        for (auto it = g_clients.begin(); it != g_clients.end(); ++it) {
            if (it->get() == raw) {
                client = *it;
                g_clients.erase(it);
                break;
            }
        }
    }
    if (!client) return;
    {
        std::lock_guard<std::mutex> lk(client->m);
        client->closing = true;
        client->cv.notify_one();
    }
    if (client->sender.joinable()) client->sender.join();
}

} // namespace

// ---------------------------------------------------------------- lifecycle

bool WsBroadcaster::start(unsigned port) {
    if (m_ctx) return true;

    char listen[64];
    std::snprintf(listen, sizeof(listen), "127.0.0.1:%u", port);
    const char* options[] = {
        "listening_ports", listen,
        "num_threads", "4",
        // ~5 s grace for both directions: blocked writes fail via the
        // request timeout; unresponsive clients miss ping/pong and are
        // closed by the read timeout (E2 reap policy).
        "request_timeout_ms", "5000",
        "websocket_timeout_ms", "5000",
        "enable_websocket_ping_pong", "yes",
        nullptr
    };

    mg_callbacks callbacks{};
    m_ctx = mg_start(&callbacks, nullptr, options);
    if (!m_ctx) {
        m_status = "FAILED to bind 127.0.0.1:" + std::to_string(port) +
                   " (port in use?)";
        console::printf("foo_obs_overlay: spectrum WS server %s", m_status.c_str());
        return false;
    }

    mg_set_websocket_handler(m_ctx, "**", ws_connect_handler, ws_ready_handler,
                             ws_data_handler, ws_close_handler, nullptr);

    g_tick_stop.store(false);
    g_tick_thread = std::thread(tick_main);

    m_status = "running on ws://127.0.0.1:" + std::to_string(port) + "/";
    console::printf("foo_obs_overlay: spectrum WS server %s", m_status.c_str());
    return true;
}

void WsBroadcaster::stop() {
    if (!m_ctx) return;
    // R12 order: stop the tick first, then mg_stop closes every connection,
    // which runs ws_close_handler => signals + joins each sender thread.
    if (g_tick_thread.joinable()) {
        g_tick_stop.store(true);
        g_tick_thread.join();
    }
    mg_stop(m_ctx);
    m_ctx = nullptr;
    m_status = "stopped";
    // mg_stop ran every close handler; the registry must already be empty.
    std::lock_guard<std::mutex> reg(g_clients_mutex);
    g_clients.clear();
}

}} // namespace obs_overlay::net
