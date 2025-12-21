# Releasing YNAB TUI

This document describes the release process for YNAB TUI.

## Quick Release

Use the release script for a streamlined release process:

```bash
# Prepare a release (updates versions, changelog, runs checks)
./scripts/release.py 0.2.0

# Or with --dry-run to see what would happen
./scripts/release.py 0.2.0 --dry-run
```

The script will:
1. Validate the version format (must be valid semver like `0.2.0`)
2. Ensure version is greater than current version
3. Update version in `pyproject.toml` and `src/__init__.py`
4. Update `CHANGELOG.md` with the release date
5. Run all checks (format, lint, typecheck)
6. Run the test suite
7. Build the package (sdist + wheel)
8. Show next steps for committing and publishing

## Manual Release Process

If you prefer to release manually, follow these steps:

### 1. Update Version Numbers

Update the version in **both** files (they must match):

```bash
# pyproject.toml line 3
version = "X.Y.Z"

# src/__init__.py line 3
__version__ = "X.Y.Z"
```

### 2. Update CHANGELOG.md

Change the `[Unreleased]` section to the new version with today's date:

```markdown
## [X.Y.Z] - YYYY-MM-DD
```

### 3. Run Checks

```bash
make check      # Format, lint, typecheck
make test       # Run test suite
```

### 4. Build the Package

```bash
make build
```

This creates:
- `dist/ynab_tui-X.Y.Z.tar.gz` (source distribution)
- `dist/ynab_tui-X.Y.Z-py3-none-any.whl` (wheel)

### 5. Commit and Tag

```bash
git add -A
git commit -m "Release vX.Y.Z"
git tag vX.Y.Z
git push origin main --tags
```

### 6. Publish to PyPI

Go to GitHub Actions and trigger the "Publish to PyPI" workflow:

1. Navigate to **Actions** → **Publish to PyPI**
2. Click **Run workflow**
3. Enter the version (e.g., `0.2.0`)
4. Click **Run workflow**

The workflow will:
- Validate that the version matches `pyproject.toml` and `src/__init__.py`
- Run the test suite
- Build the package
- Publish to PyPI using trusted publishing

## Makefile Targets

| Target | Description |
|--------|-------------|
| `make version-check` | Verify version consistency between pyproject.toml and __init__.py |
| `make build` | Build sdist and wheel using `uv build` |
| `make release` | Full release check: version-check → check → test → build |

### What `make release` Does

```bash
make release
```

This runs the following in sequence:
1. **version-check** - Ensures `pyproject.toml` and `src/__init__.py` have matching versions
2. **check** - Runs `ruff format`, `ruff check --fix`, and `mypy`
3. **test** - Runs `pytest tests/ -n auto -q`
4. **build** - Creates distribution files in `dist/`

After completion, it prints next steps for tagging and publishing.

## Version Numbering

We follow [Semantic Versioning](https://semver.org/):

- **MAJOR.MINOR.PATCH** (e.g., `1.2.3`)
- **MAJOR**: Breaking changes
- **MINOR**: New features (backwards compatible)
- **PATCH**: Bug fixes (backwards compatible)

Pre-release versions:
- `0.x.y` - Initial development (API may change)
- `1.0.0` - First stable release

## PyPI Trusted Publishing Setup

Before your first release, configure PyPI trusted publishing:

1. Go to [pypi.org](https://pypi.org) and log in
2. Go to **Account Settings** → **Publishing**
3. Add a new publisher:
   - **Owner**: `esterhui`
   - **Repository**: `ynab-tui`
   - **Workflow name**: `publish.yml`
   - **Environment**: `pypi`

This allows GitHub Actions to publish without storing API tokens.

## Troubleshooting

### Version Mismatch Error

If you see "Version mismatch" errors:

```bash
make version-check
```

Ensure both files have the exact same version string.

### Build Fails

If the build fails, check:
- All tests pass: `make test`
- No lint errors: `make check`
- Valid pyproject.toml syntax

### GitHub Actions Fails

Check the workflow logs in the Actions tab. Common issues:
- Version input doesn't match codebase version
- Missing PyPI trusted publisher configuration
- Test failures

## Release Checklist

- [ ] Version updated in `pyproject.toml`
- [ ] Version updated in `src/__init__.py`
- [ ] CHANGELOG.md updated with release date
- [ ] `make check` passes
- [ ] `make test` passes
- [ ] `make build` succeeds
- [ ] Changes committed
- [ ] Git tag created (`vX.Y.Z`)
- [ ] Tag pushed to GitHub
- [ ] GitHub Action triggered and succeeded
- [ ] Package visible on PyPI
