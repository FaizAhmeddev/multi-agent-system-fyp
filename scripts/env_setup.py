"""Create or complete .env from .env.example with random secrets.

    python scripts/env_setup.py

- Never overwrites a value that is already set in .env.
- Fills empty secrets (JWT, API keys, MCP tokens, session keys, admin passwords) with random values.
- Writes the generated sign-in details to data/local_credentials.txt (gitignored) and prints them once.
"""
from __future__ import annotations

import secrets
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE, ENV = ROOT / ".env.example", ROOT / ".env"

ALPHA = string.ascii_letters + string.digits


def _password() -> str:
    return "-".join("".join(secrets.choice(ALPHA) for _ in range(5)) for _ in range(4))


GENERATED = {
    "JWT_SECRET": lambda: secrets.token_urlsafe(48),
    "AGENTSMIND_ADMIN_EMAIL": lambda: "admin@example.com",
    "AGENTSMIND_ADMIN_PASSWORD": _password,
    "FINANCE_PORTAL_API_KEY": lambda: secrets.token_urlsafe(32),
    "FINANCE_PORTAL_SECRET_KEY": lambda: secrets.token_urlsafe(48),
    "FINANCE_PORTAL_ADMIN_EMAIL": lambda: "finance.admin@example.com",
    "FINANCE_PORTAL_ADMIN_PASSWORD": _password,
    "IT_PORTAL_API_KEY": lambda: secrets.token_urlsafe(32),
    "IT_PORTAL_SECRET_KEY": lambda: secrets.token_urlsafe(48),
    "IT_PORTAL_ADMIN_EMAIL": lambda: "it.admin@example.com",
    "IT_PORTAL_ADMIN_PASSWORD": _password,
    "FINANCE_MCP_TOKEN": lambda: secrets.token_urlsafe(32),
    "IT_MCP_TOKEN": lambda: secrets.token_urlsafe(32),
    "CALENDAR_MCP_TOKEN": lambda: secrets.token_urlsafe(32),
    "WORKSPACE_MCP_TOKEN": lambda: secrets.token_urlsafe(32),
    "GOOGLE_TOKEN_ENCRYPTION_KEY": lambda: secrets.token_urlsafe(32),
}
SHOW = [("AgentsMind", "AGENTSMIND_ADMIN_EMAIL", "AGENTSMIND_ADMIN_PASSWORD"),
        ("Finance Portal", "FINANCE_PORTAL_ADMIN_EMAIL", "FINANCE_PORTAL_ADMIN_PASSWORD"),
        ("IT Helpdesk", "IT_PORTAL_ADMIN_EMAIL", "IT_PORTAL_ADMIN_PASSWORD")]


def parse(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def main() -> int:
    existing = parse(ENV)
    lines = EXAMPLE.read_text(encoding="utf-8").splitlines()
    out, generated = [], {}
    seen = set()
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            k = k.strip()
            seen.add(k)
            cur = existing.get(k, "")
            if cur:
                out.append(f"{k}={cur}")
                continue
            if k in GENERATED:
                val = GENERATED[k]()
                generated[k] = val
                out.append(f"{k}={val}")
                continue
        out.append(line)
    extra = [f"{k}={v}" for k, v in existing.items() if k not in seen]
    if extra:
        out += ["", "# Kept from your previous .env"] + extra
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    final = parse(ENV)
    creds = ROOT / "data" / "local_credentials.txt"
    creds.parent.mkdir(parents=True, exist_ok=True)
    rows = [f"{name}\t{final.get(e, '')}\t{final.get(p, '')}" for name, e, p in SHOW]
    creds.write_text("\n".join(rows) + "\n", encoding="utf-8")
    # legacy file read by older gate scripts
    (ROOT / "data" / "first_admin.txt").write_text(f"{final.get('AGENTSMIND_ADMIN_EMAIL', '')}\t"
                                                    f"{final.get('AGENTSMIND_ADMIN_PASSWORD', '')}\n", encoding="utf-8")
    if generated:
        print(f".env updated: {len(generated)} value(s) generated ({', '.join(sorted(generated))}).")
        print("Sign-in details (also in data/local_credentials.txt, which is gitignored):")
        for r in rows:
            print("  " + r.replace("\t", "   "))
    else:
        print(".env already complete; nothing generated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
