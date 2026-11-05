# ThinkPad Logo Light — Bass Detector

Makes the red dot on the ThinkPad lid logo (and a few keyboard LEDs) blink to
the bass of whatever your laptop is playing: music, videos, games.

It listens to the sound going **out** of your PC, not the microphone, so it
works with speakers, wired headphones, Bluetooth and HDMI. When you switch
output, for example by plugging in headphones, it follows automatically.

## Requirements

- A ThinkPad running Linux with PulseAudio or PipeWire (any recent Ubuntu,
  Fedora and so on)
- `pactl` (on Ubuntu/Debian: `sudo apt install pulseaudio-utils`)
- Python 3 with `sounddevice` and `numpy`. `scipy` is recommended, because it
  makes the filtering about 25× lighter on the CPU (the script works without
  it). Add `matplotlib` if you want the plot:

  ```sh
  pip install sounddevice numpy scipy matplotlib
  ```

## Quick start

```sh
./run.sh
```

That's it. It asks for your sudo password once, then:

1. loads the `ec_sys` kernel module with write support if it isn't already
   (needed to control the logo LED, and reset on every reboot),
2. starts the LED controller (`thinkpad_dot.py`) as root in the background,
3. starts the bass detector (`bass.py`) as your normal user.

Press **Ctrl+C** (or close the plot window) to stop both.
`sudo ./run.sh` also works; the audio part always runs as your user, because
root can't hear your audio session.

## Options

Everything after `./run.sh` is passed to the bass detector:

| Option | What it does |
| --- | --- |
| `--plot` | Show a live window with the raw sound, the filtered bass and the trigger level |
| `-v`, `--verbose` | Print beats sent and received each second, and the current trigger level |
| `-r RATIO`, `--ratio RATIO` | Sensitivity in adaptive mode (default `1.6`). Lower means more flashes (try `1.3`), higher means only strong kicks (try `2.0`–`2.5`) |
| `-t LEVEL`, `--threshold LEVEL` | Use a fixed trigger level instead, e.g. `0.05`. Lower means more flashes |
| `--min-level LEVEL` | Ignore bass quieter than this (default `0.01`). Raise it if the LED flickers during silence |
| `-s SOURCE`, `--source SOURCE` | Always listen to this source instead of following the default output (list sources with `pactl list short sources`; use one ending in `.monitor`) |
| `-h`, `--help` | List all options |

Examples:

```sh
./run.sh --plot -v      # see what's happening while you tune it
./run.sh -r 1.3         # more flashes
./run.sh -t 0.05        # fixed threshold
```

### Choosing a threshold

By default the threshold is **adaptive**: a beat is counted when the bass is
`RATIO` times louder than its average over the last 2 seconds. This works at
any volume and on any output, so most people only ever need `-r`.

A **fixed** threshold (`-t`) fires whenever the bass goes above that level.
It is simpler, but the right value changes with your volume and output device.
Run with `--plot` and pick a level the orange (bass) line only crosses on the
beats you want; the red dashed lines show the current threshold.

## How it works

```
your music ──► monitor of the default output ──► bass.py
                                                  │  delay 200 ms
                                                  │  low-pass ~100 Hz (twice)
                                                  │  beat? (threshold)
                                                  ▼
                                    UDP "A" to 127.0.0.1:5005
                                                  ▼
                                    thinkpad_dot.py (root)
                                      ├─ logo LED via /sys/kernel/debug/ec/ec0/io
                                      └─ keyboard LEDs via /sys/class/leds
```

- **`bass.py`** records the "monitor" of your default output (a copy of what
  is playing) and checks every second whether the default output has changed.
  It sends at most one beat every 100 ms. Audio is processed in ~23 ms blocks
  so the CPU can idle in between (about 0.1% of one core with scipy).
- **`thinkpad_dot.py`** must run as root because it writes to the embedded
  controller. It blinks the logo LED and toggles the keyboard LEDs listed in
  its `__main__` section (`tpacpi::power`, `platform::mute`,
  `input3::capslock`, `platform::micmute`). LEDs that don't exist on your
  machine are skipped. See `ls /sys/class/leds` for what yours has.
- **`keyboard_lights.py`** is the helper for the `/sys/class/leds` LEDs.

## Running the parts by hand

If you'd rather not use `run.sh`:

```sh
sudo modprobe -r ec_sys
sudo modprobe ec_sys write_support=1
sudo python3 thinkpad_dot.py -v     # terminal 1
python3 bass.py --plot -v           # terminal 2
```

## Troubleshooting

Run `./run.sh -v` and check the lines it prints each second.

| You see | Meaning / fix |
| --- | --- |
| `beats sent` stays at 0 | No beats detected. Is something playing? Try `-r 1.3` or `--plot` to look at the signal |
| `beats sent` goes up, no `Received` lines | `thinkpad_dot.py` isn't running. Look for its error higher up |
| `Received` goes up, logo doesn't change | The EC write isn't taking effect. Check `cat /sys/module/ec_sys/parameters/write_support` says `Y`; `run.sh` reloads it, but Secure Boot / kernel lockdown can block it |
| `No 'pulse' audio device found` | PulseAudio/PipeWire isn't reachable. Run as your normal user, not a root login |
| `... not found. Load the EC driver first` | Run the two `modprobe` commands above, or just use `run.sh` |
| `skipping missing LED: ...` | Harmless. That keyboard LED doesn't exist on your model |

To test the LED side on its own (with `thinkpad_dot.py` running):

```sh
python3 -c "import socket; socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b'A', ('127.0.0.1', 5005))"
```

The logo LED should react once.
