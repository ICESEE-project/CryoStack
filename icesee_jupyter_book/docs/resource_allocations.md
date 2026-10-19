# Resource allocations

CryoStack's Resource Allocations page manages persistent funding-pool budgets,
user allowances, and new-user credit policies within the authenticated Control
Center. It uses existing CryoStack identities; no separate account or feature
flag is required.

Administrators and owners use `/control/allocations`. Researchers use
`/compute/allocations` to view their own balances and test reservations.
Developers and maintainers are not allocation administrators.

## What the amounts mean

A pool budget is an internal planning allowance. It is not evidence of an AWS
promotional-credit award, an AWS account balance, or paid execution authority.
UI amounts are USD; the database and JSON APIs store integer cents.

For each user allocation:

`available = allocated credit − reserved credit − simulated charges`

For each pool:

`unallocated = pool budget − sum of user allocated credits`

Completing a test reservation does not replenish the pool's unallocated funds.
Revoking a user's unspent credits does. Never confuse ledger figures with
provider billing data.

## Funding Pools

Create a named pool with a total budget. Select **Edit** beside a pool to change
its name or budget. A budget cannot be reduced below committed user credits or
its configured new-user credit amount. Budget changes preserve the saved
onboarding policy.

## User Allocations

Select a funding pool, search for an existing user by name or email, and select
the result. Enter a signed USD adjustment and a meaningful reason. Positive
amounts add credits; negative amounts remove only unspent credits. Reserved and
charged amounts cannot be revoked. Pool budget and user-credit checks are
transactional; concurrent requests cannot overspend the ledger.

Filter the balance table by name, email, or pool. User names and email addresses
are administrative information; ordinary researchers see only their own
allocations.

## Automatic Credits

Choose a pool, set the amount per new user, and enable the policy. Only one pool
can issue automatic credits at a time. Optional email-domain and institution
filters must both match when specified. Matches ignore case; domain matching is
exact. These filters use registration metadata and do not prove institutional
membership.

A qualifying account receives at most one introductory grant when created,
provided enough unallocated pool funds remain. Existing accounts do not receive
retroactive grants. Disabling or changing a policy preserves previous balances.
Policy saves preserve the pool budget and name.

## Activity

The activity table displays the latest 100 allocation events with named actors,
readable actions, formatted amounts, reasons, and timestamps. The underlying
ledger retains earlier entries. Pool, policy, adjustment, introductory-grant,
and test-reservation actions are recorded. Authorization denials handled by the
authentication middleware may appear in platform access logs rather than this
allocation activity table.

## Test reservations and actual cloud workloads

Test reservations are explicitly simulated. They launch neither scientific
workloads nor AWS resources. Small has a $2/hour planning ceiling and a maximum
60-minute duration; Medium has an $8/hour planning ceiling and a maximum
30-minute duration. Each reservation includes a $1 overhead allowance. These
are not AWS prices. Limits are two active reservations per user and ten for the
platform. Completion charges the reserved ceiling in the simulation ledger;
cancellation releases the reservation. Completion and cancellation are
idempotent and restricted to the owner.

Actual CryoLauncher and ICESEE BYO cloud operations require the user's verified
AWS connection and remain billed to that account. Missing, unverified, or broken
connections fail closed for ordinary users; entering a server profile name does
not grant server credentials. Connections in CryoStack's host account are
rejected. Live managed/project-funded AWS execution remains disabled in the
allocation workflow.

## Administration and recovery

Data is stored in the existing authentication SQLite database. Back up that
actual database with SQLite's online backup API; do not copy an active SQLite
file without handling its journal/WAL. Keep backups private.

Source rollback must check current hashes before replacing files. Never restore
the entire authentication database over intervening registrations or unrelated
writes. The frontend-only revision introduces no database migration. Preserve
the BYO safeguards during rollback. Do not use global `pkill` commands to
restart a single gateway.

## Architecture

Diagram source (Mermaid):

```text
flowchart LR
    Identity[Existing CryoStack session] --> Roles{Role check}
    Roles -->|Owner or admin| Control[Allocation management]
    Roles -->|Signed-in user| Personal[Own balances and reservations]
    Control --> API[Same-origin authenticated JSON API]
    Personal --> API
    API --> Ledger[Transactional allocation service]
    Ledger --> DB[(Authentication database)]
    Registration[Normal user registration] --> Trigger[Eligible one-time grant]
    Trigger --> DB
    Scientific[Actual cloud operation] --> BYO[Verified user AWS role]
    BYO --> AWS[User-owned AWS account]
```

## Deployed overview and reconciliation

The running dashboard includes a ledger-composition overview, new-user grant-capacity indicators, read-only saved-policy previews, and an admin-only CSV balance export. Previewing a saved policy does not grant credits. Exported balances are an internal ledger snapshot, not a cloud-provider invoice.

See the [live screenshot walkthrough](visual_walkthrough.md) and [Dashboard architecture](dashboard_architecture.md) for the interface and implementation boundaries.
