"""Unit tests for `tracing._load_sa_credentials_from_env_json`.

Validates the helper never raises and always falls back to None for
malformed input, so `init_tracing` can fall through to ADC.
"""
from __future__ import annotations

import json
from unittest import mock

import pytest

import tracing


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", raising=False)


def test_unset_returns_none():
    assert tracing._load_sa_credentials_from_env_json() is None


def test_unparseable_json_returns_none(monkeypatch, caplog):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", "{not-json")
    with caplog.at_level("WARNING", logger="tracing"):
        assert tracing._load_sa_credentials_from_env_json() is None
    assert any("unparseable" in r.message for r in caplog.records)


def test_non_dict_json_returns_none(monkeypatch, caplog):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", '["array","not","object"]')
    with caplog.at_level("WARNING", logger="tracing"):
        assert tracing._load_sa_credentials_from_env_json() is None
    assert any("expected JSON object" in r.message for r in caplog.records)


def test_missing_required_field_logs_field_name(monkeypatch, caplog):
    payload = {
        "type": "service_account",
        "project_id": "p",
        "private_key": "x",
        # client_email omitted
    }
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", json.dumps(payload))
    with caplog.at_level("WARNING", logger="tracing"):
        assert tracing._load_sa_credentials_from_env_json() is None
    assert any("client_email" in r.message for r in caplog.records)


def test_tolerant_missing_outer_braces(monkeypatch):
    inner = (
        '"type":"service_account","project_id":"p","private_key":"x",'
        '"client_email":"x@y.iam.gserviceaccount.com"'
    )
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", inner)
    sentinel = object()
    with mock.patch(
        "google.oauth2.service_account.Credentials.from_service_account_info",
        return_value=sentinel,
    ) as m:
        assert tracing._load_sa_credentials_from_env_json() is sentinel
    assert m.call_count == 1
    info_arg = m.call_args.args[0]
    assert info_arg["client_email"] == "x@y.iam.gserviceaccount.com"


def test_valid_payload_builds_credentials(monkeypatch):
    payload = {
        "type": "service_account",
        "project_id": "p",
        "private_key": "x",
        "client_email": "x@y.iam.gserviceaccount.com",
    }
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", json.dumps(payload))
    sentinel = object()
    with mock.patch(
        "google.oauth2.service_account.Credentials.from_service_account_info",
        return_value=sentinel,
    ):
        assert tracing._load_sa_credentials_from_env_json() is sentinel


def test_credential_construction_failure_returns_none(monkeypatch, caplog):
    payload = {
        "type": "service_account",
        "project_id": "p",
        "private_key": "x",
        "client_email": "x@y.iam.gserviceaccount.com",
    }
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", json.dumps(payload))
    with mock.patch(
        "google.oauth2.service_account.Credentials.from_service_account_info",
        side_effect=ValueError("bad key"),
    ), caplog.at_level("WARNING", logger="tracing"):
        assert tracing._load_sa_credentials_from_env_json() is None
    assert any("could not build SA credentials" in r.message for r in caplog.records)
