// Spectrum DSP pipeline — exact replication of the legacy spectrum-server.py
// numerics (contracts/dsp-parity.md, FR-005). This translation unit is the
// product's visual contract: it is compiled verbatim into both the component
// DLL and tests/parity oracle_runner (SC-003, tolerance 0.001/band/window).
//
// Deliberately dependency-free: no foobar2000 SDK, no CivetWeb — only the
// vendored KissFFT (double-precision build) and the C++ standard library.
#pragma once
#include <cstddef>
#include <vector>

#include "kiss_fftr.h"

namespace obs_overlay { namespace dsp {

constexpr int kSampleRate = 44100;
constexpr int kWindowSize = 1024;   // contiguous, non-overlapping (~43.07/s)
constexpr int kBands = 64;
constexpr double kFreqMin = 120.0;
constexpr double kFreqMax = 16000.0;
constexpr double kGain = 3.0;              // applied UNCLIPPED
constexpr double kPeakDecay = 0.995;       // AGC: peak = max(peak*decay, band)
constexpr double kSmoothing = 0.67;        // level = level*s + norm*(1-s)
constexpr double kNoiseGateRms = 0.0002;   // window RMS below => zero bands

class SpectrumPipeline {
public:
    SpectrumPipeline();
    ~SpectrumPipeline();
    SpectrumPipeline(const SpectrumPipeline&) = delete;
    SpectrumPipeline& operator=(const SpectrumPipeline&) = delete;

    // Restore the oracle's starting condition: peak=1.0, level=0.0.
    void reset();

    // Process one 1024-sample mono 44.1 kHz window through gate -> FFT ->
    // band average -> gain -> AGC -> smoothing, updating internal state.
    // Silence decay (FR-006) is this same call with an all-zero window.
    void process_window(const double* samples /* kWindowSize */);

    // Smoothed per-band output after the last window, each in [0, 1].
    const double* levels() const { return m_level; }

private:
    // Precomputed tables (FR-005)
    double m_window[kWindowSize];           // symmetric Hann, denominator N-1
    std::vector<int> m_masked_bins;         // rfft bins with 120 <= f <= 16000
    std::vector<int> m_bin_to_band;         // per masked bin; -1 = gap (dropped)
    double m_band_counts[kBands];           // bins per band, min 1

    // Mutable per-window state
    double m_peak[kBands];
    double m_level[kBands];

    // FFT workspace
    kiss_fftr_cfg m_fft_cfg;
    std::vector<kiss_fft_scalar> m_windowed;   // kWindowSize
    std::vector<kiss_fft_cpx> m_spectrum;      // kWindowSize/2 + 1
};

}} // namespace obs_overlay::dsp
