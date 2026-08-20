from __future__ import annotations

import base64
import json
import uuid

import ipywidgets as W
from IPython.display import Javascript, display


class WorkspaceBridge:
    def __init__(self) -> None:
        self.bridge_id = (
            "cryostack-workspace-"
            + uuid.uuid4().hex
        )

        self.output = W.HTML(
            value=self._render(""),
            layout=W.Layout(
                display="none",
                width="0px",
                height="0px",
            ),
        )

    def widget(self) -> W.HTML:
        return self.output

    def save(
        self,
        *,
        application: str,
        state: dict,
    ) -> None:
        command = {
            "message_id": uuid.uuid4().hex,
            "method": "PUT",
            "url": (
                f"/api/v1/workspaces/{application}"
            ),
            "payload": {
                "state": state,
            },
        }

        encoded = base64.b64encode(
            json.dumps(
                command,
                separators=(",", ":"),
            ).encode("utf-8")
        ).decode("ascii")

        self.output.value = self._render(
            encoded
        )

    def _render(self, encoded: str) -> str:
        return f"""
<div
  class="cryostack-workspace-bridge"
  data-cryostack-workspace="{encoded}"
></div>
"""


def load_workspace_bridge() -> None:
    display(
        Javascript(
            r"""
(() => {
    "use strict";

    if (window.__cryostackWorkspaceObserverInstalled) {
        return;
    }

    window.__cryostackWorkspaceObserverInstalled = true;

    const processed = new Set();

    function decode(encoded) {
        const binary = atob(encoded);

        const bytes = Uint8Array.from(
            binary,
            c => c.charCodeAt(0)
        );

        return JSON.parse(
            new TextDecoder("utf-8").decode(bytes)
        );
    }

    async function process(element) {
        const encoded =
            element?.getAttribute(
                "data-cryostack-workspace"
            );

        if (!encoded) {
            return;
        }

        let command;

        try {
            command = decode(encoded);
        } catch (error) {
            console.error(
                "[CryoStack workspace] decode failed",
                error
            );
            return;
        }

        if (
            !command.message_id ||
            processed.has(command.message_id)
        ) {
            return;
        }

        processed.add(command.message_id);

        try {
            const response = await fetch(
                command.url,
                {
                    method: command.method,
                    credentials: "same-origin",
                    headers: {
                        "Accept": "application/json",
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify(
                        command.payload
                    )
                }
            );

            const text =
                await response.text();

            if (!response.ok) {
                throw new Error(
                    `HTTP ${response.status}: ${text}`
                );
            }

            console.debug(
                "[CryoStack workspace] saved"
            );

        } catch (error) {
            console.error(
                "[CryoStack workspace] failed",
                error
            );
        }
    }

    function scan(root = document) {
        if (
            root.matches?.(
                ".cryostack-workspace-bridge"
            )
        ) {
            process(root);
        }

        root.querySelectorAll?.(
            ".cryostack-workspace-bridge"
        ).forEach(process);
    }

    const observer = new MutationObserver(
        mutations => {
            for (const mutation of mutations) {
                if (
                    mutation.type === "attributes"
                ) {
                    process(mutation.target);
                }

                for (
                    const node
                    of mutation.addedNodes
                ) {
                    if (
                        node.nodeType ===
                        Node.ELEMENT_NODE
                    ) {
                        scan(node);
                    }
                }
            }
        }
    );

    observer.observe(
        document.documentElement,
        {
            subtree: true,
            childList: true,
            attributes: true,
            attributeFilter: [
                "data-cryostack-workspace"
            ]
        }
    );

    scan();
})();
"""
        )
    )