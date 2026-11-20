# Pilot funding and release checks

The pilot has three separate records: the model execution evidence, the
participant funding/access controls, and the published walkthroughs. A native
model run can pass before a hosted funding route is ready; a saved dashboard
budget does not prove that a paid run used that budget.

## Current route and planned participant experience

The deployed Resource Allocations page manages persistent budgets and credits.
Its Test reservations are simulations, and the allocation API still rejects a
live managed reservation. Current BYO AWS runs use a verified connected account
and are billed to that account. The recording session follows that existing
route and reuses the configured MATLAB license for ISSM.

The intended invitation experience is **hosted by CryoStack**: a selected
participant signs up, confirms the invited email address and waits for approval.
That hosted route should not ask an invitee to create an AWS account, add a
payment card or connect a personal AWS role. Until its release checks below
pass and it is enabled in production, do not present that experience as active.

An isolated hosted-pilot candidate exists, including funding, transfer and
broker components. Source code and passing offline checks are development
evidence; they do not establish deployed participant acceptance. The hosted
ISSM path also needs its own MATLAB/Connector integration check. Working BYO
ISSM licensing does not establish hosted ISSM licensing.

## Saved budget records — 19 November 2026

The dashboard now has two **Manual** budget records: **$400 CryoStack Fund** and
**$100 Pilot Reserve**, totalling **$500**. The saved snapshot has **$0 allocated**,
**$0 reserved** and **$500 unallocated**. **Automatic credits remain OFF**, and
**shared hosted execution remains OFF**.

These are internal ledger budgets. Saving them did not transfer money to AWS,
pay a card, award a participant grant or activate a hosted run. Existing BYO
runs still use the participant's explicitly connected AWS account and are billed
to that account. The policy below describes the approved hosted plan; it is not
an active participant entitlement.

## Reviewed funding policy

The pilot plan reserves **$400 for participant grants** and **$100 for operating
overhead**. A selected participant receives **one $25 introductory allowance**,
with **no automatic top-up**. A $400 grant pool therefore supports at most
**16 complete $25 grants**; the operating reserve is not extra user credit.

The approved allowance is usable through **23:59:59 UTC on 18 February 2027**,
with an exclusive backend expiry of **2027-02-19T00:00:00Z**, once hosted grants
are activated. The exact invitation list and campaign closure must be recorded
by the organizer before hosted activation. Approval is based on the confirmed
invited email address. Sharing an institutional domain is not sufficient.
Do not grant the same person a new allowance after suspension/reinstatement or
a repeat registration. An account's visible balance is an internal allowance,
not an AWS promotional-credit award or an AWS spending cap.

The payment source and any institutional purchase/reimbursement process are
handled separately from these allowance records. No participant charge or
institutional purchase is authorized by this documentation.

## Release evidence

| Requirement | Evidence needed before calling the hosted pilot available |
| --- | --- |
| Invitation and approval | A fresh invited account confirms email and receives one reviewed grant at approval. A non-invited confirmed account receives no pilot grant or paid submission access. |
| Per-person and campaign limits | A server-side reservation rejects insufficient credit, expired grants, closed campaigns and top-up attempts. Concurrent sessions cannot spend the same available allowance twice. |
| Scientific execution | The selected model, saved scripts, data references, resource preset and timeout are bound to the submitted run. The completion record contains model output, retrievable logs and a readable downloaded archive. |
| Credential boundary | Participant scripts and model containers receive no AWS role credentials or owner connection record. Input/output transfer is scoped to the participant and run. |
| Isolation | One participant cannot retrieve, replace or terminate another participant's job or files, including after reload or reconnection. |
| Runtime and recovery | Cancellation, startup delay, execution timeout, worker failure and restart retain the correct reservation until execution and cost evidence can be reconciled. |
| Settlement | The service distinguishes a reserved ceiling, an estimated charge and verified settlement. It does not label browser-provided or simulated amounts as an AWS invoice. |
| ISSM licensing | The hosted ISSM job uses the reviewed existing MATLAB/Connector mechanism. A successful BYO ISSM run alone does not satisfy this check. |
| Walkthroughs | Each of the [science recording rows](recording_matrix.md) has its own reviewed video and run/download evidence. Recording a working BYO path is documented as BYO, not as hosted-funded acceptance. |
| Documentation publication | The current source and built page agree about the active route, model restrictions, grant policy and recording links. Existing private data and credentials remain outside the public pages. |

## Application scope

This tutorial series concerns standalone ISSM/Icepack runs through
**CryoLauncher**. **ICESEE** remains a separate data-assimilation application
with its own submission and results contracts. Its current staged Cloud
review accepts Lorenz-96 or `synthetic_ice_stream` within a two-process bound;
the earlier live-AWS reference is single-process Lorenz-96. See the
<a href="/applications/icesee/user_manual#cloud-mode">ICESEE manual</a> for that separate path. **Frozen Legacies** and **LIVIST** are
data applications outside this model-compute grant plan.

<a href="/docs/resource_allocations">Resource allocations</a> ·
[All pilot tutorials](../soft_launch.md)
