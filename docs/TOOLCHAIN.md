# 工具链

本机实际使用：Windows 11 x64，PowerShell；.NET SDK 10.0.401（global.json）；Python 3.12.15、uv 0.13.0；JDK 20.0.1（输出 JVM 17）；Gradle 8.13；Android SDK/platform/build-tools 36，AGP 8.11.1，Kotlin 2.1.20。

服务端 FastAPI 0.143.0、Uvicorn 0.54.0、SQLAlchemy 2.1.4、Alembic 1.20.0，完整依赖见 server/requirements.lock 与 requirements-dev.lock。Windows Microsoft.WindowsAppSDK 1.8.260921001、Microsoft.Data.Sqlite 10.0.0，SQLite 原生库显式更新至 3.50.3；NuGet packages.lock.json 与 Android gradle.lockfile 已提交源码。

bootstrap.ps1 安装本地工具，不要求替换系统 SDK。组件下载、编译与使用实际完成；完整 bootstrap 在全新机器从零执行尚未验证。Gradle wrapper 实际运行验证完成。版本升级应重新验证签名、通知与两端共享 fixture。
