// Overlay HTTP server (R2, contracts/http-api.md): CivetWeb context on
// 127.0.0.1:<overlay_port>, 4 workers. Complete surface: GET /, /bg-list,
// /bg/<name>, /api/player — everything else 404 (FR-015).
#pragma once
#include <string>

struct mg_context; // CivetWeb

namespace obs_overlay { namespace net {

class HttpServer {
public:
    HttpServer() = default;
    ~HttpServer() { stop(); }
    HttpServer(const HttpServer&) = delete;
    HttpServer& operator=(const HttpServer&) = delete;

    // Binds 127.0.0.1:port. Failure never throws: logs to the fb2k console,
    // stores a status string for the Preferences page, returns false (FR-007).
    bool start(unsigned port);
    void stop();

    bool running() const { return m_ctx != nullptr; }
    // e.g. "running on 127.0.0.1:8081" / "FAILED to bind port 8081 (...)"
    std::string status() const { return m_status; }

private:
    mg_context* m_ctx = nullptr;
    std::string m_status = "not started";
};

}} // namespace obs_overlay::net
