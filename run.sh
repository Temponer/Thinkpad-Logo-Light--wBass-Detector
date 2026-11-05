#!/usr/bin/env bash
# Start everything with one command:  ./run.sh [bass.py options]
#   e.g.  ./run.sh --plot -v      (see: python3 bass.py --help)
#   - loads the EC driver with write support (if needed)
#   - starts thinkpad_dot.py as root in the background (LED side)
#   - starts bass.py as you (audio side, even if run.sh was started with
#     sudo); closing it stops both
set -e
cd "$(dirname "$(readlink -f "$0")")"   # works through the installed symlink too

for arg in "$@"; do
    case "$arg" in -h|--help) exec python3 bass.py --help ;; esac
done

if [ "$EUID" -eq 0 ] && [ -z "$SUDO_USER" ]; then
    echo "Start this from your normal user (with or without sudo), not a root login:"
    echo "  ./run.sh"
    exit 1
fi

# Installed with ./install.sh --autostart? Then the LED part already runs as
# a system service; only start the audio part here.
if systemctl is-active --quiet thinkpad-led.service 2>/dev/null; then
    if systemctl --user is-active --quiet thinkpad-bass.service 2>/dev/null; then
        echo "Note: the autostart bass detector is also running. For manual tuning stop it first:"
        echo "  systemctl --user stop thinkpad-bass"
    fi
    echo "LED service is running (logs: journalctl -u thinkpad-led -f)"
    exec python3 bass.py "$@"
fi

sudo -v   # ask for the password once, up front

if [ "$(cat /sys/module/ec_sys/parameters/write_support 2>/dev/null)" != "Y" ]; then
    echo "Loading ec_sys with write support..."
    sudo modprobe -r ec_sys 2>/dev/null || true
    sudo modprobe ec_sys write_support=1
fi

LED_ARGS=()
for arg in "$@"; do
    case "$arg" in -v|--verbose) LED_ARGS+=(-v) ;; esac
done

# Save the terminal settings so they can be restored no matter what.
TTY_STATE=$(stty -g 2>/dev/null || true)
restore_tty() { [ -n "$TTY_STATE" ] && stty "$TTY_STATE" 2>/dev/null || true; }

# Keep the background sudo off the terminal (stdin from /dev/null, output
# through a pipe). Otherwise newer sudo puts the terminal in raw mode and
# everything printed afterwards comes out as a broken "staircase".
sudo python3 -u thinkpad_dot.py "${LED_ARGS[@]}" </dev/null > >(cat) 2>&1 &
LED_PID=$!
trap 'sudo kill "$LED_PID" 2>/dev/null; wait "$LED_PID" 2>/dev/null; restore_tty' EXIT

sleep 0.5
if ! kill -0 "$LED_PID" 2>/dev/null; then
    echo "thinkpad_dot.py failed to start (see the error above)."
    exit 1
fi

python3 bass.py "$@"
