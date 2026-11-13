# Dependency policy

- **Lockfiles are committed** and CI installs from them only (`uv sync --locked`).
- **Cooldown before adopting new releases.** Dependabot waits 7 days (14 for majors); security updates are not delayed. uv ignores releases newer than 7 days (`exclude-newer`).
- **Scanning:** OSV-Scanner on every PR and weekly; Dependabot alerts and malware alerts.
- **Fix timelines:** critical/high within 7 days, medium within 60 days, low at the next routine update.
- **Adding a dependency:** confirm it exists on the official registry, is maintained, has a compatible licence, and is worth its weight. Prefer the standard library.
- **Allowed licences:** MIT, Apache-2.0, BSD-2/3-Clause, ISC, Unicode-3.0, MPL-2.0 (file-level). Anything else needs an ADR.
