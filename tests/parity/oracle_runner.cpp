// oracle_runner — offline DSP parity check (T013, FR-013/SC-003).
//
// Compiles component/src/dsp/spectrum_pipeline.cpp VERBATIM (same translation
// unit as the shipped DLL — the tested code IS the shipped code), feeds it the
// reference WAV from reset state, and compares every band of every window
// against the legacy capture. PASS iff |delta| <= 0.001 everywhere.
//
// Usage: oracle_runner <reference.wav> <reference.jsonl>
// Exit code: 0 PASS, 1 FAIL/error.
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#include "dsp/spectrum_pipeline.h"

namespace {

constexpr double kTolerance = 0.001;

// Minimal RIFF/WAVE reader: PCM16 mono 44.1 kHz only (the committed
// reference format).
std::vector<int16_t> read_wav_pcm16_mono_44k(const char* path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) { std::fprintf(stderr, "cannot open WAV: %s\n", path); std::exit(1); }

    char riff[4], wave[4];
    uint32_t riff_size = 0;
    f.read(riff, 4);
    f.read(reinterpret_cast<char*>(&riff_size), 4);
    f.read(wave, 4);
    if (!f || std::memcmp(riff, "RIFF", 4) != 0 || std::memcmp(wave, "WAVE", 4) != 0) {
        std::fprintf(stderr, "not a RIFF/WAVE file: %s\n", path);
        std::exit(1);
    }

    uint16_t format = 0, channels = 0, bits = 0;
    uint32_t rate = 0;
    std::vector<int16_t> samples;
    bool have_fmt = false, have_data = false;

    while (f && !(have_fmt && have_data)) {
        char id[4];
        uint32_t size = 0;
        f.read(id, 4);
        f.read(reinterpret_cast<char*>(&size), 4);
        if (!f) break;
        if (std::memcmp(id, "fmt ", 4) == 0) {
            std::vector<char> fmt(size);
            f.read(fmt.data(), size);
            std::memcpy(&format, fmt.data() + 0, 2);
            std::memcpy(&channels, fmt.data() + 2, 2);
            std::memcpy(&rate, fmt.data() + 4, 4);
            std::memcpy(&bits, fmt.data() + 14, 2);
            have_fmt = true;
        } else if (std::memcmp(id, "data", 4) == 0) {
            samples.resize(size / 2);
            f.read(reinterpret_cast<char*>(samples.data()), samples.size() * 2);
            have_data = true;
        } else {
            f.seekg(size + (size & 1), std::ios::cur); // chunks are word-aligned
        }
    }

    if (!have_fmt || !have_data) {
        std::fprintf(stderr, "missing fmt/data chunk: %s\n", path);
        std::exit(1);
    }
    if (format != 1 || channels != 1 || rate != 44100 || bits != 16) {
        std::fprintf(stderr,
            "reference WAV must be PCM16 mono 44100 Hz (got fmt=%u ch=%u rate=%u bits=%u)\n",
            format, channels, rate, bits);
        std::exit(1);
    }
    return samples;
}

// Parse one JSONL line: a bare JSON array of 64 numbers.
bool parse_levels_line(const std::string& line, double out[obs_overlay::dsp::kBands]) {
    const char* p = line.c_str();
    while (*p == ' ' || *p == '\t') ++p;
    if (*p != '[') return false;
    ++p;
    for (int b = 0; b < obs_overlay::dsp::kBands; ++b) {
        char* end = nullptr;
        out[b] = std::strtod(p, &end);
        if (end == p) return false;
        p = end;
        while (*p == ' ' || *p == ',') ++p;
    }
    return *p == ']';
}

} // namespace

int main(int argc, char** argv) {
    if (argc != 3) {
        std::fprintf(stderr, "usage: %s <reference.wav> <reference.jsonl>\n", argv[0]);
        return 1;
    }

    const std::vector<int16_t> pcm = read_wav_pcm16_mono_44k(argv[1]);
    std::ifstream jsonl(argv[2]);
    if (!jsonl) { std::fprintf(stderr, "cannot open JSONL: %s\n", argv[2]); return 1; }

    using namespace obs_overlay::dsp;
    SpectrumPipeline pipeline; // constructed in reset state
    pipeline.reset();

    const size_t n_windows = pcm.size() / kWindowSize;
    double window[kWindowSize];
    double expected[kBands];
    std::string line;
    double max_delta = 0.0;
    size_t max_delta_window = 0;
    int max_delta_band = 0;

    for (size_t k = 0; k < n_windows; ++k) {
        if (!std::getline(jsonl, line)) {
            std::fprintf(stderr, "FAIL: JSONL ended early at window %zu (expected %zu)\n",
                         k, n_windows);
            return 1;
        }
        if (!parse_levels_line(line, expected)) {
            std::fprintf(stderr, "FAIL: malformed JSONL at window %zu\n", k);
            return 1;
        }

        // Same sample conversion as the capture: int16/32768 (exact).
        for (int n = 0; n < kWindowSize; ++n)
            window[n] = pcm[k * kWindowSize + n] / 32768.0;
        pipeline.process_window(window);

        const double* levels = pipeline.levels();
        for (int b = 0; b < kBands; ++b) {
            const double delta = std::fabs(levels[b] - expected[b]);
            if (delta > max_delta) {
                max_delta = delta;
                max_delta_window = k;
                max_delta_band = b;
            }
            if (delta > kTolerance) {
                std::fprintf(stderr,
                    "FAIL: first divergence at window %zu band %d: "
                    "component=%.17g reference=%.17g |delta|=%.3e (tol %.3e)\n",
                    k, b, levels[b], expected[b], delta, kTolerance);
                return 1;
            }
        }
    }

    if (std::getline(jsonl, line) && !line.empty()) {
        std::fprintf(stderr, "FAIL: JSONL has more lines than WAV windows (%zu)\n", n_windows);
        return 1;
    }

    std::printf("PASS: %zu windows x %d bands within %.3e "
                "(max |delta| %.3e at window %zu band %d)\n",
                n_windows, kBands, kTolerance, max_delta, max_delta_window, max_delta_band);
    return 0;
}
