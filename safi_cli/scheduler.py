"""Local task scheduling and prompt queuing for the SAFi CLI.

Runs completely client-side inside safi-cli. Tools execute locally in the CLI
environment, so tasks and queues are managed here without server dependencies.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SCHEDULES_FILE = Path.home() / ".config" / "safi" / "schedules.json"


def parse_time_offset(time_str: str) -> Optional[float]:
    """Parse human duration string into seconds (e.g. '30s', '5m', '2h', '1d', '90').

    Returns seconds as a float, or None if invalid.
    """
    s = time_str.strip().lower()
    if not s:
        return None

    # Plain integer or float seconds
    try:
        val = float(s)
        return max(1.0, val)
    except ValueError:
        pass

    # Multi-unit parsing (e.g. '1h30m' or '5m')
    pattern = re.compile(r"(\d+(?:\.\d+)?)\s*([smhd])")
    matches = pattern.findall(s)
    if not matches:
        return None

    unit_multipliers = {
        "s": 1.0,
        "m": 60.0,
        "h": 3600.0,
        "d": 86400.0,
    }

    total_seconds = 0.0
    for amount_str, unit in matches:
        try:
            total_seconds += float(amount_str) * unit_multipliers[unit]
        except ValueError:
            return None

    return max(1.0, total_seconds) if total_seconds > 0 else None


def format_remaining_time(seconds: float) -> str:
    """Format seconds remaining into concise human string (e.g. '45s', '12m', '1h 20m')."""
    if seconds <= 0:
        return "due now"
    secs = int(round(seconds))
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    rem_secs = secs % 60
    if mins < 60:
        return f"{mins}m" if rem_secs == 0 else f"{mins}m {rem_secs}s"
    hrs = mins // 60
    rem_mins = mins % 60
    if hrs < 24:
        return f"{hrs}h" if rem_mins == 0 else f"{hrs}h {rem_mins}m"
    days = hrs // 24
    rem_hrs = hrs % 24
    return f"{days}d" if rem_hrs == 0 else f"{days}d {rem_hrs}h"


@dataclass
class QueuedPrompt:
    """A prompt waiting to be executed by the CLI agent loop."""
    id: str
    prompt: str
    source: str = "user"  # "user" | "scheduled" | "cron"
    created_at: float = field(default_factory=time.time)
    agent: Optional[str] = None
    task_id: Optional[str] = None


@dataclass
class ScheduledTask:
    """A scheduled task managed locally in safi-cli."""
    id: str
    prompt: str
    run_at: float
    created_at: float = field(default_factory=time.time)
    interval_seconds: Optional[float] = None
    agent: Optional[str] = None
    label: str = ""
    status: str = "pending"  # "pending" | "running" | "completed" | "cancelled"
    repeat: bool = False

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.run_at - time.time())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduledTask":
        return cls(
            id=data["id"],
            prompt=data["prompt"],
            run_at=data["run_at"],
            created_at=data.get("created_at", time.time()),
            interval_seconds=data.get("interval_seconds"),
            agent=data.get("agent"),
            label=data.get("label", ""),
            status=data.get("status", "pending"),
            repeat=data.get("repeat", False),
        )


class PromptQueue:
    """Thread-safe FIFO queue for prompts awaiting agent turn execution."""

    def __init__(self) -> None:
        self._queue: queue.Queue[QueuedPrompt] = queue.Queue()
        self._lock = threading.RLock()
        self._items: List[QueuedPrompt] = []

    def put(self, prompt: str, source: str = "user", agent: Optional[str] = None, task_id: Optional[str] = None) -> QueuedPrompt:
        item = QueuedPrompt(
            id=str(uuid.uuid4())[:8],
            prompt=prompt,
            source=source,
            agent=agent,
            task_id=task_id,
        )
        with self._lock:
            self._items.append(item)
        self._queue.put(item)
        return item

    def get(self, block: bool = True, timeout: Optional[float] = None) -> Optional[QueuedPrompt]:
        try:
            item = self._queue.get(block=block, timeout=timeout)
            with self._lock:
                if item in self._items:
                    self._items.remove(item)
            return item
        except queue.Empty:
            return None

    def peek_all(self) -> List[QueuedPrompt]:
        with self._lock:
            return list(self._items)

    def clear(self) -> int:
        with self._lock:
            count = len(self._items)
            self._items.clear()
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            return count

    def size(self) -> int:
        with self._lock:
            return len(self._items)

    def is_empty(self) -> bool:
        return self.size() == 0


class TaskScheduler:
    """Background scheduler managing local timers and recurring tasks."""

    def __init__(self, prompt_queue: PromptQueue) -> None:
        self.prompt_queue = prompt_queue
        self._tasks: Dict[str, ScheduledTask] = {}
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._wakeup_callback: Optional[Callable[[], Any]] = None
        self._load_persisted_tasks()
        self._start_worker()

    def set_wakeup_callback(self, cb: Callable[[], Any]) -> None:
        """Register callback invoked when a scheduled task is triggered and queued."""
        self._wakeup_callback = cb

    def _start_worker(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="safi-scheduler")
            self._thread.start()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            now = time.time()
            due_tasks: List[ScheduledTask] = []

            with self._lock:
                for task in list(self._tasks.values()):
                    if task.status == "pending" and task.run_at <= now:
                        due_tasks.append(task)
                        if task.repeat and task.interval_seconds:
                            task.run_at = now + task.interval_seconds
                        else:
                            task.status = "completed"

            for task in due_tasks:
                logger.info("Executing scheduled task %s: %s", task.id, task.prompt)
                self.prompt_queue.put(
                    prompt=task.prompt,
                    source="scheduled",
                    agent=task.agent,
                    task_id=task.id,
                )

            if due_tasks:
                self._save_persisted_tasks()
                if self._wakeup_callback:
                    try:
                        self._wakeup_callback()
                    except Exception as exc:
                        logger.debug("Wakeup callback failed: %s", exc)

            self._stop_event.wait(1.0)

    def schedule_once(
        self,
        delay_seconds: float,
        prompt: str,
        label: str = "",
        agent: Optional[str] = None,
    ) -> ScheduledTask:
        task_id = f"task-{uuid.uuid4().hex[:6]}"
        task = ScheduledTask(
            id=task_id,
            prompt=prompt,
            run_at=time.time() + delay_seconds,
            agent=agent,
            label=label or (prompt[:30] + "..." if len(prompt) > 30 else prompt),
            status="pending",
            repeat=False,
        )
        with self._lock:
            self._tasks[task_id] = task
        self._save_persisted_tasks()
        return task

    def schedule_recurring(
        self,
        interval_seconds: float,
        prompt: str,
        label: str = "",
        agent: Optional[str] = None,
    ) -> ScheduledTask:
        task_id = f"cron-{uuid.uuid4().hex[:6]}"
        task = ScheduledTask(
            id=task_id,
            prompt=prompt,
            run_at=time.time() + interval_seconds,
            interval_seconds=interval_seconds,
            agent=agent,
            label=label or (prompt[:30] + "..." if len(prompt) > 30 else prompt),
            status="pending",
            repeat=True,
        )
        with self._lock:
            self._tasks[task_id] = task
        self._save_persisted_tasks()
        return task

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].status = "cancelled"
                del self._tasks[task_id]
                self._save_persisted_tasks()
                return True
        return False

    def list_active_tasks(self) -> List[ScheduledTask]:
        with self._lock:
            active = [t for t in self._tasks.values() if t.status == "pending"]
            active.sort(key=lambda t: t.run_at)
            return active

    def list_all_tasks(self) -> List[ScheduledTask]:
        with self._lock:
            tasks = list(self._tasks.values())
            tasks.sort(key=lambda t: t.run_at)
            return tasks

    def get_next_task(self) -> Optional[ScheduledTask]:
        active = self.list_active_tasks()
        return active[0] if active else None

    def _save_persisted_tasks(self) -> None:
        try:
            SCHEDULES_FILE.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                # Only persist recurring tasks or pending future one-shot tasks
                to_save = [
                    t.to_dict()
                    for t in self._tasks.values()
                    if t.status == "pending" and (t.repeat or t.remaining_seconds > 0)
                ]
            tmp_file = SCHEDULES_FILE.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(to_save, f, indent=2)
            os.replace(tmp_file, SCHEDULES_FILE)
        except Exception as exc:
            logger.debug("Could not persist scheduled tasks: %s", exc)

    def _load_persisted_tasks(self) -> None:
        if not SCHEDULES_FILE.exists():
            return
        try:
            with open(SCHEDULES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            now = time.time()
            with self._lock:
                for item in data:
                    task = ScheduledTask.from_dict(item)
                    if task.status == "pending":
                        # If a one-shot task expired while CLI was closed, skip it
                        if not task.repeat and task.run_at <= now:
                            continue
                        # If a repeating task expired, schedule next from now
                        if task.repeat and task.run_at <= now and task.interval_seconds:
                            task.run_at = now + task.interval_seconds
                        self._tasks[task.id] = task
        except Exception as exc:
            logger.debug("Could not load persisted schedules: %s", exc)

    def shutdown(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)


_GLOBAL_QUEUE: Optional[PromptQueue] = None
_GLOBAL_SCHEDULER: Optional[TaskScheduler] = None
_AGENT_BUSY_EVENT = threading.Event()
_CURRENT_RUNNING_PROMPT = ""
_CURRENT_TURN_STATUS = ""
_CURRENT_START_TIME: Optional[float] = None


def set_turn_status(status: str) -> None:
    """Set the human-readable live status string of the current turn."""
    global _CURRENT_TURN_STATUS
    _CURRENT_TURN_STATUS = status


def get_turn_status() -> str:
    """Get the human-readable live status string of the current turn."""
    return _CURRENT_TURN_STATUS or "Thinking"


def set_agent_status_text(text: str) -> None:
    set_turn_status(text)


def get_agent_status_text() -> str:
    return get_turn_status()


def set_agent_busy(busy: bool, prompt: str = "") -> None:
    """Update whether an agent turn is actively executing."""
    global _CURRENT_RUNNING_PROMPT, _CURRENT_TURN_STATUS, _CURRENT_START_TIME
    _CURRENT_RUNNING_PROMPT = prompt if busy else ""
    if busy:
        _CURRENT_START_TIME = time.time()
        _AGENT_BUSY_EVENT.set()
    else:
        _CURRENT_START_TIME = None
        _CURRENT_TURN_STATUS = ""
        _AGENT_BUSY_EVENT.clear()


def get_agent_elapsed_time() -> Optional[float]:
    """Get elapsed seconds since the current turn began."""
    if _CURRENT_START_TIME:
        return time.time() - _CURRENT_START_TIME
    return None


def is_agent_busy() -> bool:
    """Check if an agent turn is actively executing."""
    return _AGENT_BUSY_EVENT.is_set()


def get_running_prompt() -> str:
    """Get the prompt text of the currently executing agent turn."""
    return _CURRENT_RUNNING_PROMPT


def get_prompt_queue() -> PromptQueue:
    global _GLOBAL_QUEUE
    if _GLOBAL_QUEUE is None:
        _GLOBAL_QUEUE = PromptQueue()
    return _GLOBAL_QUEUE


def get_scheduler() -> TaskScheduler:
    global _GLOBAL_SCHEDULER
    if _GLOBAL_SCHEDULER is None:
        _GLOBAL_SCHEDULER = TaskScheduler(get_prompt_queue())
    return _GLOBAL_SCHEDULER
