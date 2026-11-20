# Auto-config Icepack: review a proposed configuration

Auto-config is a beta configuration planner. It proposes settings; it must not run a job without your explicit launch.

## Before you start

Sign in to [CryoLauncher](https://cryostack.eas.gatech.edu/cryolauncher/) and complete <a href="../soft_launch.html#before-your-first-run">account approval and funding-route checks</a>. These written controls describe the current BYO AWS path. The planned hosted invitation route is tracked separately in [pilot release checks](pilot_readiness.md); do not connect a personal paid account to work around unavailable hosted access.

Keep the case and container selected in the reviewed run plan, and run one job at a time. Record the image, resource shape and timeout before launch. Queueing and image startup add to model execution time. A displayed 60-minute time limit is a ceiling, not an observation that this example takes 60 minutes.

## Steps

1. Finish [Basic Icepack](basic_icepack.md) first. Select **Auto-config · Beta**.
2. Keep **Cloud** selected. Enter: “Run 00-meshes-functions with Icepack.” Use the exact example identifier, including hyphens. The beta parser accepts a limited vocabulary; longer conversational requests can require clarification. Keep the tested environment and resource choices from Basic.
3. Generate the proposal. If the assistant is unavailable, use Basic; report the missing capability rather than entering credentials into the prompt.
4. Review each proposed change against the displayed model, example, execution mode, resources, and time limit. Reject unexpected changes, unsupported backends, missing examples, and any increase in scientific problem size.
5. Apply only the proposal you understand. Confirm the controls actually changed and no job appeared before launch.
6. Use **Review in Advanced** to inspect the applied settings, then prepare the environment and open **Review & Launch**. Perform the same checks as Basic, then explicitly launch once.
7. Follow logs and retrieve, visualize, and download the results. Re-run with the equivalent Basic configuration before claiming parity.

Cloud resource requests are intentionally limited in this beta. A request to
change CPU, memory or time through unsupported settings produces **Please clarify**;
it does not silently apply an HPC value to AWS. Review the actual cloud resources
and time ceiling in **Review & Launch**. Ask the organizer if those settings are
unsuitable for your assigned pilot allowance.

## Negative checks

Ask for an unsupported GPU or multi-node run: the proposal must report unsupported settings rather than silently substituting a different scientific run. Do not launch such a proposal. Do not put a license address, cloud keys, private data, or secrets in the prompt.

## Expected outcome and evidence

A successful submission has a job ID. A successful model run finishes without a solver error. A complete tutorial also has retrievable logs, nonempty results, a readable figure, and a downloaded archive. Record all of these; a green job status alone is insufficient.

**Screenshot slot:** capture the selected model/example, completed run, and results panel using a participant test account. Exclude license fields, account identifiers, tokens, and private paths.

**Recording:** see the [recording matrix](recording_matrix.md) for the reviewed video and the evidence required for this workflow.

[All soft-launch tutorials](../soft_launch.md) · [Troubleshooting](troubleshooting.md)
