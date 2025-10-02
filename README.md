```sh
sudo modprobe -r ec_sys
sudo modprobe ec_sys write_support=1
```

choose the default sound source (monitor)

```py
print(sd.query_devices())
print("Default input device:", sd.default.device)
```


### this displays possible sources, choose the default one's number for device variable.

possible output:
*   5 sof-hda-dsp: - (hw:0,7), ALSA (4 in, 0 out)
*   6 sysdefault, ALSA (128 in, 128 out)
*   7 samplerate, ALSA (128 in, 128 out)
*   8 speexrate, ALSA (128 in, 128 out)
*   9 pulse, ALSA (32 in, 32 out)
*  10 upmix, ALSA (8 in, 8 out)
*  11 vdownmix, ALSA (6 in, 6 out)
*  12 dmix, ALSA (0 in, 2 out)
** 13 default, ALSA (32 in, 32 out)

### run bass.py as normal user and thinkpad_dot.py as root with sudo.