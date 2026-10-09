# Gold Chest Lights

ESP32-WROOM-32 + WS2812B strip, MicroPython, slow warm-gold breathing pulse
for a treasure chest prop. See `README.md` in this directory for wiring and
full setup/upload steps. This file is about the dev environment only.

## Environment — shared root venv, not a venv in this directory

This subproject has **no venv or pyproject.toml of its own**. It uses the
same `.venv` as the rest of the `halloween-pirates` repo, one level up at
`/Users/brianz/dev/halloween-pirates/.venv`:

- `esptool` and `mpremote` are declared as dependencies in the **root**
  `../pyproject.toml` (added via `uv add esptool` / `uv add mpremote`,
  run from the repo root, not from here).
- The root `.envrc` + `direnv` activates `../.venv` automatically on `cd`
  into the repo (same mechanism the pirate-kiosk project already uses) —
  so `esptool` and `mpremote` are just on `PATH` with no manual `source
  activate` step, as long as direnv has run.
- To add any future Python dependency for this prop (e.g. a flashing
  helper), run `uv add <pkg>` from the **repo root**
  (`/Users/brianz/dev/halloween-pirates`), not from `gold-chest-lights/`.
- This is a MicroPython project — `main.py` in this directory runs *on the
  ESP32 itself*, not in the venv. The venv only hosts the CLI tools
  (`esptool`, `mpremote`) used from the laptop to flash/upload to the
  board.

## Quick sanity check

```bash
cd /Users/brianz/dev/halloween-pirates   # direnv activates ../.venv
which esptool mpremote                    # should resolve inside .venv/bin
ls /dev/cu.*                               # board's serial port, only
                                            # appears while plugged in
```

## Gotchas learned the hard way

- **Every `mpremote` command needs a `sleep 3` between `connect` and the
  actual command**, e.g. `mpremote connect /dev/cu.usbserial-XXXX sleep 3
  exec "..."`. Opening the port toggles DTR/RTS, which resets the board
  (EN pin); without the delay, mpremote's raw-REPL handshake races the
  boot banner and fails with `could not enter raw repl`. This bit us on
  every single command during setup until we added the sleep.
- The MicroPython firmware `.bin` lives in `.fw/` (gitignored) — it's a
  downloaded artifact, re-fetch from
  https://micropython.org/download/ESP32_GENERIC/ rather than committing
  it.
- `pin_sweep.py` exists because a GPIO guessed from eyeballing a schematic
  against a breadboard photo turned out wrong twice. Don't trust a visual
  pin ID for wiring you haven't verified in code — sweep and watch.
- A WS2812B strip once got a 12V supply instead of 5V. Symptom: the first
  few LEDs locked into a fixed color (red) completely independent of any
  GPIO, pin, or even having the data wire connected at all — which looks
  identical to "nothing is wired up" and cost a long debugging session
  before the overvoltage history came up. Ask about power supply history
  early if a strip is totally unresponsive to every pin.
