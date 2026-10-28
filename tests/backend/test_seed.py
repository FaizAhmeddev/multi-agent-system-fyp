from __future__ import annotations

import importlib.util

from bhelpers import ROOT


def _load_seed():
    spec = importlib.util.spec_from_file_location("seed_script", ROOT / "scripts" / "seed.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seed_is_synthetic_idempotent_and_has_no_fixed_passwords(db_url, tmp_path, capsys, db):
    from agentsmind.db.models import Candidate, User
    from sqlalchemy import select

    seed = _load_seed()
    seed.ROOT = tmp_path
    assert seed.main() == 0
    first = capsys.readouterr().out
    assert seed.main() == 0  # re-run is safe
    db.expire_all()
    users = db.scalars(select(User)).all()
    assert len(users) == 5  # admin + 4 demo
    assert all(u.email.endswith("@example.com") for u in users)
    assert len(db.scalars(select(Candidate)).all()) == 5
    creds = (tmp_path / "data" / "seed_credentials.txt").read_text().splitlines()
    pws = [line.split("\t")[2] for line in creds]
    assert len(set(pws)) == 4 and all(len(p) == 23 for p in pws)
    assert "skip user" not in first
