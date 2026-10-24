# Deployment auf dem bestehenden Hetzner-Server

Der Scraper läuft auf dem vorhandenen Hetzner-Server, auf dem auch der Dialer und `ai.impression-marketing.de` laufen. Das Installationsskript ist darauf ausgelegt, daneben zu existieren, ohne etwas anderes anzufassen.

## Was installiert wird

| Bestandteil | Ort |
|---|---|
| Systemnutzer `scraper` (ohne Login) | |
| Code, eigene Python-Version, `.venv`, `.env` | `/opt/advanced-scraper` |
| `uv` (Python-Paketmanager), falls nicht vorhanden | `/usr/local/bin/uv` |
| systemd-Dienst und Wochen-Timer | `/etc/systemd/system/indeed-scraper.*` |

Nicht angefasst werden: Firewall, Webserver, Docker, System-Python und alle anderen Dienste. Der Scraper bekommt eine eigene Python-Version über `uv`, deshalb spielt die Ubuntu-Version keine Rolle.

Damit er den Dialer und die Website nicht ausbremst, läuft der Dienst mit niedriger CPU- und I/O-Priorität und höchstens 1 GB Arbeitsspeicher.

## 1. Installieren

Voraussetzung: Die Pull Requests sind auf `main` gemergt.

```bash
ssh root@<SERVER-IP>
curl -fsSL https://raw.githubusercontent.com/LinusMisselhorn/advanced-scraper/main/deploy/install.sh | bash
```

## 2. Service-Role-Key eintragen

```bash
nano /opt/advanced-scraper/.env
```

`SUPABASE_SERVICE_ROLE_KEY` mit dem Key aus Supabase (Project Settings, API) ersetzen. Die Datei ist nur für den Nutzer `scraper` lesbar.

## 3. Testlauf ohne Schreiben

```bash
cd /opt/advanced-scraper
sudo -u scraper .venv/bin/python -m scraper.indeed_jobspy --dry-run --show-excluded --format table
```

Darauf achten:

- **Kommen überhaupt Anzeigen?** Bei 403, 429 oder 0 Treffern blockt Indeed vermutlich die Rechenzentrums-IP. Dann zuerst lokal auf dem eigenen Rechner gegentesten.
- **Stimmen die Ausschlüsse?** Großarbeitgeber oder Ketten, die durchrutschen, in `scraper/config.py` ergänzen, committen und das Skript erneut ausführen.

## 4. Erster echter Lauf

```bash
systemctl start indeed-scraper.service
journalctl -u indeed-scraper -n 100 --no-pager
```

Danach in Supabase prüfen, ob Signale vom Typ 1003 angekommen sind.

## 5. Wöchentlichen Lauf aktivieren

```bash
systemctl enable --now indeed-scraper.timer
systemctl list-timers indeed-scraper.timer
```

Der Lauf startet montags um 05:30 Uhr deutscher Zeit, mit bis zu 15 Minuten Streuung. War der Server zu dem Zeitpunkt aus, wird der Lauf beim nächsten Start nachgeholt.

## Wartung

| Aufgabe | Befehl |
|---|---|
| Code aktualisieren | `bash /opt/advanced-scraper/deploy/install.sh` |
| Letzte Läufe ansehen | `journalctl -u indeed-scraper --since "-14 days"` |
| Lauf per Hand starten | `systemctl start indeed-scraper.service` |
| Timer stoppen | `systemctl disable --now indeed-scraper.timer` |
| Komplett entfernen | `systemctl disable --now indeed-scraper.timer; rm /etc/systemd/system/indeed-scraper.*; systemctl daemon-reload; rm -rf /opt/advanced-scraper; userdel scraper` |

Das Installationsskript ist idempotent: Mehrfaches Ausführen aktualisiert den Code und die Abhängigkeiten, die `.env` bleibt erhalten.

## Repo auf privat umstellen

Dann kann der Server nicht mehr ohne Zugangsdaten klonen:

1. Key erzeugen: `sudo -u scraper ssh-keygen -t ed25519 -f /opt/advanced-scraper/.deploy_key -N ""`
2. Inhalt von `.deploy_key.pub` in GitHub unter Settings, Deploy keys mit Leserecht eintragen.
3. `cd /opt/advanced-scraper && sudo -u scraper git remote set-url origin git@github.com:LinusMisselhorn/advanced-scraper.git`
4. `sudo -u scraper git config core.sshCommand "ssh -i /opt/advanced-scraper/.deploy_key -o StrictHostKeyChecking=accept-new"`
5. Skript mit `REPO_URL=git@github.com:LinusMisselhorn/advanced-scraper.git bash /opt/advanced-scraper/deploy/install.sh` testen.
