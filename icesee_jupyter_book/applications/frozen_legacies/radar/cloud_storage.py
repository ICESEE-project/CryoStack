"""Read-only cloud-drive providers with server-held credentials.

Data-source rows contain only approved drive/folder identifiers. OAuth client
secrets, refresh tokens, and workload credentials remain in the gateway
environment and are never returned by these classes.
"""
from __future__ import annotations

import io
import os
from datetime import datetime

from .storage import (RadarStorageProvider, StorageError, StorageObject,
                      normalize_key, mask_location)


def _time_ns(value) -> int:
    if not value:
        return 0
    if isinstance(value, datetime):
        return int(value.timestamp() * 1_000_000_000)
    return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
               * 1_000_000_000)


class _ResponseStream(io.RawIOBase):
    def __init__(self, response):
        self.response = response

    def readable(self): return True

    def read(self, n=-1):
        try:
            return self.response.raw.read() if n is None or n < 0 else self.response.raw.read(n)
        except Exception as error:
            raise StorageError(f"The cloud transfer was interrupted ({type(error).__name__}).")

    def readinto(self, buffer):
        data = self.read(len(buffer)); buffer[:len(data)] = data; return len(data)

    def close(self):
        try: self.response.close()
        finally: super().close()


class _RangeStream(io.RawIOBase):
    """Bounded lazy stream assembled from provider range requests."""

    def __init__(self, provider, key, size, chunk_size=8 * 1024 * 1024):
        self.provider, self.key = provider, key
        self.size, self.chunk_size, self.position = int(size), int(chunk_size), 0

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.position

    def seek(self, offset, whence=io.SEEK_SET):
        target = offset if whence == io.SEEK_SET else (
            self.position + offset if whence == io.SEEK_CUR else self.size + offset)
        if target < 0: raise ValueError("negative seek position")
        self.position = min(target, self.size); return self.position

    def read(self, n=-1):
        if self.position >= self.size: return b""
        remaining = self.size - self.position if n is None or n < 0 else min(n, self.size - self.position)
        chunks = []
        while remaining:
            requested = min(remaining, self.chunk_size)
            data = self.provider.read_range(self.key, self.position, requested)
            if not data: break
            chunks.append(data); self.position += len(data); remaining -= len(data)
            if len(data) < requested: break
        return b"".join(chunks)

    def readinto(self, buffer):
        data = self.read(len(buffer)); buffer[:len(data)] = data; return len(data)


class GoogleDriveProvider(RadarStorageProvider):
    provider = "gdrive"
    capabilities = frozenset({"list", "stat", "stream", "range_read"})
    header_concurrency = 8

    def __init__(self, config: dict, *, service=None):
        self.drive_id = config["drive_id"]
        self.folder_id = config["folder_id"]
        self._service = service
        self._files = None

    @property
    def service(self):
        if self._service is None:
            try:
                import google.auth
                from googleapiclient.discovery import build
                credentials, _ = google.auth.default(scopes=[
                    "https://www.googleapis.com/auth/drive.readonly"])
                self._service = build("drive", "v3", credentials=credentials,
                                      cache_discovery=False)
            except Exception as error:
                raise StorageError("Google Drive workload credentials are unavailable "
                                   f"({type(error).__name__}).")
        return self._service

    def _inventory(self, refresh=False):
        if self._files is not None and not refresh:
            return self._files
        found, queue = {}, [(self.folder_id, "")]
        try:
            while queue:
                parent, base = queue.pop(0); token = None
                while True:
                    result = self.service.files().list(
                        q=f"'{parent}' in parents and trashed = false",
                        corpora="drive", driveId=self.drive_id, includeItemsFromAllDrives=True,
                        supportsAllDrives=True, pageSize=1000, pageToken=token,
                        fields="nextPageToken,files(id,name,mimeType,size,modifiedTime,md5Checksum)"
                    ).execute()
                    for item in result.get("files") or []:
                        name = str(item.get("name") or "").replace("/", "_")
                        key = normalize_key(f"{base}/{name}".strip("/"))
                        if item.get("mimeType") == "application/vnd.google-apps.folder":
                            queue.append((item["id"], key)); continue
                        found[key] = (item["id"], StorageObject(
                            key=key, size=int(item.get("size") or 0),
                            mtime_ns=_time_ns(item.get("modifiedTime")),
                            etag=item.get("md5Checksum") or item.get("id")))
                    token = result.get("nextPageToken")
                    if not token: break
        except StorageError: raise
        except Exception as error:
            raise StorageError(f"Google Drive could not be listed ({type(error).__name__}).")
        self._files = found
        return found

    def list(self, prefix="", *, suffixes=()):
        prefix = prefix.strip("/"); lowered = tuple(x.lower() for x in suffixes)
        for key, (_id, obj) in sorted(self._inventory(refresh=True).items()):
            if prefix and key != prefix and not key.startswith(prefix + "/"): continue
            if lowered and not key.lower().endswith(lowered): continue
            yield obj

    def stat(self, key):
        pair = self._inventory().get(normalize_key(key)); return pair[1] if pair else None

    def read_range(self, key, offset, length):
        if length <= 0: return b""
        pair = self._inventory().get(normalize_key(key))
        if not pair: raise StorageError("The file is no longer in Google Drive.")
        try:
            request = self.service.files().get_media(fileId=pair[0], supportsAllDrives=True)
            request.headers["Range"] = f"bytes={offset}-{offset + length - 1}"
            return request.execute()
        except Exception as error:
            raise StorageError(f"Google Drive could not read the file ({type(error).__name__}).")

    def open_stream(self, key):
        obj = self.stat(key)
        if obj is None: raise StorageError("The file is no longer in Google Drive.")
        return _RangeStream(self, key, obj.size)

    def check(self):
        try: next(iter(self.list()), None)
        except StorageError as error: return {"ok": False, "message": str(error)}
        return {"ok": True, "message": "The approved Google Drive folder is readable."}

    def describe(self):
        return {"provider": self.provider, "location": mask_location(self.drive_id),
                "capabilities": sorted(self.capabilities)}


class OneDriveProvider(RadarStorageProvider):
    provider = "onedrive"
    capabilities = frozenset({"list", "stat", "stream", "range_read"})
    header_concurrency = 8
    GRAPH = "https://graph.microsoft.com/v1.0"

    def __init__(self, config: dict, *, session=None, token=None):
        self.drive_id, self.folder = config["drive_id"], (config.get("folder") or "").strip("/")
        self._session, self._token, self._files = session, token, None

    @property
    def session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    def _access_token(self):
        if self._token: return self._token
        try:
            import msal
            tenant, client, secret = (os.environ.get(x, "") for x in (
                "CRYOSTACK_FROZEN_LEGACIES_ONEDRIVE_TENANT_ID",
                "CRYOSTACK_FROZEN_LEGACIES_ONEDRIVE_CLIENT_ID",
                "CRYOSTACK_FROZEN_LEGACIES_ONEDRIVE_CLIENT_SECRET"))
            if not all((tenant, client, secret)): raise ValueError("missing environment")
            result = msal.ConfidentialClientApplication(
                client, authority=f"https://login.microsoftonline.com/{tenant}",
                client_credential=secret).acquire_token_for_client(
                    scopes=["https://graph.microsoft.com/.default"])
            self._token = result.get("access_token")
            if not self._token: raise ValueError(result.get("error"))
            return self._token
        except Exception as error:
            raise StorageError(f"Microsoft workload credentials are unavailable ({type(error).__name__}).")

    def _get(self, url, *, headers=None, stream=False):
        hdr = {"Authorization": "Bearer " + self._access_token(), **(headers or {})}
        response = self.session.get(url, headers=hdr, timeout=60, stream=stream)
        if response.status_code == 404: return None
        if response.status_code >= 400:
            raise StorageError(f"Microsoft Graph refused the request (HTTP {response.status_code}).")
        return response

    def _inventory(self, refresh=False):
        if self._files is not None and not refresh: return self._files
        root = f"{self.GRAPH}/drives/{self.drive_id}/root"
        if self.folder: root += ":/" + self.folder + ":"
        queue, found = [(root, "")], {}
        while queue:
            parent, base = queue.pop(0); url = parent + "/children?$top=999"
            while url:
                response = self._get(url); body = response.json()
                for item in body.get("value") or []:
                    key = normalize_key(f"{base}/{str(item.get('name') or '').replace('/', '_')}".strip("/"))
                    item_url = f"{self.GRAPH}/drives/{self.drive_id}/items/{item['id']}"
                    if "folder" in item: queue.append((item_url, key)); continue
                    found[key] = (item["id"], StorageObject(
                        key, int(item.get("size") or 0), _time_ns(item.get("lastModifiedDateTime")),
                        item.get("eTag") or item.get("cTag") or item["id"]))
                url = body.get("@odata.nextLink")
        self._files = found; return found

    def list(self, prefix="", *, suffixes=()):
        prefix = prefix.strip("/"); lowered = tuple(x.lower() for x in suffixes)
        for key, (_id, obj) in sorted(self._inventory(refresh=True).items()):
            if prefix and key != prefix and not key.startswith(prefix + "/"): continue
            if lowered and not key.lower().endswith(lowered): continue
            yield obj

    def stat(self, key):
        pair = self._inventory().get(normalize_key(key)); return pair[1] if pair else None

    def _download(self, key, headers=None, stream=False):
        pair = self._inventory().get(normalize_key(key))
        if not pair: raise StorageError("The file is no longer in OneDrive.")
        return self._get(f"{self.GRAPH}/drives/{self.drive_id}/items/{pair[0]}/content",
                         headers=headers, stream=stream)

    def read_range(self, key, offset, length):
        if length <= 0: return b""
        return self._download(key, {"Range": f"bytes={offset}-{offset + length - 1}"}).content

    def open_stream(self, key): return _ResponseStream(self._download(key, stream=True))

    def check(self):
        try: next(iter(self.list()), None)
        except StorageError as error: return {"ok": False, "message": str(error)}
        return {"ok": True, "message": "The approved OneDrive or SharePoint folder is readable."}

    def describe(self):
        return {"provider": self.provider, "location": mask_location(self.drive_id),
                "capabilities": sorted(self.capabilities)}


class DropboxProvider(RadarStorageProvider):
    provider = "dropbox"
    # Dropbox's supported SDK download route is a stream, but does not expose
    # stable HTTP range semantics. Do not claim range reads: the working cache
    # downloads an object once instead of repeatedly discarding large prefixes.
    capabilities = frozenset({"list", "stat", "stream"})

    def __init__(self, config: dict, *, client=None):
        self.namespace, self.folder = config["drive_id"], (config.get("folder") or "").strip("/")
        self._client, self._files = client, None

    @property
    def client(self):
        if self._client is None:
            try:
                import dropbox
                token, key, secret = (os.environ.get(x, "") for x in (
                    "CRYOSTACK_FROZEN_LEGACIES_DROPBOX_REFRESH_TOKEN",
                    "CRYOSTACK_FROZEN_LEGACIES_DROPBOX_APP_KEY",
                    "CRYOSTACK_FROZEN_LEGACIES_DROPBOX_APP_SECRET"))
                if not all((token, key, secret)): raise ValueError("missing environment")
                client = dropbox.Dropbox(oauth2_refresh_token=token, app_key=key,
                                         app_secret=secret, timeout=60)
                self._client = client.with_path_root(
                    dropbox.common.PathRoot.namespace_id(self.namespace))
            except Exception as error:
                raise StorageError(f"Dropbox workload credentials are unavailable ({type(error).__name__}).")
        return self._client

    def _inventory(self, refresh=False):
        if self._files is not None and not refresh: return self._files
        try:
            result = self.client.files_list_folder("/" + self.folder if self.folder else "", recursive=True)
            entries = list(result.entries)
            while result.has_more:
                result = self.client.files_list_folder_continue(result.cursor); entries += result.entries
            found = {}
            for item in entries:
                if not hasattr(item, "size"): continue
                full = (item.path_display or item.name).strip("/")
                if self.folder and full.lower().startswith(self.folder.lower() + "/"):
                    full = full[len(self.folder) + 1:]
                key = normalize_key(full)
                found[key] = (item.path_lower, StorageObject(
                    key, int(item.size), _time_ns(item.client_modified), item.content_hash))
            self._files = found; return found
        except StorageError: raise
        except Exception as error:
            raise StorageError(f"Dropbox could not be listed ({type(error).__name__}).")

    def list(self, prefix="", *, suffixes=()):
        prefix = prefix.strip("/"); lowered = tuple(x.lower() for x in suffixes)
        for key, (_path, obj) in sorted(self._inventory(refresh=True).items()):
            if prefix and key != prefix and not key.startswith(prefix + "/"): continue
            if lowered and not key.lower().endswith(lowered): continue
            yield obj

    def stat(self, key):
        pair = self._inventory().get(normalize_key(key)); return pair[1] if pair else None

    def open_stream(self, key):
        pair = self._inventory().get(normalize_key(key))
        if not pair: raise StorageError("The file is no longer in Dropbox.")
        try:
            _metadata, response = self.client.files_download(pair[0]); return _ResponseStream(response)
        except Exception as error:
            raise StorageError(f"Dropbox could not read the file ({type(error).__name__}).")

    def check(self):
        try: next(iter(self.list()), None)
        except StorageError as error: return {"ok": False, "message": str(error)}
        return {"ok": True, "message": "The approved Dropbox namespace is readable."}

    def describe(self):
        return {"provider": self.provider, "location": mask_location(self.namespace),
                "capabilities": sorted(self.capabilities)}
