# Changelog

All notable changes to gamenote are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses semantic
versioning.

## [Unreleased]

### Added
- Overlay indicators: a pulsing blue dot on "listening" and a green check on
  "saved", matching the landing-page graphic.
- Left-clicking the tray icon now opens the menu (right-click still works).
- Opt-in auto-update: checks GitHub Releases on launch and offers a one-click
  install. A "Check for updates..." item is always in the tray menu. On by
  default, toggleable in Settings.
- Test suite (pytest), ruff lint config, and GitHub Actions CI.

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

[Unreleased]: https://github.com/annotatedabstract/gamenote/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/annotatedabstract/gamenote/releases/tag/v1.1.0
[1.0.0]: https://github.com/annotatedabstract/gamenote/releases/tag/v1.0.0
