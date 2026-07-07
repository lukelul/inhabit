# Dataset / ML Export Readiness

How a real bench capture safely becomes ML-ready PVT episodes. This is the operator
runbook for the `.canlog -> parquet -> lerobot` path plus the exact validation /
quarantine rules the code already enforces (cited to source so this doc cannot drift).

The dataset is the business. Optimize for QUALITY. The strength of the guarantee
depends on the path, so be precise about which one you ran (see below) — do not read
"nothing half-valid is exported" as a blanket claim.

**Two export paths, different scopes:**
- **`EpisodeRecorder` (branch A)** — the GATED, atomic, per-episode dataset writer and
  the production path. It drops corrupt-checksum and non-finite (NaN/inf) frames at
  ingest, measures jitter ONCE over the whole episode, and QUARANTINES (writes nothing
  to the dataset; records a sidecar reason) any episode that goes backwards, has a
  dropout, exceeds the p99 jitter budget, or is too short. For the recorder path the
  strong claim holds: nothing half-valid ever lands in the dataset.
- **`tools.dataset` CLI / `export_lerobot` (branch B)** — a CONVENIENCE exporter over
  already-built `Episode` objects. It is NO LONGER gate-free:
  - It drops corrupt-checksum / non-finite frames using the SAME policy as the recorder
    (`logger.recorder.frame_reject_reason`), so the two paths cannot disagree on what a
    bad frame is (C1/C4). The canlog loader uses the REAL on-disk RX timestamp, not the
    replay re-stamp, so timing is the capture's.
  - `export_lerobot` runs a per-episode time-quality gate (C2): it REFUSES (skips, lists
    under `meta/info.json -> rejected_episodes`) any episode that is non-monotonic or has
    a dropout, and FLAGS (`quality_failed` in `meta/episodes.jsonl`, still exported) one
    whose p99 jitter exceeds budget.
  - It is still coarser than the recorder: it does not quarantine per-episode atomically
    and does not write provenance footers. For production datasets, route through the
    recorder.

---

## 1. The full pipeline

```text
real Rev-A board / bench rig
   |  (host bridge stamps each RX frame on ONE monotonic clock)
   v
.canlog  (JSONL, one frame per line)            transport/file.py : FileRecorder
   |   each record carries the real RX t_ns captured at record time
   |
   +--- branch A (gated dataset writer) ----------------------------+
   |    FileReplayTransport.recv()                transport/file.py:115
   |      re-stamps each frame: time.monotonic_ns() at recv (see NOTE)
   |    fields_from_frame(frame.data)             inhabit_bridge/conversion.py:55
   |      FROZEN CAN codec v1 -> PodFields (checksum_valid, schema_version)
   |    JointPodState (header_stamp_ns = the chosen monotonic stamp)
   |    EpisodeRecorder.ingest -> finalize        logger/recorder.py
   |      drop corrupt/non-finite frames, measure jitter, EXPORT or QUARANTINE
   |      PASS -> <out_dir>/<episode_id>.parquet  logger/parquet_io.py
   |      FAIL -> <out_dir>/quarantine/<id>.quarantine.json
   |    read_episode()  -> round-trips exactly    logger/parquet_io.py:131
   |    NOTE: recorder timing is only trustworthy if you feed it REAL RX stamps,
   |          NOT the FileReplayTransport re-stamp (see NOTE + section 4).
   |
   +--- branch B (CLI canlog -> lerobot export) --------------------+
        tools/dataset _load_canlog_episode         tools/dataset/__main__.py:20
          reads on-disk t_ns directly (transport/file._load_canlog) — NOT the
          replay re-stamp — so header_stamp_ns is the real capture cadence
          fields_from_frame -> JointPodState
          drop corrupt/non-finite frames (shared frame_reject_reason)
        export_lerobot([episode], out)            export/lerobot.py
          per-episode time-quality gate on the captured cadence:
          REFUSE non-monotonic/dropout, FLAG over-budget (quality_failed)
        load_lerobot(out)  -> Episode objects     export/lerobot.py
```

Two output formats, both reproducible:

- **Per-episode parquet** (`logger/parquet_io.py`) — the gated, atomic dataset writer.
  One file per episode, jitter stats + budget + contact-detector version stamped into
  the parquet footer. This is the format the recorder produces.
- **lerobot v2 dataset layout** (`export/lerobot.py`) — `data/*.parquet` + `meta/*.json`
  for direct ingestion by the training stack. fps and measured jitter are DERIVED from
  the sample timestamps, never hard-coded.

> **NOTE on replay timing — two different stamps, by branch.**
> `FileReplayTransport.recv()` re-stamps each frame with `time.monotonic_ns()` at recv
> time (`transport/file.py:159`); via that transport the on-disk `t_ns` is provenance
> only, so jitter measured on a *replay* reflects the replay loop speed, not the original
> bench cadence.
> - **Branch A (recorder)** consumes `FileReplayTransport.recv()`, so for trustworthy
>   timing gating you must feed it the real bridge RX stamps (or, as the smoke test does,
>   an injected uniform clock) — NOT the bare replay re-stamp. See the per-pod note in
>   section 4.
> - **Branch B (CLI canlog -> lerobot)** does NOT go through the re-stamping transport:
>   `_load_canlog_episode` reads the on-disk `t_ns` directly (`transport/file._load_canlog`)
>   and uses it as `header_stamp_ns`. So the `export_lerobot` time-quality gate reflects
>   the REAL captured cadence — a non-monotonic or hole-ridden capture is refused, an
>   over-budget one is flagged — rather than the replay loop speed.
>
> **Cross-modal synchronization.** All PVT streams (CAN joint telemetry, future video,
> future tactile) are aligned to ONE host monotonic clock (`time.monotonic_ns`). The
> authoritative timestamp is `PVTSample.timestamp_ns`, set from
> `JointPodState.header_stamp_ns` via `sample_from_pod_state` (`pvt.py:112-118`). The
> bridge node stamps this at RX time; `FileReplayTransport` re-stamps at `recv()` time.
> Measured alignment jitter (max deviation from median inter-sample gap) is recorded per
> episode in the parquet footer (`inhabit.jitter_stats`, written by `recorder.py:172`) and
> per lerobot dataset in `meta/info.json` (`time_base.measured_jitter_ns`, written by
> `export/lerobot.py:196`). Downstream consumers use `time_base.time_sync_method`
> (`single_monotonic_host_clock`) to know the alignment guarantee.

---

## 2. Exact commands (verified against `host/tests/fixtures/sample.canlog`)

**All commands in this doc run from the repo root** (the directory that contains both
`host/` and `tools/`) — the same cwd the existing P3/P4 commands and `pytest` use. Every
path below is repo-root-relative; copy-paste them as-is. These are the existing P3/P4
commands. The committed fixture is a synthetic stand-in for a real bench capture
(3 pods x 8 ticks = 24 frames).

### 2a. canlog -> lerobot, with round-trip verification (CLI)

The CLI module lives at the repo root (`tools/dataset`) and imports `export.lerobot`
from `host/`, so BOTH the repo root and `host/` must be importable. From the repo root:

```bash
# POSIX (Linux/macOS). On Windows use ';' instead of ':' as the separator.
PYTHONPATH="host:." python -m tools.dataset export \
    -i host/tests/fixtures/sample.canlog \
    -o ./lerobot_ds \
    --task insert_connector \
    --verify
```

Verified output:

```text
Exported 1 episode(s), 24 sample(s) -> .../lerobot_ds
OK: round-trip verified - 1 episode(s), 24 sample(s)
```

The CLI's canlog branch (`tools/dataset/__main__.py:20` `_load_canlog_episode`) decodes
EVERY pod into ONE episode (24 samples = 3 chain_index x 8 ticks), using the real on-disk
RX timestamp per frame. It does NOT split per pod, and it drops corrupt-checksum /
non-finite frames (shared `frame_reject_reason` policy). `export_lerobot` then applies the
per-episode time-quality gate — a non-monotonic or hole-ridden episode is REFUSED, an
over-budget-but-monotonic one is FLAGGED `quality_failed` — but it does not quarantine
per-episode atomically or write provenance footers. For a fully gated, per-pod, atomic
dataset write use branch A (section 4).

### 2b. canlog -> per-episode parquet (gated recorder)

The recorder is exercised by the committed smoke test, which is the canonical example of
the gated path (`host/tests/test_postgreen_smoke.py:104`). From the repo root:

```bash
python -m pytest host/tests/test_postgreen_smoke.py -q
```

It replays the SAME fixture -> bridge -> `EpisodeRecorder` -> parquet -> `read_episode`
-> `export_lerobot`/`load_lerobot`, asserting exact round-trip on every persisted field.

### 2c. per-episode parquet -> lerobot (CLI)

```bash
PYTHONPATH="host:." python -m tools.dataset export \
    -i ./demo_000421.parquet \
    -o ./lerobot_ds \
    --verify
```

### 2d. synthetic sanity episode (no input file)

```bash
PYTHONPATH="host;." python -m tools.dataset export --sim -o ./lerobot_ds --verify
```

---

## 3. Validation / quarantine rules ENFORCED BY CODE

Every rule below is enforced today. Each cites the function that enforces it so this doc
stays honest. An episode is **quarantined** (NOT exported; a sidecar JSON records why)
only when a `JitterBudget` gate fails. Schema and checksum rules are enforced at
different points (ingest / read), as noted.

### Gates that QUARANTINE the episode

These four are checked in `JitterBudget.check` (`logger/jitter.py:76`) and applied in
`EpisodeRecorder.finalize` (`logger/recorder.py:142-169`). On any failure: nothing is
written to the dataset dir; a `quarantine/<episode_id>.quarantine.json` sidecar is
written atomically (`logger/recorder.py:191`) and `RecorderResult.exported` is `False`.
`finalize(strict=True)` raises `QuarantineError` instead (`logger/recorder.py:161`).

| Rule | What it catches | Code |
|------|-----------------|------|
| **Monotonic timestamp (no backwards)** | any inter-sample interval `<= 0`; the one clock must never go backwards | `jitter.py:83-86` (`backwards > 0`); counted at `jitter.py:144` |
| **Jitter budget (p99)** | 99th-percentile deviation of inter-sample intervals from the median period exceeds `max_jitter_p99_ns` (default 2 ms) | `jitter.py:91-94`; p99 computed at `jitter.py:149-150` |
| **Dropout** | any interval `> max_gap_factor x period` (default 2.5x) = a missed frame / hole in the window | `jitter.py:87-90`; counted at `jitter.py:153-154` |
| **Too few samples** | `n_samples < min_samples` (default 2) = no timing signal | `jitter.py:79-82` |

The budget defaults target a ~100 Hz (10 ms) stream and are documented inline at
`jitter.py:56-70`. The active budget is stamped into every exported file's footer
(`recorder.py:172-177`) so the dataset is reproducible.

Jitter is ALWAYS measured and logged via `logging` regardless of pass/fail
(`recorder.py:145-157`), so timing quality is observable even for accepted episodes.

### chain_index identity

`chain_index` is the physical joint identifier. It is **preserved end-to-end, not gated**:

- Carried on every `PVTSample` (`pvt.py:54`) and `JointPodState` (`pvt.py:90`), mapped
  1:1 in `sample_from_pod_state` (`pvt.py:115`).
- Persisted as a typed `int32` column in per-episode parquet (`parquet_io.py:51`) and as
  the real per-frame `observation.chain_index` list in lerobot v2 (`export/lerobot.py:127`,
  `:168`) — so sparse / non-zero-based joints round-trip as themselves rather than being
  reconstructed from row position (the v1 corruption fixed in lerobot v2; see
  `tests/test_dataset_roundtrip.py:89` `test_sparse_chain_index_roundtrip`).

The recorder does NOT enforce one-chain-index-per-episode. It is a per-joint episode
writer by convention: callers select a single pod's frames before `ingest` (the smoke
test filters to `LOGGED_NODE_ID` at `test_postgreen_smoke.py:133`). If you ingest mixed
pods, jitter is measured over the interleaved multi-pod timeline, which is not what the
budget is calibrated for. Feed one pod per episode (section 4).

### schema_version

Versioned, with migrations — enforced at READ time, not as a quarantine gate:

- `PVT_SCHEMA_VERSION` (`pvt.py:27`) is the current on-disk schema; written to the
  parquet footer (`parquet_io.py:97`) and carried per-row (`pvt.py:62`).
- `read_episode` runs every row through `PVTSample.from_row` -> `migrate_row`
  (`parquet_io.py:139`, `pvt.py:129`). `migrate_row` walks `MIGRATIONS` from the row's
  version up to current; it **raises** `ValueError` if a needed migration is missing
  (`pvt.py:134`) or if the file is NEWER than the reader (`pvt.py:137-140`). So an
  out-of-range schema fails loud on load rather than silently mis-parsing.
- The CAN-side `schema_version` equals the frozen codec `PROTO_VERSION`
  (`conversion.py:51`); a frame whose version disagrees would be a codec-level concern,
  upstream of the logger.

### task_label

- Set once at recorder construction (`recorder.py:108`) and stamped onto every sample
  (`sample_from_pod_state`, `pvt.py:117`) and into the parquet footer
  (`parquet_io.py:98`), so each episode's label travels WITH the data.
- It is preserved and round-tripped (footer + per-row + lerobot `meta/tasks.jsonl`) but
  not *gated* — an unlabeled episode (`task_label=None`) still exports. Label discipline
  is an operator responsibility: always pass `--task` / `task_label=` for bench captures.

### checksum (frame-level, dropped not quarantined)

Frames with `checksum_valid=False` are counted and SKIPPED during ingest, not added to
the timeline (`recorder.py:119-121`), so a corrupt frame cannot poison time alignment.
The count is recorded in the footer (`dropped_checksum`, `recorder.py:179`) and in the
quarantine sidecar (`recorder.py:200`). Dropped frames create gaps, which can then trip
the dropout gate above — that is intentional.

### Atomicity (every write)

- Ingest only appends in memory; nothing hits disk until `finalize` (recorder docstring,
  `recorder.py:11-20`).
- PASS -> atomic parquet write: `.part` temp, fsync, `os.replace`
  (`parquet_io.py:107-118`). A crash mid-write leaves at most a `.parquet.part`, never a
  readable partial episode.
- FAIL -> quarantine sidecar written `.json.part` then `os.replace`
  (`recorder.py:205-207`).

---

## 4. Per-pod gated write (the recommended dataset path)

For a real bench capture you want one jitter-gated episode per physical joint. Pattern,
mirroring `test_postgreen_smoke.py` (run with `host/` importable, e.g.
`PYTHONPATH=host python your_recorder.py` from the repo root):

```python
from logger.recorder import EpisodeRecorder
from inhabit_bridge.conversion import fields_from_frame
from transport.file import FileReplayTransport
from inhabit_can.pvt import JointPodState

rec = EpisodeRecorder("demo_000421", out_dir="./dataset",
                      task_label="insert_connector")
with FileReplayTransport("bench.canlog") as tx:
    while (frame := tx.recv()) is not None:
        f = fields_from_frame(frame.data)
        if f.node_id != TARGET_NODE_ID:        # one pod per episode
            continue
        rec.ingest(JointPodState(
            node_id=f.node_id, chain_index=f.chain_index,
            angle_raw_adc=f.angle_raw_adc, angle_millideg=f.angle_millideg,
            angle_rad=f.angle_rad, status_flags=f.status_flags,
            checksum_valid=f.checksum_valid, schema_version=f.schema_version,
            header_stamp_ns=frame.rx_monotonic_ns,   # ONE monotonic clock
        ))
result = rec.finalize()        # EXPORT or QUARANTINE
```

`result.exported` tells you whether it passed; `result.reasons` lists every failed gate;
`result.path` is the parquet on PASS or the quarantine sidecar on FAIL.

---

## 5. Replacing the fixture with a REAL bench capture (no path changes)

The pipeline reads the capture at a fixed, convention-bound location. A real capture
flows through every command and test above UNCHANGED when it keeps the same
filename/location:

```text
host/tests/fixtures/sample.canlog      <- replace this file in place
```

Rules so bench data flows through with zero code/command changes:

1. **Same path, same name.** Drop the real capture at
   `host/tests/fixtures/sample.canlog`. Every command in section 2 and the smoke test
   (`FIXTURE = .../fixtures/sample.canlog`, `test_postgreen_smoke.py:53`) point here.
2. **Same on-disk format.** It must be valid `.canlog` JSONL (`v`/`t_ns`/`id`/`data`),
   8-byte v1 payloads. Record it with the real `FileRecorder` (`transport/file.py:40`),
   which rejects non-8-byte frames at write time, or via the live bridge recorder.
3. **LF line endings.** `.canlog` is pinned to `eol=lf` (`make_sample_canlog.py:91-94`);
   keep the real file LF so the byte-exact tests stay platform-stable.
4. **The two generator-coupled tests must be updated or removed when the fixture stops
   being the synthetic one:**
   - `test_postgreen_smoke.py:74` `test_fixture_round_trips_from_generator` asserts the
     committed bytes equal `write_fixture(...)` output. A REAL capture will not match the
     synthetic generator — this assertion is the one thing that must change (delete it or
     repoint it) when swapping in real data. It is intentionally there to stop the
     synthetic fixture drifting from its generator while it is still synthetic.
   - `test_postgreen_smoke.py:209` `test_postgreen_viz_renders_full_chain_from_fixture`
     and the `PODS` / `N_TICKS` / `angle_millideg_for` expectations
     (`test_postgreen_smoke.py:67`) assume the synthetic chain. Update these expectations
     to the real capture's pod set, or scope them to the synthetic generator.

   Everything else — the recorder gates, parquet round-trip, lerobot round-trip — is
   content-agnostic and needs no change. That is the seam closed by
   `test_arbitrary_canlog_round_trips` (section 6): an arbitrary-but-valid canlog flows
   the whole path without touching any synthetic-specific expectation.

5. **Quality gate is automatic.** A real capture that exceeds the jitter budget, has a
   dropout, or goes backwards will QUARANTINE on the recorder path (branch A) rather than
   landing a bad episode in the dataset — which is the entire point.

---

## 6. Tests

The existing suite already covers the gates and round-trips:

- `tests/test_logger.py` — over-budget jitter, dropout, backwards-clock, too-few-samples
  each quarantine; round-trip; `.part`/crash atomicity.
- `tests/test_dataset_roundtrip.py` — lerobot export/load round-trip incl. sparse
  `chain_index`; derived fps; CLI `--sim` and `.parquet` paths.
- `tests/test_postgreen_smoke.py` — the committed-fixture canlog->parquet->lerobot path.

`tests/test_dataset_readiness.py` (added with this doc) closes two seams not previously
covered:

- **`test_arbitrary_canlog_round_trips`** — an ARBITRARY (non-synthetic, different pod
  set / angles) valid canlog flows canlog -> recorder -> parquet -> lerobot and
  round-trips, proving a real bench file works WITHOUT touching the synthetic generator's
  expectations. This is the guarantee behind section 5.
- **`test_cli_canlog_export_round_trips`** — the CLI `.canlog` input branch
  (`_load_canlog_episode`), previously untested end-to-end (only `--sim` / `.parquet`
  were), exports and verifies a round-trip.

Run from the repo root:

```bash
python -m pytest host -q
```
