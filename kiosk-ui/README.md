# kiosk-ui

A browser control panel for `../pirate_riddle_kiosk.py`, for running the
kiosk without a terminal: pick a riddle difficulty (1 easiest – 10
hardest), start a session, end it gracefully, or force-quit a wedged one.

SvelteKit + Svelte 5 + Tailwind CSS. The whole thing is server-side process
management — `src/lib/server/kiosk.ts` spawns the Python script as a child
process and tracks exactly one running session at a time, matching the
project's own "one process per kid" design (see the root `CLAUDE.md`). No
database, no auth — it's a local tool for one operator on one laptop.

## Running it

```bash
npm install        # first time only
npm run dev -- --open
```

Or from the repo root: `just ui` (after the one-time `npm install`).

This starts a local dev server (usually `http://localhost:5173`) and opens
it in your browser. Leave the terminal running alongside it — closing it
(Ctrl-C) kills any session still in progress rather than orphaning it.

## What the buttons do

- **Start** — spawns `.venv/bin/python pirate_riddle_kiosk.py --difficulty
  N` for the difficulty you picked (`-u` for unbuffered output, so the log
  streams live instead of appearing in one dump at exit).
- **End Gracefully** — sends `SIGINT` to that process. This is *exactly*
  what Ctrl-C does in a terminal; the script's own shutdown handling
  (`except KeyboardInterrupt`, `watch_for_game_end`'s fallback,
  `end_session_or_die`'s hard timeout) takes it from there.
- **Force Quit** — sends `SIGKILL`. Strictly more forceful than the
  `ctrl-z && kill %1` you'd do by hand in a terminal.

The log panel tails the child process's stdout/stderr, polled once a
second — not a websocket, just `fetch()` on `GET /api/status`.

## Gotchas

- **Difficulty 1-10 maps onto `RIDDLE_POOL` one riddle per level** — see
  the comment above `RIDDLE_POOL` in `pirate_riddle_kiosk.py`. The
  difficulty ratings there are a first guess, not measured from real kids;
  expect to reorder them.
- **macOS microphone permission (TCC) is tied to the process that first
  requests it.** The first time you start a session through this UI (as
  opposed to running the script directly from a terminal), macOS may
  prompt for mic access again for this new parent process.
- **Editing `src/lib/server/kiosk.ts` while a game is running loses track
  of it** — Vite's dev-server hot-reload re-evaluates the module, resetting
  its in-memory state, but the actual OS process keeps running orphaned.
  Recover with `just kill-riddle-kiosk` (from the repo root) or Activity
  Monitor; don't edit this file mid-session.
- Only one session is tracked at a time by design. Starting a second one
  while the first is still running is rejected (`{ ok: false, error: "A
  session is already running." }`), matching the real constraint that only
  one kid is at the kiosk at once.
