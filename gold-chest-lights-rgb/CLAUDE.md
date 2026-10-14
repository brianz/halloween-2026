# Gold Chest Lights — RGB (4-wire) variant

ESP32-WROOM-32 + 5V analog RGB strip (4 wires: +5V, R, G, B — PWM-dimmed
through MOSFETs, no onboard pixel chip), MicroPython, same slow warm-gold
breathing pulse as `../gold-chest-lights` but for a second treasure chest
prop on a separate ESP32 board. See `README.md` in this directory for
wiring and full setup/upload steps. This file is about the dev
environment only.

## Keep this in sync with ../gold-chest-lights

Same visual effect, different strip hardware and GPIO role (PWM duty
cycle on 3 channels here vs. NeoPixel data-out there). If you retune
`GOLD` / `MIN_BRIGHTNESS` / `MAX_BRIGHTNESS` / `PULSE_PERIOD_S` /
`STEPS_PER_PERIOD` in one `main.py`, mirror the same values in the other
so the two chests breathe identically.

## Environment — shared root venv, not a venv in this directory

This subproject has **no venv or pyproject.toml of its own**. It uses the
same `.venv` as the rest of the `halloween-pirates` repo, one level up at
`/Users/brianz/dev/halloween-pirates/.venv` — identical setup to
`../gold-chest-lights` (see that directory's `CLAUDE.md` for the full
rationale):

- `esptool` and `mpremote` are already declared as dependencies in the
  **root** `../pyproject.toml`. Nothing new to add for this board.
- The root `.envrc` + `direnv` activates `../.venv` automatically on `cd`
  into the repo, so `esptool` and `mpremote` are just on `PATH`.
- This is a MicroPython project — `main.py` in this directory runs *on
  this board's ESP32*, not in the venv. The venv only hosts the CLI tools
  used from the laptop to flash/upload.

## Quick sanity check

```bash
cd /Users/brianz/dev/halloween-pirates   # direnv activates ../.venv
which esptool mpremote                    # should resolve inside .venv/bin
ls /dev/cu.*                               # both boards' serial ports, only
                                            # appear while plugged in
```

## Gotchas learned the hard way (carried over from ../gold-chest-lights)

- **Every `mpremote` command needs a `sleep 3` between `connect` and the
  actual command** — opening the port resets the board (EN pin via
  DTR/RTS) and the raw-REPL handshake races the boot banner without the
  delay.
- The MicroPython firmware `.bin` is a downloaded artifact — don't commit
  it, re-fetch from https://micropython.org/download/ESP32_GENERIC/.
- Don't trust a visual pin ID for wiring you haven't verified in code —
  `pin_sweep.py` exists because of exactly that mistake on the other
  chest.
- Two ESP32 boards plugged in at once means two `/dev/cu.*` entries —
  double-check which port you're targeting before flashing/uploading so
  you don't overwrite the wrong board's `main.py`.

## New gotcha specific to this (PWM/MOSFET) variant

- A 4-wire strip has **no data protocol** — unlike the WS2812B strip's
  single GPIO driving hundreds of addressable pixels over one data line,
  each color channel here is a plain PWM-dimmed power line and needs its
  own GPIO *and* its own MOSFET to handle the current. Confirm MOSFET
  gate wiring (gate → GPIO, source → GND, drain → strip channel) before
  assuming a code or pin problem.
