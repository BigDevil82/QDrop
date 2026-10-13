# QDrop

个人自用的 Android → Windows 文件/文本快传。日常模式面向“手机与当前电脑在同一局域网”：Windows 包内置本地 FastAPI 服务，Android 分享后自动发现当前网络中唯一已配对电脑并发送，不经过公网服务器，也不要求发送时选择设备。公网 Docker 部署保留为开源自部署选项。

安装产物在 `artifacts/android/QDrop-release.apk`、`artifacts/android/QDrop-debug.apk`、`artifacts/QDrop-windows-x64.zip`。正式 Android 包名 `site.leospace.qdrop`，debug 包名 `site.leospace.qdrop.debug`，可同时安装。两者允许 HTTPS，以及私有 IPv4/共享地址空间的局域网 HTTP；公共地址 HTTP 仍拒绝。Windows 包为 .NET 10 / Windows App SDK 自包含 win-x64 文件夹包，并包含 Python 3.12 与本地服务依赖。

个人局域网首次设置和日常流程见 [个人局域网模式](docs/LAN_MODE.md)。办公室电脑和宿舍笔记本各配对一次，之后手机按当前局域网发现结果自动切换，不用改地址或选电脑。

源码分发包为 `artifacts/QDrop-source.zip`，各包校验值见 `artifacts/SHA256SUMS.txt`；源码包不包含工具链、密钥、运行凭证及用户传输正文。重新打包源码与校验值可运行 `.venv\Scripts\python.exe scripts\package-source.py`。

已在 Redmi K70、Android 16、HyperOS 3 和 Windows 11 本机进行验证。用户已确认微信、图片和浏览器分享可用；三项真实传输的手机快照、服务端和电脑 SHA-256 相同，已 ACK。锁屏/休眠、真实磁盘满、30 次公网延迟、无开发工具的干净 Windows 环境仍待实测。一次私有服务器部署的 HTTPS/WSS、重启补收、双向传输和撤销验证已完成；公开源码不记录该部署地址。

## 本地启动（PowerShell，仓库根目录）

首次准备工具链，安装在仓库忽略的 `.tools` 内。已有 Java 会沿用；无 Java 则下载 JDK 17。此脚本会接受 Android SDK 组件许可证；需要可访问官方下载源。完整工具链版本见 [版本清单](docs/TOOLCHAIN.md)。

```powershell
Set-Location .\QDrop
.\scripts\bootstrap.ps1
```

打开第一个终端启动 API；它只监听本机，不使用开发明文服务做公网部署：

```powershell
.\scripts\start-server.ps1
```

第二个终端编译并运行 Windows debug 接收器：

```powershell
& .\.tools\dotnet\dotnet.exe build windows\QDrop.sln
& .\.tools\dotnet\dotnet.exe run --project windows\QDrop.App
```

关闭主窗口会隐藏到托盘；“退出”才停止。默认接收目录通过 Windows Downloads Known Folder 获取，再建立 QDrop 子目录。开机登录启动是设置中的可选开关。

配置 Android：下面构建命令在执行 bootstrap 的同一个 PowerShell 会话运行；新终端需要将 JAVA_HOME 指向自己实际安装的兼容 JDK（17 或更高），并设置 ANDROID_HOME。

```powershell
$env:ANDROID_HOME="$PWD\.tools\android-sdk"
& .\.tools\android-sdk\platform-tools\adb.exe devices -l
& .\.tools\android-sdk\platform-tools\adb.exe reverse tcp:8000 tcp:8000
Push-Location android
.\gradlew.bat assembleDebug installDebug
Pop-Location
```

手机需打开 USB 调试并允许电脑密钥；小米可能要求打开 USB 安装、确认安装弹窗。App 名称为 **QDrop Debug**。服务地址填 `http://127.0.0.1:8000`，电脑 debug 端同样填写该地址。

## 注册设备与发送第一条文本

API 启动后，每个客户端各生成一次注册码，10 分钟内单次使用：

```powershell
.\scripts\enroll.ps1
# 把输出的注册码填入 Windows 设置，点击注册。
.\scripts\enroll.ps1
# 把新的注册码填入手机，填写设备名后点击注册。
.\scripts\enroll.ps1 -Command devices
```

手机填写文字或点击前台“粘贴”，再点击“准备文字”；分享文件时，在微信可用的“用其他应用打开/系统分享”、相册或浏览器选择 QDrop。私有快照准备完成后，应用自动发现当前局域网中唯一已配对电脑并发送。

每个文件一条传输，附带文本也是独立项目，同批共用 batch_id。手机可返回源 App，发送队列已持久化；前台服务只在上传任务执行期间运行。失败后通过有网络约束的 WorkManager 补偿，一轮最多 5 次，之后可手动重试。被系统强制停止后，下次打开恢复。

已准备文件后也可在文字框输入中文，点击“附加文字”，确认预览包含文件和文字，再点击电脑目标。输入框内容需要先准备；不点击准备不会自动加入任务。来源 App 分享的单条/列表文本由 QDrop 自动准备；来源没有传入文字时不能凭空取得。

“已暂存，等待目标接收”只是服务器提交成功；“目标已收到”需要电脑 ACK。电脑按 SHA-256 校验并原子保存后 ACK；自动复制或打开是单独的本地动作。动作执行前记录 attempted，崩溃后不自动重放。可在记录中手动再次打开/复制；不承诺副作用严格恰好一次。

默认自动打开仅 PDF/TXT/PNG/JPG/JPEG/WEBP；脚本、可执行、宏文档、HTML/SVG 等仅保存。URL 仅复制。自动动作窗口为发送后最多 2 分钟；离线或批量补收只保存。锁屏不打开或复制；解锁重新检查有效窗。

## 构建正式包和安装 Windows

```powershell
.\scripts\sign-android.ps1
.\scripts\build.ps1
.\scripts\install-windows.ps1
& "$env:LOCALAPPDATA\Programs\QDrop\QDrop.App.exe"
```

`sign-android.ps1` 首次生成固定 RSA 签名密钥，放在 `%LOCALAPPDATA%\QDropSigning\release.jks`，密码由当前用户 DPAPI 保护。实际密钥不在仓库；后续更新必须使用同一密钥。请安全备份签名库，并在原 Windows 账户中将密码保存到自己的密码管理器；单独备份 DPAPI 文件不能保证重装系统后解密。环境变量中的自有签名配置也可直接用于 Gradle，见 [发布说明](docs/RELEASE.md)。

正式 APK 安装：

```powershell
& .\.tools\android-sdk\platform-tools\adb.exe install -r artifacts\android\QDrop-release.apk
```

正式包与历史同包名 debug 包签名不同，首次切换需卸载历史 debug 包后安装；卸载会重置手机本地身份和缓存。新 debug 包名已独立。公网自部署模式仍填写可信 HTTPS 地址；个人局域网模式在 Windows 点击“初始化局域网并生成手机配对码”，手机只在首次配对时填写提示的地址与注册码。

## 自动测试

```powershell
& .\.venv\Scripts\python.exe -m pytest -c server\pytest.ini server\tests -q
& .\.venv\Scripts\python.exe scripts\smoke.py
Push-Location android
.\gradlew.bat testDebugUnitTest lintDebug
Pop-Location
```

Windows 托盘菜单提供“验证剪贴板与打开”；也可运行 `QDrop.App.exe --self-test`，结果在 `%LOCALAPPDATA%\QDrop\self-test.json`。它会临时写测试文本、恢复原纯文本剪贴板，并用文件关联打开测试 TXT；若原剪贴板是其他格式，不会完整备份该格式。请在合适时运行。通知提交不等于通知按钮已点击验收。

脚本化 Windows 恢复测试（先从托盘退出接收器，确保本地 API 在运行）：

```powershell
& .\.tools\dotnet\dotnet.exe build windows\QDrop.sln
& .\.venv\Scripts\python.exe scripts\windows-recovery-test.py
```

此测试使用独立身份和 `.tools/windows-recovery`，实际验证剪贴板、重复 ACK、attempted 不重放、旧文本抑制和脚本只保存，会改变剪贴板。测试凭证文件只写忽略目录；不用于生产注册。

## 服务端部署（服务器上执行）

独立服务器使用 `--profile caddy`；已有 HTTPS 代理时使用部署说明中的 external-proxy compose 文件。部署前确认 DNS、80/443 与现有代理关系；不要为了部署停止或覆盖其他站点。

```bash
cd /srv/QDrop
cp deploy/.env.example deploy/.env
# 编辑 PUBLIC_DOMAIN / PUBLIC_BASE_URL 和容量策略；真实 .env 不提交。
docker compose --profile caddy --env-file deploy/.env -f deploy/compose.yaml config --quiet
docker compose --profile caddy --env-file deploy/.env -f deploy/compose.yaml up -d --build
docker compose --env-file deploy/.env -f deploy/compose.yaml exec api python -m app.cli enroll
# 替换为自己的域名
curl --fail https://qdrop.example.com/readyz
```

独立服务器使用 `--profile caddy` 启动 Caddy 和单实例 API；已有 Apache/Nginx/Caddy 的服务器按部署说明只启动 API，并由现有 HTTPS 代理转发。SQLite WAL 与私有磁盘放专用卷，API 以非 root 用户运行，公网不映射 API/数据目录。HTTPS 传正文，WSS 只提示；丢事件后仍从 inbox 补收。正文默认 commit 后 24 小时，敏感文本 5 分钟，ACK 后 5 分钟清理，清理周期 60 秒；活动下载租约最长 5 分钟。已接收文件留在用户接收目录，不随服务器 TTL 删除。

详细部署/备份/升级命令见 [部署说明](docs/DEPLOYMENT.md)，协议见 [protocol](protocol/README.md)，故障与下一步见 [已知问题](docs/KNOWN_ISSUES.md)。

首次安装的客户端服务地址为空，请在设置中填写自己服务器的 HTTPS origin。地址保存在 Android 私有配置及 Windows DPAPI 设置中，无需重新编译。Android 的包名/代码 namespace 是应用身份，不是网络地址，保留它可沿用现有签名与安装身份。仓库只提供保留示例域名，不包含实际服务器 IP、SSH 账号、域名或注册凭证。
