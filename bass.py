#!/usr/bin/env python3
"""Detect bass beats in whatever your PC is playing and send them to
thinkpad_dot.py (UDP 127.0.0.1:5005), which blinks the ThinkPad LEDs.

    python3 bass.py              # run quietly
    python3 bass.py -v           # print status to the terminal
    python3 bass.py --plot       # show the live waveform window
    python3 bass.py --help       # all options
"""
import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from collections import deque

# ---------------- DEFAULT SETTINGS (all can be changed with options) ---------
FS = 44100            # sampling rate
BLOCKSIZE = 16        # frames per block
WINDOW = 1            # seconds shown in the plot
CHANNEL = 0           # 0 = left, 1 = right
DELAY_SEC = 0.2       # delay before processing, in seconds
SINK_CHECK_SEC = 1.0  # how often to check if the default output changed

BEAT_RATIO = 1.6      # adaptive: how far above the average a hit must be
AVG_SEC = 2.0         # adaptive: how long the "recent average" is
MIN_LEVEL = 0.01      # ignore anything quieter than this (silence/noise)
COOLDOWN_SEC = 0.1    # send at most one beat per this many seconds

UDP_TARGET = ("127.0.0.1", 5005)

# 2nd-order low-pass at ~100 Hz, applied twice (so only bass gets through)
a = [1.0, -1.979851353142371, 0.9800523188151258]  # feedback
b = [0.00005024141818873903,
     0.00010048283637747806,
     0.00005024141818873903]                          # feedforward


def parse_args():
    p = argparse.ArgumentParser(
        description="Blink the ThinkPad LEDs to the bass of whatever is playing.")
    p.add_argument("--plot", action="store_true",
                   help="show the live waveform / threshold window")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="print status (beats sent, trigger level) to the terminal")
    p.add_argument("-t", "--threshold", type=float, default=None, metavar="LEVEL",
                   help="fixed trigger level, e.g. 0.05 (default: adaptive)")
    p.add_argument("-r", "--ratio", type=float, default=BEAT_RATIO,
                   help=f"adaptive mode: how much louder than average a beat must "
                        f"be; lower = more flashes (default {BEAT_RATIO})")
    p.add_argument("--min-level", type=float, default=MIN_LEVEL,
                   help=f"adaptive mode: ignore anything quieter than this "
                        f"(default {MIN_LEVEL})")
    p.add_argument("-s", "--source", default=None,
                   help="record from this PulseAudio/PipeWire source instead of "
                        "following the default output (see: pactl list short sources)")
    return p.parse_args()


# ---------------- SUDO HANDLING -----------------
def drop_root_if_sudo():
    """Audio lives in *your* user session; root can't see it.

    If started with sudo, re-run this script as the user who ran sudo,
    passing along what it needs to reach the sound server and the screen.
    """
    if os.geteuid() != 0:
        return
    user = os.environ.get("SUDO_USER")
    if not user or user == "root":
        sys.exit("bass.py can't hear your audio as root. Run it as your normal "
                 "user:  python3 bass.py   (or use ./run.sh)")
    import pwd
    pw = pwd.getpwnam(user)
    runtime = f"/run/user/{pw.pw_uid}"
    env = {
        "HOME": pw.pw_dir,
        "USER": user,
        "LOGNAME": user,
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "XDG_RUNTIME_DIR": runtime,
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus",
        "DISPLAY": os.environ.get("DISPLAY", ":0"),
    }
    for key in ("WAYLAND_DISPLAY", "XAUTHORITY", "MPLBACKEND"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    if "XAUTHORITY" not in env:
        for path in (f"{runtime}/gdm/Xauthority", f"{pw.pw_dir}/.Xauthority"):
            if os.path.exists(path):
                env["XAUTHORITY"] = path
                break
    cmd = ["sudo", "-u", user, "env"] + [f"{k}={v}" for k, v in env.items()] \
        + [sys.executable, os.path.abspath(__file__)] + sys.argv[1:]
    os.execvp("sudo", cmd)


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


def wanted_source(fixed_source):
    """The PulseAudio/PipeWire source we should be recording from."""
    if fixed_source:
        return fixed_source
    sink = get_default_sink()
    return f"{sink}.monitor" if sink else "@DEFAULT_MONITOR@"


# ---------------- IIR FILTER -----------------
class IIRFilter:
    def __init__(self, b, a):
        self.b = b
        self.a = a
        self.x1 = self.x2 = 0.0
        self.y1 = self.y2 = 0.0

    def process(self, x):
        y = self.b[0]*x + self.b[1]*self.x1 + self.b[2]*self.x2 \
            - (self.a[1]*self.y1 + self.a[2]*self.y2)
        self.x2, self.x1 = self.x1, x
        self.y2, self.y1 = self.y1, y
        return y


# ---------------- BEAT DETECTOR -----------------
class BeatDetector:
    """Delays, filters and thresholds audio; sends a UDP 'A' on each beat."""

    def __init__(self, args, keep_history):
        self.fixed_threshold = args.threshold
        self.ratio = args.ratio
        self.min_level = args.min_level
        self.verbose = args.verbose
        self.avg_alpha = BLOCKSIZE / (FS * AVG_SEC)
        self.filt1 = IIRFilter(b, a)
        self.filt2 = IIRFilter(b, a)
        self.delay_queue = deque(maxlen=int(DELAY_SEC * FS))
        self.keep_history = keep_history
        self.raw_history = deque(maxlen=WINDOW * FS)
        self.filtered_history = deque(maxlen=WINDOW * FS)
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.threshold = self.fixed_threshold or self.min_level
        self.hits = 0
        self.reset()

    def reset(self):
        self.delay_queue.clear()
        self.avg = 0.0
        self.blocks = 0
        self.last_send = 0.0

    def callback(self, indata, frames, time_info, status):
        if status and self.verbose:
            print(f"audio status: {status}")
        delayed = []
        dq = self.delay_queue
        for s in indata[:, CHANNEL]:
            dq.append(s)
            if len(dq) == dq.maxlen:
                delayed.append(dq[0])  # oldest sample
        if not delayed:
            return  # still filling the delay buffer

        filtered = [self.filt2.process(self.filt1.process(s)) for s in delayed]
        if self.keep_history:
            self.raw_history.extend(delayed)
            self.filtered_history.extend(filtered)

        peak = max(abs(v) for v in filtered)
        if self.fixed_threshold is None:
            # plain running mean while warming up, then a slow moving average
            self.blocks += 1
            alpha = max(self.avg_alpha, 1.0 / self.blocks)
            self.avg += (peak - self.avg) * alpha
            self.threshold = max(self.min_level, self.avg * self.ratio)
        else:
            self.threshold = self.fixed_threshold

        now = time.monotonic()
        if peak > self.threshold and now - self.last_send >= COOLDOWN_SEC:
            self.last_send = now
            self.hits += 1
            self.udp.sendto(b"A", UDP_TARGET)


# ---------------- PLOT (only with --plot) -----------------
class Plot:
    def __init__(self, detector):
        import matplotlib.pyplot as plt
        import numpy as np
        self.plt, self.np, self.det = plt, np, detector
        plt.ion()
        self.fig, self.ax = plt.subplots()
        self.line_raw, = self.ax.plot([], [], label="Raw")
        self.line_filt, = self.ax.plot([], [], label="Filtered (bass)")
        self.thr_hi = self.ax.axhline(0, color="red", ls="--", lw=1, label="Threshold")
        self.thr_lo = self.ax.axhline(0, color="red", ls="--", lw=1)
        self.ax.set_ylim(-1, 1)
        self.ax.set_xlim(0, WINDOW * FS)
        self.ax.set_xlabel("Samples")
        self.ax.set_ylabel("Amplitude")
        self.ax.legend(loc="upper right")
        self.title = self.ax.set_title("waiting for audio...")

    def is_open(self):
        return self.plt.fignum_exists(self.fig.number)

    def update(self):
        np, det = self.np, self.det
        raw = np.array(det.raw_history)
        filt = np.array(det.filtered_history)
        n = min(len(raw), len(filt))
        if n >= 2:
            x = np.arange(n)
            self.line_raw.set_data(x, raw[-n:])
            self.line_filt.set_data(x, filt[-n:])
            self.ax.set_xlim(0, n)
            t = det.threshold
            self.thr_hi.set_ydata([t, t])
            self.thr_lo.set_ydata([-t, -t])
            self.title.set_text(f"beats sent: {det.hits}")
        self.plt.pause(0.03)


# ---------------- MAIN -----------------
def main():
    args = parse_args()
    drop_root_if_sudo()

    # The ALSA "pulse" device records from whatever $PULSE_SOURCE names;
    # it must be set before sounddevice opens a stream.
    source = wanted_source(args.source)
    os.environ["PULSE_SOURCE"] = source
    import sounddevice as sd

    device = next((i for i, d in enumerate(sd.query_devices())
                   if d["name"] == "pulse" and d["max_input_channels"] > 0), None)
    if device is None:
        sys.exit("No 'pulse' audio device found. Is PulseAudio or pipewire-pulse "
                 "running, and are you running this as your normal user?")

    detector = BeatDetector(args, keep_history=args.plot)
    plot = Plot(detector) if args.plot else None

    def open_stream(src):
        os.environ["PULSE_SOURCE"] = src  # a fresh connection picks this up
        detector.reset()
        s = sd.InputStream(samplerate=FS, blocksize=BLOCKSIZE, device=device,
                           channels=2, callback=detector.callback)
        s.start()
        print(f"Listening to: {src}")
        return s

    mode = (f"fixed threshold {args.threshold}" if args.threshold is not None
            else f"adaptive threshold (ratio {args.ratio})")
    print(f"Bass detector running, {mode}. Ctrl+C to stop.")

    stream = open_stream(source)
    last_check = time.monotonic()
    last_hits = 0
    try:
        while plot is None or plot.is_open():
            if plot:
                plot.update()
            else:
                time.sleep(0.1)
            now = time.monotonic()
            if now - last_check < SINK_CHECK_SEC:
                continue
            if args.verbose:
                rate = (detector.hits - last_hits) / (now - last_check)
                print(f"beats sent: {detector.hits} ({rate:.1f}/s)   "
                      f"trigger level: {detector.threshold:.3f}")
                last_hits = detector.hits
            last_check = now
            new_source = wanted_source(args.source)
            if new_source != source:
                print("Output changed, switching...")
                stream.close()
                source = new_source
                stream = open_stream(source)
    except KeyboardInterrupt:
        pass
    finally:
        stream.close()
        print("Stopped.")


if __name__ == "__main__":
    main()
