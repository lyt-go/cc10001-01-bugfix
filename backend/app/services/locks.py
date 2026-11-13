"""按业务记录粒度提供互斥锁。

同一采集源的上线动作、同一任务的调度动作可能被并发提交。校验和落库必须在同一把锁里完成，
否则两个请求都可能先看到「允许流转」，再先后写入，造成重复推进或半套状态。
"""
from __future__ import annotations

import threading

_registry_guard = threading.Lock()
_registry: dict[str, threading.RLock] = {}


def _lock_for(key: str) -> threading.RLock:
    with _registry_guard:
        lock = _registry.get(key)
        if lock is None:
            lock = threading.RLock()
            _registry[key] = lock
        return lock


def entry_lock(module: str, entry_id: int) -> threading.RLock:
    """返回某条业务记录的互斥锁。"""
    return _lock_for(f"entry:{module}:{entry_id}")


def module_lock(module: str) -> threading.RLock:
    """返回某个业务模块的互斥锁，用于生成编号和追加记录。"""
    return _lock_for(f"module:{module}")


def workflow_lock() -> threading.RLock:
    """采集源、解析规则、采集任务共享的准入锁。

    准入校验要同时读取三张表的最新状态，动作统一串行执行：校验与落库在同一把锁里完成，
    并发提交时只有第一个请求能真正推进状态。
    """
    return _lock_for("workflow")
