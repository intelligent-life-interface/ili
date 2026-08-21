# deploy/systemd/

Optionale systemd-User-Units für einen bare-metal-Betrieb (ohne Containerfile/Compose):

- `dashboard-api.service` — startet das FastAPI-Backend direkt via `venv`.
- `dashboard-runner.service` — Webhook-Runner (z.B. für n8n-Trigger).

Beide nutzen `%h` (systemd-Kurzform für das Home-Verzeichnis des Units) statt fest
codierter Pfade — vor dem Kopieren nur `WorkingDirectory`/`ExecStart` an den eigenen
Installationsort anpassen, falls abweichend von `~/containers/dashboard`.

```bash
cp deploy/systemd/<unit> ~/.config/systemd/user/<unit>
systemctl --user daemon-reload
systemctl --user enable --now <unit>
```

Für den Standard-Weg (empfohlen) siehe stattdessen `QUICKSTART.md` (Docker/Podman
Compose) — diese Units sind nur für wer explizit ohne Container betreiben will.
