import json
import sqlite3
from app import config
from app.errors import DomainError
from app.values import instant, scalar

# 公告表只追加：任何修订都产生新行 version+1，撤销只置 status，绝不 DELETE。
SCHEMA = """
CREATE TABLE IF NOT EXISTS announcements (
    announcement_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL,
    superseded_by TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (announcement_id, version)
);
CREATE TABLE IF NOT EXISTS waiver_verdicts (
    run_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
"""


def connect():
    data_dir = config.DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(data_dir / "records.db", timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    return db


REQUIRED = ("announcement_id", "carrier", "destination", "published_at", "stop_at", "resume_at", "reason")
STATUSES = {"active", "revoked", "superseded"}


def _validate(payload):
    if not isinstance(payload, dict):
        raise DomainError("BAD_BODY", "公告需要对象")
    for key in REQUIRED:
        if not str(payload.get(key, "")).strip():
            raise DomainError("MISSING_FIELD", f"公告缺少字段 {key}")
    published, stop, resume = (instant(payload[k]) for k in ("published_at", "stop_at", "resume_at"))
    if not stop < resume:
        raise DomainError("BAD_WINDOW", "恢复时刻必须晚于停运时刻")
    clean = {k: str(payload[k]).strip() for k in REQUIRED}
    clean["status"] = payload.get("status", "active") if payload.get("status") in STATUSES else "active"
    return clean


def seed():
    "幂等播种内置样例公告；重跑不产生重复版本。"
    with connect() as db:
        for item in config.DEFAULT_WAIVERS:
            exists = db.execute(
                "SELECT 1 FROM announcements WHERE announcement_id=? AND version=1",
                (item["announcement_id"],),
            ).fetchone()
            if not exists:
                db.execute(
                    "INSERT INTO announcements(announcement_id,version,payload,status,superseded_by,created_at)"
                    " VALUES(?,1,?,?,?,?)",
                    (
                        item["announcement_id"],
                        json.dumps(item, ensure_ascii=False),
                        item["status"],
                        None,
                        instant(item["published_at"]).isoformat(),
                    ),
                )


def list_announcements(include_inactive=True):
    seed()
    with connect() as db:
        rows = db.execute(
            "SELECT payload,status,superseded_by FROM announcements ORDER BY announcement_id,version"
        ).fetchall()
    out = []
    for raw, status, superseded_by in rows:
        item = json.loads(raw)
        item["status"] = status
        item["superseded_by"] = superseded_by
        if include_inactive or status == "active":
            out.append(item)
    return out


def active_announcements():
    "返回每条公告的最新有效版本（active）；撤销与被替换版本不参与免责，但仍保留可查。"
    return [a for a in list_announcements() if a["status"] == "active"]


def get_versions(announcement_id):
    seed()
    with connect() as db:
        rows = db.execute(
            "SELECT version,payload,status,superseded_by,created_at FROM announcements"
            " WHERE announcement_id=? ORDER BY version",
            (announcement_id,),
        ).fetchall()
    if not rows:
        raise DomainError("NOT_FOUND", "公告不存在", 404)
    versions = []
    for version, raw, status, superseded_by, created_at in rows:
        item = json.loads(raw)
        item.update(version=version, status=status, superseded_by=superseded_by, created_at=created_at)
        versions.append(item)
    return versions


def latest_version(db, announcement_id):
    row = db.execute(
        "SELECT MAX(version) FROM announcements WHERE announcement_id=?", (announcement_id,)
    ).fetchone()
    return row[0] or 0


def register(payload):
    "登记公告 v1。同号公告已存在时走 recheck 修订路径，不允许覆盖。"
    clean = _validate(payload)
    seed()
    with connect() as db:
        if latest_version(db, clean["announcement_id"]):
            raise DomainError("ANNOUNCEMENT_EXISTS", "公告已存在，请走修订接口")
        db.execute(
            "INSERT INTO announcements(announcement_id,version,payload,status,superseded_by,created_at)"
            " VALUES(?,1,?,?,'active',?)",
            (
                clean["announcement_id"],
                json.dumps(clean, ensure_ascii=False),
                clean["status"],
                instant(clean["published_at"]).isoformat(),
            ),
        )
    return get_versions(clean["announcement_id"])[-1]


def recheck(announcement_id, expected_version, payload, action):
    """
    公告晚到/撤销后的重新核对：
    - 乐观锁 expected_version，失效返回 409；
    - 成功才追加新版本，失败保留旧版；
    - action=revoke 仅把最新版标记 revoked（保留原文）；action=replace 追加修订版并把旧版置 superseded。
    """
    if action not in {"replace", "revoke"}:
        raise DomainError("BAD_ACTION", "动作只能是 replace 或 revoke")
    seed()
    if action == "replace":
        clean = _validate(payload)
        if clean["announcement_id"] != announcement_id:
            raise DomainError("ID_MISMATCH", "公告号不可变更")
    with connect() as db:
        current = latest_version(db, announcement_id)
        if not current:
            raise DomainError("NOT_FOUND", "公告不存在", 404)
        if current != expected_version:
            raise DomainError("STALE_VERSION", "公告版本已更新，请刷新后重新核对", 409)
        if action == "revoke":
            db.execute(
                "UPDATE announcements SET status='revoked' WHERE announcement_id=? AND version=?",
                (announcement_id, current),
            )
        else:
            db.execute(
                "UPDATE announcements SET status='superseded',superseded_by=? "
                "WHERE announcement_id=? AND version=?",
                (str(current + 1), announcement_id, current),
            )
            db.execute(
                "INSERT INTO announcements(announcement_id,version,payload,status,superseded_by,created_at)"
                " VALUES(?,?,?,?,'active',?)",
                (
                    announcement_id,
                    current + 1,
                    json.dumps(clean, ensure_ascii=False),
                    "active",
                    instant(clean["published_at"]).isoformat(),
                ),
            )
    return get_versions(announcement_id)


def save_verdicts(run_id, payload):
    "幂等保存：同 run_id 重跑 INSERT OR IGNORE，绝不重复减免。"
    with connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO waiver_verdicts(run_id,payload) VALUES(?,?)",
            (run_id, json.dumps(scalar(payload), ensure_ascii=False)),
        )


def get_verdicts(run_id):
    with connect() as db:
        row = db.execute("SELECT payload FROM waiver_verdicts WHERE run_id=?", (run_id,)).fetchone()
    if not row:
        raise DomainError("NOT_FOUND", "免责裁定不存在", 404)
    return json.loads(row[0])
