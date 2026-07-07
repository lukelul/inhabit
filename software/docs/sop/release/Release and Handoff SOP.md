# Release and Handoff SOP

## When Benchmarks Are Green

All BENCHMARKS.md items 1-8 must be green before proceeding.

Verify:
```bash
pwsh scripts/verify.ps1                    # local
gh run list --workflow=verify              # CI
npx gitnexus analyze --force              # re-index
```

---

## Run Ultracode (When Ready)

**Do not run ultracode now.** Only after benchmarks 1-8 are green.

Ultracode prompt:
> "Audit firmware + host for CAN-timing races, ISR safety, schema drift, and untested paths; verify every finding with an independent agent before reporting."

This is a repo-wide hardening pass, not a feature build.

---

## Final Verification

- [ ] `scripts/verify.ps1` passes (all C + Python tests)
- [ ] CI workflow green on `main`
- [ ] No open PRs with unresolved blocking comments
- [ ] GitNexus index fresh and no orphaned modules
- [ ] All frozen contracts verified untouched
- [ ] Risk register reviewed -- no CRITICAL unmitigated risks
- [ ] Documentation vault up to date

---

## Tag / Release

```bash
git tag -a v<version> -m "Release v<version>: <description>"
git push origin v<version>
```

Create a GitHub release:
```bash
gh release create v<version> --title "v<version>" --notes "..."
```

---

## Hardware Handoff

- [ ] Board serial number recorded
- [ ] Calibration data saved (per-pod ADC-to-angle mapping)
- [ ] Known hardware issues documented in risk register
- [ ] Bring-up stage achieved documented
- [ ] Photos of assembled board archived
- [ ] Any scope/logic analyzer captures saved

---

## Documentation Handoff

- [ ] KNOWLEDGE-TRANSFER.md is current
- [ ] Obsidian vault reflects actual system state
- [ ] All TBD items reviewed -- mark as intentionally deferred or resolve
- [ ] SOPs tested (someone followed them successfully)
- [ ] Decision records up to date

---

## Risk Review

- [ ] Risk register reviewed with all stakeholders
- [ ] No CRITICAL risks without mitigation plan
- [ ] Hardware-gated benchmarks have a plan for resolution
- [ ] Timeline for next milestone documented

---

## Next Milestone Planning

After release:
1. Identify next milestone from roadmap (see `.claude/CLAUDE.md`)
2. Update BENCHMARKS.md with new items
3. Update ORCHESTRATION.md with new track assignments
4. Update risk register with newly relevant risks
5. Plan hardware procurement (if Rev-B or new sensors needed)
