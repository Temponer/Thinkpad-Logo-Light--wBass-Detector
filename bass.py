import sounddevice as sd
import numpy as np
import matplotlib.pyplot as plt
from collections import deque
import socket
from thinkpad_dot import ECLED

# ---------------- SETTINGS -----------------
FS = 44100            # sampling rate
BLOCKSIZE = 16        # frames per block
DEVICE = 13           # PulseAudio input (see sd.query_devices())
WINDOW = 1            # seconds to display
CHANNEL = 0           # 0 = left, 1 = right
DELAY_SEC = 0.2       # delay in seconds
DELAY_SAMPLES = int(DELAY_SEC * FS)

print(sd.query_devices())
print("Default input device:", sd.default.device)

# IIR filter coefficients (example: 2nd-order bandpass)
a = [1.0, -1.979851353142371, 0.9800523188151258]  # feedback
b = [0.00005024141818873903,
     0.00010048283637747806,
     0.00005024141818873903]   # feedforward
PEAK_THRESHOLD = 0.45

# UDP
udp_soc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_soc.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
udp_soc.bind(("", 5005))

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
ax.legend()
plt.title("Real-time Audio (Raw vs Filtered)")

# ---------------- CALLBACK -----------------
def callback(indata, frames, time, status):
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

    # Ensure both have exactly the same length
    min_len = min(len(raw_history), len(filtered_history))
    while len(raw_history) > min_len:
        raw_history.popleft()
    while len(filtered_history) > min_len:
        filtered_history.popleft()

    # Trigger only on delayed + filtered signal
    if max(np.abs(second_pass)) > PEAK_THRESHOLD:
        udp_soc.sendto(b"A", ("127.0.0.1", 5005))

# ---------------- PLOT UPDATE -----------------
def update_plot():
    data_raw = np.array(raw_history)
    data_filt = np.array(filtered_history)

    min_len = min(len(data_raw), len(data_filt))
    data_raw = data_raw[-min_len:]
    data_filt = data_filt[-min_len:]
    x = np.arange(len(data_raw))

    line_raw.set_xdata(x)
    line_raw.set_ydata(data_raw)
    line_filt.set_xdata(x)
    line_filt.set_ydata(data_filt)

    ax.set_xlim(0, len(data_raw))
    fig.canvas.draw()
    fig.canvas.flush_events()

# ---------------- STREAM -----------------
with sd.InputStream(samplerate=FS, blocksize=BLOCKSIZE,
                    device=DEVICE, channels=2, callback=callback):
    print(f"Listening with {DELAY_SEC*1000:.0f} ms delayed processing...")
    try:
        while True:
            update_plot()
    except KeyboardInterrupt:
        print("Stopped.")
