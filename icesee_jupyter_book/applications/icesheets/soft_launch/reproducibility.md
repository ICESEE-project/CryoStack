# Reproducibility evidence for each run

A recorded workflow needs a reproducible run record as well as a successful
video. Capture the **actual submitted source and input data** from the run's
frozen staging/S3 snapshot, together with its executed container and outputs.
Do not reconstruct a past run from today's mutable workspace, current dataset
alias, latest image tag or a different successful job.

The [18 November Basic ISSM execution reference](basic_issm_reference.md)
provides an actual checked run, byte-matched scientific source and criteria
declared before its actual AWS retake. The retake passed with exact mesh and
four-field equality; its remaining evidence gaps are explicit.

## Freeze the run evidence

Before submission, preserve the staged input manifest and its content hashes
when the route provides them. After the run, retrieve the run-scoped input
snapshot and compare every source/data file against that manifest. Preserve
S3 object version IDs when available, or the object modification times and
retrieved byte hashes relative to the actual submission time. If evidence
cannot establish which bytes were submitted, mark input binding incomplete;
do not label a later workspace copy the original input.

Keep a content-addressed input archive and a separate results archive. Record
the SHA-256 of each archive and of every source, helper, parameter and data
file inside it. A file hash identifies bytes; it does not establish scientific
correctness. Changing a file after a run creates a new input version.

## Required manifest for each science clip

| Evidence | What to retain |
| --- | --- |
| Clip and actual run | Workflow/model/example/target, the real job and run record, submission/start/stop times, terminal outcome and its evidence. A privacy-safe public identifier can refer to the private job record. |
| Submitted source and data | Relative paths, sizes and SHA-256 values from the run snapshot, including imported helpers, parameter files and each referenced dataset. Retain the frozen manifest/object-version or timing evidence. |
| Executed software | Actual container image digest, model version and relevant MATLAB/Firedrake/MPI/PETSc/Python versions where used. A mutable image tag or an unverified build recipe is insufficient. Record unknown versions as missing. |
| Scientific configuration | Mesh/geometry, boundary and initial conditions, units, solver/tolerance settings, time step/count/final time, assimilation options where applicable, and every applied override. Cite the submitted file that defines each value. |
| Randomness | Every seed and RNG/library where randomness is used; otherwise record why no RNG applies. A fixed seed alone does not guarantee identical floating-point results across software or hardware. |
| Resources | Region, CPU/memory, process/thread counts, architecture and reviewed model/task time limits. Preserve actual execution facts separately from requested ceilings. |
| Outputs | The saved/opened archive and its SHA-256, member hashes/sizes, native completion log, expected native fields/units/mesh, readable figures and the checks actually performed. A download link or PNG alone is insufficient. |
| Comparison | The exact two run manifests, matching input hashes, compared arrays/metrics, units, alignment and declared tolerances, plus the computed differences and pass/fail result. |

The public manifest must omit license values/endpoints, AWS account/role/secret
identifiers, tokens, pairing codes, personal details and private paths. Keep
raw provenance privately. Sanitizing a manifest must not change the scientific
input/output bytes or their hashes. If a raw source/data artifact cannot be
published, state its access limitation instead of claiming that an unrelated
public example is the exact original.

## Check actual artifacts

Save and open the results archive, verify archive integrity and inventory its
members. Confirm expected fields are present and finite, units/mesh are correct,
solver completion is supported by the actual log, and generated figures can be
read. Compare manifest hashes to the saved files after download. Missing files,
nonfinite fields, failed convergence or a hash mismatch keep that clip's
reproducibility acceptance incomplete even when the browser says Completed.

A setup clip records configuration/readiness evidence and its limits. It does
not fabricate a scientific output manifest or call a Connector status check a
MATLAB checkout. The subsequent native ISSM run supplies runtime evidence.

## Byte identity and numerical agreement

Use exact hashes for byte identity of submitted source/data and retained
artifacts. Numerical outputs may differ with MPI reduction order, compilers,
solver/library versions or mesh ordering. State whether a check requires exact
bytes, exact arrays or numerical agreement. Declare absolute/relative tolerances
and any coordinate alignment before evaluating differences; do not widen them
merely to turn a failure into a pass.

The [PC/AWS comparison](comparison.md) preserves the particular historical
JSON/shelf checks already measured. It does not qualify the new HDF5/MAT cases,
a changed scientific configuration or a new PC installation. Claim a new PC/AWS
match only after both runs actually use matching submitted input hashes and
the declared checker passes. Native scientific interpretation and accuracy
remain separate from implementation reproducibility.

[Recording matrix](recording_matrix.md) · [All pilot tutorials](../soft_launch.md)
