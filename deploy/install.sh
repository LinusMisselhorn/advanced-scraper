#!/usr/bin/env bash
# Installiert oder aktualisiert advanced-scraper auf einem bestehenden Server.
#
# Aufruf als root:
#   Erstinstallation: curl -fsSL https://raw.githubusercontent.com/LinusMisselhorn/advanced-scraper/main/deploy/install.sh | bash
#   Update:           bash /opt/advanced-scraper/deploy/install.sh
#
# Was das Skript anfasst:
#   - Systemnutzer "scraper" (ohne Login)
#   - Ordner /opt/advanced-scraper (Code, eigene Python-Version, .venv, .env)
#   - /usr/local/bin/uv, falls noch nicht vorhanden
#   - systemd-Units indeed-scraper.service und indeed-scraper.timer
# Was es NICHT anfasst: Firewall, Webserver, Docker, System-Python, andere Dienste.
# Der Timer wird nicht aktiviert. Die .env wird nie überschrieben.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/LinusMisselhorn/advanced-scraper.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
APP_DIR="/opt/advanced-scraper"
APP_USER="scraper"
PYTHON_VERSION="3.12"

log() { printf '\n==> %s\n' "$*"; }

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Bitte als root ausführen." >&2
  exit 1
fi

log "Voraussetzungen prüfen"
for cmd in git curl systemctl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "$cmd fehlt. Installieren mit: apt-get install -y $cmd" >&2
    exit 1
  fi
done

if ! command -v uv >/dev/null 2>&1; then
  log "uv installieren (verwaltet eine eigene Python-Version, System-Python bleibt unberührt)"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi

if ! id "$APP_USER" >/dev/null 2>&1; then
  log "Systemnutzer $APP_USER anlegen"
  useradd --system --home-dir "$APP_DIR" --no-create-home --shell /usr/sbin/nologin "$APP_USER"
fi

if [[ -d "$APP_DIR/.git" ]]; then
  log "Code aktualisieren ($REPO_BRANCH)"
  sudo -u "$APP_USER" git -C "$APP_DIR" fetch --quiet origin "$REPO_BRANCH"
  sudo -u "$APP_USER" git -C "$APP_DIR" checkout --quiet "$REPO_BRANCH"
  sudo -u "$APP_USER" git -C "$APP_DIR" pull --quiet --ff-only origin "$REPO_BRANCH"
else
  log "Code klonen ($REPO_BRANCH)"
  git clone --quiet --branch "$REPO_BRANCH" "$REPO_URL" "$APP_DIR"
  chown -R "$APP_USER:$APP_USER" "$APP_DIR"
fi

log "Python $PYTHON_VERSION und Abhängigkeiten"
export UV_PYTHON_INSTALL_DIR="$APP_DIR/.python"
export UV_CACHE_DIR="$APP_DIR/.uv-cache"
cd "$APP_DIR"
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
  sudo -u "$APP_USER" -E uv venv --quiet --python "$PYTHON_VERSION" "$APP_DIR/.venv"
fi
sudo -u "$APP_USER" -E uv pip install --quiet --python "$APP_DIR/.venv/bin/python" -r requirements.txt

if [[ ! -f "$APP_DIR/.env" ]]; then
  log ".env aus Vorlage anlegen (Key muss noch eingetragen werden)"
  install -m 600 -o "$APP_USER" -g "$APP_USER" "$APP_DIR/.env.example" "$APP_DIR/.env"
fi

log "systemd-Units installieren"
install -m 644 "$APP_DIR/deploy/systemd/indeed-scraper.service" /etc/systemd/system/indeed-scraper.service
install -m 644 "$APP_DIR/deploy/systemd/indeed-scraper.timer" /etc/systemd/system/indeed-scraper.timer
systemctl daemon-reload

log "Fertig: $(sudo -u "$APP_USER" git -C "$APP_DIR" rev-parse --short HEAD)"
if grep -q "dein-service-role-key-hier" "$APP_DIR/.env"; then
  echo "Nächster Schritt: Key eintragen mit  nano $APP_DIR/.env"
fi
echo "Testlauf:        cd $APP_DIR && sudo -u $APP_USER .venv/bin/python -m scraper.indeed_jobspy --dry-run --show-excluded --format table"
echo "Timer-Status:    systemctl is-enabled indeed-scraper.timer || true"
