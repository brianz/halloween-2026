# Gold Chest Lights

Slow, warm yellow/gold "breathing" pulse on a WS2812B strip hidden at the
bottom of the treasure chest prop, under the fake jewels/gold coins.

ESP32-WROOM-32 dev board, MicroPython, no Arduino IDE. Fully CLI-driven.

## Wiring

- Strip **+** and **GND** → ESP32 5V and GND (the "positive 6 / negative 11"
  rows from the breadboard — those are power, not GPIO, so they don't show
  up in code).
- Strip **data** → an ESP32 GPIO. `main.py` currently guesses **GPIO 15**
  since that's closest to what you described, but it's just a constant
  (`DATA_PIN` at the top of `main.py`) — change it to whatever GPIO the
  data wire is actually on and re-upload.
- Also set `NUM_LEDS` in `main.py` to the actual LED count on your strip.

## One-time setup (not done yet — nothing has been installed)

1. Install the two small CLI tools needed to talk to the board:
   ```bash
   uv tool install esptool
   uv tool install mpremote
   ```
2. Plug in the ESP32 via USB and find its serial port:
   ```bash
   ls /dev/cu.*
   ```
   Look for something like `/dev/cu.usbserial-XXXX` or
   `/dev/cu.SLAB_USBtoUART` (appears only while the board is plugged in).
3. Erase the flash and install MicroPython firmware (one-time; download the
   latest ESP32 `.bin` from https://micropython.org/download/ESP32_GENERIC/
   first):
   ```bash
   esptool --port /dev/cu.usbserial-XXXX erase-flash
   esptool --port /dev/cu.usbserial-XXXX write-flash -z 0x1000 ESP32_GENERIC-*.bin
   ```

## Upload and run

```bash
mpremote connect /dev/cu.usbserial-XXXX cp main.py :main.py
mpremote connect /dev/cu.usbserial-XXXX reset
```

`main.py` on the board auto-runs on boot/reset, so the pulse starts as
soon as the chest is powered on — no laptop needed afterward.

To iterate without re-flashing: edit `main.py` locally, re-run the `cp`
command above, then `reset`.

To watch it live / stop it:
```bash
mpremote connect /dev/cu.usbserial-XXXX run main.py
```
(Ctrl-C stops the pulse and turns the strip off.)
