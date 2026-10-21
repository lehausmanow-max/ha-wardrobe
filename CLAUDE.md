# CLAUDE.md: ha-wardrobe

This repository is the Wardrobe app for Home Assistant. It is **public**. Home Assistant installs it from GitHub as an app repository, and Alex's click on **Update** in Home Assistant is the approval gate for every release.

## You work in this repository only

- Change code in this working copy, run the app locally from `dev/`, and commit, tag and push releases.
- Never connect to the Home Assistant box: no SSH, no SCP, no Docker, no Home Assistant API calls. The rules in `.claude/settings.json` enforce this.

## Never

- Commit secrets, `.env` files or anything under `dev/data/`. Everything pushed here is public and stays in history.
- Change the repository name or URL, the `url:` fields in `repository.yaml` and `wardrobe/config.yaml`, or the `slug:` field in `wardrobe/config.yaml`. The installed slug (`e054cba1_wardrobe`) and the app's data folder depend on them; changing any of them gives a new, empty app.
- Push a change inside `wardrobe/` without a version bump and a tag.
- Push to `main` before the CI check on `release` is green for that exact commit.
- Move a version number backwards.
- Loosen `.gitattributes`. `run.sh` breaks with Windows line endings.
- Indent lines in `.gitignore`. Git treats leading spaces as part of the pattern.

## Release routine

Home Assistant offers an update only when `version:` in `wardrobe/config.yaml` changes. Changes outside `wardrobe/` (README, `.gitignore`, this file) need no bump.

Home Assistant offers the update as soon as a bumped `version:` reaches `main`; tags don't matter to it. So every commit goes through the `release` branch first, and reaches `main` only once the CI check (`.github/workflows/check.yml`) is green.

1. Change the code. Run the tests locally (see Tests below).
2. Bump `version:` in `wardrobe/config.yaml`: the last number for fixes, the middle one for features.
3. Add a `wardrobe/CHANGELOG.md` entry under the new version. Home Assistant shows it in the update dialog.
4. Stage and check:
   ```
   git add .
   git status
   ```
   Nothing from `dev/data`, no `__pycache__`, no `.db` files. If anything like that is staged, stop and tell Alex.
5. Commit locally. Don't push to `main` yet.
   ```
   git commit -m "Release X.Y.Z: <what changed>"
   ```
6. Push the commit to the release branch:
   ```
   git push origin HEAD:release
   ```
   This must be a fast-forward. If it's rejected, stop and tell Alex; never force-push.
7. Wait for the check on that commit to finish:
   - With `gh` installed: `gh run watch`.
   - Without it: `curl -s https://api.github.com/repos/lehausmanow-max/ha-wardrobe/commits/$(git rev-parse HEAD)/check-runs`. Every run must show `"status": "completed"` and `"conclusion": "success"`.
   - If neither works, ask Alex to look at the Actions tab.
8. Only when the check is green, push to `main`, then create and push the tag. The tag **must be annotated** (`-a`).
   ```
   git push origin HEAD:main
   git tag -a vX.Y.Z -m "Release X.Y.Z"
   git push origin vX.Y.Z
   ```
9. Confirm the tag reached GitHub: `git ls-remote --tags origin vX.Y.Z` must print one line.
10. Tell Alex the version is pushed. He runs Check for updates and Update (with backup ticked) in Home Assistant.

A red check means fix it with a new commit and repeat from step 6. Nothing reaches `main` until the check is green. Commits that don't bump the version (docs, CI, tests) take the same route, minus steps 2, 3, 8's tag and 9.

## Tests

Tests live in `tests/` at the repo root, so they stay out of the image. They use pytest with no network, run on the same Python minor version as the base image (`PYTHON_VERSION` in `check.yml`), and import the app from `wardrobe/app` (set in `pytest.ini`). Locally, with `uv`:
```
uv run --no-project --python 3.14 --with-requirements wardrobe/app/requirements.txt --with-requirements tests/requirements.txt python -m pytest
```
Use `python -m pytest`, not `pytest`: on this Windows machine uv's `pytest.exe` launcher fails to start. When the base image pin changes, update `PYTHON_VERSION` too; CI fails if they differ.

## Releases that change the database

Say so explicitly in the CHANGELOG entry and to Alex before he updates. Rolling back such a release means restoring the update-time backup, not reverting code.
