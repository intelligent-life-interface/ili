"""report_sanitizer.py — strip personal/identifying data from outgoing bug reports.

Every text that leaves an ili instance towards GitHub (auto error reports,
manual card exports, deep-link bodies) passes through ``sanitize()`` first.
The filter is deliberately greedy: a false positive costs a few characters of
context, a false negative leaks somebody's home directory name, LAN address
or token into a public issue tracker.

What is removed / masked
------------------------
* home directories          /home/<user>, /Users/<user>, C:\\Users\\<user>
* IPv4 / IPv6 addresses
* host names                *.local, *.intranet.*, *.arpa, *.lan, *.home and
                            generic FQDNs (at least one dot, known TLD-ish tail)
* e-mail addresses
* secrets                   ghp_/gho_/ghu_/ghs_/ghr_, github_pat_, sk-ant-/sk-proj-,
                            AKIA…, "Bearer <token>", key=/token=/password=
                            query or assignment values
* URL query strings         everything after '?' in http(s) URLs
* URL credentials           (removed from connection strings like postgresql:// auth)

The function never raises — a report must not fail because the scrubber
choked on odd input. Only the *category and count* of removals is logged,
never the removed value.

Interface
---------
sanitize(text: str) -> tuple[str, dict]   # (clean_text, {category: count})
"""
import logging
import re

log = logging.getLogger("dashboard.services.report_sanitizer")

# Order matters: secrets and URLs first (they may contain hosts/emails that
# would otherwise be split into harmless-looking fragments), paths before
# hosts (a path may contain a dotted file name that looks like an FQDN).
_RULES: list[tuple[str, re.Pattern, str]] = [
    ("token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"), "<token>"),
    ("token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "<token>"),
    ("token", re.compile(r"\bsk-(?:ant|proj)-[A-Za-z0-9_-]{20,}\b"), "<token>"),
    ("token", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<token>"),
    ("token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-+/=]{8,}"), "Bearer <token>"),
    ("token", re.compile(r"(?i)([A-Za-z0-9_-]*(?:api[_-]?key|token|secret|password|passwd|pwd)[A-Za-z0-9_-]*)\s*[=:]\s*\S+"),
     r"\1=<redacted>"),
    ("url_credential", re.compile(r"(://)[A-Za-z0-9._-]+:[^\s@\"']+@"), r"\1<user>:<password>@"),
    ("url_query", re.compile(r"(https?://[^\s?#\"']+)\?[^\s\"']*"), r"\1?<query>"),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<email>"),
    ("home_path", re.compile(r"/home/[^/\s\"']+"), "/home/<user>"),
    ("home_path", re.compile(r"/Users/[^/\s\"']+"), "/Users/<user>"),
    ("home_path", re.compile(r"(?i)([A-Z]:\\Users\\)[^\\\s\"']+"), r"\1<user>"),
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b"), "<ip>"),
    # IPv6: at least two groups separated by ':' with hex chars, avoid matching
    # plain times like 12:30 by requiring a hex letter or '::' somewhere.
    ("ipv6", re.compile(r"\b(?=[0-9a-fA-F:]*(?:[a-fA-F]|::))[0-9a-fA-F]{0,4}(?::[0-9a-fA-F]{0,4}){2,7}\b"),
     "<ip>"),
    ("hostname", re.compile(
        r"\b[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
        r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*"
        r"\.(?:local|intranet|arpa|lan|home|fritz\.box|internal)(?:\.[A-Za-z0-9-]+)*\b"), "<host>"),
    # Generic FQDN: something.something.tld — but skip well-known public API
    # hosts and file names (ends with .py/.js/... handled by the exclusion list).
    ("hostname", re.compile(
        r"\b(?!(?:api\.github\.com|github\.com|api\.anthropic\.com|localhost)\b)"
        r"(?:[A-Za-z0-9-]+\.){2,}(?:com|net|org|ch|de|at|io|dev|cloud|app|info|eu|me|tv|cl|es)\b"),
     "<host>"),
]


def sanitize(text: str) -> tuple[str, dict]:
    """Return (clean_text, stats). Never raises.

    stats maps a category name to the number of replacements made, e.g.
    {"home_path": 2, "ipv4": 1}. Categories with zero hits are omitted.
    """
    if not text:
        return "", {}
    stats: dict[str, int] = {}
    clean = str(text)
    try:
        for category, pattern, replacement in _RULES:
            clean, n = pattern.subn(replacement, clean)
            if n:
                stats[category] = stats.get(category, 0) + n
    except Exception as exc:  # pragma: no cover — defensive, must never break a report
        log.error("sanitize failed (%s) — returning input truncated", exc)
        return str(text)[:2000], {"error": 1}
    if stats:
        log.debug("sanitize: removed %s (input %d chars → %d)", stats, len(text), len(clean))
    else:
        log.debug("sanitize: nothing to remove (%d chars)", len(text))
    return clean, stats
