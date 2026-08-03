# Releasing

Consumers resolve `@v1` **at every run**, so moving that tag instantly changes
CI behavior for every repo that uses it. The release process exists to make
that power safe. The prime directive:

> **Never make a breaking interface change and move `v1` onto it.**
> Backward-compatible → move `v1`. Breaking → new major (`v2`), consumers
> migrate deliberately.

"Breaking" means the *interface*: renaming or removing an input, changing an
input's meaning or default in a way that alters behavior for existing callers,
or requiring a new secret. Swapping tooling *inside* a job (a different secret
scanner, new flags, caching) is not breaking — that's the whole point of the
central repo.

## Release steps

1. **Land the change on `main` via a PR.** The PR must be green on:
   - `Self-check` — actionlint (+ advisory zizmor)
   - `Smoke Test` — the pipelines actually running against
     [`test-fixtures/`](test-fixtures/) (gradle-test, ios-test, compliance,
     secret scan)

2. **Tag an immutable version — nobody is affected yet:**

   ```bash
   git tag v1.1.0
   git push origin v1.1.0
   ```

3. **Canary it.** Point ONE real consumer at the exact tag and let a real PR
   run there:

   ```yaml
   uses: QuietFlare/ci-workflows/.github/workflows/pr-pipeline.yml@v1.1.0
   ```

   The canary covers what the smoke test cannot: real project shape, real
   secrets, and the release path (TestFlight needs real App Store Connect
   credentials, so it is only ever validated by a canary).

4. **Promote — this is the moment every consumer changes:**

   ```bash
   git tag -f v1 v1.1.0
   git push -f origin v1
   ```

   Then revert the canary's pin back to `@v1`.

## Rollback

If a regression ships anyway, un-break every consumer at once by pointing
`v1` back at the last good version — no consumer edits needed:

```bash
git tag -f v1 v1.0.0        # last known good
git push -f origin v1
```

Then fix forward at leisure.

## Consumer pinning options (document, don't dictate)

- `@v1` — floating major: fixes arrive automatically. Right for a small fleet
  the maintainer also operates (i.e. our own repos).
- `@v1.1.0` — immutable: zero surprise; pair with Dependabot's
  `github-actions` ecosystem, which opens bump PRs so each repo's own CI
  validates every upgrade before adoption. Right for large fleets and
  external consumers.
- `@<sha>` — maximum paranoia; same idea as pinning actions by SHA.

## Versioning summary

| Change | Version | Tag motion |
|---|---|---|
| Bug fix, tooling swap inside a job | `v1.x.Y` | move `v1` after canary |
| New input with a safe default, new opt-in job | `v1.X.0` | move `v1` after canary |
| Rename/remove input, new required secret, behavior change for existing callers | `v2.0.0` | new `v2` tag; `v1` keeps working untouched |
