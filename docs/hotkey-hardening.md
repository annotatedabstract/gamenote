# Hotkey hardening: failure modes of the `keyboard` library and the native alternative

Maintainer note, 2026-07-06 (v1.5.0 investigation). Background: a user-visible
"alt+f1 stops responding, overlay and tray still fine" report was root-caused
to the `keyboard` library (0.13.5, unmaintained since 2020), not to gamenote's
own state. All four mechanisms below were verified against the library source;
1 and 2 were reproduced empirically by pushing synthetic events through the
real `direct_callback` with the OS hook stubbed.

## Failure mechanisms

1. **Callback exception kills the processing thread.** Every registered
   callback runs on the library's single processing thread via
   `pre_process_event`, which has no try/except (only `invoke_handlers`,
   a different path, has one). One escaping exception ends that thread
   permanently. The traceback goes to stderr — invisible under
   pythonw/frozen builds — and nothing reaches gamenote.log; `HotkeyManager`
   still looks healthy.
2. **Stale `_pressed_events` entry breaks matching for all hotkeys.** Hotkey
   matching compares against the live set of pressed keys. A key-up swallowed
   by the lock screen, the UAC secure desktop, or an elevated window keeps
   that key "pressed" forever, so no hotkey tuple ever matches again — single
   keys (f13–f15) included. Self-heals only if the stuck key is pressed again.
3. **Matching reads live state, not a per-event snapshot.** A fast tap can be
   released before the processing thread handles the press (e.g. while
   transcription holds the GIL), so the press never matches.
4. **Windows silently removes a timed-out `WH_KEYBOARD_LL` hook** (Win8+),
   and UIPI blocks the unelevated hook while an elevated window has focus.
   The hook proc is Python-under-GIL for every system-wide keystroke, so
   whisper CPU bursts raise the timeout risk. Nothing in-process observes the
   removal: both library threads stay alive.

The library cannot recover from any of these: `start_if_necessary` never
restarts anything once `listening` is `True`; pause/resume and re-registering
do not re-install the hook or revive the thread.

## What ships now (stages 1 + 2)

- `build_mapping` wraps every callback in try/except with `log.exception`, so
  no exception of ours — or of Qt's signal emission — can reach the
  processing thread. Kills mechanism 1 at the source and finally makes such
  failures visible in gamenote.log.
- `ListenerWatchdog` (60 s QTimer in `app.py`) checks the library's
  `listening_thread`/`processing_thread`; if one died it recreates the
  module-global listener, clears the stale pressed-key state (mechanism 2, as
  far as it accompanies a recovery), and re-binds the mapping through
  `HotkeyManager`. Registering against the fresh listener installs a new OS
  hook, which also covers a dead hook *pump*. If recovery fails, a tray
  balloon asks for a restart — once. All keyboard-internals access is
  defensive, so a future library version degrades the watchdog to a no-op.

Residual gaps: mechanism 2 outside a thread death (stuck key while everything
runs), mechanism 3 (inherent to the matching design), and mechanism 4 (both
threads stay alive, so the watchdog has nothing to observe; probing would mean
injecting synthetic keystrokes system-wide, which is not acceptable next to
games).

## Evaluated: native `RegisterHotKey`/`WM_HOTKEY` backend

**Verdict: recommended as the structural fix, not implemented yet.** A
Windows-native backend eliminates all four mechanisms at once:

- `RegisterHotKey` makes the OS do the matching — no LL hook, no Python in
  the keystroke path, no GIL sensitivity, no pressed-state machine, no
  processing thread to die. `WM_HOTKEY` arrives on a plain message loop.
- Registration failures are *synchronous and diagnosable* (`GetLastError`,
  including "hotkey already taken by another app", which today surfaces as
  nothing at all).
- The message-loop thread is ours: trivial to supervise, and there is nothing
  Windows silently unhooks.

Fit with gamenote's UX: hotkeys are single keys (f13–f15) or simple
modifier+key combos (alt+f1) — exactly the `MOD_*` + VK shape `RegisterHotKey`
supports. The one behavioral change: a registered combo is consumed
system-wide (the game no longer sees the keypress), where the keyboard lib
with `suppress=False` passed it through. For gamenote's dedicated-hotkey use
this is acceptable, arguably desirable.

Implementation sketch (moderate effort, ~200 lines + tests):

- A dedicated thread owning `RegisterHotKey`/`GetMessage`; both register and
  unregister must run on that thread, so register/unregister requests are
  posted to it (`PostThreadMessage` with `WM_APP`+n, or re-registering from a
  queue after a custom wake message). `WM_HOTKEY` → the existing queued Qt
  signal, same as today.
- A small parser mapping the config's keyboard-lib names ("f13", "alt+f1") to
  `MOD_ALT|MOD_CONTROL|MOD_SHIFT|MOD_WIN` + a virtual-key code, with
  `MOD_NOREPEAT` to suppress auto-repeat. Existing configs keep working;
  unmappable exotic names (multi-step hotkeys, mouse buttons) fail validation
  visibly instead of binding flakily.
- `HotkeyManager`'s public surface (register/set_mapping/pause/resume/rebind)
  stays; only the backend changes, so tray/settings/watchdog wiring is
  untouched. The watchdog shrinks to supervising our own thread.
- Windows-only: keep the `keyboard` backend as the non-Windows/dev fallback
  (the rest of the app already has such platform splits), or drop non-Windows
  support outright.
- Cost: elevated games still eat hotkeys unless gamenote runs elevated
  (unchanged — that is UIPI, not a library issue), and `RegisterHotKey` fails
  if another app owns the combo (today it would silently never fire; failing
  loudly is an improvement).

Suggested trigger for doing it: the next hotkey-reliability report that the
stage-1/2 hardening does not explain, or the next planned feature touching
`hotkeys.py`.
