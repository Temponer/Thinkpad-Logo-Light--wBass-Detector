```sh
sudo modprobe -r ec_sys
sudo modprobe ec_sys write_support=1
```

## Sound source

`bass.py` listens to **whatever is currently playing on your default output**
(the "monitor" of the default sink), not the microphone. It follows the output
automatically: laptop speakers when nothing is plugged in, headphones /
Bluetooth / HDMI when they become the default. It checks every second and
switches by itself.

Needs PulseAudio or PipeWire (`pipewire-pulse`) and `pactl`
(`sudo apt install pulseaudio-utils` if it is missing).

To pin a specific source instead, set `SOURCE` in `bass.py` to one of:

```sh
pactl list short sources
```

(use a name ending in `.monitor` to capture an output).

## Trigger level

By default the trigger is adaptive (`PEAK_THRESHOLD = None`): the LED fires when
the bass is `BEAT_RATIO` times louder than its average over the last
`AVG_SEC` seconds, so it works at any volume. The red dashed lines on the plot
show the current trigger level and the title counts the hits sent. Lower
`BEAT_RATIO` (e.g. 1.3) for more flashes, raise it (e.g. 2.0) for fewer, or
set `PEAK_THRESHOLD` to a number for a fixed level.

To check the LED side alone, with `thinkpad_dot.py` running:

```sh
python3 -c "import socket; socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b'A', ('127.0.0.1', 5005))"
```

It should print `Received message` and blink.

## Run

One command starts everything (asks for your sudo password once, loads
`ec_sys` with write support if needed, runs the LED part as root and the audio
part as you). Close the plot window or press Ctrl+C to stop both:

```sh
./run.sh
```

Don't run it with `sudo`. Manual alternative: `sudo python3 thinkpad_dot.py`
in one terminal and `python3 bass.py` in another.