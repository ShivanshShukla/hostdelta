# Release procedure

A version number and a successful fixture suite are not substitutes for deployment
acceptance. Record what was verified, where it was verified and which optional
features remain untested. The project can produce installable release artifacts
without claiming that every cloud/distribution combination has been certified.

## Before tagging

- [ ] Update `src/hostdelta/__init__.py`, `pyproject.toml`, documentation and changelog together.
- [ ] Run the complete test suite on supported Python/Linux combinations and macOS tooling.
- [ ] Run `scripts/verify_live.py` on the target systemd Linux/OpenStack deployment.
- [ ] Run the Proxmox acceptance procedure if advertising that deployment as verified.
- [ ] Complete the isolated restart/recovery and selected TCP-mode procedures.
- [ ] Verify v1-to-v2 migration and a rollback using a pre-upgrade backup.
- [ ] Review source permissions, credentials, redaction and configuration examples.
- [ ] Review the source archive contents; exclude credentials, local databases and private logs.
- [ ] Check wheel installation and executable-archive behavior in a clean environment.
- [ ] Review all source/coverage limitations in the release notes.

## Build

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m pip wheel --no-deps --wheel-dir dist .
python3 scripts/build_release.py
```

The build produces a source tarball, `hostdelta.pyz`, and `SHA256SUMS`. If the wheel
is already present, it is included in the checksum manifest. Runtime dependencies
remain empty. The wheel's isolated build needs setuptools; the source/zipapp build
does not download anything.

In a clean virtual environment, install the wheel with `--no-index --no-deps` and
verify `hostdelta --version`, JSON configuration validation and the test suite.
On Linux, perform initialization and a one-shot collection under the intended
operating identity. Follow `docs/operations.md` for upgrade and rollback.

## Publish

The manual release workflow builds and uploads CI artifacts but does not automatically
publish to PyPI, create a GitHub release, or push a tag. A maintainer reviews the live
acceptance report and artifacts, then publishes a tag/release through the repository's
normal process. Never substitute a similarly named package on a public index.

Release notes should include the supported version, checksums, relevant migration
steps, actual verification environments and any known limitations. Do not mark
untested live integrations as passed. Attach sanitized acceptance results when useful.

## Current verification record

The implementation includes unit tests, transaction/recovery tests, subprocess
lifecycle tests and loopback HTTP protocol integration tests. The initial local
verification environment is macOS with Python 3.14. Live OpenStack/Proxmox acceptance
is intentionally performed by the deployment owner using `docs/live-validation.md`.
CI configuration is supplied; a configured workflow is not itself evidence that the
remote CI run has completed.
