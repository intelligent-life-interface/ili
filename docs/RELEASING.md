# Releasing ili

Versions are **manual semver** (`MAJOR.MINOR.PATCH`) — no automatic bumping.
A release is a git tag; GitHub Actions builds and pushes the images.

## Images

| Image | Built from | Role |
|---|---|---|
| `ghcr.io/toa1984/ili` | `Containerfile` | FastAPI backend (`api`) |
| `ghcr.io/toa1984/ili-web` | `Containerfile.web` | nginx frontend (`web`) |
| `ghcr.io/toa1984/ili-terminal` | `deploy/Containerfile.terminal` | optional browser terminal |

Each tag `vX.Y.Z` produces the image tags `X.Y.Z`, `X.Y` and `latest`
(`latest` is skipped for pre-releases such as `v0.2.0-rc1`). A manual run of the
workflow (*Actions → Release images → Run workflow*) pushes `edge` from the
chosen branch without touching `latest`. Platforms: `linux/amd64` and `linux/arm64`.

## Steps

1. Make sure `main` contains the state you want to ship and that the stack
   builds and starts locally (`docker compose up -d --build`, open the browser).
2. Bump `VERSION` and commit it: `echo 0.2.0 > VERSION && git commit -am "Release 0.2.0"`.
3. Tag and push:
   ```bash
   git tag v0.2.0
   git push origin main --tags
   ```
4. Watch the run: `gh run watch` (or the Actions tab). Three jobs, one per image.
5. Check the packages: `gh api /user/packages?package_type=container`.

## Visibility

The packages inherit the repository visibility. While the repository is private,
`docker compose pull` needs a login (`docker login ghcr.io` with a token that has
`read:packages`). Making the repository **and** each of the three packages public
is a separate, manual decision — it is never done by automation.

## Users update with

```bash
docker compose pull && docker compose up -d
```
(pinned version: `ILI_VERSION=0.2.0` in `.env`).
