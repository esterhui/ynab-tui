#!/usr/bin/env python3
"""Release helper script for YNAB TUI.

Usage:
    ./scripts/release.py 0.2.0           # Execute release
    ./scripts/release.py 0.2.0 --dry-run # Preview all steps without changes
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


def print_dry_run(text: str) -> None:
    """Print dry-run action."""
    if RICH_AVAILABLE:
        console.print(f"[cyan][DRY-RUN][/] {text}")
    else:
        print(f"[DRY-RUN] {text}")


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

    def suggest_next(self) -> str:
        """Suggest the next patch version."""
        return f"{self.major}.{self.minor}.{self.patch + 1}"


def get_current_version(root: Path) -> Version | None:
    """Get current version from pyproject.toml."""
    pyproject = root / "pyproject.toml"
    content = pyproject.read_text()

    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        return None

    return Version.parse(match.group(1))




# =============================================================================
# Git helpers
# =============================================================================


def get_existing_tags(root: Path) -> list[str]:
    """Get list of existing git tags."""
    try:
        result = subprocess.run(
            ["git", "tag", "--list", "v*"],
            capture_output=True,
            text=True,
            cwd=root,
        )
        if result.stdout.strip():
            return result.stdout.strip().split("\n")
        return []
    except FileNotFoundError:
        return []


def tag_exists(root: Path, version: Version) -> bool:
    """Check if a tag for this version already exists."""
    tag = f"v{version}"
    return tag in get_existing_tags(root)


def check_git_clean(root: Path) -> bool:
    """Check if git working directory is clean."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=root,
        )
        return not result.stdout.strip()
    except FileNotFoundError:
        return True  # Git not available, skip check


def create_git_commit(root: Path, version: Version, dry_run: bool) -> bool:
    """Create a git commit for the release."""
    message = f"Release v{version}"

    if dry_run:
        print_dry_run(f"Would commit: \"{message}\"")
        return True

    try:
        # Stage the changed file
        subprocess.run(
            ["git", "add", "pyproject.toml"],
            capture_output=True,
            text=True,
            cwd=root,
            check=True,
        )

        # Create commit
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True,
            text=True,
            cwd=root,
        )
        if result.returncode != 0:
            print_error(f"Failed to commit: {result.stderr}")
            return False

        print_success(f"Committed: \"{message}\"")
        return True
    except subprocess.CalledProcessError as e:
        print_error(f"Git error: {e}")
        return False
    except FileNotFoundError:
        print_error("Git not found")
        return False


def create_git_tag(root: Path, version: Version, dry_run: bool) -> bool:
    """Create a git tag for the release."""
    tag = f"v{version}"

    if dry_run:
        print_dry_run(f"Would create git tag: {tag}")
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

        print_success(f"Created tag: {tag}")
        return True
    except FileNotFoundError:
        print_error("Git not found")
        return False


# =============================================================================
# CHANGELOG validation
# =============================================================================


def check_changelog_has_version(root: Path, version: Version) -> bool:
    """Check if CHANGELOG.md has an entry for this version."""
    changelog = root / "CHANGELOG.md"

    if not changelog.exists():
        return False

    content = changelog.read_text()

    # Look for ## [X.Y.Z] pattern
    pattern = rf"## \[{re.escape(str(version))}\]"
    return bool(re.search(pattern, content))


# =============================================================================
# File updates
# =============================================================================


def update_pyproject_version(
    root: Path, current: Version, new_version: Version, dry_run: bool
) -> bool:
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

    if dry_run:
        print_dry_run(f"Would update pyproject.toml: {current} → {new_version}")
    else:
        pyproject.write_text(new_content)
        print_success(f"Updated pyproject.toml → {new_version}")

    return True




# =============================================================================
# Commands
# =============================================================================


def run_command(cmd: list[str], description: str, dry_run: bool) -> bool:
    """Run a command and report result."""
    if dry_run:
        print_dry_run(f"Would run: {' '.join(cmd)}")
        return True

    print_info(f"{description}...")

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


# =============================================================================
# Main
# =============================================================================


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Release a new version of YNAB TUI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s 0.2.0           Execute release (update versions, test, build, commit, tag)
  %(prog)s 0.2.0 --dry-run Preview all steps without making any changes
  %(prog)s 0.2.0 --skip-tests  Skip running tests (faster, but risky)
  %(prog)s 0.2.0 --no-tag  Skip creating git tag

Before running, make sure CHANGELOG.md has an entry for the new version.
        """,
    )
    parser.add_argument(
        "version",
        help="Version to release (e.g., 0.2.0 or v0.2.0)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview all steps without making any changes",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip running tests (use with caution)",
    )
    parser.add_argument(
        "--no-tag",
        action="store_true",
        help="Skip creating git tag (tag is created by default)",
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

    # Get current version from pyproject.toml (single source of truth)
    current_version = get_current_version(root)

    if not current_version:
        print_error("Could not read version from pyproject.toml")
        return 1

    # Display header
    print_header(f"Release v{new_version}" + (" (dry-run)" if args.dry_run else ""))

    if RICH_AVAILABLE:
        table = Table(show_header=True)
        table.add_column("", style="cyan")
        table.add_column("Current", style="yellow")
        table.add_column("New", style="green")
        table.add_row("Version", str(current_version), str(new_version))
        console.print(table)
    else:
        print(f"Version: {current_version} → {new_version}")

    # ==========================================================================
    # Validation
    # ==========================================================================
    print_header("Validation")

    # Check if tag already exists
    if tag_exists(root, new_version):
        print_error(f"Tag v{new_version} already exists!")
        print_info(f"Did you mean v{new_version.suggest_next()}?")
        return 1
    print_success(f"Tag v{new_version} does not exist")

    # Check version increment (skip for first release)
    existing_tags = get_existing_tags(root)
    if existing_tags:
        # Not first release - require version > current
        if not new_version > current_version:
            print_error(
                f"New version {new_version} must be greater than current "
                f"{current_version}"
            )
            return 1
        print_success(f"Version {new_version} > {current_version}")
    else:
        print_success("First release - skipping version comparison")

    # Check CHANGELOG has entry for this version
    if not check_changelog_has_version(root, new_version):
        print_error(f"CHANGELOG.md missing entry for version {new_version}")
        print()
        print_info("Please add a changelog entry before releasing:")
        print()
        print(f"    ## [{new_version}] - {date.today().isoformat()}")
        print()
        print("    ### Added")
        print("    - Your changes here")
        print()
        return 1
    print_success(f"CHANGELOG.md has entry for [{new_version}]")

    # Check git working directory is clean
    if not check_git_clean(root):
        print_error("Git working directory has uncommitted changes")
        print_info("Commit or stash changes before releasing")
        return 1
    print_success("Git working directory clean")

    # ==========================================================================
    # Update version file
    # ==========================================================================
    print_header("Update Version")

    if not update_pyproject_version(root, current_version, new_version, args.dry_run):
        return 1

    # ==========================================================================
    # Run checks and tests
    # ==========================================================================
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

    # ==========================================================================
    # Build package
    # ==========================================================================
    print_header("Build & Tag")

    if not run_command(["uv", "build"], "Build package", args.dry_run):
        return 1

    # Show built artifacts (not in dry-run)
    if not args.dry_run:
        dist_dir = root / "dist"
        wheel = dist_dir / f"ynab_tui-{new_version}-py3-none-any.whl"
        if wheel.exists():
            print_success(f"Package built: {wheel.name}")

    # ==========================================================================
    # Commit and tag
    # ==========================================================================
    if not create_git_commit(root, new_version, args.dry_run):
        return 1

    if not args.no_tag:
        if not create_git_tag(root, new_version, args.dry_run):
            return 1

    # ==========================================================================
    # Success!
    # ==========================================================================
    if args.dry_run:
        print_header("DRY RUN COMPLETE")
        print()
        print_info("No changes were made.")
        print()
        print("To execute this release, run:")
        print(f"  ./scripts/release.py {new_version}")
        print()
    else:
        print_header(f"Release v{new_version} Complete!")
        print()
        next_steps = f"""\
Next steps:
  git push origin main --tags

Then publish on PyPI:
  GitHub → Actions → "Publish to PyPI" → Run with version: {new_version}
"""
        if RICH_AVAILABLE:
            console.print(Panel(next_steps, border_style="green"))
        else:
            print(next_steps)

    return 0


if __name__ == "__main__":
    sys.exit(main())
