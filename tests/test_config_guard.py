"""Startup guard: MOCK_MODE must not be enabled in DEPLOY_ENV=prod.

The guard lives in src/config.py and runs at import time. These tests reload
the module under different env-var combinations to verify it fires only for
the prod+mock combination.
"""
import importlib
import sys

import pytest


def _reload_config(monkeypatch, *, mock_mode: str, deploy_env: str):
    monkeypatch.setenv("MOCK_MODE", mock_mode)
    monkeypatch.setenv("DEPLOY_ENV", deploy_env)
    sys.modules.pop("config", None)
    return importlib.import_module("config")


def test_guard_blocks_mock_mode_in_prod(monkeypatch):
    with pytest.raises(RuntimeError, match="MOCK_MODE=true is not allowed"):
        _reload_config(monkeypatch, mock_mode="true", deploy_env="prod")


def test_guard_blocks_uppercase_prod(monkeypatch):
    # Comparison is lowercased so "PROD"/"Prod" typos still trip the guard.
    with pytest.raises(RuntimeError):
        _reload_config(monkeypatch, mock_mode="true", deploy_env="PROD")


def test_guard_allows_mock_mode_in_local(monkeypatch):
    cfg = _reload_config(monkeypatch, mock_mode="true", deploy_env="local")
    assert cfg.MOCK_MODE is True
    assert cfg.DEPLOY_ENV == "local"


def test_guard_allows_real_mode_in_prod(monkeypatch):
    cfg = _reload_config(monkeypatch, mock_mode="false", deploy_env="prod")
    assert cfg.MOCK_MODE is False
    assert cfg.DEPLOY_ENV == "prod"


def test_guard_allows_mock_mode_in_test(monkeypatch):
    cfg = _reload_config(monkeypatch, mock_mode="true", deploy_env="test")
    assert cfg.MOCK_MODE is True


@pytest.fixture(autouse=True)
def _restore_config(monkeypatch):
    """Reload config back to conftest defaults after each test so other test
    modules that imported `config` keep seeing MOCK_MODE=true / DEPLOY_ENV=test.
    """
    yield
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("DEPLOY_ENV", "test")
    sys.modules.pop("config", None)
    importlib.import_module("config")
