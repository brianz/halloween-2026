"""Standalone GPIO sweep to find which pins actually drive the R/G/B
MOSFET gates for the 4-wire strip.

Run directly (not via main.py) so you can watch the strip and read the
printed pin numbers in your own terminal at your own pace:

    mpremote connect /dev/cu.usbserial-0001 sleep 3 run pin_sweep.py

Ctrl-C stops it. It loops forever so you can watch multiple passes.

Each pin in turn goes HIGH for 3 seconds (watch the strip — note which
*color* lights up, not just whether something lights up), then LOW for
1 second, then moves on. Whichever pin number is printed when a color
reacts is the real RED_PIN/GREEN_PIN/BLUE_PIN for main.py.

Pins deliberately left out, and why:
  - GPIO 6-11: wired internally to the SPI flash chip. Driving these can
    crash or corrupt the board. Never test these.
  - GPIO 34, 35, 36, 39: input-only, can't be set as OUTPUT.
  - GPIO 1, 3: UART0 TX/RX — this is the exact serial link this script
    runs over. Toggling them breaks the connection you're watching.
"""

import time

from machine import Pin

CANDIDATE_PINS = [
    0, 2, 4, 5, 12, 13, 14, 15, 16, 17,
    18, 19, 21, 22, 23, 25, 26, 27, 32, 33,
]

HIGH_SECONDS = 3
GAP_SECONDS = 1


def sweep_once():
    for gpio in CANDIDATE_PINS:
        try:
            p = Pin(gpio, Pin.OUT)
            p.value(1)
            print("GPIO {} HIGH -- watch the strip now".format(gpio))
            time.sleep(HIGH_SECONDS)
            p.value(0)
            p = Pin(gpio, Pin.IN)  # release back to high-impedance
            time.sleep(GAP_SECONDS)
        except Exception as e:
            print("GPIO {} skipped ({})".format(gpio, e))


def run():
    round_num = 1
    try:
        while True:
            print("=== sweep round {} ===".format(round_num))
            sweep_once()
            round_num += 1
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    run()
