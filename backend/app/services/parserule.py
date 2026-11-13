"""解析规则业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.services.admission import (
    PARSERULE_FIELDS,
    RULE_VALIDATION_FIELDS,
    missing_fields,
    text,
)
from app.services.locks import entry_lock, module_lock, workflow_lock
from app.services.transitions import apply_status, transition_error
from app.store import store

MODULE = "parserule"
REQUIRED_FIELDS = ["规则编号", "页面选择器", "内容选择器"]
STATUS_ORDER = ["草稿", "规则验证中", "已启用", "已废弃"]
ACTION_RULES = {"提交规则验证": "规则验证中", "启用规则": "已启用", "废弃规则": "已废弃"}
# 启用规则只能从「规则验证中」进入：验证通过是启用前提，不能从草稿直接启用。
ALLOWED_FROM = {
    "规则验证中": {"草稿"},
    "已启用": {"规则验证中"},
    "已废弃": {"草稿", "规则验证中", "已启用"},
}
TERMINAL_STATUSES: set[str] = set()
NEGATIVE_ACTIONS: set[str] = set()


class ParseruleService:
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
            rows = [row for row in rows if keyword in str(row.get("规则编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = missing_fields(values, REQUIRED_FIELDS)
        if missing:
            return None, missing
        with entry_lock(MODULE, 0), module_lock(MODULE):
            rows = store.rows(MODULE)
            entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            for field in PARSERULE_FIELDS:
                if field in values:
                    entry[field] = text(values.get(field))
            entry["status"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        """执行解析规则动作：校验与写入在同一把锁内完成，失败时不改动任何字段。"""
        with entry_lock(MODULE, entry_id), workflow_lock():
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"解析规则 {entry_id} 不存在"
            if action not in ACTION_RULES:
                return None, f"动作「{action}」不属于解析规则可执行范围"
            target = ACTION_RULES[action]
            if target not in STATUS_ORDER:
                return None, f"目标状态「{target}」不在允许的状态序列里"
            code = text(entry.get("规则编号")) or f"解析规则 {entry_id}"
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
            if target == "已启用":
                missing = missing_fields(entry, RULE_VALIDATION_FIELDS)
                if missing:
                    return None, (
                        f"{code} 缺少验证字段：{'、'.join(missing)}，"
                        f"规则验证未完成，不能启用规则"
                    )
            apply_status(
                entry,
                status_order=STATUS_ORDER,
                target=target,
                abnormal=action in NEGATIVE_ACTIONS,
            )
            return entry, f"{code} 已{action}，当前状态为「{target}」"
