# Changelog

All notable changes to gamenote are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic
versioning.

## [Unreleased]

### Added
- Recording position in notes: a per-profile "Stamp recording position from an
  OBS file" option adds a `{clip}` prefix token that expands to how far into the
  current OBS recording each note is (e.g. `[06:12]`), and stays correct across
  OBS automatic file splits. Omitted cleanly when no recording is active.
- Device setting (Settings -> Model): Auto (GPU when available, the default),
  Force GPU (CUDA), or Force CPU. Using the GPU still requires the NVIDIA CUDA
  libraries (see the README); without them the app runs on CPU as before. Force
  CPU also skips the GPU probe and its launch warning.

### Changed
- The OBS integration script is renamed (`gamenote-session.lua` ->
  `gamenote-obs.lua`) and now writes a combined `gamenote-obs.json` sidecar (game,
  session start, current-file start) instead of plain-text `.current_session`.
  Older plain-text `.current_session` / `.current_game` files are still read;
  re-point a profile's "Session file" at the JSON to use the new script and the
  `{clip}` token. Requires OBS 28+ for split tracking.

## [1.2.0] - 2026-06-07

### Added
- Overlay indicators: a pulsing blue dot on "listening" and a green check on
  "saved", matching the landing-page graphic.
- Left-clicking the tray icon now opens the menu (right-click still works).
- Opt-in auto-update: checks GitHub Releases on launch and offers a one-click
  install. A "Check for updates..." item is always in the tray menu. On by
  default, toggleable in Settings.
- Push-to-talk capture mode: per profile, press to start and press the same key
  again to stop (the default stays auto-stop on silence).
- "Open notes folder" and "Open last note" in the tray menu.
- Transcription language setting (needs a multilingual model for non-English).
- Custom .wav files for the arming sound and the hotkey beep (blank = the
  built-in tones).
- Test suite (pytest), ruff lint config, and GitHub Actions CI.

### Changed
- The model is no longer bundled in the installer; it downloads once on first
  run to %LOCALAPPDATA% and persists across updates. The installer drops from
  ~500 MB to ~90 MB, and updates are small.

### Fixed
- The log file now rotates (1 MB x 3) instead of growing without bound.
- The updater verifies the downloaded installer's size before running it.
- Audio capture falls back to the system default input device if the configured
  one is unavailable.

## [1.1.0] - 2026-06-07

### Added
- Arming sound when the app is ready and a subtle beep when a hotkey fires, each
  toggleable (global arming sound, per-profile beep).
- Larger, more noticeable "gamenote ready" overlay at launch.
- Restore-defaults buttons in Settings (Global tab and each profile), with a
  confirmation.
- Optional legacy OBS workflow: a profile can read its session header from a
  `.current_session` file, falling back to the date when absent. Includes a
  trimmed OBS script under `integrations/obs/`.

## [1.0.0] - 2026-06-06

### Added
- Initial standalone Windows release. PySide6 system-tray app with switchable
  note profiles, one global hotkey per profile, local faster-whisper
  transcription, a focus-safe overlay, and a per-user installer with the
  small.en model bundled (CPU by default).

[Unreleased]: https://github.com/annotatedabstract/gamenote/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/annotatedabstract/gamenote/releases/tag/v1.2.0
[1.1.0]: https://github.com/annotatedabstract/gamenote/releases/tag/v1.1.0
[1.0.0]: https://github.com/annotatedabstract/gamenote/releases/tag/v1.0.0
