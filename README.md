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

### run bass.py as normal user and thinkpad_dot.py as root with sudo.