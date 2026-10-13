# 个人局域网模式

此模式面向同一 Wi-Fi 下的 Android 手机与 Windows 电脑，不经过公网服务器。Windows 电脑运行 QDrop API 和托盘接收器；手机准备分享内容后会自动发现当前网络中唯一已配对的 Windows 电脑并发送。

首次在每个地点各做一次配对：在电脑启动 API（`scripts/start-lan-server.ps1`）并把 Windows 接收器服务地址设为 `http://127.0.0.1:8000`；用 `python -m app.cli enroll` 分别生成 Windows 与 Android 的注册码。Android 首次配置填写电脑“显示局域网地址”给出的 `http://192.168.x.x:8000` 和注册码。注册完成后，Android 保存该电脑的配对资料。

Windows 防火墙需允许 TCP 8000 和 UDP 48735，且仅限“专用网络”。UDP 48735 仅用于发现请求和不含凭据的地址响应；文件、令牌和传输状态均走 HTTP API。个人局域网模式明确允许私有 IP 的 HTTP，公共 IP 和域名 HTTP 仍被客户端拒绝。不要在公共 Wi-Fi 使用此模式。

日常使用时保持 Windows 的本地 API 与 QDrop 托盘程序运行。手机从分享页选 QDrop，或在 QDrop 输入文字/选择文件；应用会在约 1.2 秒内发现已配对电脑后自动发送。没有发现目标或发现多台已配对电脑时不会发送，避免误投递。

当前本机 API 依赖 Python 3.12 虚拟环境；后续会将其纳入 Windows 安装包的启动流程。此文档不把该尚未完成的整合描述为已交付功能。
