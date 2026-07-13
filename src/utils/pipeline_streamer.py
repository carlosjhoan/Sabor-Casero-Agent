"""
Pipeline Streamer — Real-time streaming display for the assistant pipeline.

Shows phase transitions, skill delegation, RAG retrieval, and decisions
as they happen, in a code-agent-style streaming format with timing.

Usage::

    streamer = PipelineStreamer()

    with streamer.phase("Classification") as p:
        p.step("Analyzing message...")
        # ... do work ...
        p.info("Intent", "CONSULTING")
        p.info("Topics", "menu, greeting")
        p.done("3 topics classified")

    with streamer.phase("RAG Retrieval") as p:
        p.step("Querying menu database...")
        # ... do work ...
        p.done("Found 10 items")

    streamer.response("¡Hola! Soy Luz Stella...")
    streamer.total()
"""

import time
import sys
from contextlib import contextmanager
from typing import Optional

try:
    import colorama
    colorama.init()
    HAS_COLORAMA = True
except ImportError:
    HAS_COLORAMA = False


class Style:
    """ANSI escape codes (used only when colorama is available)."""
    if HAS_COLORAMA:
        CYAN = '\033[96m'
        GREEN = '\033[92m'
        YELLOW = '\033[93m'
        RED = '\033[91m'
        BLUE = '\033[94m'
        MAGENTA = '\033[95m'
        GRAY = '\033[90m'
        BOLD = '\033[1m'
        DIM = '\033[2m'
        RESET = '\033[0m'
    else:
        CYAN = GREEN = YELLOW = RED = BLUE = MAGENTA = GRAY = BOLD = DIM = RESET = ''


def wprint(text: str, end: str = '\n'):
    """Print with immediate flush for real-time streaming."""
    print(text, end=end, flush=True)


# Legacy alias for internal use
_wprint = wprint


class PhaseContext:
    """Context for a single pipeline phase. Returned by ``PipelineStreamer.phase()``.

    Do not instantiate directly — use ``streamer.phase()``.
    """

    def __init__(self, streamer: 'PipelineStreamer', name: str, emoji: str = '▶'):
        self._streamer = streamer
        self._name = name
        self._emoji = emoji
        self._start: Optional[float] = None
        self._has_error: bool = False

    def __enter__(self) -> 'PhaseContext':
        self._start = time.time()
        self._streamer._print_phase_header(
            self._name, self._emoji,
            phase_index=self._streamer._phase_count + 1,
        )
        self._streamer._phase_count += 1
        return self

    def __exit__(self, *args) -> None:
        elapsed = time.time() - self._start if self._start else 0
        if self._has_error:
            print(f"    {Style.RED}✗{Style.RESET} Failed  ({Style.DIM}{elapsed:.3f}s{Style.RESET})", flush=True)
        else:
            print(f"    {Style.GREEN}✅{Style.RESET} Done  ({Style.DIM}{elapsed:.3f}s{Style.RESET})", flush=True)
        self._streamer._last_elapsed = elapsed

    # ── Streaming helpers ────────────────────────────────────────────────

    def step(self, message: str):
        """Print an in-progress step."""
        _wprint(f"    {Style.GRAY}└{Style.RESET} {message}")

    def info(self, key: str, value: str):
        """Print a key/value info line."""
        _wprint(f"    {Style.CYAN}{key}:{Style.RESET} {value}")

    def result(self, status: str, detail: str = '', is_error: bool = False):
        """Print a result with inline status."""
        if is_error:
            self._has_error = True
        icon = '✗' if is_error else '✓'
        color = Style.RED if is_error else Style.GREEN
        _wprint(f"    {color}{icon}{Style.RESET} {status}{': ' + detail if detail else ''}")

    def done(self, message: str = ''):
        """Manually signal completion with an optional result summary."""
        elapsed = time.time() - self._start if self._start else 0
        suffix = f' — {message}' if message else ''
        print(f"    {Style.GREEN}✅{Style.RESET} Done{suffix}  ({Style.DIM}{elapsed:.3f}s{Style.RESET})", flush=True)
        self._streamer._last_elapsed = elapsed


class PipelineStreamer:
    """Top-level streamer for the full assistant pipeline.

    Create once per message and use ``phase()`` context managers
    to wrap each logical stage.
    """

    def __init__(self):
        self._pipeline_start = time.time()
        self._phase_count = 0
        self._last_elapsed: Optional[float] = None

    # ── Phase management ─────────────────────────────────────────────────

    def phase(self, name: str, emoji: str = '▶') -> PhaseContext:
        """Start a new pipeline phase. Returns a context manager.

        Example::

            with streamer.phase("Classification") as p:
                p.step("Classifying...")
                p.done("menu query")
        """
        return PhaseContext(self, name, emoji)

    # ── Special-purpose sections ─────────────────────────────────────────

    def response(self, text: str):
        """Print the final assistant response in a clearly delimited box."""
        sep = '═' * 50
        print(f"\n  {Style.BOLD}{sep}{Style.RESET}", flush=True)
        print(f"  {Style.BOLD}  RESPUESTA{Style.RESET}", flush=True)
        print(f"  {Style.BOLD}{sep}{Style.RESET}", flush=True)
        print(f"\n{text}\n", flush=True)

    def total(self):
        """Print pipeline total time at the end."""
        elapsed = time.time() - self._pipeline_start
        if self._phase_count > 0:
            print(f"\n  {Style.BOLD}⏱️  Pipeline total:{Style.RESET} {elapsed:.3f}s  "
                  f"({Style.DIM}{self._phase_count} phases{Style.RESET})", flush=True)
        else:
            print(f"\n  {Style.BOLD}⏱️  Pipeline total:{Style.RESET} {elapsed:.3f}s", flush=True)

    def multi_step(self, items: list):
        """Print a compact multi-step block (e.g. skills that ran)."""
        if not items:
            return
        print(f"    {Style.GRAY}Skills executed:{Style.RESET}", flush=True)
        for item in items:
            print(f"      {Style.DIM}•{Style.RESET} {item}", flush=True)

    def note(self, message: str, emoji: str = '💬'):
        """Print an inline note outside any phase."""
        print(f"\n  {Style.DIM}{emoji}  {message}{Style.RESET}", flush=True)

    def status(self, message: str, emoji: str = '🔧'):
        """Print a live real-time status line outside any phase.

        This is the primary mechanism for showing WHAT the system is doing
        *right now* — used by the Planner to emit descriptive, continuous
        status messages instead of just discrete phase boundaries.

        Example output::

            🔧   Status: Ejecutando menu-query — consultando plato del día
            📊   Status: Procesando resultado de classify...
            💬   Status: Generando respuesta final...

        Args:
            message: Descriptive text of current action.
            emoji: Emoji to prefix the status (🤔 🔧 📊 💬).
        """
        print(f"  {emoji}  {Style.BOLD}Status:{Style.RESET} {message}", flush=True)

    def fire_and_forget(self, message: str):
        """Print a fire-and-forget notification (background task)."""
        print(f"    {Style.YELLOW}🔥{Style.RESET} {message}", flush=True)

    def _print_phase_header(self, name: str, emoji: str, phase_index: int):
        """Print the phase header with numbering."""
        numbered = f"  {Style.BOLD}▸ {emoji}  {phase_index}. {name}{Style.RESET}"
        _wprint('')
        _wprint(numbered)
        _wprint(f"  {Style.DIM}{'─' * 48}{Style.RESET}")

    # ── Internal helpers ─────────────────────────────────────────────────

    def _print_phase_header(self, name: str, emoji: str, phase_index: int):
        """Print the phase header with numbering."""
        numbered = f"  {Style.BOLD}▸ {emoji}  {phase_index}. {name}{Style.RESET}"
        _wprint('')
        _wprint(numbered)
        _wprint(f"  {Style.DIM}{'─' * 48}{Style.RESET}")
