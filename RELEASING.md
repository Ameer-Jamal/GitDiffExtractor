# Releasing RepoLens

RepoLens uses automated GitHub Actions to build standalone desktop binaries (macOS, Windows, Linux) and Python distribution packages (wheel & sdist), and automatically publish them to GitHub Releases.

## How to Release a New Version

### Option A: Tagging via Git (Recommended)

1. **Verify all tests pass**:
   ```bash
   pytest tests/
   ```

2. **Update version** (if needed):
   In `pyproject.toml`, update:
   ```toml
   version = "1.0.0"
   ```

3. **Commit, tag, and push**:
   ```bash
   git add pyproject.toml
   git commit -m "Release v1.0.0"
   git tag v1.0.0
   git push origin main --tags
   ```

4. **Watch the build**:
   Navigate to the **Actions** tab on GitHub:
   `https://github.com/Ameer-Jamal/GitDiffExtractor/actions`
   The `Release` workflow will:
   - Build Python wheels & source distributions
   - Compile desktop binaries for macOS, Windows, and Linux via PyInstaller
   - Create a GitHub Release titled `Release v1.0.0` with auto-generated release notes
   - Attach all binaries and packages to the release!

---

### Option B: Triggering via GitHub Actions Web UI

1. Go to `https://github.com/Ameer-Jamal/GitDiffExtractor/actions/workflows/release.yml`.
2. Click **Run workflow**.
3. Enter the tag name (e.g., `v1.0.0`).
4. Optionally choose whether to create it as a Draft or Prerelease.
5. Click **Run workflow**.

---

### Optional: Publishing to PyPI

If you wish to also publish the Python package to PyPI (`pip install repolens`):
1. Generate an API token on [pypi.org](https://pypi.org/manage/account/token/).
2. Add it as a secret in your GitHub repository:
   - Go to **Settings > Secrets and variables > Actions > New repository secret**.
   - Name: `PYPI_API_TOKEN`.
   - Value: `<your-pypi-token>`.
3. The release workflow will automatically detect this secret and publish the wheel to PyPI on each release.
