"""Control Center view of the registration review queue.

Content builder only; wrapped by ``templates.control_layout``. Shows no
password hash, token, email body or mail credential.
"""
from __future__ import annotations

from html import escape

from .templates import _date
from .templates_access import ACCESS_STYLE

DECISION_LABELS = {
    "approve": "Approve",
    "reject": "Reject",
    "suspend": "Suspend",
    "reinstate": "Reinstate",
}

STYLE = """
<style>
  .reg-summary { display: flex; flex-wrap: wrap; gap: 0.6rem; margin-bottom: 1rem; }
  .reg-summary .access-tag { font-size: 0.75rem; padding: 0.35rem 0.6rem; }
  .reg-card { padding: 0.9rem 1rem; border-top: 1px solid #e2e8f0; }
  .reg-card:first-of-type { border-top: 0; }
  .reg-card.focus { background: #eff6ff; }
  .reg-head { display: flex; flex-wrap: wrap; gap: 0.4rem 1rem; align-items: baseline; }
  .reg-head strong { font-size: 0.9rem; }
  .reg-meta { color: #64748b; font-size: 0.75rem; }
  .reg-actions { display: grid; gap: 0.5rem; margin-top: 0.7rem; }
  .reg-actions form { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
  .reg-actions input[type="text"] { flex: 1 1 260px; min-height: 38px; padding: 0.5rem 0.65rem;
    border: 1px solid #cbd5e1; border-radius: 8px; font: inherit; font-size: 0.8rem; }
  .reg-warning { margin-bottom: 1rem; padding: 0.75rem 0.9rem; border: 1px solid #fde68a;
    border-radius: 10px; background: #fffbeb; color: #92400e; font-size: 0.8rem; line-height: 1.5; }
  .reg-kv { display: grid; grid-template-columns: max-content 1fr; gap: 0.3rem 1rem;
    padding: 0.9rem 1rem; font-size: 0.8rem; }
  .reg-kv dt { color: #64748b; font-weight: 700; }
  .reg-kv dd { margin: 0; overflow-wrap: anywhere; }

  .registration-page {max-width:1160px;margin:0 auto;color:#17243b}
  .registration-page * {box-sizing:border-box}
  .reg-hero {display:flex;justify-content:space-between;align-items:center;gap:24px;margin:0 0 24px;padding:6px 0 0}
  .reg-eyebrow {font-size:11px;letter-spacing:.14em;font-weight:750;color:#3865b6;text-transform:uppercase}
  .reg-hero h1 {font-size:28px;letter-spacing:-.035em;margin:7px 0 9px;line-height:1.15}
  .reg-hero p {font-size:14px;color:#62718a;margin:0;line-height:1.6}
  .reg-summary {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:0 0 24px}
  .reg-stat {padding:17px 20px;background:white;border:1px solid #e1e8f2;border-radius:12px;box-shadow:0 3px 12px #16274904;display:flex;align-items:center;gap:14px}
  .reg-stat b {font-size:28px;letter-spacing:-.04em;color:#243b64;line-height:1}
  .reg-stat span {font-size:12px;color:#61708a;font-weight:650}
  .reg-stat:first-child {background:#eff5ff;border-color:#cadaf6}
  .reg-stat:first-child b {color:#245bd2}
  .registration-page .panel {border-radius:14px;overflow:hidden;border:1px solid #dfe7f2;box-shadow:0 5px 20px #14294a04;margin-bottom:22px}
  .registration-page .panel-header {padding:18px 22px;background:#fff;font-size:15px;border-bottom:1px solid #e7edf5}
  .registration-page .reg-card {padding:20px 22px}
  .registration-page .reg-head {gap:6px 16px;align-items:center}
  .registration-page .reg-head strong {font-size:15px}
  .registration-page .reg-meta {font-size:12px;line-height:1.55;overflow-wrap:anywhere}
  .registration-page .access-tag {font-size:11px;font-weight:650;padding:4px 9px}
  .reviewer-workspace {display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr)}
  .reviewer-setup {padding:22px;border-right:1px solid #e7edf5;background:#fbfcff;min-width:0}
  .reviewer-setup>p:first-child {font-weight:650;font-size:15px;line-height:1.5}
  .reviewer-roster {min-width:0}
  .reviewer-roster .reg-card {padding:16px 20px!important}
  .reviewer-roster .reg-card strong {font-size:14px}
  .reviewer-roster .reg-card>div {min-width:0}
  .approver-picker {display:grid!important;grid-template-columns:minmax(0,1fr)!important;gap:15px!important;margin-top:22px}
  .approver-picker label {font-size:12px!important;font-weight:650!important;gap:7px!important;min-width:0}
  .registration-page input[type=text],.registration-page select {width:100%;min-width:0!important;height:44px!important;min-height:44px!important;padding:0 12px!important;border:1px solid #ccd7e7!important;border-radius:8px!important;background:#fff!important;color:#17243b;font:inherit!important;font-size:13px!important;box-shadow:0 1px 2px #14213a03}
  .registration-page input:focus,.registration-page select:focus {outline:3px solid #2563eb20;outline-offset:1px;border-color:#5281de!important}
  .registration-page .access-button {min-height:40px;border-radius:8px;padding:9px 15px;font-size:12px;white-space:nowrap}
  .approver-picker>.access-button {justify-self:start;margin-top:2px;background:#245bd2;box-shadow:0 3px 7px #245bd21a}
  .reviewer-roster .access-button {font-weight:600;color:#6a7486;border-color:#e0e6ee;background:transparent;min-height:34px;padding:6px 10px}
  .reviewer-roster .access-button:hover {color:#b42335;border-color:#edb9c1;background:#fff6f7}
  .reg-other {margin-top:14px;border-top:1px solid #edf1f7;padding-top:12px}
  .reg-other summary {font-size:12px;color:#62718a;cursor:pointer;font-weight:600}
  .reg-other[open] summary {margin-bottom:12px}
  .reg-other form {margin-top:9px}
  .reg-operations {margin-top:22px;border:1px solid #e1e8f2;border-radius:12px;background:#f8fafc;padding:17px 20px}
  .reg-operations>summary {cursor:pointer;font-size:13px;font-weight:650;color:#586b85}
  .reg-operations[open]>summary {margin-bottom:18px}
  .reg-history {display:grid;grid-template-columns:1fr 1fr;gap:16px}
  .reg-history details>summary {padding:16px 20px;cursor:pointer;font-size:13px;font-weight:600;color:#62718a}
  @media(max-width:850px){.reviewer-workspace{grid-template-columns:1fr}.reviewer-setup{border-right:0;border-bottom:1px solid #e7edf5}.reg-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.reg-history{grid-template-columns:1fr}}
  @media(max-width:480px){.reg-hero h1{font-size:24px}.reg-stat{padding:14px;gap:9px}.registration-page .reg-card{padding:16px}.reg-hero{display:block}.reg-actions form{align-items:stretch}.reg-actions input[type=text]{flex-basis:100%}}

</style>
"""


def _account_card(row: dict, *, focus: bool, can_decide: bool, link_accounts: bool = True) -> str:
    verified = row.get("email_verified_at")
    tags = [
        f'<span class="access-tag">{escape(row.get("registration_method") or "")}</span>',
        (f'<span class="access-tag success">email confirmed</span>' if verified
         else '<span class="access-tag failure">email not confirmed</span>'),
    ]
    if row.get("provisioning_status"):
        tags.append(f'<span class="access-tag">workspace: '
                    f'{escape(row["provisioning_status"])}</span>')
    forms = []
    other_forms = []
    for decision in row.get("decisions") or ():
        needs_reason = decision != "approve"
        danger = " danger" if decision in ("reject", "suspend") else ""
        placeholder = ("Reason (required, kept in the audit log)" if needs_reason
                       else "Note (optional, kept in the audit log)")
        (forms if decision == "approve" else other_forms).append(f"""
        <form method="post" action="/control/registrations/{escape(row['id'])}/decision">
          <input type="hidden" name="decision" value="{escape(decision)}">
          <input type="text" name="reason" maxlength="500" placeholder="{placeholder}"
                 aria-label="{escape(DECISION_LABELS[decision])}: reason"
                 {'required minlength="4"' if needs_reason else ''}>
          <button class="access-button{danger}" type="submit">{escape(DECISION_LABELS[decision])}</button>
        </form>""")
    if can_decide and row.get("status") == "pending" and not verified:
        forms.append('<p class="access-hint">Approval is available once the applicant '
                     'has confirmed their email address.</p>')
    if other_forms:
        forms.append('<details class="reg-other"><summary>Other actions</summary>' + ''.join(other_forms) + '</details>')
    address = (f'<a class="table-link" href="/control/users/{escape(row["id"])}">'
               f'{escape(row.get("email") or "")}</a>' if link_accounts else
               f'<span>{escape(row.get("email") or "")}</span>')
    return f"""
    <div class="reg-card{' focus' if focus else ''}" id="user-{escape(row['id'])}">
      <div class="reg-head">
        <strong>{escape(row.get('display_name') or '')}</strong>
        {address}
        <span class="reg-meta">{escape(row.get('institution') or 'No institution given')}</span>
        <span class="reg-meta">requested {_date(row.get('requested_at'))}</span>
      </div>
      <div style="margin-top:0.4rem">{''.join(tags)}</div>
      <div class="reg-actions">{''.join(forms)}</div>
    </div>"""


def registrations_content(*, overview: dict, message: str | None = None,
                          error: str | None = None) -> str:
    counts = overview["counts"]
    mail = overview["mail"]
    focus = overview.get("focus_user_id")
    can_decide = overview["can_decide"]
    limited = overview.get("registration_only", False)
    can_retry = overview.get("can_retry", can_decide)

    notices = []
    if message:
        notices.append(f'<div class="access-notice" role="status">{escape(message)}</div>')
    if error:
        notices.append(f'<div class="access-notice error" role="alert">{escape(error)}</div>')
    if not overview["approval_required"]:
        notices.append(
            '<div class="reg-warning">The approval gate is <strong>off</strong> '
            '(CRYOSTACK_REGISTRATION_APPROVAL). New accounts can use CryoStack '
            'immediately and nothing below is enforced. See the operator guide '
            'for the cutover procedure.</div>')
    if not limited and mail["problems"]:
        notices.append('<div class="reg-warning">Email delivery is misconfigured: '
                       + escape(" ".join(mail["problems"])) + '</div>')
    elif not limited and mail["mode"] == "disabled":
        notices.append('<div class="reg-warning">Email delivery is <strong>disabled</strong>: '
                       'notices are queued but not sent (CRYOSTACK_MAIL_MODE).</div>')
    if not limited and overview["approval_required"] and not mail["reviewers_authorized"]:
        notices.append('<div class="reg-warning">No authorized reviewer address is '
                       'configured, so nobody is '
                       'emailed about new registrations. Check this page.</div>')
    if not limited and mail["reviewers_refused"]:
        notices.append('<div class="reg-warning">Ignored reviewer addresses (no approved '
                       'account with registration-review permission): '
                       + escape(", ".join(mail["reviewers_refused"])) + '</div>')

    def section(title: str, status: str, empty: str) -> str:
        rows = overview["accounts"][status]
        body = "".join(_account_card(row, focus=row["id"] == focus, can_decide=can_decide,
                                    link_accounts=not limited)
                       for row in rows) or f'<div class="panel-empty">{escape(empty)}</div>'
        return f"""
    <div class="panel">
      <div class="panel-header">{escape(title)} ({counts.get(status, 0)})</div>
      {body}
    </div>"""

    chosen = overview.get("focus")
    selected = f"""
    <div class="panel" id="selected">
      <div class="panel-header">Selected account &middot; {escape(chosen['status'])}</div>
      {_account_card(chosen, focus=True, can_decide=can_decide, link_accounts=not limited)}
    </div>""" if chosen else ""
    if limited:
        return f"""{ACCESS_STYLE}{STYLE}{''.join(notices)}
        <p class="access-hint">You can approve or reject new registrations after their email is confirmed.</p>
        {selected}{section('Awaiting review', 'pending', 'No registrations are waiting.')}"""

    approver_panel = ""
    if overview.get("can_manage_approvers"):
        candidates = overview.get("approver_candidates", [])
        eligible = [entry for entry in candidates if entry["eligible"]]
        waiting = [entry for entry in candidates if not entry["eligible"]]
        options = "".join(
            f'<option value="{escape(entry["email"])}">{escape(entry.get("display_name") or entry["email"])} — {escape(entry["email"])}</option>'
            for entry in eligible)
        entries = "".join(f"""
          <div class="reg-card" style="display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap">
            <div><strong>{escape(entry.get('display_name') or entry['email'])}</strong>
              <div class="reg-meta">{escape(entry['email'])}</div>
              <span class="access-tag{' success' if entry['active'] else ' failure'}">
                {'Ready to review' if entry['active'] else 'Permission inactive — check this account'}</span></div>
            <form method="post" action="/control/registrations/approvers/{escape(entry['user_id'])}/remove">
              <button class="access-button secondary" type="submit">Remove access</button>
            </form>
          </div>""" for entry in overview.get("approvers", []))
        waiting_rows = "".join(
            f'<div style="display:flex;justify-content:space-between;gap:1rem;padding:.75rem 0;border-bottom:1px solid var(--border,#e2e8f0);flex-wrap:wrap">'
            f'<div><strong>{escape(entry.get("display_name") or entry["email"])}</strong><div class="reg-meta">{escape(entry["email"])}</div></div>'
            f'<div><span class="access-tag">{("Email confirmation needed" if entry["email_verified_at"] is None else "Account approval needed")}</span> '
            f'<a href="/control/registrations?user={escape(entry["id"])}">Review account →</a></div></div>'
            for entry in waiting)
        add_form = f"""
            <form method="post" action="/control/registrations/approvers/add" style="display:grid;grid-template-columns:minmax(220px,1fr) minmax(180px,1fr) auto;gap:.75rem;align-items:end" class="approver-picker">
              <label style="display:grid;gap:.4rem;font-weight:600">Choose a reviewer
                <select name="email" required aria-label="Approver email" style="min-height:44px;border:1px solid #cbd5e1;border-radius:8px;padding:.65rem;background:white;color:#172033;max-width:100%">
                  <option value="" disabled selected>Select an eligible account</option>{options}
                </select></label>
              <label style="display:grid;gap:.4rem;font-weight:600"><span>Note <span class="reg-meta">(optional)</span></span>
                <input type="text" name="reason" maxlength="500" aria-label="Approver note" placeholder="e.g. Backup while I am away" style="min-height:44px;border:1px solid #cbd5e1;border-radius:8px;padding:.65rem;box-sizing:border-box"></label>
              <button class="access-button" type="submit">Add approver</button>
            </form>""" if eligible else '<p class="access-hint">No additional accounts are ready yet. Review the accounts below, or ask your reviewer to sign up and confirm their email.</p>'
        approver_panel = f"""
        <style>@media(max-width:800px){{.approver-picker{{grid-template-columns:1fr!important}}}}</style>
        <div class="panel" id="registration-approvers">
          <div class="panel-header">Registration approvers</div>
          <div class="reviewer-workspace"><div class="reviewer-setup"><p style="margin-top:0">Choose trusted people to review signups when you are away.</p>
            <p class="access-hint">Reviewers receive email notifications and can approve or reject new registrations. Only owners can manage this list.</p>
            {add_form}</div><div class="reviewer-roster">
          <div style="padding:.75rem 1rem;background:#f8fafc;font-weight:600">Current reviewers</div>
          {entries or '<div class="panel-empty">You are the only reviewer. Add a backup above.</div>'}
          {('<details style="padding:1rem"><summary style="cursor:pointer;font-weight:600">Not ready to add (' + str(len(waiting)) + ')</summary><p class="access-hint">Email confirmation and account approval are required before someone can review other people.</p>' + waiting_rows + '</details>') if waiting else ''}
        </div></div></div>"""

    provisioning_rows = "".join(f"""
      <tr>
        <td><a class="table-link" href="/control/users/{escape(r['user_id'])}">{escape(r['email'])}</a></td>
        <td>{escape(r['status'])}</td><td>{int(r['attempts'])}</td>
        <td>{escape(r.get('last_error') or '')}</td><td>{_date(r['updated_at'])}</td>
        <td>{'' if not can_retry else f'''<form method="post" action="/control/registrations/{escape(r['user_id'])}/provisioning">
          <button class="access-button secondary" type="submit">Retry now</button></form>'''}</td>
      </tr>""" for r in overview["provisioning"])
    failed_mail = "".join(f"""
      <tr>
        <td>{escape(r['template'])}</td><td>{escape(r['recipient'])}</td>
        <td>{int(r['attempts'])}</td><td>{escape(r.get('last_error') or '')}</td>
        <td>{_date(r['updated_at'])}</td>
        <td>{'' if not can_retry else f'''<form method="post" action="/control/registrations/notifications/{escape(r['id'])}/retry">
          <button class="access-button secondary" type="submit">Retry</button></form>'''}</td>
      </tr>""" for r in mail["failed"])
    mail_counts = ", ".join(f"{escape(k)} {v}" for k, v in sorted(mail["counts"].items())) or "none"
    baseline = overview.get("baseline")

    return f"""
    {ACCESS_STYLE}{STYLE}
    <div class="registration-page">
    <div class="reg-hero"><div><span class="reg-eyebrow">Access management</span>
      <h1>Review access requests</h1><p>Review new accounts and manage the people who can approve them.</p></div></div>
    {''.join(notices)}
    <div class="reg-summary">
      <div class="reg-stat"><b>{counts.get('pending',0)}</b><span>Awaiting review</span></div>
      <div class="reg-stat"><b>{counts.get('approved',0)}</b><span>Approved accounts</span></div>
      <div class="reg-stat"><b>{len(overview.get('approvers',[]))}</b><span>Backup reviewers</span></div>
      <div class="reg-stat"><b>{counts.get('suspended',0)+counts.get('rejected',0)}</b><span>Inactive accounts</span></div>
    </div>
    {selected}
    {section('Awaiting review', 'pending', 'No registrations are waiting.')}
    {approver_panel}
    <div class="reg-history">
      <details class="panel"><summary>Suspended accounts · {counts.get('suspended',0)}</summary>{section('Suspended', 'suspended', 'No suspended accounts.')}</details>
      <details class="panel"><summary>Rejected registrations · {counts.get('rejected',0)}</summary>{section('Rejected', 'rejected', 'No rejected registrations.')}</details>
    </div>
    <details class="reg-operations"><summary>Delivery &amp; workspace details</summary>
    <div class="panel">
      <div class="panel-header">Workspace provisioning</div>
      {f'''<div class="access-table-wrap"><table>
        <thead><tr><th>Account</th><th>State</th><th>Attempts</th><th>Last error</th>
        <th>Updated</th><th></th></tr></thead><tbody>{provisioning_rows}</tbody></table></div>'''
        if provisioning_rows else '<div class="panel-empty">No workspace provisioning tasks are waiting.</div>'}
    </div>

    <div class="panel">
      <div class="panel-header">Email</div>
      <dl class="reg-kv">
        <dt>Delivery</dt><dd>{escape(mail['mode'])}</dd>
        <dt>Sender</dt><dd>{escape(mail['sender'] or '-')}</dd>
        <dt>Link origin</dt><dd>{escape(mail['base_url'] or '-')}</dd>
        <dt>Reviewers</dt><dd>{int(mail['reviewers_authorized'])} authorized address(es)</dd>
        <dt>Outbox</dt><dd>{mail_counts}</dd>
        <dt>Baseline</dt><dd>{escape(_date(baseline['created_at']) + ' by ' + baseline['operator']) if baseline else 'not recorded'}</dd>
      </dl>
      {f'''<div class="access-table-wrap"><table>
        <thead><tr><th>Message</th><th>To</th><th>Attempts</th><th>Last error</th>
        <th>Updated</th><th></th></tr></thead><tbody>{failed_mail}</tbody></table></div>'''
        if failed_mail else ''}
    </div>
    </details></div>
    """
