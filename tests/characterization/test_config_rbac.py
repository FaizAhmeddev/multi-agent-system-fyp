"""Characterization: config.py users, roles, tab visibility and agent allow-lists."""
import importlib
import importlib.util

import pytest


@pytest.fixture
def config(monkeypatch):
    for k in ("FYP_PASSWORD_ADMIN", "FYP_PASSWORD_HR", "FYP_PASSWORD_FINANCE",
              "FYP_PASSWORD_IT", "FYP_PASSWORD_DEMO", "FYP_PASSWORD_ASSISTANT"):
        monkeypatch.delenv(k, raising=False)
    import config as cfg
    # config.load_local_env() reads FYP_FINAL/.env if present; a clean clone has none.
    return importlib.reload(cfg)


def test_no_default_passwords_when_env_not_set(config):
    """Flipped in Phase 1b (was test_default_demo_passwords_exist_when_env_not_set)."""
    assert set(config.USERS) == {"admin", "hr", "finance", "it", "demo", "assistant"}
    assert all(u["password"] == "" for u in config.USERS.values())


@pytest.mark.skipif(importlib.util.find_spec("sqlalchemy") is None, reason="needs SQLAlchemy")
def test_legacy_login_refuses_empty_and_unset_passwords(config):
    """Flipped in Phase 1b: an account with no configured password cannot sign in."""
    import database.sqlite_db as sdb

    sdb._engine, sdb._Session = None, None  # fresh engine on the temp legacy DB
    assert sdb.authenticate_user("admin", "") is None
    assert sdb.authenticate_user("admin", "admin123") is None


def test_tab_visibility_per_role(config):
    assert config.get_visible_tabs_for_role("Admin") == config._FULL_TABS
    assert "Finance" not in config.get_visible_tabs_for_role("HR Manager")
    assert config.get_visible_tabs_for_role("Finance Manager") == ["Assistant", "Dashboard", "Finance", "History"]
    assert config.get_visible_tabs_for_role("Employee") == ["Assistant", "History"]


def test_unknown_role_sees_only_assistant(config):
    """Flipped in Phase 1b (was test_unknown_role_sees_everything): fail closed."""
    assert config.get_visible_tabs_for_role("Nonexistent") == ["Assistant", "History"]


def test_unknown_role_gets_general_agent_only(config):
    """Flipped in Phase 1b (was test_unknown_role_has_unrestricted_agents)."""
    assert config.get_role_orchestrator_allowlist("Nonexistent") == ["general"]


def test_hr_allowlist_excludes_finance(config):
    assert "finance" not in config.get_role_orchestrator_allowlist("HR Manager")
    assert config.get_role_orchestrator_allowlist("Finance Manager") == ["finance"]


def test_assistant_role_limited_to_email_and_inbox(config):
    """Flipped in Phase 1b (was test_assistant_role_can_reach_finance_and_hr_agents)."""
    allow = config.get_role_orchestrator_allowlist("Assistant")
    assert set(allow) == {"general", "email", "hr_gmail"}


def test_mcp_defaults(config):
    assert config.MCP_SERVER_HOST == "localhost"
    assert config.MCP_SERVER_PORT == 8765


def test_mq_enabled_by_default(config, monkeypatch):
    monkeypatch.delenv("FYP_ENABLE_MQ", raising=False)
    # Docstring says "off by default" but the code defaults to "true".
    assert config.orchestrator_mq_enabled() is True


def test_sqlite_default_database_url(config, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    config.DATABASE_URL = ""
    assert config.get_database_url().startswith("sqlite:///")
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/db")
    config.DATABASE_URL = ""
    assert config.get_database_url() == "postgresql://u:p@h/db"
