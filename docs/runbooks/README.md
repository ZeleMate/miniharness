# Runbooks

One file per operational task: deploy, rollback, rotate a secret, restore a backup, respond to a security report. Keep each to a numbered list someone (or an agent) can follow under stress.

Quarterly checklist:

- [ ] `copier update` to pull template changes (the weekly `template-update` workflow opens an issue when one is available)
- [ ] Review tooling versions and the threat model
- [ ] Rotate secrets that are due (see `docs/secrets.md`)
- [ ] Test restoring a backup
