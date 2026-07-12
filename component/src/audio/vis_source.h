// Visualisation-stream audio source (R1/E3, D7): dedicated pull thread with
// a monotonic read cursor over latency-compensated playback audio, feeding
// contiguous non-overlapping 1024-sample 44.1 kHz mono windows to the DSP.
// Silence windows at the same cadence on pause/stop/starvation (FR-006).
#pragma once

namespace obs_overlay { namespace audio {

class VisSource {
public:
    // Main thread (initquit on_init): creates the visualisation stream and
    // starts the pull thread. Returns false if the stream cannot be created.
    static bool start();
    // Main thread (initquit on_quit): stops the thread, releases the stream.
    static void stop();

    // Thread-safe copy of the latest 64 smoothed band levels (any thread).
    static void copy_levels(double out[64]);
};

}} // namespace obs_overlay::audio
