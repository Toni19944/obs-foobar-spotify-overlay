#include "assets/asset_extract.h"

#include <SDK/foobar2000.h>

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstring>
#include <string>

#include "assets/embedded_assets.h"
#include "net/path_guard.h" // utf8_to_wide
#include "settings.h"

namespace obs_overlay { namespace assets {

static bool ensure_directory(const std::wstring& dir) {
    // Two levels at most (<profile>\foo_obs_overlay\bg) — create parents.
    std::wstring partial;
    for (size_t i = 0; i <= dir.size(); ++i) {
        if (i == dir.size() || dir[i] == L'\\' || dir[i] == L'/') {
            if (!partial.empty() && partial.back() != L':') {
                if (!CreateDirectoryW(partial.c_str(), nullptr) &&
                    GetLastError() != ERROR_ALREADY_EXISTS &&
                    GetLastError() != ERROR_ACCESS_DENIED) {
                    // ACCESS_DENIED can fire on drive roots; real failures
                    // surface on the final component below.
                }
            }
            if (i < dir.size()) partial.push_back(L'\\');
        } else {
            partial.push_back(dir[i]);
        }
    }
    const DWORD attrs = GetFileAttributesW(dir.c_str());
    return attrs != INVALID_FILE_ATTRIBUTES && (attrs & FILE_ATTRIBUTE_DIRECTORY);
}

void extract_default_backgrounds() {
    const pfc::string8 folder8 = settings::default_bg_folder();
    const std::wstring folder = net::utf8_to_wide(folder8.get_ptr());
    if (!ensure_directory(folder)) {
        console::printf("foo_obs_overlay: cannot create background folder: %s",
                        folder8.get_ptr());
        return;
    }

    unsigned written = 0, skipped = 0, failed = 0;
    for (size_t i = 0; i < assets_count(); ++i) {
        const EmbeddedAsset& a = assets_begin()[i];
        if (std::strncmp(a.name, "bg/", 3) != 0) continue;

        const std::wstring target =
            folder + L"\\" + net::utf8_to_wide(a.name + 3);
        if (GetFileAttributesW(target.c_str()) != INVALID_FILE_ATTRIBUTES) {
            ++skipped; // user file present — never overwrite
            continue;
        }

        HANDLE h = CreateFileW(target.c_str(), GENERIC_WRITE, 0, nullptr,
                               CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (h == INVALID_HANDLE_VALUE) { ++failed; continue; }
        DWORD out = 0;
        const BOOL ok = WriteFile(h, a.data, (DWORD)a.size, &out, nullptr);
        CloseHandle(h);
        if (!ok || out != a.size) {
            DeleteFileW(target.c_str());
            ++failed;
        } else {
            ++written;
        }
    }

    if (written > 0 || failed > 0) {
        console::printf(
            "foo_obs_overlay: default backgrounds extracted to %s "
            "(%u written, %u already present, %u failed)",
            folder8.get_ptr(), written, skipped, failed);
    }
}

}} // namespace obs_overlay::assets
