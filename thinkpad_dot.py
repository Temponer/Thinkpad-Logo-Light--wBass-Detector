#!/usr/bin/env python3
import time
import keyboard_lights
import socket

class ECLED:
    def __init__(self, kernel_file="/sys/kernel/debug/ec/ec0/io", offset=12, min_interval_ms=100):
        self.kernel_file = kernel_file
        self.offset = offset
        self.min_interval = min_interval_ms / 1000.0  # convert ms to seconds
        self._last_update = 0.0
        self._led_state = False  # Track LED state for toggling

        self.led_off()  # Ensure LED is off at startup

    def _write_byte(self, byte_val, offset=None):
        with open(self.kernel_file, "wb") as f:
            if offset is not None:
                f.seek(offset)
            f.write(bytes([byte_val]))

    def led_on(self):
        self._write_byte(0x0a, self.offset)

    def led_off(self):
        self._write_byte(0x8a, self.offset)

    def led_toggle(self):
        if self._led_state:
            self.led_off()
        else:
            self.led_on()
        self._led_state = not self._led_state

    def led_fade(self):
        self._write_byte(0xaa, self.offset)

    def _update_led_implementation(self):
        self.led_off()
        self.led_fade()

    def update_led(self):
        current_time = time.time()
        if current_time - self._last_update >= self.min_interval:
            self._update_led_implementation()
            self._last_update = current_time

# Example usage
if __name__ == "__main__":
    udp_soc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_soc.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_soc.bind(("127.0.0.1", 5005))

    led = ECLED(min_interval_ms=100) 
    kbled = keyboard_lights.LED(min_interval_ms=100, led = \
    ['tpacpi::power', 'platform::mute','input3::capslock','platform::micmute'])
    while True:
        # led.update_led()
        # time.sleep(0.05)  # main loop sleep
        result = udp_soc.recv(1)  # buffer size is 1 byte
        if result is not None:
            if result == b'A':
                print("Received message:", result)
                led.update_led()
                kbled.update_led()
