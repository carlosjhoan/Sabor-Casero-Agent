"""
CheckpointManager — save/load/clear per-skill checkpoints.

Each checkpoint is a ``Checkpoint`` dataclass persisted to
``data/checkpoints/{session_id}.json`` as a list of entries.  On crash
resume, ``load_latest()`` returns the most recent checkpoint for a session
so the pipeline can pick up where it left off.

Usage::

    mgr = CheckpointManager()
    mgr.save("session-1", checkpoint)
    latest = mgr.load_latest("session-1")
    mgr.clear("session-1")
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class Checkpoint:
    """A single checkpoint entry for one stage execution.

    Attributes:
        stage_name: Name of the stage (e.g. ``"classify"``).
        stage_index: Ordinal position in the pipeline (0-based).
        trace_id: The trace ID active when this checkpoint was saved.
        input_data: Stage input — must be JSON-serialisable.
        output_data: Stage output — must be JSON-serialisable.
        created_at: Timestamp of when the checkpoint was saved.
        validated: Whether the output passed validation gates.
    """

    stage_name: str
    stage_index: int
    trace_id: str
    input_data: dict
    output_data: dict
    created_at: datetime
    validated: bool = True


def _checkpoint_to_dict(cp: Checkpoint) -> dict:
    """Serialize a ``Checkpoint`` to a JSON-safe dict."""
    d = asdict(cp)
    d["created_at"] = cp.created_at.isoformat()
    return d


def _dict_to_checkpoint(d: dict) -> Checkpoint:
    """Deserialize a dict back to a ``Checkpoint``."""
    d = dict(d)  # shallow copy
    d["created_at"] = datetime.fromisoformat(d["created_at"])
    return Checkpoint(**d)


class CheckpointManager:
    """Manages per-session checkpoint persistence.

    Parameters
    ----------
    checkpoint_dir: Directory path for checkpoint files.
        Defaults to ``"data/checkpoints/"``.
    """

    def __init__(self, checkpoint_dir: str = "data/checkpoints") -> None:
        self._checkpoint_dir = Path(checkpoint_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def checkpoint_path(self, session_id: str) -> Path:
        """Return the filesystem path for a session's checkpoint file.

        Args:
            session_id: Unique session identifier.

        Returns:
            ``Path`` pointing to ``{checkpoint_dir}/{session_id}.json``.
        """
        return self._checkpoint_dir / f"{session_id}.json"

    def save(self, session_id: str, checkpoint: Checkpoint) -> None:
        """Persist a checkpoint for the given session.

        Appends *checkpoint* to the session's checkpoint list.  If a
        checkpoint with the same ``stage_index`` already exists it is
        overwritten (upsert by ``stage_index``).

        Args:
            session_id:  Unique session identifier.
            checkpoint: The ``Checkpoint`` to persist.

        Raises:
            CheckpointError: If the file cannot be written (permissions,
                invalid path, etc.).
        """
        from src.core.agent.exceptions import CheckpointError

        path = self.checkpoint_path(session_id)
        try:
            self._checkpoint_dir.mkdir(parents=True, exist_ok=True)

            # Load existing checkpoints (if any)
            entries: list[dict] = []
            if path.exists():
                raw = path.read_text(encoding="utf-8")
                if raw.strip():
                    entries = json.loads(raw)

            # Upsert by stage_index
            entry = _checkpoint_to_dict(checkpoint)
            for i, existing in enumerate(entries):
                if existing.get("stage_index") == checkpoint.stage_index:
                    entries[i] = entry
                    break
            else:
                entries.append(entry)

            path.write_text(
                json.dumps(entries, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except (OSError, PermissionError, TypeError, ValueError) as exc:
            raise CheckpointError(
                f"Cannot save checkpoint: {exc}",
                operation="save",
                path=str(path),
            )

    def load_latest(self, session_id: str) -> Optional[Checkpoint]:
        """Load the most recent checkpoint for a session.

        Args:
            session_id: Unique session identifier.

        Returns:
            The latest ``Checkpoint``, or ``None`` if no checkpoint exists
            for the session.
        """
        path = self.checkpoint_path(session_id)
        if not path.exists():
            return None

        try:
            raw = path.read_text(encoding="utf-8")
            if not raw.strip():
                return None
            entries: list[dict] = json.loads(raw)
            if not entries:
                return None
            latest = entries[-1]
            return _dict_to_checkpoint(latest)
        except (OSError, json.JSONDecodeError):
            return None

    def clear(self, session_id: str) -> None:
        """Remove the checkpoint file for a session.

        Args:
            session_id: Unique session identifier.

        Does **not** raise if the file does not exist.
        """
        path = self.checkpoint_path(session_id)
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
