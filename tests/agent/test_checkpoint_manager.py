"""
Tests for CheckpointManager (Task 3.1).

Covers save, load_latest, clear, checkpoint_path, and crash-resume scenario
(S-P3-01 — crash resume golden).
"""
import json
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock


# =========================================================================
# Unit tests — Checkpoint dataclass + CheckpointManager
# =========================================================================

class TestCheckpoint:
    """Verify the Checkpoint dataclass structure."""

    def test_checkpoint_fields(self):
        """Checkpoint has all required fields and defaults."""
        from src.engine.checkpoint import Checkpoint

        now = datetime.now()
        cp = Checkpoint(
            stage_name="classify",
            stage_index=1,
            trace_id="trace-123",
            input_data={"msg": "hello"},
            output_data={"intent": "greeting"},
            created_at=now,
            validated=True,
        )
        assert cp.stage_name == "classify"
        assert cp.stage_index == 1
        assert cp.trace_id == "trace-123"
        assert cp.input_data == {"msg": "hello"}
        assert cp.output_data == {"intent": "greeting"}
        assert cp.created_at == now
        assert cp.validated is True

    def test_checkpoint_default_validated(self):
        """Checkpoint defaults validated=True."""
        from src.engine.checkpoint import Checkpoint

        cp = Checkpoint(
            stage_name="rag",
            stage_index=2,
            trace_id="trace-456",
            input_data={},
            output_data={},
            created_at=datetime.now(),
        )
        assert cp.validated is True


class TestCheckpointManager:
    """Verify CheckpointManager save/load/clear lifecycle."""

    @pytest.fixture
    def manager(self, tmp_path):
        """CheckpointManager using a temp directory."""
        from src.engine.checkpoint import CheckpointManager
        mgr = CheckpointManager(checkpoint_dir=str(tmp_path))
        return mgr

    def test_checkpoint_path_format(self, manager):
        """checkpoint_path returns data/checkpoints/{session_id}.json."""
        path = manager.checkpoint_path("session-abc")
        assert path.name == "session-abc.json"

    def test_save_checkpoint(self, manager):
        """save() persists a checkpoint to disk."""
        from src.engine.checkpoint import Checkpoint

        cp = Checkpoint(
            stage_name="classify",
            stage_index=1,
            trace_id="trace-111",
            input_data={"msg": "hello"},
            output_data={"intent": "greeting"},
            created_at=datetime.now(),
        )
        manager.save("session-1", cp)

        path = manager.checkpoint_path("session-1")
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["stage_name"] == "classify"
        assert data[0]["trace_id"] == "trace-111"

    def test_load_latest_returns_last_checkpoint(self, manager):
        """load_latest() returns the most recent checkpoint for a session."""
        from src.engine.checkpoint import Checkpoint

        cp1 = Checkpoint(
            stage_name="classify", stage_index=1, trace_id="trace-1",
            input_data={"m": "a"}, output_data={"r": 1},
            created_at=datetime.now(),
        )
        cp2 = Checkpoint(
            stage_name="rag", stage_index=2, trace_id="trace-1",
            input_data={"m": "a"}, output_data={"r": 2},
            created_at=datetime.now(),
        )
        manager.save("session-2", cp1)
        manager.save("session-2", cp2)

        loaded = manager.load_latest("session-2")
        assert loaded is not None
        assert loaded.stage_name == "rag"
        assert loaded.stage_index == 2

    def test_load_latest_no_checkpoint(self, manager):
        """load_latest() returns None when no checkpoint exists."""
        loaded = manager.load_latest("nonexistent")
        assert loaded is None

    def test_clear_removes_checkpoint_file(self, manager):
        """clear() removes the checkpoint file for a session."""
        from src.engine.checkpoint import Checkpoint

        cp = Checkpoint(
            stage_name="classify", stage_index=1, trace_id="trace-3",
            input_data={}, output_data={}, created_at=datetime.now(),
        )
        manager.save("session-3", cp)
        assert manager.checkpoint_path("session-3").exists()

        manager.clear("session-3")
        assert not manager.checkpoint_path("session-3").exists()

    def test_clear_nonexistent_does_not_raise(self, manager):
        """clear() on a nonexistent session does not raise."""
        manager.clear("no-such-session")  # should not raise

    def test_load_latest_returns_checkpoint_dataclass(self, manager):
        """load_latest() deserializes back to a Checkpoint dataclass."""
        from src.engine.checkpoint import Checkpoint

        now = datetime.now()
        cp = Checkpoint(
            stage_name="response", stage_index=5, trace_id="trace-99",
            input_data={"user": "msg"}, output_data={"resp": "ok"},
            created_at=now, validated=True,
        )
        manager.save("session-dc", cp)

        loaded = manager.load_latest("session-dc")
        assert loaded is not None
        assert isinstance(loaded, Checkpoint)
        assert loaded.stage_name == "response"
        assert loaded.stage_index == 5
        assert loaded.input_data == {"user": "msg"}

    def test_save_overwrites_previous_checkpoint(self, manager):
        """save() with same stage_index overwrites the previous entry."""
        from src.engine.checkpoint import Checkpoint

        cp1 = Checkpoint(
            stage_name="classify", stage_index=1, trace_id="t1",
            input_data={"v": 1}, output_data={}, created_at=datetime.now(),
        )
        cp2 = Checkpoint(
            stage_name="classify", stage_index=1, trace_id="t2",
            input_data={"v": 2}, output_data={}, created_at=datetime.now(),
        )
        manager.save("session-ow", cp1)
        manager.save("session-ow", cp2)

        loaded = manager.load_latest("session-ow")
        assert loaded is not None
        assert loaded.trace_id == "t2"
        assert loaded.input_data == {"v": 2}


# =========================================================================
# Exception handling
# =========================================================================

class TestCheckpointManagerErrors:
    """Verify CheckpointManager error handling via CheckpointError."""

    def test_save_to_bad_path_raises_checkpoint_error(self, tmp_path):
        """save() when write fails raises CheckpointError."""
        from src.engine.checkpoint import CheckpointManager, Checkpoint
        from src.engine.exceptions import CheckpointError
        from datetime import datetime
        from unittest.mock import patch

        mgr = CheckpointManager(checkpoint_dir=str(tmp_path))
        cp = Checkpoint(
            stage_name="test", stage_index=0, trace_id="t",
            input_data={}, output_data={}, created_at=datetime.now(),
        )
        # Make write_text raise PermissionError
        with patch.object(Path, "write_text", side_effect=PermissionError("denied")):
            with pytest.raises(CheckpointError):
                mgr.save("bad-session", cp)

    def test_load_from_bad_path_returns_none_gracefully(self, tmp_path, monkeypatch):
        """load_latest() when read fails returns None (no crash)."""
        from src.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=str(tmp_path))
        # Create a checkpoint file
        cp_path = mgr.checkpoint_path("any")
        cp_path.write_text("not-json")

        # load_latest should return None when JSON is invalid
        loaded = mgr.load_latest("any")
        assert loaded is None


# =========================================================================
# S-P3-01: Crash resume golden test
# =========================================================================

class TestCrashResume:
    """S-P3-01 — Crash resume: pipeline resumes from last checkpoint."""

    def test_crash_resume_golden(self, tmp_path):
        """
        Given a pipeline that completes stages 1-3,
        When it crashes during stage 4,
        And the pipeline restarts,
        Then it resumes at stage 4 without redoing stages 1-3.
        """
        from src.engine.checkpoint import CheckpointManager, Checkpoint
        from datetime import datetime

        mgr = CheckpointManager(checkpoint_dir=str(tmp_path))
        session_id = "crash-test"

        # Simulate stages 1-3 completing successfully
        for i in range(1, 4):
            cp = Checkpoint(
                stage_name=f"stage_{i}",
                stage_index=i,
                trace_id="golden-trace",
                input_data={"step": i},
                output_data={"result": i * 10},
                created_at=datetime.now(),
            )
            mgr.save(session_id, cp)

        # Crash happens at stage 4 (no checkpoint)
        # Resume: load latest checkpoint
        resume = mgr.load_latest(session_id)
        assert resume is not None
        assert resume.stage_name == "stage_3"
        assert resume.stage_index == 3
        assert resume.output_data == {"result": 30}

        # Full re-execution from scratch produces identical output
        mgr.clear(session_id)
        for i in range(1, 4):
            cp = Checkpoint(
                stage_name=f"stage_{i}",
                stage_index=i,
                trace_id="golden-trace",
                input_data={"step": i},
                output_data={"result": i * 10},
                created_at=datetime.now(),
            )
            mgr.save(session_id, cp)

        # After re-execution, latest is same as before crash resume
        after_replay = mgr.load_latest(session_id)
        assert after_replay is not None
        assert after_replay.stage_name == resume.stage_name
        assert after_replay.stage_index == resume.stage_index
        assert after_replay.output_data == resume.output_data
