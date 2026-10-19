"""Loopback-only Control Center allocation demo with fresh, private state; no AWS backend."""
from __future__ import annotations

import argparse
import getpass
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def create_demo(*, root, password):
    from aiohttp import web
    from icesee_auth import AuthManager
    from icesee_auth.security import hash_password
    from control_center import install_control_center
    from control_center.services.access import AccessService

    # Never inherit deployment credentials, OAuth clients, operator lists, or live state settings.
    for name in list(os.environ):
        if name.startswith(('AWS_', 'CRYOSTACK_', 'HTTP_X_CRYOSTACK_', 'APPTAINER_DOCKER_')):
            os.environ.pop(name,None)
    os.environ.update(CRYOSTACK_ALLOCATION_DEMO='1',CRYOSTACK_AUTH_DATABASE=str(root/'auth.db'),
        CRYOSTACK_CONTROL_OPS_DATABASE=str(root/'ops.db'),CRYOSTACK_WORKSPACE_ROOT=str(root/'workspace'),
        CRYOSTACK_LIVIST_DATABASE=str(root/'livist.db'),CRYOSTACK_FROZEN_LEGACIES_CATALOG=str(root/'catalog.db'),
        CRYOSTACK_FROZEN_LEGACIES_WORKING_CACHE=str(root/'cache'),CRYOSTACK_FROZEN_LEGACIES_REVIEW_ROOT=str(root/'reviews'))
    auth=AuthManager(database_path=root/'auth.db',secure_cookies=False)
    app=web.Application(client_max_size=16384)
    auth.install(app)
    app['access_service']=AccessService(auth.storage)
    install_control_center(app,auth=auth,database_path=root/'auth.db')
    # Both are isolated demo identities using the password entered locally by the operator.
    owner=auth.storage.create_user(email='owner@example.test',display_name='Demo owner',
        institution='Demo',password_hash=hash_password(password))
    auth.storage.grant_role(user_id=owner.id,role='owner')
    s=app['allocation_service']
    pool=s.configure_pool(owner.id,name='October 15 demo',budget=10000,intro_enabled=True,default_credit=1000)
    researcher=auth.storage.create_user(email='researcher@example.test',display_name='Demo researcher',
        institution='Demo',password_hash=hash_password(password))

    async def home(request):
        return web.Response(text='''<h1>CryoStack allocation simulation</h1><p>No AWS or scientific jobs execute here.</p>
        <a href="/control/allocations">Administrator</a> · <a href="/compute/allocations">Researcher</a>
        <p>The production four-application registry is unchanged.</p>''',content_type='text/html')
    app.router.add_get('/',home)
    return app,dict(owner_id=owner.id,researcher_id=researcher.id,pool_id=pool)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=18080)
    args=parser.parse_args()
    os.umask(0o077)
    root=Path(tempfile.mkdtemp(prefix='cryostack-allocation-demo-'))
    password=getpass.getpass('Choose demo-only login password (8+ characters): ')
    app,ids=create_demo(root=root,password=password)
    del password
    print('Private demo state:',root)
    print('Demo user IDs and pool:',ids)
    print('Log in as owner@example.test or researcher@example.test with your chosen demo password.')
    from aiohttp import web
    web.run_app(app,host='127.0.0.1',port=args.port)
