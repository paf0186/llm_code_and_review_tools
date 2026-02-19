"""Tests for the models module."""

from gerrit_cli.models import (
    Author,
    ChangeInfo,
    CodeContext,
    Comment,
    CommentThread,
    ExtractedComments,
    ReplyResult,
)


class TestAuthor:
    """Tests for Author dataclass."""

    def test_from_gerrit_full(self):
        """Test creating Author from complete Gerrit data."""
        data = {
            "name": "John Doe",
            "email": "john@example.com",
            "username": "johnd",
            "_account_id": 12345,
        }
        author = Author.from_gerrit(data)

        assert author.name == "John Doe"
        assert author.email == "john@example.com"
        assert author.username == "johnd"
        assert author.account_id == 12345

    def test_from_gerrit_minimal(self):
        """Test creating Author from minimal Gerrit data."""
        data = {}
        author = Author.from_gerrit(data)

        assert author.name == "Unknown"
        assert author.email is None
        assert author.username is None
        assert author.account_id is None

    def test_to_dict(self):
        """Test converting Author to dict."""
        author = Author(
            name="Jane Doe",
            email="jane@example.com",
            username="janed",
            account_id=54321,
        )
        result = author.to_dict()

        assert result["name"] == "Jane Doe"
        assert result["email"] == "jane@example.com"
        assert result["username"] == "janed"
        assert result["account_id"] == 54321


class TestCodeContext:
    """Tests for CodeContext dataclass."""

    def test_to_dict(self):
        """Test converting CodeContext to dict."""
        context = CodeContext(
            lines=["line1", "line2", "line3"],
            start_line=10,
            end_line=12,
            target_line=11,
        )
        result = context.to_dict()

        assert result["lines"] == ["line1", "line2", "line3"]
        assert result["start_line"] == 10
        assert result["end_line"] == 12
        assert result["target_line"] == 11

    def test_format(self):
        """Test formatting CodeContext as string."""
        context = CodeContext(
            lines=["def foo():", "    return 42", ""],
            start_line=10,
            end_line=12,
            target_line=11,
        )
        result = context.format()

        assert ">>>   11: " in result
        assert "     10: " in result
        assert "def foo():" in result
        assert "return 42" in result

    def test_format_without_target(self):
        """Test formatting without target line."""
        context = CodeContext(
            lines=["line1", "line2"],
            start_line=1,
            end_line=2,
            target_line=None,
        )
        result = context.format()

        # No >>> marker when no target line
        assert ">>>" not in result


class TestComment:
    """Tests for Comment dataclass."""

    def test_from_gerrit(self):
        """Test creating Comment from Gerrit data."""
        data = {
            "id": "abc123",
            "patch_set": 5,
            "line": 42,
            "message": "Fix this bug",
            "author": {"name": "Reviewer", "_account_id": 100},
            "unresolved": True,
            "updated": "2025-01-01 12:00:00.000000000",
            "in_reply_to": "parent123",
        }
        comment = Comment.from_gerrit("/path/to/file.py", data)

        assert comment.id == "abc123"
        assert comment.patch_set == 5
        assert comment.file_path == "/path/to/file.py"
        assert comment.line == 42
        assert comment.message == "Fix this bug"
        assert comment.author.name == "Reviewer"
        assert comment.unresolved is True
        assert comment.in_reply_to == "parent123"

    def test_from_gerrit_patchset_level(self):
        """Test creating patchset-level Comment."""
        data = {
            "id": "xyz789",
            "patch_set": 3,
            "message": "Overall looks good",
            "author": {"name": "Lead"},
            "unresolved": False,
            "updated": "2025-01-01 12:00:00.000000000",
        }
        comment = Comment.from_gerrit("/PATCHSET_LEVEL", data)

        assert comment.line is None
        assert comment.file_path == "/PATCHSET_LEVEL"

    def test_to_dict(self):
        """Test converting Comment to dict."""
        author = Author(name="Test", email="test@example.com")
        comment = Comment(
            id="test123",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Test comment",
            author=author,
            unresolved=True,
            updated="2025-01-01",
        )
        result = comment.to_dict()

        assert result["id"] == "test123"
        assert result["author"]["name"] == "Test"
        assert result["code_context"] is None


class TestCommentThread:
    """Tests for CommentThread dataclass."""

    def test_is_resolved_with_resolved_root(self):
        """Test thread with resolved root comment."""
        root = Comment(
            id="root",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Issue",
            author=Author(name="Reviewer"),
            unresolved=False,
            updated="2025-01-01",
        )
        thread = CommentThread(root_comment=root)

        assert thread.is_resolved is True

    def test_is_resolved_with_unresolved_root(self):
        """Test thread with unresolved root comment."""
        root = Comment(
            id="root",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Issue",
            author=Author(name="Reviewer"),
            unresolved=True,
            updated="2025-01-01",
        )
        thread = CommentThread(root_comment=root)

        assert thread.is_resolved is False

    def test_is_resolved_uses_last_reply(self):
        """Test that is_resolved uses last reply status."""
        root = Comment(
            id="root",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Issue",
            author=Author(name="Reviewer"),
            unresolved=True,
            updated="2025-01-01",
        )
        reply = Comment(
            id="reply",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Done",
            author=Author(name="Author"),
            unresolved=False,
            updated="2025-01-02",
            in_reply_to="root",
        )
        thread = CommentThread(root_comment=root, replies=[reply])

        assert thread.is_resolved is True

    def test_all_comments(self):
        """Test getting all comments in thread."""
        root = Comment(
            id="root",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Issue",
            author=Author(name="Reviewer"),
            unresolved=True,
            updated="2025-01-01",
        )
        reply1 = Comment(
            id="reply1",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Working on it",
            author=Author(name="Author"),
            unresolved=True,
            updated="2025-01-02",
            in_reply_to="root",
        )
        reply2 = Comment(
            id="reply2",
            patch_set=1,
            file_path="test.py",
            line=10,
            message="Done",
            author=Author(name="Author"),
            unresolved=False,
            updated="2025-01-03",
            in_reply_to="reply1",
        )
        thread = CommentThread(root_comment=root, replies=[reply1, reply2])

        all_comments = thread.all_comments
        assert len(all_comments) == 3
        assert all_comments[0].id == "root"
        assert all_comments[1].id == "reply1"
        assert all_comments[2].id == "reply2"


class TestExtractedComments:
    """Tests for ExtractedComments dataclass."""

    def test_get_unresolved_threads(self):
        """Test filtering to unresolved threads."""
        change_info = ChangeInfo(
            change_id="test",
            change_number=123,
            project="test/project",
            branch="master",
            subject="Test change",
            status="NEW",
            current_revision="abc123",
            owner=Author(name="Owner"),
            url="https://example.com/123",
        )

        resolved_thread = CommentThread(
            root_comment=Comment(
                id="resolved",
                patch_set=1,
                file_path="test.py",
                line=10,
                message="Good",
                author=Author(name="R"),
                unresolved=False,
                updated="2025-01-01",
            )
        )

        unresolved_thread = CommentThread(
            root_comment=Comment(
                id="unresolved",
                patch_set=1,
                file_path="test.py",
                line=20,
                message="Fix this",
                author=Author(name="R"),
                unresolved=True,
                updated="2025-01-01",
            )
        )

        extracted = ExtractedComments(
            change_info=change_info,
            threads=[resolved_thread, unresolved_thread],
            unresolved_count=1,
            total_count=2,
        )

        unresolved = extracted.get_unresolved_threads()
        assert len(unresolved) == 1
        assert unresolved[0].root_comment.id == "unresolved"

    def test_format_summary(self):
        """Test formatting summary."""
        change_info = ChangeInfo(
            change_id="test",
            change_number=123,
            project="test/project",
            branch="master",
            subject="Test change",
            status="NEW",
            current_revision="abc123",
            owner=Author(name="Owner"),
            url="https://example.com/123",
        )

        thread = CommentThread(
            root_comment=Comment(
                id="test",
                patch_set=1,
                file_path="test.py",
                line=10,
                message="Fix this please",
                author=Author(name="Reviewer"),
                unresolved=True,
                updated="2025-01-01",
            )
        )

        extracted = ExtractedComments(
            change_info=change_info,
            threads=[thread],
            unresolved_count=1,
            total_count=1,
        )

        summary = extracted.format_summary()
        assert "Test change" in summary
        assert "Unresolved threads: 1" in summary
        assert "Reviewer" in summary
        assert "Fix this please" in summary


class TestReplyResult:
    """Tests for ReplyResult dataclass."""

    def test_success_result(self):
        """Test successful reply result."""
        result = ReplyResult(
            success=True,
            comment_id="abc123",
            message="Done",
            marked_resolved=True,
        )

        assert result.success is True
        assert result.error is None

        d = result.to_dict()
        assert d["success"] is True
        assert d["marked_resolved"] is True

    def test_failure_result(self):
        """Test failed reply result."""
        result = ReplyResult(
            success=False,
            comment_id="abc123",
            message="Done",
            marked_resolved=False,
            error="API error: 403 Forbidden",
        )

        assert result.success is False
        assert result.error == "API error: 403 Forbidden"
