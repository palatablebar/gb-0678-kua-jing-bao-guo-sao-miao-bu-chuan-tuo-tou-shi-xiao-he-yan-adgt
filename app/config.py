from pathlib import Path
import os
ROOT=Path(__file__).resolve().parent.parent
DATA_DIR=Path(os.environ.get("DATA_DIR", "/tmp/parcelsla"))
TITLE='跨境包裹扫描补传与妥投时效核验'
SHORT='parcelsla'
COLUMNS=['scan_id', 'parcel', 'node', 'event_time', 'received_time', 'destination', 'promised_hours', 'declared_value', 'reported', 'note']
MODULES=[('scans', '扫描采信'), ('nodes', '节点映射'), ('timezones', '时区归整'), ('paths', '路径裁决'), ('timeliness', '时效计算'), ('compensation', '赔付对账'), ('archives', '批次归档'), ('waivers', '停运免责')]
RULE_VERSION="2026.11.18-r2"
DEFAULT_WAIVERS=[
 {"announcement_id":"FM-JP-20261110-01","carrier":"承运商A","destination":"JP","published_at":"2026-11-09T06:00:00Z","stop_at":"2026-11-10T00:00:00Z","resume_at":"2026-11-12T00:00:00Z","reason":"目的地机场突发停运","status":"active"},
 {"announcement_id":"FM-JP-20261113-02","carrier":"承运商A","destination":"JP","published_at":"2026-11-13T02:00:00Z","stop_at":"2026-11-12T18:00:00Z","resume_at":"2026-11-14T00:00:00Z","reason":"清关系统故障（公告晚到）","status":"active"},
 {"announcement_id":"FM-US-20261110-03","carrier":"承运商B","destination":"US","published_at":"2026-11-09T10:00:00Z","stop_at":"2026-11-10T00:00:00Z","resume_at":"2026-11-11T00:00:00Z","reason":"目的地枢纽关闭（后撤销示例）","status":"revoked"}
]
