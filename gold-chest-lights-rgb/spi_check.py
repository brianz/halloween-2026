"""Standalone DotStar (APA102) link check.

Unlike the WS2812B strip's single data line or an analog RGB strip's
independent R/G/B channels, a DotStar strip's two signal wires (DI, CI)
are both labeled right on the flex PCB — there's no GPIO to "guess" the
way pin_sweep.py does in the other two chest-lights directories. Confirm
DI/CI wiring against the strip's silkscreen (or with a multimeter
continuity check) before assuming a code or pin problem.

This script instead confirms the SPI link + strip itself works, by
cycling the whole strip through red, green, blue, white, then off, using
the same MOSI_PIN/SCK_PIN/MISO_PIN/NUM_LEDS constants as main.py. Run
directly (not via main.py):

    mpremote connect /dev/cu.usbserial-0001 sleep 3 run spi_check.py

Ctrl-C stops it and turns the strip off. If nothing lights for ANY color,
recheck the 5V/GND power wiring and the DI/CI <-> MOSI_PIN/SCK_PIN wiring
before suspecting the code.
"""

import time

from machine import SPI, Pin

MOSI_PIN = 23  # -> strip DI
SCK_PIN = 18  # -> strip CI
MISO_PIN = 19  # unused, but machine.SPI() requires a pin
NUM_LEDS = 144

spi = SPI(
    2,
    baudrate=4_000_000,
    polarity=0,
    phase=0,
    sck=Pin(SCK_PIN),
    mosi=Pin(MOSI_PIN),
    miso=Pin(MISO_PIN),
)

_END_FRAME_LEN = (NUM_LEDS + 15) // 16

COLORS = [
    ("red", (255, 0, 0)),
    ("green", (0, 255, 0)),
    ("blue", (0, 0, 255)),
    ("white", (255, 255, 255)),
    ("off", (0, 0, 0)),
]

STEP_SECONDS = 2


def set_all(r, g, b):
    spi.write(bytes(4))  # start frame: 32 zero bits
    spi.write(bytes([0xFF, b, g, r]) * NUM_LEDS)
    spi.write(bytes([0xFF]) * _END_FRAME_LEN)


def run():
    try:
        while True:
            for name, (r, g, b) in COLORS:
                print("showing {}".format(name))
                set_all(r, g, b)
                time.sleep(STEP_SECONDS)
    except KeyboardInterrupt:
        set_all(0, 0, 0)
        print("stopped")


if __name__ == "__main__":
    run()
