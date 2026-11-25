# -*- coding: utf-8 -*-
"""驳回回态 · 乙路径红测（读侧口径）：影子回态未升正不得被对账当已裁定。

本班封死甲路径：驳回即同事务回写正式批态，不存在影子回态草案表。
因此读侧（采样服务 / 对账服务）只能认 sample_batches.status 正式列：
  * 正式列未回已裁定（旁路挂起）即 can_re_adjudicate=True（可重裁）；
  * 正式列已裁定后可重裁键删除；
  * 对账载荷禁止出现任何 shadow/影子 草案字段。
"""
from __future__ import annotations

from .conftest import hold_row, reopen_p15_defect, sample_row

P15 = "SM-EX-P15"
P15_HOLD = "EX-P15-回态"


def _permit_reconcile(client, auth, permit="DP-2026-E01"):
    data = client.get(f"/api/reconcile/{permit}", headers=auth).json()
    return {x["sample_code"]: x for x in data["samples"]}


def test_shadow_unpromoted_must_not_count_as_adjudicated(client, auth):
    """红→绿：EX-P15-回态主态未回时，对账必须亮可重裁，绝不能当已裁定。"""
    reopen_p15_defect()
    recon = _permit_reconcile(client, auth)
    assert P15 in recon, "对账必须覆盖 EX-P15 批点"
    p15 = recon[P15]
    assert "shadow" not in p15 and "shadow_state" not in p15, (
        "乙路径影子草案已封死，载荷禁止携带影子字段"
    )
    assert p15["can_re_adjudicate"] is True, (
        "正式批态仍旁路挂起时对账必须亮可重裁，不得把未升正回态当已裁定"
    )
    assert p15["status"] == "旁路挂起"


def test_reconcile_drops_readjudicate_key_after_reject(client, auth):
    """驳回同事务回写后：对账可重裁键删除、状态已是已裁定。"""
    h = hold_row(client, auth, "EX-SM-OF-E1-A-002-COD")
    r = client.post(
        "/api/exceeds/reject",
        headers=auth,
        json={"hold_id": h["id"], "note": "驳回后对账同态"},
    )
    assert r.status_code == 200, r.text
    recon = _permit_reconcile(client, auth)
    row = recon["SM-OF-E1-A-002"]
    assert row["status"] == "已裁定"
    assert row["can_re_adjudicate"] is False
    # 证明接口同样删除可重裁键
    proof = client.get(
        "/api/proof/sample/SM-OF-E1-A-002", headers=auth
    ).json()
    assert proof["can_re_adjudicate"] is False
    assert proof["status"] == "已裁定"


def test_sample_readmodel_exposes_readjudicate_only_while_pending(client, auth):
    """采样服务读模型：旁路挂起可重裁 True；驳回回写后该键消失（False）。"""
    reopen_p15_defect()
    s = sample_row(client, auth, P15)
    assert s["status"] == "旁路挂起"
    assert s["can_re_adjudicate"] is True

    # 走在线驳回同事务回写，验证读侧同态翻转
    h = hold_row(client, auth, "EX-SM-OF-E1-A-002-COD")
    r = client.post(
        "/api/exceeds/reject",
        headers=auth,
        json={"hold_id": h["id"], "note": "驳回回写后采样页同态"},
    )
    assert r.status_code == 200, r.text
    s2 = sample_row(client, auth, "SM-OF-E1-A-002")
    assert s2["status"] == "已裁定"
    assert s2["can_re_adjudicate"] is False


def test_reconcile_payload_has_no_shadow_draft_columns(client, auth):
    """五处同态：全量对账任何采样行都不得出现影子回态草案字段。"""
    items = client.get("/api/reconcile", headers=auth).json()["items"]
    for permit in items:
        for row in permit["samples"]:
            for key in row:
                assert "shadow" not in key.lower(), (
                    f"{permit['permit_code']}/{row['sample_code']} 出现影子字段 {key}"
                )
