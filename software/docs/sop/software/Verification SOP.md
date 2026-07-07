# Verification SOP

## Verification Scripts

### `scripts/verify.ps1` (Windows PowerShell)
```powershell
pwsh scripts/verify.ps1
```

### `scripts/verify.sh` (Linux/CI)
```bash
bash scripts/verify.sh
```

---

## What It Runs

### Firmware C Tests (Blocking)
Compiles and runs each test binary:
1. `test_can_frame.c` + `can_frame.c` -- CAN schema v1 pack/unpack
2. `test_calib.c` + `calib.c` -- calibration fit and telemetry
3. `test_mcp2515.c` + `mcp2515.c` + `can_frame.c` -- MCP2515 loopback
4. `test_can_health.c` + `can_health.c` + `can_frame.c` -- fault-bit policy
5. `test_enum.c` + `enum.c` + `can_frame.c` -- ENUM state machine

Requires: gcc, clang, or cc on PATH.

### Host Python Tests (Blocking)
```bash
python -m pytest host -q
```

Requires: Python 3.11+, pytest, pyarrow.

### Ruff Lint (Advisory locally, Blocking in CI)
```bash
ruff check host
```

### Mypy Type Check (Advisory locally, Blocking in CI)
```bash
mypy host/
```
In CI, mypy runs on all of `host/` with strict settings.

---

## CI Workflow (`.github/workflows/ci.yml`)

Runs on: push to main, all PRs, manual dispatch.

| Step | Tool | Blocking? |
|------|------|-----------|
| Firmware C tests | gcc via `verify.sh` | Yes |
| Host pytest | pytest | Yes |
| Ruff lint | ruff | Yes (CI only) |
| Mypy strict | mypy | Yes (CI only) |

---

## How to Interpret Failures

### C Test Failure
```
firmware test failed: run can_frame
```
- The test binary ran but returned non-zero
- Check `test_can_frame.c` -- which assertion failed?
- If build fails: check includes, missing source files, syntax errors

### Pytest Failure
```
FAILED host/tests/test_codec.py::test_roundtrip
```
- Read the assertion error
- Check if frozen contracts were accidentally modified
- Run specific test: `python -m pytest host/tests/test_codec.py -v`

### Ruff Failure (CI)
```
host/inhabit_bridge/bridge_node.py:42:1: E302 ...
```
- Fix the lint issue locally
- Auto-fix: `ruff check host --fix`

### Mypy Failure (CI)
```
host/inhabit_can/pvt.py:42: error: Incompatible return type
```
- Add/fix type annotations
- Check if a dependency's type stubs are missing

---

## How to Add Tests

### Python Tests
1. Create `host/tests/test_<module>.py`
2. Use pytest conventions: `def test_<name>():`
3. Import from the module under test
4. Run: `python -m pytest host/tests/test_<module>.py -v`

### C Tests
1. Create `firmware/test/test_<module>.c`
2. Include the header, write test functions with assert()
3. Add build+run lines to `scripts/verify.ps1` and `scripts/verify.sh`
4. Run: `pwsh scripts/verify.ps1`

---

## What "Green" Means

All of the following:
- All C test binaries compile and run without assertion failures
- All Python tests pass
- (CI only) ruff reports no errors
- (CI only) mypy reports no type errors

---

## What Counts as a Blocker

| Issue | Blocker? |
|-------|----------|
| C test assertion failure | Yes |
| pytest failure | Yes |
| ruff error (CI) | Yes |
| mypy error (CI) | Yes |
| ruff warning (local) | No (advisory) |
| mypy error (local) | No (advisory) |
| Missing C compiler | No (tests skipped with warning) |
| Missing Python | No (tests skipped with warning) |
