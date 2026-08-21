# Security Policy

Thank you for helping keep this project and its users safe.

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues,
discussions, or pull requests.**

Instead, use GitHub's private vulnerability reporting for this repository:

1. Open the **Security** tab of this repository.
2. Click **Report a vulnerability**.
3. Describe the issue using the form (see "What to include" below).

The report is only visible to the maintainers until a fix is published.

## What to Include

A good report makes the problem reproducible:

- The affected component, file, or endpoint
- The version or commit you tested (see `VERSION` or the latest release tag)
- Step-by-step instructions to reproduce the issue
- The impact you believe it has (what an attacker could do)
- Any proof-of-concept code, logs, or screenshots — with secrets removed

## What to Expect

This project is maintained on a best-effort basis by volunteers.

- You will usually receive an acknowledgement within **7 days**.
- We will work with you to understand and validate the issue.
- Confirmed vulnerabilities are fixed in the next release; we will let you
  know when the fix is published.
- With your consent, we credit you in the release notes. Say so in your
  report if you prefer to stay anonymous.

## Supported Versions

Only the **latest release** receives security fixes. Please update to the
current version before reporting, and check whether the issue still exists
there.

## Scope

In scope:

- Code in this repository and the container images built from it
- Default configuration shipped with the project

Out of scope:

- Vulnerabilities in third-party dependencies that are not exploitable through
  this project (please report those upstream)
- Issues that require a deliberately insecure configuration by the operator
- Denial-of-service findings without a concrete, low-cost attack path
- Findings from automated scanners without a demonstrated impact

## Coordinated Disclosure

Please give us a reasonable amount of time to fix the issue before publishing
any details. We ask for **90 days** from the first report, or until a fix is
released — whichever comes first.

## Secrets in the Repository

This project must never contain real credentials. If you find an API key,
password, or token in the code or history, treat it as a vulnerability and
report it through the channel above — even if it looks expired.
