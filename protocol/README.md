# QDrop protocol v1

API 主版本固定 1。三端共用 `fixtures/transfer.json` 与 `transfer.schema.json`；`openapi.json` 为实现生成的请求契约。UTC RFC3339 时间；size 为实际 UTF-8/文件字节数，sha256 为小写 64 位 hex。文件/文本正文都走 HTTP 二进制流，不用 JSON/base64 包裹文件。

除 `/healthz`、`/readyz`、`POST /v1/enroll` 外所有业务接口需 `Authorization: Bearer <设备 token>`。WSS `/v1/events` 同样在握手 Header 携带凭证，不能把 token 放查询参数。生产 HTTPS/WSS；debug 本机才允许 HTTP/WS。

| 接口 | 角色 / 行为 |
|---|---|
| POST /v1/enroll | CLI 随机一次性 code；返回 UUID、私有组与独立 256-bit token，仅一次 |
| GET /v1/me /devices | 本设备/同组未撤销设备，限制、协议版本、server_time、在线提示 |
| POST /v1/transfers | 由凭证决定 sender；同组 recipient_device_id；client_transfer_id 幂等 |
| PUT /v1/transfers/{id}/content | 仅发送者；流式写 .part，size/SHA-256 完整匹配后原子替换 |
| POST /v1/transfers/{id}/commit | 仅发送者；UPLOADED → READY；重复提交返回原状态 |
| GET /v1/inbox | 仅当前设备 READY 未过期项，50 条稳定排序分页，next_cursor |
| GET /v1/transfers/{id} | 仅发送者/目标设备可查元数据与状态 |
| GET /v1/transfers/{id}/content | 仅目标，开始时检查 TTL，持有限时下载租约 |
| POST /v1/transfers/{id}/ack | 仅目标，size/SHA-256 一致且已本地持久化；重复 ACK 幂等 |
| POST /v1/transfers/{id}/cancel | 仅发送者，未接收任务；无法撤回已经读出的字节 |

身份/权限不按 android/windows 固定单向。服务器可接收 Windows 创建的任务，也允许 Android 目标读取、ACK；这些已自动测试。当前一期 UI 只启用手机发送与电脑接收，设备 capability 字段仅表明协议角色支持，不代表手机接收 UI 已启用。

创建字段：client_transfer_id、recipient_device_id、kind（text/file）、name（文本为 null）、mime、size、sha256、sensitivity（normal/sensitive）、requested_ttl_seconds、origin_created_at、batch_id（可 null）。同 sender/key 且同参数返回相同 id；参数变化返回 409 IDEMPOTENCY_CONFLICT。摘要保留到元数据过期，不能用同一 key 修改文件。

状态：CREATED → UPLOADED → READY → RECEIVED；前 3 个状态可转 CANCELLED/EXPIRED。终态不回退。上传截止默认创建后 30 分钟，内容 TTL 从 commit 起算。敏感文本同时受源端发送后 5 分钟限制。auto_action_until 取源端发送 +120s 与服务器 commit +120s 的较早值，严重偏差关闭自动动作。

ACK 表示落盘，不表示复制、打开或已看过。已经确认的 ACK 在元数据保留期内即使正文删了仍成功；未确认而 TTL 已过，返回 410，客户端保留“已保存，确认迟到”。本地 action_state 与 receipt 分开：pending/attempted/succeeded/failed/skipped，先 durable attempted 后调用系统动作，崩溃后不自动重放。

错误为 `{code,message,retryable,request_id}`。401 停止凭证重试；403 无权；409 状态/幂等冲突（UPLOAD_BUSY 可重试）；410 到期终止；413 超限；422 参数/摘要/UTF-8 错误；429 遵守 Retry-After；507 空间或配额不足；503 数据库暂不可用。客户端按 code/HTTP 状态处理，不解析中文 message。

WSS 事件只含 event_id/type/transfer_id/server_time，不含正文。类型 transfer.ready/received/expired/cancelled、device.changed、heartbeat。30 秒心跳，90 秒接收超时。新进程同身份替换旧连接；撤销后 HTTP 立即拒绝，现有 WSS 在最多约 2 秒的撤销检查内关闭。首次连接、重连、恢复与 Windows 60 秒补偿查询都以 inbox 为依据。
