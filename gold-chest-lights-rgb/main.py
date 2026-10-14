"""Treasure chest gold pulse — MicroPython, 4-wire RGB strip variant.

Slowly breathes a warm gold/yellow across a 5V analog RGB LED strip
(separate +5V, R, G, B wires — no onboard pixel chip like WS2812B), driven
by PWM on three GPIOs, each through its own N-channel MOSFET. Same
breathing effect as ../gold-chest-lights (WS2812B strip, different board)
— if you retune the look, change GOLD / MIN_BRIGHTNESS / MAX_BRIGHTNESS /
PULSE_PERIOD_S / STEPS_PER_PERIOD here AND there so the two chests match.

Upload with mpremote and it autoruns on boot if saved as main.py on the
board's filesystem. See README.md for the flash/upload steps.
"""

import math
import time

from machine import Pin, PWM

# --- Wiring: change these to match your actual setup -----------------
# Strip's +5V wire goes to a 5V supply (ESP32 5V pin if the strip is short
# enough to stay within its rating, otherwise a separate 5V PSU — see
# README). Strip GND, PSU GND (if separate), and ESP32 GND must all be
# tied together. The strip's R/G/B wires do NOT connect to the ESP32
# directly: each goes to the drain of its own N-channel MOSFET, the
# MOSFET's source goes to GND, and the MOSFET's gate goes to the matching
# GPIO below. GPIOs alone can't sink the current an LED strip channel
# draws. Don't trust a visual wiring check alone — if a channel doesn't
# light, use pin_sweep.py (below) to find the real pin.
RED_PIN = 25
GREEN_PIN = 26
BLUE_PIN = 27

PWM_FREQ = 1000  # Hz; above flicker-fusion, low enough for most MOSFETs to switch cleanly

# --- Look of the pulse -------------------------------------------------
GOLD = (255, 110, 0)  # amber-gold with a hint of red; less green/blue = less white
MIN_BRIGHTNESS = 0.08  # never fully goes dark — keeps it feeling "alive"
MAX_BRIGHTNESS = 0.9  # pulling back from 1.0 avoids a washed-out/white peak
PULSE_PERIOD_S = 4.0  # seconds for one full dim->bright->dim breath
STEPS_PER_PERIOD = 120  # higher = smoother, lower = less flicker-prone

red = PWM(Pin(RED_PIN), freq=PWM_FREQ, duty_u16=0)
green = PWM(Pin(GREEN_PIN), freq=PWM_FREQ, duty_u16=0)
blue = PWM(Pin(BLUE_PIN), freq=PWM_FREQ, duty_u16=0)
step_delay_ms = int((PULSE_PERIOD_S * 1000) / STEPS_PER_PERIOD)


def set_color(r, g, b):
    red.duty_u16(int(r / 255 * 65535))
    green.duty_u16(int(g / 255 * 65535))
    blue.duty_u16(int(b / 255 * 65535))


def run():
    try:
        i = 0
        while True:
            phase = (i % STEPS_PER_PERIOD) / STEPS_PER_PERIOD * 2 * math.pi
            level = (math.sin(phase) + 1) / 2  # 0..1 smooth breathing curve
            brightness = MIN_BRIGHTNESS + level * (MAX_BRIGHTNESS - MIN_BRIGHTNESS)
            set_color(
                int(GOLD[0] * brightness),
                int(GOLD[1] * brightness),
                int(GOLD[2] * brightness),
            )
            time.sleep_ms(step_delay_ms)
            i += 1
    except KeyboardInterrupt:
        set_color(0, 0, 0)


if __name__ == "__main__":
    run()
