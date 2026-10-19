"""Cloud-drive adapters use fake APIs: no external accounts or network calls."""
from __future__ import annotations

from icesee_jupyter_book.applications.frozen_legacies.radar.cloud_storage import (
    DropboxProvider,
    GoogleDriveProvider,
    OneDriveProvider,
)

import io
from datetime import datetime, timezone


class _Request:
    def __init__(self, value):
        self.value = value
        self.headers = {}

    def execute(self):
        if callable(self.value):
            return self.value(self.headers)
        return self.value


class _FakeDrive:
    data = b"0123456789abcdef"

    def files(self):
        return self

    def list(self, **kwargs):
        parent = kwargs["q"].split("'")[1]
        rows = {
            "folder-root": [
                {"id": "sub", "name": "tiff", "mimeType": "application/vnd.google-apps.folder"},
            ],
            "sub": [
                {"id": "radar", "name": "F127-C0471_C0483.tiff",
                 "mimeType": "image/tiff", "size": str(len(self.data)),
                 "modifiedTime": "2026-10-15T12:00:00Z", "md5Checksum": "abc"},
            ],
        }
        return _Request({"files": rows.get(parent, [])})

    def get_media(self, **kwargs):
        def response(headers):
            value = headers.get("Range", "bytes=0-15").removeprefix("bytes=")
            start, end = [int(x) for x in value.split("-")]
            return self.data[start:end + 1]
        return _Request(response)


def test_google_drive_fake_lists_stats_and_reads_ranges():
    provider = GoogleDriveProvider(
        {"drive_id": "drive", "folder_id": "folder-root"}, service=_FakeDrive())
    objects = list(provider.list(suffixes=(".tiff",)))
    assert [o.key for o in objects] == ["tiff/F127-C0471_C0483.tiff"]
    assert objects[0].size == 16 and objects[0].etag == "abc"
    assert provider.stat(objects[0].key) == objects[0]
    assert provider.read_range(objects[0].key, 3, 5) == b"34567"
    with provider.open_stream(objects[0].key) as stream:
        assert stream.read(4) == b"0123"
        assert stream.seek(10) == 10 and stream.read() == b"abcdef"
    assert provider.check()["ok"] is True


class _GraphResponse:
    def __init__(self, body=None, content=b"", status=200):
        self._body, self.content, self.status_code = body or {}, content, status
        self.raw = io.BytesIO(content)
    def json(self): return self._body
    def close(self): self.raw.close()


class _FakeGraph:
    data = b"graph-radar"
    def get(self, url, headers=None, timeout=None, stream=False):
        if url.endswith("/children?$top=999"):
            return _GraphResponse({"value": [{"id": "f1", "name": "radar.tiff",
                "size": len(self.data), "lastModifiedDateTime": "2026-10-15T12:00:00Z",
                "eTag": "etag"}]})
        if url.endswith("/content"):
            value = self.data
            if headers and headers.get("Range"):
                start, end = map(int, headers["Range"].removeprefix("bytes=").split("-"))
                value = value[start:end + 1]
            return _GraphResponse(content=value)
        return _GraphResponse(status=404)


def test_onedrive_fake_lists_ranges_and_streams_without_external_calls():
    provider = OneDriveProvider({"drive_id": "drive", "folder": ""},
                                session=_FakeGraph(), token="test-token")
    assert [item.key for item in provider.list()] == ["radar.tiff"]
    assert provider.read_range("radar.tiff", 2, 5) == b"aph-r"
    with provider.open_stream("radar.tiff") as stream:
        assert stream.read() == _FakeGraph.data


class _DropboxEntry:
    name = "radar.tiff"; path_display = "/archive/radar.tiff"; path_lower = "/archive/radar.tiff"
    size = 13; client_modified = datetime(2026, 10, 15, tzinfo=timezone.utc); content_hash = "hash"


class _DropboxListing:
    entries = [_DropboxEntry()]; has_more = False; cursor = "done"


class _DropboxResponse:
    def __init__(self): self.raw = io.BytesIO(b"dropbox-radar")
    def close(self): self.raw.close()


class _FakeDropbox:
    def files_list_folder(self, path, recursive=False):
        assert path == "/archive" and recursive is True
        return _DropboxListing()
    def files_download(self, path):
        assert path == "/archive/radar.tiff"
        return _DropboxEntry(), _DropboxResponse()


def test_dropbox_fake_lists_and_streams_without_claiming_range_reads():
    provider = DropboxProvider({"drive_id": "namespace", "folder": "archive"},
                               client=_FakeDropbox())
    assert [item.key for item in provider.list()] == ["radar.tiff"]
    assert "range_read" not in provider.capabilities
    with provider.open_stream("radar.tiff") as stream:
        assert stream.read() == b"dropbox-radar"
