# 扫描时效定义

scan_id是扫描事件唯一键，parcel是包裹号。节点按收件、起运、清关、妥投顺序推进；可缺中间节点，但必须有收件。按event_time排序，received_time仅用于上传延迟。倒退扫描隔离，不改写先前妥投事件。妥投使用最早有效发生时刻。

目的地JP/US/DE对应东京/纽约/柏林。时效以目的地工作日小时计算，周末与节假日停表。JP含2026-11-03与11-23，US含11-26，DE含10-03；支持按参数覆盖假日。未妥投计算至as_of，默认2026-11-18T00:00Z。每超时小时赔付1元，上限保价10%，reported为原申报赔付。

业务ID和超大整数按文本保形；Decimal参与数量金额计算，对外序列化为字符串。哨兵集合定义在app/values.py，缺失值不能当零。所有时间带UTC偏移，先转UTC比较，业务日按指定地区划分。区间统一[start,end)。重复业务键保留第一条、完全相同行计重复；值冲突行隔离且保留原值。空文件、全空白、仅表头分开拒绝。

运行清单包括输入sha256、规则版本、参数、生成时刻与耗时。源行编号以CSV解析器的物理结束行号表示，引号内换行不增加记录数。输入超过4MB返回413，非法表头和类型返回422，失效版本复核返回409。

## 停运免责（M8）

公告以 announcement_id+version 为键，只追加不删除：status 取 active/superseded/revoked。裁定按包裹输出 waiver_decision（准予免责/不予免责）、waiver_pieces（逐公告依据：免责区间 basis_start→basis_end、减免工时 relief_hours、证据扫描 proof_scans）、relief_hours、original/adjusted 的 working/late/expected 与 comp_change。唯一对外结论为 sla 与 expected（调整后口径）。停运窗口内无该包裹扫描轨迹的包裹不予免责；撤销与被替换公告不参与；同 run_id 重跑复用裁定，不重复减免。样例 outage.csv 覆盖有证据免责、无证据驳回、晚到公告与撤销公告四类场景。