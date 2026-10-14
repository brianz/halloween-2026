# Gold Chest Lights — DotStar variant

ESP32-WROOM-32 + Adafruit DotStar (APA102) strip (144 LED/m, 4 wires: 5V,
GND, DI, CI — addressable, data+clock over SPI, no onboard analog PWM
channels), MicroPython, same slow warm-gold breathing pulse as
`../gold-chest-lights` but for a second treasure chest prop on a separate
ESP32 board. See `README.md` in this directory for wiring and full
setup/upload steps. This file is about the dev environment only.

## Keep this in sync with ../gold-chest-lights

Same visual effect, different strip hardware and GPIO role (hand-rolled
APA102 frames over `machine.SPI` here vs. the built-in `neopixel` module
there). If you retune `GOLD` / `MIN_BRIGHTNESS` / `MAX_BRIGHTNESS` /
`PULSE_PERIOD_S` / `STEPS_PER_PERIOD` in one `main.py`, mirror the same
values in the other so the two chests breathe identically.

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
- Two ESP32 boards plugged in at once means two `/dev/cu.*` entries —
  double-check which port you're targeting before flashing/uploading so
  you don't overwrite the wrong board's `main.py`.

## New gotchas specific to this (DotStar/APA102) variant

- Don't assume this is "the same as the RGB strip wiring" or "the same
  as the WS2812B strip wiring" — it's neither. There's no MOSFET/PWM
  layer (this is a direct digital logic signal like WS2812B) but it's
  two wires, not one (data + clock, more like SPI), and MicroPython has
  no built-in driver for it the way it does for WS2812B's `neopixel`
  module — `main.py` builds APA102's start-frame/pixel-frame/end-frame
  byte layout by hand over `machine.SPI`.
- `machine.SPI()` on ESP32 requires a `miso` pin argument to construct
  the bus even though this one-directional link never reads anything —
  `MISO_PIN` in `main.py` is a throwaway GPIO, not a real wire.
- Never exceed 6V on this strip (Adafruit's own spec) — don't assume the
  12V-strip overvoltage gotcha from `../gold-chest-lights/CLAUDE.md`
  doesn't apply just because this is "a different strip"; the failure
  mode (dead driver chips that block everything downstream, looking
  identical to zero wiring) is the same risk, just at a lower voltage
  threshold.
- The product listing's "144 LED/m" figure wasn't the real count: this
  strip actually has **288 LEDs**. With `NUM_LEDS` set too low, only the
  first half of the strip lit — a wrong-but-plausible-looking result
  (not a dead strip, not a wiring fault), because the end frame still
  clocks out *something*, just not enough to latch every pixel. Don't
  trust a datasheet/listing LED count — verify by watching the physical
  strip when `NUM_LEDS` is suspect.
