"""Gateway-only, owner-scoped institutional license bridge for hosted ISSM.

The existing paired session stays paired. Only a short-lived MATLAB-purpose
grant goes to the root supervisor; no control or deployment secret leaves here.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import re
import ssl
import stat
import urllib.request
import zipfile

MAX_RUNTIME_BYTES = 2 * 1024**2


def gateway_owner_credential(owner, key):
    """Separate from kernel owner grants; this authority stays on the gateway."""
    if not isinstance(owner, str) or not owner or len(owner) > 200 or not key:
        raise PermissionError('Gateway owner authority is unavailable')
    return hmac.new(key.encode(), b'cryostack-hosted-license-owner-v1\0'+owner.encode(), hashlib.sha256).hexdigest()


def runtime_archive(files=None):
    """Deterministic trusted client bundle, separate from participant input."""
    if files is None:
        from cryostack_src.cloud.runtime import license_tunnel_client_extra_files
        files = license_tunnel_client_extra_files()
        required = {'.cryostack_runtime/websockets/__init__.py',
                    '.cryostack_runtime/websockets/asyncio/client.py',
                    '.cryostack_runtime/websockets/asyncio/connection.py'}
        if not required <= set(files):
            raise ValueError('The pinned license-client dependency bundle is incomplete')
    if 'cryostack_license_tunnel_client.py' not in files:
        raise ValueError('The reviewed license client is missing')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        total = 0
        for name, text in sorted(files.items()):
            if name != 'cryostack_license_tunnel_client.py' and not re.fullmatch(
                    r'\.cryostack_runtime/websockets/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.py|'
                    r'\.cryostack_runtime/websockets/LICENSE', name):
                raise ValueError('Unexpected trusted license-runtime path')
            body = text.encode() if isinstance(text, str) else bytes(text)
            total += len(body)
            if total > MAX_RUNTIME_BYTES:
                raise ValueError('License runtime exceeds its bound')
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, body)
    return buffer.getvalue()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise PermissionError('License control redirects are refused')


class ConnectorLicenses:
    def __init__(self, config, *, call=None, runtime=None):
        self.config = config
        self.runtime = runtime_archive() if runtime is None else runtime
        self.digest = hashlib.sha256(self.runtime).hexdigest()
        if self.digest != config.connector_license_runtime_sha256:
            raise PermissionError('License runtime differs from its immutable review')
        self._call = call or self._request

    def _request(self, user_id, action, reservation=None, ttl=None):
        from icesee_jupyter_book.core.connector_relay_auth import deployment_token
        key = deployment_token()
        if not key:
            raise PermissionError('Institutional connection control is unavailable')
        body = dict(owner_user_id=user_id, action=action)
        if reservation is not None:
            body['reservation_id'] = reservation
        if ttl is not None:
            body['ttl_seconds'] = ttl
        request = urllib.request.Request(
            self.config.transfer_origin + '/connector/hosted-license',
            data=json.dumps(body).encode(), method='POST',
            headers={'Authorization': 'Bearer ' + gateway_owner_credential(user_id, key),
                     'Content-Type': 'application/json'})
        opener = urllib.request.build_opener(_NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        try:
            with opener.open(request, timeout=10) as response:
                raw = response.read(16385)
                if len(raw) > 16384:
                    raise ValueError('License control response exceeds its bound')
                result = json.loads(raw)
        except Exception:
            raise PermissionError('The institutional Connector is unavailable for this run.') from None
        if not isinstance(result, dict) or result.get('ok') is not True:
            raise PermissionError('The institutional Connector is unavailable for this run.')
        return result

    def connected(self, user_id):
        try:
            return self._call(user_id, 'status').get('connected') is True
        except Exception:
            return False

    def issue(self, user_id, reservation):
        from cryostack_src.cloud.matlab_license import site_cloud_license_port, site_cloud_license_vendor_port
        grant = self._call(user_id, 'grant', reservation, self.config.limits.task_timeout_seconds)
        if (grant.get('owner_user_id') != user_id or grant.get('reservation_id') != reservation
                or grant.get('purpose') != 'matlab-license'
                or not re.fullmatch('[a-f0-9]{32}', grant.get('session_id', ''))
                or not re.fullmatch('[A-Za-z0-9_-]{43,128}', grant.get('token', ''))):
            raise PermissionError('Institutional grant ownership or purpose differs')
        environment = {'CRYOSTACK_LT_RELAY': self.config.transfer_origin,
                       'CRYOSTACK_LT_SESSION': grant['session_id'],
                       'CRYOSTACK_LT_TOKEN': grant['token'],
                       'CRYOSTACK_LT_PURPOSE': 'matlab-license',
                       'CRYOSTACK_LT_PORT': str(site_cloud_license_port())}
        vendor = site_cloud_license_vendor_port()
        if vendor is not None:
            environment['CRYOSTACK_LT_VENDOR_PORT'] = str(vendor)
        return json.dumps({'runtime': base64.b64encode(self.runtime).decode(),
                           'environment': environment}, separators=(',', ':')).encode()

    def revoke(self, user_id, reservation):
        self._call(user_id, 'revoke', reservation)
