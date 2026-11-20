# Compare PC and AWS results

## Prepare comparable runs

Use the same model, source files, input bytes, mesh, step count, solver settings, CPU count, and software/container versions. First run the one-step case. Follow the [run reproducibility procedure](reproducibility.md): compare hashes from each actual submitted/run-scoped input snapshot, retain the executed image digest and measured software versions, and hash the saved output archives. A current workspace copy or matching image tag does not establish matched inputs.

The Icepack case performs a diagnostic flow solve followed by bounded prognostic steps on a triangular rectangle. The ISSM case performs repeated SSA Stressbalance solves; its repetitions do not advance physical time. Six steps are not a promise of six minutes.

## Local commands

Extract the [JSON launch packet](../soft_launch.md), not the newer HDF5/MAT initial-condition packet. Copy the matching JSON into `icepack/data/` or `issm/data/`. Activate the model's existing environment before executing:

```bash
# Icepack: inside an environment containing Firedrake and Icepack
cd icepack
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python run.py
```

For ISSM, start MATLAB with ISSM correctly installed and both its `bin` and `lib` directories on the MATLAB path, change into `issm`, and run `runme`. The example creates writable `execution/` and `outputs/` directories beside the script, so an installed container image can remain read-only. Use your institution's authorized license configuration. CryoLauncher's browser runs on its server; a browser's “local” filesystem is not your PC. Native PC execution requires installing the scientific environment separately.

## Historical reference outcomes

These one-step values were measured in the tested container on the gateway, not inferred from the scripts. They provide a scale check; compare the same inputs/environment before applying the provisional tolerance.

| Model | Thickness min/max (m) | Mean thickness (m) | Velocity RMS (m/year) |
|---|---|---|---|
| ISSM | 300 / 500 | 400 | about 6.23869837 |
| Icepack | about 300.02342485 / 499.98146762 | about 400.00692324 | about 130.14195129 |

The packet's `references/` folder includes measured metrics and provenance. Local PC containers reproduced both models’ four metrics within the stated tolerance. These checks used a local Docker Icepack image and an existing Apptainer ISSM 4.24 image; the tested gateway ISSM is 2026.1. Agreement for this small case does not establish general equivalence between versions. The one-step Icepack AWS check also reproduced all four PC Docker metrics on
23 October 2026, with a largest absolute difference of about 5.71e-8. Its
native script took about 15 seconds inside a roughly 44-second container run.
ISSM PC-vs-AWS remains pending. Bare native PC Icepack encountered an MPI/compiler
version mismatch, so the passing PC comparison uses a compatible container.

## Historical full-field shelf comparison

The packet now includes `icepack_builtin_shelf/`: the exact generated script and
export helpers used for the larger **Basic / 02 Synthetic Ice Shelf** check,
alongside a measured synthetic mesh/field reference. It also includes upstream
source attribution and licensing. Use the small one-step case first; the larger
case takes several minutes and does not replace an ISSM comparison.

Activate the matching compatible Icepack/Firedrake environment. From the packet's
`icepack_builtin_shelf/` directory, run:

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MPLBACKEND=Agg \
  python cryostack_icepack_runner.py run.py .
```

Then, from the packet root:

```bash
python tools/compare_builtin_shelf_fields.py icepack_builtin_shelf/outputs \
  references/icepack-builtin-shelf-02 --script icepack_builtin_shelf/run.py
```

The checker requires the exact source script, matching units, finite arrays and
matching mesh coordinates/connectivity. It refuses mismatched meshes rather
than comparing unrelated node orders. Coordinates use an absolute tolerance of
`1e-8` and triangles must match exactly. Fields use
`abs(PC - reference) <= 1e-6 + 1e-5*abs(reference)`.

The recorded PC-container/AWS comparison passed for all six exported component
arrays. Largest differences were about `1.33e-5` for thickness, `1.53e-6` for
velocity magnitude and `4.43e-8` for damage. Both meshes had 3,371 nodes and 6,533
triangles. These are engineering checks for this case, not a scientific accuracy
standard or a guarantee for a different installation.

Compare exported arrays on both sides: thickness and velocity are interpolated
from CG2 to CG1. Native higher-order extrema are not directly equivalent to the
portable export. The damage undershoot (about -0.003602) is preserved, not clipped.
The reference subset includes mesh and fields; it omits the original figures and
mesh-generator file. Its provenance records file hashes and the tested image.

## Compare

Both runs write `outputs/reference-metrics.json`. Make two folders, `pc/` and `aws/`, next to `tools/` in the extracted packet. Copy the file from your local run into `pc/`. After the matching AWS run, extract `reference-metrics.json` from the downloaded results archive into `aws/`, then run:

```bash
python tools/compare_results.py pc/reference-metrics.json aws/reference-metrics.json
```

The provisional acceptance criterion for each metric is `abs(A-B) <= 1e-6 + 1e-5*abs(A)`. This is a proposed engineering tolerance, not a scientific validation standard. Model, case, and step count must match; missing/nonfinite metrics fail. Runtime is recorded but not compared. This numerical tolerance is distinct from
exact source/data or archive-byte identity. The new HDF5/MAT initial-condition
cases have no PC/AWS comparison pass recorded on this page.

Compare thickness minimum, maximum, mean and velocity RMS (`speed_l2`). These scalar checks are a smoke test, not complete field equivalence. Compare full exported fields and convergence if your scientific use requires stronger validation. Mesh order can vary between installations; nodal array equality is unsuitable without aligning coordinates.

If comparison fails, inspect versions, MPI/compiler environment, input hashes, boundary conditions, mesh, and solver convergence before widening tolerances. A successful import does not prove the native compiler/MPI toolchain works.

## Expected outcome and evidence

A successful submission has a job ID. A successful model run finishes without a solver error. A complete tutorial also has retrievable logs, nonempty results, a readable figure, and a downloaded archive. Record all of these; a green job status alone is insufficient.

**Screenshot slot:** capture the selected model/example, completed run, and results panel using a participant test account. Exclude license fields, account identifiers, tokens, and private paths.

**Recording:** see the [recording matrix](recording_matrix.md) for the reviewed video and the evidence required for this workflow.

[All soft-launch tutorials](../soft_launch.md) · [Troubleshooting](troubleshooting.md)

## Separate 18 November AWS repeat

The [canonical Basic ISSM reference](basic_issm_reference.md) now has a second
actual AWS run under criteria sealed before submission. Mesh and all four
compared physical fields are exactly equal. This is an AWS-to-AWS result; it
does not replace or expand the historical PC/AWS checks above.
