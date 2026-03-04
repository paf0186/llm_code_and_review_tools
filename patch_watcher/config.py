"""Configuration loading for patch watcher."""

import os
from dataclasses import dataclass
from pathlib import Path


def _load_env_file() -> None:
    """Load environment variables from .env file in standard locations.

    Only sets variables that are not already in the environment.
    Uses stdlib parsing (no dotenv dependency).
    """
    env_locations = [
        Path.home() / ".config" / "patch-watcher" / ".env",
        Path("/shared/support_files/.env"),
        Path(".env"),
    ]
    for env_path in env_locations:
        if env_path.exists():
            _parse_env_file(env_path)
            return


def _parse_env_file(path: Path) -> None:
    """Parse a simple KEY=VALUE .env file into os.environ.

    Supports:
      - Lines with KEY=VALUE (optional quoting with ' or ")
      - Comments (#) and blank lines are skipped
      - Does NOT override existing environment variables
    """
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Strip matching quotes
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value


_load_env_file()


@dataclass
class PatchWatcherConfig:
    """Patch watcher configuration.

    Attributes:
        patches_file: Path to the patches JSON file.
        report_file: Path where the report JSON is written.
        watcher_tool: Path to watcher_tool.sh.
    """

    patches_file: str = ""
    report_file: str = ""
    watcher_tool: str = ""

    def __post_init__(self) -> None:
        watcher_dir = str(Path(__file__).resolve().parent)

        # patches_file: PATCH_WATCHER_PATCHES_FILE > PATCHES_FILE > default
        if not self.patches_file:
            self.patches_file = os.environ.get(
                "PATCH_WATCHER_PATCHES_FILE",
                os.environ.get(
                    "PATCHES_FILE",
                    "/shared/support_files/patches_to_watch.json",
                ),
            )

        # report_file: PATCH_WATCHER_REPORT_FILE > REPORT_FILE > default
        if not self.report_file:
            self.report_file = os.environ.get(
                "PATCH_WATCHER_REPORT_FILE",
                os.environ.get(
                    "REPORT_FILE",
                    "/tmp/patch_watcher_report.json",
                ),
            )

        # watcher_tool: PATCH_WATCHER_TOOL_PATH > derived from __file__
        if not self.watcher_tool:
            self.watcher_tool = os.environ.get(
                "PATCH_WATCHER_TOOL_PATH",
                os.path.join(watcher_dir, "watcher_tool.sh"),
            )

        # --- Validation ---
        watcher_path = Path(self.watcher_tool)
        if not watcher_path.exists():
            raise FileNotFoundError(
                f"watcher_tool.sh not found at {self.watcher_tool}\n"
                f"Set PATCH_WATCHER_TOOL_PATH or ensure watcher_tool.sh "
                f"is in {watcher_dir}/"
            )
        if not os.access(self.watcher_tool, os.X_OK):
            raise PermissionError(
                f"watcher_tool.sh is not executable: {self.watcher_tool}"
            )

        patches_path = Path(self.patches_file)
        if not patches_path.exists():
            raise FileNotFoundError(
                f"Patches file not found: {self.patches_file}\n"
                f"Set PATCH_WATCHER_PATCHES_FILE or PATCHES_FILE, "
                f"or create the file at the default location."
            )


def load_config(
    patches_file: str | None = None,
    report_file: str | None = None,
    watcher_tool: str | None = None,
) -> PatchWatcherConfig:
    """Load patch watcher configuration from environment.

    Explicit arguments override environment variables.
    """
    return PatchWatcherConfig(
        patches_file=patches_file or "",
        report_file=report_file or "",
        watcher_tool=watcher_tool or "",
    )
