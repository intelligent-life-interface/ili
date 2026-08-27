# Releasing ili

Versions are **manual semver** (`MAJOR.MINOR.PATCH`) — no automatic bumping.
A release is a git tag; GitHub Actions builds and pushes the images.

## Images

| Image | Built from | Role |
|---|---|---|
| `ghcr.io/toa1984/ili` | `Containerfile` | FastAPI backend (`api`) |
| `ghcr.io/toa1984/ili-web` | `Containerfile.web` | nginx frontend (`web`) |
| `ghcr.io/toa1984/ili-terminal` | `deploy/Containerfile.terminal` | optional browser terminal |

**Each repo builds only its own images — never cross-project** (decision
2026-08-24). The workflow derives the image namespace from the repository it
runs in:

| Repository | Images | Registries |
|---|---|---|
| `Toa1984/ili-public` | `ghcr.io/toa1984/ili{,-web,-terminal}` | ghcr + Docker Hub mirror `docker.io/toa1984/ili{,-web,-terminal}` |
| `Toa1984/ili-coding` (private workshop) | `ghcr.io/toa1984/ili-coding{,-web,-terminal}` | ghcr only (private packages), no Docker Hub |

The published `ili*` ghcr packages are linked to `Toa1984/ili-public`; only
runs from that repo can write them. The Docker Hub mirror exists for
discoverability (only Docker Hub is indexed by `docker search`, ghcr is not)
and needs the repo secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`
(personal access token, read/write; stored in `config.env` on the home server
as `DOCKERHUB_USER`/`DOCKERHUB_TOKEN`). Repo short descriptions and READMEs
on Docker Hub are maintained manually.

Each tag `vX.Y.Z` produces the image tags `X.Y.Z`, `X.Y` and `latest`
(`latest` is skipped for pre-releases such as `v0.2.0-rc1`). A manual run of the
workflow (*Actions → Release images → Run workflow*) pushes `edge` from the
chosen branch without touching `latest`. Platforms: `linux/amd64` and `linux/arm64`.

## Checklist before tagging

Lessons from 0.1.8–0.1.10 — every item here once cost a release or a user.

- [ ] **Base images current:** Node LTS in `deploy/Containerfile.terminal` (Node
      20 went EOL 2026-04 while the image still used it), Debian release in all
      `FROM` lines (`trixie` = 13), `nginx:alpine` for web.
- [ ] **Vulnerability scan of the freshly built images** (Trivy, containerised —
      nothing to install; the workflow repeats this after the push):
      ```bash
      docker run --rm -v trivy-cache:/root/.cache/trivy docker.io/aquasec/trivy:latest \
        image --ignore-unfixed --severity CRITICAL,HIGH \
        --skip-dirs /usr/local/lib/node_modules/npm ghcr.io/toa1984/ili:edge
      ```
      Fixable CRITICAL/HIGH must be 0 for all three images. Unfixed Debian CVEs
      (perl, curl, openssl, ...) are present in every current base image — note
      them, do not chase them. Findings inside npm's own `node_modules` are
      skipped for the same reason (npm@latest is installed at build time).
      The api image ships without pip (removed after the build — pip's vendored
      msgpack/setuptools copies are flagged but cannot be updated separately).
- [ ] **Registry install path works without a checkout:** in an EMPTY folder run
      `docker run --rm -v "$PWD":/out <image>:edge init`, then check that the
      written compose files contain **no `build:` block** (`grep build: *.yml`)
      and that `.env` has `COMPOSE_FILE=` active. Then `docker compose up -d` and
      open the browser — the terminal container must be running too.
- [ ] **Every user-facing hint says the same thing** — including the two
      settings a first-time user must make: Claude access (`CLAUDE_CODE_OAUTH_TOKEN`
      or `ANTHROPIC_API_KEY`) and `TERMINAL_PASSWORD` (empty = generated, read via
      `docker compose logs web | grep ili-setup`): `init` output
      (`docker-entrypoint.sh`), QUICKSTART.md, README, Docker Hub description
      (`hub.docker.com/r/toa1984/ili`). Docker Hub is edited by hand — do not
      forget it.
- [ ] **Workflow runs in `Toa1984/ili-public`** (see above) — secrets
      `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN` present there.
- [ ] **Mirror check:** before writing a file into `ili-public` compare its blob
      SHA with the workshop state it was copied from (`git rev-parse HEAD:<file>`
      vs. the contents API `sha`). README.md diverges between the repos — patch,
      do not overwrite.
- [ ] `VERSION` bumped in the workshop **and** in `ili-public`; tag on the
      commit that carries the bump.
- [ ] After the run: tags `X.Y.Z`, `X.Y`, `latest` visible on ghcr **and**
      Docker Hub for all three images; GitHub release entry created with notes.

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
