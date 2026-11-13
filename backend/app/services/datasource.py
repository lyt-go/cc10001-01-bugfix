"""采集源登记业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.services.admission import DATASOURCE_FIELDS, datasource_config_reasons, missing_fields, text
from app.services.locks import entry_lock, module_lock, workflow_lock
from app.services.transitions import apply_status, transition_error
from app.store import store

MODULE = "datasource"
REQUIRED_FIELDS = ["源端编号", "目标域名", "入口URL"]
STATUS_ORDER = ["草稿", "连通测试中", "已上线", "已归档"]
ACTION_RULES = {"发起连通测试": "连通测试中", "标记上线": "已上线", "归档源配置": "已归档"}
# 每个目标状态允许的前置状态；已归档是终态，不再接受任何动作。
ALLOWED_FROM = {
    "连通测试中": {"草稿"},
    "已上线": {"连通测试中"},
    "已归档": {"连通测试中", "已上线"},
}
TERMINAL_STATUSES: set[str] = set()
NEGATIVE_ACTIONS: set[str] = set()


class DatasourceService:
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
            rows = [row for row in rows if keyword in str(row.get("源端编号", ""))]
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
            for field in DATASOURCE_FIELDS:
                if field in values:
                    entry[field] = text(values.get(field))
            entry["status"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        """执行采集源动作：校验与写入在同一把锁内完成，失败时不改动任何字段。"""
        with entry_lock(MODULE, entry_id), workflow_lock():
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"采集源 {entry_id} 不存在"
            if action not in ACTION_RULES:
                return None, f"动作「{action}」不属于采集源登记可执行范围"
            target = ACTION_RULES[action]
            if target not in STATUS_ORDER:
                return None, f"目标状态「{target}」不在允许的状态序列里"
            code = text(entry.get("源端编号")) or f"采集源 {entry_id}"
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
            if target == "已上线":
                config_reasons = datasource_config_reasons(entry, code)
                if config_reasons:
                    return None, f"{code} 不能标记为「{target}」：" + "；".join(config_reasons)
            apply_status(
                entry,
                status_order=STATUS_ORDER,
                target=target,
                abnormal=action in NEGATIVE_ACTIONS,
            )
            return entry, f"{code} 已{action}，当前状态为「{target}」"
