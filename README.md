# ci-workflows

Reusable GitHub Actions workflows for **indie iOS and Kotlin Multiplatform apps** — a PR pipeline, a release pipeline, and the building blocks behind them, designed around one constraint big-company CI guides ignore: **macOS runner minutes are expensive** (10× billing on private repos, free on public ones), and a solo developer's CI should spend them deliberately.

```yaml
# .github/workflows/ci.yml — a complete PR gate in twelve lines
on:
  pull_request:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  pr:
    uses: QuietFlare/ci-workflows/.github/workflows/pr-pipeline.yml@v1
    with:
      project: MyApp.xcodeproj
      scheme: MyApp
```

## What's inside

Three **pipelines** — the batteries-included entry points:

| Pipeline | What it runs | When to trigger it |
|---|---|---|
| [`pr-pipeline.yml`](.github/workflows/pr-pipeline.yml) | Gradle tests (Ubuntu) → iOS simulator tests + SwiftLint (macOS) → AI code review | `pull_request` |
| [`release-pipeline.yml`](.github/workflows/release-pipeline.yml) | the same tests, then archive + upload to **TestFlight** via App Store Connect cloud signing | version tags (`v*`) |
| [`security-pipeline.yml`](.github/workflows/security-pipeline.yml) | secret scan + dependency review + App Store compliance preflight (all Ubuntu, seconds-cheap) → opt-in CodeQL | `pull_request` + weekly schedule |

Seven **building blocks** — call them directly when you want a different composition:

| Workflow | Runner | What it does |
|---|---|---|
| [`ios-test.yml`](.github/workflows/ios-test.yml) | macOS | Build + simulator tests, no signing needed; optional SwiftLint; optional JDK/Gradle setup for KMP projects; always uploads the `.xcresult` |
| [`gradle-test.yml`](.github/workflows/gradle-test.yml) | Ubuntu | JVM/KMP/Android-unit Gradle tests with build cache + wrapper validation — the cheap tier; put everything you can here |
| [`ai-review.yml`](.github/workflows/ai-review.yml) | Ubuntu | Automated PR review via [PR-Agent](https://github.com/qodo-ai/pr-agent); defaults to Gemini Flash (free tier), swappable to any LiteLLM model |
| [`codeql-swift.yml`](.github/workflows/codeql-swift.yml) | macOS | CodeQL static analysis of Swift; uploads to the Security tab (free on public repos) or attaches the SARIF as an artifact (private repos without Advanced Security) |
| [`testflight.yml`](.github/workflows/testflight.yml) | macOS | Archive + TestFlight upload using an App Store Connect API key — no certificates in the repo |
| [`security-scan.yml`](.github/workflows/security-scan.yml) | Ubuntu | [gitleaks](https://github.com/gitleaks/gitleaks) full-history secret scan + GitHub dependency review of PR-introduced dependencies |
| [`ios-compliance.yml`](.github/workflows/ios-compliance.yml) | Ubuntu | App Store preflight: privacy manifest present, `ITSAppUsesNonExemptEncryption` declared, no signing material (.p8/.p12/.mobileprovision) committed |

Complete caller workflows to copy live in [`examples/`](examples/): a [plain SwiftUI app](examples/pr-ci.yml), a [KMP + iOS app](examples/kmp-pr-ci.yml), a [tag-triggered release](examples/release.yml), a [security pipeline](examples/security.yml), and a [scheduled CodeQL scan](examples/codeql.yml).

Every input is documented inline in each workflow's `workflow_call` block, with a minimal caller in its header comment.

## Design principles

- **Cost-aware by default.** Triggers always live in *your* repo, so a private repo can gate macOS jobs behind `pull_request` + `workflow_dispatch` only, while a public repo (free minutes) runs everything on every push. The expensive jobs never hide behind a default you didn't choose.
- **Two test tiers.** Anything testable on the JVM runs on Ubuntu at ~1/10th the cost. macOS is reserved for what genuinely needs a simulator: the app itself, the Swift↔Kotlin bridge, Keychain, and friends.
- **No signing secrets in CI tests.** Test jobs run with `CODE_SIGNING_ALLOWED=NO`. Only the release path touches signing, and it uses App Store Connect **cloud signing** — three secrets, zero certificates or provisioning profiles committed anywhere.
- **Fail loud, ship evidence.** Test result bundles upload pass or fail; Gradle HTML reports upload on failure; the release pipeline re-tests the exact commit being shipped.
- **KMP is a first-class citizen.** Any workflow that runs `xcodebuild` accepts a `java-version` input for projects whose Xcode build embeds a Kotlin Multiplatform framework via a Gradle pre-build step.

## Requirements & secrets

| Feature | Needs |
|---|---|
| iOS/Gradle tests | nothing — works out of the box |
| Secret scan / compliance preflight | nothing — works out of the box |
| Dependency review | the dependency graph: free on public repos; private repos need GitHub Advanced Security |
| AI review | one repo secret: `GEMINI_API_KEY` ([free from Google AI Studio](https://aistudio.google.com/apikey)) — or an OpenAI key and a `review-model` change |
| TestFlight | `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_P8` from an [App Store Connect API key](https://appstoreconnect.apple.com/access/integrations/api), plus an `ExportOptions.plist` in your repo |
| CodeQL → Security tab | public repo (free) or GitHub Advanced Security; otherwise use `upload: false` for artifact mode |

## Picking Xcode and simulator versions

The `xcode-version` / `destination` defaults (`'16'` / `iPhone 16` on `macos-15`) are chosen to match what's **preinstalled on the runner image** — the most common CI failure mode is selecting an Xcode whose iOS simulator runtime isn't on the image, which surfaces as "no destination found". Check the [runner image manifests](https://github.com/actions/runner-images) when overriding, and pin a simulator device you can see in the image's list.

Release archives are different: they build for device (no simulator needed), so `release-pipeline.yml` defaults the archive step to `latest-stable` — Apple expects submissions built with a current toolchain.

## Versioning

Pin the major tag and get fixes automatically:

```yaml
uses: QuietFlare/ci-workflows/.github/workflows/pr-pipeline.yml@v1
```

- `v1` — floating major tag, moved forward for fixes and backward-compatible additions (same model as `actions/checkout`).
- `v1.x.y` — immutable semver tags if you want zero surprise.
- Breaking input changes only ever land in a new major (`v2`).

## License

[MIT](LICENSE)
