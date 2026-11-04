import argparse
import socket
import threading
import time

import numpy as np
import sounddevice as sd

try:
    from scipy.signal import lfilter
except ImportError:  # SciPy is optional; fall back to a pure-Python biquad
    lfilter = None

# ---------------- ARGUMENTS -----------------
parser = argparse.ArgumentParser(description="Detect bass hits and signal the ThinkPad LED script over UDP.")
parser.add_argument("--plot", action="store_true",
                    help="show the live raw/filtered waveform plot (uses more CPU)")
parser.add_argument("--device", type=int, default=13,
                    help="input device index (see --list-devices)")
parser.add_argument("--list-devices", action="store_true",
                    help="print the available audio devices and exit")
parser.add_argument("--samplerate", type=int, default=44100, help="sampling rate in Hz")
parser.add_argument("--blocksize", type=int, default=512,
                    help="frames per audio callback; larger = less CPU, more latency")
parser.add_argument("--channel", type=int, default=0, help="0 = left, 1 = right")
parser.add_argument("--delay", type=float, default=0.2, help="delay before detection, in seconds")
parser.add_argument("--threshold", type=float, default=0.45, help="peak threshold on the filtered signal")
parser.add_argument("--min-send-interval", type=float, default=0.05,
                    help="minimum seconds between UDP trigger packets")
parser.add_argument("--fps", type=float, default=20, help="plot refresh rate (with --plot)")
parser.add_argument("--window", type=float, default=1.0, help="seconds shown in the plot (with --plot)")
parser.add_argument("--host", default="127.0.0.1", help="UDP target host")
parser.add_argument("--port", type=int, default=5005, help="UDP target port")
args = parser.parse_args()

if args.list_devices:
    print(sd.query_devices())
    print("Default input device:", sd.default.device)
    raise SystemExit

FS = args.samplerate
DELAY_SAMPLES = int(args.delay * FS)

# IIR filter coefficients (2nd-order bandpass), applied twice in cascade
a = np.array([1.0, -1.979851353142371, 0.9800523188151258])  # feedback
b = np.array([0.00005024141818873903,
              0.00010048283637747806,
              0.00005024141818873903])                        # feedforward


# ---------------- IIR FILTER (block based, keeps state between blocks) -----------------
class IIRFilter:
    def __init__(self, b, a):
        self.b = b
        self.a = a
        self.zi = np.zeros(max(len(a), len(b)) - 1)

    def process(self, x):
        if lfilter is not None:
            y, self.zi = lfilter(self.b, self.a, x, zi=self.zi)
            return y
        # Fallback: transposed direct form II, one sample at a time
        b0, b1, b2 = self.b
        _, a1, a2 = self.a
        z1, z2 = self.zi
        y = np.empty_like(x)
        for i, s in enumerate(x):
            out = b0 * s + z1
            z1 = b1 * s - a1 * out + z2
            z2 = b2 * s - a2 * out
            y[i] = out
        self.zi = np.array([z1, z2])
        return y


filt1 = IIRFilter(b, a)
filt2 = IIRFilter(b, a)

# ---------------- DELAY BUFFER (numpy FIFO) -----------------
delay_buf = np.zeros(DELAY_SAMPLES, dtype=np.float32)

# ---------------- UDP (send only, no bind) -----------------
udp_soc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
target = (args.host, args.port)
last_send = 0.0

# ---------------- PLOT BUFFERS (only used with --plot) -----------------
PLOT_DECIMATE = 20  # plot every Nth sample; plenty for a visual waveform
plot_len = max(1, int(args.window * FS) // PLOT_DECIMATE)
raw_hist = np.zeros(plot_len, dtype=np.float32)
filt_hist = np.zeros(plot_len, dtype=np.float32)
plot_lock = threading.Lock()


def push(hist, data):
    n = len(data)
    if n >= len(hist):
        hist[:] = data[-len(hist):]
    else:
        hist[:-n] = hist[n:]
        hist[-n:] = data


# ---------------- CALLBACK -----------------
def callback(indata, frames, time_info, status):
    global delay_buf, last_send
    if status:
        print(status)
    samples = indata[:, args.channel]

    # Delay: push the new block in, take the oldest block out
    if DELAY_SAMPLES:
        buf = np.concatenate((delay_buf, samples))
        delayed = buf[:frames]
        delay_buf = buf[frames:]
    else:
        delayed = samples.copy()

    filtered = filt2.process(filt1.process(delayed))

    if args.plot:
        with plot_lock:
            push(raw_hist, delayed[::PLOT_DECIMATE])
            push(filt_hist, filtered[::PLOT_DECIMATE])

    if np.max(np.abs(filtered)) > args.threshold:
        now = time.monotonic()
        if now - last_send >= args.min_send_interval:
            udp_soc.sendto(b"A", target)
            last_send = now


# ---------------- PLOT -----------------
def run_plot():
    import matplotlib.pyplot as plt

    plt.ion()
    fig, ax = plt.subplots()
    x = np.arange(plot_len)
    line_raw, = ax.plot(x, raw_hist, label="Raw")
    line_filt, = ax.plot(x, filt_hist, label="Filtered")
    ax.set_ylim(-1, 1)
    ax.set_xlim(0, plot_len)
    ax.set_xlabel(f"Samples (every {PLOT_DECIMATE}th)")
    ax.set_ylabel("Amplitude")
    ax.legend()
    plt.title("Real-time Audio (Raw vs Filtered)")

    interval = 1.0 / args.fps
    while plt.fignum_exists(fig.number):
        with plot_lock:
            line_raw.set_ydata(raw_hist.copy())
            line_filt.set_ydata(filt_hist.copy())
        plt.pause(interval)  # redraws and sleeps, capping the frame rate


# ---------------- STREAM -----------------
with sd.InputStream(samplerate=FS, blocksize=args.blocksize, device=args.device,
                    channels=2, dtype="float32", callback=callback):
    print(f"Listening on device {args.device} with {args.delay * 1000:.0f} ms delay"
          f"{' (plot on)' if args.plot else ''}. Ctrl+C to stop.")
    try:
        if args.plot:
            run_plot()
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    print("Stopped.")
