// Now-playing metadata snapshot (R6/D3, data-model NowPlayingSnapshot).
// Written only by the main-thread play_callback; read by HTTP workers.
// No per-request main-thread marshaling (FR-012).
#pragma once
#include <string>

namespace obs_overlay { namespace player {

struct NowPlayingSnapshot {
    bool active = false;          // false => /api/player hide signal (index -1)
    std::string artist;           // UTF-8; fb2k titleformat "?" served as-is
    std::string title;
    double duration = 0.0;        // seconds; 0 for unknown/streams
    double position_anchor = 0.0; // seconds at anchor_time
    double anchor_time = 0.0;     // steady-clock seconds; interpolation base
    enum class State { playing, paused, stopped } state = State::stopped;
};

// Thread-safe copy of the current snapshot.
NowPlayingSnapshot get_snapshot();

// steady-clock seconds matching NowPlayingSnapshot::anchor_time.
double now_seconds();

// Served position: anchor + elapsed while playing, frozen while paused.
double snapshot_position(const NowPlayingSnapshot& s);

}} // namespace obs_overlay::player
