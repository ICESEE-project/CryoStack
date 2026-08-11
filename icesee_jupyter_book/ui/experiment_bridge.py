"""Browser bridge between Voilà applications and CryoStack experiments."""

from __future__ import annotations

import base64
import json
import uuid

import ipywidgets as W
from IPython.display import Javascript, display


class ExperimentBridge:
    """Send experiment commands through the authenticated browser session.

    Python updates a hidden HTML element with an encoded command.
    Browser JavaScript watches that element and sends the request through
    the user's existing authenticated CryoStack session.

    The HttpOnly authentication cookie never enters the notebook kernel.
    """

    def __init__(self) -> None:
        self.bridge_id = (
            "cryostack-experiment-"
            + uuid.uuid4().hex
        )

        self.output = W.HTML(
            value=self._render_payload(""),
            layout=W.Layout(
                width="0px",
                height="0px",
                overflow="hidden",
                display="none",
            ),
        )

    def widget(self) -> W.HTML:
        """Return the hidden widget that carries experiment commands."""
        return self.output

    def create(
        self,
        *,
        application: str,
        name: str,
        backend: str,
        configuration: dict,
        status: str = "queued",
        job_id: str | None = None,
        cluster: str | None = None,
        working_directory: str | None = None,
        output_directory: str | None = None,
        log_path: str | None = None,
        metadata: dict | None = None,
        configuration_id: str | None = None,
    ) -> None:
        """Request creation of a CryoStack experiment."""

        payload = {
            "application": application,
            "name": name,
            "backend": backend,
            "configuration": configuration,
            "status": status,
            "job_id": job_id,
            "cluster": cluster,
            "working_directory": working_directory,
            "output_directory": output_directory,
            "log_path": log_path,
            "metadata": metadata or {},
        }

        if configuration_id:
            payload["configuration_id"] = configuration_id

        self._dispatch(
            method="POST",
            url="/api/v1/experiments",
            payload=payload,
            action="create",
        )

    def update(
        self,
        *,
        experiment_id: str,
        **fields,
    ) -> None:
        """Request an update to an existing CryoStack experiment."""

        self._dispatch(
            method="PATCH",
            url=(
                "/api/v1/experiments/"
                + experiment_id
            ),
            payload=fields,
            action="update",
        )

    def delete(
        self,
        *,
        experiment_id: str,
    ) -> None:
        """Request deletion of an experiment."""

        self._dispatch(
            method="DELETE",
            url=(
                "/api/v1/experiments/"
                + experiment_id
            ),
            payload={},
            action="delete",
        )

    def _dispatch(
        self,
        *,
        method: str,
        url: str,
        payload: dict,
        action: str,
    ) -> None:
        command = {
            "message_id": uuid.uuid4().hex,
            "action": action,
            "method": method,
            "url": url,
            "payload": payload,
        }

        raw = json.dumps(
            command,
            separators=(",", ":"),
        ).encode("utf-8")

        encoded = base64.b64encode(
            raw
        ).decode("ascii")

        # Updating widget HTML causes a real DOM mutation.
        # The JavaScript MutationObserver installed below sees this
        # and performs the authenticated API request.
        self.output.value = self._render_payload(
            encoded
        )

    def _render_payload(
        self,
        encoded: str,
    ) -> str:
        return f"""
<div
    id="{self.bridge_id}"
    class="cryostack-experiment-bridge"
    data-cryostack-command="{encoded}"
></div>
"""

    def update_by_job(
        self,
        *,
        job_id: str,
        **fields,
    ) -> None:
        self._dispatch(
            method="PATCH",
            url=(
                "/api/v1/experiments/job/"
                + str(job_id)
            ),
            payload=fields,
            action="update",
        )


def load_experiment_bridge() -> None:
    """Install the browser-side CryoStack experiment observer."""

    display(
        Javascript(
            r"""
(() => {
    "use strict";

    if (
        window.__cryostackExperimentObserverInstalled
    ) {
        return;
    }

    window.__cryostackExperimentObserverInstalled = true;

    const processed = new Set();

    function decodeCommand(encoded) {
        const binary = atob(encoded);

        const bytes = Uint8Array.from(
            binary,
            char => char.charCodeAt(0)
        );

        const text = new TextDecoder(
            "utf-8"
        ).decode(bytes);

        return JSON.parse(text);
    }

    async function processBridge(element) {
        if (!element) {
            return;
        }

        const encoded =
            element.getAttribute(
                "data-cryostack-command"
            );

        if (!encoded) {
            return;
        }

        let command;

        try {
            command = decodeCommand(encoded);
        } catch (error) {
            console.error(
                "[CryoStack experiment] "
                + "Could not decode command:",
                error
            );
            return;
        }

        if (!command.message_id) {
            return;
        }

        if (
            processed.has(command.message_id)
        ) {
            return;
        }

        processed.add(command.message_id);

        console.info(
            "[CryoStack experiment] sending",
            command
        );

        try {
            const options = {
                method: command.method,
                credentials: "same-origin",
                headers: {
                    "Accept":
                        "application/json",
                    "Content-Type":
                        "application/json"
                }
            };

            if (
                command.method !== "GET"
                && command.method !== "HEAD"
            ) {
                options.body = JSON.stringify(
                    command.payload || {}
                );
            }

            const response = await fetch(
                command.url,
                options
            );

            const text =
                await response.text();

            let result = null;

            if (text) {
                try {
                    result = JSON.parse(text);
                } catch {
                    result = {
                        raw: text
                    };
                }
            }

            if (!response.ok) {
                throw new Error(
                    `HTTP ${response.status}: ${text}`
                );
            }

            console.info(
                "[CryoStack experiment] saved",
                result
            );

            window.dispatchEvent(
                new CustomEvent(
                    "cryostack-experiment-result",
                    {
                        detail: {
                            ok: true,
                            action:
                                command.action,
                            message_id:
                                command.message_id,
                            result
                        }
                    }
                )
            );

        } catch (error) {
            console.error(
                "[CryoStack experiment] failed",
                error
            );

            window.dispatchEvent(
                new CustomEvent(
                    "cryostack-experiment-result",
                    {
                        detail: {
                            ok: false,
                            action:
                                command.action,
                            message_id:
                                command.message_id,
                            error:
                                String(error)
                        }
                    }
                )
            );
        }
    }

    function scan(root = document) {
        if (
            root.matches?.(
                ".cryostack-experiment-bridge"
            )
        ) {
            processBridge(root);
        }

        root.querySelectorAll?.(
            ".cryostack-experiment-bridge"
        ).forEach(
            processBridge
        );
    }

    const observer = new MutationObserver(
        mutations => {
            for (
                const mutation
                of mutations
            ) {
                if (
                    mutation.type ===
                    "attributes"
                ) {
                    processBridge(
                        mutation.target
                    );
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
                "data-cryostack-command"
            ]
        }
    );

    scan();

    console.info(
        "[CryoStack experiment] "
        + "bridge installed"
    );
})();
"""
        )
    )
