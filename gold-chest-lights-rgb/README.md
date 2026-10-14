# Gold Chest Lights — RGB (4-wire) variant

Same slow, warm amber-gold "breathing" pulse as `../gold-chest-lights`, but
for a second treasure chest prop built with a 5V analog RGB strip (4 wires:
+5V, R, G, B — no onboard pixel chip) instead of a WS2812B strip. Runs on
its own separate ESP32-WROOM-32 board. MicroPython, no Arduino IDE, fully
CLI-driven.

If you retune the pulse's look (color, brightness range, speed), change it
in both `main.py` here and `../gold-chest-lights/main.py` so the two chests
stay in sync.

## Wiring

A 4-wire RGB strip has no data protocol — each color channel is just a
PWM-dimmable power line. The ESP32 GPIOs can't sink that current directly,
so each channel goes through its own N-channel MOSFET (e.g. AO3400,
2N7000, or a 3-channel MOSFET driver breakout):

- Strip **+5V** → a 5V supply. For a short strip this can be the ESP32's
  own 5V pin; for anything longer, use a separate 5V PSU sized for the
  strip's total draw — **don't try to power the strip through the ESP32's
  5V pin for anything but a quick bench test.**
- Strip **GND**, PSU GND (if separate), and ESP32 GND all tied together —
  a MOSFET low-side switch only works with a shared ground.
- Strip **R** → MOSFET #1 drain; MOSFET #1 source → GND; MOSFET #1 gate →
  **GPIO 25**.
- Strip **G** → MOSFET #2 drain; MOSFET #2 source → GND; MOSFET #2 gate →
  **GPIO 26**.
- Strip **B** → MOSFET #3 drain; MOSFET #3 source → GND; MOSFET #3 gate →
  **GPIO 27**.
- These are constants (`RED_PIN` / `GREEN_PIN` / `BLUE_PIN` at the top of
  `main.py`) — change and re-upload if the wiring ever differs. Don't
  trust a schematic read alone; if a channel doesn't light, use
  `pin_sweep.py` (below) to find the real pin.
- The strip is 5V — **never power it from anything higher.** (A 12V
  supply killed a WS2812B strip on the other chest: see
  `../gold-chest-lights/README.md`'s wiring notes. Same risk applies
  here.)

## One-time setup

Tools (`esptool`, `mpremote`) are declared in the **root**
`../pyproject.toml` and live in the shared `../.venv`, activated
automatically by direnv — see `CLAUDE.md` in this directory. Nothing to
install here.

1. Plug in this board's ESP32 via USB and find its serial port:
   ```bash
   ls /dev/cu.*
   ```
   Look for something like `/dev/cu.usbserial-XXXX` (appears only while
   the board is plugged in). If both chest ESP32s are plugged in at once,
   confirm which port is *this* board before uploading — unplug the other
   board if unsure.
2. Erase the flash and install MicroPython firmware (one-time per board;
   download the latest ESP32 `.bin` from
   https://micropython.org/download/ESP32_GENERIC/ first):
   ```bash
   esptool --port /dev/cu.usbserial-XXXX erase-flash
   esptool --port /dev/cu.usbserial-XXXX write-flash -z 0x1000 ESP32_GENERIC-*.bin
   ```

## Upload and run

`mpremote` needs ~3 seconds after opening the port before it can enter
raw REPL — the board resets on connect (DTR/RTS toggling the EN pin) and
the handshake races the boot banner otherwise, failing with
`could not enter raw repl`. Always chain a `sleep 3`:

```bash
mpremote connect /dev/cu.usbserial-XXXX sleep 3 cp main.py :main.py
mpremote connect /dev/cu.usbserial-XXXX sleep 3 reset
```

`main.py` on the board auto-runs on boot/reset, so the pulse starts as
soon as the chest is powered on — no laptop needed afterward.

To iterate without re-flashing: edit `main.py` locally, re-run the `cp`
command above, then `reset`.

To watch it live / stop it:
```bash
mpremote connect /dev/cu.usbserial-XXXX sleep 3 run main.py
```
(Ctrl-C stops the pulse and turns the strip off.)

## If a channel doesn't light (or lights the wrong color)

`pin_sweep.py` drives every plausible GPIO high/low in turn, printing
each one, so you can watch the strip and find which pin actually drives
which MOSFET gate:

```bash
mpremote connect /dev/cu.usbserial-XXXX sleep 3 run pin_sweep.py
```

Watch *which color* lights up at each printed pin, not just whether
something lights up — a mismatched RED_PIN/GREEN_PIN/BLUE_PIN assignment
looks fine electrically but produces the wrong hues once `main.py` runs.

If **no** pin does anything — even with a MOSFET gate wire physically
unplugged giving the identical result — the problem isn't the pin or the
code, it's the strip, its power, or the MOSFET wiring. Check the shared
ground first (see Wiring above); a floating ground between the ESP32 and
the strip's power supply looks identical to "nothing is connected."
