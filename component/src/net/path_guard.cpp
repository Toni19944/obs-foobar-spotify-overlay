#include "net/path_guard.h"

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

namespace obs_overlay { namespace net {

static int hex_val(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

std::string percent_decode(const std::string& in) {
    std::string out;
    out.reserve(in.size());
    for (size_t i = 0; i < in.size(); ++i) {
        if (in[i] == '%' && i + 2 < in.size()) {
            const int hi = hex_val(in[i + 1]);
            const int lo = hex_val(in[i + 2]);
            if (hi >= 0 && lo >= 0) {
                out.push_back(static_cast<char>((hi << 4) | lo));
                i += 2;
                continue;
            }
        }
        out.push_back(in[i]);
    }
    return out;
}

std::wstring utf8_to_wide(const std::string& in) {
    if (in.empty()) return std::wstring();
    const int n = MultiByteToWideChar(CP_UTF8, 0, in.data(), (int)in.size(), nullptr, 0);
    if (n <= 0) return std::wstring();
    std::wstring out(n, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, in.data(), (int)in.size(), &out[0], n);
    return out;
}

std::string wide_to_utf8(const std::wstring& in) {
    if (in.empty()) return std::string();
    const int n = WideCharToMultiByte(CP_UTF8, 0, in.data(), (int)in.size(),
                                      nullptr, 0, nullptr, nullptr);
    if (n <= 0) return std::string();
    std::string out(n, '\0');
    WideCharToMultiByte(CP_UTF8, 0, in.data(), (int)in.size(), &out[0], n,
                        nullptr, nullptr);
    return out;
}

static std::wstring canonicalize(const std::wstring& path) {
    wchar_t buf[MAX_PATH * 4];
    const DWORD n = GetFullPathNameW(path.c_str(),
                                     (DWORD)(sizeof(buf) / sizeof(buf[0])),
                                     buf, nullptr);
    if (n == 0 || n >= sizeof(buf) / sizeof(buf[0])) return std::wstring();
    return std::wstring(buf, n);
}

bool resolve_bg_path(const std::string& raw_name,
                     const std::wstring& base_folder,
                     std::wstring& out_full_path) {
    if (raw_name.empty() || base_folder.empty()) return false;

    // Layer 1 — lexical reject after percent-decoding: the bg namespace is
    // flat, so any separator or dot-dot is hostile by definition.
    const std::string name = percent_decode(raw_name);
    if (name.empty()) return false;
    if (name.find('/') != std::string::npos) return false;
    if (name.find('\\') != std::string::npos) return false;
    if (name.find("..") != std::string::npos) return false;

    const std::wstring wide_name = utf8_to_wide(name);
    if (wide_name.empty()) return false;

    // Layer 2 — canonical containment: the resolved full path must keep the
    // canonical base folder as a proper prefix (closes encoding/8.3 tricks).
    const std::wstring canon_base = canonicalize(base_folder);
    if (canon_base.empty()) return false;
    const std::wstring canon_full = canonicalize(base_folder + L"\\" + wide_name);
    if (canon_full.empty()) return false;

    const std::wstring prefix = canon_base + L"\\";
    if (canon_full.size() <= prefix.size()) return false;
    if (_wcsnicmp(canon_full.c_str(), prefix.c_str(), prefix.size()) != 0) return false;
    // Still flat after canonicalization: no further separators allowed.
    if (canon_full.find_first_of(L"\\/", prefix.size()) != std::wstring::npos) return false;

    out_full_path = canon_full;
    return true;
}

}} // namespace obs_overlay::net
