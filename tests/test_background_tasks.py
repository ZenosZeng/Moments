import threading
import time
import pytest

from pic_timeline.background_tasks import BackgroundTask


def wait_finished(task):
    deadline = time.monotonic() + 5
    while task.status()["state"] == "running" and time.monotonic() < deadline:
        time.sleep(.01)
    assert task.status()["state"] != "running"
    return task.status()


def test_progress_duplicate_start_and_snapshot_invalidation():
    entered, release = threading.Event(), threading.Event()

    def worker(progress):
        progress("处理", 2, 10)
        entered.set()
        assert release.wait(5)
        progress("处理", 10, 10)
        return {"data": {"value": "snapshot"}}

    task = BackgroundTask("生成预览", worker, {"处理": (0, .99)})
    assert task.start()
    try:
        assert entered.wait(5)
        assert not task.start()
        status = task.status()
        assert status["completed"] == 2 and status["total"] == 10
        assert status["percent"] == 19.8 and status["state"] == "running"
        task.invalidate()
    finally:
        release.set()
    status = wait_finished(task)
    assert status["state"] == "complete" and status["percent"] == 100
    assert status["stale"] and not status["ready"]
    assert task.result() is None
    assert task.start()
    status = wait_finished(task)
    assert status["run_id"] == 2 and status["ready"]
    assert task.result()["data"] == {"value": "snapshot"}
    assert status["finished_at"] is not None


def test_failure_preserves_processed_count_and_can_retry():
    failed = True

    def worker(progress):
        progress("处理", 1, 3)
        if failed:
            raise ValueError("读取失败")
        progress("处理", 3, 3)
        return {"message": "已完成"}

    task = BackgroundTask("更新索引", worker, {"处理": (0, .99)})
    assert task.start()
    status = wait_finished(task)
    assert status["state"] == "error" and status["message"] == "读取失败"
    assert status["completed"] == 1 and status["percent"] < 100
    assert not status["ready"]
    failed = False
    assert task.start()
    assert wait_finished(task)["state"] == "complete"


def test_thread_launch_failure_does_not_leave_task_running(monkeypatch):
    task = BackgroundTask("更新索引", lambda progress: {}, {})

    def fail(thread):
        raise OSError("线程启动失败")

    monkeypatch.setattr(threading.Thread, "start", fail)
    with pytest.raises(ValueError, match="无法启动"):
        task.start()
    assert task.status()["state"] == "error"
