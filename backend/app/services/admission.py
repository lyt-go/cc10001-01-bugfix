"""采集链路准入校验：采集源、解析规则、采集任务共用同一套判定口径。

页面上的「已上线」「已启用」只是已落库状态的展示，不能作为准入依据。任务提交调度和启动时
统一调用这里重新读取采集源与解析规则的最新状态，并确认任务自身的调度配置完整，任何一项
不满足都返回带原因的不通过结论，调用方不做任何状态写入。
"""
from __future__ import annotations

from typing import Any

from app.store import store

DATASOURCE_MODULE = "datasource"
PARSERULE_MODULE = "parserule"

DATASOURCE_ONLINE = "已上线"
RULE_ENABLED = "已启用"

# 采集源上线与任务执行都需要的接入配置：上线前至少要求登记字段完整，
# 其余接入参数在准入结论里原样带给任务，保证执行时用的是同一份配置。
DATASOURCE_REQUIRED_FIELDS = ["源端编号", "目标域名", "入口URL"]
DATASOURCE_CONFIG_FIELDS = ["入口URL", "请求方式", "字符编码", "访问频率", "超时秒数"]
# 规则验证必须确认的抽取配置，缺任何一项都不能视为验证通过。
RULE_VALIDATION_FIELDS = ["属性提取器", "列表容错", "空值占位符", "输出字段映射"]
# 任务提交调度后，真正执行时依赖的增量与批次配置。
TASK_BINDING_FIELDS = ["调度周期", "增量字段", "批次大小", "起始水位", "截止水位"]

DATASOURCE_FIELDS = [
    "源端编号",
    "目标域名",
    "入口URL",
    "请求方式",
    "字符编码",
    "访问频率",
    "超时秒数",
    "归属项目",
]
PARSERULE_FIELDS = [
    "规则编号",
    "页面选择器",
    "内容选择器",
    "属性提取器",
    "列表容错",
    "空值占位符",
    "字符清洗正则",
    "输出字段映射",
]
TASK_FIELDS = [
    "任务编号",
    "采集源名称",
    "规则编号",
    "调度周期",
    "增量字段",
    "批次大小",
    "起始水位",
    "截止水位",
]


def text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def missing_fields(row: dict[str, Any], fields: list[str]) -> list[str]:
    return [field for field in fields if not text(row.get(field))]


def _find_by(module: str, field: str, code: str) -> dict[str, Any] | None:
    if not code:
        return None
    for row in store.rows(module):
        if text(row.get(field)) == code:
            return row
    return None


def find_datasource(code: str) -> dict[str, Any] | None:
    """按源端编号查找采集源；兼容用目标域名引用的历史数据。"""
    row = _find_by(DATASOURCE_MODULE, "源端编号", code)
    if row is None:
        row = _find_by(DATASOURCE_MODULE, "目标域名", code)
    return row


def find_parserule(code: str) -> dict[str, Any] | None:
    return _find_by(PARSERULE_MODULE, "规则编号", code)


def datasource_config_reasons(row: dict[str, Any], code: str) -> list[str]:
    """采集源能否标记上线：只检查接入配置是否完整，不要求已经是「已上线」。"""
    missing = missing_fields(row, DATASOURCE_REQUIRED_FIELDS)
    if not missing:
        return []
    return [
        f"采集源 {code} 缺少登记字段：{'、'.join(missing)}，无法形成可用的接入配置"
    ]


def evaluate_datasource(row: dict[str, Any] | None, code: str | None = None) -> dict[str, Any]:
    """判定一个采集源能否被采集任务引用，只依据已落库状态和配置完整度。"""
    resolved_code = text(code) or (text(row.get("源端编号")) if row else "")
    if row is None:
        return {
            "code": resolved_code,
            "found": False,
            "status": None,
            "online": False,
            "missing_fields": [],
            "ready": False,
            "reasons": [f"采集源「{resolved_code or '未填写'}」不存在，无法确认上线状态"],
        }

    status = text(row.get("status"))
    missing = missing_fields(row, DATASOURCE_REQUIRED_FIELDS)
    config_missing = missing_fields(row, DATASOURCE_CONFIG_FIELDS)
    reasons: list[str] = []
    if status != DATASOURCE_ONLINE:
        reasons.append(
            f"采集源 {resolved_code} 当前状态为「{status or '未知'}」，"
            f"未达到「{DATASOURCE_ONLINE}」，不能作为采集任务的接入源"
        )
    reasons.extend(datasource_config_reasons(row, resolved_code))
    return {
        "code": resolved_code,
        "found": True,
        "status": status,
        "online": status == DATASOURCE_ONLINE,
        "missing_fields": missing,
        "config_missing_fields": config_missing,
        "ready": not reasons,
        "reasons": reasons,
    }


def evaluate_parserule(row: dict[str, Any] | None, code: str | None = None) -> dict[str, Any]:
    """判定一条解析规则能否被采集任务引用，只依据已落库状态和验证配置完整度。"""
    resolved_code = text(code) or (text(row.get("规则编号")) if row else "")
    if row is None:
        return {
            "code": resolved_code,
            "found": False,
            "status": None,
            "enabled": False,
            "missing_fields": [],
            "valid": False,
            "ready": False,
            "reasons": [f"解析规则「{resolved_code or '未填写'}」不存在，无法确认启用状态"],
        }

    status = text(row.get("status"))
    missing = missing_fields(row, RULE_VALIDATION_FIELDS)
    reasons: list[str] = []
    if status != RULE_ENABLED:
        reasons.append(
            f"解析规则 {resolved_code} 当前状态为「{status or '未知'}」，"
            f"未达到「{RULE_ENABLED}」，不能用于采集任务抽取"
        )
    if missing:
        reasons.append(
            f"解析规则 {resolved_code} 缺少验证字段：{'、'.join(missing)}，规则验证未通过"
        )
    return {
        "code": resolved_code,
        "found": True,
        "status": status,
        "enabled": status == RULE_ENABLED,
        "missing_fields": missing,
        "valid": not missing,
        "ready": not reasons,
        "reasons": reasons,
    }


def _build_config(
    task: dict[str, Any],
    source: dict[str, Any] | None,
    rule: dict[str, Any] | None,
) -> dict[str, Any]:
    """任务执行所需的完整抽取配置：请求接入参数 + 规则抽取参数 + 调度批次参数。"""
    return {
        "任务编号": text(task.get("任务编号")),
        "采集源": {
            "源端编号": text(source.get("源端编号")) if source else "",
            "目标域名": text(source.get("目标域名")) if source else "",
            "入口URL": text(source.get("入口URL")) if source else "",
            "请求方式": text(source.get("请求方式")) if source else "",
            "字符编码": text(source.get("字符编码")) if source else "",
            "访问频率": text(source.get("访问频率")) if source else "",
            "超时秒数": text(source.get("超时秒数")) if source else "",
            "status": text(source.get("status")) if source else "",
        },
        "解析规则": {
            "规则编号": text(rule.get("规则编号")) if rule else "",
            "页面选择器": text(rule.get("页面选择器")) if rule else "",
            "内容选择器": text(rule.get("内容选择器")) if rule else "",
            "属性提取器": text(rule.get("属性提取器")) if rule else "",
            "列表容错": text(rule.get("列表容错")) if rule else "",
            "空值占位符": text(rule.get("空值占位符")) if rule else "",
            "字符清洗正则": text(rule.get("字符清洗正则")) if rule else "",
            "输出字段映射": text(rule.get("输出字段映射")) if rule else "",
            "status": text(rule.get("status")) if rule else "",
        },
        "调度配置": {field: text(task.get(field)) for field in TASK_BINDING_FIELDS},
    }


def evaluate_task(task: dict[str, Any]) -> dict[str, Any]:
    """采集任务准入结论：采集源已上线 + 规则已启用 + 任务调度配置完整，三者同时满足。"""
    source_code = text(task.get("采集源名称"))
    rule_code = text(task.get("规则编号"))
    source_row = find_datasource(source_code)
    rule_row = find_parserule(rule_code)
    source_check = evaluate_datasource(source_row, source_code)
    rule_check = evaluate_parserule(rule_row, rule_code)
    task_missing = missing_fields(task, TASK_BINDING_FIELDS)
    task_code = text(task.get("任务编号")) or f"任务 {task.get('id')}"

    reasons: list[str] = []
    reasons.extend(source_check["reasons"])
    reasons.extend(rule_check["reasons"])
    if task_missing:
        reasons.append(
            f"{task_code} 缺少调度配置：{'、'.join(task_missing)}，"
            f"提交调度后无法执行增量批次"
        )

    allowed = bool(source_check["ready"] and rule_check["ready"] and not task_missing)
    config = _build_config(task, source_row, rule_row)
    return {
        "allowed": allowed,
        "结论": "通过" if allowed else "未通过",
        "reasons": reasons,
        "reason": "；".join(reasons),
        "datasource_code": source_code,
        "datasource_status": source_check["status"],
        "datasource_online": source_check["online"],
        "rule_code": rule_code,
        "rule_status": rule_check["status"],
        "rule_enabled": rule_check["enabled"],
        "task_missing_fields": task_missing,
        "config_ready": source_check["ready"] and rule_check["ready"],
        "datasource": source_check,
        "rule": rule_check,
        "config": config,
    }
