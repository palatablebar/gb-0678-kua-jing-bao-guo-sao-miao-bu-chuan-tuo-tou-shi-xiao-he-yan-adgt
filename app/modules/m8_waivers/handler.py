from flask import Blueprint, request, jsonify
from app.errors import DomainError
from app.pipeline import stage_preview
from app import waiver_store

bp = Blueprint("waivers", __name__)


@bp.route("/api/waivers", methods=["GET", "POST"])
def preview():
    payload = request.get_json(silent=True) if request.method == "POST" else {}
    if payload is None or not isinstance(payload, dict):
        raise DomainError("BAD_BODY", "请求需要对象")
    return jsonify(stage_preview(7, payload))


@bp.get("/api/announcements")
def announcements():
    return jsonify({"announcements": waiver_store.list_announcements()})


@bp.get("/api/announcements/<announcement_id>")
def announcement_versions(announcement_id):
    return jsonify({"announcement_id": announcement_id, "versions": waiver_store.get_versions(announcement_id)})


@bp.post("/api/announcements")
def register_announcement():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise DomainError("BAD_BODY", "请求需要对象")
    return jsonify(waiver_store.register(payload))


@bp.post("/api/announcements/<announcement_id>/recheck")
def recheck_announcement(announcement_id):
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload.get("version"), int):
        raise DomainError("BAD_VERSION", "请提供公告当前版本号")
    action = payload.get("action", "replace")
    versions = waiver_store.recheck(announcement_id, payload["version"], payload.get("announcement", {}), action)
    return jsonify({"announcement_id": announcement_id, "versions": versions})
