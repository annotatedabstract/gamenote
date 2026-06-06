# Gamenote: Claude Code Handoff

## Goal

Turn the existing `gamenote_daemon.py` (a working push-to-note voice capture daemon) into a standalone Windows desktop application with:

- A PySide6 GUI for configuration.
- Switchable note **profiles** (each profile determines where a note goes and how it is formatted).
- A system tray presence (the app lives in the tray, not as an always-open window).
- Full decoupling from the OBS Lua script.
- Distribution to people who do not have Python installed.

This is a **refactor and extend**, not a rewrite. The capture, transcription, note-writing, no-activate overlay, and single-instance logic already work. Preserve that behavior.

---

## 0. How to use this document (read first)

1. **Read the two existing files in the repo before writing anything:** `gamenote_daemon.py` and `gamenote-setup.md`. They are the starting point and the source of the working core logic.
2. **Treat Section 3 (Locked decisions) as fixed.** Do not re-open those choices.
3. **Confirm the module layout (Section 4) and the open questions (Section 10) with the human before generating the full file tree.** The human prefers proposing structure, then confirming, then coding.
4. **Build in the stages defined in Section 8.** Each stage ends at a checkpoint the human tests by hand. Stop at each checkpoint. Do not steamroll through all five stages in one pass.
5. **House style for any docs/README you generate:** no em dashes (use commas, periods, or parentheses), compact bullets, consistent headers.

---

## 1. What gamenote currently is

- A resident background process. A Stream Deck key sends a global hotkey, the daemon catches it, records a short voice note from the mic, auto-stops on trailing silence (energy-based VAD), transcribes locally with faster-whisper, and appends a timestamped line to a per-game notes file.
- The current note destination is `N:\Recordings\<Game>\<Game>_notes.md`. The game name and recording-session timestamp are read from two small files (`.current_game`, `.current_session`) written by an OBS Lua script. The daemon never derives the name itself.
- A tiny always-on-top Tkinter overlay confirms "listening" then "saved", and is built to never steal focus from the game (it uses a Win32 `WS_EX_NOACTIVATE` ex-style applied through ctypes).
- Config is a block of module-level constants at the top of the file. Calibration of the silence threshold is done by setting `DEBUG = True` and reading `rms=` values from a console.

**Known inconsistency to reconcile:** the code sets `HOTKEY = "f13"` but `gamenote-setup.md` says the default is `ctrl+alt+n`. Standardize on the F13 through F24 family (see Section 3, decision 2).

---

## 2. Core logic to preserve (lift, do not rewrite)

From the current daemon, keep the behavior of:

- **Energy-based VAD endpointing** in `record_note` (the `SILENCE_THRESHOLD`, `SILENCE_SECONDS`, `START_GRACE_SECONDS`, `MIN_SECONDS`, `MAX_SECONDS` logic). These defaults are tuned and should remain the defaults.
- **Model warmup on load** (`_warmup`), which forces backend/library init at launch so failures surface immediately rather than on the first real note.
- **CUDA-then-CPU fallback** in `load_model` (try CUDA float16, fall back to CPU int8). See Section 7 for how this interacts with distribution.
- **The no-activate overlay trick.** Port it to Qt (Section 4). If Qt window flags alone do not fully prevent focus theft on Windows, fall back to the same native `WS_EX_NOACTIVATE` ex-style the current Tk overlay already applies.
- **The single-instance guard** (bind a localhost port so a second copy refuses to start). This works in a frozen app too; keep it.
- **The session-header tail-scan** in `last_session_in_file` / `append_note` (read the last 8 KB, find the most recent `## Recording session:` header, only write a new header when the file is new or the session value changed).

---

## 3. Locked decisions

1. **GUI framework: PySide6 (Qt).** Chosen for distribution-quality presentation. Use `QSystemTrayIcon` for the tray and Qt signals/slots for cross-thread communication. The overlay is reimplemented as a frameless Qt tool window (one toolkit in the process, no Tk event loop alongside Qt).
2. **Hotkey model: one key per profile.** Every profile owns its own hotkey; all are registered and live at once. There is no active-profile switching yet. Design the data model and controller so an active-profile mode can be added later without restructuring, but do not build it now. Default hotkeys should come from the F13 through F24 range, which games never use and which a Stream Deck can send directly.
3. **Global vs per-profile split:**
   - **Global:** model size, beam size, input device, sample rate, frame size, all VAD/timing params, overlay on/off and duration, log level, the current context value and its source.
   - **Per-profile:** name, hotkey, destination root, path template, line format (timestamp format and optional prefix), session-header toggle.
   - Rationale: model is global because per-profile models would mean either several models held in VRAM at once or a multi-second reload on a keypress. Note type is about destination and format, not transcription quality.
4. **Config storage: `%APPDATA%\gamenote\config.json` (JSON).** Standard per-user Windows location, writable, survives moving the app, trivial to read/write/validate.
5. **Decouple from OBS via an app-owned context string plus path templates.** The app owns a "context" value (set from the tray or settings, default empty). Path templates use tokens (Section 5). Optionally, context can be read from an external file per the `source: "file"` setting, which lets someone point it back at `.current_game` if they still run OBS. This is off by default.
6. **Packaging: design for distribution to non-Python users from the start.** Target PyInstaller. The distributed build defaults to the **CPU (int8)** path so it runs on any Windows machine without a GPU or CUDA. GPU is an opt-in advanced path, not bundled by default. Handle model acquisition for a frozen context (Section 7). Document the admin/elevation requirement for capturing the hotkey over an elevated game.

---

## 4. Target architecture

### Proposed module layout (confirm with the human, then build)

```
gamenote/
  __init__.py
  app.py            # QApplication bootstrap, single-instance guard, wires everything, launches to tray (no window)
  config.py         # load/save config.json, schema, defaults, version/migration
  profiles.py       # Profile dataclass, destination resolver, line-format renderer
  audio.py          # mic capture + VAD endpointing (from record_note)
  transcribe.py     # model load/warmup + transcribe (from load_model/_warmup/transcribe)
  notes.py          # append_note, session-header logic, path resolution glue
  controller.py     # recording state machine, global recording lock, worker orchestration
  hotkeys.py        # register/unregister keyboard hotkeys, map hotkey -> profile id
  overlay.py        # Qt frameless, topmost, no-activate confirmation window
  tray.py           # QSystemTrayIcon + menu
  gui/
    __init__.py
    settings_window.py   # tabbed settings: Global, Profiles
    profile_editor.py    # add/remove/edit a profile
    mic_meter.py         # live RMS meter widget for silence calibration
  assets/
    icon.ico             # tray + app icon
packaging/
  gamenote.spec          # PyInstaller spec
  build.sh               # build script (Git Bash friendly)
main.pyw                 # thin entry point that calls gamenote.app.main()
requirements.txt
config.example.json
README.md
.gitattributes           # * text=auto eol=lf
```

### Threading model (important, get this right)

- **Main thread owns the Qt event loop.** The tray, overlay, and settings window are created and touched only on the main thread. Never call a `QWidget` method from another thread.
- **The `keyboard` library runs its own listener thread** and fires hotkey callbacks off-thread. Do not touch Qt from those callbacks. Instead, emit a Qt signal carrying the profile id (a small `QObject` bridge with a `Signal(str)`), connected with a queued connection so the slot runs on the main thread. The slot then starts the recording worker. Emitting a Qt signal from a plain Python thread is safe; the queued connection delivers it on the receiver's thread.
- **Recording plus transcription run in a worker** (a `QThread`, or a worker object moved to a `QThread`). The worker emits status signals (`listening`, `saved:<preview>`, `no speech`, `mic error`, `error`) that the main thread renders in the overlay.
- **One global recording lock** (single mic). A press while a note is in progress is ignored, with a brief overlay note. Two notes never record at once.
- **Model load and warmup happen at startup on a background thread.** Until the model is ready, presses are ignored with a "loading" overlay/tooltip. The tray tooltip reflects loading vs ready.

---

## 5. Data model

### config.json shape (concrete)

```json
{
  "version": 1,
  "global": {
    "model_size": "small.en",
    "beam_size": 1,
    "input_device": null,
    "sample_rate": 16000,
    "frame_ms": 30,
    "silence_threshold": 0.006,
    "silence_seconds": 1.5,
    "start_grace_seconds": 3.0,
    "min_seconds": 0.4,
    "max_seconds": 60.0,
    "overlay": { "enabled": true, "hide_ms": 2500 },
    "context": { "value": "", "source": "manual", "file_path": "" },
    "log_level": "INFO"
  },
  "profiles": [
    {
      "id": "editing",
      "name": "Editing notes",
      "hotkey": "f13",
      "dest_root": "N:\\Recordings",
      "path_template": "{context}\\{context}_notes.md",
      "line_format": { "timestamp_format": "%Y-%m-%d %H:%M:%S", "prefix": "" },
      "use_session_headers": true
    },
    {
      "id": "bugs",
      "name": "Bugs",
      "hotkey": "f14",
      "dest_root": "N:\\Notes",
      "path_template": "bugs.md",
      "line_format": { "timestamp_format": "%Y-%m-%d %H:%M:%S", "prefix": "[bug] " },
      "use_session_headers": false
    },
    {
      "id": "daily",
      "name": "Daily log",
      "hotkey": "f15",
      "dest_root": "N:\\Notes",
      "path_template": "{date}_log.md",
      "line_format": { "timestamp_format": "%H:%M:%S", "prefix": "" },
      "use_session_headers": false
    }
  ]
}
```

Notes on the schema:

- Windows paths in JSON need escaped backslashes (`\\`) or forward slashes. The resolver should accept both. The GUI can store whichever form is convenient and normalize on save.
- `context.source` is `"manual"` (value set in-app) or `"file"` (re-read from `file_path` each time a note is filed, the optional OBS bridge).
- `input_device`: `null` for system default, or an int index, or a name substring (matches the current daemon's behavior). The GUI device dropdown should write the int index.
- Provide a `Profile` dataclass with typed fields and a `from_dict`/`to_dict`. Validate on load (unique ids, unique hotkeys, non-empty name and dest_root). Surface validation errors in the GUI rather than crashing.

### Destination resolver

- Tokens: `{profile}`, `{context}`, `{date}`, `{time}`.
  - `{profile}` resolves to a filesystem-safe form of the profile (propose id or a slug of the name; confirm which).
  - `{context}` resolves to the current context value, sanitized. If context is empty, fall back to a configurable placeholder (default `_Unsorted`) so notes still land somewhere rather than failing.
  - `{date}` is `%Y-%m-%d`. `{time}` is `%H-%M-%S` (no colons, filesystem-safe).
- Sanitize every token for Windows filenames: strip `< > : " / \ | ? *` and trailing dots/spaces.
- Final path = `dest_root` joined with the rendered template. `mkdir(parents=True, exist_ok=True)` on the parent. Use `pathlib`.

### Line format and session headers

- Default line: `- [{timestamp}] {prefix}{text}`, where `{timestamp}` uses the profile's `timestamp_format`.
- Session headers: keep the current tail-scan logic. Without OBS there is no session timestamp, so the default header value is the date (`%Y-%m-%d`). A new header is written when the file is new or the last header in the file differs from the current value. `use_session_headers: false` disables headers entirely for that profile (flat append).

---

## 6. Decoupling from OBS

- Remove the hard dependency on `.current_game` / `.current_session` and the OBS Lua. The daemon no longer needs either file to function.
- Context is owned by the app and set two ways: a tray submenu (recent contexts plus a "set new context" entry) and a field in the settings window. Default empty.
- Keep the optional `source: "file"` path so a profile environment that still runs OBS can point context at `.current_game`. Off by default.
- In the README, describe the new context model and mark the OBS Lua workflow as legacy/optional. Do not delete the old setup doc; supersede it.

---

## 7. Packaging plan (decision 6 detail)

- **Tool: PyInstaller.** Build one-folder first (easier to debug bundling), then optionally one-file once it works.
- **CPU default.** The distributed app uses faster-whisper on CPU (int8). Do not bundle the large CUDA wheels (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`) by default. Keep the CUDA-then-CPU fallback in code, but the shipped build targets machines with no GPU. Treat GPU as a separate, documented opt-in (advanced users install the wheels and run from source, or a separate GPU build profile).
- **Model acquisition for a frozen app.** A frozen exe still needs the `small.en` model. Two options:
  - (a) Bundle the model files in the distribution and point faster-whisper at the bundled path. Offline, predictable, larger installer. Recommended for a friend handoff.
  - (b) Download on first run to `%LOCALAPPDATA%` with a small progress UI. Smaller installer, needs internet once.
  - Whichever is chosen, make the model cache directory explicit and writable in the frozen context (handle the model `download_root` / `HF_HOME` so it does not try to write inside the bundle). Propose (a), confirm with the human.
- **Admin / elevation.** Capturing the hotkey while a game runs as administrator requires the app to run as administrator too (this is a property of the global hook, not something code can avoid). For distribution, either request elevation via the app manifest or document "run as administrator." Note the tradeoff: a manifest means an elevation prompt on every launch. Propose, confirm.
- **Bundling gotchas to expect and iterate on:**
  - `ctranslate2` and `faster_whisper`: likely need `--collect-all` or explicit hidden imports and data files for their DLLs and shared libraries.
  - `sounddevice`: bundles PortAudio; confirm the DLL is collected.
  - PySide6: confirm the platform plugin and any needed Qt plugins are bundled.
  - `keyboard`: confirm its low-level hook works in the frozen build.
  - Expect to iterate on `gamenote.spec`. Run the build, run the exe, read the error, adjust. Do not assume the first spec is correct.
- **Outputs:** `packaging/gamenote.spec`, `packaging/build.sh`, README sections for "building the app" (for the maintainer) and "installing and running" (for the recipient).

---

## 8. Build stages (each ends at a human-tested checkpoint)

**Stage 1: Config layer.** Move the constants into `config.py` backed by `%APPDATA%\gamenote\config.json` (create with defaults on first run). No behavior change otherwise; the daemon still runs as a console/pythonw process and files a note exactly as before.
- Checkpoint (human): launch it, press the hotkey, confirm a note is filed identically to the current behavior, confirm the JSON is created and edits to it are picked up.

**Stage 2: Profiles, resolver, decouple.** Add the `Profile` dataclass, the destination resolver, and the line/format renderer. Generalize `append_note` to take a profile. Register one hotkey per profile via `hotkeys.py`. Make context app-owned (set via a temporary mechanism for now, for example a config field). Remove the OBS hard dependency.
- Checkpoint (human): two profiles on different hotkeys file to different paths and formats; a `{context}` profile files under the current context; an empty context falls back to the placeholder.

**Stage 3: Qt skeleton, tray, overlay.** Stand up `app.py` (QApplication, single-instance guard, launch to tray with no window). Build `tray.py` (menu: set context, pause/resume hotkeys, open settings placeholder, quit). Reimplement the overlay in Qt as a frameless, topmost, no-activate window driven by worker signals.
- Checkpoint (human): app launches to the tray with no window; tray menu works; the overlay appears on a note and does not steal focus from a fullscreen game; hotkeys still file notes; pause/resume works.

**Stage 4: Settings GUI.** Build the settings window: a Global tab (model, device dropdown, VAD/timing, overlay) and a Profiles tab (add/remove/edit, hotkey capture, destination root, path template with a live preview of the resolved path, line format, session-header toggle). Add the live mic-level meter for silence calibration (this replaces the `DEBUG = True` console step). Apply changes live: re-register hotkeys on profile change, reload the model only if a model-affecting setting changed and only when not mid-note.
- Checkpoint (human): edit a profile in the GUI, confirm changes take effect without a restart; use the mic meter to set the silence threshold; confirm a model change reloads cleanly.

**Stage 5: Packaging.** Write `gamenote.spec` and `build.sh`, CPU-default, model handling per Section 7, admin note, README. Iterate the spec until the one-folder build runs.
- Checkpoint (human): build the exe, run it on a machine or VM without Python, confirm it launches to the tray and files a note.

---

## 9. Conventions and constraints

- **Refactor, do not rewrite.** Preserve the working core listed in Section 2.
- Python 3.11+ syntax. Type hints on function signatures. `pathlib` over `os.path`. Standard library first; reach for third-party only when it materially helps. Format to ruff/black defaults.
- File naming: snake_case for Python modules, kebab-case for shell scripts and config-style files.
- Target Windows. The global hotkey, the no-activate overlay, and the Stream Deck workflow are Windows-centric. Do not spend effort on macOS or Linux unless asked.
- Do not invent library APIs. If unsure about a Qt, PyInstaller, faster-whisper, or sounddevice detail, verify against the docs or test it, and say so rather than guessing.
- Add a repo `.gitattributes` with `* text=auto eol=lf`.
- No secrets are expected. Ship `config.example.json`, not a real config. Do not commit a populated `config.json`.
- Generated docs follow the house style: no em dashes, compact bullets, consistent headers.

---

## 10. Open questions to raise with the human before or during Stage 1

1. Confirm the module layout in Section 4 (or propose an adjustment).
2. `{profile}` token: resolve to the profile id or a slug of the name?
3. Session semantics without OBS: date-based default is proposed. Confirm, or define a run-based or context-change-based session boundary.
4. Model for the distributed build: bundle the model (option a) or download on first run (option b)? Option (a) is recommended.
5. Elevation: request admin via manifest, or document "run as administrator"?
6. Default profiles to ship in `config.example.json`. Proposed: "Editing notes" (per-context, like the current per-game behavior), "Bugs" (flat file), "Daily log" (date-based file). Confirm or adjust.
