"""Tests for lustre_crash.cli module."""

import json
import tempfile
from unittest.mock import patch

from click.testing import CliRunner

from lustre_crash.cli import (
    _format_command_result,
    _format_session,
    _get_recipes,
    main,
)
from lustre_crash.session import CommandResult, SessionResult


class TestFormatCommandResult:
    """Tests for _format_command_result()."""

    def test_success(self):
        cr = CommandResult(command="bt", output="some output")
        d = _format_command_result(cr)
        assert d["command"] == "bt"
        assert d["output"] == "some output"
        assert "error" not in d

    def test_error(self):
        cr = CommandResult(
            command="badcmd", output="", error=True,
            error_message="invalid command"
        )
        d = _format_command_result(cr)
        assert d["error"] is True
        assert d["error_message"] == "invalid command"


class TestFormatSession:
    """Tests for _format_session()."""

    def test_basic(self):
        sr = SessionResult(
            commands=[CommandResult(command="bt", output="output")],
            return_code=0,
        )
        d = _format_session(sr)
        assert d["return_code"] == 0
        assert len(d["commands"]) == 1
        assert "init_output" not in d
        assert "stderr" not in d

    def test_with_init_and_stderr(self):
        sr = SessionResult(
            commands=[],
            init_output="crash 8.0.4",
            crash_stderr="some warning",
            return_code=0,
        )
        d = _format_session(sr)
        assert d["init_output"] == "crash 8.0.4"
        assert d["stderr"] == "some warning"


class TestGetRecipes:
    """Tests for _get_recipes()."""

    def test_returns_dict(self):
        recipes = _get_recipes()
        assert isinstance(recipes, dict)
        assert "overview" in recipes
        assert "backtrace" in recipes
        assert "memory" in recipes
        assert "lustre" in recipes
        assert "io" in recipes

    def test_recipe_structure(self):
        recipes = _get_recipes()
        for name, recipe in recipes.items():
            assert "description" in recipe
            assert "analyses" in recipe
            assert isinstance(recipe["analyses"], list)

    def test_lustre_needs_modules(self):
        recipes = _get_recipes()
        assert recipes["lustre"]["needs_modules"] is True
        # Others should not
        assert recipes.get("overview", {}).get("needs_modules") is None


class TestRunCommand:
    """Tests for the 'run' CLI command."""

    @patch("lustre_crash.cli.run_session")
    def test_basic_run(self, mock_session):
        mock_session.return_value = SessionResult(
            commands=[CommandResult(command="bt", output="bt output")],
            return_code=0,
        )

        runner = CliRunner()
        result = runner.invoke(main, ["run", "bt"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["commands"][0]["output"] == "bt output"

    @patch("lustre_crash.cli.run_session")
    def test_run_with_options(self, mock_session):
        mock_session.return_value = SessionResult(
            commands=[CommandResult(command="bt", output="ok")],
            return_code=0,
        )

        runner = CliRunner()
        result = runner.invoke(main, [
            "run", "--vmlinux", "/boot/vmlinux",
            "--vmcore", "/var/crash/vmcore",
            "--timeout", "60",
            "--minimal",
            "--crash-bin", "/usr/bin/crash",
            "--mod-dir", "/path/kos",
            "bt",
        ])

        assert result.exit_code == 0
        mock_session.assert_called_once()
        call_kwargs = mock_session.call_args[1]
        assert call_kwargs["vmlinux"] == "/boot/vmlinux"
        assert call_kwargs["vmcore"] == "/var/crash/vmcore"
        assert call_kwargs["timeout"] == 60
        assert call_kwargs["minimal"] is True
        assert call_kwargs["crash_binary"] == "/usr/bin/crash"
        assert call_kwargs["mod_dir"] == "/path/kos"

    @patch("lustre_crash.cli.run_session")
    def test_run_nonzero_return_code(self, mock_session):
        mock_session.return_value = SessionResult(
            commands=[CommandResult(command="bt", output="")],
            return_code=1,
        )

        runner = CliRunner()
        result = runner.invoke(main, ["run", "bt"])

        assert result.exit_code == 1

    @patch("lustre_crash.cli.run_session", side_effect=FileNotFoundError("crash not found"))
    def test_run_crash_not_found(self, mock_session):
        runner = CliRunner()
        result = runner.invoke(main, ["run", "bt"])

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "error" in data or "NOT_FOUND" in result.output

    @patch("lustre_crash.cli.run_session", side_effect=RuntimeError("oops"))
    def test_run_generic_error(self, mock_session):
        runner = CliRunner()
        result = runner.invoke(main, ["run", "bt"])

        assert result.exit_code == 1

    @patch("lustre_crash.cli.run_session")
    def test_run_pretty(self, mock_session):
        mock_session.return_value = SessionResult(
            commands=[CommandResult(command="bt", output="ok")],
            return_code=0,
        )

        runner = CliRunner()
        result = runner.invoke(main, ["--pretty", "run", "bt"])

        assert result.exit_code == 0
        # Pretty output has indentation
        assert "  " in result.output


class TestScriptCommand:
    """Tests for the 'script' CLI command."""

    @patch("lustre_crash.cli.run_session")
    def test_basic_script(self, mock_session):
        mock_session.return_value = SessionResult(
            commands=[
                CommandResult(command="bt", output="bt out"),
                CommandResult(command="ps", output="ps out"),
            ],
            return_code=0,
        )

        runner = CliRunner()
        with runner.isolated_filesystem():
            with open("cmds.txt", "w") as f:
                f.write("bt\nps\n")
            result = runner.invoke(main, ["script", "cmds.txt"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["commands"]) == 2

    @patch("lustre_crash.cli.run_session")
    def test_script_skips_comments_and_blanks(self, mock_session):
        mock_session.return_value = SessionResult(
            commands=[CommandResult(command="bt", output="out")],
            return_code=0,
        )

        runner = CliRunner()
        with runner.isolated_filesystem():
            with open("cmds.txt", "w") as f:
                f.write("# this is a comment\n\nbt\n\n# another comment\n")
            result = runner.invoke(main, ["script", "cmds.txt"])

        assert result.exit_code == 0
        call_args = mock_session.call_args
        assert call_args[1]["commands"] == ["bt"]

    def test_script_empty_file(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            with open("empty.txt", "w") as f:
                f.write("# only comments\n\n")
            result = runner.invoke(main, ["script", "empty.txt"])

        assert result.exit_code == 2

    @patch("lustre_crash.cli.run_session", side_effect=RuntimeError("boom"))
    def test_script_crash_error(self, mock_session):
        runner = CliRunner()
        with runner.isolated_filesystem():
            with open("cmds.txt", "w") as f:
                f.write("bt\n")
            result = runner.invoke(main, ["script", "cmds.txt"])

        assert result.exit_code == 1


class TestRecipesCommand:
    """Tests for the 'recipes' CLI command."""

    def test_list_recipes(self):
        runner = CliRunner()
        result = runner.invoke(main, ["recipes"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "recipes" in data
        assert "overview" in data["recipes"]

    @patch("lustre_crash.cli.run_drgn_kernel_triage")
    def test_run_recipe(self, mock_triage):
        mock_triage.return_value = {"overview": {"hostname": "test"}}

        runner = CliRunner()
        result = runner.invoke(main, [
            "recipes", "overview",
            "--vmcore", "/path/to/vmcore",
            "--vmlinux", "/path/to/vmlinux",
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["recipe"] == "overview"

    def test_unknown_recipe(self):
        runner = CliRunner()
        result = runner.invoke(main, ["recipes", "nonexistent"])

        assert result.exit_code == 2

    def test_lustre_recipe_requires_mod_dir(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "recipes", "lustre",
            "--vmcore", "/path/to/vmcore",
            "--vmlinux", "/path/to/vmlinux",
        ])

        assert result.exit_code == 2
        assert "mod-dir" in result.output.lower() or "requires" in result.output.lower()

    def test_recipe_requires_vmcore(self):
        runner = CliRunner()
        result = runner.invoke(main, ["recipes", "overview"])

        assert result.exit_code == 2
        assert "vmcore" in result.output.lower() or "requires" in result.output.lower()
