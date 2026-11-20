# CryoLauncher science and setup recordings

This matrix tracks ten science walkthroughs: Basic, Advanced, bring-your-own
script and bring-your-own data for **Icepack** and **ISSM**, plus one
**Auto-config** case and one controlled **own-problem** comparison. Two separate setup clips cover connecting an approved BYO AWS account and
configuring its MATLAB license/ISSM Connector. The existing native model runs remain the execution baseline. A new recording is accepted only after its own run, results and
download have been checked; a previous completed job is not a recording of a
new workflow.

**Bring your own script/data** means editing your model code or referencing
your input files. **BYO AWS** means using a connected AWS billing account.
These are separate choices. The ten science walkthroughs use the reviewed
BYO AWS connection. The first-time setup recording uses a separately authorized
connection. Neither demonstrates the unreleased hosted-funding path.

## Recording matrix

| ID | Model and workflow | What the recording must show | Written procedure | Recording for this session |
| --- | --- | --- | --- | --- |
| IP-BASIC | Icepack · Basic | Select Tutorial / 02 Synthetic Ice Shelf; keep its default 200 steps in each phase; review; launch once; inspect native thickness/velocity figures; download and open the ZIP. | [Basic Icepack](basic_icepack.md) | [Reviewed video, 202 s](basic_icepack.md); native source/fields/archive checked, with CG1/damage qualifications |
| IS-BASIC | ISSM · Basic | Select SquareIceShelf and SSA Stressbalance; reuse the configured MATLAB license/Connector; launch; render `StressbalanceSolution` / `Vel`; download and open the ZIP. | [Basic ISSM](basic_issm.md) | [Reviewed video, 202 s](basic_issm.md); native run and exact AWS repeat passed |
| IP-ADVANCED | Icepack · Advanced | Clone 02 Synthetic Ice Shelf; import the canonical `run.py` with only its temperature constant changed from 255.15 to 254.15 K using **Replace existing script files**; save/reopen and record the submitted hash. Keep mesh and 200 steps per phase, then launch and inspect native results. This is changed physics, separate from Basic. | [Advanced Icepack](advanced_icepack.md) | [Reviewed video, 249 s](advanced_icepack.md); native changed-case inputs, fields and downloaded archive checked |
| IS-ADVANCED | ISSM · Advanced | Clone SquareIceShelf; change `hmax=1000;` to `hmax=1010;` in `Square.par`; save/reopen. Keep `hmin=300`, mesh/front/SSA/MPI settings, choose `runme.m` and launch. The added thickness tapers downstream; it is not uniform +10 m. | [Advanced ISSM](advanced_issm.md) | [Reviewed video, 248 s](advanced_issm.md); source-bound changed-case run, native fields and downloaded archive checked |
| IP-SCRIPT | Icepack · own script | Add `run.py` and its helper to an owned example; save both; select the run target; retain `h` and `u` for export; launch; inspect fields and the downloaded archive. | [Bring your own script](bring_script.md) | [Reviewed video, 266 s](bring_script.md); exact submitted source/data, native fields and downloaded archive checked |
| IS-SCRIPT | ISSM · own script | Create an owned example; import `runme.m`, `Launch.par` and the validator with replacement enabled; upload/reference `issm-shelf-small-v1.json`; confirm all three saved files and explicit target; launch with the existing license; render and download the native result. | [ISSM own script](issm_own_script.md) | [Reviewed beginner interactive wide video, 247 s](issm_own_script.md); exact three scripts/JSON, native fields and archive checked |
| IP-DATA | Icepack · own data | Import `run.py` and `initial_fields.py`; reference `icepack-shelf-initial.h5` in an owned example; show exact staging, full-field geometry/velocity initialization, native solve, thickness/freeboard/speed plots and the opened archive. This HDF5 fixture is not a Firedrake CheckpointFile. | [Upload a dataset](upload_dataset.md) | [Reviewed guided interactive wide video, 251 s](upload_dataset.md); exact uploaded grid, all initialized fields, native output and archive checked |
| IS-DATA | ISSM · own data | Import `runme.m`, `Launch.par`, validator and `load_initial_conditions.m`; reference `issm-shelf-initial.mat`; show exact staging, full-field geometry/velocity initialization, native SSA solve, thickness/freeboard/speed plots and the opened archive. Reuse the existing license. | [ISSM MAT initialization](issm_mat_data.md) | [Reviewed beginner video, 263 s](issm_mat_data.md); native full-field initialization, fields and archive checked |
| AUTO-CONFIG | ISSM · Auto-config | Propose the existing SquareIceShelf case; inspect and apply only the intended settings; confirm no job launches automatically; review the model/resources/license; explicitly launch once, inspect native results and open the downloaded archive. | [Auto-config ISSM](auto_issm.md) | [Reviewed interactive wide video, 194 s](auto_issm.md); applied 120-cap/native fields/archive checked |
| OWN-PROBLEM | Icepack · coupled +15 m case | Use unchanged scripts, upload plus15m HDF5, retain the baseline reference alias, launch once and compare the recorded initial/final fields. Interior and inflow thickness change together. | [Own problem](own_problem_icepack.md) | [Reviewed interactive wide video, 322 s](own_problem_icepack.md); exact inputs, native transfer, comparison fields and archive checked |

The HDF5/MAT inputs are synthetic structured-array initial conditions prepared
for these recordings. Upstream/community-data provenance is not established
for these fixtures. Their 16 offline file/loader checks passed. The Icepack HDF5 native initialization/output and video are now accepted; ISSM MAT initialization/native output and its 263-second beginner video are also accepted. The additional bounded ZIP/NetCDF cases retain their own preparation
checks; they do not replace the requested HDF5/MAT science clips. Basic ISSM has a reviewed video and exact AWS-repeat receipt. Icepack Basic has a reviewed native video with explicit portable-export and
damage-undershoot limits. The Icepack own-script clip also has a reviewed native run, source/data hashes and saved archive. Advanced Icepack also has a reviewed native changed-temperature clip. Advanced ISSM also has a reviewed changed-thickness clip. Auto-config also has a reviewed native video and changed-cap comparison. These inputs are not observational datasets or
scientific-validation benchmarks. The
[PC/AWS comparison](comparison.md) names the versions, metrics and tolerances
used for numerical comparison.

## BYO AWS account setup segment

The <a href="byo_aws_setup.html#first-time-connection">first-time connection recording</a> follows the connection form, the blue **Open AWS Setup** button and the new CloudFormation tab. It records the IAM acknowledgement and **Create stack**, **CREATE_COMPLETE**, the **Outputs** table and its **RoleArn** value, then the actual role ARN inserted into CryoLauncher, verification and **Connected**. The connection form is already open when that segment begins; a preceding **Connect AWS Account** click is not claimed.

The guide explains selecting the full ARN in the **Value** column and copying
with **Ctrl+C** or **Command+C**; the recorded AWS table has no dedicated Copy
icon. Authentication is completed with capture off. Account IDs, ARN values,
connection parameters and session identity are masked in the published edit.

This setup recording stops at **Connected**. It does not prepare compute,
launch a scientific model, test MATLAB or establish an AWS funding transfer.
The connected account pays AWS charges; a Resource Allocations balance does
not fund it automatically. The ten native science recordings retain their
separate execution, result and archive evidence.

The <a href="byo_aws_setup.html#existing-connection-recording">162-second existing-connection review</a>
is retained for accounts that are already connected. Its omitted entry and
verification clicks are not presented as first-time creation footage.

## MATLAB BYO setup clip

Follow the complete [MATLAB BYO setup tutorial](matlab_byo_setup.md). Show the
masked `port@server` form, **Configure license**, the cleared input and saved
secret-reference state, execution-role attachment/readiness, and the
**INSTITUTIONAL CONNECTION → Open Connector... → Re-check** sequence from a
network/VPN that can reach the institution's service. Keep the actual endpoint,
ARN, pairing code and account identifiers out of public footage.

If the account already has its managed secret, clearing the local reference
and using **Configure license** reattaches that existing secret; it does not
replace its value. Caption the branch exactly and retain a private restore
reference. Explain that pre-launch readiness checks are not a MATLAB checkout;
only the subsequent native MATLAB/ISSM run proves execution. The [195-second reviewed clip](matlab_byo_setup.md) is published with its off-screen-step limits stated.

## What counts as a completed walkthrough

For each row, retain the selected model, interface, example, run target and
input filenames; evidence that changed files were saved; the reviewed resource
shape and time limit; and the resulting job identifier in the private run
record. Check the model's completion log, expected figures/fields and the
downloaded ZIP after it has actually been saved and opened. Do not count a
generated download link as a completed download.

The reviewer records the video filename/link and run evidence for that row.
A failed staging step, solver error, missing field or unreadable archive keeps
that row incomplete even if another row has passed. Preserve unexpected
behavior and its resolution in the review notes rather than editing a failure
out of an apparent success.

## Reproducibility acceptance

Every science clip must retain the [complete run manifest and artifact checks](reproducibility.md):
actual submitted source/data hashes, executed image digest/model versions,
scientific settings/units, resource/process/thread limits, seeds or an explicit
no-RNG reason, actual job outcome, and saved output/archive hashes. Bind these
to the frozen run snapshot, not current workspace files. Publish a sanitized
manifest and keep raw account/license/provenance details private. Identify
byte-identity checks separately from numerical tolerances. No new PC/AWS
agreement is claimed without actual matched-input runs and computed comparison.

## Video acceptance

Each workflow has its own independently understandable clip. Its opening title
names the model/workflow and the application URL:
<https://cryostack.eas.gatech.edu/cryolauncher/>. Brief captions explain the goal,
input file/example, scientific settings and expected result before the relevant
controls are used. Name the input format and units, distinguish a source-only
comment edit from a scientific change, and explain what the plotted field and
color scale mean. If a plot omits axis or color-bar units, add a caption with
the units verified from the submitted case and model convention; do not guess
from a field name. Missing units/evidence keep the clip incomplete. A viewer
must be able to follow the clip without this page or an earlier video open.

Trim long queue, image-startup and solver waits. At each cut, show an elapsed-time
card stating which wait was skipped and the actual observed duration; retain
the real before/after job states and completion evidence. Do not simulate
progress, present a previous job as the current launch, or imply that an edited
wait is the model's runtime. Keep any failure and its correction in the review
record. End with the native result, a brief interpretation and evidence that
the results archive was actually saved and opened. The BYO setup segment
likewise explains its purpose and final connected/readiness state.

## Recording boundaries

- Use the existing license configuration for ISSM; do not expose its value,
  AWS account identifiers, role details, tokens or private file paths in the
  public recording. A configured license label is sufficient on screen.
- Keep one paid job active at a time and review its selected resource and
  timeout before launch. The earlier 14-second and 7.4-minute model samples
  are observations, not runtime promises for a changed case.
- Record each application's actual controls. This is a CryoLauncher matrix;
  it does not qualify ICESEE's separate ensemble-assimilation submission path.
- Do not show a planned hosted option or an isolated frontend candidate as
  deployed participant behavior. The [release checks](pilot_readiness.md)
  track that boundary.

[All pilot tutorials](../soft_launch.md)
