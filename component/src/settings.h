// Component settings (data-model.md ComponentSettings) — cfg_var-backed,
// edited on the Preferences page (FR-008), persisted by foobar2000.
#pragma once
#include <SDK/foobar2000.h>

namespace obs_overlay { namespace settings {

// Persisted values (defaults per data-model.md).
extern cfg_uint cfg_overlay_port;        // 8081
extern cfg_uint cfg_spectrum_port;       // 9001
extern cfg_bool cfg_enabled;             // true
extern cfg_string cfg_bg_folder;         // "" => default_bg_folder()
extern cfg_int cfg_spectrum_offset_ms;   // 0, clamp -500..+500 (FR-008/D7)

constexpr int kPortMin = 1024;
constexpr int kPortMax = 65535;
constexpr int kOffsetMsMin = -500;
constexpr int kOffsetMsMax = 500;

// Both ports in [1024, 65535] and distinct.
bool ports_valid(t_uint32 overlay_port, t_uint32 spectrum_port);

int clamp_offset_ms(int v);

// <fb2k profile>\foo_obs_overlay\bg — Win32 (non-file://) path, no trailing
// separator. Default background folder; first-run extraction target (D5).
pfc::string8 default_bg_folder();

// Configured bg folder if set, else default_bg_folder(). Win32 path.
pfc::string8 effective_bg_folder();

// Clamped snapshot accessors (guard against hand-edited config values).
t_uint32 overlay_port();
t_uint32 spectrum_port();
int spectrum_offset_ms();

}} // namespace obs_overlay::settings
