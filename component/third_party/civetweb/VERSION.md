# CivetWeb — vendored copy

- **Release**: v1.16
- **Source**: https://github.com/civetweb/civetweb/archive/refs/tags/v1.16.zip
- **Vendored**: 2026-07-12 (task T003) — `include/civetweb.h`, `src/civetweb.c`
  + required `.inl` units only; examples/tests/docs dropped
- **License**: MIT (`LICENSE.md` retained)
- **Build config** (set in `component/CMakeLists.txt`): `NO_SSL`, `NO_CGI`,
  `NO_FILES`, `NO_CACHING`, `USE_WEBSOCKET` — HTTP handlers + WebSocket only,
  no filesystem document root (R2)
