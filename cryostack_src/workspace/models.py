from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
from typing import Optional


@dataclass(slots=True)
class RunInfo:

    id: str

    name: str

    model: str

    backend: str

    execution_mode: str

    status: str = "submitted"

    created: datetime = field(default_factory=datetime.now)

    finished: Optional[datetime] = None

    remote_directory: Optional[Path] = None

    results_directory: Optional[Path] = None

    figures_directory: Optional[Path] = None

    log_file: Optional[Path] = None

    jobid: Optional[str] = None

    command: str = ""

    notes: str = ""