import os
import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from mailbomb.cli import cli


def test_setup_no_credentials_file(tmp_path):
    runner = CliRunner()
    with patch("mailbomb.cli.get_credentials_path", return_value=tmp_path / "credentials.json"):
        with patch("mailbomb.cli.webbrowser") as mock_wb:
            result = runner.invoke(cli, ["setup"], input="n\n")
            assert "credentials.json" in result.output


def test_setup_with_credentials_file(tmp_path):
    creds_path = tmp_path / "credentials.json"
    creds_path.write_text('{"installed": {}}')
    token_path = tmp_path / "token.json"

    runner = CliRunner()
    with patch("mailbomb.cli.get_credentials_path", return_value=creds_path):
        with patch("mailbomb.cli.get_token_path", return_value=token_path):
            with patch("mailbomb.cli.get_gmail_service") as mock_service:
                mock_svc = MagicMock()
                mock_svc.users().getProfile().execute.return_value = {
                    "emailAddress": "test@gmail.com",
                    "messagesTotal": 500000,
                }
                mock_service.return_value = mock_svc
                result = runner.invoke(cli, ["setup"])
                assert "test@gmail.com" in result.output or result.exit_code == 0
