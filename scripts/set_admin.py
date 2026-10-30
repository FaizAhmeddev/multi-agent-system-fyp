"""Set the AgentsMind admin sign-in (email and password) without losing any data.

    .venv\\Scripts\\python scripts\\set_admin.py --email you@example.com --password "Your-Password-1"

What it does:
1. Checks the email and the password rules (12+ characters, not common, not containing the email name).
2. Database: if a user with that email exists, it gets the admin role and the new password.
   Otherwise the existing admin account is renamed to that email and gets the new password.
   The account is unlocked and its open sessions are signed out.
3. Updates AGENTSMIND_ADMIN_EMAIL and AGENTSMIND_ADMIN_PASSWORD in .env (other lines are kept as they are).
4. Updates the AgentsMind row in data/local_credentials.txt.
Stop AgentsMind first (scripts\\win\\stop_all.ps1) so the database is not in use.
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from email_validator import EmailNotValidError, validate_email  # noqa: E402
from sqlalchemy import select  # noqa: E402

from agentsmind.audit import audit  # noqa: E402
from agentsmind.auth.service import ensure_roles, normalise_email, revoke_all_sessions  # noqa: E402
from agentsmind.db.models import User  # noqa: E402
from agentsmind.db.session import SessionLocal  # noqa: E402
from agentsmind.security.passwords import hash_password, password_problems, verify_password  # noqa: E402
from agentsmind.settings import get_settings  # noqa: E402


def set_env_values(env: Path, values: dict[str, str]) -> None:
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    seen: set[str] = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in values and "=" in line and not line.lstrip().startswith("#"):
            out.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in values.items() if k not in seen]
    env.write_text("\n".join(out) + "\n", encoding="utf-8")


def set_local_credentials(path: Path, email: str, password: str) -> None:
    rows = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    rows = [r for r in rows if not r.startswith("AgentsMind\t")]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([f"AgentsMind\t{email}\t{password}"] + rows) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--if-changed", action="store_true",
                    help="do nothing when that admin already has this password (used at each start on a server)")
    a = ap.parse_args(argv)

    try:
        email = normalise_email(validate_email(a.email, check_deliverability=False).normalized)
    except EmailNotValidError as e:
        print(f"Email not accepted: {e}")
        return 2
    problems = password_problems(a.password, email=email, min_length=get_settings().password_min_length)
    if problems:
        print("Password not accepted: " + " ".join(problems))
        return 2

    with SessionLocal() as db:
        roles = ensure_roles(db)
        user = db.scalar(select(User).where(User.email == email))
        if a.if_changed and user is not None and "admin" in user.role_names and user.is_active and \
                verify_password(a.password, user.password_hash):
            print(f"Admin {email}: already set.")
            return 0
        action = "updated"
        if user is None:
            admins = [u for u in db.scalars(select(User)) if "admin" in u.role_names]
            if admins:
                user = min(admins, key=lambda u: u.id)
                action = f"renamed from {user.email}"
                user.email = email
            else:
                user = User(email=email, full_name="Administrator", password_hash="", roles=[],
                            timezone=get_settings().timezone)
                db.add(user)
                action = "created"
        if roles["admin"] not in user.roles:
            user.roles.append(roles["admin"])
        user.password_hash = hash_password(a.password)
        user.password_changed_at = datetime.now(UTC)
        user.failed_login_count = 0
        user.locked_until = None
        user.is_active = True
        db.flush()
        revoke_all_sessions(db, user.id)
        audit(db, "admin.credentials_set", actor_email="scripts/set_admin.py", target_type="user",
              target_id=user.id, detail={"email": email, "action": action}, commit=False)
        db.commit()

    set_env_values(ROOT / ".env", {"AGENTSMIND_ADMIN_EMAIL": email, "AGENTSMIND_ADMIN_PASSWORD": a.password})
    set_local_credentials(ROOT / "data" / "local_credentials.txt", email, a.password)
    (ROOT / "data" / "first_admin.txt").write_text(f"{email}\t{a.password}\n", encoding="utf-8")
    print(f"Admin {email}: {action}. .env and data/local_credentials.txt updated.")
    print("Start AgentsMind with Start-AgentsMind.bat (or python main.py) and sign in at http://127.0.0.1:8000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
