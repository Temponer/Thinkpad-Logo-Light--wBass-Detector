#!/usr/bin/env bash
# Start everything with one command:  ./run.sh [bass.py options]
#   e.g.  ./run.sh --plot -v      (see: python3 bass.py --help)
#   - loads the EC driver with write support (if needed)
#   - starts thinkpad_dot.py as root in the background (LED side)
#   - starts bass.py as you (audio side, even if run.sh was started with
#     sudo); closing it stops both
set -e
cd "$(dirname "$0")"

for arg in "$@"; do
    case "$arg" in -h|--help) exec python3 bass.py --help ;; esac
done

if [ "$EUID" -eq 0 ] && [ -z "$SUDO_USER" ]; then
    echo "Start this from your normal user (with or without sudo), not a root login:"
    echo "  ./run.sh"
    exit 1
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

sudo python3 thinkpad_dot.py "${LED_ARGS[@]}" &
LED_PID=$!
trap 'sudo kill "$LED_PID" 2>/dev/null; wait "$LED_PID" 2>/dev/null' EXIT

sleep 0.5
if ! kill -0 "$LED_PID" 2>/dev/null; then
    echo "thinkpad_dot.py failed to start (see the error above)."
    exit 1
fi

python3 bass.py "$@"
