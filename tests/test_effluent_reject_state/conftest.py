"""驳回回态共用夹具：本机种子目录预置 EX-P15-回态 缺陷数据。"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

import db
from app import app
from db import init_db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "effluent_reject.db")
    init_db()
    return TestClient(app)


@pytest.fixture()
def auth(client):
    tok = client.post(
        "/api/login", json={"username": "admin", "password": "admin123"}
    ).json()["token"]
    return {"Authorization": "Bearer " + tok}


def sample_row(client, auth, sample_code):
    rows = client.get("/api/samples", headers=auth).json()["items"]
    return next(x for x in rows if x["sample_code"] == sample_code)


def hold_row(client, auth, hold_key):
    rows = client.get("/api/exceeds", headers=auth).json()["items"]
    return next(x for x in rows if x["hold_key"] == hold_key)


def reopen_p15_defect():
    """在用例内复现 EX-P15-回态缺陷：挂起已驳回而主态正式列仍旁路挂起。

    种子层修复负责在 init 时纠偏；读侧用例需要一个"未升正"批点时，
    用本助手把批点打回偏航态（仅测试数据操作，不改生产口径）。
    """
    with sqlite3.connect(db.DB_PATH) as raw:
        raw.execute(
            """UPDATE sample_batches SET status='旁路挂起', adjudicated_at=NULL
               WHERE sample_code='SM-EX-P15'"""
        )
        raw.commit()
