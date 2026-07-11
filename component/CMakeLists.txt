# foo_obs_overlay — native foobar2000 overlay component (feature 013).
# MSVC x64 only. Builds: vendored fb2k SDK static libs, CivetWeb, KissFFT,
# the component DLL (+ build-time asset embed), the DSP parity oracle_runner,
# and the .fb2k-component package.
cmake_minimum_required(VERSION 3.24)
project(foo_obs_overlay LANGUAGES C CXX)

if(NOT MSVC)
    message(FATAL_ERROR "foo_obs_overlay builds with MSVC only (plan: v143+ x64)")
endif()
if(NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR "x64 only — configure with a 64-bit MSVC toolchain")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
# Static CRT: the DLL must load on machines without a matching VC redist.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

add_compile_definitions(UNICODE _UNICODE WIN32 _WINDOWS)
add_compile_options(/utf-8)

set(REPO_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/..)
set(SDK_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/third_party/fb2k-sdk)

# ---------------------------------------------------------------- pfc
file(GLOB PFC_SOURCES ${SDK_ROOT}/pfc/*.cpp)
list(REMOVE_ITEM PFC_SOURCES ${SDK_ROOT}/pfc/synchro_nix.cpp) # nix-only unit
add_library(pfc STATIC ${PFC_SOURCES})
target_include_directories(pfc PUBLIC ${SDK_ROOT})

# ---------------------------------------------------------------- fb2k SDK
file(GLOB FB2K_SDK_SOURCES ${SDK_ROOT}/foobar2000/SDK/*.cpp)
add_library(fb2k_sdk STATIC ${FB2K_SDK_SOURCES})
target_include_directories(fb2k_sdk PUBLIC ${SDK_ROOT} ${SDK_ROOT}/foobar2000)
target_link_libraries(fb2k_sdk PUBLIC pfc)

# ---------------------------------------------------------------- CivetWeb
add_library(civetweb STATIC third_party/civetweb/src/civetweb.c)
target_include_directories(civetweb PUBLIC third_party/civetweb/include)
# Minimal feature set (R2): HTTP handlers + WebSocket, no TLS/CGI/file serving.
target_compile_definitions(civetweb PRIVATE NO_SSL NO_CGI NO_FILES NO_CACHING USE_WEBSOCKET)
target_link_libraries(civetweb PUBLIC Ws2_32)

# ---------------------------------------------------------------- KissFFT
add_library(kissfft STATIC
    third_party/kissfft/kiss_fft.c
    third_party/kissfft/kiss_fftr.c)
target_include_directories(kissfft PUBLIC third_party/kissfft)
# Double precision is part of the DSP parity contract (R4/D6).
target_compile_definitions(kissfft PUBLIC kiss_fft_scalar=double)

# ------------------------------------------------- embedded assets (bin2c)
set(GEN_DIR ${CMAKE_CURRENT_BINARY_DIR}/generated)
set(EMBEDDED_ASSETS_CPP ${GEN_DIR}/embedded_assets.cpp)
file(GLOB BG_FILES ${REPO_ROOT}/bg/*)
add_custom_command(
    OUTPUT ${EMBEDDED_ASSETS_CPP}
    COMMAND ${CMAKE_COMMAND}
        -DHTML_FILE=${REPO_ROOT}/nowplaying-overlay.html
        -DBG_DIR=${REPO_ROOT}/bg
        -DOUT_CPP=${EMBEDDED_ASSETS_CPP}
        -P ${CMAKE_CURRENT_SOURCE_DIR}/tools/embed_assets.cmake
    DEPENDS ${REPO_ROOT}/nowplaying-overlay.html ${BG_FILES}
            ${CMAKE_CURRENT_SOURCE_DIR}/tools/embed_assets.cmake
    COMMENT "Embedding overlay assets byte-exact (SC-007)")

# ---------------------------------------------------------------- DLL
set(COMPONENT_SOURCES
    src/foo_obs_overlay.cpp)

add_library(foo_obs_overlay SHARED
    ${COMPONENT_SOURCES}
    # compiled directly into the DLL so the exported entrypoint is never
    # discarded as an unreferenced static-lib member
    ${SDK_ROOT}/foobar2000/foobar2000_component_client/component_client.cpp
    ${EMBEDDED_ASSETS_CPP})
target_include_directories(foo_obs_overlay PRIVATE src)
target_link_libraries(foo_obs_overlay PRIVATE
    fb2k_sdk civetweb kissfft
    ${SDK_ROOT}/foobar2000/shared/shared-x64.lib)
set_target_properties(foo_obs_overlay PROPERTIES PREFIX "")

# ---------------------------------------------------------------- oracle
# Compiles the component's DSP sources verbatim (the tested code IS the
# shipped code). Runner source lands in T013.
if(EXISTS ${REPO_ROOT}/tests/parity/oracle_runner.cpp)
    add_executable(oracle_runner
        ${REPO_ROOT}/tests/parity/oracle_runner.cpp
        src/dsp/spectrum_pipeline.cpp)
    target_include_directories(oracle_runner PRIVATE src)
    target_link_libraries(oracle_runner PRIVATE kissfft)
endif()

# ---------------------------------------------------------------- package
# fb2k 2.x multi-arch layout: 64-bit DLL lives under x64/ inside the zip.
set(PKG_DIR ${CMAKE_CURRENT_BINARY_DIR}/package)
add_custom_target(fb2k_component ALL
    COMMAND ${CMAKE_COMMAND} -E make_directory ${PKG_DIR}/x64
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:foo_obs_overlay> ${PKG_DIR}/x64/foo_obs_overlay.dll
    COMMAND ${CMAKE_COMMAND} -E chdir ${PKG_DIR} ${CMAKE_COMMAND} -E tar cf
        ${CMAKE_CURRENT_BINARY_DIR}/foo_obs_overlay.fb2k-component --format=zip x64/foo_obs_overlay.dll
    DEPENDS foo_obs_overlay
    COMMENT "Packaging foo_obs_overlay.fb2k-component (x64/ layout)")
