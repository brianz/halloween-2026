"""Treasure chest gold pulse — MicroPython, DotStar (APA102) strip variant.

Slowly breathes a warm gold/yellow across an Adafruit DotStar (APA102)
strip — addressable like the WS2812B strip in ../gold-chest-lights, but
clocked over a separate data+clock pair instead of a single self-timed
data line. Runs on its own ESP32-WROOM-32 board. Same breathing effect as
../gold-chest-lights — if you retune the look, change GOLD /
MIN_BRIGHTNESS / MAX_BRIGHTNESS / PULSE_PERIOD_S / STEPS_PER_PERIOD here
AND there so the two chests match.

MicroPython has a built-in `neopixel` module but no built-in APA102
driver, so this talks APA102 directly over hardware SPI: a start frame
(32 zero bits), one 32-bit frame per LED (header byte + B, G, R — note
the byte order), then an end frame of enough 0xFF bytes to clock the
signal all the way down the strip.

Upload with mpremote and it autoruns on boot if saved as main.py on the
board's filesystem. See README.md for the flash/upload steps.
"""

import math
import time

from machine import SPI, Pin

# --- Wiring: change these to match your actual setup -----------------
# Strip's 5V/GND wires go to a 5V supply and shared ground (see README —
# do NOT exceed 5V, color-controller chips on these strips die above 6V).
# Strip's DI (data in) and CI (clock in) wires go straight to these two
# ESP32 GPIOs — no MOSFETs needed, this is a logic-level digital protocol
# like the WS2812B strip, just split across two wires instead of one.
# SCK_PIN/MOSI_PIN are the ESP32's default hardware VSPI pins; MISO_PIN is
# required to construct the SPI bus but is never driven by this code — it
# doesn't need to be physically connected to anything.
MOSI_PIN = 23  # -> strip DI
SCK_PIN = 18  # -> strip CI
MISO_PIN = 19  # unused, but machine.SPI() requires a pin

NUM_LEDS = 288  # actual count on this strip -- recount and change if you cut it

# --- Look of the pulse -------------------------------------------------
GOLD = (255, 110, 0)  # amber-gold with a hint of red; less green/blue = less white
MIN_BRIGHTNESS = 0.08  # never fully goes dark — keeps it feeling "alive"
MAX_BRIGHTNESS = 0.9  # pulling back from 1.0 avoids a washed-out/white peak
PULSE_PERIOD_S = 4.0  # seconds for one full dim->bright->dim breath
STEPS_PER_PERIOD = 120  # higher = smoother, lower = less flicker-prone

spi = SPI(
    2,
    baudrate=4_000_000,
    polarity=0,
    phase=0,
    sck=Pin(SCK_PIN),
    mosi=Pin(MOSI_PIN),
    miso=Pin(MISO_PIN),
)
step_delay_ms = int((PULSE_PERIOD_S * 1000) / STEPS_PER_PERIOD)

# Frame layout: 4-byte start frame + 4 bytes/LED + end frame.
# End frame needs at least NUM_LEDS/2 bits of clock to flush the last
# LED's data through the chain's internal shift registers.
_END_FRAME_LEN = (NUM_LEDS + 15) // 16
_PIXELS_OFFSET = 4
_PIXELS_END = _PIXELS_OFFSET + NUM_LEDS * 4
_buf = bytearray(_PIXELS_END + _END_FRAME_LEN)
_buf[_PIXELS_END:] = bytes([0xFF]) * _END_FRAME_LEN


def set_all(r, g, b):
    # Header 0xFF = max 5-bit brightness field; we scale r/g/b ourselves
    # instead of using APA102's own per-pixel brightness bits.
    _buf[_PIXELS_OFFSET:_PIXELS_END] = bytes([0xFF, b, g, r]) * NUM_LEDS
    spi.write(_buf)


def run():
    try:
        i = 0
        while True:
            phase = (i % STEPS_PER_PERIOD) / STEPS_PER_PERIOD * 2 * math.pi
            level = (math.sin(phase) + 1) / 2  # 0..1 smooth breathing curve
            brightness = MIN_BRIGHTNESS + level * (MAX_BRIGHTNESS - MIN_BRIGHTNESS)
            set_all(
                int(GOLD[0] * brightness),
                int(GOLD[1] * brightness),
                int(GOLD[2] * brightness),
            )
            time.sleep_ms(step_delay_ms)
            i += 1
    except KeyboardInterrupt:
        set_all(0, 0, 0)


if __name__ == "__main__":
    run()
