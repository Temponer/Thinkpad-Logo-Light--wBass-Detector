#!/usr/bin/env python3
import os
import time


class LED:
    """Blink LEDs exposed under /sys/class/leds/<name>/brightness.

    LEDs that don't exist on this machine are skipped with a warning instead
    of crashing (names like 'input3::capslock' differ between machines and can
    change after a reboot or when devices are plugged in).
    """

    def __init__(self, led=("platform::mute",), min_interval_ms=100):
        if isinstance(led, str):
            led = [led]
        self.led_file = []
        for name in led:
            path = f"/sys/class/leds/{name}/brightness"
            if os.path.exists(path):
                self.led_file.append(path)
            else:
                print(f"[keyboard_lights] skipping missing LED: {name}")
        self.min_interval = min_interval_ms / 1000.0  # convert ms to seconds
        self._last_update = 0.0
        self._led_state = False  # Track LED state for toggling

        self.led_off()  # Ensure LED is off at startup

    def _write_str(self, string: str):
        for file in list(self.led_file):
            try:
                with open(file, "w") as f:
                    f.write(string)
            except OSError as e:
                print(f"[keyboard_lights] can't write {file}: {e} (disabling it)")
                self.led_file.remove(file)

    def led_on(self):
        self._write_str("1")

    def led_off(self):
        self._write_str("0")

    def led_toggle(self):
        if self._led_state:
            self.led_off()
        else:
            self.led_on()
        self._led_state = not self._led_state

    def _update_led_implementation(self):
        self.led_toggle()

    def update_led(self):
        current_time = time.time()
        if current_time - self._last_update >= self.min_interval:
            self._update_led_implementation()
            self._last_update = current_time
