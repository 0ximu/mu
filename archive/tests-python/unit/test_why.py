"""Tests for the Why Layer - Git history analysis for code rationale."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mu.extras.intelligence.why import CommitInfo, WhyAnalyzer, WhyResult


class TestCommitInfo:
    """Test CommitInfo dataclass."""

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        commit = CommitInfo(
            hash="abc1234",
            full_hash="abc1234567890",
            author="Test Author",
            author_email="test@example.com",
            date=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
            message="feat: add auth",
            full_message="feat: add auth\n\nAdded authentication module.",
            files_changed=["src/auth.py", "tests/test_auth.py"],
            issue_refs=["123", "456"],
            pr_refs=["789"],
        )

        result = commit.to_dict()

        assert result["hash"] == "abc1234"
        assert result["full_hash"] == "abc1234567890"
        assert result["author"] == "Test Author"
        assert result["author_email"] == "test@example.com"
        assert result["message"] == "feat: add auth"
        assert result["files_changed"] == ["src/auth.py", "tests/test_auth.py"]
        assert result["issue_refs"] == ["123", "456"]
        assert result["pr_refs"] == ["789"]


class TestWhyResult:
    """Test WhyResult dataclass."""

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        result = WhyResult(
            target="AuthService",
            target_type="class",
            file_path="src/auth.py",
            line_start=10,
            line_end=50,
            origin_reason="Created to handle user authentication",
            total_commits=5,
            evolution_summary="5 commits over 6 months by 2 contributors",
            primary_author="Test Author",
            contributors=[{"author": "Test Author", "commits": 3}],
            issue_refs=["123"],
            pr_refs=["456"],
            frequently_changed_with=["src/users.py"],
            analysis_time_ms=150.5,
        )

        output = result.to_dict()

        assert output["target"] == "AuthService"
        assert output["target_type"] == "class"
        assert output["file_path"] == "src/auth.py"
        assert output["origin_reason"] == "Created to handle user authentication"
        assert output["total_commits"] == 5
        assert output["primary_author"] == "Test Author"
        assert output["issue_refs"] == ["123"]
        assert output["frequently_changed_with"] == ["src/users.py"]


class TestWhyAnalyzer:
    """Test WhyAnalyzer."""

    @pytest.fixture
    def analyzer(self, tmp_path: Path) -> WhyAnalyzer:
        """Create analyzer with temp path."""
        return WhyAnalyzer(db=None, root_path=tmp_path)

    def test_extract_issue_refs(self, analyzer: WhyAnalyzer) -> None:
        """Test extraction of issue references from commit messages."""
        # GitHub style
        assert "123" in analyzer._extract_issue_refs("Fixes #123")
        assert "456" in analyzer._extract_issue_refs("closes #456")

        # JIRA style
        assert "PROJ-789" in analyzer._extract_issue_refs("PROJ-789: Fix bug")

        # Issue keyword
        assert "42" in analyzer._extract_issue_refs("issue: 42")

    def test_extract_pr_refs(self, analyzer: WhyAnalyzer) -> None:
        """Test extraction of PR references from commit messages."""
        # Merge commit style
        assert "123" in analyzer._extract_pr_refs("Merge pull request #123")

        # Trailing PR number
        assert "456" in analyzer._extract_pr_refs("Add feature (#456)")

    def test_analyze_contributors(self, analyzer: WhyAnalyzer) -> None:
        """Test contributor analysis."""
        commits = [
            CommitInfo(
                hash="a", full_hash="a" * 40, author="Alice",
                author_email="alice@test.com",
                date=datetime.now(UTC), message="", full_message="",
            ),
            CommitInfo(
                hash="b", full_hash="b" * 40, author="Alice",
                author_email="alice@test.com",
                date=datetime.now(UTC), message="", full_message="",
            ),
            CommitInfo(
                hash="c", full_hash="c" * 40, author="Bob",
                author_email="bob@test.com",
                date=datetime.now(UTC), message="", full_message="",
            ),
        ]

        contributors = analyzer._analyze_contributors(commits)

        assert len(contributors) == 2
        assert contributors[0]["author"] == "Alice"
        assert contributors[0]["commits"] == 2
        assert contributors[1]["author"] == "Bob"
        assert contributors[1]["commits"] == 1

    def test_generate_origin_reason(self, analyzer: WhyAnalyzer) -> None:
        """Test origin reason generation."""
        commit = CommitInfo(
            hash="abc",
            full_hash="abc" * 13,
            author="Developer",
            author_email="dev@test.com",
            date=datetime(2024, 6, 15, tzinfo=UTC),
            message="feat: implement authentication flow",
            full_message="feat: implement authentication flow",
        )

        reason = analyzer._generate_origin_reason(commit, {"123"})

        assert "2024-06-15" in reason
        assert "Developer" in reason
        assert "implement authentication flow" in reason
        assert "123" in reason

    def test_generate_evolution_summary(self, analyzer: WhyAnalyzer) -> None:
        """Test evolution summary generation."""
        now = datetime.now(UTC)
        commits = [
            CommitInfo(
                hash="a", full_hash="a" * 40, author="Alice",
                author_email="alice@test.com",
                date=now, message="Recent", full_message="",
            ),
        ]
        contributors = [{"author": "Alice", "commits": 1}]

        summary = analyzer._generate_evolution_summary(commits, contributors)

        assert "1 commits" in summary
        assert "Alice" in summary

    def test_resolve_target_file_path(self, analyzer: WhyAnalyzer, tmp_path: Path) -> None:
        """Test target resolution for file paths."""
        # Create test file
        test_file = tmp_path / "src" / "auth.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("class Auth: pass")

        file_path, line_start, line_end, target_type = analyzer._resolve_target(
            "src/auth.py"
        )

        assert file_path == test_file
        assert line_start is None
        assert line_end is None
        assert target_type == "file"

    def test_resolve_target_with_lines(self, analyzer: WhyAnalyzer, tmp_path: Path) -> None:
        """Test target resolution with line range."""
        # Create test file
        test_file = tmp_path / "src" / "auth.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("class Auth:\n    pass\n")

        file_path, line_start, line_end, target_type = analyzer._resolve_target(
            "src/auth.py:1-2"
        )

        assert file_path == test_file
        assert line_start == 1
        assert line_end == 2
        assert target_type == "lines"

    def test_resolve_target_not_found(self, analyzer: WhyAnalyzer) -> None:
        """Test target resolution for non-existent file."""
        file_path, line_start, line_end, target_type = analyzer._resolve_target(
            "nonexistent.py"
        )

        assert file_path is None
        assert target_type == "unknown"

    @patch("subprocess.run")
    def test_get_commits(
        self, mock_run: MagicMock, analyzer: WhyAnalyzer, tmp_path: Path
    ) -> None:
        """Test getting commits from git log."""
        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("# test")

        # Mock git log output
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "abc123full\x00abc123\x00Author\x00author@test.com\x00"
                "2024-06-15T10:00:00+00:00\x00feat: add feature\x00Body text #123\x1e"
            ),
        )

        commits = analyzer._get_commits(test_file, None, None, 10)

        assert len(commits) == 1
        assert commits[0].hash == "abc123"
        assert commits[0].author == "Author"
        assert commits[0].message == "feat: add feature"
        assert "123" in commits[0].issue_refs

    @patch("subprocess.run")
    def test_get_commits_with_line_range(
        self, mock_run: MagicMock, analyzer: WhyAnalyzer, tmp_path: Path
    ) -> None:
        """Test getting commits for a line range."""
        test_file = tmp_path / "test.py"
        test_file.write_text("# test\ncode\n")

        mock_run.return_value = MagicMock(returncode=0, stdout="")

        analyzer._get_commits(test_file, 1, 2, 10)

        # Verify -L flag was used
        call_args = mock_run.call_args[0][0]
        assert any("-L1,2:" in str(arg) for arg in call_args)

    @patch("subprocess.run")
    def test_analyze_cochanges(
        self, mock_run: MagicMock, analyzer: WhyAnalyzer, tmp_path: Path
    ) -> None:
        """Test co-change analysis."""
        test_file = tmp_path / "auth.py"

        commits = [
            CommitInfo(
                hash="a", full_hash="a" * 40, author="A",
                author_email="a@test.com",
                date=datetime.now(UTC), message="", full_message="",
                files_changed=["auth.py", "users.py"],
            ),
            CommitInfo(
                hash="b", full_hash="b" * 40, author="A",
                author_email="a@test.com",
                date=datetime.now(UTC), message="", full_message="",
                files_changed=["auth.py", "users.py", "config.py"],
            ),
            CommitInfo(
                hash="c", full_hash="c" * 40, author="A",
                author_email="a@test.com",
                date=datetime.now(UTC), message="", full_message="",
                files_changed=["auth.py", "users.py"],
            ),
        ]

        cochanges = analyzer._analyze_cochanges(test_file, commits, max_cochanges=5)

        # users.py should be in co-changes (3/3 commits)
        assert "users.py" in cochanges

    def test_analyze_target_not_found(self, analyzer: WhyAnalyzer) -> None:
        """Test analyze with non-existent target."""
        result = analyzer.analyze("nonexistent_file.py")

        assert result.target_type == "unknown"
        assert "not found" in result.origin_reason.lower()

    @patch.object(WhyAnalyzer, "_get_commits")
    def test_analyze_no_commits(
        self, mock_get_commits: MagicMock, analyzer: WhyAnalyzer, tmp_path: Path
    ) -> None:
        """Test analyze when file has no git history."""
        # Create test file
        test_file = tmp_path / "new_file.py"
        test_file.write_text("# new file")

        mock_get_commits.return_value = []

        result = analyzer.analyze("new_file.py")

        assert result.total_commits == 0
        assert "no git history" in result.origin_reason.lower()

    @patch.object(WhyAnalyzer, "_get_commits")
    def test_analyze_with_commits(
        self, mock_get_commits: MagicMock, analyzer: WhyAnalyzer, tmp_path: Path
    ) -> None:
        """Test analyze with commits."""
        # Create test file
        test_file = tmp_path / "auth.py"
        test_file.write_text("class Auth: pass")

        mock_get_commits.return_value = [
            CommitInfo(
                hash="recent",
                full_hash="recent" * 7,
                author="Alice",
                author_email="alice@test.com",
                date=datetime(2024, 6, 15, tzinfo=UTC),
                message="fix: auth bug",
                full_message="fix: auth bug\n\nFixes #456",
                files_changed=["auth.py"],
                issue_refs=["456"],
                pr_refs=[],
            ),
            CommitInfo(
                hash="origin",
                full_hash="origin" * 6 + "xx",
                author="Bob",
                author_email="bob@test.com",
                date=datetime(2024, 1, 1, tzinfo=UTC),
                message="feat: add auth module",
                full_message="feat: add auth module\n\nImplements #123",
                files_changed=["auth.py", "users.py"],
                issue_refs=["123"],
                pr_refs=[],
            ),
        ]

        result = analyzer.analyze("auth.py")

        assert result.total_commits == 2
        assert result.origin_commit is not None
        assert result.origin_commit.hash == "origin"
        assert "123" in result.issue_refs
        assert "456" in result.issue_refs
        assert len(result.contributors) == 2


class TestWhyAnalyzerWithMubase:
    """Test WhyAnalyzer with MUbase integration."""

    def test_resolve_target_node_id(self, tmp_path: Path) -> None:
        """Test target resolution using node ID."""
        # Create mock MUbase
        mock_db = MagicMock()
        mock_node = MagicMock()
        mock_node.file_path = "src/auth.py"
        mock_node.line_start = 10
        mock_node.line_end = 50
        mock_db.get_node.return_value = mock_node

        # Create file
        test_file = tmp_path / "src" / "auth.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("class Auth: pass")

        analyzer = WhyAnalyzer(db=mock_db, root_path=tmp_path)
        file_path, line_start, line_end, target_type = analyzer._resolve_target(
            "cls:src/auth.py:Auth"
        )

        assert file_path == test_file
        assert line_start == 10
        assert line_end == 50
        assert target_type == "cls"
        mock_db.get_node.assert_called_once_with("cls:src/auth.py:Auth")

    def test_resolve_target_by_name(self, tmp_path: Path) -> None:
        """Test target resolution by name lookup."""
        # Create mock MUbase
        mock_db = MagicMock()
        mock_node = MagicMock()
        mock_node.file_path = "src/services/auth.py"
        mock_node.line_start = 5
        mock_node.line_end = 100
        mock_node.type = "class"
        mock_db.find_by_name.return_value = [mock_node]

        # Create file
        test_file = tmp_path / "src" / "services" / "auth.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("class AuthService: pass")

        analyzer = WhyAnalyzer(db=mock_db, root_path=tmp_path)
        file_path, line_start, line_end, target_type = analyzer._resolve_target(
            "AuthService"
        )

        assert file_path == test_file
        assert line_start == 5
        assert line_end == 100
