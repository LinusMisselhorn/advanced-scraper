# Deployment auf Hetzner Cloud

Der Scraper läuft auf einem kleinen Hetzner-Cloud-Server. Die Einrichtung erledigt `cloud-init.yaml` beim ersten Start automatisch: Pakete, Python-Umgebung, Code, Firewall, systemd-Dienst und Wochen-Timer. Per Hand bleiben nur der Service-Role-Key und der erste Testlauf.

## Voraussetzungen

- Hetzner-Cloud-Konto mit einem Projekt (z. B. "IMPRESSION")
- SSH-Key auf deinem Rechner. Prüfen mit `cat ~/.ssh/id_ed25519.pub`. Falls nicht vorhanden: `ssh-keygen -t ed25519`
- Der Scraper-Code liegt auf `main` (Pull Request von `feat/indeed-jobspy` gemergt). Sonst in `cloud-init.yaml` die Zeile `REPO_BRANCH=main` auf den gewünschten Branch ändern.
- Das Repo ist öffentlich, deshalb kann der Server ohne Zugangsdaten klonen. Wird es privat, braucht der Server einen Deploy-Key (siehe unten).

## 1. Server anlegen

In der Hetzner Console: Projekt öffnen, **Server hinzufügen**.

| Einstellung | Wert |
|---|---|
| Standort | Nürnberg oder Falkenstein |
| Image | Ubuntu 24.04 |
| Typ | kleinster Shared-vCPU-Typ (x86 oder Arm, beides funktioniert) |
| Netzwerk | öffentliche IPv4 und IPv6 |
| SSH-Key | deinen öffentlichen Key hinzufügen |
| Cloud config | kompletten Inhalt von `deploy/cloud-init.yaml` einfügen |
| Name | `signal-scraper` |

Backups und Volumes sind nicht nötig. Alle Daten liegen in Supabase.

## 2. Einrichtung prüfen

Nach etwa fünf Minuten:

```bash
ssh root@<SERVER-IP>
cloud-init status --wait      # sollte "status: done" melden
cat /root/scraper-setup-done  # Zeitstempel der fertigen Einrichtung
```

Bei Problemen: `less /var/log/cloud-init-output.log`

## 3. Service-Role-Key eintragen

```bash
nano /opt/advanced-scraper/.env
```

`SUPABASE_SERVICE_ROLE_KEY` mit dem Key aus Supabase (Project Settings, API) ersetzen und speichern. Die Datei ist nur für den Nutzer `scraper` lesbar.

## 4. Testlauf ohne Schreiben

```bash
cd /opt/advanced-scraper
sudo -u scraper .venv/bin/python -m scraper.indeed_jobspy --dry-run --show-excluded --format table
```

Darauf achten:

- **Kommen überhaupt Anzeigen?** Bei 403, 429 oder 0 Treffern blockt Indeed vermutlich die Rechenzentrums-IP. Dann zuerst lokal auf dem eigenen Rechner gegentesten.
- **Stimmen die Ausschlüsse?** Großarbeitgeber oder Ketten, die durchrutschen, in `scraper/config.py` ergänzen, committen und auf dem Server `scraper-update` ausführen.

## 5. Erster echter Lauf

```bash
systemctl start indeed-scraper.service
journalctl -u indeed-scraper -n 100 --no-pager
```

Danach in Supabase prüfen, ob Signale vom Typ 1003 angekommen sind.

## 6. Wöchentlichen Lauf aktivieren

```bash
systemctl enable --now indeed-scraper.timer
systemctl list-timers indeed-scraper.timer
```

Der Lauf startet montags um 05:30 Uhr deutscher Zeit, mit bis zu 15 Minuten Streuung. War der Server zu dem Zeitpunkt aus, wird der Lauf beim nächsten Start nachgeholt.

## Wartung

| Aufgabe | Befehl |
|---|---|
| Code aktualisieren | `scraper-update` |
| Letzte Läufe ansehen | `journalctl -u indeed-scraper --since "-14 days"` |
| Lauf per Hand starten | `systemctl start indeed-scraper.service` |
| Timer stoppen | `systemctl disable --now indeed-scraper.timer` |

Sicherheitsupdates spielt Ubuntu über `unattended-upgrades` selbst ein.

## Repo auf privat umstellen

1. Auf dem Server einen Key erzeugen: `sudo -u scraper ssh-keygen -t ed25519 -f /opt/advanced-scraper/.deploy_key -N ""`
2. Den Inhalt von `.deploy_key.pub` in GitHub unter Settings, Deploy keys als Leserecht eintragen.
3. Remote umstellen: `cd /opt/advanced-scraper && sudo -u scraper git remote set-url origin git@github.com:LinusMisselhorn/advanced-scraper.git`
4. `sudo -u scraper git config core.sshCommand "ssh -i /opt/advanced-scraper/.deploy_key -o StrictHostKeyChecking=accept-new"`
5. Mit `scraper-update` testen.
