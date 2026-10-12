# 发布与安装

在仓库根目录按 README 执行 sign-android.ps1、build.ps1、install-windows.ps1。正式 APK 为 artifacts/android/QDrop-release.apk，Debug 独立包为 QDrop-debug.apk；Windows 文件夹包为 artifacts/QDrop-windows-x64.zip，解压后运行 QDrop.App.exe，或执行安装脚本创建当前用户快捷方式。

正式签名 RSA 3072；证书 SHA-256：`20d0aba10b24a76d89a0811fdea2b63efcd13bca11c6f278f8dc182fdcc8f63a`。本机固定密钥位于仓库外 `%LOCALAPPDATA%\QDropSigning\release.jks`，密码为当前用户 DPAPI 文件。更新必须保留同一密钥；备份 JKS 并在原账户将密码安全保存到自己的密码管理器，单独 DPAPI 文件无法保证重装后解密。

已有签名可通过 Gradle 环境变量 QDROP_KEYSTORE、QDROP_STORE_PASSWORD、QDROP_KEY_PASSWORD、QDROP_KEY_ALIAS 注入；不要把秘密填入仓库、命令日志或签名配置文件。签名脚本禁止把密钥目录设在仓库内，并在 finally 清除密码环境变量。

正式包仅支持可信 HTTPS；Debug 额外允许本机 loopback。手机需安装确认及通知权限，拒绝通知不能视为传输已完成。Windows 包含 .NET 与 Windows App SDK 运行文件；已验证本机无系统 .NET 10 时启动，但纯净主机和通知按钮仍待测试。Windows EXE 当前未做 Authenticode 签名，不宣称可信发布者认证。校验分发包可用 artifacts/SHA256SUMS.txt。
