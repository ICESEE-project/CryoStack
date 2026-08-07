"""Browser bridge between Voilà applications and CryoStack experiments."""

from __future__ import annotations

import json
import uuid

import ipywidgets as W

from IPython.display import Javascript, display


class ExperimentBridge:
    """Submit experiment events through the authenticated browser session.

    Python controls the experiment payload, while JavaScript performs the
    HTTP request. This means the CryoStack HttpOnly session cookie never
    enters the notebook kernel.
    """

    def __init__(self) -> None:
        self.bridge_id = (
            "cryostack-experiment-"
            + uuid.uuid4().hex
        )

        self.output = W.HTML(
            value=self._initial_html(),
            layout=W.Layout(
                width="0px",
                height="0px",
                overflow="hidden",
            ),
        )

    def widget(self) -> W.HTML:
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
    ) -> None:
        payload = {
            "application": application,
            "name": name,
            "backend": backend,
            "configuration": configuration,
            "status": status,
            "job_id": job_id,
            "cluster": cluster,
            "working_directory": (
                working_directory
            ),
            "output_directory": (
                output_directory
            ),
            "log_path": log_path,
            "metadata": metadata or {},
        }

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
        self._dispatch(
            method="PATCH",
            url=(
                "/api/v1/experiments/"
                + experiment_id
            ),
            payload=fields,
            action="update",
        )

    def _dispatch(
        self,
        *,
        method: str,
        url: str,
        payload: dict,
        action: str,
    ) -> None:
        message_id = uuid.uuid4().hex

        command = {
            "message_id": message_id,
            "action": action,
            "method": method,
            "url": url,
            "payload": payload,
        }

        encoded = json.dumps(command)

        self.output.value = (
            self._initial_html()
            + f"""
<script>
(() => {{
    const command = {encoded};

    window.dispatchEvent(
        new CustomEvent(
            "cryostack-experiment-command",
            {{
                detail: command
            }}
        )
    );
}})();
</script>
"""
        )

    def _initial_html(self) -> str:
        return f"""
<div
    id="{self.bridge_id}"
    data-cryostack-experiment-bridge
></div>
"""

def load_experiment_bridge() -> None:
    """Install the CryoStack experiment API listener in the browser."""

    display(
        Javascript(
            r"""
(() => {
    "use strict";

    if (window.__cryostackExperimentBridgeInstalled) {
        return;
    }

    window.__cryostackExperimentBridgeInstalled = true;

    window.addEventListener(
        "cryostack-experiment-command",
        async (event) => {
            const command = event.detail || {};

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
                            command.payload || {}
                        )
                    }
                );

                const text = await response.text();

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
                        `CryoStack experiment API returned `
                        + `${response.status}: ${text}`
                    );
                }

                window.dispatchEvent(
                    new CustomEvent(
                        "cryostack-experiment-result",
                        {
                            detail: {
                                ok: true,
                                message_id:
                                    command.message_id,
                                action:
                                    command.action,
                                result
                            }
                        }
                    )
                );

                console.debug(
                    "[CryoStack experiment]",
                    command.action,
                    result
                );

            } catch (error) {

                console.error(
                    "[CryoStack experiment]",
                    error
                );

                window.dispatchEvent(
                    new CustomEvent(
                        "cryostack-experiment-result",
                        {
                            detail: {
                                ok: false,
                                message_id:
                                    command.message_id,
                                action:
                                    command.action,
                                error:
                                    String(error)
                            }
                        }
                    )
                );
            }
        }
    );
})();
"""
        )
    )