"""Scan the repository for committed secrets: the working tree and every commit in history.

    python scripts/secrets_scan.py            working tree + full git history
    python scripts/secrets_scan.py --tree     working tree only

No third-party packages. Exit code 1 when a likely secret is found. Matches print the file,
the commit (for history) and a masked preview, never the full value.
Allowed: placeholders in .env.example, test tokens built at runtime, and example.com data.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git") or "git"

RULES: list[tuple[str, re.Pattern[str]]] = [
    ("OpenAI API key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{20,}")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("Google OAuth client secret", re.compile(r"\bGOCSPX-[A-Za-z0-9_\-]{20,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Google OAuth refresh token", re.compile(r"\b1//0[0-9A-Za-z_\-]{30,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}")),
    ("Private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----")),
    ("Gmail app password assignment",
     re.compile(r"(?i)GMAIL_APP_PASSWORD\s*=\s*['\"]?[a-z]{4}\s?[a-z]{4}\s?[a-z]{4}\s?[a-z]{4}\b")),
    ("Password assignment", re.compile(r"(?i)\b(?:password|passwd|secret|api_key|token)\s*=\s*['\"][^'\"\s]{12,}['\"]")),
]
# Files that are allowed to contain password-like literals (tests build throwaway values).
ALLOW_PATHS = re.compile(r"^(tests/|frontend/e2e/|\.env\.example$|docs/|CHANGELOG\.md$|sandbox_data/)")
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".woff", ".woff2", ".db", ".bundle", ".zip", ".pyc"}
FORBIDDEN_FILES = re.compile(r"(^|/)(credentials\.json|token\.json|google_token\.enc|\.env)$|fyp_data\.db$|orchestrator\.log$")


def mask(s: str) -> str:
    return s[:6] + "..." + s[-2:] if len(s) > 10 else "***"


def scan_text(path: str, text: str, where: str) -> list[str]:
    hits = []
    for name, rx in RULES:
        if name == "Password assignment" and ALLOW_PATHS.search(path):
            continue
        for m in rx.finditer(text):
            if re.fullmatch(r"[^=]*=\s*['\"]?[xX\s]+['\"]?", m.group(0)):
                continue  # placeholder such as "xxxx xxxx xxxx xxxx"
            line = text.count("\n", 0, m.start()) + 1
            hits.append(f"{where}{path}:{line}  {name}  {mask(m.group(0))}")
    return hits


def tracked_files() -> list[str]:
    out = subprocess.run([GIT, "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout  # noqa: S603
    return [p for p in out.splitlines() if p]


def scan_tree() -> list[str]:
    hits = []
    for p in tracked_files():
        if FORBIDDEN_FILES.search(p):
            hits.append(f"{p}  file that must never be committed")
            continue
        if Path(p).suffix.lower() in SKIP_EXT:
            continue
        try:
            text = (ROOT / p).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        hits += scan_text(p, text, "")
    return hits


def scan_history() -> list[str]:
    hits = []
    revs = subprocess.run([GIT, "rev-list", "--all"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()  # noqa: S603
    files_seen = subprocess.run([GIT, "log", "--all", "--name-only", "--pretty=format:"], cwd=ROOT,  # noqa: S603
                                capture_output=True, text=True, check=True).stdout
    for p in sorted({x for x in files_seen.splitlines() if x}):
        if FORBIDDEN_FILES.search(p):
            hits.append(f"history: {p}  was committed in the past (purge it from history)")
    log = subprocess.run([GIT, "log", "--all", "-p", "--no-color", "--unified=0", "--pretty=format:@@commit %h"],  # noqa: S603
                         cwd=ROOT, capture_output=True, text=True, errors="ignore", check=True).stdout
    commit, path = "", ""
    for line in log.splitlines():
        if line.startswith("@@commit "):
            commit = line.split()[1]
        elif line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("+") and not line.startswith("+++") and Path(path).suffix.lower() not in SKIP_EXT:
            for h in scan_text(path, line[1:], f"history {commit}: "):
                hits.append(h.replace(f"{path}:1", path))
    print(f"history: {len(revs)} commits scanned")
    return sorted(set(hits))


def main() -> int:
    tree_only = "--tree" in sys.argv
    hits = scan_tree()
    print(f"working tree: {len(tracked_files())} tracked files scanned")
    if not tree_only:
        hits += scan_history()
    for h in hits:
        print("  " + h)
    print("SECRETS SCAN:", "FOUND " + str(len(hits)) if hits else "CLEAN")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
