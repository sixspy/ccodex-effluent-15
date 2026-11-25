# -*- coding: utf-8 -*-
"""驳回回态 · 甲路径红测：驳回动作须同事务把主批态写成已裁定并清旁路标记。

夹具键 EX-P15-回态：驳回只关挂起（已驳回）而主批态正式列仍停旁路挂起。
本文件用测试器证明当前实现的缺口：
  1. 预置缺陷未在库启动时按同事务口径回写主批态；
  2. 缺少驳回端点 /api/exceeds/reject，无法把驳回与主态回写放进同一事务；
  3. 同事务原子性（整笔回退拒收）没有落点。
"""
from __future__ import annotations

from .conftest import hold_row, sample_row

P15 = "SM-EX-P15"
P15_HOLD = "EX-P15-回态"


def test_p15_fixture_reject_must_write_main_state_back(client, auth):
    """EX-P15-回态：种子入库即应按甲路径把正式批态回写为已裁定。

    红：当前 db 层原样种入缺陷，主批态正式列仍是旁路挂起、裁定时刻为空。
    """
    s = sample_row(client, auth, P15)
    assert s["status"] == "已裁定", (
        "驳回后正式批态未回写已裁定，仍停在 " + s["status"]
    )
    assert s["adjudicated_at"], "回写已裁定时必须落裁定时刻"
    h = hold_row(client, auth, P15_HOLD)
    assert h["status"] == "已驳回"


def test_reject_commits_hold_close_and_main_state_in_one_tx(client, auth):
    """在线驳回：挂起关闭（已驳回）与主批态回写已裁定必须同响应同事务。"""
    h = hold_row(client, auth, "EX-SM-OF-E1-A-002-COD")
    r = client.post(
        "/api/exceeds/reject",
        headers=auth,
        json={"hold_id": h["id"], "note": "驳回回态甲路径当班裁决"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hold_status"] == "已驳回"
    assert body["sample_status"] == "已裁定"
    assert body["sample_adjudicated"] is True
    s = sample_row(client, auth, "SM-OF-E1-A-002")
    assert s["status"] == "已裁定"
    assert s["adjudicated_at"]
    # 旁路标记清除：不再有任何开放挂起
    opens = client.get("/api/exceeds?status=开放", headers=auth).json()["items"]
    assert all(x["sample_code"] != "SM-OF-E1-A-002" for x in opens)


def test_reject_on_closed_hold_is_refused(client, auth):
    """已驳回挂起二次驳回必须拒收（锁守卫 409），不得二次改正式批态。"""
    import sqlite3

    import db

    h = hold_row(client, auth, P15_HOLD)
    before = sample_row(client, auth, P15)
    r = client.post(
        "/api/exceeds/reject",
        headers=auth,
        json={"hold_id": h["id"], "note": "重复驳回"},
    )
    assert r.status_code in (400, 409)
    after = sample_row(client, auth, P15)
    assert after["status"] == before["status"] == "已裁定"
    with sqlite3.connect(db.DB_PATH) as raw:
        n = raw.execute(
            "SELECT COUNT(*) FROM audit_trail WHERE action='exceed_reject' AND target=?",
            (P15,),
        ).fetchone()[0]
    assert n == 0, "拒收路径不得写驳回审计"


def test_reject_rolls_back_whole_ticket_when_sample_missing(client, auth):
    """同事务原子性：主批不存在时整笔回退，挂起行保持原样，不留半截驳回。"""
    import sqlite3

    import db

    h = hold_row(client, auth, "EX-SM-OF-E1-A-002-COD")
    with sqlite3.connect(db.DB_PATH) as raw:
        raw.execute("PRAGMA foreign_keys=OFF")
        raw.execute("DELETE FROM sample_batches WHERE sample_code='SM-OF-E1-A-002'")
        raw.commit()
    r = client.post(
        "/api/exceeds/reject",
        headers=auth,
        json={"hold_id": h["id"], "note": "应整笔回退"},
    )
    assert r.status_code in (404, 400), r.text
    with sqlite3.connect(db.DB_PATH) as raw:
        row = raw.execute(
            "SELECT status FROM exceed_holds WHERE id=?", (h["id"],)
        ).fetchone()
    assert row[0] == "开放", "回退拒收后挂起必须仍是开放，禁止半截关闭"
