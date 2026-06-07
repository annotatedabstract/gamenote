# OBS session integration (optional)

By default gamenote stamps each `## Recording session:` header with the date. If
you record with OBS and want the header to carry the recording's start time
instead (so notes group by recording session, the legacy behavior), use this.

## What it does

`gamenote-session.lua` writes one file when OBS starts recording:

```
<Session folder>\.current_session   ->   2026-05-31_14-02-10
```

gamenote reads that value for the session header, and writes a new header only
when it changes (that is, when a new recording starts). If the file is missing or
empty, gamenote falls back to the date, so nothing breaks when OBS is not running.

## Setup

1. In OBS: Tools, Scripts, add `gamenote-session.lua`. Set "Session folder" to a
   folder gamenote can read (for example `N:\Recordings`).
2. In gamenote: open Settings, pick the profile, and under session headers:
   - tick "Write session headers"
   - tick "Read session value from a file (legacy OBS .current_session)"
   - set "Session file" to `<that folder>\.current_session`
3. Start recording in OBS. The next note filed by that profile gets a header like
   `## Recording session: 2026-05-31_14-02-10`.

This is per profile, so point each profile that should use it at the same file.

## Notes

- This script only writes `.current_session`. It does not set the game name; for
  that, a profile can read its context from a file (Settings, Context, "Read
  context from a file"), pointed at a `.current_game` file.
- The full original workflow script (which also creates per-recording rename
  `.bat` files and `.current_game`) is a separate, personal script and is not
  shipped here.
