"""状态流转的公共校验：显式前置状态、幂等与终态处理。

所有业务服务都按同一套口径推进状态：
1. 动作必须属于本模块的动作表；
2. 目标状态必须在状态序列里，且当前状态必须在显式声明的允许前置状态里；
3. 已处于目标状态时拒绝重复推进，避免并发请求重复写入；
4. 终态（已归档、已废弃、已终止等）不允许再执行任何动作；
5. 拒绝时带回当前状态、目标状态和允许的下一步，前端可直接展示原因。
"""
from __future__ import annotations

from typing import Any


def transition_error(
    *,
    label: str,
    current: object,
    target: str,
    status_order: list[str],
    allowed_from: dict[str, set[str]],
    terminal_statuses: set[str] | None = None,
) -> str | None:
    """校验一次状态流转。返回 None 表示可以推进，返回字符串表示拒绝原因。

    - 当前状态不在状态序列里：拒绝，说明数据本身已不合法；
    - 当前已是目标状态：拒绝重复推进（并发提交时只有第一个请求生效）；
    - 当前处于终态：拒绝重新上线、回退或再次推进；
    - 目标不是显式声明的前置状态后继：拒绝跳级、倒序和跨状态推进。
    """
    terminal = set(terminal_statuses or set()) | {status_order[-1]}
    current_text = str(current)
    if current_text not in status_order:
        return (
            f"{label}当前状态「{current_text}」不在允许的状态序列"
            f"（{' → '.join(status_order)}）里，无法执行「{target}」"
        )
    if current_text == target:
        return f"{label}已处于「{target}」，无需重复推进（重复提交不会再次生效）"
    if current_text in terminal:
        return (
            f"{label}已处于终态「{current_text}」，不允许再推进到「{target}」；"
            f"如需重新启用，请新建记录"
        )
    if current_text not in allowed_from.get(target, set()):
        next_steps = [current for current, targets in allowed_from.items() if current_text in targets]
        next_text = f"，当前状态只能推进到「{next_steps[0]}」" if next_steps else "，当前状态已是流程终点"
        return (
            f"不允许从「{current_text}」直接变为「{target}」{next_text}；"
            f"状态必须按序流转，不允许跳级或倒序"
        )
    return None


def apply_status(
    entry: dict[str, Any],
    *,
    status_order: list[str],
    target: str,
    abnormal: bool = False,
) -> None:
    """把目标状态写回记录，并同步 pending / abnormal 两个派生标记。"""
    entry["status"] = target
    entry["pending"] = target != status_order[-1]
    entry["abnormal"] = abnormal
