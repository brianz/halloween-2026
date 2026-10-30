"""
Standalone mic diagnostic — no ElevenLabs, no Temporal, just PyAudio/CoreAudio.
Use this to isolate "is the mic actually reaching Python" from "is something
in the kiosk/ElevenLabs stack swallowing it."

What it does:
  1. Lists every input-capable audio device PortAudio can see, and which one
     is the default.
  2. Opens an input stream with the exact same settings the kiosk's
     DefaultAudioInterface uses (16-bit mono, 16kHz, 4000-frame buffer) and
     records a few seconds.
  3. Reports the peak amplitude it captured and saves the clip to a WAV file
     so you can play it back.

A near-zero peak with no errors raised is the classic signature of a macOS
TCC permission problem: CoreAudio silently hands back zeroed buffers instead
of raising, rather than refusing to open the stream. See the printed
troubleshooting notes below if that's what you see.

Run:  .venv/bin/python mic_test.py [--seconds N] [--device INDEX]
"""

import argparse
import array
import math
import sys
import wave

try:
    import pyaudio
except ImportError:
    sys.exit("pyaudio not installed — run `just deps` first (needs portaudio: brew install portaudio).")

RATE = 16000
CHANNELS = 1
FORMAT = pyaudio.paInt16
FRAMES_PER_BUFFER = 4000  # same as DefaultAudioInterface.INPUT_FRAMES_PER_BUFFER
OUT_PATH = "mic_test_capture.wav"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=4.0, help="How long to record (default 4s)")
    parser.add_argument(
        "--device", type=int, default=None, help="PortAudio device index to use instead of the default"
    )
    return parser.parse_args()


def list_devices(p: "pyaudio.PyAudio", default_index: int) -> None:
    print(f"PortAudio version: {pyaudio.get_portaudio_version_text()}")
    print(f"Host APIs: {[p.get_host_api_info_by_index(i)['name'] for i in range(p.get_host_api_count())]}")
    print(f"\nInput-capable devices (default marked with *):")
    for i in range(p.get_device_count()):
        info = p.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0:
            marker = "*" if i == default_index else " "
            print(
                f"  {marker} [{i}] {info['name']!r} "
                f"(maxInputChannels={info['maxInputChannels']}, "
                f"defaultSampleRate={info['defaultSampleRate']})"
            )
    print()


def main() -> None:
    args = parse_args()
    p = pyaudio.PyAudio()

    try:
        default_index = p.get_default_input_device_info()["index"]
    except OSError:
        default_index = None
        print("!! PortAudio reports NO default input device at all.")
        print("   Check System Settings > Sound > Input — is anything listed/selected there?\n")

    list_devices(p, default_index)

    device_index = args.device if args.device is not None else default_index
    if device_index is None:
        sys.exit("No input device to use (pass --device INDEX from the list above).")

    device_name = p.get_device_info_by_index(device_index)["name"]
    print(f"Recording {args.seconds}s from device [{device_index}] {device_name!r}...")
    print("(talk into the mic now)")

    stream = p.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        input_device_index=device_index,
        frames_per_buffer=FRAMES_PER_BUFFER,
    )

    frames = []
    n_buffers = int(RATE / FRAMES_PER_BUFFER * args.seconds) + 1
    for _ in range(n_buffers):
        frames.append(stream.read(FRAMES_PER_BUFFER, exception_on_overflow=False))

    stream.stop_stream()
    stream.close()
    p.terminate()

    raw = b"".join(frames)
    samples = array.array("h")  # 16-bit signed, matches FORMAT=paInt16
    samples.frombytes(raw)
    peak = max((abs(s) for s in samples), default=0)
    rms = math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0

    with wave.open(OUT_PATH, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(raw)

    print(f"\nCaptured {len(raw)} bytes. Peak amplitude: {peak}/32768. RMS: {rms:.1f}.")
    print(f"Saved to {OUT_PATH} — play it back (`afplay {OUT_PATH}`) to confirm by ear.\n")

    if peak < 50:
        print("!! Peak amplitude is near zero — essentially silence.")
        print("   This is the classic signature of macOS blocking mic access at the")
        print("   CoreAudio level WITHOUT raising an error: PortAudio opens the stream")
        print("   fine and gets back all-zero buffers instead of a permission error.")
        print("   See the troubleshooting notes below.")
    else:
        print("Looks like real audio made it into Python. If the kiosk still isn't")
        print("picking you up, the problem is more likely downstream (ElevenLabs")
        print("websocket, ASR) than the mic capture itself.")


if __name__ == "__main__":
    main()
