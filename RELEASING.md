# Releasing YNAB TUI

## Release Workflow

### 1. Update CHANGELOG.md

Add an entry for the new version before running the release script:

```markdown
## [0.2.0] - 2024-12-21

### Added
- New feature X

### Fixed
- Bug Y
```

### 2. Run the Release Script

```bash
# Preview what will happen (recommended first)
./scripts/release.py 0.2.0 --dry-run

# Execute the release
./scripts/release.py 0.2.0
```

### 3. Push and Publish

```bash
git push origin main --tags
```

Then publish on PyPI:
1. Go to GitHub → Actions → "Publish to PyPI"
2. Click "Run workflow"
3. Enter the version number (e.g., `0.2.0`)

## What the Release Script Does

1. **Validates** version format (must be semver like `X.Y.Z`)
2. **Checks** tag `vX.Y.Z` doesn't already exist
3. **Checks** new version > current version (skipped for first release)
4. **Verifies** CHANGELOG.md has an entry for this version
5. **Checks** git working directory is clean
6. **Updates** version in `pyproject.toml`
7. **Runs** `make check` (format, lint, typecheck)
8. **Runs** test suite
9. **Builds** package (sdist + wheel)
10. **Commits** the version change
11. **Creates** git tag `vX.Y.Z`

## Script Options

```bash
./scripts/release.py 0.2.0              # Full release
./scripts/release.py 0.2.0 --dry-run    # Preview without changes
./scripts/release.py 0.2.0 --skip-tests # Skip tests (use with caution)
./scripts/release.py 0.2.0 --no-tag     # Skip creating git tag
```

## Version Management

The version is defined in a single place: `pyproject.toml`

```toml
[project]
version = "0.1.0"
```

The `__version__` in Python is read dynamically using `importlib.metadata`:

```python
# src/__init__.py
from importlib.metadata import version
__version__ = version("ynab-tui")
```

## PyPI Trusted Publishing Setup

Before your first release, configure trusted publishing on PyPI:

1. Go to [pypi.org](https://pypi.org) → Log in
2. Go to **Account Settings** → **Publishing**
3. Add new pending publisher:
   - **Owner:** `esterhui`
   - **Repository:** `ynab-tui`
   - **Workflow name:** `publish.yml`
   - **Environment:** `pypi`

## Troubleshooting

### "Tag already exists"

The tag for this version was already created. Either:
- Use a different version number
- Delete the tag if it was created in error: `git tag -d vX.Y.Z`

### "CHANGELOG.md missing entry"

Add a changelog entry before releasing:

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added/Changed/Fixed
- Your changes here
```

### "Working directory has uncommitted changes"

Commit or stash your changes before releasing:

```bash
git stash
./scripts/release.py 0.2.0
git stash pop
```
