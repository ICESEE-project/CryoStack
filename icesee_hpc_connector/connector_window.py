"""macOS onboarding / status window for the CryoStack Connector.

A menu-bar-only app is invisible on a crowded screen and undiscoverable for a
first-time participant. This adds a small native window that appears on launch
(and whenever the connector is unpaired) with an obvious pairing field, and
switches to a "Connected" panel after pairing. The menu bar stays as a
convenience surface.

The *content* of the window for each state is a pure function
(:func:`window_view`) so it can be tested without AppKit. The
:class:`AppKitConnectorWindow` at the bottom is the thin NSWindow renderer and
is imported only on macOS.
"""
from __future__ import annotations

from icesee_hpc_connector.connector_controller import ConnectorState

CRYOSTACK_URL = "https://cryostack.eas.gatech.edu/"

# action ids emitted by the window's buttons
ACTION_PAIR = "pair"
ACTION_OPEN_CRYOSTACK = "open-cryostack"
ACTION_HIDE = "hide"


class WindowMode:
    ONBOARDING = "onboarding"
    WORKING = "working"
    CONNECTED = "connected"


def window_view(state: str) -> dict:
    """What the window shows for a given :class:`ConnectorState`."""
    if state == ConnectorState.CONNECTED:
        return {
            "mode": WindowMode.CONNECTED,
            "title": "CryoStack Connector",
            "headline": "✓ Connected",
            "body": "Connected to CryoStack. This connector will keep running in "
                    "the menu bar.",
            "show_code_field": False,
            "buttons": [
                ("Open CryoStack", ACTION_OPEN_CRYOSTACK),
                ("Hide Window", ACTION_HIDE),
            ],
            "footnote": "",
        }

    if state in (ConnectorState.PAIRING, ConnectorState.RECONNECTING):
        return {
            "mode": WindowMode.WORKING,
            "title": "CryoStack Connector",
            "headline": "Connecting…",
            "body": "Establishing the secure bridge to CryoStack.",
            "show_code_field": False,
            "buttons": [("Hide Window", ACTION_HIDE)],
            "footnote": "",
        }

    body = {
        ConnectorState.ERROR:
            "The pairing session is no longer valid. Enter a fresh pairing code "
            "from CryoStack:",
        ConnectorState.DISCONNECTED:
            "Disconnected. Enter a fresh pairing code from CryoStack to "
            "reconnect:",
        ConnectorState.STOPPED:
            "Enter the pairing code shown in CryoStack:",
    }.get(state, "Enter the pairing code shown in CryoStack:")

    return {
        "mode": WindowMode.ONBOARDING,
        "title": "CryoStack Connector",
        "headline": "Status: Not paired",
        "body": body,
        "show_code_field": True,
        "field_placeholder": "pairing code",
        "buttons": [("Pair", ACTION_PAIR)],
        "footnote": "CryoStack Connector will continue running in the menu bar "
                    "after this window is closed.",
    }


def should_show_on_state(state: str) -> bool:
    """The window auto-shows itself while the connector is not connected."""
    return window_view(state)["mode"] != WindowMode.CONNECTED


# ---------------------------------------------------------------------------
# AppKit renderer (macOS only)
# ---------------------------------------------------------------------------
def build_appkit_window(on_action):
    """Create the native window. ``on_action(action_id, code)`` is called on the
    main thread when a button is pressed. Returns an object with
    ``show()`` / ``hide()`` / ``refresh(state)`` / ``is_visible()``; returns
    ``None`` if AppKit is unavailable (the caller then falls back to the modal
    pairing prompt)."""
    try:
        import AppKit
        import objc
    except Exception:
        return None

    try:
        return _AppKitConnectorWindow(AppKit, objc, on_action)
    except Exception:
        return None


class _AppKitConnectorWindow:  # pragma: no cover - requires a macOS GUI session
    def __init__(self, AppKit, objc, on_action):
        self._AppKit = AppKit
        self._on_action = on_action
        self._state = ConnectorState.IDLE

        style = (
            AppKit.NSWindowStyleMaskTitled
            | AppKit.NSWindowStyleMaskClosable
            | AppKit.NSWindowStyleMaskMiniaturizable
        )
        rect = AppKit.NSMakeRect(0, 0, 420, 260)
        self._win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, AppKit.NSBackingStoreBuffered, False
        )
        self._win.setTitle_("CryoStack Connector")
        self._win.setReleasedWhenClosed_(False)
        self._win.center()

        content = self._win.contentView()

        self._headline = self._label(AppKit, (24, 210, 372, 24), 17, bold=True)
        self._body = self._label(AppKit, (24, 120, 372, 84), 13)
        self._field = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(24, 84, 210, 24))
        self._field.setPlaceholderString_("pairing code")
        # Behave like a normal text field: editable, selectable, single line so
        # Cmd+C/V/X/A and the AppKit context menu work. The explicit Paste
        # button below is a guaranteed fallback if the app menu's paste: does
        # not reach the field editor under rumps.
        self._field.setEditable_(True)
        self._field.setSelectable_(True)
        self._field.setUsesSingleLineMode_(True)
        self._field.setAllowsEditingTextAttributes_(False)
        cell = self._field.cell()
        if cell is not None:
            cell.setUsesSingleLineMode_(True)
            cell.setScrollable_(True)
        self._win.setInitialFirstResponder_(self._field)

        target = self._make_target(objc)

        # explicit "Paste" -- populates the field only, never auto-submits
        self._paste_btn = AppKit.NSButton.alloc().initWithFrame_(AppKit.NSMakeRect(240, 82, 64, 28))
        self._paste_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self._paste_btn.setTitle_("Paste")
        self._paste_btn.setToolTip_("Paste the pairing code from the clipboard")
        self._paste_btn.setTarget_(target)
        self._paste_btn.setAction_("onPaste:")

        self._button = AppKit.NSButton.alloc().initWithFrame_(AppKit.NSMakeRect(312, 82, 84, 28))
        self._button.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self._button.setTarget_(target)
        self._button.setAction_("onButton:")
        self._button.setKeyEquivalent_("\r")   # Return triggers the primary button
        self._button2 = AppKit.NSButton.alloc().initWithFrame_(AppKit.NSMakeRect(220, 82, 84, 28))
        self._button2.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self._button2.setTarget_(target)
        self._button2.setAction_("onButton2:")
        self._foot = self._label(AppKit, (24, 24, 372, 40), 11)

        for v in (self._headline, self._body, self._field, self._paste_btn,
                  self._button, self._button2, self._foot):
            content.addSubview_(v)

        self.refresh(self._state)

    # -- clipboard fallback -------------------------------------------
    def _paste_from_clipboard(self):
        AppKit = self._AppKit
        pb = AppKit.NSPasteboard.generalPasteboard()
        text = pb.stringForType_(AppKit.NSPasteboardTypeString)
        if text is None:
            try:
                text = pb.stringForType_("public.utf8-plain-text")
            except Exception:
                text = None
        if not text:
            return
        # normalise here too; _fire already strips before submit
        self._field.setStringValue_(str(text).strip())
        self._win.makeFirstResponder_(self._field)

    # -- helpers --------------------------------------------------------
    def _label(self, AppKit, frame, size, bold=False):
        lbl = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(*frame))
        lbl.setBezeled_(False)
        lbl.setDrawsBackground_(False)
        lbl.setEditable_(False)
        lbl.setSelectable_(False)
        font = (AppKit.NSFont.boldSystemFontOfSize_(size) if bold
                else AppKit.NSFont.systemFontOfSize_(size))
        lbl.setFont_(font)
        return lbl

    def _make_target(self, objc):
        outer = self

        class _Target(objc.lookUpClass("NSObject")):
            def onButton_(self, _sender):
                outer._fire(0)

            def onButton2_(self, _sender):
                outer._fire(1)

            def onPaste_(self, _sender):
                outer._paste_from_clipboard()

        self._target = _Target.alloc().init()
        return self._target

    def _fire(self, which):
        view = window_view(self._state)
        buttons = view["buttons"]
        if which >= len(buttons):
            return
        _label, action = buttons[which]
        code = str(self._field.stringValue()).strip() if view["show_code_field"] else ""
        self._on_action(action, code)

    # -- public --------------------------------------------------------
    def refresh(self, state):
        self._state = state
        view = window_view(state)
        self._headline.setStringValue_(view["headline"])
        self._body.setStringValue_(view["body"])
        self._foot.setStringValue_(view.get("footnote", ""))
        self._field.setHidden_(not view["show_code_field"])
        self._paste_btn.setHidden_(not view["show_code_field"])
        if not view["show_code_field"]:
            # never keep a pairing code around after we leave the entry state
            self._field.setStringValue_("")
        buttons = view["buttons"]
        self._button.setHidden_(len(buttons) < 1)
        self._button2.setHidden_(len(buttons) < 2)
        if buttons:
            self._button.setTitle_(buttons[0][0])
        if len(buttons) > 1:
            self._button2.setTitle_(buttons[1][0])
        self._win.setTitle_(view["title"])

    def show(self):
        self._AppKit.NSApp.activateIgnoringOtherApps_(True)
        self._win.makeKeyAndOrderFront_(None)
        # When the pairing field is showing, put the cursor in it so the user
        # can paste (Cmd+V) or type the code immediately.
        if not self._field.isHidden():
            self._win.makeFirstResponder_(self._field)

    def hide(self):
        self._win.orderOut_(None)

    def is_visible(self):
        return bool(self._win.isVisible())
