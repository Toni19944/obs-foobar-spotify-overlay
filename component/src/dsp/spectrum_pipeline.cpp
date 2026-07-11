#include "dsp/spectrum_pipeline.h"

#include <cmath>
#include <cstring>
#include <stdexcept>

namespace obs_overlay { namespace dsp {

// Table construction mirrors spectrum-server.py's module-level precompute
// step for step, including numpy's evaluation order, so boundary
// comparisons (mask edges, band edges) resolve identically.
SpectrumPipeline::SpectrumPipeline() {
    // np.hanning(1024): w[n] = 0.5 - 0.5*cos(2*pi*n/(M-1)), symmetric.
    constexpr double kPi = 3.141592653589793238462643383279502884;
    for (int n = 0; n < kWindowSize; ++n) {
        m_window[n] = 0.5 - 0.5 * std::cos((2.0 * kPi * n) / (kWindowSize - 1));
    }

    // np.fft.rfftfreq(1024, d=1/44100): f[k] = k * (1.0 / (n*d)).
    const double d = 1.0 / kSampleRate;
    const double val = 1.0 / (kWindowSize * d);
    const int num_bins = kWindowSize / 2 + 1;

    // Frequency mask: 120 <= f <= 16000.
    std::vector<double> masked_freqs;
    for (int k = 0; k < num_bins; ++k) {
        const double f = k * val;
        if (f >= kFreqMin && f <= kFreqMax) {
            m_masked_bins.push_back(k);
            masked_freqs.push_back(f);
        }
    }

    // np.logspace(log10(120), log10(16000), 65) == 10**linspace(a, b, 65)
    // (numpy linspace: y[i] = i*step + a, endpoint forced to b).
    double edges[kBands + 1];
    {
        const double a = std::log10(kFreqMin);
        const double b = std::log10(kFreqMax);
        const double step = (b - a) / kBands;
        for (int i = 0; i <= kBands; ++i) {
            const double e = (i == kBands) ? b : (i * step + a);
            edges[i] = std::pow(10.0, e);
        }
    }

    // Masked bin -> band via [edges[b], edges[b+1]) ranges; the exact last
    // edge joins the final band; anything else (gap bins) stays -1 => dropped.
    m_bin_to_band.assign(masked_freqs.size(), -1);
    for (int b = 0; b < kBands; ++b) {
        for (size_t i = 0; i < masked_freqs.size(); ++i) {
            if (masked_freqs[i] >= edges[b] && masked_freqs[i] < edges[b + 1])
                m_bin_to_band[i] = b;
        }
    }
    for (size_t i = 0; i < masked_freqs.size(); ++i) {
        if (masked_freqs[i] == edges[kBands]) m_bin_to_band[i] = kBands - 1;
    }

    // Per-band bin counts for averaging, min 1 (div-by-zero guard).
    for (int b = 0; b < kBands; ++b) m_band_counts[b] = 0.0;
    for (size_t i = 0; i < m_bin_to_band.size(); ++i) {
        if (m_bin_to_band[i] >= 0) m_band_counts[m_bin_to_band[i]] += 1.0;
    }
    for (int b = 0; b < kBands; ++b) {
        if (m_band_counts[b] == 0.0) m_band_counts[b] = 1.0;
    }

    m_fft_cfg = kiss_fftr_alloc(kWindowSize, 0 /* forward */, nullptr, nullptr);
    if (!m_fft_cfg) throw std::bad_alloc();
    m_windowed.resize(kWindowSize);
    m_spectrum.resize(num_bins);

    reset();
}

SpectrumPipeline::~SpectrumPipeline() {
    kiss_fftr_free(m_fft_cfg);
}

void SpectrumPipeline::reset() {
    for (int b = 0; b < kBands; ++b) {
        m_peak[b] = 1.0;
        m_level[b] = 0.0;
    }
}

void SpectrumPipeline::process_window(const double* samples) {
    double band[kBands] = {};

    // Noise gate: window RMS below threshold => all-zero band vector, which
    // still flows through AGC + smoothing below (geometric decay, FR-006).
    double sumsq = 0.0;
    for (int n = 0; n < kWindowSize; ++n) sumsq += samples[n] * samples[n];
    const double rms = std::sqrt(sumsq / kWindowSize);

    if (rms >= kNoiseGateRms) {
        for (int n = 0; n < kWindowSize; ++n)
            m_windowed[n] = samples[n] * m_window[n];
        kiss_fftr(m_fft_cfg, m_windowed.data(), m_spectrum.data());

        // Band-average the masked-bin magnitudes (np.abs => hypot), then
        // apply gain UNCLIPPED — the AGC's min(1, .) is the only bound.
        for (size_t i = 0; i < m_masked_bins.size(); ++i) {
            const int b = m_bin_to_band[i];
            if (b < 0) continue; // gap bin
            const kiss_fft_cpx& c = m_spectrum[m_masked_bins[i]];
            band[b] += std::hypot(c.r, c.i);
        }
        for (int b = 0; b < kBands; ++b)
            band[b] = band[b] / m_band_counts[b] * kGain;
    }

    // AGC + temporal smoothing, exactly as audio_callback:
    //   peak = max(peak*0.995, band); norm = min(1, band/peak);
    //   level = level*S + norm*(1-S)
    for (int b = 0; b < kBands; ++b) {
        const double decayed = m_peak[b] * kPeakDecay;
        m_peak[b] = (decayed > band[b]) ? decayed : band[b];
        const double ratio = band[b] / m_peak[b];
        const double norm = (ratio < 1.0) ? ratio : 1.0;
        m_level[b] = m_level[b] * kSmoothing + norm * (1.0 - kSmoothing);
    }
}

}} // namespace obs_overlay::dsp
