# Reporting bugs and ideas to the ili project — what leaves your instance

ili can talk back to its home repository (`Toa1984/ili-public`) in three ways.
**All of them are off by default, and nothing is sent without your account.**

| Path | Needs | What is sent | When |
|---|---|---|---|
| **Browser form** (deep link) | nothing — you submit on github.com with your own account | the pre-filled text you see in the form | only when you click "submit" on GitHub |
| **Card → issue** ("Als Issue exportieren") | GitHub login in ili (see below) | the card's title + description, sanitized, shown to you first and editable | only on your explicit click |
| **Automatic error reports** | GitHub login **and** the checkbox *Fehler automatisch anonymisiert melden* | technical data only (see list) | when an unhandled error happens (max. 10 per day) |

## Signing in — GitHub App device flow

Settings panel (⚙️ Darstellung → *GitHub-Rückkanal*) → **Mit GitHub anmelden**. ili shows a
short code; enter it on <https://github.com/login/device> while logged in with **your** GitHub
account (free). ili then holds a user token that can only **create issues and comments** in the
ili repository — that is the only permission the GitHub App "ili" asks for.

* No shared secret ships with ili: the installation only knows the App's public client id.
* The token is stored in `data/github/github_auth.json` (mode 0600) — never in `user_settings.json`,
  which is exportable. **Abmelden** deletes it.
* The token expires after 8 hours and is refreshed automatically; remove it any time.

## What automatic reports contain — and what they never contain

Sent: ili version / channel / commit · the component (route or page path) · exception type ·
the error message and the stack frames **inside `app/`** · an error hash for de-duplication.

Before sending, `app/services/report_sanitizer.py` removes or masks: home directories
(`/home/<user>`, `/Users/<user>`, `C:\Users\<user>`), IPv4/IPv6 addresses, host names
(`*.local`, `*.intranet.*`, `*.lan`, any FQDN), e-mail addresses, tokens/keys/passwords,
URL query strings.

**Never sent:** board names, card contents, request bodies, headers, cookies, your Claude or
other API keys, anything from `boards/` or `data/`.

## Audit: see what was sent

Settings panel → **Letzte Meldungen**, or the file `data/github/github_reports.log` (one JSON
line per report with the exact title and body). **Vorschau** shows what a report would look like
without sending anything.

## De-duplication and limits

Identical errors (same hash) add a short "+1 on version x" comment to the existing issue instead of
opening a new one. At most 10 new issues/comments per day per instance.

## Operator notes

* `ILI_GITHUB_APP_CLIENT_ID` — public client id of the GitHub App (set in the compose `environment`).
* `ILI_GITHUB_ISSUES_REPO` — defaults to `Toa1984/ili-public`; forks can point it elsewhere.
* `ILI_GITHUB_REPORTS_PER_DAY` — daily cap, default 10.
