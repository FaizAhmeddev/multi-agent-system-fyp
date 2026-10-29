"""Remove the portals' sample records (example.com / .net / .org emails). Run by external_systems/main.py."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from sqlalchemy import or_, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from portal_common.core import load_dotenv_file, make_sqlite_engine  # noqa: E402

SAMPLE = ("@example.com", "@example.net", "@example.org")


def main() -> int:
    load_dotenv_file(HERE.parent / ".env")
    from finance_portal.app import load_config as finance_config
    from finance_portal.models import Base as FinanceBase
    from finance_portal.models import Person
    from it_portal.app import load_config as it_config
    from it_portal.models import Base as ITBase
    from it_portal.models import Ticket

    n = 0
    for cfg, base, model, col in ((finance_config(), FinanceBase, Person, "email"),
                                  (it_config(), ITBase, Ticket, "requester_email")):
        eng = make_sqlite_engine(cfg["db_url"])
        base.metadata.create_all(eng)
        db = sessionmaker(bind=eng)()
        c = getattr(model, col)
        for r in db.scalars(select(model).where(or_(*[c.like(f"%{d}") for d in SAMPLE]))):
            db.delete(r)
            n += 1
        db.commit()
        db.close()
    print(f"Sample records removed from the portals: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
