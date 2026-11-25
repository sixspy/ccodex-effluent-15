# -*- coding: utf-8 -*-
"""驳回回态 · 争用红测：两路会话同时对同一旁路批点驳回须抢挂起锁。

后到者只记争用痕（contention_log 一条 争用失败），零回态：
不改挂起行、不改正式批态、不写驳回审计。
"""
from __future__ import annotations

import threading

from fastapi.testclient import TestClient

import db
from app import app
from .conftest import hold_row, sample_row

TARGET = "SM-OF-E1-A-002"
TARGET_HOLD = "EX-SM-OF-E1-A-002-COD"


def _token(username, password):
    c = TestClient(app)
    return c.post(
        "/api/login", json={"username": username, "password": password}
    ).json()["token"]


def race_reject(hold_id: int) -> tuple[dict, dict]:
    """并发双请求打同批驳回，返回两路 (status_code, json)。"""
    results: dict[str, dict] = {}
    barrier = threading.Barrier(2)

    def worker(name: str, username: str, password: str) -> None:
        c = TestClient(app)
        token = _token(username, password)
        headers = {"Authorization": "Bearer " + token}
        barrier.wait()
        resp = c.post(
            "/api/exceeds/reject",
            headers=headers,
            json={"hold_id": hold_id, "note": f"race-{name}"},
        )
        try:
            payload = resp.json()
        except Exception:
            payload = {}
        results[name] = {"status": resp.status_code, "body": payload}

    t1 = threading.Thread(target=worker, args=("a", "admin", "admin123"))
    t2 = threading.Thread(target=worker, args=("w", "writer", "writer123"))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)
    return results["a"], results["w"]


def test_race_reject_two_sessions_same_batch(client, auth):
    """两路同批抢驳回：一胜 200 一败 409，败方零回态且留争用痕。"""
    import sqlite3

    h = hold_row(client, auth, TARGET_HOLD)
    first, second = race_reject(h["id"])
    codes = sorted([first["status"], second["status"]])
    assert codes == [200, 409], (first, second)

    winner = first if first["status"] == 200 else second
    loser = second if first["status"] == 200 else first
    assert winner["body"]["sample_status"] == "已裁定"
    assert loser["body"].get("sample_status") != "已裁定", "败方不得回写主态"

    with sqlite3.connect(db.DB_PATH) as raw:
        sample = raw.execute(
            "SELECT status,adjudicated_at FROM sample_batches WHERE sample_code=?",
            (TARGET,),
        ).fetchone()
        hold = raw.execute(
            "SELECT status,closed_at FROM exceed_holds WHERE id=?", (h["id"],)
        ).fetchone()
        contentions = raw.execute(
            "SELECT actor,action FROM contention_log WHERE lock_key=? ORDER BY id",
            (f"sample:{hold_row(client, auth, TARGET_HOLD)['sample_id']}",),
        ).fetchall()
        reject_audits = raw.execute(
            "SELECT COUNT(*) FROM audit_trail WHERE action='exceed_reject'"
        ).fetchone()[0]

    assert sample[0] == "已裁定" and sample[1], "胜方同事务回写正式批态"
    assert hold[0] == "已驳回" and hold[1], "挂起只关一次"
    raced = [x for x in contentions if x[1] == "争用失败"]
    assert len(raced) == 1, f"后到只记一条争用痕，实际 {raced}"
    assert reject_audits == 1, "败方零回态：驳回审计只能有胜方一条"


def test_lock_held_by_other_session_blocks_reject(client, auth):
    """确定性争用：挂起锁被他人持有时，驳回必须 409 且挂起/主态零改。"""
    import sqlite3

    h = hold_row(client, auth, TARGET_HOLD)
    # admin 先以锁接口占住 sample 锁，writer 会话后到驳回
    occupy = client.post(
        "/api/locks/acquire?lock_key=" + f"sample:{h['sample_id']}",
        headers=auth,
    )
    assert occupy.status_code == 200

    c2 = TestClient(app)
    tok2 = _token("writer", "writer123")
    blocked = c2.post(
        "/api/exceeds/reject",
        headers={"Authorization": "Bearer " + tok2},
        json={"hold_id": h["id"], "note": "后到争用"},
    )
    assert blocked.status_code == 409

    s = sample_row(client, auth, TARGET)
    h2 = hold_row(client, auth, TARGET_HOLD)
    assert s["status"] == "旁路挂起", "争用败方零回态：正式批态不得改"
    assert h2["status"] == "开放", "争用败方零回态：挂起不得关"

    with sqlite3.connect(db.DB_PATH) as raw:
        raced = raw.execute(
            "SELECT actor,action FROM contention_log WHERE lock_key=? AND action='争用失败'",
            (f"sample:{h['sample_id']}",),
        ).fetchall()
    assert len(raced) == 1 and raced[0][0] == "writer"
