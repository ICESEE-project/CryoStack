# Basic ISSM execution reference — 18 November 2026

One native **SquareIceShelf / SSA Stressbalance** execution completed on AWS
on 18 November 2026. Its submitted scientific files, immutable image and
native outputs were checked. **The 160-second walkthrough is now reviewed and published, and the
separately submitted AWS retake passed the predeclared comparison.** This record is separate from the
historical [PC/AWS comparison](comparison.md).

## What actually ran

| Item | Actual evidence |
| --- | --- |
| Submission / execution | Submitted 18:39:45 UTC; started 18:43:37 UTC; stopped 18:44:19 UTC on 18 November 2026. AWS job status was `SUCCEEDED`. |
| Scientific source | Four scientific files byte-match the run-scoped S3 input snapshot: `runme.m`, `Square.par`, `DomainOutline.exp` and `Front.exp`. All 37 retrieved input objects were last modified before submission. The job's own run-root setting points to that snapshot. |
| Domain / mesh | Synthetic 1,000 × 1,000 km square; nominal Triangle size 100 km. Actual exported mesh: 91 vertices and 148 triangles. |
| Geometry / initialization | Thickness decreases from 1,000 to 300 m along y. Base and surface satisfy hydrostatic flotation using the model's density defaults. Initial velocity is zero. Rheology temperature is 253 K (`273-20`). |
| Solve | One SSA `Stressbalance` solve; no physical time advancement. Source requests 2 MPI processes; the task requests 2 vCPU and 8 GiB. Requested counts are distinct from an observed MPI-rank measurement. |
| Software | Actual job log identifies ISSM 2026.1. The exact Batch job-definition revision pins container digest `sha256:d68d88dcb7047f29d6e277a45710f50f1bf3023566e0472f07a7dd75ffbcd170`. |

The complete 37-file input snapshot is retained privately under content hash
`09166ed71a3b4ce264317f0bf9b0f2565ff8528836db580a0f885d8d57f002e8`.
The public [scientific-source packet](basic-issm-matched-source.zip) contains
only the four already-public files independently matched to the submitted
bytes, plus their explanation. It does not contain MATLAB/ISSM binaries,
private runtime wrappers or license/account configuration. A compatible native
installation and an authorized MATLAB license remain necessary for a rerun.

## What was checked in the actual outputs

The saved results ZIP contains nine members and has SHA-256
`c2b0979288f1f51cc8339e68ea4a08efa6effa7ca79e84a3e28410e4a2251fdd`.
Its archive CRC passed. The native metadata reports `StressbalanceSolution`
with status `ok`; all HDF5 arrays are finite. `Pressure`, `Vel`, `Vx` and `Vy`
each contain 91 nodal values. Triangle connectivity is an in-range, 1-based
148 × 3 array. The exported `StressbalanceConvergenceNumSteps` value is 23.
The largest difference between `Vel` and
`sqrt(Vx² + Vy²)` is approximately `1.82e-12`, below the declared artifact
consistency bound `1e-10`.

The velocity figure is readable. Its plot does not label units, so tutorial
captions must explicitly identify coordinates in metres and speed in metres
per year. Pressure uses pascals. These units follow the native ISSM field
conventions documented in
[mesh2d](https://raw.githubusercontent.com/ISSMteam/ISSM/main/src/m/classes/mesh2d.m)
and [initialization](https://raw.githubusercontent.com/ISSMteam/ISSM/main/src/m/classes/initialization.m);
those current source definitions are unit references, not a substitute for
the actual image/version evidence above.

The [sanitized run manifest](basic-issm-reference-manifest.json) records
input/output member hashes, settings, checks and evidence gaps. Raw logs,
account identifiers and private run metadata remain access-controlled.
The first run did not capture MATLAB's software version or Triangle's internal
mesh-generator seed. The record keeps both gaps visible and does not claim
complete environment or RNG provenance.

## Criteria declared before the clean retake

At **19:32:26 UTC on 18 November 2026**, before the second job was submitted,
the [AWS repeat criteria](basic-issm-repeat-criteria.json) were sealed as SHA-256
`dcf0a523552ec1d1d39c0c20ff90c5e1d0c916d8b3bda2fea6b1854f07352a32`:

- The four scientific file hashes and image digest must match exactly.
- Mesh connectivity and node ordering must match exactly; coordinates may
  differ by at most `1e-8` m, with no silent remapping.
- For finite, equally located/shaped `Pressure`, `Vel`, `Vx` and `Vy` arrays,
  every value must satisfy `abs(retake-reference) <= 1e-8 + 1e-10*abs(reference)`.
- Report exact array equality, maximum differences and both convergence-step
  counts. Archive byte equality is recorded but is not required because
  timestamps and added provenance can differ.

These are predeclared engineering checks for this one scientific case, not a
scientific-accuracy standard. A provenance-only prelude may capture versions
and initial RNG state without changing the scientific files, image, solver,
mesh, seeds or RNG progression. Thresholds will not be widened after results
are seen. The actual second AWS run passed these unchanged criteria; no new PC/AWS result is claimed.

[Reproducibility requirements](reproducibility.md) ·
[Recording matrix](recording_matrix.md) · [Basic ISSM tutorial](basic_issm.md)

## Actual AWS retake and reviewed video

The retake was submitted at **20:30:09.612 UTC**, started at **20:33:44.021 UTC**
and stopped at **20:34:26.859 UTC** on 18 November 2026, with exit code 0.
The task ran 42.838 seconds after 214.409 seconds from submission to start.
All 38 input objects predate submission; the four scientific files and pinned
image match the reference exactly. No scientific override was applied.

The mesh x/y arrays and connectivity are exactly equal. `Pressure`, `Vel`,
`Vx` and `Vy` are exactly equal, with maximum absolute and relative differences
of zero. Both convergence-step fields are 23. The <a href="videos/issm-aws-repeat-result.json">sealed comparison receipt</a>
reports the declared bounds and archive/member hashes. The new ZIP has 11
members, valid CRC and SHA-256
`be5223513d0b5374baddbe1f9624e18fc6e420cabe5f5c88991fbd897fbd8c52`.
Archive bytes differ because timestamps and added provenance differ; numerical
and archive identity remain separate checks.

The <a href="videos/issm-retake-manifest.json">sanitized retake manifest</a> records actual
MATLAB 24.2.0.3070828 (R2024b) Update 7 and ISSM 2026.1, `glnxa64`, observed
OMP/OpenBLAS thread requests of 1 and MATLAB's max-compute-thread query of 1.
Source requests 2 MPI processes; child ranks are not observed by the MATLAB
parent. The recorded pre-run MATLAB global state is `twister`, seed 0; its MAT
artifact decodes and its SHA-256 matches the recorded value. Raw state remains
private. Triangle internal and script/library-owned RNGs remain unobserved.
The first reference's missing version/RNG observations are not filled in
retroactively.

Watch the [reviewed Basic ISSM video](basic_issm.md).
This result establishes same-case AWS repeatability within the declared
checks; it does not establish a scientific-accuracy benchmark or a new PC run.
