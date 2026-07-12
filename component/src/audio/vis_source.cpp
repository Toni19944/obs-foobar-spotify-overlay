#include "audio/vis_source.h"

#include <SDK/foobar2000.h>

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstring>
#include <mutex>
#include <thread>
#include <vector>

#include "dsp/spectrum_pipeline.h"
#include "player/now_playing.h"
#include "settings.h"

namespace obs_overlay { namespace audio {

namespace {

constexpr double kWindowPeriod =
    (double)dsp::kWindowSize / (double)dsp::kSampleRate; // ~23.2 ms (~43/s)
constexpr double kBacklogSeconds = 2.0;   // generous starve margin (R1)
constexpr double kStarvationGrace = 0.25; // playing but no data => silence feed
constexpr double kReanchorSlack = 0.75;   // cursor drift beyond this => re-anchor

std::mutex g_levels_mutex;
double g_levels[dsp::kBands] = {};

std::atomic<bool> g_stop{false};
std::thread g_thread;
visualisation_stream_v2::ptr g_stream; // created/released on the main thread

double steady_now() {
    using namespace std::chrono;
    return duration<double>(steady_clock::now().time_since_epoch()).count();
}

void publish_levels(const dsp::SpectrumPipeline& pipeline) {
    std::lock_guard<std::mutex> lock(g_levels_mutex);
    std::memcpy(g_levels, pipeline.levels(), sizeof(g_levels));
}

// Pull-thread state machine (R1). Everything here is exclusive to the
// thread except the published levels and the (atomic-read) settings.
void pull_thread_main() {
    dsp::SpectrumPipeline pipeline;

    std::vector<double> src;      // downmixed native-rate samples (+carry)
    double resample_phase = 0.0;  // fractional read position into src (R5)
    unsigned src_rate = 0, src_channels = 0;

    std::vector<double> acc;      // 44.1 kHz mono accumulator
    acc.reserve(dsp::kWindowSize * 4);

    double cursor = 0.0;          // stream-time seconds; advances by consumed audio
    bool anchored = false;
    double offset_s = settings::spectrum_offset_ms() / 1000.0;

    double last_data_time = steady_now();
    double silence_deadline = steady_now();
    const double zeros[dsp::kWindowSize] = {};

    auto feed_silence_window = [&]() {
        // Wall-clock cadence is fine here: input is all-zero, only the
        // decay-step count matters (R1). Drift-compensated deadline.
        const double now = steady_now();
        if (silence_deadline < now - 1.0) silence_deadline = now; // fell behind
        const double wait = silence_deadline - now;
        if (wait > 0.0)
            std::this_thread::sleep_for(std::chrono::duration<double>(wait));
        silence_deadline += kWindowPeriod;
        pipeline.process_window(zeros);
        publish_levels(pipeline);
    };

    auto reset_input_chain = [&]() {
        src.clear();
        resample_phase = 0.0;
        acc.clear();
    };

    audio_chunk_impl chunk;

    while (!g_stop.load(std::memory_order_relaxed)) {
        // D7: timing-offset change re-anchors the read cursor live —
        // no server restart, DSP state untouched.
        const double offset_now = settings::spectrum_offset_ms() / 1000.0;
        if (offset_now != offset_s) {
            offset_s = offset_now;
            anchored = false;
        }

        const auto state = player::get_snapshot().state;
        if (state != player::NowPlayingSnapshot::State::playing) {
            anchored = false;
            feed_silence_window(); // decays exactly like the legacy feed
            continue;
        }

        if (!anchored) {
            double t = 0.0;
            if (g_stream.is_valid() && g_stream->get_absolute_time(t)) {
                // Read position = playback time − offset (positive offset =
                // spectrum later). Contiguous reads resume from here (E3).
                cursor = t - offset_s;
                if (cursor < 0.0) cursor = 0.0;
                anchored = true;
                reset_input_chain();
                last_data_time = steady_now();
            } else {
                feed_silence_window();
                continue;
            }
        }

        if (g_stream.is_valid() && g_stream->get_chunk_absolute(chunk, cursor, kWindowPeriod)
            && chunk.get_sample_count() > 0) {
            cursor += chunk.get_duration();
            last_data_time = steady_now();
            silence_deadline = steady_now(); // resync the silence cadence

            const unsigned rate = chunk.get_srate();
            const unsigned channels = chunk.get_channels();
            if (rate != src_rate || channels != src_channels) {
                // Rate/channel change (track transition): reset the
                // interpolator phase, never the DSP state (R5).
                src.clear();
                resample_phase = 0.0;
                src_rate = rate;
                src_channels = channels;
            }

            // Downmix: mean across channels (legacy data.mean(axis=1)).
            const audio_sample* data = chunk.get_data();
            const size_t frames = chunk.get_sample_count();
            const size_t base = src.size();
            src.resize(base + frames);
            for (size_t f = 0; f < frames; ++f) {
                double sum = 0.0;
                for (unsigned c = 0; c < channels; ++c)
                    sum += (double)data[f * channels + c];
                src[base + f] = sum / (double)channels;
            }

            // Linear resample to 44.1 kHz with fractional phase carried
            // across chunk boundaries (R5). Identity ratio for 44.1k input.
            const double ratio = (double)src_rate / (double)dsp::kSampleRate;
            size_t consumed = 0;
            while (true) {
                const size_t i = (size_t)resample_phase;
                if (i + 1 >= src.size()) break;
                const double frac = resample_phase - (double)i;
                acc.push_back(src[i] + (src[i + 1] - src[i]) * frac);
                resample_phase += ratio;
                consumed = i;
            }
            if (consumed > 0) {
                src.erase(src.begin(), src.begin() + consumed);
                resample_phase -= (double)consumed;
            }

            // Emit every complete contiguous window (E3: no skips/repeats).
            size_t off = 0;
            while (acc.size() - off >= (size_t)dsp::kWindowSize) {
                pipeline.process_window(acc.data() + off);
                publish_levels(pipeline);
                off += dsp::kWindowSize;
            }
            if (off > 0) acc.erase(acc.begin(), acc.begin() + off);
            continue; // keep consuming while data is available
        }

        // No data at the cursor. Distinguish "not yet available" (live edge)
        // from "fell out of the backlog" (seek/stall) via current time.
        double t = 0.0;
        if (g_stream.is_valid() && g_stream->get_absolute_time(t)) {
            const double target = t - offset_s;
            if (cursor > target + kReanchorSlack ||
                cursor < target - kBacklogSeconds + kReanchorSlack) {
                console::printf(
                    "foo_obs_overlay: spectrum read discontinuity "
                    "(cursor %.3f, playback %.3f) — re-anchoring", cursor, target);
                anchored = false;
                continue;
            }
        }

        if (steady_now() - last_data_time > kStarvationGrace) {
            feed_silence_window(); // starving mid-play: decay, don't freeze
        } else {
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
    }
}

} // namespace

bool VisSource::start() {
    if (g_thread.joinable()) return true;
    try {
        visualisation_manager::get()->create_stream(
            g_stream, visualisation_manager::KStreamFlagNewFFT);
        g_stream->request_backlog(kBacklogSeconds);
        g_stream->set_channel_mode(visualisation_stream_v2::channel_mode_default);
    } catch (const std::exception& e) {
        console::printf("foo_obs_overlay: visualisation stream unavailable: %s",
                        e.what());
        g_stream.release();
        return false;
    }
    g_stop.store(false);
    g_thread = std::thread(pull_thread_main);
    return true;
}

void VisSource::stop() {
    if (g_thread.joinable()) {
        g_stop.store(true);
        g_thread.join();
    }
    g_stream.release();
}

void VisSource::copy_levels(double out[dsp::kBands]) {
    std::lock_guard<std::mutex> lock(g_levels_mutex);
    std::memcpy(out, g_levels, sizeof(g_levels));
}

}} // namespace obs_overlay::audio
