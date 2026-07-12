#include "player/now_playing.h"

#include <SDK/foobar2000.h>

#include <chrono>
#include <mutex>

namespace obs_overlay { namespace player {

namespace {

std::mutex g_mutex;
NowPlayingSnapshot g_snapshot;

double steady_now() {
    using namespace std::chrono;
    return duration<double>(steady_clock::now().time_since_epoch()).count();
}

// Pre-compiled titleformat scripts (compiled lazily on the main thread).
titleformat_object::ptr g_tf_artist, g_tf_title;

void ensure_scripts() {
    if (g_tf_artist.is_empty())
        titleformat_compiler::get()->compile_safe(g_tf_artist, "%artist%");
    if (g_tf_title.is_empty())
        titleformat_compiler::get()->compile_safe(g_tf_title, "%title%");
}

// Main thread only. Evaluates against the currently playing track — used
// from both new_track and dynamic_info_track (stream metadata updates).
void refresh_titles_locked() {
    ensure_scripts();
    const auto pc = playback_control::get();
    pfc::string8 artist, title;
    pc->playback_format_title(nullptr, artist, g_tf_artist, nullptr,
                              playback_control::display_level_all);
    pc->playback_format_title(nullptr, title, g_tf_title, nullptr,
                              playback_control::display_level_all);
    g_snapshot.artist = artist.get_ptr();
    g_snapshot.title = title.get_ptr();
}

class play_callbacks : public play_callback_static {
public:
    unsigned get_flags() override {
        return flag_on_playback_new_track | flag_on_playback_dynamic_info_track |
               flag_on_playback_time | flag_on_playback_seek |
               flag_on_playback_pause | flag_on_playback_stop;
    }

    void on_playback_new_track(metadb_handle_ptr p_track) override {
        std::lock_guard<std::mutex> lock(g_mutex);
        g_snapshot.active = true;
        g_snapshot.state = NowPlayingSnapshot::State::playing;
        g_snapshot.duration = p_track.is_valid() ? p_track->get_length() : 0.0;
        if (g_snapshot.duration < 0.0) g_snapshot.duration = 0.0; // unknown/stream
        g_snapshot.position_anchor = 0.0;
        g_snapshot.anchor_time = steady_now();
        refresh_titles_locked();
    }

    void on_playback_dynamic_info_track(const file_info&) override {
        std::lock_guard<std::mutex> lock(g_mutex);
        if (g_snapshot.active) refresh_titles_locked();
    }

    void on_playback_time(double p_time) override {
        std::lock_guard<std::mutex> lock(g_mutex);
        g_snapshot.position_anchor = p_time;
        g_snapshot.anchor_time = steady_now();
    }

    void on_playback_seek(double p_time) override {
        std::lock_guard<std::mutex> lock(g_mutex);
        g_snapshot.position_anchor = p_time;
        g_snapshot.anchor_time = steady_now();
    }

    void on_playback_pause(bool p_state) override {
        std::lock_guard<std::mutex> lock(g_mutex);
        if (p_state) {
            // Freeze position at the pause moment (main thread => exact).
            g_snapshot.position_anchor = playback_control::get()->playback_get_position();
        }
        g_snapshot.anchor_time = steady_now();
        g_snapshot.state = p_state ? NowPlayingSnapshot::State::paused
                                   : NowPlayingSnapshot::State::playing;
    }

    void on_playback_stop(play_control::t_stop_reason p_reason) override {
        if (p_reason == play_control::stop_reason_starting_another)
            return; // new_track follows immediately; avoid a stopped flicker
        std::lock_guard<std::mutex> lock(g_mutex);
        g_snapshot = NowPlayingSnapshot(); // inactive/stopped
    }

    // unused
    void on_playback_starting(play_control::t_track_command, bool) override {}
    void on_playback_edited(metadb_handle_ptr) override {}
    void on_playback_dynamic_info(const file_info&) override {}
    void on_volume_change(float) override {}
};

FB2K_SERVICE_FACTORY(play_callbacks);

} // namespace

NowPlayingSnapshot get_snapshot() {
    std::lock_guard<std::mutex> lock(g_mutex);
    return g_snapshot;
}

double now_seconds() { return steady_now(); }

double snapshot_position(const NowPlayingSnapshot& s) {
    if (!s.active) return 0.0;
    double pos = s.position_anchor;
    if (s.state == NowPlayingSnapshot::State::playing)
        pos += steady_now() - s.anchor_time;
    if (pos < 0.0) pos = 0.0;
    return pos;
}

}} // namespace obs_overlay::player
