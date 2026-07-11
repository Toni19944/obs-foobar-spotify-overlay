// Interface to the build-generated embedded asset table.
// The definitions live in <build>/generated/embedded_assets.cpp, produced by
// component/tools/embed_assets.cmake from the repo-root overlay HTML and bg/
// set — byte-exact (SC-007). This header is hand-written and stable.
#pragma once
#include <cstddef>

namespace obs_overlay { namespace assets {

struct EmbeddedAsset {
    const char* name;         // "nowplaying-overlay.html" or "bg/<filename>"
    const unsigned char* data;
    size_t size;
    const char* content_type;
};

const EmbeddedAsset* assets_begin();
size_t assets_count();

// Asset 0: the overlay page served at "/".
const EmbeddedAsset* overlay_html();

// Exact-name lookup within the embedded table (no filesystem).
const EmbeddedAsset* find_asset(const char* name);

}} // namespace obs_overlay::assets
