# gamenote

[![CI](https://github.com/annotatedabstract/gamenote/actions/workflows/ci.yml/badge.svg)](https://github.com/annotatedabstract/gamenote/actions/workflows/ci.yml)

Push-to-note voice capture for gameplay recording sessions. Press a hotkey (sent
by a Stream Deck key, or any key in the F13 to F24 range), speak a note, and it
transcribes locally and appends a timestamped line to a notes file. The app
lives in the system tray, shows a small overlay that never steals focus from the
game, and routes notes through switchable profiles.

![gamenote demo](gamenote.gif)

This is the standalone desktop version. It no longer depends on OBS; OBS is now
an optional integration (recording-aware session headers and a `{clip}` token),
not a requirement. See `integrations/obs/` if you record with OBS.

## Concepts

- **Profiles.** Each profile owns a hotkey and decides where its note goes and
  how the line is formatted. All profiles are live at once, one key each. The
  defaults are "Editing notes" (per-context file), "Bugs" (a flat file), and
  "Daily log" (a per-day file).
- **Context.** The app owns a context string (for example the game you are
  recording). Path templates can use it. Set it from the tray ("Set context") or
  in Settings. Default is empty; an empty context falls back to `_Unsorted` so
  notes always land somewhere.
- **Global vs per-profile.** The model, input device, and all silence/timing
  settings are global. Destination and formatting are per profile.

### Path templates

A profile's file path is `destination root` joined with its `path template`.
Templates use these tokens:

- `{profile}` the profile id
- `{context}` the current context, sanitized (falls back to `_Unsorted`)
- `{date}` the date, `YYYY-MM-DD`
- `{time}` the time, `HH-MM-SS` (filesystem safe)

By default every profile's destination root is a `gamenote` folder in your
Documents (resolved per machine on first run, for example
`C:\Users\you\Documents\gamenote`). Change it per profile in Settings.

Examples (with the default root):

- `{context}_notes.md` gives `...\Documents\gamenote\Disco Elysium_notes.md`
- `bugs.md` gives a single flat `...\Documents\gamenote\bugs.md`
- `{date}_log.md` gives one file per day under `...\Documents\gamenote`

### Line format and session headers

- Each note is `- [timestamp] prefix text`, where the timestamp format and the
  optional prefix are per profile. The prefix may include a `{clip}` token that
  expands to the note's position in the current OBS recording (for example
  `06:12`); see the OBS bullet below.
- With session headers enabled, a `## Recording session: YYYY-MM-DD` header is
  written when the file is new or the date changed. Disable headers for a flat
  append.
- Optional (OBS): with the small script in `integrations/obs/`, a profile can
  read recording info from a `gamenote-obs.json` sidecar — the session header
  carries the recording's start time, and the `{clip}` prefix token stamps how
  far into the recording each note is (and stays correct across OBS file splits).
  With session headers on, a `### Recording file:` sub-header also names the
  recording file each `{clip}` offset refers to, so notes stay attributable when
  OBS splits the recording mid-session. The older plain-text `.current_session` /
  `.current_game` files still work. See `integrations/obs/` for setup.

## Config

Settings live in `%APPDATA%\gamenote\config.json`, created with defaults on first
run. Edit it in the Settings window (recommended) or by hand. `config.example.json`
in this repo shows the shape. The log is at `%APPDATA%\gamenote\gamenote.log`.

## Installing and running (recipient)

You do not need Python.

Easiest: run the installer `gamenote-setup-<version>.exe` if one is provided. It
installs per user (no admin needed), adds a Start menu shortcut, and offers
optional desktop and "run at login" shortcuts. Then skip to step 3.

Or, from the folder build:

1. Unzip the `gamenote` folder anywhere (for example your Desktop). Keep the
   folder intact; the exe needs the files beside it.
2. Run `gamenote.exe`. It starts in the system tray (look for the icon near the
   clock). On the first run it downloads the speech model once (about 480 MB,
   needs internet); the tray shows "downloading model" then "ready". The model is
   cached and reused, so later launches and updates are fast.
3. Right click the tray icon to set the context, pause or resume hotkeys, open
   settings, or quit.
4. By default notes go to a `gamenote` folder in your Documents. Open Settings
   only if you want to change a destination or a hotkey. Bind the profile's
   hotkey on your Stream Deck (a System, Hotkey action) or just press it on the
   keyboard.
5. Press a profile's hotkey, speak, and stop. After a short silence it files the
   note and the overlay confirms with the first words.

### Update channels

By default the app updates from stable releases. Settings → Updates → Channel
offers an opt-in "Development builds" channel: CI publishes an automated build
of every change that passes the tests to a rolling `dev` pre-release, and the
in-app updater installs from it. Dev builds update often and may be broken — if
one misbehaves, switch the channel back to "Stable releases" and reinstall the
latest stable installer from the
[releases page](https://github.com/annotatedabstract/gamenote/releases/latest)
(a dev build identifies as its base version, so the stable checker will not
offer it again until a newer stable release exists).

### Run as administrator (only if needed)

If your game runs as administrator, Windows will not deliver the hotkey to a
non-elevated app. In that case, run `gamenote.exe` as administrator too (right
click, Run as administrator), so both run at the same elevation. This is a
property of the global keyboard hook, not something the app can work around. If
your games do not run elevated, normal launch is fine.

Tip: borderless windowed is more reliable than exclusive fullscreen for both the
hotkey and the overlay.

## Calibrating the silence threshold

Open Settings, go to the Global tab, and click "Start meter". Stay quiet for a
second, then speak. The readout shows the live RMS and a peak. Set the silence
threshold between the silence floor and your speaking level (closer to the floor,
with a small margin), then Apply. Stop the meter before recording a real note so
they do not share the mic.

## Building the app (maintainer)

Built on Windows with PyInstaller. The build is CPU only by default, so the
distributed app runs on any Windows machine with no GPU and no CUDA.

Prerequisites:

- Python 3.11 or newer.
- `pip install -r requirements.txt`

Build (Git Bash):

```
bash packaging/build.sh
```

This runs PyInstaller and produces a one-folder app at `dist/gamenote`.
Distribute the whole `dist/gamenote` folder. The model is not bundled, so the
build stays small; the app downloads it on first run (see the note below).

To build by hand instead:

```
pyinstaller --noconfirm --clean packaging/gamenote.spec
```

Notes:

- The model is not bundled, which keeps the build and installer small. The app
  downloads `small.en` on first run into `%LOCALAPPDATA%\gamenote\models` and
  reuses it across updates. The runtime still loads a model bundled at
  `models/small.en` inside the app folder if one is present, so you can pre-bundle
  it for a fully offline build.
- The large CUDA wheels are not installed in the build environment, so they are
  not bundled. The CUDA path remains as a runtime fallback for anyone who installs
  `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` and runs from source.
- Expect to iterate `packaging/gamenote.spec` if a dependency's DLLs or data are
  not collected. Run the exe, read the log, adjust.

## Building the installer (maintainer)

Wraps `dist/gamenote` into a single `setup.exe` with shortcuts and an
uninstaller, using Inno Setup.

Prerequisite (one time): `winget install JRSoftware.InnoSetup`

Build (Git Bash):

```
bash packaging/build-installer.sh
```

It builds the app first if needed, then compiles `packaging/installer.iss`. The
installer lands in `packaging/installer_output/gamenote-setup-<version>.exe`. The
installer is per user by default (no admin), with optional desktop and
"run at login" shortcuts the user can tick during setup. Keep `MyAppVersion` in
`packaging/installer.iss` in sync with `gamenote/__init__.py`.

The installer (about 90 MB) is too large for the git repo, so distribute it as a
GitHub Release asset, not a committed file. Tag a release and upload
`gamenote-setup-<version>.exe` to it.

### Automated dev builds (CI)

Every push to `main` that passes the test matrix also builds the installer on CI
and republishes it as `gamenote-setup-dev.exe` on the rolling `dev` pre-release
(re-runnable from the Actions tab via workflow_dispatch). Stable users never see
it: the updater's stable channel uses `releases/latest`, which excludes
pre-releases. Details:

- `packaging/build.sh` stamps a gitignored `build_info.json` (commit, build
  time) that the spec bundles; the in-app dev channel compares it against the
  `commit:` / `built_at:` lines in the dev release body, which CI composes from
  the same file.
- CI builds on Python 3.12 (the newest matrix-tested version); local stable
  releases may use a newer Python. Accepted difference.
- CI passes `/DMyAppVersion=<version>-dev.<sha>` to ISCC; the `#ifndef` guard in
  `packaging/installer.iss` lets the command line win, so dev installs are
  identifiable in Add/Remove Programs.

## Running from source (development)

```
pip install -r requirements.txt
pythonw main.pyw        # windowless (tray only)
python main.pyw         # with a console, useful for logs
```

For the GPU path from source, also `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`,
then relaunch. By default (Settings → Model → Device = Auto) the app tries CUDA at
launch and falls back to CPU automatically. Set Device to "Force CPU" to skip the GPU
probe, or "Force GPU (CUDA)" to be warned at launch if the GPU does not engage. The
tray status shows which device won (`ready (cuda)` or `ready (cpu)`).

### Tests and lint

```
pip install -r requirements-dev.txt
ruff check gamenote main.pyw tests
pytest
```

The tests cover the pure logic (config, profiles, path resolver, notes, updater,
sounds, hotkeys) and run in CI on every push.

## Support

gamenote is free and stays that way. If it has saved you an editing session and
you feel like it, there is a Ko-fi: https://ko-fi.com/annotatedabstract. Entirely
optional, and never required to use anything here.

## License

MIT. See `LICENSE`.
