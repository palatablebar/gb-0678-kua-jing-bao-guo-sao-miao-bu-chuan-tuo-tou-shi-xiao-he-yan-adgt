from decimal import Decimal
from app.values import instant, number, money
from app.modules.m5_timeliness.rules import working_hours
from app.errors import DomainError

# 停运免责裁决（M8）
#
# 争议焦点：承运商要求按公告整段免除时效，客服担心无轨迹证明的包裹被一并免责。
#
# 裁决口径（唯一结论）：
# 1) 免责区间起点不取“公告发布时刻”，也不无条件取“服务停止时刻”，
#    而是 max(公告服务停止时刻, 该包裹最后一次正常扫描时刻)；
# 2) 免责区间终点取 min(公告恢复时刻, 包裹实际/截止时钟)；
# 3) 必须在公告停运窗口内存在该包裹的扫描轨迹作为受影响证据，
#    没有任何窗口内扫描的包裹不予免责（即使公告覆盖其目的地）；
# 4) 每个包裹按“公告窗口 ∩ 自身证据窗口”逐包裁定，承运商整段免责主张被限缩为有证据部分；
# 5) 撤销/被替换的公告不参与；重跑按 run_id 幂等，不重复减免。


def _clock_end(row, as_of):
    return instant(row["delivered_at"]) if row.get("delivered_at") else max(instant(row["accepted_at"]), as_of)


def _holidays(row, parameters):
    table = parameters.get("holidays", {}) if parameters else {}
    return set(table.get(row["destination"], set()))


def _window_for(ann, row, clock_end):
    """返回 (免责起, 免责止, 证据扫描列表)；无证据返回 None。"""
    stop = instant(ann["stop_at"])
    resume = instant(ann["resume_at"])
    accepted = instant(row["accepted_at"])
    # 公告窗口与该包裹生命周期取交集，空交集直接排除
    win_start = max(stop, accepted)
    win_end = min(resume, clock_end)
    if win_start >= win_end:
        return None
    # 轨迹证明：停运窗口 [stop, resume) 内属于该包裹的原始扫描（来自 M3 归整后的事件）
    proof = [
        e for e in row.get("_events", [])
        if stop <= instant(e["event_utc"]) < resume
    ]
    if not proof:
        return None
    last_normal = max(instant(e["event_utc"]) for e in proof)
    start = max(stop, last_normal)
    end = win_end
    if start >= end:
        # 最后一次扫描已贴近恢复点，没有可停表区间
        return None
    return start, end, proof


def evaluate(rows, context):
    parameters = context.get("parameters", {})
    as_of = instant(parameters.get("as_of", "2026-11-18T00:00:00Z"))
    rate = number(parameters.get("hourly_compensation", "1.00"))
    if rate < 0:
        raise DomainError("BAD_RATE", "赔付费率不能为负")
    announcements = context.get("announcements", [])
    active = [a for a in announcements if a.get("status", "active") == "active"]

    output = []
    granted = 0
    denied_no_proof = 0
    total_relief_hours = Decimal(0)
    original_comp_total = Decimal(0)
    adjusted_comp_total = Decimal(0)

    for row in rows:
        clock_end = _clock_end(row, as_of)
        holidays = _holidays(row, parameters)
        original_hours = number(row["working_hours"])
        original_late = number(row["late_hours"])
        original_comp = number(row["expected"])
        original_comp_total += original_comp

        matched = [a for a in active if a["destination"] == row["destination"]]
        pieces = []
        relief_seconds = Decimal(0)
        # 同一包裹可能命中多条公告，按公告分别停表；区间由窗口交集保证互不重叠
        for ann in matched:
            window = _window_for(ann, row, clock_end)
            if window is None:
                continue
            start, end, proof = window
            relief = working_hours(start, end, row["zone"], holidays)
            relief_seconds += relief
            pieces.append({
                "announcement_id": ann["announcement_id"],
                "carrier": ann["carrier"],
                "published_at": ann["published_at"],
                "stop_at": ann["stop_at"],
                "resume_at": ann["resume_at"],
                "basis_start": start.isoformat(),
                "basis_end": end.isoformat(),
                "relief_hours": str(relief),
                "proof_scans": sorted(e["scan_id"] for e in proof),
                "proof_rule": "窗口内存在受影响扫描；起点=max(停运, 末次正常扫描)",
            })

        adjusted_hours = max(Decimal(0), original_hours - relief_seconds)
        promised = number(row["promised_hours"])
        adjusted_late = max(Decimal(0), adjusted_hours - promised)
        adjusted_comp = min(number(row["declared_value"]) * Decimal("0.10"), adjusted_late * rate)
        adjusted_comp = number(money(adjusted_comp))
        adjusted_comp_total += adjusted_comp

        if pieces:
            decision = "准予免责"
            granted += 1
            total_relief_hours += relief_seconds
            reason = "停运窗口内有轨迹证明，按证据区间停表"
        else:
            decision = "不予免责"
            reason = "公告停运窗口内无该包裹扫描轨迹，或无覆盖目的地的有效公告"
            if matched:
                denied_no_proof += 1

        output.append({
            **row,
            "waiver_decision": decision,
            "waiver_reason": reason,
            "waiver_pieces": pieces,
            "matched_announcements": [a["announcement_id"] for a in matched],
            "relief_hours": str(relief_seconds),
            "original_working_hours": str(original_hours),
            "adjusted_working_hours": str(adjusted_hours),
            "original_late_hours": str(original_late),
            "adjusted_late_hours": str(adjusted_late),
            "original_sla": row["sla"],
            "adjusted_sla": "超时" if adjusted_late > 0 else "达标",
            "original_expected": money(original_comp),
            "adjusted_expected": money(adjusted_comp),
            "comp_change": money(original_comp - adjusted_comp),
            # 唯一对外结论字段（下游与页面以这两个为准）
            "sla": "超时" if adjusted_late > 0 else "达标",
            "expected": money(adjusted_comp),
        })

    metrics = {
        "parcels": len(output),
        "active_announcements": len(active),
        "waivers_granted": granted,
        "waivers_denied_no_proof": denied_no_proof,
        "total_relief_hours": str(total_relief_hours),
        "original_compensation": money(original_comp_total),
        "adjusted_compensation": money(adjusted_comp_total),
        "compensation_reduction": money(original_comp_total - adjusted_comp_total),
        "idempotent_key": "run_id",
    }
    return {"rows": output, "quarantine": [], "metrics": metrics}
