"""超标旁路挂起开闭与驳回回态。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit
from locks import release, require_lock
from models import ExceedCloseIn, ExceedOpenIn

router = APIRouter(tags=["exceed"])


@router.get("/api/exceeds")
def list_exceeds(authorization: AuthHeader = None, status: str | None = None):
    require_user(authorization)
    with connect() as conn:
        q = """SELECT h.*, s.sample_code, o.outfall_code FROM exceed_holds h
               JOIN sample_batches s ON s.id=h.sample_id
               JOIN outfalls o ON o.id=s.outfall_id"""
        if status:
            rows = conn.execute(
                q + " WHERE h.status=? ORDER BY h.id DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute(q + " ORDER BY h.id DESC").fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/api/exceeds/open")
def open_exceed(body: ExceedOpenIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    lock_key = f"sample:{body.sample_id}"
    with connect() as conn:
        require_lock(conn, lock_key, user)
        try:
            sample = conn.execute(
                """SELECT s.*, o.cod_limit, o.nh3n_limit, o.tp_limit
                   FROM sample_batches s JOIN outfalls o ON o.id=s.outfall_id
                   WHERE s.id=?""",
                (body.sample_id,),
            ).fetchone()
            if not sample:
                raise HTTPException(404, "采样批次不存在")
            if sample["status"] == "作废":
                raise HTTPException(400, "已作废不可挂起")
            open_row = conn.execute(
                "SELECT id FROM exceed_holds WHERE sample_id=? AND status='开放'",
                (body.sample_id,),
            ).fetchone()
            if open_row:
                raise HTTPException(400, "已有开放挂起")
            import json

            metrics = json.loads(sample["metrics"] or "{}")
            from validators import adjudicate_exceed

            exceeded, metric, measured, limit = adjudicate_exceed(
                metrics,
                {
                    "cod": sample["cod_limit"],
                    "nh3n": sample["nh3n_limit"],
                    "tp": sample["tp_limit"],
                },
            )
            if not exceeded:
                raise HTTPException(400, "当前指标未超标，无需挂起")
            hold_key = f"EX-{sample['sample_code']}-{metric}-M"
            conn.execute(
                """INSERT INTO exceed_holds(sample_id,hold_key,exceed_metric,measured,
                   limit_value,status,opened_at,note) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    body.sample_id,
                    hold_key,
                    metric,
                    measured,
                    limit,
                    "开放",
                    now_iso(),
                    body.note,
                ),
            )
            conn.execute(
                "UPDATE sample_batches SET status=? WHERE id=?",
                ("旁路挂起", body.sample_id),
            )
            write_audit(
                conn,
                user,
                "exceed_open",
                sample["sample_code"],
                {"hold_key": hold_key, "metric": metric},
            )
            conn.commit()
            return {"hold_key": hold_key, "metric": metric}
        finally:
            release(conn, lock_key, user)
            conn.commit()


@router.post("/api/exceeds/close")
def close_exceed(body: ExceedCloseIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    with connect() as conn:
        hold = conn.execute(
            "SELECT * FROM exceed_holds WHERE id=?", (body.hold_id,)
        ).fetchone()
        if not hold:
            raise HTTPException(404, "挂起不存在")
        if hold["status"] != "开放":
            raise HTTPException(400, "挂起已关闭")
        lock_key = f"sample:{hold['sample_id']}"
        require_lock(conn, lock_key, user)
        try:
            conn.execute(
                """UPDATE exceed_holds SET status='已关闭', closed_at=?, note=?
                   WHERE id=?""",
                (now_iso(), body.note or hold["note"], body.hold_id),
            )
            conn.execute(
                """UPDATE sample_batches SET status='已裁定', adjudicated_at=?
                   WHERE id=?""",
                (now_iso(), hold["sample_id"]),
            )
            sample = conn.execute(
                "SELECT sample_code FROM sample_batches WHERE id=?",
                (hold["sample_id"],),
            ).fetchone()
            write_audit(
                conn,
                user,
                "exceed_close",
                sample["sample_code"] if sample else str(hold["sample_id"]),
                {"hold_id": body.hold_id, "note": body.note},
            )
            conn.commit()
            return {"ok": True, "ticket_adjudicated": True, "sample_adjudicated": True}
        finally:
            release(conn, lock_key, user)
            conn.commit()


@router.post("/api/exceeds/reject")
def reject_exceed(body: ExceedCloseIn, authorization: AuthHeader = None):
    """驳回回态（甲路径，当班封死）。

    分两段、同一连接：
      1. 抢 sample 挂起锁（独立短事务）。两路同批抢驳回时后到者 409，
         争用失败痕当场提交，败方零回态；
      2. BEGIN IMMEDIATE 主事务：exceed_holds 置已驳回（关挂起、清旁路标记）
         与 sample_batches 正式状态列回写已裁定同事务，任一步失败整笔回退。
    锁持有至 finally 释放，驳回与主批态回写绝不混用。
    """
    user = require_writer(authorization)
    with connect() as conn:
        hold = conn.execute(
            "SELECT * FROM exceed_holds WHERE id=?", (body.hold_id,)
        ).fetchone()
        if not hold:
            raise HTTPException(404, "挂起不存在")
        # 注：挂起是否仍开放的判定收进持锁后的原子复查，避免两路并发时
        # 后到者在抢锁前就被 400 拦下，争用一律走挂起锁 409 + 争用痕。
        lock_key = f"sample:{hold['sample_id']}"
        # —— 第一段：BEGIN IMMEDIATE 原子抢挂起锁 ——
        # 读锁表→插锁→复查挂起→提交在同一立即写事务内，两路并发必被
        # SQLite 写锁串行化，杜绝"读到空快照→锁被复活→漏判进主事务"。
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        holder_row = conn.execute(
            "SELECT holder FROM effluent_locks WHERE lock_key=?", (lock_key,)
        ).fetchone()
        lock_inserted = False
        if holder_row and holder_row["holder"] != user:
            conn.rollback()
            conn.isolation_level = ""
            # 争用痕独立连接落库：败方零回态但留痕，不受异常连接回滚影响
            with connect() as trail:
                trail.execute(
                    """INSERT INTO contention_log(lock_key,actor,action,detail,created_at)
                       VALUES (?,?,?,?,?)""",
                    (
                        lock_key,
                        user,
                        "争用失败",
                        f"驳回同批争用，持有人={holder_row['holder']}",
                        now_iso(),
                    ),
                )
                trail.commit()
            raise HTTPException(
                409, f"挂起锁被占用：{lock_key} 持有人 {holder_row['holder']}"
            )
        if not holder_row:
            conn.execute(
                "INSERT INTO effluent_locks(lock_key,holder,acquired_at) VALUES (?,?,?)",
                (lock_key, user, now_iso()),
            )
            lock_inserted = True
        # 持锁后在同一立即事务内复查挂起行：持锁期间无人能改挂起，
        # 关掉"前一路刚释放锁、挂起已驳回"的窗口，败者一律走挂起锁 409
        fresh = conn.execute(
            "SELECT status FROM exceed_holds WHERE id=?", (body.hold_id,)
        ).fetchone()
        if not fresh or fresh["status"] != "开放":
            conn.rollback()
            conn.isolation_level = ""
            with connect() as trail:
                trail.execute(
                    """INSERT INTO contention_log(lock_key,actor,action,detail,created_at)
                       VALUES (?,?,?,?,?)""",
                    (
                        lock_key,
                        user,
                        "争用失败",
                        "驳回同批争用，挂起已被先到会话驳回",
                        now_iso(),
                    ),
                )
                trail.commit()
            if lock_inserted:
                with connect() as cleaner:
                    cleaner.execute(
                        "DELETE FROM effluent_locks WHERE lock_key=? AND holder=?",
                        (lock_key, user),
                    )
                    cleaner.commit()
            raise HTTPException(409, "挂起已被先到会话驳回，后到只记争用痕")
        conn.commit()  # 锁立即落库并释放 SQLite 写锁，供第二路立刻判定争用
        # —— 第二段：驳回与主态回写同事务 ——
        try:
            conn.execute("BEGIN IMMEDIATE")
            sample = conn.execute(
                "SELECT * FROM sample_batches WHERE id=?", (hold["sample_id"],)
            ).fetchone()
            if not sample:
                # 主批缺失：整笔回退拒收，挂起行保持开放
                raise HTTPException(404, "采样批次不存在，驳回整笔回退")
            stamp = now_iso()
            cur = conn.execute(
                """UPDATE exceed_holds SET status='已驳回', closed_at=?, note=?
                   WHERE id=? AND status='开放'""",
                (stamp, body.note or hold["note"], body.hold_id),
            )
            if cur.rowcount != 1:
                raise HTTPException(409, "挂起状态已变化，驳回整笔回退")
            cur2 = conn.execute(
                """UPDATE sample_batches SET status='已裁定', adjudicated_at=?
                   WHERE id=? AND status='旁路挂起'""",
                (stamp, hold["sample_id"]),
            )
            if cur2.rowcount != 1:
                # 主态回写失败：同事务回滚，禁止挂起已闭而主态未回
                raise HTTPException(409, "主批态回写失败，驳回整笔回退拒收")
            write_audit(
                conn,
                user,
                "exceed_reject",
                sample["sample_code"],
                {
                    "hold_id": body.hold_id,
                    "note": body.note,
                    "path": "甲",
                    "rule": "驳回与主批态回写同事务，旁路标记同清",
                },
            )
            conn.commit()
            return {
                "ok": True,
                "hold_id": body.hold_id,
                "hold_status": "已驳回",
                "sample_id": hold["sample_id"],
                "sample_status": "已裁定",
                "sample_adjudicated": True,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.isolation_level = ""
            release(conn, lock_key, user)
            conn.commit()
