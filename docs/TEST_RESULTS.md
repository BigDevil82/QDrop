# 测试记录

执行日期：2026-10-12。设备：Windows 11 x64；Redmi K70（23113RKC6C），Android 16 / API 36，HyperOS 3，微信 8.0.69。以下区分实际执行、模拟验证和待验收，不能据此宣称一期全部通过。

## 自动与真机测试

- 服务端 pytest：12 passed，1 个 Starlette/httpx 测试客户端弃用警告。使用真实临时 SQLite 和磁盘，覆盖鉴权、跨组隔离、双向权限、幂等冲突、大小/摘要、配额、撤销、分页、ACK/取消竞争、清理和错误 fixture。
- TCP 集成测试实际中断上传并以同一任务重试；实际流式上传/下载 50 MiB，在暂停读取期间触发 TTL，活动下载完整且 SHA-256 相同，新下载被拒绝，租约结束后清理。
- scripts/smoke.py：HTTP、WebSocket 提示、服务端重启后补 ACK、双向收发权限、UTF-8 摘要五项通过。
- Windows 实际 WPF 恢复测试：UTF-8（包含开头 BOM、中文、emoji、长 URL）剪贴板逐字一致；补 ACK；attempted 动作不重放；路径穿越 PS1 文件安全保存且不运行；360 秒旧文本不复制，五项通过。
- Windows 安装目录自包含程序实际启动，平台自测验证共享 fixture、STA 剪贴板、TXT 文件关联打开、托盘、通知注册/提交和关闭隐藏。通知按钮点击、干净 Windows 主机仍待验收。
- Android Debug 和 Release URL 单元测试分别 2 项通过；lint 无错误，Debug 的 3 条建议涉及新版本 Gradle、OkHttp 和 kapt/KSP。Release 构建含单元测试和 lint。
- Android 真机 instrumentation：4 个测试方法通过，包含实际 ContentResolver 的未知大小、零字节、失效 URI、超过 50 MiB 流；EXTRA_STREAM/ClipData 去重；共享传输及错误 fixture；私有文本快照。注册测试需传入一次性 enrollment 参数，未提供参数时该方法不执行注册，不能算新增注册验证。
- APK 固定外部签名验证与真机安装、正式包启动实际执行；Debug、测试 APK 和正式 APK 可分别安装。正式包 HTTPS 限制由 Release 单元测试验证，真实公网 TLS 联调尚未执行。
- Docker Compose 配置解析通过；本机 Docker daemon 未运行，镜像构建和容器运行未执行。

## 第 15 节一期矩阵

| 用例 | 状态与证据 |
| --- | --- |
| A01 | 真机注册、me、用户确认设备选择成功；私有凭证存储实现。最新包身份可保留；日志凭证未输出。 |
| A02 | 真实微信 PDF 分享通过；1955643 字节，手机/服务端/电脑 SHA-256 相同并 ACK。 |
| A03 | 用户确认两张图片同批发送成功；1373251 / 2909533 字节，两份电脑文件 SHA-256 与服务端一致，均 ACK，无重复传输。用户同时设置的文本未收到，同批没有文本任务，因此不能标记混合发送验收通过。补修多项分享列表文本解析及准备文字保留文件，自动回归结果见下文。 |
| A04 | 用户确认浏览器 URL 分享；107 字节文本已 ACK；Windows 中文长文本逐字一致自动测试通过，URL 不访问。 |
| A05 | 模拟 360 秒旧文本与补收抑制通过；真实电脑离线等待 5 分钟尚未执行。 |
| A06 | 实际 TCP 上传中断、相同 ID 重试及幂等测试通过。 |
| A07 | 实际 Windows 持久化 ACK 恢复、动作 attempted 不重放通过。 |
| A08 | 服务端实际重启、遗漏事件后 inbox 补收通过。 |
| A09 | 最新真机 ContentResolver 边界测试通过。 |
| A10 | 安全名称函数及真实路径穿越中文 PS1 落盘通过；全部同名/长名组合的 UI 手工测试未执行。 |
| A11 | 模拟服务端写盘 OSError 验证不虚报成功；真实服务端/Windows 磁盘满未执行。 |
| A12 | 撤销、跨设备/跨组正文与 ACK 拒绝、连接失效自动测试通过。 |
| A13 | 实际 50 MiB 下载和 TTL 竞争、ACK 清理自动测试通过。 |
| A14 | 锁屏/恢复保护已实现；真实锁屏、休眠和退出组合未执行。 |
| A15 | 实际 PS1 文件只保存；EXE/宏文档自动动作白名单保护已实现，实物组合未全部测试。 |
| A16 | 实际托盘、关闭隐藏与显式退出通过；开机登录启动设置已实现，重启登录测试未执行。 |

真实源文件只保留在本机忽略目录，不随源码分发。PDF 摘要 `32f4e6e18dac7dee4585fff24bc5b9f325a32bd4090ce6c4a9f4940df4596887`；图片 `6c68aa6a8f68001f0a49a0d7ed71e107875f83018e012eae37aee954f9fbbde1`；浏览器文本 `a0e8638ffa0f7ad44f64784516689df9c94b348618e2251902af3c7c49c7988f`。

不宣称后台持续在线、后台手机剪贴板读取、验证码必达或本地副作用严格恰好一次。尚未执行公网 30 次性能测量与长时间运行测试。

## 多图反馈后复核

用户反馈：两张图片成功接收，没有收到设置的文本。服务端同批只有两条文件记录，电脑两份最终文件摘要一致；检查时手机诊断快照已被后续 URL 分享覆盖，无法从该快照证明这次来源 Intent 是否携带文本，也不能断言是相册未提供文本。

代码确认两处缺口并修复：多项分享 EXTRA_TEXT 的列表形态未读取；在 QDrop 里“准备文字”会替换已准备文件。现在支持单条/列表 EXTRA_TEXT 与 ClipData 文本，手动准备文字保留文件并替换已有文本，按钮按上下文显示“附加文字”，输入框明确需先准备。来源协议依据：[Android ACTION_SEND_MULTIPLE](https://developer.android.com/reference/android/content/Intent#ACTION_SEND_MULTIPLE)。不读取图片 OCR 或后台剪贴板。

修复后真机回归：5 个方法通过（未传 enrollment 的注册方法仅返回，不能计为新注册测试）；新用例实际启动 MainActivity，提供两个合成 ContentProvider URI 和列表中文文本，确认得到 file/file/text 三项私有快照及正确文本字节数/摘要，另验证单条与 ClipData 文本解析。这里的 URI 是测试数据，不冒充真实相册完整混合传输。首次运行被 HyperOS 拒绝后台启动 Activity 而超时；测试通过 shell 先把本 App 放到前台后复跑，5 项通过。Debug/Release 各 2 项 URL 单元测试、lint 和固定签名发布重建通过。

## 公开源码配置复核

两端默认服务器地址改为空，已有私有设置保留；公开示例改用保留域名。Git 暂存区检查未发现真实服务器 IP/域名、运行凭证或私钥；deploy/.env 被忽略，.env.example 可提交。Windows 重新构建与自包含发布通过，构建 0 警告/0 错误；Android Debug/Release 重新构建、各 2 项 URL 单元测试、lint 与 APK 固定签名验证通过。首轮 Windows 构建因本机联调进程锁定输出而失败，停止该进程后复跑通过。

Compose 使用 deploy/.env.example 实际解析通过；Caddy 2.10.2 实际 adapt --validate 通过，额外将 MAX_FILE_BYTES 改为 1048576 验证生成配置请求体上限同步变化。没有运行 Docker 容器或申请公网证书，这些不能标记通过。
