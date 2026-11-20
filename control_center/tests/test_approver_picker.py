from control_center.tests.test_registration_approval import Env
from control_center.templates_registrations import registrations_content


def test_owner_picker_lists_only_ready_accounts_and_explains_blockers(tmp_path):
    env = Env(tmp_path)
    owner = env.user('owner', 'owner')
    ready = env.user('ready')
    unverified = env.user('unverified', verified=False)
    pending = env.user('pending', status='pending')
    current = env.user('current')
    env.service.approvers.grant(actor_user_id=owner.id, email=current.email)
    view = env.service.overview(actor_user_id=owner.id)
    html = registrations_content(overview=view)
    assert f'<option value="{ready.email}">' in html
    for user in (owner, unverified, pending, current):
        assert f'<option value="{user.email}">' not in html
    assert 'Email confirmation needed' in html
    assert 'Account approval needed' in html
    assert f'/control/registrations?user={pending.id}' in html
    assert 'Ready to review' in html and 'Remove access' in html
    assert env.service.approver_candidates(ready.id) == []
