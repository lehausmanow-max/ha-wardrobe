# CLAUDE.md: ha-wardrobe

This repository is the Wardrobe app for Home Assistant. It is **public**. Home Assistant installs it from GitHub as an app repository, and Alex's click on **Update** in Home Assistant is the approval gate for every release.

## You work in this repository only

- Change code in this working copy, run the app locally from `dev/`, and commit, tag and push releases.
- Never connect to the Home Assistant box: no SSH, no SCP, no Docker, no Home Assistant API calls. The rules in `.claude/settings.json` enforce this.

## Never

- Commit secrets, `.env` files or anything under `dev/data/`. Everything pushed here is public and stays in history.
- Change the repository name or URL, the `url:` fields in `repository.yaml` and `wardrobe/config.yaml`, or the `slug:` field in `wardrobe/config.yaml`. The installed slug (`e054cba1_wardrobe`) and the app's data folder depend on them; changing any of them gives a new, empty app.
- Push a change inside `wardrobe/` without a version bump and a tag.
- Move a version number backwards.
- Loosen `.gitattributes`. `run.sh` breaks with Windows line endings.
- Indent lines in `.gitignore`. Git treats leading spaces as part of the pattern.

## Release routine

Home Assistant offers an update only when `version:` in `wardrobe/config.yaml` changes. Changes outside `wardrobe/` (README, `.gitignore`, this file) need no bump.

1. Change the code.
2. Bump `version:` in `wardrobe/config.yaml`: the last number for fixes, the middle one for features.
3. Add a `wardrobe/CHANGELOG.md` entry under the new version. Home Assistant shows it in the update dialog.
4. Stage and check:
   ```
   git add .
   git status
   ```
   Nothing from `dev/data`, no `__pycache__`, no `.db` files. If anything like that is staged, stop and tell Alex.
5. Commit, tag and push. The tag **must be annotated** (`-a`); `--follow-tags` silently skips lightweight tags.
   ```
   git commit -m "Release X.Y.Z: <what changed>"
   git tag -a vX.Y.Z -m "Release X.Y.Z"
   git push --follow-tags
   ```
6. Confirm the tag reached GitHub: `git ls-remote --tags origin vX.Y.Z` must print one line.
7. Tell Alex the version is pushed. He runs Check for updates and Update (with backup ticked) in Home Assistant.

## Releases that change the database

Say so explicitly in the CHANGELOG entry and to Alex before he updates. Rolling back such a release means restoring the update-time backup, not reverting code.
