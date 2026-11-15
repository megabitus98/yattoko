# Releases: version numbers, release notes, version in the bot

2026-11-15. Owner-approved direction (conversation of 2026-11-15); this document is the written design for review.

## Why

Today every promoted merge moves `stable` and gets a dated image tag (`2026.11.15-3587cf8`), but nothing says what changed or which version is running. The owner wants proper releases: a version number per release, a changelog, and the running version visible. Dependency updates should count up the last number (v1.0.1, v1.0.2, ...), real changes the higher ones.

## Goals

- Every promote that moves `stable` is one release with a SemVer version `vX.Y.Z`, no human step.
- The bump comes from the PR title: `deps:` (Dependabot) and `fix:` and every other known type are a patch, `feat:` a minor, a `!` after the type (`feat!:`, `fix!:`) a major.
- A GitHub Release per version, with the PR title and description as notes. The Releases page is the changelog.
- The git commit and the image get the tag `vX.Y.Z` (rollback target), next to `stable` and the dated tag.
- `/about` shows the running version.
- After an update the bot messages each owner once: new version, previous version, the release title, a link to the release.

## Non-goals

- No `CHANGELOG.md` file in the repository: the pipeline would have to commit to `main` after the tests (an untested tree, against the promote rule), and Dependabot cannot edit it.
- No release PRs (release-please style): a human would have to merge each one, which breaks the Dependabot auto-merge.
- No version in `pyproject.toml`: it stays as it is and is not the release version; the git tag is.
- No releases for anything that does not move `stable` (promote finds nothing to promote: no version).

## Anti-goals (a failure even if it works)

- An image whose baked version differs from the release it is published as.
- A version number reused, skipped by a race and then reused, or decided by guessing an unclear title.
- Any new job with a write token that checks out code or runs an action (the existing pipeline rule).

## Constraints from the current pipeline

- `promote.yml` is the only writer of `stable` and promotes only the exact image its PR head was tested as. It already finds the PR (from `merge`'s input or `commits/<sha>/pulls`) and checks that `main`'s tree equals the tested head's tree. It now needs `contents: write` to create the tag and the release; it still checks out nothing and runs no action.
- The image is built in `ci.yml`'s `unit` job (read-only token, full history checked out). The version must be baked in there, before the tests, so it has to be computed at build time.
- Titles reach scripts only through `env:`, never inline `${{ }}` in `run:` (script injection).
- `tests/repo/test_pipeline_files.py` enforces the security rules; it changes with the pipeline.

## Approach (chosen)

The version is computed twice, from the same rule, and must agree:

1. **Title and build (`unit`):** `unit` reads the PR title live from the API (not from the event payload, which a re-run reuses unchanged, so a re-run after fixing a title sees the new one) and fails at once, before the build, unless it matches `^(feat|fix|deps|docs|ci|test|build|chore|refactor|perf)(\([a-z0-9-]+\))?!?: .+`. The base is the commit on `main` the PR is built on. If a `promote` run for that commit is queued or running, `unit` waits for it (bounded, about 15 minutes; it needs `actions: read`). Next version = the nearest `v*.*.*` tag on the base's history, bumped by the title's type; no tag at all makes the first release `v1.0.0` whatever the type. Baked as build args into the image: `APP_VERSION`, `APP_RELEASE_TITLE` (the PR title) and `APP_RELEASE_URL` (`<server>/<repo>/releases/tag/<version>`), as env vars and as the label `org.opencontainers.image.version`.
2. **Promote:** after its existing checks it reads the PR title again, computes the next version from the nearest tag on the parent of the `main` commit with the same rule, reads the image's version label, and fails (with the existing promote-failed message) when they differ or the tag already exists. Otherwise it tags the image `vX.Y.Z` (with `stable` and the dated tag, one `imagetools create`), creates the git tag on the `main` commit and a GitHub Release (title = version and PR title, body = the notes of every PR merged since the previous tag, newest first; normally just this one; marked latest).

Why the two computations agree: a PR is promoted only when `main`'s tree equals its tested tree, so its base is the commit just before it on `main`, and `unit` waited until that base had its tag.

When they still differ, the commit is not released and ships with the next release, the same as a direct push to `main` today (the next release's notes list it). Two causes remain, and the failure message names them: the title's type was changed after CI (to release this PR as it is, push a new commit to it before merging, so the image is built again: `push` never replaces an existing `sha-<head>` image, so a re-run alone does not help), or a promote race the wait did not catch.

### Why there is no separate title job (builder check, my call)

A `title` job on `pull_request: edited` inside `ci.yml` would clash with three rules: the `ci-<pr>` concurrency group cancels a running regression on every title or body edit; `notify` would report that cancel as a failure (the head did not change); and promote's `green()` takes the newest run of each check, so skipped edit runs would block the release. Checking the title in `unit` avoids all three, and promote checks it again.

### Write tokens

`promote` gains `contents: write` for the tag and the release (`merge` already holds it to merge). It still checks out nothing and runs no action.

### Approaches considered

- **SemVer from PR titles at promote (chosen):** no human step, fits the Dependabot auto-merge, notes come from what is already written.
- **release-please / release PRs:** good changelogs, but a human merges each release PR; Dependabot updates would pile up unreleased.
- **CalVer only (keep the dated tags):** zero work, but the owner asked for SemVer with patch numbers for dependency updates.

## Dependabot

`dependabot.yml` sets `commit-message: prefix: "deps"` for all three ecosystems, so its PR titles start with `deps:`. Its PRs then pass the title check and become patch releases.

## The bot

- `config.config`: `APP_VERSION` (default `dev`), `APP_RELEASE_TITLE`, `APP_RELEASE_URL` (default empty); read like every other setting.
- `/about` (`BotText.about`) gets a version line.
- Startup announcement in `main.serve()` after `app.start()`: the last announced version is kept in SQLite (a new one-row key/value table created by `create_all`, no migration). If it is unset (first start) store it silently; if it differs from `APP_VERSION`, send each owner one plain-text message (`send_to_owners`) with the new and previous version, the title and the link, then store it. `dev` never announces. A version skipped between two Keel polls is not announced separately; the message names the previous running version, and the link leads to the Releases page.
- The message text lives in `BotText`; it must not leak anything private (versions, a PR title and a GitHub link are fine).

## Rollout

- This change itself is a `feat:` PR. No release tags exist yet, so it becomes `v1.0.0`; the current `stable` stays untagged.
- Docs: README (versions and releases), `deploy/README.md` (the `title` check, promote creates releases, `vX.Y.Z` image tags for rollback), `AGENTS.md`.

## Left to the builder

- Exact names: the new job, the SQLite table, build-arg and env names if better ones fit.
- How the tag is found (`git tag --merged`, `git describe`, or the API) as long as `unit` and `promote` use the same rule.
- The wording of the announcement and the `/about` line.
- Tests: `promote` holds a write token, so it checks out nothing and cannot share a helper file with `unit`; the bump rule and the title regex are written in both workflows, and a repository test checks that both copies are the same. Pipeline tests for the new permissions (`actions: read` on `unit`, `contents: write` on `promote`) and the title check.
- Promote's step order, and what a re-run does after a partial failure (image tagged but no release yet, or the `stable == digest` early exit): a re-run must finish a half-done release, never mint a second version.
- Dependabot PRs already open when this lands have titles without `deps:`; `@dependabot recreate` or a manual title edit plus a re-run fixes them.
