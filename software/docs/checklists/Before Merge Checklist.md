# Before Merge Checklist

- [ ] `scripts/verify.ps1` passes locally
- [ ] CI checks green (`gh pr checks <number>`)
- [ ] New code has at least one test
- [ ] Changes only in track's own directory
- [ ] Frozen contracts untouched (CAN schema v1, RobotAdapter, PVTSample, JointPodState.msg)
- [ ] CodeRabbit has no unresolved Major comments
- [ ] `embedded-reviewer` returns OK (for firmware/host changes)
- [ ] GitNexus `impact()` run on modified symbols -- no HIGH/CRITICAL unaddressed
- [ ] GitNexus `detect_changes()` shows only expected scope
- [ ] Squash merge with descriptive commit message
- [ ] Run `verify.ps1` on `main` after merge
