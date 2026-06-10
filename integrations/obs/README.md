# OBS integration (optional)

gamenote works fine on its own. If you record with OBS, this small script lets
gamenote enrich notes with recording info: the recording's start time (for the
`## Recording session:` header) and **how far into the current recording each
note is** (the `{clip}` prefix token, e.g. `[06:12]`). The `file_path` field
also feeds a `### Recording file:` sub-header in the notes, naming the file
each `{clip}` offset refers to — useful with OBS automatic file splitting.

## What it does

`gamenote-obs.lua` writes a single JSON file into the chosen folder while you
record:

```jsonc
// <folder>\gamenote-obs.json
{
  "game":          "Disco Elysium",          // the active scene name
  "session_start": "2026-06-08_14-02-10",     // when recording started
  "file_start":    "2026-06-08_14-16-55",     // when the CURRENT file began
  "file_path":     "N:\\Recordings\\dE_2.mkv",// the current recording file
  "recording":     true                        // false once recording stops
}
```

`file_start` is what makes the `{clip}` offset work even with OBS **automatic
file splitting**: the script re-stamps it on OBS's `file_changed` signal every
time a split rolls over to a new file, so the offset is measured from the start
of the *current* file, not the whole session. (This is why session start alone
isn't enough.)

**Requires OBS 28 or newer** for the `file_changed` signal. On older OBS the
session header still works, but `{clip}` won't reset across splits.

## Setup

1. **OBS:** Tools → Scripts → add `gamenote-obs.lua`. Set "Folder for
   gamenote-obs.json" to a folder gamenote can read (e.g. `N:\Recordings`).
2. **gamenote:** open Settings → Profiles, pick a profile, tick **"Read OBS
   recording info from a file"**, and set "OBS file" to
   `<folder>\gamenote-obs.json`. That one option drives everything:
   - With **"Write session headers"** on, the `## Recording session:` header
     carries the recording's start time, and a `### Recording file:` sub-header
     names the current recording file.
   - Put `{clip}` in the **Line prefix** (e.g. `[{clip}] `) to stamp each note's
     position in the recording.
   - **Game as context (optional):** tick **"Also read {context} (the game)
     from this file"** to make this profile's `{context}` follow the OBS scene
     name, overriding the global context (the tray's "Set context" keeps
     driving the other profiles). To have *every* profile follow OBS instead,
     use the global option: Settings → Context → "Read context from a file",
     pointed at the same `<folder>\gamenote-obs.json`.
3. Start recording in OBS. Notes filed by that profile now carry the session
   header with the recording's start time, a `[mm:ss]` recording position (if
   `{clip}` is in the prefix), and a `### Recording file:` sub-header naming
   the current recording file (written when the file changes, e.g. on an OBS
   split). When you're not recording (or the file is missing), gamenote falls
   back gracefully: the header uses the date, `{clip}` is omitted (its empty
   `[]` is tidied away), and the sub-header is skipped — likewise when OBS
   hasn't reported the file path yet (it appears at the next split).

## Older setups

Versions before 1.4.0 had a separate per-profile "Session file" option that
could read a plain-text `.current_session` file. That option is gone: the
session header now comes from this script's `gamenote-obs.json` automatically
whenever "Read OBS recording info from a file" (previously called "Stamp
recording position from an OBS file") is on. If you used the old option,
just point "OBS file" at `<folder>\gamenote-obs.json`.

Context-from-file is unchanged and still accepts a plain-text file (e.g. a
legacy `.current_game`) as well as this JSON.

## Maintaining your own workflow script

If you run a fuller personal OBS script (e.g. one that also writes rename `.bat`
files), you don't need a second script — just write the same JSON from yours.
The minimal pieces:

```lua
-- once: connect file_changed on RECORDING_STARTED so splits re-stamp file_start
local sh = obs.obs_output_get_signal_handler(obs.obs_frontend_get_recording_output())
obs.signal_handler_connect(sh, "file_changed", function(cd)
  state.file_start = os.date("%Y-%m-%d_%H-%M-%S")
  state.file_path  = obs.calldata_string(cd, "next_file")
  write_gamenote_obs_json()   -- serialize game/session_start/file_start/file_path/recording
end)

-- write the JSON (obs_data handles escaping of backslash paths):
local d = obs.obs_data_create()
obs.obs_data_set_string(d, "game", game_name)
obs.obs_data_set_string(d, "session_start", session_start)
obs.obs_data_set_string(d, "file_start", file_start)
obs.obs_data_set_string(d, "file_path", file_path)
obs.obs_data_set_bool(d, "recording", true)   -- false on RECORDING_STOPPED
local json = obs.obs_data_get_json(d)
obs.obs_data_release(d)
-- io.open(folder .. "\\gamenote-obs.json", "w"):write(json)
```

Timestamps must be `YYYY-MM-DD_HH-MM-SS` (gamenote also accepts ISO
`YYYY-MM-DDTHH:MM:SS`). See `gamenote-obs.lua` in this folder for the complete,
ready-to-use version.
