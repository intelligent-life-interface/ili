---
name: netzwerk-konventionen
description: Netzwerk-Regeln für den Home-Stack — monitoring-Podman-Netz explizit setzen, Ports 88xx-Konvention, Caddy-Pflichtablauf (Validate → Restart, nie nur reload → Regressionstest → Doku an 3 Stellen), zwei NICs → Caddy-Upstreams auf host.containers.internal statt fester 127.0.0.1/192.168.x.x-IPs, kein IPv6 im LAN, Cloudflare-Tunnel nur mit Access-Policy zuerst, Router-Skripte nur interaktiv mit Backup+Rollback. Enthält net-check.sh (OK/WARN/FAIL wie architektur-review). Nutze bei allem, was Podman-Netzwerke, Container-Ports, Caddyfile, Cloudflare-Tunnel/Access, host.containers.internal, IPv6 oder OpenWrt-Router-Konfiguration betrifft — BEVOR du einen Container startest, einen Caddy-VHost anlegst oder einen Dienst nach aussen öffnest.
---

# netzwerk-konventionen — Regeln für Podman-Netz, Caddy, Tunnel und Router

Diese Regeln sagen, **wie ein Dienst im Netz sichtbar wird** — vom Podman-Netzwerk über
Caddy bis zum Cloudflare-Tunnel. Jede Regel ist mit einem Vorfall belegt (Belege am Ende).
Abgrenzung: `security-konventionen` §3 ist die Kurzfassung (Exposure-Grundsatz), hier steht
die Langfassung + das Prüfskript; Caddy-Detailwissen (Zertifikate, inode-Falle) bleibt in
`~/containers/caddy/CLAUDE.md` — nicht duplizieren, nur verweisen.

## 0. Zuerst prüfen, dann ändern

```bash
~/.claude/skills/netzwerk-konventionen/net-check.sh <containername>
~/.claude/skills/netzwerk-konventionen/net-check.sh <port> [--json]
```

FAIL = nachweislich kaputt (dokumentierter Port, aber nichts lauscht) · WARN = bekannte
Stolperfalle oder ungeklärt · INFO = Hinweis auf etwas, das lokal nicht abschliessend
prüfbar ist (Cloudflare-Access-Policy, Router-seitige IPv6-Abschaltung).

## 1. Podman-Netz (verbindlich)

- Alle `monitoring`-Container mit **explizitem** `--network=monitoring` starten. Ohne das
  fällt Podman auf `slirp4netns`/`pasta` zurück, Container sehen sich dann nicht — Vorfall:
  Grafana ohne `--network` fand `influxdb2` nicht.
- InfluxDB aus Containern erreichbar als `http://influxdb2:8086` (Netz-Alias) oder
  `http://host.containers.internal:8086`.
- HomeAssistant ist die dokumentierte Ausnahme (Host-Netz, wegen Zigbee/mDNS).

## 2. Ports (Konvention)

Eigene FastAPI-/WebGUI-Dienste liegen im Bereich **88xx**; feste Fremd-Ports (InfluxDB
8086, Grafana 3000, Mosquitto 1884→1883, Paperless 8090 etc.) bleiben wie vom Image
vorgegeben. Neuer Port: `~/containers/CONTAINERS.md` ergänzen (Quelle der Wahrheit für
`net-check.sh`s Port-Auflösung), bei den 6 Kern-Containern zusätzlich Root-`CLAUDE.md`.

## 3. Caddy-Pflichtablauf (verbindlich, aus `~/containers/caddy/CLAUDE.md`)

Bei **jeder** Caddyfile-Änderung, keine Abkürzungen:

1. **Lesen**: `~/containers/caddy/CLAUDE.md` komplett, nicht nur diese Kurzfassung.
2. **Editieren**: neuer Block folgt 1:1 einem bestehenden Muster.
3. **Validieren**: `podman exec caddy caddy validate --config /etc/caddy/Caddyfile` — muss
   `Valid configuration` liefern.
4. **Ausrollen**: **immer** `systemctl --user restart container-caddy.service` — **niemals
   nur** `caddy reload` (inode-Falle: ein ersetztes Caddyfile behält die alte Inode im
   Bind-Mount, `reload` meldet trügerisch „unchanged").
5. **Verifizieren**: neuer Host UND ein garantiert funktionierender Bestandshost (z.B.
   `ili.intranet.{$CADDY_DOMAIN}`) müssen beide `200` liefern.
6. **Dokumentieren**: `docs/subdomains-dns.md` + Root-`CLAUDE.md`-Tabelle + Router-Skill-Tag
   (`projects.tsv` + `build_index.py`) — **alle drei**, nicht nur eins.

## 4. Upstream-Adresse (verbindlich seit 04.09.2026)

- Standard-Ziel: `reverse_proxy host.containers.internal:<port>`.
- **Ausnahme bei restriktivem Bind** (Dienst hört nur auf `127.0.0.1` oder eine feste
  LAN-IP statt `0.0.0.0`): `{$CADDY_INTRANET_IP}:<port>` (Env-Platzhalter) verwenden,
  **nie eine hartcodierte IP**.
  - **Why:** Der Server hat zwei NICs (`eth0` DHCP, `eth1` static). Seit dem Reboot
    04.09.2026 löst `host.containers.internal` auf `eth0`/DHCP auf (Podmans bevorzugte
    Default-Route) statt auf die erwartete statische `<SERVER_IP>`. Dienste, die nur auf
    `127.0.0.1` oder die alte statische IP gebunden waren, wurden für Caddy unerreichbar
    (502): ekg 8828, gb 8002, gb-beta 8004.
  - **Diagnose bei jedem 502 hinter Caddy:** `podman exec caddy getent hosts
    host.containers.internal` mit der tatsächlichen Bind-IP des Dienstes (`ss -ltnp`)
    vergleichen, bevor an der App gesucht wird.
- `net-check.sh` warnt automatisch, wenn eine `127.0.0.1`/`192.168.x.x`-IP im
  `reverse_proxy`-Ziel steht.

## 5. Internet-Exposure: Access zuerst, dann Tunnel (verbindlich)

- **Default = nur LAN.** Neue Dienste an `127.0.0.1` oder die LAN-IP binden, intern über
  `*.intranet.{$CADDY_DOMAIN}` erreichbar.
- Soll ein Dienst öffentlich erreichbar sein: **zuerst** die Cloudflare-Access-Policy
  vollständig konfigurieren und verifizieren, **erst danach** den Public-Hostname/die
  Caddy-Route freischalten. Sofort von extern testen (`curl --resolve` mit externer IP
  oder Mobilfunk — LAN-Tests sind bei Split-DNS wertlos).
  - **Why:** Am 24.05.2026 wurde beim Tunnel-Setup für `home.<DOMAIN>` der Public
    Hostname vor der Access-Policy angelegt — das Dashboard war ~7 Minuten ungeschützt im
    Internet.
- Diese Reihenfolge ist **nicht lokal automatisiert prüfbar** (Access-Policy lebt in der
  Cloudflare-Zero-Trust-Konsole) — `net-check.sh` gibt nur einen INFO-Hinweis, wenn ein
  Name im öffentlichen `*.{$CADDY_DOMAIN}`-Block auftaucht. Manuell verifizieren, nicht
  auf das Skript verlassen.

## 6. Kein IPv6 im LAN (verbindlich)

- Heimnetz (`<LAN_SUBNET>`) bleibt IPv4-only. Grund: einfacheres Routing/Firewalling
  und keine IPv6-Leaks am SOCKS-Killswitch vorbei (Chile-Exit deckt nur IPv4 ab).
- Netzweiter Hebel: AdGuard auf OpenWrt (`<ROUTER_IP>`) hat `aaaa_disabled: true` — keine
  AAAA-Records, alle Clients bleiben auf v4. Vollständige RA/DHCPv6-Abschaltung sitzt an
  der Swisscom Internet-Box (Gateway) — ausserhalb dieses Servers.
- `net-check.sh` prüft nur den **lokalen Host** (`ip -6 addr show scope global`); die
  Router-/Gateway-Einstellung ist von hier aus nicht prüfbar.

## 7. Router-Skripte (verbindlich seit 09.09.2026)

- Änderungen an OpenWrt (`~/Projekte/openwrt-router/*.sh`, z.B. Split-DNS, IPv6/DHCP,
  Root-PW) laufen **interaktiv** über versionierte, gesicherte Skripte — nie ad hoc per
  SSH. Jedes Skript sichert vorher die betroffenen Configs und hat bei Netz-/DHCP-/
  Firewall-Wirkung einen Rollback-Timer.
- **Automat, Subagenten und Loop-Sessions bleiben ausgeschlossen** (Boards
  `openwrt-router`/`router` `auto:false`) — Grund: ein Automat-Lauf legte am 05.09.2026
  das Netz per VLAN-Fehlkonfiguration lahm (BPI-R4 nicht mehr erreichbar, Neuaufsetzung
  nötig).

## Werkzeuge (nicht neu bauen)

| Zweck | Werkzeug |
|---|---|
| Caddyfile validieren/ausrollen | siehe Abschnitt 3, `~/containers/caddy/CLAUDE.md` |
| Neue Subdomain / Split-DNS | `~/containers/caddy/docs/subdomains-dns.md` |
| Tunnel-/Access-Details | `~/containers/caddy/docs/cloudflare-tunnel.md` |
| Router-Backup/Rollback | `~/Projekte/openwrt-router/router_backup.py` |
| Diesen Skill prüfen | `net-check.sh` (hier im Skill) |
