"""采集任务业务规则：状态流转、准入校验与筛选口径都收在这里。

任务提交调度和启动任务都不能只看前端展示的状态：每次动作在锁内重新读取采集源与解析规则的
已落库状态，并确认任务自身的调度配置完整，任一条件不满足都不写入任何状态。
"""
from __future__ import annotations

from typing import Any

from app.services.admission import (
    TASK_FIELDS,
    evaluate_task,
    missing_fields,
    text,
)
from app.services.locks import entry_lock, module_lock, workflow_lock
from app.services.transitions import apply_status, transition_error
from app.store import store

MODULE = "taskcrawl"
REQUIRED_FIELDS = ["任务编号", "采集源名称", "规则编号"]
STATUS_ORDER = ["草稿", "待调度", "执行中", "已完成", "已终止"]
ACTION_RULES = {"提交调度": "待调度", "启动任务": "执行中", "终止任务": "已终止"}
# 启动任务只能从待调度进入；已完成是终态，只能显式终止执行中的任务。
ALLOWED_FROM = {
    "待调度": {"草稿"},
    "执行中": {"待调度"},
    "已终止": {"草稿", "待调度", "执行中"},
}
TERMINAL_STATUSES: set[str] = {"已完成"}
NEGATIVE_ACTIONS: set[str] = {"终止任务"}
# 提交调度和启动任务都必须先通过准入校验。
ADMISSION_ACTIONS = {"提交调度", "启动任务"}


class TaskcrawlService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def evaluate(self, task: dict[str, Any]) -> dict[str, Any]:
        """任务准入结论：列表、详情和动作接口共用同一份校验口径。"""
        return evaluate_task(task)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = missing_fields(values, REQUIRED_FIELDS)
        if missing:
            return None, missing
        with entry_lock(MODULE, 0), module_lock(MODULE):
            rows = store.rows(MODULE)
            entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            for field in TASK_FIELDS:
                if field in values:
                    entry[field] = text(values.get(field))
            entry["status"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        """执行采集任务动作：准入校验与状态写入在同一把锁内完成，失败时不留半套状态。"""
        with entry_lock(MODULE, entry_id), workflow_lock():
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"采集任务 {entry_id} 不存在"
            if action not in ACTION_RULES:
                return None, f"动作「{action}」不属于采集任务可执行范围"
            target = ACTION_RULES[action]
            if target not in STATUS_ORDER:
                return None, f"目标状态「{target}」不在允许的状态序列里"
            code = text(entry.get("任务编号")) or f"采集任务 {entry_id}"
            reason = transition_error(
                label=code,
                current=entry.get("status"),
                target=target,
                status_order=STATUS_ORDER,
                allowed_from=ALLOWED_FROM,
                terminal_statuses=TERMINAL_STATUSES,
            )
            if reason:
                return None, reason
            admission: dict[str, Any] | None = None
            if action in ADMISSION_ACTIONS:
                admission = self.evaluate(entry)
                if not admission["allowed"]:
                    return None, f"{code} 不能{action}：" + "；".join(admission["reasons"])
            apply_status(
                entry,
                status_order=STATUS_ORDER,
                target=target,
                abnormal=action in NEGATIVE_ACTIONS,
            )
            if admission is not None:
                # 准入已通过，把同一份结论固化到任务上，详情页不再各自推导。
                entry["admission"] = admission
                entry["config_ready"] = True
            return entry, f"{code} 已{action}，当前状态为「{target}」"
