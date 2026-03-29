import json
import os
import pytest
from unittest.mock import patch, MagicMock
from mailbomb.auth import (
    get_credentials_path,
    get_token_path,
    get_gmail_service,
    SCOPES,
)


def test_scopes_include_modify():
    assert "https://mail.google.com/" in SCOPES


def test_credentials_path_default():
    path = get_credentials_path()
    assert path.name == "credentials.json"
    assert ".mailbomb" in str(path)


def test_token_path_default():
    path = get_token_path()
    assert path.name == "token.json"
    assert ".mailbomb" in str(path)


@patch("mailbomb.auth.build")
@patch("mailbomb.auth.Credentials")
def test_get_gmail_service_with_valid_token(mock_creds_class, mock_build, tmp_path):
    token_path = tmp_path / "token.json"
    token_path.write_text("{}")

    mock_creds = MagicMock()
    mock_creds.valid = True
    mock_creds_class.from_authorized_user_file.return_value = mock_creds

    mock_service = MagicMock()
    mock_build.return_value = mock_service

    service = get_gmail_service(token_path=token_path, credentials_path=tmp_path / "creds.json")
    assert service == mock_service
    mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds)
