# 内置 ADB

`adb/` 包含 Android SDK Platform Tools 36.0.2 中用于 Windows 的 ADB 客户端和依赖：

- adb.exe
- AdbWinApi.dll
- AdbWinUsbApi.dll
- NOTICE.txt：随上游包提供的第三方声明
- source.properties：上游版本信息

这些文件来自本机 Android SDK 的 platform-tools，二进制文件原样复制。
NOTICE.txt 仅统一换行、展开制表符并清理行尾空白，保留上游声明和条款文字。
打包脚本会将其复制到 EXE 旁的 adb 文件夹，并与程序一起加入便携 ZIP。
更新版本时应同时更新整组二进制、声明和版本文件，重新验证设备连接。
