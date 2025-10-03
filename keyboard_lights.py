#!/usr/bin/env python3
import time
import socket

class LED:
    def __init__(self, led = "platform::mute", offset=12, min_interval_ms=100):
        self.led_file = [f"/sys/class/leds/{l}/brightness" for l in led]
        self.offset = offset
        self.min_interval = min_interval_ms / 1000.0  # convert ms to seconds
        self._last_update = 0.0
        self._led_state = False  # Track LED state for toggling

        self.led_off()  # Ensure LED is off at startup

    def _write_byte(self, byte_val, offset=None):
        with open(file, "w") as f:
            if offset is not None:
                f.seek(offset)
            f.write(bytes([byte_val]))

    def _write_str(self, string:str):
      for file in self.led_file:
        with open(file,"w") as f:
            f.write(string)

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

    # def led_fade(self):
    #     self._write_byte(0xaa, self.offset)

    def _update_led_implementation(self):
        # self.led_off()
        # self.led_fade()s
        self.led_toggle()

    def update_led(self):
        current_time = time.time()
        if current_time - self._last_update >= self.min_interval:
            self._update_led_implementation()
            self._last_update = current_time
