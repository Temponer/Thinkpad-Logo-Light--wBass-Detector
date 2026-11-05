import os
import shutil
import subprocess
import time
import socket
from collections import deque

import numpy as np
import matplotlib.pyplot as plt

# ---------------- SETTINGS -----------------
FS = 44100            # sampling rate
BLOCKSIZE = 16        # frames per block
WINDOW = 1            # seconds to display
CHANNEL = 0           # 0 = left, 1 = right
DELAY_SEC = 0.2       # delay in seconds
DELAY_SAMPLES = int(DELAY_SEC * FS)

# Which sound to listen to.
#   None  -> follow the default output automatically (laptop speakers,
#            headphones, Bluetooth, HDMI ...). Switches when the default
#            output changes, e.g. when you plug in headphones.
#   "..." -> a fixed PulseAudio/PipeWire source name, e.g.
#            "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor"
#            (list them with: pactl list short sources)
SOURCE = None
SINK_CHECK_SEC = 1.0  # how often to check if the default output changed

# IIR filter coefficients (example: 2nd-order bandpass)
a = [1.0, -1.979851353142371, 0.9800523188151258]  # feedback
b = [0.00005024141818873903,
     0.00010048283637747806,
     0.00005024141818873903]   # feedforward
# Trigger level on the filtered (bass) signal.
#   None   -> adaptive: fire when the bass is BEAT_RATIO times louder than its
#             recent average. Works at any volume / any output device.
#   number -> fixed level, e.g. 0.45 (the dashed lines on the plot show it)
PEAK_THRESHOLD = None
BEAT_RATIO = 1.6       # adaptive: how far above the average a hit must be
AVG_SEC = 2.0          # adaptive: how long the "recent average" is
MIN_LEVEL = 0.01       # ignore anything quieter than this (silence/noise)
COOLDOWN_SEC = 0.1     # send at most one UDP message per this many seconds

# UDP (sender only -- thinkpad_dot.py is the one listening on 5005)
udp_soc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


# ---------------- AUDIO SOURCE SELECTION -----------------
def get_default_sink():
    """Return the name of the current default output (sink), or None."""
    if not shutil.which("pactl"):
        return None
    try:
        out = subprocess.run(["pactl", "get-default-sink"], capture_output=True,
                             text=True, timeout=2)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
        # older pactl without get-default-sink
        out = subprocess.run(["pactl", "info"], capture_output=True,
                             text=True, timeout=2)
        for line in out.stdout.splitlines():
            if line.startswith("Default Sink:"):
                return line.split(":", 1)[1].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def wanted_source():
    """The PulseAudio/PipeWire source we should be recording from."""
    if SOURCE:
        return SOURCE
    sink = get_default_sink()
    return f"{sink}.monitor" if sink else "@DEFAULT_MONITOR@"


# PortAudio/ALSA's "pulse" device records from whatever $PULSE_SOURCE names.
# It must be set before sounddevice opens a stream.
os.environ["PULSE_SOURCE"] = wanted_source()
import sounddevice as sd  # noqa: E402


def find_pulse_device():
    for i, dev in enumerate(sd.query_devices()):
        if dev["name"] == "pulse" and dev["max_input_channels"] > 0:
            return i
    raise RuntimeError("No 'pulse' ALSA device found. Is PulseAudio or "
                       "pipewire-pulse running? (sd.query_devices() lists devices)")


DEVICE = find_pulse_device()


# ---------------- IIR FILTER CLASS -----------------
class IIRFilter:
    def __init__(self, b, a):
        self.b = b
        self.a = a
        self.x1 = self.x2 = 0.0
        self.y1 = self.y2 = 0.0

    def process(self, x):
        y = self.b[0]*x + self.b[1]*self.x1 + self.b[2]*self.x2 \
            - (self.a[1]*self.y1 + self.a[2]*self.y2)
        # shift states
        self.x2, self.x1 = self.x1, x
        self.y2, self.y1 = self.y1, y
        return y


# ---------------- CREATE TWO FILTERS -----------------
filt1 = IIRFilter(b, a)
filt2 = IIRFilter(b, a)

# ---------------- DELAY BUFFER -----------------
delay_queue = deque(maxlen=DELAY_SAMPLES)

# ---------------- PLOT SETUP -----------------
raw_history = deque(maxlen=WINDOW*FS)
filtered_history = deque(maxlen=WINDOW*FS)

plt.ion()
fig, ax = plt.subplots()
line_raw, = ax.plot([], [], label="Raw")
line_filt, = ax.plot([], [], label="Filtered")
ax.set_ylim(-1, 1)
ax.set_xlim(0, WINDOW*FS)
ax.set_xlabel("Samples")
ax.set_ylabel("Amplitude")
thr_hi = ax.axhline(0, color="red", ls="--", lw=1, label="Threshold")
thr_lo = ax.axhline(0, color="red", ls="--", lw=1)
ax.legend(loc="upper right")
title = ax.set_title("Real-time Audio (Raw vs Filtered)")

# trigger state (shared between the audio callback and the plot)
state = {"avg": 0.0, "blocks": 0, "threshold": MIN_LEVEL, "last_send": 0.0, "hits": 0}
AVG_ALPHA = BLOCKSIZE / (FS * AVG_SEC)


# ---------------- CALLBACK -----------------
def callback(indata, frames, time_info, status):
    if status:
        print(status)
    samples = indata[:, CHANNEL]  # select channel

    delayed_samples = []
    for s in samples:
        delay_queue.append(s)
        if len(delay_queue) == DELAY_SAMPLES:
            delayed_samples.append(delay_queue[0])  # oldest sample

    if not delayed_samples:
        return  # skip until buffer is full

    # Apply first filter
    first_pass = [filt1.process(s) for s in delayed_samples]
    # Apply second filter to output of first filter
    second_pass = [filt2.process(s) for s in first_pass]

    # Extend histories
    raw_history.extend(delayed_samples)
    filtered_history.extend(second_pass)

    # Trigger only on delayed + filtered signal
    peak = max(abs(v) for v in second_pass)
    if PEAK_THRESHOLD is None:
        # plain running mean while warming up, then a slow moving average
        state["blocks"] += 1
        alpha = max(AVG_ALPHA, 1.0 / state["blocks"])
        state["avg"] += (peak - state["avg"]) * alpha
        threshold = max(MIN_LEVEL, state["avg"] * BEAT_RATIO)
    else:
        threshold = PEAK_THRESHOLD
    state["threshold"] = threshold

    now = time.monotonic()
    if peak > threshold and now - state["last_send"] >= COOLDOWN_SEC:
        state["last_send"] = now
        state["hits"] += 1
        udp_soc.sendto(b"A", ("127.0.0.1", 5005))


# ---------------- PLOT UPDATE -----------------
def update_plot():
    data_raw = np.array(raw_history)
    data_filt = np.array(filtered_history)

    n = min(len(data_raw), len(data_filt))
    if n < 2:
        plt.pause(0.05)
        return
    x = np.arange(n)
    line_raw.set_data(x, data_raw[-n:])
    line_filt.set_data(x, data_filt[-n:])
    ax.set_xlim(0, n)
    t = state["threshold"]
    thr_hi.set_ydata([t, t])
    thr_lo.set_ydata([-t, -t])
    title.set_text(f"{source_label}   |   hits sent: {state['hits']}")
    plt.pause(0.03)


# ---------------- STREAM -----------------
source_label = ""


def open_stream(source):
    # Fresh ALSA "pulse" connection picks up the new PULSE_SOURCE.
    os.environ["PULSE_SOURCE"] = source
    delay_queue.clear()
    state["avg"], state["blocks"] = 0.0, 0
    stream = sd.InputStream(samplerate=FS, blocksize=BLOCKSIZE,
                            device=DEVICE, channels=2, callback=callback)
    stream.start()
    print(f"Listening to: {source}  ({DELAY_SEC*1000:.0f} ms delay)")
    global source_label
    source_label = f"Listening to: {source}"
    return stream


try:
    source = wanted_source()
    stream = open_stream(source)
    last_check = time.monotonic()
    while plt.fignum_exists(fig.number):
        update_plot()
        if time.monotonic() - last_check >= SINK_CHECK_SEC:
            last_check = time.monotonic()
            new_source = wanted_source()
            if new_source != source:
                print("Output changed, switching...")
                stream.close()
                source = new_source
                stream = open_stream(source)
except KeyboardInterrupt:
    pass
finally:
    try:
        stream.close()
    except Exception:
        pass
    print("Stopped.")
