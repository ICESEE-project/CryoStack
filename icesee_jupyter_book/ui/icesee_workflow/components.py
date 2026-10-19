"""Small building blocks of the ICESEE workflow UI: buttons with a clear
action hierarchy, state badges, callouts, empty and loading states, a
two-step confirmation for destructive actions, and browser downloads."""
from __future__ import annotations

import base64
import html
import threading
import time
import uuid
from pathlib import Path

import ipywidgets as W
from IPython.display import HTML, Javascript, display

from icesee_jupyter_book.core import run_lifecycle as lc

esc = html.escape

#: largest file handed to the browser in one download (base64 over the
#: notebook websocket); larger outputs are packaged on request or fetched
#: from the server another way
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024

KINDS = {"primary": "icw-btn-primary", "hero": "icw-btn-primary icw-btn-hero", "secondary": "icw-btn-secondary",
         "quiet": "icw-btn-quiet", "danger": "icw-btn-danger", "danger-solid": "icw-btn-danger-solid"}


def button(label: str, *, icon: str = "", kind: str = "secondary", tooltip: str = "", width: str = "auto") -> W.Button:
    """A labelled action button. ``kind``: hero/primary (the main next
    action), secondary, quiet (low-weight), danger (destructive)."""
    b = W.Button(description=label, icon=icon, tooltip=tooltip or label, layout=W.Layout(width=width))
    for cls in KINDS[kind].split():
        b.add_class(cls)
    return b


class BusyButton:
    """Button state transitions: ``Launch`` -> ``Submitting…`` (spinner,
    disabled) -> ``Submitted`` (briefly) -> back to its label. ``run`` makes
    the click idempotent while the action is in flight."""

    def __init__(self, btn: W.Button):
        self.btn = btn
        self.label = btn.description
        self.icon = btn.icon
        self._lock = threading.Lock()
        self.busy = False
        self._generation = 0

    def claim(self) -> bool:
        """Take the button for one action, in the click handler itself (so a
        double click cannot start two actions); ``run(..., claimed=True)``
        then performs it, typically on a worker thread."""
        return self._lock.acquire(blocking=False)

    def run(self, action, *, busy_label: str, done_label: str = "", fail_label: str = "", hold: float = 1.6,
            claimed: bool = False):
        if not claimed and not self._lock.acquire(blocking=False):
            return None                                   # a second click while busy is ignored
        self.busy = True
        self._generation += 1
        generation = self._generation
        self.btn.disabled = True
        self.btn.description, self.btn.icon = busy_label, "spinner"
        ok = False
        try:
            result = action()
            ok = result is not False
            return result
        finally:
            # the button is usable again at once; the outcome label is shown briefly
            show = (done_label if ok else fail_label)
            self.btn.description = show or self.label
            self.btn.icon = ("check" if ok else "exclamation-triangle") if show else self.icon
            self.btn.disabled = False
            self.busy = False
            self._lock.release()
            if show:
                def restore():
                    time.sleep(hold)
                    if self._generation == generation and not self.busy:
                        self.btn.description, self.btn.icon = self.label, self.icon
                threading.Thread(target=restore, daemon=True).start()

    def relabel(self, label: str, icon: str | None = None):
        self.label = label
        if icon is not None:
            self.icon = icon
        if not self.busy:
            self.btn.description = label
            if icon is not None:
                self.btn.icon = icon


def badge(text: str, tone: str = "neutral", *, dot: bool = True, title: str = "") -> str:
    t = f' title="{esc(title)}"' if title else ""
    d = '<span class="dot" aria-hidden="true"></span>' if dot else ""
    return f'<span class="icw-badge {esc(tone)}" role="status"{t}>{d}{esc(text)}</span>'


def state_badge(state: str | None, *, detail: str = "") -> str:
    if not state:
        return badge("No run", "neutral")
    return badge(lc.LABELS.get(state, state.title()), state, title=detail)


def callout(text: str, tone: str = "info", *, title: str = "", html_body: bool = False) -> str:
    icons = {"info": "ℹ", "ok": "✓", "warn": "⚠", "bad": "✕"}
    body = text if html_body else esc(text)
    head = f"<b>{esc(title)}</b> " if title else ""
    role = "alert" if tone == "bad" else "status"
    return (f'<div class="icw-callout {tone}" role="{role}"><span class="ico" aria-hidden="true">{icons.get(tone, "")}</span>'
            f"<div>{head}{body}</div></div>")


def empty_state(title: str, body: str = "", icon: str = "◌") -> str:
    return (f'<div class="icw-empty"><div class="ico" aria-hidden="true">{esc(icon)}</div><h4>{esc(title)}</h4>'
            f"<p>{esc(body)}</p></div>")


def skeleton(lines: int = 3, *, tall: bool = False, label: str = "Loading") -> str:
    bars = "".join(f'<i style="width:{w}%"></i>' for w in (92, 76, 84, 60, 70)[:lines])
    big = '<i class="tall"></i>' if tall else ""
    return f'<div class="icw-skel" aria-busy="true" aria-label="{esc(label)}">{bars}{big}</div>'


def issues_html(issues) -> str:
    if not issues:
        return ""
    items = []
    for i, issue in enumerate(issues):
        level = getattr(issue, "level", "error")
        line = getattr(issue, "line", None)
        ln = f'<span class="ln">line {line}</span>' if line else ""
        items.append(f'<li class="{esc(level)}" style="animation-delay:{min(i, 8) * 40}ms">'
                     f'<span aria-hidden="true">{"✕" if level == "error" else "⚠" if level == "warning" else "•"}</span>'
                     f"<span>{esc(getattr(issue, 'message', str(issue)))}</span>{ln}</li>")
    return '<ul class="icw-issues" aria-live="polite">' + "".join(items) + "</ul>"


def kv(rows) -> str:
    cells = "".join(f"<dt>{esc(str(k))}</dt><dd>{v}</dd>" for k, v in rows if v not in (None, ""))
    return f'<dl class="icw-kv">{cells}</dl>'


def code(text) -> str:
    return f"<code>{esc(str(text))}</code>"


def card(children, *, title: str = "", number: str | int | None = None, subtitle: str = "",
         right: W.Widget | None = None, emphasis: bool = False, css: str = "") -> W.VBox:
    head_children = []
    if title:
        num = f'<span class="num">{esc(str(number))}</span>' if number is not None else ""
        sub = f'<div class="icw-card-sub">{esc(subtitle)}</div>' if subtitle else ""
        head_children.append(W.HTML(f'<div><div class="icw-card-title">{num}<span>{esc(title)}</span></div>{sub}</div>'))
    if right is not None:
        head_children.append(right)
    items = []
    if head_children:
        head = W.HBox(head_children)
        head.add_class("icw-card-head")
        items.append(head)
    items.extend(children)
    box = W.VBox(items, layout=W.Layout(width="100%", gap="10px"))
    box.add_class("icw-card")
    if emphasis:
        box.add_class("icw-emph")
    for c in css.split():
        box.add_class(c)
    return box


def field(label: str, widget: W.Widget, help: str = "") -> W.HBox:
    h = f'<span class="icw-help">{esc(help)}</span>' if help else ""
    row = W.HBox([W.HTML(f"<label>{esc(label)}{h}</label>"), widget], layout=W.Layout(width="100%"))
    widget.layout.width = "100%"
    row.add_class("icw-field")
    return row


def human_size(n: int | float) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def human_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class ConfirmAction:
    """Two-step confirmation for a destructive action: the first click turns
    the button into "Confirm …" with a Cancel option for a few seconds."""

    def __init__(self, btn: W.Button, action, *, confirm_label: str, timeout: float = 6.0):
        self.btn, self.action, self.confirm_label, self.timeout = btn, action, confirm_label, timeout
        self.label, self.icon = btn.description, btn.icon
        self.cancel = button("Keep", kind="quiet", tooltip="Do not do this")
        self.cancel.layout.display = "none"
        self.box = W.HBox([btn, self.cancel], layout=W.Layout(gap="6px", align_items="center"))
        self._armed = False
        self._token = 0
        btn.on_click(self._click)
        self.cancel.on_click(lambda _b: self._disarm())

    def _click(self, _b=None):
        if not self._armed:
            self._armed = True
            self._token += 1
            token = self._token
            self.btn.description, self.btn.icon = self.confirm_label, "exclamation-triangle"
            self.btn.remove_class("icw-btn-danger")
            self.btn.add_class("icw-btn-danger-solid")
            self.cancel.layout.display = ""

            def expire():
                time.sleep(self.timeout)
                if self._armed and self._token == token:
                    self._disarm()
            threading.Thread(target=expire, daemon=True).start()
            return
        self._disarm()
        self.action()

    def _disarm(self):
        self._armed = False
        self.btn.description, self.btn.icon = self.label, self.icon
        self.btn.remove_class("icw-btn-danger-solid")
        self.btn.add_class("icw-btn-danger")
        self.cancel.layout.display = "none"


def run_js(output: W.Output, script: str) -> None:
    """Run a small script in the page (scripts in W.HTML do not execute)."""
    with output:
        output.clear_output(wait=True)
        display(Javascript(script))


def offer_download(output: W.Output, path: Path, *, filename: str | None = None, mime: str = "application/octet-stream") -> str:
    """Hand a server file to the browser as a download. Returns "" or the
    reason it was not offered (too large / missing)."""
    path = Path(path)
    if not path.is_file():
        return f"{path.name} does not exist"
    size = path.stat().st_size
    if size > MAX_DOWNLOAD_BYTES:
        return (f"{path.name} is {human_size(size)}, more than the {human_size(MAX_DOWNLOAD_BYTES)} the browser download "
                f"allows; it is on the server at {path}")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    name = esc(filename or path.name)
    element = f"icw_dl_{uuid.uuid4().hex}"
    with output:
        output.clear_output(wait=True)
        display(HTML(f'''<a id="{element}" href="data:{mime};base64,{data}" download="{name}" style="display:none">download</a>
<script>(function(){{var a=document.getElementById("{element}"); if(a) a.click();}})();</script>'''))
    return ""


def image_html(png: Path, *, alt: str, max_height: str = "") -> str:
    data = base64.b64encode(Path(png).read_bytes()).decode("ascii")
    style = f' style="max-height:{max_height}"' if max_height else ""
    return (f'<img src="data:image/png;base64,{data}" alt="{esc(alt)}"{style} '
            "onclick=\"(function(i){var d=document.createElement('div');d.className='icw-lightbox';"
            "d.setAttribute('role','dialog');d.setAttribute('aria-label','Enlarged figure');"
            "var c=i.cloneNode();c.onclick=null;d.appendChild(c);d.onclick=function(){d.remove()};"
            "document.addEventListener('keydown',function k(e){if(e.key==='Escape'){d.remove();"
            "document.removeEventListener('keydown',k)}});(i.closest('.icw')||document.body).appendChild(d)})(this)\">")
