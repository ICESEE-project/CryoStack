"""Bounded, unprivileged pilot worker. Standalone stdlib; not activated by itself.

The gateway must qualify a pinned NoTaskRole job definition and deliver the
per-run transfer capability through ECS secrets. Never run this on a gateway:
root is required only inside the reviewed, disposable model container.
"""
from __future__ import annotations

import ctypes
import base64
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import selectors
import signal
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

MODEL_UID = 65534
MAX_INPUT = 64 * 1024**2
MAX_OUTPUT = 64 * 1024**2
MAX_LOG = 2 * 1024**2
MAX_FILES = 256
MAX_MODEL_PROCESSES = 128
CREDENTIAL_ENV = frozenset((
    'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN',
    'AWS_CONTAINER_CREDENTIALS_RELATIVE_URI', 'AWS_CONTAINER_CREDENTIALS_FULL_URI',
    'AWS_WEB_IDENTITY_TOKEN_FILE', 'AWS_ROLE_ARN', 'AWS_SHARED_CREDENTIALS_FILE',
    'AWS_CONFIG_FILE', 'AWS_PROFILE', 'AWS_DEFAULT_PROFILE',
))


def assert_no_task_credentials(environment):
    if any(environment.get(key) for key in CREDENTIAL_ENV):
        raise PermissionError('Pilot model tasks must not receive an AWS task role or credentials')


def safe_extract(data, destination, *, uid=MODEL_UID, byte_limit=MAX_INPUT):
    """Extract bounded regular inputs only. No links, duplicate paths or outputs."""
    if len(data) > byte_limit:
        raise ValueError('Pilot input exceeds its byte allowance')
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Use a new private model input directory')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if not entries or len(entries) > MAX_FILES:
            raise ValueError('Pilot input entry count is invalid')
        names, size = set(), 0
        for entry in entries:
            name = entry.filename.rstrip('/')
            parts = name.split('/')
            mode = entry.external_attr >> 16
            if (not name or '\\' in name or '\x00' in name or
                    any(part in ('', '.', '..') for part in parts) or
                    PurePosixPath(name).is_absolute() or parts[0] == 'outputs' or
                    stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR) or
                    entry.flag_bits & 1):
                raise ValueError('Pilot input contains an unsafe or reserved path')
            if name in names:
                raise ValueError('Pilot input contains duplicate paths')
            names.add(name)
            size += entry.file_size
            if size > byte_limit:
                raise ValueError('Expanded pilot input exceeds its byte allowance')
        destination.mkdir(mode=0o700)
        for entry in entries:
            path = destination / entry.filename.rstrip('/')
            path.parent.mkdir(parents=True, exist_ok=True)
            if entry.is_dir():
                path.mkdir(exist_ok=True)
                continue
            with archive.open(entry) as source, path.open('xb') as target:
                count = 0
                while chunk := source.read(65536):
                    count += len(chunk)
                    if count > entry.file_size or count > byte_limit:
                        raise ValueError('Input decompression exceeded its declared size')
                    target.write(chunk)
            path.chmod(0o600)
    if uid is not None:
        for path in [destination, *destination.rglob('*')]:
            os.chown(path, uid, uid)
            if path.is_dir():
                path.chmod(0o700)
    return destination


#: The one delivered secret a model may see, and only for the model that
#: needs it. The transfer capability and every other service value stay with
#: the supervisor.
MODEL_SECRET_ENV = {'issm': ('MLM_LICENSE_FILE',)}
MODEL_SCRIPT = {'icepack': 'run.py', 'issm': 'runme.m'}
ISSM_RUNNER = 'cryostack_issm_cloud_runner.sh'


def child_environment(environment, work, *, model='icepack'):
    """Image runtime settings only; service capabilities never enter the model."""
    names = {'PATH', 'LANG', 'LC_ALL', 'TZ', 'LD_LIBRARY_PATH', 'VIRTUAL_ENV',
             'PETSC_DIR', 'PETSC_ARCH', 'SLEPC_DIR', 'PYTHONUNBUFFERED'}
    names |= set(MODEL_SECRET_ENV.get(model, ()))
    result = {key: value for key, value in environment.items() if key in names}
    result.update(HOME=str(work / 'home'), XDG_CACHE_HOME=str(work / 'home/.cache'),
                  TMPDIR=str(work / 'tmp'), MPLBACKEND='Agg',
                  PYOP2_CACHE_DIR=str(work / 'home/.cache/pyop2'),
                  FIREDRAKE_TSFC_KERNEL_CACHE_DIR=str(work / 'home/.cache/tsfc'),
                  OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', PYTHONUNBUFFERED='1',
                  USER='nobody', LOGNAME='nobody')
    if model == 'issm':
        result.update(WORKDIR=str(work), RUN_TARGET=MODEL_SCRIPT['issm'],
                      ICESEE_RUN_DIR=str(work))
    return result


class BoundedLog:
    def __init__(self, sink, *, limit=MAX_LOG, secrets=()):
        if type(limit) is not int or not 1 <= limit <= MAX_LOG:
            raise ValueError('Invalid bounded log allowance')
        self.sink, self.limit, self.written = sink, limit, 0
        self.secrets = sorted({bytes(x) for x in secrets if x}, key=len, reverse=True)
        if any(len(value) > 4096 for value in self.secrets):
            raise ValueError('Unexpectedly large private capability')
        self.keep = max((len(value) - 1 for value in self.secrets), default=0)
        self.pending, self.truncated = b'', False

    def _write(self, data):
        available = max(0, self.limit - self.written)
        if len(data) > available:
            self.truncated = True
        data = data[:available]
        if data:
            self.sink(data)
            self.written += len(data)

    def feed(self, data, *, final=False):
        self.pending += data
        for private in self.secrets:
            self.pending = self.pending.replace(private, b'[redacted]')
        keep = 0 if final else self.keep
        if len(self.pending) > keep:
            end = len(self.pending) - keep
            self._write(self.pending[:end])
            self.pending = self.pending[end:]
        if final:
            self.pending = b''


def _model_pids(uid=MODEL_UID):
    found = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            status = (entry / 'status').read_text()
            real = next(line.split()[1] for line in status.splitlines() if line.startswith('Uid:'))
            state = next(line.split()[1] for line in status.splitlines() if line.startswith('State:'))
            if int(real) == uid and state != 'Z':
                found.append(int(entry.name))
        except (OSError, ValueError, StopIteration):
            continue
    return found


def _stop_model(uid=MODEL_UID):
    """Also stop escaped process groups, scoped to this container's reserved UID."""
    if os.geteuid() != 0:
        raise PermissionError('Process cleanup requires the isolated root worker')
    for sig, duration in ((signal.SIGTERM, 1.0), (signal.SIGKILL, 1.0)):
        for pid in _model_pids(uid):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        end = time.monotonic() + duration
        while _model_pids(uid) and time.monotonic() < end:
            time.sleep(0.02)
    return not _model_pids(uid)


def _drop_privileges(uid, maximum_file_bytes):
    os.setgroups([])
    os.setgid(uid)
    os.setuid(uid)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise OSError(ctypes.get_errno(), 'Cannot restrict privilege gains')
    resource.setrlimit(resource.RLIMIT_NPROC, (MAX_MODEL_PROCESSES, MAX_MODEL_PROCESSES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    resource.setrlimit(resource.RLIMIT_FSIZE, (maximum_file_bytes, maximum_file_bytes))


def run_science(command, work, *, seconds, environment=None, sink=None,
                log_limit=MAX_LOG, uid=MODEL_UID, private_values=(), model='icepack'):
    if os.geteuid() != 0 or uid == 0:
        raise PermissionError('Use a disposable model container with an isolated root supervisor')
    if type(seconds) is not int or not 1 <= seconds <= 600:
        raise ValueError('Pilot model runtime must be between 1 and 600 seconds')
    environment = dict(os.environ if environment is None else environment)
    assert_no_task_credentials(environment)
    if _model_pids(uid):
        raise PermissionError('Reserved model identity is already active')
    work = Path(work)
    if work.is_symlink():
        raise ValueError('Model directory must not be a symlink')
    work = work.resolve()
    if not work.is_dir():
        raise ValueError('A prepared private model directory is required')
    for name in ('home', 'tmp', 'outputs'):
        path = work / name
        path.mkdir(exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise ValueError('Model state paths must be ordinary directories')
        os.chown(path, uid, uid)
        path.chmod(0o700)
    log = BoundedLog(sink or sys.stdout.buffer.write, limit=log_limit, secrets=private_values)
    start = time.monotonic()
    process = subprocess.Popen(command, cwd=work, env=child_environment(environment, work, model=model),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        close_fds=True, start_new_session=True,
        preexec_fn=lambda: _drop_privileges(uid, MAX_OUTPUT))
    selector = selectors.DefaultSelector()
    os.set_blocking(process.stdout.fileno(), False)
    selector.register(process.stdout, selectors.EVENT_READ)
    timed_out, cleaned, ended, stream_closed = False, False, None, False
    try:
        while True:
            now = time.monotonic()
            status = process.poll()
            if status is None and not timed_out and now - start >= seconds:
                timed_out = True
                cleaned = _stop_model(uid)
                ended = time.monotonic()
            elif status is not None and ended is None:
                cleaned = _stop_model(uid)
                ended = time.monotonic()
            events = selector.select(0.05)
            eof = False
            for key, _ in events:
                try:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    eof = stream_closed = True
                    selector.unregister(key.fileobj)
                    break
                log.feed(chunk)
            if ((stream_closed and process.poll() is not None) or
                    (ended is not None and time.monotonic() - ended > 1.0)):
                break
        process.wait(timeout=2)
    finally:
        cleaned = _stop_model(uid)
        selector.close()
        process.stdout.close()
        log.feed(b'', final=True)
    return {'exit_code': 124 if timed_out else process.returncode,
            'timed_out': timed_out, 'runtime_seconds': time.monotonic() - start,
            'log_bytes_forwarded': log.written, 'log_truncated': log.truncated,
            'model_uid': uid, 'model_processes_stopped': cleaned}


def package_outputs(directory, destination, receipt, *, byte_limit=MAX_OUTPUT):
    """Package after model cleanup; never follow model-created links or devices."""
    directory, destination = Path(directory), Path(destination)
    if not receipt.get('model_processes_stopped'):
        raise PermissionError('Stop model processes before collecting outputs')
    entries, size, count = [], 0, 0
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Model output directory is unavailable')
    for path in directory.rglob('*'):
        count += 1
        mode = path.lstat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError('Output links and special files are refused')
        if count > MAX_FILES:
            raise ValueError('Pilot output entry count exceeded')
        if path.name == '.cryostack-worker.json':
            raise ValueError('Model output uses a reserved receipt filename')
        if stat.S_ISREG(mode):
            size += path.stat().st_size
            if size > byte_limit:
                raise ValueError('Pilot output exceeds its byte allowance')
            entries.append(path)
    with destination.open('xb') as target:
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(entries):
                archive.write(path, path.relative_to(directory))
            archive.writestr('.cryostack-worker.json', json.dumps(receipt, sort_keys=True))
    if destination.stat().st_size > byte_limit:
        destination.unlink()
        raise ValueError('Compressed pilot output exceeds its byte allowance')
    return destination


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        raise PermissionError('Pilot transfer redirects are refused')


def transfer(origin, reservation, name, token, *, data=None, byte_limit=MAX_INPUT):
    from urllib.parse import urlsplit
    parsed = urlsplit(origin)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')
            or not re.fullmatch(r'[a-f0-9]{32}', reservation)
            or name not in ('input', 'output', 'license', 'license-release')):
        raise ValueError('A reviewed HTTPS transfer origin and reservation are required')
    if data is not None and (name != 'output' or len(data) > MAX_OUTPUT):
        raise ValueError('Invalid bounded output transfer')
    if data is None and name not in ('input', 'license', 'license-release'):
        raise ValueError('Only reviewed input downloads are supported')
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', token):
        raise ValueError('Invalid private transfer capability')
    opener = urllib.request.build_opener(_NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    request = urllib.request.Request(origin.rstrip('/') + '/api/pilot-transfer/' + reservation + '/' + name,
        data=data, method='POST' if data is not None or name == 'license-release' else 'GET',
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/zip'})
    with opener.open(request, timeout=30) as response:
        length = response.headers.get('Content-Length')
        if length is not None and int(length) > byte_limit:
            raise ValueError('Transfer exceeds the pilot byte allowance')
        content = response.read(byte_limit + 1)
        if len(content) > byte_limit:
            raise ValueError('Transfer exceeds the pilot byte allowance')
        return content


def validate_license_payload(data, spec):
    """A trusted bundle digest and fixed-purpose localhost plan, never model input."""
    if len(data) > 4 * 1024**2:
        raise ValueError('License response exceeds its bound')
    payload = json.loads(data)
    if not isinstance(payload, dict) or set(payload) != {'runtime', 'environment'}:
        raise ValueError('Unexpected license response fields')
    runtime = base64.b64decode(payload['runtime'], validate=True)
    if (len(runtime) > 2 * 1024**2
            or hashlib.sha256(runtime).hexdigest() != spec['license_runtime_sha256']):
        raise PermissionError('Trusted license runtime differs from immutable review')
    environment = payload['environment']
    required = {'CRYOSTACK_LT_RELAY', 'CRYOSTACK_LT_SESSION', 'CRYOSTACK_LT_TOKEN',
                'CRYOSTACK_LT_PURPOSE', 'CRYOSTACK_LT_PORT'}
    if not isinstance(environment, dict) or not required <= set(environment) or set(environment) - required - {'CRYOSTACK_LT_VENDOR_PORT'}:
        raise PermissionError('Unexpected private-service settings')
    if (environment['CRYOSTACK_LT_RELAY'] != spec['origin']
            or environment['CRYOSTACK_LT_PURPOSE'] != 'matlab-license'
            or not re.fullmatch('[a-f0-9]{32}', environment['CRYOSTACK_LT_SESSION'])
            or not re.fullmatch('[A-Za-z0-9_-]{43,128}', environment['CRYOSTACK_LT_TOKEN'])):
        raise PermissionError('License capability origin or purpose differs')
    for name in ('CRYOSTACK_LT_PORT', 'CRYOSTACK_LT_VENDOR_PORT'):
        if name in environment and (not isinstance(environment[name], str)
                or not re.fullmatch('[0-9]{1,5}', environment[name])
                or not 1024 <= int(environment[name]) <= 65535):
            raise ValueError('Invalid local license listener port')
    if environment.get('CRYOSTACK_LT_PORT') == environment.get('CRYOSTACK_LT_VENDOR_PORT'):
        raise ValueError('License listeners must use distinct ports')
    return runtime, environment


@contextmanager
def supervisor_license(spec, token, environment, private):
    """Start tracked root-owned listeners; only localhost MLM reaches the model.

    Trusted code lives outside the model-owned tree and is digest-checked.
    The listeners receive no transfer capability or AWS identity. Their token
    is never on argv, in scientific inputs or in scientific child environment.
    """
    if 'license_runtime_sha256' not in spec:
        yield environment, ()
        return
    processes = []
    issued = False
    try:
        # A response can be lost after the gateway mints a grant. Attempt its
        # idempotent release even when the download itself fails.
        issued = True
        data = transfer(spec['origin'], spec['reservation'], 'license', token, byte_limit=4*1024**2)
        runtime, plan = validate_license_payload(data, spec)
        support = safe_extract(runtime, private / 'license-runtime', uid=None, byte_limit=2*1024**2)
        helper = support / 'cryostack_license_tunnel_client.py'
        if not helper.is_file():
            raise ValueError('Trusted license client is missing')
        private_env = {key: environment[key] for key in ('PATH', 'LANG', 'LC_ALL', 'LD_LIBRARY_PATH') if key in environment}
        private_env.update(plan)
        endpoints = [('primary', plan['CRYOSTACK_LT_PORT'])]
        if plan.get('CRYOSTACK_LT_VENDOR_PORT'):
            endpoints.append(('vendor', plan['CRYOSTACK_LT_VENDOR_PORT']))
        for endpoint, port in endpoints:
            local_env = dict(private_env, CRYOSTACK_LT_ENDPOINT=endpoint, CRYOSTACK_LT_PORT=port)
            subprocess.run([sys.executable, str(helper), 'selfcheck'], env=local_env,
                           cwd=support, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30, check=True)
            process = subprocess.Popen([sys.executable, str(helper), 'serve'], env=local_env,
                           cwd=support, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
            processes.append(process)
            import socket
            end = time.monotonic() + 5
            while True:
                if process.poll() is not None:
                    raise PermissionError('Institutional license listener could not start')
                with socket.socket() as connection:
                    connection.settimeout(.2)
                    if connection.connect_ex(('127.0.0.1', int(port))) == 0:
                        break
                if time.monotonic() >= end:
                    raise PermissionError('Institutional license listener did not become ready')
                time.sleep(.05)
        model_env = dict(environment, MLM_LICENSE_FILE=plan['CRYOSTACK_LT_PORT']+'@127.0.0.1')
        yield model_env, (plan['CRYOSTACK_LT_TOKEN'].encode(),)
    finally:
        for process in reversed(processes):
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                # The disposable container also owns listener lifetime. Do
                # not let a process-exit race skip capability revocation.
                pass
        if issued:
            try:
                transfer(spec['origin'], spec['reservation'], 'license-release', token, byte_limit=1024)
            except Exception:
                # Gateway cancellation/settlement also revokes; relay TTL is at
                # most the reviewed task timeout, never extended on retry.
                pass


def main():
    environment = dict(os.environ)
    assert_no_task_credentials(environment)
    if os.geteuid() != 0:
        raise PermissionError('Pilot worker requires the reviewed disposable container supervisor')
    raw_spec = environment['CRYOSTACK_PILOT_SPEC']
    if len(raw_spec) > 4096:
        raise ValueError('Pilot specification exceeds its allowance')
    spec = json.loads(raw_spec)
    expected = {'origin', 'reservation', 'input_sha256', 'script_sha256', 'seconds', 'model'}
    if set(spec) not in (expected, expected | {'license_runtime_sha256'}):
        raise ValueError('Unexpected pilot specification fields')
    model = spec['model']
    if model not in MODEL_SCRIPT:
        raise PermissionError('Only Icepack and ISSM are supported by this worker')
    if 'license_runtime_sha256' in spec and (model != 'issm' or not isinstance(spec['license_runtime_sha256'], str)
            or not re.fullmatch('[a-f0-9]{64}', spec['license_runtime_sha256'])):
        raise PermissionError('Only reviewed ISSM tasks may request a license tunnel')
    if any(not environment.get(name) for name in MODEL_SECRET_ENV.get(model, ())):
        raise PermissionError('The model license was not delivered to this task')
    if (type(spec['seconds']) is not int or not 1 <= spec['seconds'] <= 600
            or any(not isinstance(spec[k], str) or not re.fullmatch('[a-f0-9]{64}', spec[k])
                   for k in ('input_sha256', 'script_sha256'))):
        raise ValueError('Invalid reviewed runtime or source hashes')
    token = environment['CRYOSTACK_TRANSFER_TOKEN']
    if not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', token):
        raise ValueError('Invalid private transfer capability')
    data = transfer(spec['origin'], spec['reservation'], 'input', token)
    if hashlib.sha256(data).hexdigest() != spec['input_sha256']:
        raise ValueError('Input archive differs from the reviewed bytes')
    with tempfile.TemporaryDirectory(prefix='cryostack-pilot-') as private:
        private = Path(private)
        private.chmod(0o711)  # child may traverse, not list/read supervisor files
        work = safe_extract(data, private / 'model')
        script = work / MODEL_SCRIPT[model]
        if hashlib.sha256(script.read_bytes()).hexdigest() != spec['script_sha256']:
            raise ValueError('Model script differs from the reviewed bytes')
        if model == 'issm':
            command = ['bash', str(work / ISSM_RUNNER)]
        else:
            # The supervisor uses the base Python. The qualified image keeps
            # Firedrake, PETSc and Icepack in its model-specific environment.
            command = ['/usr/local/bin/with-icepack', 'python',
                       str(work / 'cryostack_icepack_runner.py'),
                       str(script), str(work)]
        with supervisor_license(spec, token, environment, private) as (model_environment, private_values):
            receipt = run_science(command, work, seconds=spec['seconds'], environment=model_environment,
                                 private_values=(token.encode(), *private_values,
                                     *(environment[k].encode() for k in MODEL_SECRET_ENV.get(model, ()) if environment.get(k))), model=model)
        archive = package_outputs(work / 'outputs', private / 'output.zip', receipt)
        transfer(spec['origin'], spec['reservation'], 'output', token,
                 data=archive.read_bytes(), byte_limit=1024**2)
        return receipt['exit_code']


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        # Detailed exception strings may contain a capability or signed URL.
        print('Pilot worker refused execution:', type(error).__name__, file=sys.stderr)
        raise SystemExit(70)
