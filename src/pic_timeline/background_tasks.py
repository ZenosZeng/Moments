from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any, Callable


ProgressCallback = Callable[[str, int, int], None]


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class BackgroundTask:
    def __init__(
        self,
        label: str,
        worker: Callable[[ProgressCallback], dict[str, Any]],
        phases: dict[str, tuple[float, float]],
    ):
        self.label = label
        self.worker = worker
        self.phases = phases
        self._lock = threading.Lock()
        self._revision = 0
        self._result_revision = -1
        self._result: dict[str, Any] | None = None
        self._started = 0.0
        self._status: dict[str, Any] = {
            "state": "idle", "run_id": 0, "message": "尚未运行",
            "started_at": None, "finished_at": None,
            "stage": "", "completed": 0, "total": 0,
            "percent": None, "elapsed_seconds": 0,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            status = dict(self._status)
            if status["state"] == "running":
                status["elapsed_seconds"] = round(time.monotonic() - self._started)
            status["ready"] = self._result is not None and self._result_revision == self._revision
            status["stale"] = self._result_revision != self._revision
            return status

    def result(self) -> dict[str, Any] | None:
        with self._lock:
            return self._result if self._result_revision == self._revision else None

    def invalidate(self) -> None:
        with self._lock:
            self._revision += 1
            self._result = None

    def cache_report(self, reused: int, total: int, unit: str) -> None:
        with self._lock:
            self._status["cache"] = {"reused": reused, "pending": total - reused, "total": total, "unit": unit}

    def start(self) -> bool:
        with self._lock:
            if self._status["state"] == "running":
                return False
            revision = self._revision
            self._started = time.monotonic()
            self._status = {
                "state": "running", "run_id": self._status["run_id"] + 1,
                "message": f"正在{self.label}",
                "started_at": _timestamp(), "finished_at": None,
                "stage": "准备中", "completed": 0, "total": 0,
                "percent": None, "elapsed_seconds": 0,
            }
        try:
            threading.Thread(target=self._run, args=(revision,), daemon=True).start()
        except Exception as exc:
            with self._lock:
                self._status.update({"state": "error", "message": str(exc), "finished_at": _timestamp()})
            raise ValueError(f"无法启动{self.label}：{exc}") from exc
        return True

    def _progress(self, stage: str, completed: int, total: int) -> None:
        lower, upper = self.phases[stage]
        fraction = min(1, completed / total) if total else 1
        with self._lock:
            self._status.update({
                "stage": stage, "completed": completed, "total": total,
                "percent": round(min(99, 100 * (lower + (upper - lower) * fraction)), 1),
                "message": f"{stage}：{completed:,}/{total:,}",
            })

    def _run(self, revision: int) -> None:
        try:
            result = self.worker(self._progress)
            outcome = {
                "state": "complete", "percent": 100,
                "message": result.get("message", f"{self.label}已完成"),
            }
        except Exception as exc:
            result = None
            outcome = {"state": "error", "message": str(exc) or "任务失败"}
        with self._lock:
            if result is not None:
                if self._revision == revision:
                    self._result, self._result_revision = result, revision
                for key in ("counters", "artifacts"):
                    if key in result:
                        outcome[key] = result[key]
            self._status.update({
                **outcome, "finished_at": _timestamp(),
                "elapsed_seconds": round(time.monotonic() - self._started),
            })
