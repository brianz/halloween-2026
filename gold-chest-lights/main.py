"""Treasure chest gold pulse — MicroPython, runs directly on the ESP32.

Slowly breathes a warm gold/yellow across a WS2812B (NeoPixel-compatible)
strip hidden under the fake jewels, as if the treasure itself is alive.

Upload with mpremote and it autoruns on boot if saved as main.py on the
board's filesystem. See README.md for the flash/upload steps.
"""

import math
import time

from machine import Pin
from neopixel import NeoPixel

# --- Wiring: change these to match your actual setup -----------------
# "Positive"/"negative" from the breadboard are the strip's 5V/GND power
# wires, not GPIO pins — they don't belong in code. Only the data line
# (a GPIO) matters here. Update DATA_PIN to whatever GPIO your white/
# data wire is actually on if it turns out not to be 15.
DATA_PIN = 15
NUM_LEDS = 30  # count the LEDs on your strip and set this exactly

# --- Look of the pulse -------------------------------------------------
GOLD = (255, 180, 20)  # warm gold; use (255, 255, 0) for a punchier yellow
MIN_BRIGHTNESS = 0.08  # never fully goes dark — keeps it feeling "alive"
MAX_BRIGHTNESS = 1.0
PULSE_PERIOD_S = 4.0  # seconds for one full dim->bright->dim breath
STEPS_PER_PERIOD = 120  # higher = smoother, lower = less flicker-prone

np = NeoPixel(Pin(DATA_PIN), NUM_LEDS)
step_delay_ms = int((PULSE_PERIOD_S * 1000) / STEPS_PER_PERIOD)


def set_all(r, g, b):
    for i in range(NUM_LEDS):
        np[i] = (r, g, b)
    np.write()


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
