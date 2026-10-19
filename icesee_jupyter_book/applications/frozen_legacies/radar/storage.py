"""Storage providers for Frozen Legacies data sources.

A *data source* is an external storage location holding radar files. Frozen
Legacies reads it only through :class:`RadarStorageProvider`, addressing
objects by **storage keys** -- relative, ``/``-separated names inside the
source (``tiff/F127/F127-C0471_C0483.tiff``). Keys are internal: they are
never sent to ordinary clients.

The contract (shared by every provider):

``list(prefix, suffixes)``
    All objects under a prefix as :class:`StorageObject` (key, size, mtime,
    etag). Providers page internally; callers just iterate.
``stat(key)`` / ``exists(key)``
    Metadata of one object, or ``None``.
``open_stream(key)``  (capability ``stream``)
    A readable binary stream of the whole object.
``read_range(key, offset, length)``  (capability ``range_read``)
    Part of an object -- enough to read a TIFF header without downloading
    the image (see :class:`RangeReader`).
``check()``
    Connection test (``{"ok", "message"}``, never secrets).
``describe()``
    A non-sensitive description for maintainers (location masked).

Capabilities are declared in :attr:`RadarStorageProvider.capabilities`:
``list``, ``stat``, ``stream``, ``range_read``, ``local_files`` (objects are
already files on this server), ``change_tracking`` (the provider can report
changes since a token; none implement it yet).

Application code never receives a local path from a provider. Files reach
the pickers only through :mod:`radar.working_cache`, which materializes an
object into a bounded local working copy -- or, for ``local_files``
providers, uses the file in place (:meth:`LocalProvider.local_file` is for the
cache only).

Implemented:

* ``local`` -- a directory on the server or a mounted archive, inside an
  operator-approved storage root (``$CRYOSTACK_FROZEN_LEGACIES_STORAGE_ROOTS``);
* ``cedar`` -- Georgia Tech CEDAR research storage mounted on the server
  (NFS); read like ``local`` inside an approved storage root, and refused
  unless the directory is on a mounted network filesystem;
* ``s3`` -- read-only Amazon S3 (or an approved S3-compatible endpoint),
  inside an operator-approved bucket/prefix
  (``$CRYOSTACK_FROZEN_LEGACIES_S3_ALLOWED``). Credentials come only from the
  server's AWS credential chain (instance/task IAM role, or the standard
  environment / shared configuration of the service account); a data source
  never carries credentials.

Google Drive, OneDrive/SharePoint and Dropbox are implemented as read-only
providers. They are enabled only when their SDK, server-held workload
credentials and operator allow-list are all present. Data-source records never
contain credentials.
"""
from __future__ import annotations

import io
import importlib.util
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator


STORAGE_ROOTS_ENV = "CRYOSTACK_FROZEN_LEGACIES_STORAGE_ROOTS"
S3_ALLOWED_ENV = "CRYOSTACK_FROZEN_LEGACIES_S3_ALLOWED"
S3_ENDPOINTS_ENV = "CRYOSTACK_FROZEN_LEGACIES_S3_ENDPOINTS"
PROVIDERS = ("local", "s3", "cedar", "gdrive", "onedrive", "dropbox")
CLOUD_PROVIDERS = ("gdrive", "onedrive", "dropbox")
PLANNED_PROVIDERS = CLOUD_PROVIDERS
#: what each planned provider still needs before it can be implemented
#: (reported to maintainers; nothing here is a working connector)
PLANNED_REQUIREMENTS = {
    "gdrive": ["a Google Cloud service account (workload identity) with read access to the "
               "shared drive", "the google-api-python-client package on the server",
               "a fake or recorded Drive API for automated tests",
               "operator allow-list CRYOSTACK_FROZEN_LEGACIES_GDRIVE_ALLOWED"],
    "onedrive": ["a Microsoft Entra application with Sites.Selected/Files.Read.All granted "
                 "for the SharePoint site", "the msal package on the server",
                 "a fake or recorded Microsoft Graph API for automated tests",
                 "operator allow-list CRYOSTACK_FROZEN_LEGACIES_ONEDRIVE_ALLOWED"],
    "dropbox": ["a Dropbox team app with files.content.read and a server-held refresh token "
                "(never in a data source)", "the dropbox package on the server",
                "a fake or recorded Dropbox API for automated tests",
                "an operator allow-list of team folders"],
}
#: filesystem types accepted as network-attached research storage (CEDAR)
NETWORK_FSTYPES = frozenset({"nfs", "nfs4", "cifs", "smb3", "smbfs"})
DRIVE_ALLOWED_ENV = {"gdrive": "CRYOSTACK_FROZEN_LEGACIES_GDRIVE_ALLOWED",
                     "onedrive": "CRYOSTACK_FROZEN_LEGACIES_ONEDRIVE_ALLOWED",
                     "dropbox": "CRYOSTACK_FROZEN_LEGACIES_DROPBOX_ALLOWED"}
CAPABILITIES = ("list", "stat", "stream", "range_read", "local_files", "change_tracking")

_KEY_SEGMENT = re.compile(r"[^\x00-\x1f\x7f/\\]{1,255}")


class StorageError(RuntimeError):
    """The storage location could not be read (possibly temporarily)."""


class StorageKeyError(ValueError):
    """A storage key is malformed or escapes its data source."""


@dataclass(frozen=True)
class StorageObject:
    key: str
    size: int
    mtime_ns: int
    etag: str | None = None

    @property
    def version(self) -> str:
        """Identifies this content of the object (ETag, else size + mtime)."""
        return self.etag or f"{self.size}-{self.mtime_ns}"


def normalize_key(key: object) -> str:
    """A safe relative storage key (no absolute paths, ``..`` or control chars)."""
    if not isinstance(key, str):
        raise StorageKeyError("Storage keys are strings.")
    parts = key.split("/")
    if not key or len(key) > 1024 or any(
        p in ("", ".", "..") or not _KEY_SEGMENT.fullmatch(p) for p in parts
    ):
        raise StorageKeyError(f"Unsafe storage key: {key!r}")
    return key


def approved_roots() -> list[Path]:
    raw = os.environ.get(STORAGE_ROOTS_ENV, "")
    return [Path(p).expanduser().resolve() for p in raw.split(os.pathsep) if p.strip()]


def mask_location(location: str) -> str:
    """Show the last two segments of a storage location only."""
    parts = [p for p in str(location or "").replace("\\", "/").split("/") if p]
    if len(parts) <= 2:
        return "/".join(parts) or "—"
    return "…/" + "/".join(parts[-2:])


class RadarStorageProvider(ABC):
    """Read-only access to one data source."""

    provider: str = "base"
    capabilities: frozenset = frozenset()

    @abstractmethod
    def list(self, prefix: str = "", *, suffixes: tuple[str, ...] = ()) -> Iterator[StorageObject]:
        """Objects under ``prefix`` (recursively), optionally by suffix."""

    @abstractmethod
    def stat(self, key: str) -> StorageObject | None:
        """Metadata of one object, or ``None`` when it does not exist."""

    def exists(self, key: str) -> bool:
        return self.stat(key) is not None

    def open_stream(self, key: str) -> BinaryIO:
        raise StorageError(f"The {self.provider} provider cannot stream objects.")

    def read_range(self, key: str, offset: int, length: int) -> bytes:
        raise StorageError(f"The {self.provider} provider cannot read ranges.")

    def read_bytes(self, key: str, *, limit: int) -> bytes:
        """A small object in full (navigation files), refusing larger ones."""
        obj = self.stat(key)
        if obj is None:
            raise StorageError("The object is not available.")
        if obj.size > limit:
            raise StorageError("The object is too large to read in full.")
        with self.open_stream(key) as stream:
            return stream.read(limit + 1)[:limit]

    @abstractmethod
    def check(self) -> dict:
        """Connection test: ``{"ok": bool, "message": str}`` (no secrets)."""

    @abstractmethod
    def describe(self) -> dict:
        """Non-sensitive description for maintainers."""


class RangeReader(io.RawIOBase):
    """A seekable read-only stream over :meth:`RadarStorageProvider.read_range`,
    with a small block cache, so header parsers can read a remote object
    without downloading it."""

    BLOCK = 64 * 1024

    def __init__(self, provider: RadarStorageProvider, key: str, size: int):
        self.provider, self.key, self.size = provider, key, size
        self.position = 0
        self.blocks: dict[int, bytes] = {}
        self.bytes_read = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=io.SEEK_SET):
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self.position, io.SEEK_END: self.size}[whence]
        self.position = max(0, base + offset)
        return self.position

    def _block(self, index: int) -> bytes:
        if index not in self.blocks:
            if len(self.blocks) > 64:
                self.blocks.clear()
            data = self.provider.read_range(self.key, index * self.BLOCK, self.BLOCK)
            self.bytes_read += len(data)
            self.blocks[index] = data
        return self.blocks[index]

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.position
        out = bytearray()
        while n > 0 and self.position < self.size:
            index, within = divmod(self.position, self.BLOCK)
            chunk = self._block(index)[within:within + n]
            if not chunk:
                break
            out += chunk
            self.position += len(chunk)
            n -= len(chunk)
        return bytes(out)

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)


class LocalProvider(RadarStorageProvider):
    """The reference provider: a directory on the server inside an approved
    storage root. It supports every capability except change tracking."""

    provider = "local"
    capabilities = frozenset({"list", "stat", "stream", "range_read", "local_files"})

    def __init__(self, root: str | Path, *, roots: list[Path] | None = None):
        self._root = Path(root).expanduser().resolve()
        allowed = approved_roots() if roots is None else [Path(r).resolve() for r in roots]
        if not any(self._root == r or self._root.is_relative_to(r) for r in allowed):
            raise StorageKeyError(
                "This directory is not inside an approved Frozen Legacies storage root.")

    def _path(self, key: str) -> Path:
        path = (self._root / normalize_key(key)).resolve()
        if not path.is_relative_to(self._root):
            raise StorageKeyError("Storage key escapes the data source.")
        return path

    def _object(self, path: Path) -> StorageObject:
        stat = path.stat()
        return StorageObject(key=path.relative_to(self._root).as_posix(),
                             size=stat.st_size, mtime_ns=stat.st_mtime_ns)

    def list(self, prefix: str = "", *, suffixes: tuple[str, ...] = ()):
        if not self._root.is_dir():
            raise StorageError("The data source directory is not available.")
        base = self._path(prefix) if prefix else self._root
        if not base.is_dir():
            return
        lowered = tuple(s.lower() for s in suffixes)

        def failed(error):
            raise StorageError("Part of the data source could not be listed.")

        for directory, dirnames, filenames in os.walk(base, followlinks=False, onerror=failed):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames):
                if name.startswith(".") or (lowered and not name.lower().endswith(lowered)):
                    continue
                path = Path(directory) / name
                if path.is_symlink() or not path.is_file():
                    continue
                try:
                    yield self._object(path)
                except OSError:
                    continue

    def stat(self, key: str) -> StorageObject | None:
        try:
            path = self._path(key)
        except StorageKeyError:
            return None
        if path.is_symlink() or not path.is_file():
            return None
        return self._object(path)

    def open_stream(self, key: str):
        try:
            return self._path(key).open("rb")
        except OSError:
            raise StorageError("The object could not be opened.")

    def read_range(self, key: str, offset: int, length: int) -> bytes:
        with self.open_stream(key) as handle:
            handle.seek(offset)
            return handle.read(length)

    def local_file(self, key: str) -> Path | None:
        """The object as a file on this server (for the working cache only)."""
        try:
            path = self._path(key)
        except StorageKeyError:
            return None
        return path if path.is_file() and not path.is_symlink() else None

    def check(self) -> dict:
        if not self._root.is_dir():
            return {"ok": False, "message": "The directory is not available on the server."}
        if not os.access(self._root, os.R_OK | os.X_OK):
            return {"ok": False, "message": "The server cannot read the directory."}
        return {"ok": True, "message": "The directory is readable."}

    def describe(self) -> dict:
        return {"provider": self.provider, "location": mask_location(str(self._root)),
                "capabilities": sorted(self.capabilities)}


# ── S3 ───────────────────────────────────────────────────────────────
_BUCKET = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]")
_REGION = re.compile(r"[a-z]{2}(-[a-z]+)+-\d")
_ENDPOINT_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
#: configuration keys that would mean a credential is being configured
_CREDENTIAL_WORDS = ("key", "secret", "token", "password", "credential", "session")
_MISSING_CODES = {"404", "NoSuchKey", "NotFound"}
_DENIED_CODES = {"403", "AccessDenied", "AllAccessDisabled", "InvalidAccessKeyId",
                 "SignatureDoesNotMatch", "ExpiredToken", "InvalidToken", "AccountProblem"}


def _s3_allowed() -> list[tuple[str, str]]:
    """Approved (bucket, prefix) pairs: ``bucket`` or ``bucket/prefix``, comma- or
    space-separated."""
    out = []
    for item in re.split(r"[,\s]+", os.environ.get(S3_ALLOWED_ENV, "")):
        item = item.strip().strip("/")
        if not item:
            continue
        bucket, _, prefix = item.partition("/")
        out.append((bucket, prefix.strip("/")))
    return out


def _s3_endpoints() -> dict[str, str]:
    """Approved S3-compatible endpoints: ``name=https://host,…`` (operator only)."""
    out = {}
    for item in re.split(r"[,\s]+", os.environ.get(S3_ENDPOINTS_ENV, "")):
        name, _, url = item.partition("=")
        if name and url:
            out[name.strip()] = url.strip()
    return out


def s3_approvals() -> list[tuple[str, str]]:
    """The operator's approved (bucket, prefix) pairs (public: no credentials)."""
    return _s3_allowed()


def s3_endpoint_names() -> list[str]:
    """Names of the approved S3-compatible endpoints; their URLs stay on the server."""
    return list(_s3_endpoints())


def _error_code(error) -> str | None:
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        code = (response.get("Error") or {}).get("Code")
        status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
        return str(code or status or "") or None
    return None


_TRANSIENT_CODES = {"500", "502", "503", "504", "InternalError", "ServiceUnavailable",
                    "SlowDown", "RequestTimeout", "Throttling", "ThrottlingException"}
_NO_CREDENTIALS = {"NoCredentialsError", "PartialCredentialsError", "CredentialRetrievalError",
                   "NoAuthTokenError", "UnauthorizedSSOTokenError"}


def _s3_error(error, *, what: str) -> StorageError:
    if type(error).__name__ in _NO_CREDENTIALS:
        return StorageError("The server has no usable AWS credentials for S3 (configure an "
                            "IAM role or the AWS default credential chain on the server).")
    code = _error_code(error)
    if code in _DENIED_CODES:
        return StorageError(f"Access denied by S3 while trying to {what}; check the "
                            "server's IAM permissions.")
    response = getattr(error, "response", None)
    status = ((response or {}).get("ResponseMetadata") or {}).get("HTTPStatusCode") \
        if isinstance(response, dict) else None
    if code in _TRANSIENT_CODES or (isinstance(status, int) and status >= 500):
        return StorageError(f"S3 is temporarily unavailable ({code}); try again later.")
    if code:
        return StorageError(f"S3 refused to {what} ({code}).")
    return StorageError(f"S3 is temporarily unavailable ({type(error).__name__}).")


class _S3Stream(io.RawIOBase):
    """An S3 object body as a readable stream; transfer errors become
    :class:`StorageError` so callers can retry or report them."""

    def __init__(self, body):
        self.body = body

    def readable(self):
        return True

    def read(self, n=-1):
        try:
            return self.body.read() if n is None or n < 0 else self.body.read(n)
        except Exception as error:
            raise StorageError(f"The S3 transfer was interrupted ({type(error).__name__}).")

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)

    def close(self):
        try:
            self.body.close()
        except Exception:
            pass
        super().close()


class S3Provider(RadarStorageProvider):
    """Read-only S3 data source (``s3://bucket/prefix``).

    Uses only ``ListBucket`` (paginated, under the prefix), ``HeadObject`` and
    ``GetObject`` (whole or ranged). Credentials are resolved by the AWS SDK's
    default chain on the server; nothing is stored. A 403 is reported as
    access denied -- never as a missing object.
    """

    provider = "s3"
    capabilities = frozenset({"list", "stat", "stream", "range_read"})
    #: parallel header reads while indexing (the client is thread-safe)
    header_concurrency = 16

    def __init__(self, config: dict, *, client=None):
        validate_s3_config(config)
        self.bucket = config["bucket"]
        self.prefix = (config.get("prefix") or "").strip("/")
        self.region = config.get("region") or None
        self.endpoint = config.get("endpoint") or None
        self._client = client

    @property
    def client(self):
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError:
                raise StorageError("S3 support needs the boto3 package on the server.")
            endpoint_url = _s3_endpoints().get(self.endpoint) if self.endpoint else None
            self._client = boto3.session.Session().client(
                "s3", region_name=self.region, endpoint_url=endpoint_url,
                config=Config(retries={"max_attempts": 5, "mode": "standard"},
                              connect_timeout=10, read_timeout=60,
                              max_pool_connections=32,
                              # S3-compatible endpoints (MinIO, Ceph) expect path-style URLs
                              s3={"addressing_style": "path"} if endpoint_url else None))
        return self._client

    def _full(self, key: str) -> str:
        key = normalize_key(key)
        return f"{self.prefix}/{key}" if self.prefix else key

    def _relative(self, full_key: str) -> str | None:
        if self.prefix:
            if not full_key.startswith(self.prefix + "/"):
                return None
            full_key = full_key[len(self.prefix) + 1:]
        try:
            return normalize_key(full_key)
        except StorageKeyError:
            return None                      # folder markers, odd keys: skipped

    @staticmethod
    def _object(key: str, size: int, modified, etag) -> StorageObject:
        mtime_ns = int(modified.timestamp() * 1_000_000_000) if modified is not None else 0
        return StorageObject(key=key, size=int(size), mtime_ns=mtime_ns,
                             etag=(etag or "").strip('"') or None)

    def list(self, prefix: str = "", *, suffixes: tuple[str, ...] = ()):
        base = self._full(prefix) + "/" if prefix else (self.prefix + "/" if self.prefix else "")
        lowered = tuple(x.lower() for x in suffixes)
        try:
            pages = self.client.get_paginator("list_objects_v2").paginate(
                Bucket=self.bucket, Prefix=base, PaginationConfig={"PageSize": 1000})
            for page in pages:
                for item in page.get("Contents") or []:
                    key = self._relative(item["Key"])
                    if key is None or key.rsplit("/", 1)[-1].startswith("."):
                        continue
                    if lowered and not key.lower().endswith(lowered):
                        continue
                    yield self._object(key, item.get("Size", 0), item.get("LastModified"),
                                       item.get("ETag"))
        except StorageError:
            raise
        except Exception as error:
            raise _s3_error(error, what="list the data source")

    def stat(self, key: str) -> StorageObject | None:
        try:
            full = self._full(key)
        except StorageKeyError:
            return None
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=full)
        except Exception as error:
            if _error_code(error) in _MISSING_CODES:
                return None
            raise _s3_error(error, what="read object metadata")
        return self._object(key, head.get("ContentLength", 0), head.get("LastModified"),
                            head.get("ETag"))

    def open_stream(self, key: str):
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self._full(key))
        except Exception as error:
            if _error_code(error) in _MISSING_CODES:
                raise StorageError("The object is no longer in the data source.")
            raise _s3_error(error, what="read an object")
        return _S3Stream(response["Body"])

    def read_range(self, key: str, offset: int, length: int) -> bytes:
        if length <= 0:
            return b""
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self._full(key),
                                              Range=f"bytes={offset}-{offset + length - 1}")
        except Exception as error:
            code = _error_code(error)
            if code in ("InvalidRange", "416"):
                return b""
            if code in _MISSING_CODES:
                raise StorageError("The object is no longer in the data source.")
            raise _s3_error(error, what="read part of an object")
        stream = _S3Stream(response["Body"])
        try:
            return stream.read()
        finally:
            stream.close()

    def check(self) -> dict:
        try:
            self.client.list_objects_v2(Bucket=self.bucket,
                                        Prefix=(self.prefix + "/") if self.prefix else "",
                                        MaxKeys=1)
        except StorageError as error:
            return {"ok": False, "message": str(error)}
        except Exception as error:
            return {"ok": False, "message": str(_s3_error(error, what="list the data source"))}
        return {"ok": True, "message": "The bucket prefix can be listed with the server's "
                                       "AWS credentials."}

    def describe(self) -> dict:
        where = f"s3://{self.bucket}/{self.prefix}".rstrip("/")
        return {"provider": self.provider, "location": mask_location(where),
                "capabilities": sorted(self.capabilities),
                "endpoint": self.endpoint or "aws"}


def validate_s3_config(config: dict) -> dict:
    """Reject S3 configurations outside the operator's approvals, or carrying
    anything that looks like a credential."""
    for key in config:
        if any(word in str(key).lower() for word in _CREDENTIAL_WORDS):
            raise StorageKeyError("Data sources never carry credentials; the server's AWS "
                                  "credential chain is used.")
    bucket = str(config.get("bucket") or "")
    prefix = str(config.get("prefix") or "").strip("/")
    if not _BUCKET.fullmatch(bucket) or ".." in bucket:
        raise StorageKeyError("Invalid S3 bucket name.")
    if prefix:
        normalize_key(prefix)
    region = config.get("region")
    if region and not _REGION.fullmatch(str(region)):
        raise StorageKeyError("Invalid AWS region.")
    endpoint = config.get("endpoint")
    if endpoint and (not _ENDPOINT_NAME.fullmatch(str(endpoint))
                     or endpoint not in _s3_endpoints()):
        raise StorageKeyError("This S3 endpoint is not approved on this server.")
    allowed = _s3_allowed()
    if not any(bucket == b and (not p or prefix == p or prefix.startswith(p + "/"))
               for b, p in allowed):
        raise StorageKeyError("This bucket/prefix is not approved for Frozen Legacies "
                              f"on this server ({S3_ALLOWED_ENV}).")
    return {"bucket": bucket, "prefix": prefix, "region": region or None,
            "endpoint": endpoint or None}


# ── cloud drives (planned; not available) ───────────────────────────
_DRIVE_ID = re.compile(r"[A-Za-z0-9!_-]{1,128}")


def _drive_allowed(provider: str) -> set[str]:
    raw = os.environ.get(DRIVE_ALLOWED_ENV[provider], "")
    return {item.strip() for item in re.split(r"[,\s]+", raw) if item.strip()}


def cloud_provider_status() -> list[dict]:
    """Return non-secret SDK, credential, and allow-list readiness."""
    modules = {"gdrive": "googleapiclient", "onedrive": "msal", "dropbox": "dropbox"}
    credentials = {
        "gdrive": ("GOOGLE_APPLICATION_CREDENTIALS",),
        "onedrive": ("CRYOSTACK_FROZEN_LEGACIES_ONEDRIVE_TENANT_ID",
                     "CRYOSTACK_FROZEN_LEGACIES_ONEDRIVE_CLIENT_ID",
                     "CRYOSTACK_FROZEN_LEGACIES_ONEDRIVE_CLIENT_SECRET"),
        "dropbox": ("CRYOSTACK_FROZEN_LEGACIES_DROPBOX_REFRESH_TOKEN",
                    "CRYOSTACK_FROZEN_LEGACIES_DROPBOX_APP_KEY",
                    "CRYOSTACK_FROZEN_LEGACIES_DROPBOX_APP_SECRET"),
    }
    out = []
    for provider in CLOUD_PROVIDERS:
        try:
            sdk = importlib.util.find_spec(modules[provider]) is not None
        except (ImportError, ModuleNotFoundError):
            sdk = False
        approved = sorted(_drive_allowed(provider))
        credential_ready = all(bool((os.environ.get(name) or "").strip())
                               for name in credentials[provider])
        missing = []
        if not sdk: missing.append("provider SDK")
        if not credential_ready: missing.append("server workload credentials")
        if not approved: missing.append(f"operator allow-list {DRIVE_ALLOWED_ENV[provider]}")
        out.append({"provider": provider, "configured": not missing, "sdk": sdk,
                    "credentials": credential_ready, "approved": approved,
                    "missing": missing})
    return out


def validate_drive_config(provider: str, config: dict) -> dict:
    """The configuration rules a Google Drive / OneDrive provider must follow.

    A drive source names a shared drive (``drive_id``) and a folder inside it
    (``folder_id`` for Google Drive, ``folder`` path for OneDrive/SharePoint);
    the drive must be on the operator's allow-list
    (``$CRYOSTACK_FROZEN_LEGACIES_GDRIVE_ALLOWED`` /
    ``$CRYOSTACK_FROZEN_LEGACIES_ONEDRIVE_ALLOWED``), and the server's own
    workload identity would be used -- a data source never carries tokens.
    Validation only: there is no provider behind it yet.
    """
    if provider not in PLANNED_PROVIDERS:
        raise StorageKeyError(f"{provider!r} is not a cloud-drive provider.")
    for key in config:
        if any(word in str(key).lower() for word in _CREDENTIAL_WORDS + ("client",)):
            raise StorageKeyError("Data sources never carry credentials.")
    drive_id = str(config.get("drive_id") or "")
    if not _DRIVE_ID.fullmatch(drive_id):
        raise StorageKeyError("Invalid drive ID.")
    if provider == "gdrive":
        folder = str(config.get("folder_id") or "")
        if not _DRIVE_ID.fullmatch(folder):
            raise StorageKeyError("Invalid folder ID.")
        location = {"drive_id": drive_id, "folder_id": folder}
    else:
        folder = str(config.get("folder") or "").strip("/")
        if folder:
            normalize_key(folder)
        location = {"drive_id": drive_id, "folder": folder}
    if drive_id not in _drive_allowed(provider):
        raise StorageKeyError("This drive is not approved for Frozen Legacies on this server "
                              f"({DRIVE_ALLOWED_ENV[provider]}).")
    return location


def mount_of(path: Path) -> dict | None:
    """The mount holding ``path`` (``{"fstype", "mountpoint"}``) from
    ``/proc/self/mountinfo``; ``None`` where that is unavailable."""
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    best = None
    resolved = Path(path).resolve()
    for line in lines:
        left, _sep, right = line.partition(" - ")
        fields, tail = left.split(), right.split()
        if len(fields) < 5 or not tail:
            continue
        mountpoint = Path(fields[4].replace("\\040", " "))
        if resolved == mountpoint or resolved.is_relative_to(mountpoint):
            if best is None or len(str(mountpoint)) > len(str(best["mountpoint"])):
                best = {"mountpoint": mountpoint, "fstype": tail[0]}
    return best


class CedarProvider(LocalProvider):
    """Georgia Tech CEDAR research storage, mounted on this server.

    CEDAR ("Cost-Effective Data Access for Research") is campus network
    storage mounted over NFS (here ``cedar-cos.nas.gatech.edu`` at
    ``/projects/<lab>``); there is no CEDAR cloud API. It is therefore read
    like a local directory -- inside an operator-approved storage root -- with
    one extra rule: the directory must be on a network filesystem, so a local
    folder cannot pose as CEDAR and an unmounted CEDAR path (an empty local
    directory) is reported instead of indexed as empty."""

    provider = "cedar"

    def _mount(self) -> dict | None:
        return mount_of(self._root)

    def _require_mount(self) -> dict:
        mount = self._mount()
        if mount is None or mount["fstype"] not in NETWORK_FSTYPES:
            raise StorageError("The CEDAR directory is not on a mounted network filesystem "
                               "(is CEDAR mounted on this server?).")
        return mount

    def list(self, prefix: str = "", *, suffixes: tuple[str, ...] = ()):
        self._require_mount()
        yield from super().list(prefix, suffixes=suffixes)

    def check(self) -> dict:
        try:
            mount = self._require_mount()
        except StorageError as error:
            return {"ok": False, "message": str(error)}
        result = super().check()
        if result.get("ok"):
            result["message"] = (f"{result.get('message') or 'Readable.'} "
                                 f"CEDAR network filesystem ({mount['fstype']}).").strip()
        return result


def provider_for(provider: str, config: dict) -> RadarStorageProvider:
    """Build the provider of a data source from its (non-secret) configuration."""
    if provider == "local":
        return LocalProvider(config.get("root") or "")
    if provider == "cedar":
        return CedarProvider(config.get("root") or "")
    if provider == "s3":
        return S3Provider(config)
    if provider in CLOUD_PROVIDERS:
        config = validate_drive_config(provider, config)
        from .cloud_storage import DropboxProvider, GoogleDriveProvider, OneDriveProvider
        return {"gdrive": GoogleDriveProvider, "onedrive": OneDriveProvider,
                "dropbox": DropboxProvider}[provider](config)
    raise StorageError(f"Storage provider {provider!r} is not supported on this server.")
