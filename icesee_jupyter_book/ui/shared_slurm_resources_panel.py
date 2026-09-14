"""Shared "Slurm resources" panel -- reusable by IceSheets, ICESEE and future
Icepack UIs.

This is a *presentation* helper: it takes the gateway's existing widget
instances and arranges them into three clearly labelled groups with concise
help text. It never renames a serializer key, changes a submission argument,
or owns model-specific logic.

    Job settings
        Job name
        Wall time
    Compute resources
        Nodes   Tasks   Tasks / node        (responsive 3->2->1 grid)
        Partition
        Memory
    Allocation & notifications
        Account
        Email
"""
from __future__ import annotations

from dataclasses import dataclass

import ipywidgets as W

_HELP = {
    "wall_time": "Maximum requested runtime (MM:SS, HH:MM:SS or D-HH:MM:SS).",
    "nodes": "Number of compute nodes to request.",
    "tasks": "Total Slurm tasks.",
    "tasks_per_node": "Maximum tasks assigned to each node.",
    "partition": "Slurm partition / queue.",
    "memory": "Requested memory (e.g. 512M, 4G, 16GB, 1T).",
    "account": "Allocation / project charged by the job.",
    "email": "Address for Slurm BEGIN/END/FAIL notifications (optional).",
}


def _group_title(text: str) -> W.HTML:
    return W.HTML(f"<div class='cryostack-group-title'>{text}</div>")


def _field(label: str, widget: W.Widget, help_key: str | None = None) -> W.VBox:
    widget.layout = W.Layout(width="100%")
    children = [W.HTML(f"<div class='cryostack-field-label'>{label}</div>"), widget]
    if help_key and _HELP.get(help_key):
        children.append(W.HTML(f"<div class='cryostack-help'>{_HELP[help_key]}</div>"))
    box = W.VBox(children, layout=W.Layout(width="100%", gap="2px"))
    box.add_class("cryostack-field")
    return box


def _row(*fields: W.Widget) -> W.HBox:
    row = W.HBox(list(fields), layout=W.Layout(width="100%", gap="14px"))
    row.add_class("cryostack-field-row")
    return row


@dataclass
class SlurmResourcesPanel:
    container: W.VBox


def build_slurm_resources_panel(
    *,
    job_name: W.Widget,
    wall_time: W.Widget,
    nodes: W.Widget,
    tasks: W.Widget,
    tasks_per_node: W.Widget,
    partition: W.Widget,
    memory: W.Widget,
    account: W.Widget,
    email: W.Widget,
    extra_children: list[W.Widget] | None = None,
) -> SlurmResourcesPanel:
    job_settings = W.VBox(
        [
            _group_title("Job settings"),
            _row(_field("Job name", job_name), _field("Wall time", wall_time, "wall_time")),
        ],
        layout=W.Layout(width="100%", gap="6px"),
    )

    numeric_grid = W.HBox(
        [
            _field("Nodes", nodes, "nodes"),
            _field("Tasks", tasks, "tasks"),
            _field("Tasks / node", tasks_per_node, "tasks_per_node"),
        ],
        layout=W.Layout(width="100%", gap="14px"),
    )
    numeric_grid.add_class("cryostack-slurm-numeric-grid")

    compute_resources = W.VBox(
        [
            _group_title("Compute resources"),
            numeric_grid,
            _row(_field("Partition", partition, "partition"), _field("Memory", memory, "memory")),
        ],
        layout=W.Layout(width="100%", gap="6px"),
    )

    allocation = W.VBox(
        [
            _group_title("Allocation & notifications"),
            _row(_field("Account", account, "account"), _field("Email", email, "email")),
        ],
        layout=W.Layout(width="100%", gap="6px"),
    )

    children = [job_settings, compute_resources, allocation]
    if extra_children:
        children.extend(extra_children)

    container = W.VBox(children, layout=W.Layout(width="100%", gap="16px"))
    container.add_class("cryostack-slurm-resources-panel")
    return SlurmResourcesPanel(container=container)
