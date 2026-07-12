#include "net/http_server.h"

#include <SDK/foobar2000.h>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "civetweb.h"

#include "assets/embedded_assets.h"
#include "net/path_guard.h"
#include "player/now_playing.h"
#include "settings.h"

namespace obs_overlay { namespace net {

namespace {

// ---------------------------------------------------------------- helpers

void json_escape_into(std::string& out, const std::string& s) {
    for (const char c : s) {
        switch (c) {
        case '"':  out += "\\\""; break;
        case '\\': out += "\\\\"; break;
        case '\b': out += "\\b"; break;
        case '\f': out += "\\f"; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default:
            if (static_cast<unsigned char>(c) < 0x20) {
                char buf[8];
                std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                out += buf;
            } else {
                out += c; // UTF-8 passthrough
            }
        }
    }
}

std::string format_number(double v) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "%.3f", v);
    return buf;
}

void send_response(mg_connection* conn, int status, const char* status_text,
                   const char* content_type, const void* body, size_t body_len) {
    mg_printf(conn,
              "HTTP/1.1 %d %s\r\n"
              "Content-Type: %s\r\n"
              "Content-Length: %zu\r\n"
              "Access-Control-Allow-Origin: *\r\n"
              "Cache-Control: no-cache\r\n"
              "Connection: keep-alive\r\n"
              "\r\n",
              status, status_text, content_type, body_len);
    if (body_len > 0) mg_write(conn, body, body_len);
}

void send_404(mg_connection* conn) {
    static const char body[] = "404 not found";
    send_response(conn, 404, "Not Found", "text/plain", body, sizeof(body) - 1);
}

const char* content_type_for_name(const std::wstring& name) {
    const size_t dot = name.find_last_of(L'.');
    if (dot == std::wstring::npos) return "application/octet-stream";
    std::wstring ext = name.substr(dot + 1);
    for (auto& c : ext) c = towlower(c);
    if (ext == L"jpg" || ext == L"jpeg") return "image/jpeg";
    if (ext == L"png") return "image/png";
    if (ext == L"gif") return "image/gif";
    if (ext == L"webp") return "image/webp";
    return "application/octet-stream";
}

bool has_image_extension(const std::wstring& name) {
    return std::strcmp(content_type_for_name(name), "application/octet-stream") != 0;
}

// ---------------------------------------------------------------- handlers

void handle_root(mg_connection* conn) {
    const assets::EmbeddedAsset* html = assets::overlay_html();
    // Served from memory, byte-identical to the repo file (SC-007).
    send_response(conn, 200, "OK", html->content_type, html->data, html->size);
}

void handle_bg_list(mg_connection* conn) {
    const pfc::string8 folder8 = settings::effective_bg_folder();
    const std::wstring folder = utf8_to_wide(folder8.get_ptr());

    // Request-time enumeration (R7); missing/empty folder => [] (contract).
    std::string json = "[";
    bool first = true;
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW((folder + L"\\*").c_str(), &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
            const std::wstring name = fd.cFileName;
            if (!has_image_extension(name)) continue;
            if (!first) json += ",";
            first = false;
            json += "\"bg/";
            json_escape_into(json, wide_to_utf8(name));
            json += "\"";
        } while (FindNextFileW(h, &fd));
        FindClose(h);
    }
    json += "]";
    send_response(conn, 200, "OK", "application/json", json.data(), json.size());
}

void handle_bg_file(mg_connection* conn, const char* name_start) {
    const pfc::string8 folder8 = settings::effective_bg_folder();
    const std::wstring folder = utf8_to_wide(folder8.get_ptr());

    std::wstring full;
    if (!resolve_bg_path(name_start, folder, full)) { // E4: violations => 404
        send_404(conn);
        return;
    }

    HANDLE h = CreateFileW(full.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr,
                           OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) {
        send_404(conn);
        return;
    }
    LARGE_INTEGER size{};
    if (!GetFileSizeEx(h, &size) || size.QuadPart > (64ll << 20)) {
        CloseHandle(h);
        send_404(conn);
        return;
    }
    std::vector<char> body(static_cast<size_t>(size.QuadPart));
    DWORD read = 0;
    const BOOL ok = body.empty() ||
        ReadFile(h, body.data(), (DWORD)body.size(), &read, nullptr);
    CloseHandle(h);
    if (!ok || read != body.size()) {
        send_404(conn);
        return;
    }
    send_response(conn, 200, "OK", content_type_for_name(full),
                  body.data(), body.size());
}

// /api/player (T019, contracts/http-api.md): beefweb-compatible shape from
// the cached snapshot — never touches the fb2k main thread, never 4xx/5xx.
void handle_api_player(mg_connection* conn) {
    const mg_request_info* ri = mg_get_request_info(conn);

    // Parse requested columns (percent-decoded, comma-separated titleformat).
    std::vector<std::string> columns;
    if (ri->query_string && *ri->query_string) {
        char decoded[2048];
        const int n = mg_get_var(ri->query_string, std::strlen(ri->query_string),
                                 "columns", decoded, sizeof(decoded));
        if (n > 0) {
            const std::string list(decoded, (size_t)n);
            size_t pos = 0;
            while (pos <= list.size()) {
                const size_t comma = list.find(',', pos);
                if (comma == std::string::npos) {
                    columns.push_back(list.substr(pos));
                    break;
                }
                columns.push_back(list.substr(pos, comma - pos));
                pos = comma + 1;
            }
        }
    }

    const player::NowPlayingSnapshot s = player::get_snapshot();

    std::string json = "{\"player\":{\"activeItem\":{";
    if (s.active) {
        json += "\"index\":0,\"position\":";
        json += format_number(player::snapshot_position(s));
        json += ",\"duration\":";
        json += format_number(s.duration);
        json += ",\"columns\":[";
        // Positional answers (verified parse contract): %artist% -> artist,
        // %title% -> title, anything else -> "" (never an error).
        for (size_t i = 0; i < columns.size(); ++i) {
            if (i) json += ",";
            json += "\"";
            if (columns[i] == "%artist%") json_escape_into(json, s.artist);
            else if (columns[i] == "%title%") json_escape_into(json, s.title);
            json += "\"";
        }
        json += "]";
    } else {
        // Stopped shape: index -1, empty columns — the overlay's hide signal.
        json += "\"index\":-1,\"position\":0,\"duration\":0,\"columns\":[]";
    }
    json += "},\"playbackState\":\"";
    switch (s.state) {
    case player::NowPlayingSnapshot::State::playing: json += "playing"; break;
    case player::NowPlayingSnapshot::State::paused:  json += "paused";  break;
    default:                                         json += "stopped"; break;
    }
    json += "\"}}";

    send_response(conn, 200, "OK", "application/json", json.data(), json.size());
}

// Single dispatch handler: the endpoint list is closed (FR-015) — anything
// unrecognized, including /api/artwork/*, is a 404.
int request_handler(mg_connection* conn, void*) {
    const mg_request_info* ri = mg_get_request_info(conn);
    const char* uri = ri->local_uri ? ri->local_uri : "/";

    if (std::strcmp(ri->request_method, "GET") != 0) {
        send_404(conn);
        return 1;
    }

    if (std::strcmp(uri, "/") == 0) handle_root(conn);
    else if (std::strcmp(uri, "/bg-list") == 0) handle_bg_list(conn);
    else if (std::strncmp(uri, "/bg/", 4) == 0 && uri[4] != '\0') handle_bg_file(conn, uri + 4);
    else if (std::strcmp(uri, "/api/player") == 0) handle_api_player(conn);
    else send_404(conn);

    return 1; // handled
}

} // namespace

// ---------------------------------------------------------------- lifecycle

bool HttpServer::start(unsigned port) {
    if (m_ctx) return true;

    char listen[64];
    std::snprintf(listen, sizeof(listen), "127.0.0.1:%u", port);
    const char* options[] = {
        "listening_ports", listen,
        "num_threads", "4",
        "request_timeout_ms", "10000",
        nullptr
    };

    mg_callbacks callbacks{};
    m_ctx = mg_start(&callbacks, nullptr, options);
    if (!m_ctx) {
        // FR-007: visible, harmless failure — fb2k keeps running.
        m_status = "FAILED to bind 127.0.0.1:" + std::to_string(port) +
                   " (port in use?)";
        console::printf("foo_obs_overlay: overlay HTTP server %s", m_status.c_str());
        return false;
    }

    mg_set_request_handler(m_ctx, "**", request_handler, nullptr);
    m_status = "running on http://127.0.0.1:" + std::to_string(port) + "/";
    console::printf("foo_obs_overlay: overlay HTTP server %s", m_status.c_str());
    return true;
}

void HttpServer::stop() {
    if (!m_ctx) return;
    mg_stop(m_ctx); // joins workers, releases the port (SC-004)
    m_ctx = nullptr;
    m_status = "stopped";
}

}} // namespace obs_overlay::net
