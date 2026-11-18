# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV。

## 停运公告（M8）

- `GET /api/announcements`：返回全部公告的全部版本（含 active/revoked/superseded），原始公告不删除。
- `POST /api/announcements`：登记公告 v1；同号重复登记返回 422 `ANNOUNCEMENT_EXISTS`，不覆盖。
- `GET /api/announcements/<id>`：返回该公告按版本排序的历史。
- `POST /api/announcements/<id>/recheck`：body `{version, action, announcement}`。action=replace 追加修订版（旧版置 superseded），action=revoke 仅置 revoked；version 乐观锁失效返回 409，失败时保留旧版不新增。
- `GET/POST /api/waivers`：M8 裁定预览。完整流水线 `/api/runs` 自动追加 M8 阶段，并把逐包裁定按 run_id 幂等写入 waiver_verdicts，重跑不重复减免。

公告字段：announcement_id、carrier、destination、published_at、stop_at、resume_at、reason、status。时间必须带 UTC 偏移，resume_at 必须晚于 stop_at，否则 422。免责起点取 max(stop_at, 末次窗口扫描)，发布时刻仅作依据展示。
