# F14 experimental qualification results

F14 is closed under the alternative experimental criterion accepted by the user
on 2026-10-16. All six hosted samples, four scenarios and unchanged coverage
floors passed. This disposition replaces the original requirement to measure a
real release sequence; it does not establish production release savings.

The [canonical protocol](../../release-package.md#accepted-f14-experiment)
defines the experiment. The [machine-readable receipts](2026-10-16-f14-experiment.json)
retain exact observations, environments, hashes, sample timings and job times.
The [earlier audit evidence](2026-10-16-audit-remediation-evidence.md) remains a
historical record of local qualification before publication.

## Source and hosted execution

- Measured harness commit H: `b827c308cfc09a99086b9a089c7b28b7f4ddc44d`.
- Branch: `codex/audit-remediation-2026-10-16`, [draft PR 90](https://github.com/asphyx0r/git-starter-kit/pull/90).
- Actual event: `workflow_dispatch`, input `qualification_experiment=true`.
- [Experimental run 38965445362](https://github.com/asphyx0r/git-starter-kit/actions/runs/38965445362),
  attempt 1, created `2026-10-16T20:53:06Z`: completed successfully, 14/14 jobs.
- Its seven ordinary qualification jobs passed first, supplying the original
  Linux/Windows measurements. Six experimental jobs and their aggregate then
  passed. No failed attempt is substituted or relabeled.
- Ordinary H [push CI](https://github.com/asphyx0r/git-starter-kit/actions/runs/38965371460)
  and [PR CI](https://github.com/asphyx0r/git-starter-kit/actions/runs/38965378360)
  also passed independently: seven normal jobs each, experimental jobs skipped.

This report is committed after H. That documentation commit is not the measured
source. Its ordinary push/PR CI results belong to the current PR verification,
not to the frozen experimental series. No merge, tag, release or protection
change was performed for this experiment.

## Method and observed behavior

Each OS has three isolated hosted runners. Sample orders rotate through
`full/reuse/fallback`, `reuse/fallback/full` and `fallback/full/reuse`.
The ordinary suites supplying the original pair ran on separate VMs; each
sample performs one unmeasured helper round trip locally. This is not physical
CPU or disk cache warming by the original suites on the sample VM.

Both setup caches, Python and npm, reported hits for all six samples. The
locked installation and fresh `node_modules` per runner remain in place.
No suite cache was cleared. Before/after environment records match each other
and the corresponding original/fresh environment on each OS.

| Case | Observation in every sample |
| --- | --- |
| No proof | Common `full` decision; actual complete native Python and shell suites run |
| Valid original pair | `reuse` for both tag and `release.published` contexts; no heavy suite runs |
| Invalid proof before decision | Simulated Windows image drift selects common `full`; complete native suites run |
| Loss after reuse decision | Removing Linux raw coverage from a copied packet is refused by the aggregate guard |

Eligibility is supplied by a closed injected API fixture, with no forwarding of
unknown routes. It simulates a successful default-branch push, completed
producer state, trusted `main` tip H, tag/release consumers and an unpublished
artifact envelope. The real manual event and its then-running state remain
separately recorded. The original commit, run, attempt, creation date and all
16 measurement-file bytes remain unchanged through tag and release reuse.
This does not attest H as a trusted real `main` commit or create an eligible
production packet.

## Environments and complete suites

| Observed fact | Linux | Windows |
| --- | --- | --- |
| Image OS | `ubuntu24` | `win25-vs2026` |
| Image version | `20261012.334.1` | `20261007.264.1` |
| Python | 3.11.17 | 3.14.8 |
| Node / npm | 24.20.0 / 11.19.0 | 24.20.0 / 11.19.0 |
| Coverage / PowerShell | 7.16.2 / 7.6.6 | 7.16.2 / 7.6.6 |
| Python discovered per full/fallback execution | 718 | 718 |
| Skipped per execution | 11 | 14 |
| Failures / errors / unexpected successes | 0 / 0 / 0 | 0 / 0 / 0 |
| Shell suites per execution | 6, all successful | 2, all successful |

The original warm-up has the same discovery/skip counts. All twelve measured
full/fallback executions match it. The Windows focused shell profile is the
existing two-suite profile, not a reduced experimental selection. Exact tools,
per-suite durations and counts are retained in the JSON receipts.

## Recomputed coverage

After downloading all eleven artifacts, each ZIP was checked against its
GitHub API SHA-256. All file manifests were verified. The six sample packets
were compared with the original ordinary coverage artifacts. An independent
local invocation of the unchanged production validator then rechecked retained
tag/release packets and recombined all six full/fallback raw coverage pairs.
Its floors, source packet, scenario distributions and assembled costs match the
hosted aggregate exactly.

All six recombined pairs produce these scores; all four required scores exceed
the unchanged 85% floors:

| Dataset | Global | Statements | Branches |
| --- | --- | --- | --- |
| Linux | 90.28% (7,522/8,332) | 91.76% (5,482/5,974) | 86.51% (2,040/2,358) |
| Linux + Windows | 91.49% (7,623/8,332) | 92.80% (5,544/5,974) | 88.17% (2,079/2,358) |

Global is Coverage's combined statement-and-branch score, not line coverage
alone. The measured list remains 25 Python sources, unchanged from H's parent;
H changes the workflow-contract implementation, so its content hashes are not
claimed equal to that parent. The earlier published base had 24 sources before
the remediation introduced `qualification.py`. No omission, skip rule, timeout,
assertion or threshold was relaxed for this experiment.

## Component timing results

Seconds below are medians of three samples with minimum-maximum ranges.
Pair maximum and sum are computed within each matched sample before taking
their medians. Reuse in this table is the arithmetic mean of that sample's
separately measured tag and release consumer times.

| Path | Linux median (range) | Windows median (range) | Pair maximum median | Pair sum median |
| --- | --- | --- | --- | --- |
| Full | 373.979 (371.615-386.144) | 543.044 (539.740-562.431) | 543.044 | 925.884 |
| Reuse | 3.020 (2.987-3.049) | 2.834 (2.800-3.170) | 3.049 | 5.849 |
| Fallback | 375.846 (375.449-378.761) | 553.061 (515.723-553.346) | 553.061 | 929.192 |

Producer component P counts the ordinary Python and shell duration once:
372.971 seconds Linux and 356.427 seconds Windows. For each paired metric,
the assembled full comparison is `P + 2 * median(full)`; reuse is
`P + median(tag reuse) + median(release reuse)`. These are sums of component
medians, not medians of complete observed sequences.

| Assembled producer plus two consumers | Pair maximum, seconds | Pair sum, seconds |
| --- | --- | --- |
| Both consumers full | 1,459.060 | 2,581.165 |
| Tag and release reuse | 379.068 | 741.095 |
| Both consumers fallback | 1,479.093 | 2,587.782 |

The native two-OS helper model is not the production job placement: production
resolution, common verification and final aggregation run in separate Linux
jobs. P excludes its environment/export/sealing overhead, while full/fallback
include their decision, probes, real suites and exports. All comparisons omit
queueing, setup, fresh preflights, static/network guards, real API transport and
release orchestration. These values demonstrate measured component reduction,
not actual end-to-end release duration or billed runner savings.

Paired fallback-minus-full deltas are Linux median +4.231 seconds
(-10.695 to +4.782), Windows median -9.370 seconds (-24.017 to +10.302).
The corresponding differences between path medians are +1.867 and +10.017
seconds. These are different statistics. Three samples and ordinary runner
variance do not isolate a positive Windows fallback overhead or establish
confidence intervals.

Separately, the actual 14-job experiment took 1,845 seconds from run creation
to the last job completion (30 minutes 45 seconds), with 7,067 seconds summed
across job start/completion intervals (117 minutes 47 seconds). These include
the observed job preparation/execution intervals; the wall value also includes
scheduling. Neither value is GitHub's billed, OS-weighted usage.

## Durable evidence and preservation

The companion JSON retains the eleven artifact IDs, names, archive SHA-256
digests and expiry times, six sample-manifest digests, original input/file
hashes, six recombined score records, actual environments and exact timings.
The hosted aggregate `result.json` SHA-256 is:

```text
1ed749efa9eac4ee9cc34feab81aad4d6224498078e99d1e44e2700fae888d5e
```

Artifacts have seven-day retention, with recorded expiries on 2026-10-23.
Their eventual expiration does not erase these receipts, but hashes and compact
results cannot reconstruct the omitted raw coverage databases or logs. The
raw ZIPs, logs, collection copies and validation outputs are task-owned
temporary artifacts; they are not committed. Future raw replay requires
retaining an authorized copy before expiry or executing a new dated series.

The production qualification helper, Python/npm locks, version registry,
coverage policy and four floors are unchanged by H. The original seven job
objects are identical to H's parent. Experimental jobs are manual-only and
read-only; both harness files remain excluded from distributed packages by the
existing `tests/` exclusion. This exclusion was checked through the existing
classifier; no release ZIP was rebuilt to make this claim.

The five published metadata files remain identical to the published base:
`VERSION`, `SHA256SUMS`, `manifest.json`, `starter-kit-manifest.json` and
`CHANGELOG.md`. The subsequent result commit changes documentation only.
The final exact-head CI proof is recorded in PR 90 after that commit, avoiding
a self-referential report-commit cycle.

No authentic producer-to-tag-to-release sequence or real default-branch trust
relationship was exercised. Those are limits of the accepted experiment,
not unresolved gates for its F14 closure.
