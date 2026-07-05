# Releasing gamenote

A stable release is one commit plus one tag; CI does the rest.

## Cutting a release

1. **Bump the version** in `gamenote/__init__.py` (`__version__ = "x.y.z"`).
   This is the only place the version lives — the installer and both CI
   workflows receive it from here.
2. **Move the CHANGELOG notes**: retitle the `## [Unreleased]` section of
   `CHANGELOG.md` to `## [x.y.z] - YYYY-MM-DD`, start a fresh empty
   `## [Unreleased]` above it, and update the link definitions at the bottom
   (add `[x.y.z]: .../compare/v<prev>...vx.y.z`, point `[Unreleased]` at
   `vx.y.z...HEAD`). This section becomes the GitHub release notes verbatim.
3. **Commit and push** to `main`, and wait for CI to go green
   (`tests/test_version.py` fails the run if the CHANGELOG section for the new
   version is missing — a bump is always documented).
4. **Tag and push the tag**:

   ```
   git tag vx.y.z
   git push origin vx.y.z
   ```

The release workflow (`.github/workflows/release.yml`) then:

- fails fast if the tag does not match `gamenote.__version__`,
- re-runs ruff and the test suite (tag pushes do not trigger the CI workflow),
- builds the app (`packaging/build.sh`, which stamps `build_info.json`) and
  the installer (ISCC with `/DMyAppVersion=x.y.z`) on Python 3.14,
- creates the GitHub release titled `vx.y.z` with the CHANGELOG section as
  notes (`packaging/release_notes.py`) and uploads
  `gamenote-setup-x.y.z.exe`.

Users on the stable channel get the update offer automatically: the in-app
updater polls `releases/latest`, which now points at the new release. The
landing page's download buttons also track `releases/latest` on their own.

## If something goes wrong

- **Workflow failed before publishing**: fix the problem, delete the tag
  (`git push --delete origin vx.y.z; git tag -d vx.y.z`), and re-tag the fixed
  commit. Nothing was published, so nothing to clean up.
- **Bad release published**: delete the release *and* the tag on GitHub, then
  release a fixed `x.y.(z+1)`. Do not reuse a version number that shipped —
  installed apps compare versions numerically and would not re-offer it.

## Manual fallback (CI unavailable)

```
bash packaging/build.sh
bash packaging/build-installer.sh
```

This produces `packaging/installer_output/gamenote-setup-<version>.exe` with
the version read from `gamenote/__init__.py`. Create the GitHub release for
the tag by hand and upload the installer as its asset. Use the same Python
version CI uses (3.14) so the shipped runtime stays consistent.

## The dev channel (for context)

Every green push to `main` republishes `gamenote-setup-dev.exe` on the rolling
`dev` prerelease (`build-dev` job in `.github/workflows/ci.yml`). It is fully
automatic and independent of stable releases; stable users never see it
(`releases/latest` excludes prereleases). Opt in via Settings → Updates →
Channel.
