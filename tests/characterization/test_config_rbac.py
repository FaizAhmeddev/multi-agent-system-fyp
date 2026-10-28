"""Characterization: config.py users, roles, tab visibility and agent allow-lists."""
import importlib

import pytest


@pytest.fixture
def config(monkeypatch):
    for k in ("FYP_PASSWORD_ADMIN", "FYP_PASSWORD_HR", "FYP_PASSWORD_FINANCE",
              "FYP_PASSWORD_IT", "FYP_PASSWORD_DEMO", "FYP_PASSWORD_ASSISTANT"):
        monkeypatch.delenv(k, raising=False)
    import config as cfg
    # config.load_local_env() reads FYP_FINAL/.env if present; a clean clone has none.
    return importlib.reload(cfg)


@pytest.mark.legacy_bug
def test_default_demo_passwords_exist_when_env_not_set(config):
    # Six built-in accounts with guessable defaults (README documents admin123 / hr123 ...).
    assert set(config.USERS) == {"admin", "hr", "finance", "it", "demo", "assistant"}
    assert config.USERS["admin"]["password"] == "admin123"
    assert config.USERS["demo"]["role"] == "Admin"  # a second full-admin account


def test_tab_visibility_per_role(config):
    assert config.get_visible_tabs_for_role("Admin") == config._FULL_TABS
    assert "Finance" not in config.get_visible_tabs_for_role("HR Manager")
    assert config.get_visible_tabs_for_role("Finance Manager") == ["Assistant", "Dashboard", "Finance", "History"]
    assert config.get_visible_tabs_for_role("Employee") == ["Assistant", "History"]


def test_unknown_role_sees_everything(config):
    # ROLE_VISIBLE_TABS.get(unknown) is None -> treated as "all tabs".
    assert config.get_visible_tabs_for_role("Nonexistent") == config._FULL_TABS


@pytest.mark.legacy_bug
def test_unknown_role_has_unrestricted_agents(config):
    # Fail-open: an unknown role gets None == no agent restriction.
    assert config.get_role_orchestrator_allowlist("Nonexistent") is None


def test_hr_allowlist_excludes_finance(config):
    assert "finance" not in config.get_role_orchestrator_allowlist("HR Manager")
    assert config.get_role_orchestrator_allowlist("Finance Manager") == ["finance"]


@pytest.mark.legacy_bug
def test_assistant_role_can_reach_finance_and_hr_agents(config):
    allow = config.get_role_orchestrator_allowlist("Assistant")
    assert {"finance", "hr", "it_support", "documents"} <= set(allow)


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
