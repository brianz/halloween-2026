# Gold Chest Lights — DotStar variant

Same slow, warm amber-gold "breathing" pulse as `../gold-chest-lights`,
but for a second treasure chest prop built with an [Adafruit DotStar
(APA102) strip](https://www.adafruit.com/product/2239) — 144 LED/m, one
meter, white PCB — instead of a WS2812B strip. Runs on its own separate
ESP32-WROOM-32 board. MicroPython, no Arduino IDE, fully CLI-driven.

If you retune the pulse's look (color, brightness range, speed), change
it in both `main.py` here and `../gold-chest-lights/main.py` so the two
chests stay in sync.

## Why this isn't the same code as ../gold-chest-lights or a PWM/RGB strip

DotStar is addressable, like WS2812B — one GPIO can drive hundreds of
individually-settable pixels — but instead of WS2812B's single
self-clocked data line, APA102 (the chip DotStar is built on) uses two
wires: a data line and a separate clock line, much like SPI. That means:

- No MOSFETs or per-channel GPIOs needed (unlike a plain analog 4-wire
  RGB strip) — this is a direct logic-level digital connection, same
  category as the WS2812B strip, just two wires instead of one.
- MicroPython's built-in `neopixel` module doesn't speak this protocol,
  so `main.py` talks to the strip directly over `machine.SPI`, building
  the APA102 frame format (start frame, one 4-byte frame per LED, end
  frame) by hand.

## Wiring

The strip has a 4-pin JST SM connector on each end, labeled on the flex
PCB itself: **5V, GND, DI (data in), CI (clock in)**.

- Strip **5V** → a 5V supply, and strip **GND** → that supply's GND, tied
  together with the ESP32's GND. **Never exceed 6V** — Adafruit's own
  spec for this strip says a higher voltage can destroy the whole run of
  LED driver chips, not just the first one.
  - For a single meter, Adafruit's 5V/4A adapter (wired in via a 2.1mm DC
    jack) is their suggested supply; don't try to run a full meter off
    the ESP32's own 5V pin.
- Strip **DI** → ESP32 **GPIO 23** (`MOSI_PIN` in `main.py`).
- Strip **CI** → ESP32 **GPIO 18** (`SCK_PIN` in `main.py`).
- GPIO 23/18 are the ESP32's default hardware VSPI pins, chosen so
  `main.py` can use `machine.SPI` (hardware-accelerated) instead of a
  slower bit-banged software SPI.
- `machine.SPI` also wants a MISO pin to construct the bus (`MISO_PIN` =
  **GPIO 19**) even though this strip has no data-out wire to send
  anything back on — leave it unconnected, it's only there to satisfy the
  constructor.
- For a short run (around a meter, like this one) at 3.3V logic level
  into a 5V strip, direct GPIO connection is normally reliable. If pixels
  flicker, show wrong colors, or only the first few respond correctly,
  that's a classic symptom of a marginal logic-level signal — add a logic
  level shifter (e.g. 74AHCT125) on DI and CI before assuming a code bug.
- Also set `NUM_LEDS` in `main.py` to the actual LED count on your strip
  (currently **144**, the uncut one-meter length). The strip has cut
  lines every LED if you need to shorten it — recount and update
  `NUM_LEDS` if you do.

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

## If the strip doesn't light (or looks wrong)

`spi_check.py` cycles the whole strip through red/green/blue/white/off so
you can confirm the SPI link and strip work independent of the breathing
logic:

```bash
mpremote connect /dev/cu.usbserial-XXXX sleep 3 run spi_check.py
```

If **no** color does anything, this is a two-wire digital protocol with
both wires already labeled on the strip's PCB — there's no GPIO to sweep
the way `pin_sweep.py` does for the other two chests. Check, in order:
shared ground between the ESP32 and the strip's power supply, DI → GPIO
23, CI → GPIO 18, and that the strip hasn't seen more than 6V.
