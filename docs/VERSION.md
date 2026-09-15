# Which ili version is installed?

Pick the first method that works in your situation — they are ordered from the
easiest to the one that still answers when nothing is running.

## 1. In ili itself

The version sits next to the logo in the navigation, on every page. Hover over it
for the commit and the build date. A small `↑` means a newer release is out;
clicking the label opens the release notes.

## 2. The API (stack running)

```bash
curl -s http://localhost:8080/api/version
```

```json
{
  "version": "0.1.19",
  "commit": "f3913a9c…",
  "build_date": "2026-09-15T20:30:00.000Z",
  "channel": "stable"
}
```

This goes through `web` to `api` — both must be up.

## 3. Image labels (works even when containers are stopped)

Every image published to ghcr.io / Docker Hub carries its version as an OCI label.
Ask the **container**, not the tag — `ghcr.io/toa1984/ili:latest` on your disk may
be newer than what is actually running:

```bash
docker inspect ili-api --format '{{index .Config.Labels "org.opencontainers.image.version"}}'
docker inspect ili-api --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'   # commit
docker inspect ili-api --format '{{index .Config.Labels "org.opencontainers.image.created"}}'    # build time
```

The same works for `ili-web` and `ili-terminal`, as long as the container exists
(`docker ps -a`).

`docker compose images` does **not** answer the question: it shows the tag you
pulled, which for a normal install is `latest`.

## 4. The api start log (0.1.19 and later)

```bash
docker compose logs api | grep "starting"
# ili 0.1.19 starting (commit f3913a9…, built 2026-09-15T20:30:00.000Z, channel stable)
```

## 5. Built from a git checkout

Images you built yourself have no release labels, and commit/build date read
`unknown`. The version is the `VERSION` file in your checkout:

```bash
cat VERSION
```

## What the fields mean

| Field | Meaning |
|-------|---------|
| `version` | ili release (semver) — from the `VERSION` file baked into the image |
| `commit` | git commit the image was built from (`unknown` for self-built images) |
| `build_date` | when the image was built (`unknown` for self-built images) |
| `channel` | `stable` or `beta`, set with `ILI_UPDATE_CHANNEL` |

## Update check

```bash
curl -s http://localhost:8080/api/update-status
```

ili asks GitHub for the latest release of its channel and caches the answer for
one hour, so a release published a moment ago can take up to an hour to show up.
To switch the check off entirely, set `ILI_UPDATE_CHECK=off` in `.env` and
recreate the api container (`docker compose up -d api`).
