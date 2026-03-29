from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from mailbomb.cli import cli


@patch("mailbomb.cli.scan_messages")
def test_scan_command_builds_query(mock_scan):
    mock_scan.return_value = {"fetched": 42, "skipped": 3}
    runner = CliRunner()
    result = runner.invoke(cli, ["scan", "--before", "2006-01-01", "--after", "2004-01-01"])
    assert result.exit_code == 0
    call_args = mock_scan.call_args
    query = call_args[1].get("query") or call_args[0][0]
    assert "before:2006/01/01" in query
    assert "after:2004/01/01" in query


@patch("mailbomb.cli.scan_messages")
def test_scan_command_before_only(mock_scan):
    mock_scan.return_value = {"fetched": 10, "skipped": 0}
    runner = CliRunner()
    result = runner.invoke(cli, ["scan", "--before", "2006-01-01"])
    assert result.exit_code == 0
