#!/usr/bin/env python3
"""Release helper script for YNAB TUI.

Usage:
    ./scripts/release.py 0.2.0           # Prepare release
    ./scripts/release.py 0.2.0 --dry-run # Preview changes without modifying files
    ./scripts/release.py 0.2.0 --tag     # Also create git tag after build
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# Rich is optional - gracefully degrade if not available
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    console = None


# =============================================================================
# Output helpers
# =============================================================================


def print_header(text: str) -> None:
    """Print a section header."""
    if RICH_AVAILABLE:
        console.print(f"\n[bold blue]{'─' * 60}[/]")
        console.print(f"[bold blue]{text}[/]")
        console.print(f"[bold blue]{'─' * 60}[/]")
    else:
        print(f"\n{'─' * 60}")
        print(text)
        print("─" * 60)


def print_success(text: str) -> None:
    """Print success message."""
    if RICH_AVAILABLE:
        console.print(f"[green]✓[/] {text}")
    else:
        print(f"✓ {text}")


def print_error(text: str) -> None:
    """Print error message."""
    if RICH_AVAILABLE:
        console.print(f"[red]✗[/] {text}")
    else:
        print(f"✗ {text}")


def print_info(text: str) -> None:
    """Print info message."""
    if RICH_AVAILABLE:
        console.print(f"[dim]→[/] {text}")
    else:
        print(f"→ {text}")


def print_warning(text: str) -> None:
    """Print warning message."""
    if RICH_AVAILABLE:
        console.print(f"[yellow]![/] {text}")
    else:
        print(f"! {text}")


# =============================================================================
# Version handling
# =============================================================================


@dataclass
class Version:
    """Semantic version."""

    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, version_str: str) -> Version | None:
        """Parse a version string like '0.1.0' or 'v0.1.0'."""
        # Remove leading 'v' if present
        version_str = version_str.lstrip("v")

        match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version_str)
        if not match:
            return None

        return cls(
            major=int(match.group(1)),
            minor=int(match.group(2)),
            patch=int(match.group(3)),
        )

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __gt__(self, other: Version) -> bool:
        if self.major != other.major:
            return self.major > other.major
        if self.minor != other.minor:
            return self.minor > other.minor
        return self.patch > other.patch

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return False
        return (self.major, self.minor, self.patch) == (
            other.major,
            other.minor,
            other.patch,
        )


def get_current_version(root: Path) -> Version | None:
    """Get current version from pyproject.toml."""
    pyproject = root / "pyproject.toml"
    content = pyproject.read_text()

    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        return None

    return Version.parse(match.group(1))


def get_init_version(root: Path) -> Version | None:
    """Get current version from src/__init__.py."""
    init_file = root / "src" / "__init__.py"
    content = init_file.read_text()

    match = re.search(r'^__version__\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        return None

    return Version.parse(match.group(1))


# =============================================================================
# File updates
# =============================================================================


def update_pyproject_version(root: Path, new_version: Version, dry_run: bool) -> bool:
    """Update version in pyproject.toml."""
    pyproject = root / "pyproject.toml"
    content = pyproject.read_text()

    new_content = re.sub(
        r'^(version\s*=\s*)"[^"]+"',
        f'\\1"{new_version}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )

    if content == new_content:
        print_error("Failed to update pyproject.toml - pattern not found")
        return False

    if not dry_run:
        pyproject.write_text(new_content)

    print_success(f"Updated pyproject.toml → {new_version}")
    return True


def update_init_version(root: Path, new_version: Version, dry_run: bool) -> bool:
    """Update version in src/__init__.py."""
    init_file = root / "src" / "__init__.py"
    content = init_file.read_text()

    new_content = re.sub(
        r'^(__version__\s*=\s*)"[^"]+"',
        f'\\1"{new_version}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )

    if content == new_content:
        print_error("Failed to update src/__init__.py - pattern not found")
        return False

    if not dry_run:
        init_file.write_text(new_content)

    print_success(f"Updated src/__init__.py → {new_version}")
    return True


def update_changelog(root: Path, new_version: Version, dry_run: bool) -> bool:
    """Update CHANGELOG.md with release date."""
    changelog = root / "CHANGELOG.md"

    if not changelog.exists():
        print_warning("CHANGELOG.md not found - skipping")
        return True

    content = changelog.read_text()
    today = date.today().isoformat()

    # Try to replace [Unreleased] with the new version
    # Pattern: ## [Unreleased] or ## [X.Y.Z] - Unreleased
    unreleased_pattern = r"## \[Unreleased\]"
    if re.search(unreleased_pattern, content):
        new_content = re.sub(
            unreleased_pattern,
            f"## [{new_version}] - {today}",
            content,
            count=1,
        )
        if not dry_run:
            changelog.write_text(new_content)
        print_success(f"Updated CHANGELOG.md → [{new_version}] - {today}")
        return True

    # Try to update existing version entry without date
    version_pattern = rf"## \[{re.escape(str(new_version))}\](?!\s*-\s*\d)"
    if re.search(version_pattern, content):
        new_content = re.sub(
            version_pattern,
            f"## [{new_version}] - {today}",
            content,
            count=1,
        )
        if not dry_run:
            changelog.write_text(new_content)
        print_success(f"Updated CHANGELOG.md → [{new_version}] - {today}")
        return True

    # Check if version already has a date
    dated_pattern = rf"## \[{re.escape(str(new_version))}\] - \d{{4}}-\d{{2}}-\d{{2}}"
    if re.search(dated_pattern, content):
        print_info(f"CHANGELOG.md already has dated entry for {new_version}")
        return True

    print_warning(f"Could not find [Unreleased] or [{new_version}] in CHANGELOG.md")
    print_info("Please update CHANGELOG.md manually")
    return True


# =============================================================================
# Commands
# =============================================================================


def run_command(cmd: list[str], description: str, dry_run: bool) -> bool:
    """Run a command and report result."""
    print_info(f"{description}...")

    if dry_run:
        print_info(f"[dry-run] Would run: {' '.join(cmd)}")
        return True

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )

        if result.returncode != 0:
            print_error(f"{description} failed!")
            if result.stdout:
                print(result.stdout)
            if result.stderr:
                print(result.stderr)
            return False

        print_success(f"{description} passed")
        return True

    except FileNotFoundError:
        print_error(f"Command not found: {cmd[0]}")
        return False


def check_git_clean(root: Path) -> bool:
    """Check if git working directory is clean."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=root,
        )
        if result.stdout.strip():
            return False
        return True
    except FileNotFoundError:
        return True  # Git not available, skip check


def create_git_tag(root: Path, version: Version, dry_run: bool) -> bool:
    """Create a git tag for the release."""
    tag = f"v{version}"

    if dry_run:
        print_info(f"[dry-run] Would create git tag: {tag}")
        return True

    try:
        result = subprocess.run(
            ["git", "tag", tag],
            capture_output=True,
            text=True,
            cwd=root,
        )
        if result.returncode != 0:
            print_error(f"Failed to create tag: {result.stderr}")
            return False

        print_success(f"Created git tag: {tag}")
        return True
    except FileNotFoundError:
        print_error("Git not found")
        return False


# =============================================================================
# Main
# =============================================================================


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Prepare a release of YNAB TUI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s 0.2.0           Prepare release 0.2.0
  %(prog)s 0.2.0 --dry-run Preview changes without modifying files
  %(prog)s 0.2.0 --tag     Also create git tag after successful build
  %(prog)s 0.2.0 --skip-tests  Skip running tests (faster, but risky)
        """,
    )
    parser.add_argument(
        "version",
        help="Version to release (e.g., 0.2.0 or v0.2.0)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying any files",
    )
    parser.add_argument(
        "--tag",
        action="store_true",
        help="Create git tag after successful build",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip running tests (use with caution)",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow release with uncommitted changes",
    )

    args = parser.parse_args()

    # Find project root
    root = Path(__file__).parent.parent

    # Parse and validate new version
    new_version = Version.parse(args.version)
    if not new_version:
        print_error(f"Invalid version format: {args.version}")
        print_info("Version must be in format: X.Y.Z (e.g., 0.2.0)")
        return 1

    # Get current versions
    current_pyproject = get_current_version(root)
    current_init = get_init_version(root)

    if not current_pyproject:
        print_error("Could not read version from pyproject.toml")
        return 1

    if not current_init:
        print_error("Could not read version from src/__init__.py")
        return 1

    # Display version info
    print_header("Release Preparation")

    if RICH_AVAILABLE:
        table = Table(show_header=True)
        table.add_column("Source", style="cyan")
        table.add_column("Current", style="yellow")
        table.add_column("New", style="green")
        table.add_row("pyproject.toml", str(current_pyproject), str(new_version))
        table.add_row("src/__init__.py", str(current_init), str(new_version))
        console.print(table)
    else:
        print(f"pyproject.toml: {current_pyproject} → {new_version}")
        print(f"src/__init__.py: {current_init} → {new_version}")

    if args.dry_run:
        print_warning("DRY RUN - no files will be modified")

    # Validation checks
    print_header("Validation")

    # Check versions match
    if current_pyproject != current_init:
        print_error(
            f"Version mismatch: pyproject.toml={current_pyproject}, "
            f"__init__.py={current_init}"
        )
        print_info("Fix this before releasing")
        return 1
    print_success("Current versions match")

    # Check new version is greater
    if not new_version > current_pyproject:
        print_error(
            f"New version {new_version} must be greater than current {current_pyproject}"
        )
        return 1
    print_success(f"Version {new_version} > {current_pyproject}")

    # Check git status
    if not args.allow_dirty and not check_git_clean(root):
        print_error("Working directory has uncommitted changes")
        print_info("Commit or stash changes first, or use --allow-dirty")
        return 1
    print_success("Git working directory clean")

    # Update version files
    print_header("Update Files")

    if not update_pyproject_version(root, new_version, args.dry_run):
        return 1

    if not update_init_version(root, new_version, args.dry_run):
        return 1

    if not update_changelog(root, new_version, args.dry_run):
        return 1

    # Run checks
    print_header("Run Checks")

    if not run_command(["make", "check"], "Lint and typecheck", args.dry_run):
        return 1

    if not args.skip_tests:
        if not run_command(
            ["uv", "run", "pytest", "tests/", "-n", "auto", "-q"],
            "Test suite",
            args.dry_run,
        ):
            return 1
    else:
        print_warning("Skipping tests (--skip-tests)")

    # Build
    print_header("Build Package")

    if not run_command(["uv", "build"], "Build package", args.dry_run):
        return 1

    # Create tag if requested
    if args.tag:
        print_header("Git Tag")
        if not create_git_tag(root, new_version, args.dry_run):
            return 1

    # Success!
    print_header("Release Prepared Successfully!")

    if args.dry_run:
        if RICH_AVAILABLE:
            console.print(
                Panel(
                    "[yellow]This was a dry run. "
                    "Run without --dry-run to make changes.[/]",
                    title="Dry Run Complete",
                )
            )
        else:
            print("\nThis was a dry run. Run without --dry-run to make changes.")
    else:
        next_steps = f"""
Next steps:

  1. Review the changes:
     git diff

  2. Commit the release:
     git add -A
     git commit -m "Release v{new_version}"

  3. {"Tag was already created!" if args.tag else f"Create and push tag:"}
     {"" if args.tag else f"git tag v{new_version}"}
     git push origin main --tags

  4. Publish to PyPI:
     Go to GitHub → Actions → "Publish to PyPI"
     Click "Run workflow" with version: {new_version}
"""
        if RICH_AVAILABLE:
            console.print(Panel(next_steps, title="Next Steps", border_style="green"))
        else:
            print(next_steps)

    return 0


if __name__ == "__main__":
    sys.exit(main())
