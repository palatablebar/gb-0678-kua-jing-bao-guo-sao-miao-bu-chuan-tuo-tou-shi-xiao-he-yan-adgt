import pytest
from app.modules.m8_waivers.rules import evaluate
from app import waiver_store, store
from app.errors import DomainError
from app.pipeline import calculate, execute, load_sample

ANN = {
    "announcement_id": "FM-JP-T1", "carrier": "承运商A", "destination": "JP",
    "published_at": "2026-11-09T06:00:00Z", "stop_at": "2026-11-10T00:00:00Z",
    "resume_at": "2026-11-12T00:00:00Z", "reason": "机场停运", "status": "active",
}


def _row(parcel, events, delivered="2026-11-13T02:00:00Z", working="66", late="42", expected="42.00", sla="超时"):
    return {
        "parcel": parcel, "destination": "JP", "zone": "Asia/Tokyo",
        "accepted_at": "2026-11-09T08:00:00Z", "delivered_at": delivered,
        "promised_hours": "24", "declared_value": "500",
        "working_hours": working, "late_hours": late, "expected": expected, "sla": sla,
        "_events": [{"scan_id": s, "node": n, "event_utc": t} for s, n, t in events],
    }


def _ctx(announcements):
    return {"parameters": {}, "announcements": announcements, "quarantine": []}


def test_window_start_uses_last_scan_not_published_or_stop():
    "TRAP-31 免责起点=max(停运, 末次窗口扫描)，而非公告发布或无条件停运时刻"
    row = _row("P1", [("s1", "起运", "2026-11-11T02:00:00Z"), ("s2", "清关", "2026-11-11T08:00:00Z")])
    out = evaluate([row], _ctx([ANN]))["rows"][0]
    piece = out["waiver_pieces"][0]
    assert piece["basis_start"] == "2026-11-11T08:00:00+00:00"
    assert piece["basis_end"] == "2026-11-12T00:00:00+00:00"
    assert out["waiver_decision"] == "准予免责"


def test_no_scan_in_window_denies_even_when_announcement_matches():
    "客服核心担忧：无轨迹证明的包裹不能被整段免责"
    row = _row("P2", [("s1", "起运", "2026-11-09T20:00:00Z")])
    out = evaluate([row], _ctx([ANN]))["rows"][0]
    assert out["waiver_decision"] == "不予免责"
    assert out["waiver_pieces"] == []
    assert out["relief_hours"] == "0"
    assert out["adjusted_expected"] == out["original_expected"]


def test_revoked_announcement_never_grants():
    row = _row("P3", [("s1", "起运", "2026-11-11T02:00:00Z")])
    revoked = {**ANN, "status": "revoked"}
    out = evaluate([row], _ctx([revoked]))["rows"][0]
    assert out["waiver_decision"] == "不予免责"
    assert out["matched_announcements"] == []


def test_destination_mismatch_not_matched():
    row = _row("P4", [("s1", "起运", "2026-11-11T02:00:00Z")])
    row["destination"] = "US"
    out = evaluate([row], _ctx([ANN]))["rows"][0]
    assert out["waiver_decision"] == "不予免责"


def test_late_announcement_window_uses_stop_not_published():
    "公告晚到：免责仍按实际服务停止时刻，发布时刻仅作依据展示"
    late = {**ANN, "announcement_id": "FM-LATE", "published_at": "2026-11-13T02:00:00Z",
            "stop_at": "2026-11-12T18:00:00Z", "resume_at": "2026-11-14T00:00:00Z"}
    row = _row("P5", [("s1", "起运", "2026-11-13T00:30:00Z")])
    out = evaluate([row], _ctx([late]))["rows"][0]
    piece = out["waiver_pieces"][0]
    assert piece["basis_start"] == "2026-11-13T00:30:00+00:00"
    assert piece["published_at"] == "2026-11-13T02:00:00Z"


def test_unique_conclusion_sla_and_compensation_consistent():
    row = _row("P6", [("s1", "起运", "2026-11-10T02:00:00Z")], working="30", late="6", expected="6.00")
    out = evaluate([row], _ctx([ANN]))["rows"][0]
    # 对外唯一字段 sla/expected 与调整后结论一致，原结论保留可追溯
    assert out["sla"] == out["adjusted_sla"]
    assert out["expected"] == out["adjusted_expected"]
    assert out["original_expected"] == "6.00"
    assert number_like(out["comp_change"]) == number_like(out["original_expected"]) - number_like(out["adjusted_expected"])


def test_grant_can_turn_late_into_compliant():
    row = _row("P7", [("s1", "起运", "2026-11-10T02:00:00Z")], working="30", late="6", expected="6.00")
    big = {**ANN, "resume_at": "2026-11-13T00:00:00Z"}
    out = evaluate([row], _ctx([big]))["rows"][0]
    assert out["adjusted_sla"] == "达标" and out["sla"] == "达标"
    assert out["adjusted_expected"] == "0.00"


def number_like(value):
    from decimal import Decimal
    return Decimal(str(value))


def test_metrics_totals_and_denial_count():
    granted = _row("G1", [("s1", "起运", "2026-11-11T02:00:00Z")])
    denied = _row("D1", [("s1", "起运", "2026-11-09T20:00:00Z")])
    m = evaluate([granted, denied], _ctx([ANN]))["metrics"]
    assert m["waivers_granted"] == 1
    assert m["waivers_denied_no_proof"] == 1
    assert number_like(m["compensation_reduction"]) == number_like(m["original_compensation"]) - number_like(m["adjusted_compensation"])


# ---------- 公告存储：只追加、版本、失败保留旧版 ----------

def test_register_and_list_versions():
    saved = waiver_store.register(ANN)
    assert saved["version"] == 1 and saved["status"] == "active"
    versions = waiver_store.get_versions("FM-JP-T1")
    assert len(versions) == 1


def test_duplicate_register_rejected_without_overwrite():
    waiver_store.register(ANN)
    with pytest.raises(DomainError) as e:
        waiver_store.register({**ANN, "reason": "被篡改的原因"})
    assert e.value.code == "ANNOUNCEMENT_EXISTS"
    assert waiver_store.get_versions("FM-JP-T1")[0]["reason"] == "机场停运"


def test_recheck_replace_appends_and_keeps_old_version():
    waiver_store.register(ANN)
    revised = {**ANN, "resume_at": "2026-11-12T12:00:00Z", "reason": "机场停运·延长"}
    versions = waiver_store.recheck("FM-JP-T1", 1, revised, "replace")
    assert len(versions) == 2
    assert versions[0]["status"] == "superseded" and versions[1]["status"] == "active"
    assert versions[0]["reason"] == "机场停运"  # 原始公告未被删除或改写


def test_recheck_stale_version_keeps_old():
    waiver_store.register(ANN)
    with pytest.raises(DomainError) as e:
        waiver_store.recheck("FM-JP-T1", 99, {**ANN, "resume_at": "2026-11-13T00:00:00Z"}, "replace")
    assert e.value.code == "STALE_VERSION"
    assert len(waiver_store.get_versions("FM-JP-T1")) == 1  # 失败保留旧版，无新增


def test_revoke_marks_status_but_preserves_payload():
    waiver_store.register(ANN)
    versions = waiver_store.recheck("FM-JP-T1", 1, {}, "revoke")
    assert versions[-1]["status"] == "revoked"
    assert all(a["announcement_id"] != "FM-JP-T1" for a in waiver_store.active_announcements())
    assert waiver_store.get_versions("FM-JP-T1")[0]["announcement_id"] == "FM-JP-T1"


def test_bad_window_rejected():
    with pytest.raises(DomainError) as e:
        waiver_store.register({**ANN, "announcement_id": "FM-BAD", "resume_at": "2026-11-09T00:00:00Z"})
    assert e.value.code == "BAD_WINDOW"


# ---------- 端到端：样例、幂等、重跑不重复减免 ----------

def test_outage_sample_decisions():
    r = calculate(load_sample("outage.csv"))
    m8 = r["stages"][7]
    by_id = {row["parcel"]: row for row in m8["rows"]}
    assert by_id["P001"]["waiver_decision"] == "准予免责"
    assert by_id["P002"]["waiver_decision"] == "不予免责"   # 窗口内无扫描
    assert by_id["P005"]["waiver_decision"] == "不予免责"   # 停运后无任何扫描
    assert by_id["P006"]["waiver_decision"] == "不予免责"   # 撤销公告
    assert by_id["P004"]["waiver_pieces"][0]["announcement_id"] == "FM-JP-20261113-02"
    assert number_like(m8["metrics"]["compensation_reduction"]) > 0


def test_rerun_idempotent_no_double_relief():
    raw = load_sample("outage.csv")
    a = execute(raw)
    before = a["stages"][7]["metrics"]["adjusted_compensation"]
    b = execute(raw)
    assert a["run_id"] == b["run_id"]
    assert len(store.history()) == 1
    assert b["stages"][7]["metrics"]["adjusted_compensation"] == before
    # 裁定表同 run_id 只有一份
    import sqlite3
    from app.config import DATA_DIR
    db = sqlite3.connect(DATA_DIR / "records.db")
    assert db.execute("SELECT COUNT(*) FROM waiver_verdicts").fetchone()[0] == 1


def test_seed_announcements_idempotent():
    waiver_store.seed()
    first = len(waiver_store.list_announcements())
    waiver_store.seed()
    assert len(waiver_store.list_announcements()) == first


# ---------- HTTP 接口 ----------

def test_waiver_pages_and_api(client):
    assert client.get("/waivers").status_code == 200
    r = client.get("/api/waivers")
    assert r.status_code == 200 and "rows" in r.get_json()


def test_announcement_api_lifecycle(client):
    body = {**ANN, "announcement_id": "FM-HTTP-1"}
    assert client.post("/api/announcements", json=body).status_code == 200
    listed = client.get("/api/announcements").get_json()["announcements"]
    assert any(a["announcement_id"] == "FM-HTTP-1" for a in listed)
    # 陈旧版本 409
    r = client.post("/api/announcements/FM-HTTP-1/recheck",
                    json={"version": 99, "action": "revoke", "announcement": {}})
    assert r.status_code == 409
    # 正确版本撤销成功，旧版仍可查
    assert client.post("/api/announcements/FM-HTTP-1/recheck",
                       json={"version": 1, "action": "revoke", "announcement": {}}).status_code == 200
    versions = client.get("/api/announcements/FM-HTTP-1").get_json()["versions"]
    assert versions[-1]["status"] == "revoked"


def test_archive_contains_waiver_evidence(client):
    import csv, io
    p = client.post("/api/runs", json={"sample": "outage.csv"}).get_json()
    data = client.get("/api/runs/" + p["run_id"] + "/archive").data.decode("utf-8-sig")
    kinds = {row[3] for row in csv.reader(io.StringIO(data))}
    assert "waiver" in kinds
