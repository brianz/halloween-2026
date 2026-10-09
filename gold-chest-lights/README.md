# Gold Chest Lights

Slow, warm amber-gold "breathing" pulse on a WS2812B strip hidden at the
bottom of the treasure chest prop, under the fake jewels/gold coins.

ESP32-WROOM-32 dev board, MicroPython, no Arduino IDE. Fully CLI-driven.

## Wiring

- Strip **+** and **GND** → ESP32 5V and GND.
- Strip **data** → an ESP32 GPIO (currently **GPIO 5**). It's just a
  constant (`DATA_PIN` at the top of `main.py`) — change it and re-upload
  if the wiring ever changes. Don't trust a schematic read alone; if the
  strip doesn't light, use `pin_sweep.py` (below) to find the real pin.
- Also set `NUM_LEDS` in `main.py` to the actual LED count on your strip
  (currently **150**).
- The strip is 5V — **never power it from anything higher** (a 12V supply
  killed an earlier strip: the first few WS2812 chips died into a stuck,
  data-independent color and blocked everything downstream of them, which
  looked identical to a wiring/pin problem until traced back to the
  overvoltage).

## One-time setup

Tools (`esptool`, `mpremote`) are declared in the **root**
`../pyproject.toml` and live in the shared `../.venv`, activated
automatically by direnv — see `CLAUDE.md` in this directory. Nothing to
install here.

1. Plug in the ESP32 via USB and find its serial port:
   ```bash
   ls /dev/cu.*
   ```
   Look for something like `/dev/cu.usbserial-XXXX` (appears only while
   the board is plugged in).
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

## If the strip doesn't light (or only partially lights)

`pin_sweep.py` drives every plausible GPIO high/low in turn, printing
each one, so you can watch the strip and find which pin (if any) is
actually wired to DIN:

```bash
mpremote connect /dev/cu.usbserial-XXXX sleep 3 run pin_sweep.py
```

If **no** pin does anything — even with the data wire physically
unplugged from the ESP32 giving the identical result — the problem isn't
the pin or the code, it's the strip or its wiring. Check for overvoltage
history first (see Wiring above); a dead first LED blocks the whole
chain and looks exactly like "nothing is connected."
