# Releasing

Tokenomics ships two official packages from the same versioned contract:

- Python: `agent-tokenomics`
- TypeScript: `@agent-tokenomics/core`

Both package versions must match the GitHub release tag (`vX.Y.Z`). The release workflow builds the artifacts once, smoke-tests the built packages, then publishes those exact artifacts.

## Before the first release

1. Merge schema/runtime parity work, including #3, before freezing `v0.1.0`.
2. Create GitHub environments named `pypi` and `npm`. Add required reviewers if desired.
3. Configure a PyPI pending Trusted Publisher:
   - project: `agent-tokenomics`
   - owner: `kvnloo`
   - repository: `tokenomics`
   - workflow: `release.yml`
   - environment: `pypi`
4. Bootstrap `@agent-tokenomics/core` once on npm. npm requires the package to exist before a Trusted Publisher can be attached.
5. In the npm package settings, configure GitHub Actions Trusted Publishing:
   - owner: `kvnloo`
   - repository: `tokenomics`
   - workflow: `release.yml`
   - environment: `npm`
   - allow direct `npm publish`
6. After OIDC publishing works, disallow traditional npm publishing tokens.

Do not create a GitHub Release until both registry trust relationships are ready. No long-lived publish token belongs in GitHub Secrets.

## Release

1. Update both versions together:
   - `pyproject.toml`
   - `packages/typescript/package.json`
2. Update `CHANGELOG.md`.
3. Merge to `master`.
4. Create and publish a GitHub Release tagged `vX.Y.Z`.

Publishing the GitHub Release triggers `.github/workflows/release.yml`.
