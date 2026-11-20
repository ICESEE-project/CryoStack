"""The archive must remain downloadable when a renderer suppresses scripts."""
import base64
from html.parser import HTMLParser
from cryostack_src.workspace import manager


def test_archive_is_a_real_clickable_link_without_javascript(tmp_path, monkeypatch):
    path=tmp_path/'outputs.zip'; path.write_bytes(b'archive fixture')
    shown=[]; monkeypatch.setattr(manager,'display',shown.append)
    manager.WorkspaceManager._auto_download(path, 'results"<test>.zip')
    class Links(HTMLParser):
        attrs=None
        def handle_starttag(self,tag,attrs):
            if tag=='a': self.attrs=dict(attrs)
    parser=Links(); parser.feed(shown[0].data)
    assert '<script' not in shown[0].data
    assert parser.attrs['download'].startswith('results"<test>_')
    prefix,data=parser.attrs['href'].split(',',1)
    assert prefix=='data:application/zip;base64'
    assert base64.b64decode(data)==path.read_bytes()
