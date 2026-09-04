# Contributing to ili — Crowd Development Workflow

ili implements a **crowd-development workflow** where contributions flow through GitHub Issues and Pull Requests. You can take an idea card from an ili instance, work on it locally, and submit your solution back to the community.

## Workflow

### Stage 1: Discover Ideas on GitHub

Every ili instance comes with a set of **seed idea cards** (in the `Ideen` / Ideas board). When you set up ili for the first time and authenticate with GitHub, these cards automatically create corresponding **GitHub Issues** in the central repository.

Visit the [repository issues](https://github.com/Toa1984/ili-public/issues?labels=idea%2Cseed) to see what the community is already thinking about.

### Stage 2: Take a Card, Code Locally

1. **Pick an issue** from the repository that interests you.
2. **Create your own ili instance** (fork the repository or clone it):
   ```bash
   docker run --rm -v "$PWD":/out ghcr.io/toa1984/ili init
   docker compose -f docker-compose.yml -f docker-compose.terminal.yml up -d
   ```
   (See [QUICKSTART.md](QUICKSTART.md) for full setup.)

3. **Work on your local instance:**
   - The issue description links to the original idea card
   - Create a project board in your ili instance, sketch out your solution
   - Use your own AI (Claude, Ollama, etc.) to brainstorm and prototype
   - Document decisions and findings on your local cards

### Stage 3: Submit a Pull Request

Once you have a working solution:

1. **Commit your code** to a branch:
   ```bash
   git checkout -b feature/your-idea-name
   git add -A
   git commit -m "Add: your feature"
   ```

2. **Push to your fork** and **create a Pull Request** to `Toa1984/ili-public`.
   - Reference the issue: `Closes #42` in the PR description
   - Keep the PR focused (one feature per PR)
   - Ensure tests pass and no secrets are leaked (run `privacy-scanner` if unsure)

3. **The maintainer reviews and merges** your contribution.

### Stage 4: Others Adopt Your Solution

Once merged into `ili-public`, the next person who runs ili will see your code in their instance. If they had a similar problem:
- They get a working solution they can customize
- No need to re-solve the same problem
- **Everyone saves time and tokens** 🎉

---

## Linking Idea Cards to Issues

When you create a new ili instance and log in with GitHub:

1. The Ideen board's seed cards automatically create GitHub issues
2. Each card gets a `github_issue_id` field storing the link
3. **You can see your local work linked to the community's backlog**

Example:
- Your ili instance has `card_idea_1` ("Build a log scanner")
- It creates `https://github.com/Toa1984/ili-public/issues/42`
- You code in your local ili, push a PR for that issue
- Others install the next version of ili and get your code

---

## Card ↔ Issue Sync (Manual Export)

If you're working in someone else's ili instance and discover an idea worth contributing back:

1. Open the card detail
2. Click **Export as GitHub Issue**
3. Choose which board/repository to submit to
4. Preview the sanitized text (no IPs, paths, secrets)
5. Submit — the issue appears on GitHub with a link back to your instance

---

## Privacy & Safety

- **Seed cards are public** (part of the repository)
- **Manual exports are opt-in** — you decide what to share
- **All exports are sanitized** — no paths, IPs, API keys, or internal data
- **Your local instance stays private** — only export what you want the world to see

---

## Tech Stack

ili uses:
- **Frontend:** vanilla JS + HTML5 UI-Kit
- **Backend:** Python FastAPI
- **Orchestration:** Docker Compose / Podman
- **AI Integration:** Claude API, Ollama, or your own LLM

See [API.md](docs/API.md) and [PROJECT-TERMINAL.md](docs/PROJECT-TERMINAL.md) for details.

---

## Questions?

- **Installation issues?** See [QUICKSTART.md](QUICKSTART.md)
- **How does ili work?** Read [METHODIK.md](docs/METHODIK.md) (in German)
- **Bug reports?** [Create an issue](https://github.com/Toa1984/ili-public/issues/new)

Happy coding! 🚀
