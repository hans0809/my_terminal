# Desk OS

个人桌面副屏终端 — 极简墨水屏风格系统监视器。

## Phase 1（当前）

默认主页显示：日期、时间、天气、CPU、GPU（含显存/温度）、RAM、Cursor Models / Other Models 用量与重置日、磁盘、网络、PING、今日键数、当前窗口/正在播放、运行时间，以及右下角隐藏入口。开机时逐行显字；小狗闲下来会沿底边走两步。

## 运行


```bash
cd desk_os
python main.py
```

若缺少依赖：

```bash
pip install -r requirements.txt
```

## 技术栈

- Python + FastAPI + PyWebView
- HTML / CSS / JavaScript
- psutil（系统监控）
- nvidia-smi（GPU，可选）
- Cursor 本机登录态（额度，可选）

## 显示器

系统枚举的显示器序号 **≠** Windows 设置里的「显示器 1/2/3」。

查看本机实际序号：

```bash
python -m backend.display_utils
```

默认自动选择**非主屏中面积最小**的显示器（通常是 iPad 副屏）。

手动指定：

```bash
set DESK_OS_MONITOR=1
python main.py
```

切换全屏/窗口时会保持在当前显示器，不会跳回主屏。

## 可选配置

```bash
set DESK_OS_PING_HOST=192.168.1.100      # ping 目标（默认 1.1.1.1）
set DESK_OS_WEATHER_LAT=31.2             # 天气纬度（默认北京）
set DESK_OS_WEATHER_LON=121.5            # 天气经度
set DESK_OS_CURSOR_TOKEN=...             # 可选：覆盖 Cursor token（默认读本机登录态）
```

Cursor 用量（`CUR` / `OTH`）对应仪表盘里的 **Cursor Models** 与 **Other Models** 已用百分比。超过 80% 时该行加深并全刷一次墨水；重置日在 `RST`。无需 API Key；未登录或拉取失败时显示 `N/A`。后台约 90 秒刷新一次。

## 快捷键

- `F11` — 切换全屏 / 窗口模式（默认窗口 420×720，全屏时放大排版）
- `Esc` — 返回默认主页（Phase 1 占位页可用）
- `Alt + F4` — 关闭程序
