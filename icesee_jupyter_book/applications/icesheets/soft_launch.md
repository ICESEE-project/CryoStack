# CryoLauncher Pilot Tutorials

## Read the tutorials without signing in

The written guides, silent interactive videos and example downloads are public.
Read, watch and download without an account. Start with Icepack Basic: it does
not need a MATLAB license.

:::{raw} html
<style>
.pilot-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; margin: 14px 0 28px; }
.pilot-card { display: flex; flex-direction: column; gap: 6px; padding: 16px 18px; border: 1px solid rgba(148, 163, 184, 0.32); border-radius: 12px; background: #ffffff; color: #0f172a !important; text-decoration: none !important; transition: border-color 160ms ease, box-shadow 160ms ease; }
.pilot-card:hover { border-color: rgba(37, 99, 235, 0.45); box-shadow: 0 8px 22px rgba(15, 23, 42, 0.08); }
.pilot-card strong { font-size: 1rem; }
.pilot-card span:last-child { color: #475569; font-size: 0.9rem; line-height: 1.5; }
.pilot-step { display: inline-flex; width: 26px; height: 26px; align-items: center; justify-content: center; border-radius: 999px; background: #eff6ff; color: #1d4ed8; font-size: 0.8rem; font-weight: 700; }
</style>
<nav class="pilot-grid" aria-label="Start reading">
  <a class="pilot-card" href="soft_launch/basic_icepack.html#recorded-basic-icepack">
    <span class="pilot-step">1</span><strong>Begin with Icepack Basic</strong>
    <span>Watch the checked native shelf run, inspect its fields and follow the saved-result download.</span>
  </a>
  <a class="pilot-card" href="#verified-guides">
    <strong>Browse all 12 verified guides</strong>
    <span>Icepack and ISSM model workflows, your scripts and data, a controlled comparison, and the two setup recordings.</span>
  </a>
</nav>
:::

(before-your-first-run)=
## Practice with your account

Cloud runs use your connected AWS account today, and that account is billed.

[Create a CryoStack account](https://cryostack.eas.gatech.edu/auth/register?return_to=%2Fcryolauncher%2F)
or [sign in](https://cryostack.eas.gatech.edu/auth/login?return_to=%2Fcryolauncher%2F)
when you are ready to practice. New accounts need email confirmation and
administrator approval before using the applications.

For your first AWS connection, use
<a href="soft_launch/byo_aws_setup.html#first-time-connection">Connect an AWS account</a>: written steps and a recording of access-stack creation and verification.
For an already connected account, use the
<a href="soft_launch/byo_aws_setup.html#existing-connection-recording">existing-connection review</a>
instead of creating another role. ISSM also needs your own eligible MATLAB
license and a live Connector paired to your CryoStack account; follow the
[MATLAB and Connector setup guide](soft_launch/matlab_byo_setup.md).

(verified-guides)=
## Verified guides

The model recordings retain their checked native inputs, model outputs and saved
archives. Model-specific limits and scientific context are stated in each guide.

:::{raw} html
<nav class="pilot-grid" aria-label="Verified workflow guides">
  <a class="pilot-card" href="soft_launch/basic_icepack.html#recorded-basic-icepack"><strong>Basic Icepack</strong><span>Run the supplied synthetic shelf with its recorded default time stepping; inspect thickness, velocity and the archive.</span></a>
  <a class="pilot-card" href="soft_launch/basic_issm.html"><strong>Basic ISSM</strong><span>Run the supplied SquareIceShelf diagnostic case with your reviewed MATLAB license and Connector.</span></a>
  <a class="pilot-card" href="soft_launch/advanced_icepack.html"><strong>Advanced Icepack</strong><span>Clone the shelf and change only its temperature from 255.15 to 254.15 K; inspect the checked changed-case results.</span></a>
  <a class="pilot-card" href="soft_launch/advanced_issm.html"><strong>Advanced ISSM</strong><span>Clone SquareIceShelf and change the upstream thickness parameter from 1000 to 1010 m, retaining its downstream taper.</span></a>
  <a class="pilot-card" href="soft_launch/bring_script.html"><strong>Icepack: your script</strong><span>Download and import the two exact Python files, reference their JSON input and select the run target.</span></a>
  <a class="pilot-card" href="soft_launch/issm_own_script.html"><strong>ISSM: your script</strong><span>Import the three MATLAB sources, reference the JSON input and inspect the checked native diagnostic solve.</span></a>
  <a class="pilot-card" href="soft_launch/upload_dataset.html"><strong>Icepack: HDF5 initial fields</strong><span>Upload the bounded HDF5 fixture and verify thickness, geometry and velocity initialization in the native run.</span></a>
  <a class="pilot-card" href="soft_launch/issm_mat_data.html"><strong>ISSM: MAT initial fields</strong><span>Import four MATLAB sources and the MAT initial fields, then inspect initialization, native fields and the saved archive.</span></a>
  <a class="pilot-card" href="soft_launch/auto_issm.html"><strong>ISSM Auto-config</strong><span>Review and apply the tested solver-limit change, launch explicitly and inspect the native result.</span></a>
  <a class="pilot-card" href="soft_launch/own_problem_icepack.html"><strong>Controlled Icepack comparison</strong><span>Increase interior and inflow thickness together by 15 m, then compare the recorded initial and final fields.</span></a>
  <a class="pilot-card" href="soft_launch/byo_aws_setup.html"><strong>Connect an AWS account</strong><span>Create the access stack, read its RoleArn output and verify a first-time connection. Existing-account review is included separately.</span></a>
  <a class="pilot-card" href="soft_launch/matlab_byo_setup.html"><strong>Existing MATLAB license setup</strong><span>Reattach the existing managed license reference, connect your institutional session and check native MATLAB execution.</span></a>
</nav>
:::

The model examples use synthetic inputs and the recorded scientific environments.
Keep the downloaded source files and results with their hashes, units and run
settings. See [reproducibility](soft_launch/reproducibility.md) for those records
and [troubleshooting](soft_launch/troubleshooting.md) for common checks.
