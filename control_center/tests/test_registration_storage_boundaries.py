from pathlib import Path
import pytest
from cryostack_src.workspace.identity import WorkspaceUser
from icesee_auth.provisioning import provision_owner_workspace

@pytest.fixture(autouse=True)
def private_store(tmp_path,monkeypatch):
    monkeypatch.setenv('CRYOSTACK_FROZEN_LEGACIES_STORAGE_DB',str(tmp_path/'quotas.db'))
    monkeypatch.delenv('CRYOSTACK_WORKSPACE_MOUNT',raising=False)


def test_owner_link_cannot_provision_another_account_directory(tmp_path):
    root=tmp_path/'workspace';users=root/'users';other=users/'another-owner';other.mkdir(parents=True)
    account=WorkspaceUser(user_id='approved-new-rehearsal',source='cryostack-auth')
    (users/account.safe_id).symlink_to(other,target_is_directory=True)
    with pytest.raises(RuntimeError,match='symbolic link'):
        provision_owner_workspace(account.user_id,workspace_root=root)
    assert not list(other.iterdir())


def test_users_link_cannot_redirect_provisioning_outside_the_configured_root(tmp_path):
    root=tmp_path/'workspace';root.mkdir()
    outside=tmp_path/'outside';outside.mkdir()
    (root/'users').symlink_to(outside,target_is_directory=True)
    with pytest.raises(RuntimeError,match='symbolic link'):
        provision_owner_workspace('approved-new-rehearsal',workspace_root=root)
    assert not list(outside.iterdir())
