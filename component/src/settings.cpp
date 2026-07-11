#include "settings.h"

namespace obs_overlay { namespace settings {

// {566ed20f-15a7-417c-a98c-ea8259c01e62}
static constexpr GUID guid_overlay_port =
    { 0x566ed20f, 0x15a7, 0x417c, { 0xa9, 0x8c, 0xea, 0x82, 0x59, 0xc0, 0x1e, 0x62 } };
// {76d893e3-5af4-434e-83c6-5992b388a0a0}
static constexpr GUID guid_spectrum_port =
    { 0x76d893e3, 0x5af4, 0x434e, { 0x83, 0xc6, 0x59, 0x92, 0xb3, 0x88, 0xa0, 0xa0 } };
// {f16b4d1e-8847-4ee9-837b-724ba172ccd3}
static constexpr GUID guid_enabled =
    { 0xf16b4d1e, 0x8847, 0x4ee9, { 0x83, 0x7b, 0x72, 0x4b, 0xa1, 0x72, 0xcc, 0xd3 } };
// {502c162a-5ffd-4b6e-b36e-ce70fa658b0f}
static constexpr GUID guid_bg_folder =
    { 0x502c162a, 0x5ffd, 0x4b6e, { 0xb3, 0x6e, 0xce, 0x70, 0xfa, 0x65, 0x8b, 0x0f } };
// {238e2f73-01d1-46d5-b48b-cc7e43d0bc33}
static constexpr GUID guid_spectrum_offset_ms =
    { 0x238e2f73, 0x01d1, 0x46d5, { 0xb4, 0x8b, 0xcc, 0x7e, 0x43, 0xd0, 0xbc, 0x33 } };

cfg_uint cfg_overlay_port(guid_overlay_port, 8081);
cfg_uint cfg_spectrum_port(guid_spectrum_port, 9001);
cfg_bool cfg_enabled(guid_enabled, true);
cfg_string cfg_bg_folder(guid_bg_folder, "");
cfg_int cfg_spectrum_offset_ms(guid_spectrum_offset_ms, 0);

bool ports_valid(t_uint32 overlay_port, t_uint32 spectrum_port) {
    if (overlay_port < kPortMin || overlay_port > kPortMax) return false;
    if (spectrum_port < kPortMin || spectrum_port > kPortMax) return false;
    return overlay_port != spectrum_port;
}

int clamp_offset_ms(int v) {
    return pfc::clip_t(v, kOffsetMsMin, kOffsetMsMax);
}

static pfc::string8 profile_path_win32() {
    pfc::string8 p = core_api::get_profile_path();
    if (pfc::string_has_prefix_i(p, "file://")) p.remove_chars(0, 7);
    return p;
}

pfc::string8 default_bg_folder() {
    pfc::string8 p = profile_path_win32();
    p.end_with_slash();
    p += "foo_obs_overlay\\bg";
    return p;
}

pfc::string8 effective_bg_folder() {
    pfc::string8 configured = cfg_bg_folder.get();
    if (configured.is_empty()) return default_bg_folder();
    // normalize: no trailing separator (path guard appends its own)
    while (configured.length() > 0 &&
           (configured.ends_with('\\') || configured.ends_with('/'))) {
        configured.truncate(configured.length() - 1);
    }
    return configured;
}

static t_uint32 clamp_port(t_uint32 v, t_uint32 fallback) {
    if (v < kPortMin || v > kPortMax) return fallback;
    return v;
}

t_uint32 overlay_port() { return clamp_port((t_uint32)cfg_overlay_port.get(), 8081); }
t_uint32 spectrum_port() { return clamp_port((t_uint32)cfg_spectrum_port.get(), 9001); }
int spectrum_offset_ms() { return clamp_offset_ms((int)cfg_spectrum_offset_ms.get()); }

}} // namespace obs_overlay::settings
