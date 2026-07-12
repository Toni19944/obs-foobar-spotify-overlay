// Path guard for /bg/<name> requests (E4/FR-016, R8): lexical reject +
// canonical containment. No fb2k dependencies (plain Win32).
#pragma once
#include <string>

namespace obs_overlay { namespace net {

// Percent-decode a raw <name> from the request URI (UTF-8), reject any
// '/', '\', or ".." in the decoded name (flat single-level namespace),
// resolve it against base_folder (Win32 path, no trailing separator) and
// verify the canonical full path stays inside it. On success writes the
// canonical wide path for opening. Any violation or failure => false (404).
bool resolve_bg_path(const std::string& raw_name,
                     const std::wstring& base_folder,
                     std::wstring& out_full_path);

// Percent-decode helper (%xx only; '+' left as-is). Exposed for reuse.
std::string percent_decode(const std::string& in);

std::wstring utf8_to_wide(const std::string& in);
std::string wide_to_utf8(const std::wstring& in);

}} // namespace obs_overlay::net
