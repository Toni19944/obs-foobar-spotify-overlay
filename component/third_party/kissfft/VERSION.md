# KissFFT — vendored copy

- **Release**: 131.1.0
- **Source**: https://github.com/mborgerding/kissfft/archive/refs/tags/131.1.0.zip
- **Vendored**: 2026-07-12 (task T004) — core real-FFT units only
  (`kiss_fft.c/h`, `kiss_fftr.c/h`, guts/log headers)
- **License**: BSD-3-Clause (`COPYING` + `LICENSES/` retained)
- **Build config** (set in `component/CMakeLists.txt`):
  `kiss_fft_scalar=double` — double-precision build required for DSP parity (R4/D6)
