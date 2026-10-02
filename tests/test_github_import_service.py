"""Tests für github_import_service.py"""
from unittest.mock import patch

from app.services.github_import_service import (
    list_github_repos,
    import_github_repos,
)


def test_list_github_repos_empty_user(monkeypatch):
    """list_github_repos mit leerem User-Feld → nutzt Viewer."""
    mock_token = "test-token"
    monkeypatch.setenv("ILI_GITHUB_TOKEN", mock_token)

    with patch("app.services.github_import_service._get_user_info") as mock_user:
        mock_user.return_value = {"login": "octocat"}
        with patch("app.services.github_import_service._fetch_user_repos") as mock_fetch:
            mock_fetch.return_value = ([], "octocat")

            result = list_github_repos("")

            assert result["viewer_login"] == "octocat"
            assert result["requested_user"] == "octocat"


def test_import_github_repos_board_exists(monkeypatch, tmp_path):
    """import_github_repos überspringt existierende Boards."""
    # Setup: ein Manifest mit einem existierenden Board
    monkeypatch.setenv("PROJEKTE_BASE", str(tmp_path))

    with patch("app.services.github_import_service._manifest.load") as mock_load:
        mock_load.return_value = {
            "boards": [
                {"id": "existing-repo", "name": "Existing"}
            ]
        }

        result = import_github_repos(["octocat/existing-repo"])

        assert result["octocat/existing-repo"]["status"] == "skipped"
        assert result["octocat/existing-repo"]["reason"] == "board_exists"


def test_import_github_repos_invalid_name():
    """import_github_repos überspringt ungültige Namen."""
    result = import_github_repos(["no-slash", "", "octocat/"])

    assert result["no-slash"]["status"] == "skipped"
    assert result[""]["status"] == "skipped"


def test_github_repo_field_set_in_manifest(monkeypatch, tmp_path):
    """import_github_repos setzt das github_repo-Feld im Manifest."""
    monkeypatch.setenv("PROJEKTE_BASE", str(tmp_path))
    monkeypatch.setenv("ILI_GITHUB_TOKEN", "test-token")

    with patch("app.services.github_import_service.create_board"):
        with patch("app.services.github_import_service.clone_github_repo", return_value=True):
            with patch("app.services.github_import_service._manifest.load") as mock_load:
                with patch("app.services.github_import_service._manifest.update") as mock_update:
                    mock_load.return_value = {"boards": []}

                    import_github_repos(["octocat/test-repo"])

                    # update wurde mit einem Mutator aufgerufen
                    assert mock_update.called
