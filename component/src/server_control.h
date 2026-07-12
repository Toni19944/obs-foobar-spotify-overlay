// Server lifecycle control shared between initquit (T022) and the
// Preferences page (T032). Implemented in foo_obs_overlay.cpp.
#pragma once
#include <string>

namespace obs_overlay {

void start_servers();
void stop_servers();
// Stops both servers and starts them again on the current settings iff
// enabled — Apply/enable/disable path, no fb2k restart needed (US4.2).
void restart_servers();

std::string http_status();
std::string ws_status();

} // namespace obs_overlay
