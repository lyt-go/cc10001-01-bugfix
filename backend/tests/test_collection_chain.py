"""采集链路回归测试：状态流转、准入校验、配置贯通与并发提交。

运行：cd backend && .venv/bin/python -m pytest tests -q
"""
from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import SEED_ROWS
from app.store import store


@pytest.fixture(autouse=True)
def reset_store() -> Iterator[None]:
    """每个用例从同一份示例数据出发，避免用例之间互相污染状态。"""
    store._tables = {name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()}
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def act(client: TestClient, module: str, entry_id: int, action: str) -> dict:
    return client.post(
        f"/api/{module}/{entry_id}/actions", json={"values": {"action": action}}
    ).json()


def entry_of(client: TestClient, module: str, entry_id: int) -> dict:
    return client.get(f"/api/{module}/{entry_id}").json()


DATA_0721 = 4
PARS_0314 = 4
TASK_2048 = 4


def online_source(client: TestClient, entry_id: int = DATA_0721) -> None:
    assert act(client, "datasource", entry_id, "发起连通测试")["ok"]
    assert act(client, "datasource", entry_id, "标记上线")["ok"]


def enable_rule(client: TestClient, entry_id: int = PARS_0314) -> None:
    """PARS-0314 初始处于「规则验证中」，验证通过后即可启用。"""
    assert act(client, "parserule", entry_id, "启用规则")["ok"]


# ---------- 采集源状态机 ----------


def test_datasource_rejects_skipping_and_reverse(client: TestClient) -> None:
    skipped = act(client, "datasource", DATA_0721, "标记上线")
    assert skipped["ok"] is False
    assert "跳级" in skipped["message"] or "只能推进到" in skipped["message"]
    assert "草稿" == entry_of(client, "datasource", DATA_0721)["status"]

    online_source(client)
    reversed_ = act(client, "datasource", DATA_0721, "发起连通测试")
    assert reversed_["ok"] is False
    assert "已处于「已上线」" in reversed_["message"] or "不允许" in reversed_["message"]
    assert "已上线" == entry_of(client, "datasource", DATA_0721)["status"]

    duplicate = act(client, "datasource", DATA_0721, "标记上线")
    assert duplicate["ok"] is False
    assert "无需重复推进" in duplicate["message"]
    assert "已上线" == entry_of(client, "datasource", DATA_0721)["status"]


def test_datasource_archived_cannot_come_back(client: TestClient) -> None:
    online_source(client)
    assert act(client, "datasource", DATA_0721, "归档源配置")["ok"]
    reopened = act(client, "datasource", DATA_0721, "标记上线")
    assert reopened["ok"] is False
    assert "终态" in reopened["message"] and "不允许" in reopened["message"]
    retested = act(client, "datasource", DATA_0721, "发起连通测试")
    assert retested["ok"] is False
    assert entry_of(client, "datasource", DATA_0721)["status"] == "已归档"


def test_datasource_action_does_not_leak_partial_state(client: TestClient) -> None:
    before = dict(entry_of(client, "datasource", DATA_0721))
    act(client, "datasource", DATA_0721, "标记上线")
    after = entry_of(client, "datasource", DATA_0721)
    assert after == before


def test_datasource_unknown_action_is_rejected(client: TestClient) -> None:
    result = act(client, "datasource", DATA_0721, "直接上线")
    assert result["ok"] is False
    assert "不属于采集源登记可执行范围" in result["message"]
    assert entry_of(client, "datasource", DATA_0721)["status"] == "草稿"


# ---------- 解析规则状态机 ----------


def test_parserule_initial_verification_state_can_be_enabled(client: TestClient) -> None:
    """PARS-0314 已在规则验证中，验证字段齐全，允许启用。"""
    assert act(client, "parserule", PARS_0314, "启用规则")["ok"] is True
    assert entry_of(client, "parserule", PARS_0314)["status"] == "已启用"


def test_parserule_cannot_enable_without_validation(client: TestClient) -> None:
    """PARS-0001 还在草稿，必须先提交规则验证，不能直接启用。"""
    enable_from_draft = act(client, "parserule", 1, "启用规则")
    assert enable_from_draft["ok"] is False
    assert "只能推进到「规则验证中」" in enable_from_draft["message"]
    assert entry_of(client, "parserule", 1)["status"] == "草稿"

    assert act(client, "parserule", 1, "提交规则验证")["ok"] is True
    assert act(client, "parserule", 1, "废弃规则")["ok"] is True
    assert act(client, "parserule", 1, "启用规则")["ok"] is False
    assert entry_of(client, "parserule", 1)["status"] == "已废弃"


# ---------- 任务准入 ----------


def test_task_submit_blocked_when_rule_not_enabled(client: TestClient) -> None:
    online_source(client)
    detail = entry_of(client, "taskcrawl", TASK_2048)
    assert detail["admission"]["allowed"] is False
    assert detail["admission"]["datasource_online"] is True
    assert detail["admission"]["rule_enabled"] is False
    blocked = act(client, "taskcrawl", TASK_2048, "提交调度")
    assert blocked["ok"] is False
    assert PARS_0314 and "PARS-0314" in blocked["message"]
    assert entry_of(client, "taskcrawl", TASK_2048)["status"] == "草稿"


def test_task_submit_blocked_when_source_not_online(client: TestClient) -> None:
    enable_rule(client)
    blocked = act(client, "taskcrawl", TASK_2048, "提交调度")
    assert blocked["ok"] is False
    assert "DATA-0721" in blocked["message"] and "未达到「已上线」" in blocked["message"]
    assert entry_of(client, "taskcrawl", TASK_2048)["status"] == "草稿"


def test_task_admission_rechecks_persisted_state_not_frontend(client: TestClient) -> None:
    """前端即使把任务行展示为已上线、已启用，后端仍按落库状态判定。"""
    online_source(client)
    enable_rule(client)
    assert act(client, "taskcrawl", TASK_2048, "提交调度")["ok"]

    # 调度完成后采集源被归档，启动任务必须重新校验并拒绝，任务状态不得前进。
    assert act(client, "datasource", DATA_0721, "归档源配置")["ok"]
    detail = entry_of(client, "taskcrawl", TASK_2048)
    assert detail["status"] == "待调度"
    assert detail["admission"]["allowed"] is False
    started = act(client, "taskcrawl", TASK_2048, "启动任务")
    assert started["ok"] is False
    assert entry_of(client, "taskcrawl", TASK_2048)["status"] == "待调度"


def test_task_full_flow_produces_consistent_config(client: TestClient) -> None:
    online_source(client)
    enable_rule(client)
    assert act(client, "taskcrawl", TASK_2048, "提交调度")["ok"]
    assert act(client, "taskcrawl", TASK_2048, "启动任务")["ok"]

    detail = entry_of(client, "taskcrawl", TASK_2048)
    assert detail["status"] == "执行中"
    assert detail["config_ready"] is True
    admission = detail["admission"]
    assert admission["allowed"] is True
    config = admission["config"]

    source = config["采集源"]
    assert source["源端编号"] == "DATA-0721"
    assert source["入口URL"] == "https://public.example.org/catalog/"
    assert source["请求方式"] == "GET"
    assert source["字符编码"] == "GB18030"
    assert source["访问频率"] == "每两秒一次"
    assert source["超时秒数"] == "12"
    assert source["status"] == "已上线"

    rule = config["解析规则"]
    assert rule["规则编号"] == "PARS-0314"
    assert rule["属性提取器"] and rule["列表容错"]
    assert rule["空值占位符"] == "-"
    assert rule["输出字段映射"]
    assert rule["status"] == "已启用"

    schedule = config["调度配置"]
    assert schedule["调度周期"] == "每 30 分钟增量采集一次"
    assert schedule["增量字段"] == "updated_at"
    assert schedule["批次大小"] == "500"
    assert schedule["起始水位"] == "2026-07-01T00:00:00+08:00"
    assert schedule["截止水位"] == "2026-07-21T23:59:59+08:00"


def test_task_list_and_detail_share_same_admission(client: TestClient) -> None:
    online_source(client)
    detail = entry_of(client, "taskcrawl", TASK_2048)
    listed = next(
        row
        for row in client.get("/api/taskcrawl").json()["items"]
        if row["任务编号"] == "TASK-2048"
    )
    assert listed["admission"] == detail["admission"]
    assert listed["status"] == detail["status"]


# ---------- 并发 ----------


def test_concurrent_datasource_online_only_one_succeeds(client: TestClient) -> None:
    assert act(client, "datasource", DATA_0721, "发起连通测试")["ok"]
    results: list[dict] = []
    barrier = threading.Barrier(8)

    def submit() -> None:
        barrier.wait()
        results.append(act(client, "datasource", DATA_0721, "标记上线"))

    threads = [threading.Thread(target=submit) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(1 for result in results if result["ok"]) == 1
    assert sum(1 for result in results if not result["ok"]) == 7
    assert entry_of(client, "datasource", DATA_0721)["status"] == "已上线"
    # 只有成功那一次带状态变更，失败请求返回的状态与落库一致。
    for result in results:
        if not result["ok"]:
            assert result["entry"]["status"] == "已上线"


def test_concurrent_task_submit_only_one_succeeds(client: TestClient) -> None:
    online_source(client)
    enable_rule(client)
    results: list[dict] = []
    barrier = threading.Barrier(8)

    def submit() -> None:
        barrier.wait()
        results.append(act(client, "taskcrawl", TASK_2048, "提交调度"))

    threads = [threading.Thread(target=submit) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(1 for result in results if result["ok"]) == 1
    assert entry_of(client, "taskcrawl", TASK_2048)["status"] == "待调度"
    assert entry_of(client, "taskcrawl", TASK_2048)["config_ready"] is True
