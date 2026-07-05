# Changelog

All notable changes to gamenote are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic
versioning.

## [Unreleased]

## [1.5.0] - 2026-07-05

### Added
- Stable releases are now built and published by CI: pushing a `vX.Y.Z` tag
  runs `.github/workflows/release.yml`, which verifies the tag against the
  package version, re-runs lint and tests, builds the installer, and creates
  the GitHub release with the matching CHANGELOG section as its notes.
  `RELEASE.md` documents the flow.
- Per-profile game-as-context: a profile that reads OBS recording info can now
  also source its `{context}` from the same `gamenote-obs.json` ("Also read
  {context} (the game) from this file"), so e.g. editing notes follow the OBS
  scene name automatically while the tray's "Set context" keeps driving every
  other profile. The global context-from-file option is unchanged for setups
  where everything should follow OBS.

### Changed
- Update downloads are now verified against the SHA-256 digest GitHub records
  for the release asset (in addition to the existing size check); a mismatch
  discards the download instead of running the installer. Releases without a
  digest keep the size-only check.
- Upgrading via the installer now deletes the previous version's `_internal`
  payload before copying the new one, so files renamed or removed between
  versions cannot linger and get loaded by mistake. Config, log, and
  downloaded models live outside the install folder and are untouched; a model
  bundled *inside* the payload (v1.0/v1.1 installs upgraded in place, or a
  hand-pre-bundled offline build) is moved to `%LOCALAPPDATA%\gamenote\models`
  first, where the app now also loads models from, so it keeps working offline
  across upgrades.
- The single-instance check uses a named mutex on Windows instead of binding a
  fixed localhost port, so an unrelated program owning that port can no longer
  make gamenote refuse to start with "already running".
- The app version is single-sourced from `gamenote/__init__.py`: the installer
  script and both CI workflows pass it to Inno Setup, so
  `packaging/installer.iss` no longer carries its own copy to keep in sync.
- CI now tests Python 3.11–3.14, and both the dev and release builds ship on
  Python 3.14 (previously dev builds used 3.12 while local stable builds used
  3.14).
- The per-profile OBS option is relabeled "Read OBS recording info from a file"
  (was "Stamp recording position from an OBS file") and its path field "OBS
  file" (was "Recording file"), reflecting that it now drives the `{clip}`
  stamp, the session header, the recording-file sub-header, and optionally the
  context. Configs are unaffected.
- The profile editor's resolved-path preview now resolves `{context}` the same
  way notes do — including file-sourced and per-profile OBS contexts — instead
  of only the manually typed global value.

### Fixed
- Setting a context from the tray while the settings window is open is no
  longer reverted to the window's stale Context fields on Apply/Save; the
  Context group is only written back if it was actually edited.
- OBS-derived note decoration is now read as one consistent snapshot per note:
  the session header, `{clip}` offset, recording-file sub-header, and
  per-profile game context all come from a single read of `gamenote-obs.json`
  instead of four separate ones, so a note can no longer mix values from before
  and after an OBS update (and each note does one file read instead of four).
- A sidecar read that catches OBS mid-write (an empty or partially written
  file — the OBS script rewrites it in place) is retried once after a short
  delay instead of silently dropping the session header, `{clip}` stamp, and
  game context for that note.
- A model size or device change made while a note is recording (or while a
  model is still loading) is no longer dropped: it now applies automatically as
  soon as the note or load finishes, instead of waiting for the next
  settings Apply.
- Settings now refuse a "Min seconds" larger than "Max seconds", which would
  have silently discarded every recorded note.
- Hotkeys that fail to register with Windows (invalid key name, or the
  combination is taken by another app) are now reported in a dialog on
  Apply/Save and a tray balloon at startup, instead of only a log line.
- If applying settings fails (e.g. the config file cannot be written), the
  in-memory configuration is rolled back to its previous state instead of
  diverging from what is on disk.
- Version tags with a suffix (e.g. `v1.2.3-rc1`) no longer parse with
  concatenated digits (`1.2.31`); the suffix is ignored.

## [1.4.0] - 2026-06-10

### Added
- Opt-in development update channel (Settings -> Updates -> Channel): CI
  publishes an automated build of every change that passes the tests to a
  rolling `dev` pre-release, and the in-app updater can install straight from
  it. The default remains stable releases, which are unaffected; switching back
  is a one-time reinstall of the latest stable installer from the releases page.
- Notes now record which video file they belong to: when a profile stamps
  recording positions from OBS ("Stamp recording position from an OBS file")
  and writes session headers, a `### Recording file:` sub-header naming the
  current recording file is written under the `## Recording session:` header
  whenever the file changes — so `{clip}` offsets stay attributable when OBS
  automatic file splitting starts a new file mid-session.

### Changed
- The OBS-sourced session header no longer needs its own option: whenever "Stamp
  recording position from an OBS file" is on (and session headers are enabled),
  the `## Recording session:` header automatically carries the recording's start
  time from `gamenote-obs.json`. It also now falls back to the date once
  recording stops, matching the documented behavior and the other OBS-derived
  decorations.

### Removed
- The legacy per-profile "Read session value from a file" option
  (`session_from_file` / `session_file`) and plain-text `.current_session`
  support. The `gamenote-obs.json` sidecar written by
  `integrations/obs/gamenote-obs.lua` is the one OBS integration going forward;
  if you used the old option, point the profile's "Recording file" at the JSON
  instead. Old configs load fine (the obsolete keys are ignored and dropped on
  the next save). Plain-text context files (e.g. a legacy `.current_game`) still
  work for the context-from-file setting.

### Fixed
- A manual "Check for updates" while offline now reports that the check could
  not be completed, instead of incorrectly saying you are on the latest version.

## [1.3.0] - 2026-06-08

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

### Fixed
- A corrupt or hand-broken config is now backed up to `config.json.bad` and reset
  to defaults instead of failing to load on every launch; the config is also
  flushed to disk durably on save.
- The updater only downloads from an HTTPS GitHub URL and writes the installer
  atomically, cleaning up partial downloads.
- A failed model load now reports "model error" on a hotkey press instead of a
  permanent "loading...".
- The silence-calibration meter reliably releases the microphone when its window
  or tab is hidden or closed.

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

[Unreleased]: https://github.com/annotatedabstract/gamenote/compare/v1.5.0...HEAD
[1.5.0]: https://github.com/annotatedabstract/gamenote/releases/tag/v1.5.0
[1.4.0]: https://github.com/annotatedabstract/gamenote/releases/tag/v1.4.0
[1.3.0]: https://github.com/annotatedabstract/gamenote/releases/tag/v1.3.0
[1.2.0]: https://github.com/annotatedabstract/gamenote/releases/tag/v1.2.0
[1.1.0]: https://github.com/annotatedabstract/gamenote/releases/tag/v1.1.0
[1.0.0]: https://github.com/annotatedabstract/gamenote/releases/tag/v1.0.0
