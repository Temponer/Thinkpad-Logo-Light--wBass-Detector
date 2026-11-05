#!/usr/bin/env bash
# Install the ThinkPad bass LED.
#
#   ./install.sh               add the "thinkpad-bass" command (runs run.sh)
#   ./install.sh --autostart   also start it automatically at every login
#   ./install.sh --uninstall   remove everything this script installed
#
# Files stay in this folder (the command is a link to it), so a later
# "git pull" updates the installed version too. Don't move or delete the
# folder after installing; run ./install.sh again if you do move it.
set -e
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
BIN_DIR="$HOME/.local/bin"
CMD="$BIN_DIR/thinkpad-bass"
USER_UNIT_DIR="$HOME/.config/systemd/user"
LED_UNIT=/etc/systemd/system/thinkpad-led.service
BASS_UNIT="$USER_UNIT_DIR/thinkpad-bass.service"
MODLOAD=/etc/modules-load.d/thinkpad-bass.conf
MODOPTS=/etc/modprobe.d/thinkpad-bass.conf
CONF="$HOME/.config/thinkpad-bass.conf"

if [ "$EUID" -eq 0 ]; then
    echo "Run ./install.sh as your normal user (no sudo); it asks for the password when needed."
    exit 1
fi

AUTOSTART=0
case "${1:-}" in
    "") ;;
    --autostart) AUTOSTART=1 ;;
    --uninstall)
        echo "Removing thinkpad-bass..."
        systemctl --user disable --now thinkpad-bass.service 2>/dev/null || true
        rm -f "$BASS_UNIT" "$CMD" "$CONF"
        systemctl --user daemon-reload 2>/dev/null || true
        if [ -e "$LED_UNIT" ] || [ -e "$MODLOAD" ] || [ -e "$MODOPTS" ]; then
            sudo systemctl disable --now thinkpad-led.service 2>/dev/null || true
            sudo rm -f "$LED_UNIT" "$MODLOAD" "$MODOPTS"
            sudo systemctl daemon-reload
        fi
        echo "Done. (This folder and your Python packages were left alone.)"
        exit 0 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1 (try --help)"; exit 1 ;;
esac

PY="$(command -v python3)" || { echo "python3 not found"; exit 1; }

# ---- 1. dependencies ----
echo "Checking Python packages..."
missing=()
for mod in sounddevice numpy scipy matplotlib; do
    "$PY" -c "import importlib.util as u, sys; sys.exit(u.find_spec('$mod') is None)" \
        || missing+=("$mod")
done
if [ ${#missing[@]} -gt 0 ]; then
    echo "  installing: ${missing[*]}"
    "$PY" -m pip install --user "${missing[@]}" \
        || "$PY" -m pip install --user --break-system-packages "${missing[@]}"
fi
if ! command -v pactl >/dev/null; then
    echo "  'pactl' is missing. Install it with:  sudo apt install pulseaudio-utils"
    echo "  (or your distro's equivalent), then run this script again."
    exit 1
fi

# ---- 2. the command ----
chmod +x "$DIR/run.sh" "$DIR/install.sh"
mkdir -p "$BIN_DIR"
ln -sf "$DIR/run.sh" "$CMD"
echo "Installed command: thinkpad-bass  ->  $DIR/run.sh"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "  Note: $BIN_DIR is not on your PATH yet. Log out and back in, or add"
       echo "        export PATH=\"\$HOME/.local/bin:\$PATH\"   to your ~/.bashrc / ~/.zshrc" ;;
esac

if [ "$AUTOSTART" -eq 0 ]; then
    echo
    echo "Run it with:  thinkpad-bass        (options: thinkpad-bass --help)"
    echo "To start it automatically at login:  ./install.sh --autostart"
    exit 0
fi

# ---- 3. autostart ----
echo "Setting up autostart (needs sudo for the LED part)..."
# load the EC driver with write support at every boot
sudo mkdir -p "$(dirname "$MODOPTS")" "$(dirname "$MODLOAD")" "$(dirname "$LED_UNIT")"
echo "options ec_sys write_support=1" | sudo tee "$MODOPTS" >/dev/null
echo "ec_sys" | sudo tee "$MODLOAD" >/dev/null

# LED controller: system service, runs as root
sudo tee "$LED_UNIT" >/dev/null <<UNIT
[Unit]
Description=ThinkPad logo LED bass blinker (LED side)

[Service]
ExecStartPre=-/sbin/modprobe -r ec_sys
ExecStartPre=/sbin/modprobe ec_sys write_support=1
ExecStart=/usr/bin/python3 -u $DIR/thinkpad_dot.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now thinkpad-led.service

# Bass detector: user service, runs as you inside your audio session
mkdir -p "$USER_UNIT_DIR"
if [ ! -e "$CONF" ]; then
    cat > "$CONF" <<'TXT'
# Options for the autostarted bass detector (same as: thinkpad-bass --help).
# After editing, apply with:  systemctl --user restart thinkpad-bass
# Examples:  ARGS=-r 1.3      ARGS=-t 0.05      ARGS=--min-level 0.02
ARGS=
TXT
fi
cat > "$BASS_UNIT" <<UNIT
[Unit]
Description=ThinkPad logo LED bass blinker (audio side)
After=pipewire-pulse.service pulseaudio.service

[Service]
EnvironmentFile=-%h/.config/thinkpad-bass.conf
ExecStart=$PY -u $DIR/bass.py \$ARGS
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now thinkpad-bass.service

sleep 2
echo
if systemctl is-active --quiet thinkpad-led.service && \
   systemctl --user is-active --quiet thinkpad-bass.service; then
    echo "Autostart is on and running. Play some music!"
else
    echo "Something didn't start. Check:"
fi
cat <<'TXT'

  status:   systemctl status thinkpad-led ; systemctl --user status thinkpad-bass
  logs:     journalctl -u thinkpad-led -f ; journalctl --user -u thinkpad-bass -f
  stop:     systemctl --user stop thinkpad-bass
  options:  edit ~/.config/thinkpad-bass.conf, then systemctl --user restart thinkpad-bass
  remove:   ./install.sh --uninstall
TXT
