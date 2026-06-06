# Gamenote Voice Note Tool: Setup Guide

A push-to-note voice capture tool for gameplay recording sessions. Press a Stream Deck key, speak a note, and it transcribes and appends a timestamped line to a single per-game notes file on the NAS. No window steals focus, so the game is never interrupted.

## How it fits together

- **Trigger.** A Stream Deck key sends a hotkey. A background daemon catches it. The key never opens a window, so focus stays on the game.
- **Capture.** The daemon records the mic, auto-stops after a short silence, and transcribes locally with faster-whisper.
- **Filing.** The daemon reads the current game and recording-session timestamp from two small files the OBS Lua writes, then appends the note to `N:\Recordings\<Game>\<Game>_notes.md`. That is the same folder your rename script moves the footage into, so notes and footage live together.
- **Confirmation.** A tiny always-on-top overlay (never takes focus) flashes "listening" then "saved" with the first words.

The game name has one source of truth: your OBS scene name, cleaned by the Lua exactly as `rename_recordings.sh` cleans it. The daemon never derives the name itself, so the notes file and the footage folder always match.

## Files in this delivery

- **`gamenote_daemon.py`**, the background daemon you run on the recording PC.
- **`make_postprocess_bat.lua`**, your existing OBS script with the note-tool exports added. It is a full replacement for the file you are running now.
- **`gamenote-setup.md`**, this guide.

## Prerequisites

- **Python 3.10 or newer** on Windows (tkinter ships with the standard python.org installer).
- **Python packages:** `pip install sounddevice numpy faster-whisper keyboard`
- **A microphone.** Since no commentary is recorded during capture, your normal mic is fine; nothing competes for it.
- **GPU is optional.** The daemon tries CUDA at launch and falls back to CPU automatically if the GPU libraries are not present. `small.en` on CPU transcribes a short note in roughly one to three seconds, which is fine. For the sub-second GPU path, install the two NVIDIA runtime wheels: `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`. The daemon adds their DLL folders to its search path on the next launch and uses the GPU. No full CUDA Toolkit install is needed.
- **First run downloads the model** (`small.en`, a few hundred MB) to the local cache. One time, needs internet.

## Step 1: Replace the OBS Lua

1. Back up your current `make_postprocess_bat.lua`.
2. Replace it with the `make_postprocess_bat.lua` from this delivery, at the same path OBS already loads it from (this preserves your saved settings).
3. In OBS, open **Tools, Scripts**, select the script, and set **Note Tool Folder** to `N:\Recordings`. Your other settings are untouched.
4. Switch scenes once to confirm. A `.current_game` file should appear in `N:\Recordings` containing the cleaned game name. Start a recording and a `.current_session` file should appear with a `YYYY-MM-DD_HH-MM-SS` timestamp.

The Lua now writes these exports on scene change, on recording start, and on script load. The existing rename-bat behavior is unchanged.

## Step 2: Install Python packages

```
pip install sounddevice numpy faster-whisper keyboard
```

## Step 3: Configure the daemon

Open `gamenote_daemon.py` and check the config block at the top. The ones that matter:

- **`RECORDINGS_ROOT`**, defaults to `N:\Recordings`. Must match the Note Tool Folder you set in OBS.
- **`HOTKEY`**, defaults to `ctrl+alt+n`. Pick a combo no game uses.
- **`MODE`**, `vad` (press, speak, auto-stops on silence) or `toggle` (press to start, press again to stop). Default is `vad`.
- **`INPUT_DEVICE`**, `None` uses the system default mic. To pick a specific device, run `python -c "import sounddevice; print(sounddevice.query_devices())"` and set this to the device index or a substring of its name.
- **`SILENCE_THRESHOLD`**, the RMS level below which audio counts as silence. The default `0.006` suits a typical quiet setup, but tune it (Step 4).

## Step 4: First run and silence calibration

Run it from a terminal the first time so you can see what it is doing and tune the threshold:

1. Set `DEBUG = True` near the top of `gamenote_daemon.py`.
2. Run `python gamenote_daemon.py`. Wait for the "Listening for hotkey" line.
3. Press your hotkey, stay quiet for a second, then speak a test note, then stop.
4. Watch the printed `rms=` values. Silence sits at one level, your voice at a clearly higher one. Set **`SILENCE_THRESHOLD`** between the two (closer to the silence floor, with a small margin).
5. Set `DEBUG = False` again once it feels right.

If notes cut off mid-sentence, raise `SILENCE_SECONDS`. If an accidental press records for too long, lower `START_GRACE_SECONDS`.

## Step 5: Autostart the daemon (windowless)

Run it with `pythonw` so there is no console window:

1. Press `Win + R`, type `shell:startup`, press Enter.
2. Create a shortcut in that folder with the target:
   `"C:\Path\To\pythonw.exe" "C:\Path\To\gamenote_daemon.py"`
3. It now launches on login and runs in the background. The single-instance guard stops a second copy from starting.

Check `gamenote.log` (next to the script) if you ever need to see what it did.

## Step 6: Bind the Stream Deck key

1. In the Stream Deck software, drag a **System, Hotkey** action onto a key.
2. Set its hotkey to the same combo as `HOTKEY` (default `Ctrl + Alt + N`).
3. Pressing the key now sends that keystroke, which the daemon catches. The key only injects a keystroke, so no window appears and focus does not change.

## Using it

1. While recording, press the key.
2. The overlay shows "listening". Speak your note.
3. Stop talking. After a short silence it transcribes and the overlay shows "saved" with the first words. (In `toggle` mode, press the key again to stop.)
4. The note is appended to `N:\Recordings\<Game>\<Game>_notes.md`.

A second press while it is still listening force-stops the current note immediately.

## What a notes file looks like

```
# Disco Elysium notes

## Recording session: 2026-05-31_14-02-10

- [2026-05-31 14:08:22] the thought cabinet payoff lands here, callback to the cold open
- [2026-05-31 14:21:05] note the skill check failure framing, useful for the determinism point

## Recording session: 2026-06-02_19-40-55

- [2026-06-02 19:55:13] revisit this dialogue tree for the Camus angle
```

One file per game, appended across every session. A `## Recording session:` header marks each session for navigation; every note also carries a full timestamp so it stands on its own.

## Aligning a note to the footage

Note timestamps and OBS filename timestamps come from the same PC clock, so they line up directly with no drift.

- A note at `14:08:22` belongs to whichever recording file in that game folder has the latest start timestamp at or before `14:08:22`.
- The offset into that file is the note time minus the file's start timestamp (the `YYYY-MM-DD_HH-MM-SS` part of the filename, which your rename script preserves and only prefixes with the game name).
- This holds across your hourly splits, because each split file is named with its own start time.

## Troubleshooting

- **Hotkey does nothing while the game is focused.** If you run the game as administrator, the daemon must also run as administrator to receive input while the game is in front. Run both at the same elevation. Also prefer borderless windowed over exclusive fullscreen, which is more reliable for both the hotkey and the overlay.
- **Overlay never appears.** The daemon still works; the overlay is best-effort. Check `gamenote.log`. You can also set `SHOW_OVERLAY = False` if you would rather not use it.
- **Wrong or missing game name.** Confirm `.current_game` exists in `N:\Recordings` and holds the expected name. If it is missing, switch scenes once or restart the OBS script. Notes captured with no game value land under `N:\Recordings\_Unsorted`.
- **Transcription is slow, or you want the GPU.** The daemon falls back to CPU whenever the GPU libraries are missing (the log will say "GPU path unavailable ... Falling back to CPU"). To use the GPU, install `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` and relaunch; the log should then say "Loaded model 'small.en' on CUDA". You can also drop to a smaller model with `MODEL_SIZE = "base.en"` if CPU speed matters and you would rather not set up the GPU.
- **Notes feel inaccurate.** Raise `BEAM_SIZE` to `5` for better accuracy at a small speed cost.
- **Writes to the NAS occasionally hiccup.** OBS already writes recordings to `N:\Recordings` over the network during capture, so this path is the same one your captures rely on. If a write ever fails, the error is logged and the next note proceeds normally.
