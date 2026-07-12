// First-run extraction of the embedded default background set to
// <fb2k profile>\foo_obs_overlay\bg\ (D5/R7). Hand-written — kept separate
// from the build-generated embedded_assets.cpp, which regeneration clobbers.
#pragma once

namespace obs_overlay { namespace assets {

// Creates the default bg folder if needed and writes every embedded "bg/*"
// asset that does not already exist (user edits are never overwritten).
// Errors are logged to the fb2k console and are non-fatal.
void extract_default_backgrounds();

}} // namespace obs_overlay::assets
