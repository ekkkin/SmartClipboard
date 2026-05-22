# SmartClipboard - 悬浮剪切板管理器

<!-- 徽章 -->
[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> 一个优雅的 Windows 悬浮剪切板工具，支持剪切板历史、收藏、备忘录和钉出窗口，
> **专为 RDP 远程桌面环境优化**，在远程会话中也能快速粘贴。

![预览图](docs/preview.png)

---

## 功能特性

### 核心功能

| 功能 | 说明 |
|------|------|
| **剪切板历史** | 自动记录复制内容（最近 200 条），点击即粘贴到光标位置 |
| **收藏** | 右键收藏常用内容，跨会话持久化保留 |
| **备忘录** | 新建/编辑/删除备忘录，双击粘贴，支持置顶提醒 |
| **钉出窗口** | 右键将单条内容钉到独立小窗口，单击粘贴，右键复制 |

### 增强功能

- **提醒通知**：右键备忘录设置当天提醒时间（默认 17:00），到点系统托盘通知
- **窗口钉住**：钉住后点击内容不关闭窗口，Alt+Q 仍可关闭
- **实时搜索**：按 Ctrl+F 或直接在搜索框输入关键词
- **拖拽移动 + 边缘缩放**：标题栏拖动窗口，边缘拖拽调整大小
- **开机自启动**：托盘菜单中一键开启

### 专为 RDP 优化

采用正确的时序设计（`setText` → 等待 200ms → `hide` → 等待 200ms → `Ctrl+V`），
确保在 Windows RDP 远程桌面环境下剪贴板内容能正确同步到远程会话，粘贴的是最新内容。

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Alt + Q` | 显示/隐藏剪切板窗口 |
| `Alt + W` | 直接打开收藏模式 |
| `单击条目` | 粘贴内容（剪切板/收藏模式） |
| `双击条目` | 粘贴内容（备忘录模式） |
| `右键条目` | 弹出操作菜单（收藏/钉出/编辑/删除...） |

## 预览截图

> 截图位置：`docs/preview.png`

浅绿色透明 Glassmorphism 风格，窗口毛玻璃质感，视觉舒适。

## 安装与运行

### 方式一：直接运行 EXE（推荐）

下载 [Releases](https://github.com/YOUR_USERNAME/SmartClipboard/releases) 中的 `SmartClipboard.exe`，双击运行即可。

### 方式二：从源码运行

```bash
# 克隆仓库
git clone https://github.com/YOUR_USERNAME/SmartClipboard.git
cd SmartClipboard

# 安装依赖
pip install -r requirements.txt

# 运行
python smart_clipboard.py
```

### 方式三：自行打包

```bash
# 安装依赖
pip install -r requirements.txt
pip install pyinstaller

# 打包（输出 dist/SmartClipboard.exe）
pyinstaller --onefile --windowed --name SmartClipboard smart_clipboard.py
```

## 依赖

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.8+ | 运行环境 |
| PyQt5 | >= 5.15.0 | GUI 界面 |
| pynput | >= 1.7.6 | 全局快捷键监听 |
| pywin32 | >= 305 | Windows API（仅 Windows） |

## 数据存储

所有数据存储在 `~/.smart_clipboard/data.db`（SQLite 数据库），包括：

- `clipboard_history` — 剪切板历史记录
- `favorites` — 收藏内容
- `memos` — 备忘录（含提醒时间）

错误日志：`~/.smart_clipboard/error.log`

## 项目结构

```
SmartClipboard/
├── smart_clipboard.py      # 主程序（约 1800 行）
├── requirements.txt         # Python 依赖
├── build.bat               # 打包脚本
├── run.bat                 # 运行脚本
├── README.md               # 本文件
├── LICENSE                 # MIT 许可证
└── docs/
    ├── preview.png         # 预览截图
    └── RDP剪贴板同步技术总结.md  # RDP 问题修复记录
```

## 代码架构

```
smart_clipboard.py
├── 配置常量
│   ├── DATA_DIR, LOG_PATH, TYPE_DELAY_MS
│   └── MODE_TITLES, CLEAR_CONFIRM, RESIZE_CURSORS
├── 工具函数
│   ├── log_error()              # 错误日志
│   ├── exception_hook()         # 全局异常处理
│   ├── paste_content()          # 粘贴内容（RDP 优化版）
│   └── build_item_widget()      # 列表项 UI 构建
├── 数据层
│   └── StorageManager           # SQLite 数据库操作
├── 核心功能
│   ├── ClipboardMonitor         # 剪切板监听线程
│   ├── SingleInstance           # 单实例互斥锁
│   ├── HotkeyListener           # Alt+Q / Alt+W 快捷键
│   └── FloatingWindow           # 主悬浮窗口
├── 辅助窗口
│   ├── PinnedItemWindow         # 钉出小窗口
│   ├── MemoEditorWindow         # 备忘录编辑窗口
│   └── TimePickerDialog         # 提醒时间选择
└── 系统集成
    ├── AutoStartManager         # 开机自启动
    └── SmartClipboardApp        # 应用主类
```

## UI 主题

浅绿色透明 Glassmorphism 风格：

| 元素 | 颜色 |
|------|------|
| 窗口背景 | `rgba(200, 240, 210, 180)` |
| 容器背景 | `rgba(220, 245, 225, 0.65)` |
| 主文字 | `#1a3a2a`（深绿色） |
| 强调色 | `rgba(60, 179, 113, ...)`（海绿色） |
| 边框 | `rgba(120, 200, 140, 0.4)` |

## 常见问题

**Q: 快捷键没反应？**

确保以管理员权限运行程序（pynput 在某些系统上需要管理员权限）。

**Q: RDP 环境下粘贴的是旧内容？**

程序已针对 RDP 做了专门优化（见 `docs/RDP剪贴板同步技术总结.md`）。如果仍有问题，可以调整 `paste_content()` 中的延迟时间（当前 200ms）。

**Q: 提示"已有实例在运行"？**

程序使用单实例互斥锁，同时只能运行一个实例。关闭后台进程或重启电脑即可。

## 更新日志

- **v1.0.0** — 初始版本，支持剪切板历史、收藏、备忘录、钉出窗口
- **v1.1.0** — 修复 RDP 远程桌面粘贴延迟问题

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可证

[MIT License](LICENSE) — 自由使用、修改和分发。
