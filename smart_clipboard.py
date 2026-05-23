"""
悬浮剪切板 - Smart Clipboard Manager
快捷键 Alt+Q 调出，点击模拟输入，支持收藏和备忘录
"""

import sys
import os
import sqlite3
import time
import ctypes
from ctypes import wintypes
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QListWidgetItem, QLineEdit, QPushButton, QLabel, QMenu,
    QSystemTrayIcon, QAction, QAbstractItemView, QFrame,
    QTextEdit, QDialog, QMessageBox, QTimeEdit
)
from PyQt5.QtCore import Qt, QTimer, QSize, pyqtSignal, QObject, QThread, QTime
from PyQt5.QtGui import QIcon, QColor, QPixmap, QPainter, QBrush, QPen, QCursor


# ============================================================
# 配置常量
# ============================================================
DATA_DIR = os.path.join(os.path.expanduser("~"), ".smart_clipboard")
LOG_PATH = os.path.join(DATA_DIR, "error.log")
TYPE_DELAY_MS = 500  # 缩短到500ms，主要等待 Alt 键释放
# 全局粘贴标志，用于暂停剪贴板监听
_is_pasting = False

# ============================================================
# Win32 剪贴板操作（用于产生多条剪贴板历史）
# ============================================================
def _set_clipboard_win32(text: str) -> bool:
    """使用 Win32 API 设置剪贴板，产生独立的历史记录"""
    try:
        import win32clipboard
        import win32con
        
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
        return True
    except Exception as e:
        print(f"Win32 剪贴板设置失败: {e}")
        return False

def _set_clipboard_double(text: str) -> bool:
    """一次性添加两条相同内容到剪贴板历史（一次 Open 中连续设置两次）"""
    try:
        import win32clipboard
        import win32con
        
        # 方案 C：一次 OpenClipboard 中连续设置两次
        win32clipboard.OpenClipboard()
        try:
            # 第一次 Empty + Set
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            
            # 第二次 Empty + Set（不关闭剪贴板）
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
        
        return True
    except Exception as e:
        print(f"Win32 剪贴板设置失败: {e}")
        return False

MODE_TITLES = {"clipboard": "📋 剪切板", "favorites": "⭐ 收藏", "memos": "📝 备忘录"}
CLEAR_CONFIRM = {"clipboard": "剪切板历史", "favorites": "收藏", "memos": "备忘录"}

RESIZE_CURSORS = {
    'top': Qt.CursorShape.SizeVerCursor, 'bottom': Qt.CursorShape.SizeVerCursor,
    'left': Qt.CursorShape.SizeHorCursor, 'right': Qt.CursorShape.SizeHorCursor,
    'top_left': Qt.CursorShape.SizeFDiagCursor, 'top_right': Qt.CursorShape.SizeFDiagCursor,
    'bottom_left': Qt.CursorShape.SizeBDiagCursor, 'bottom_right': Qt.CursorShape.SizeBDiagCursor,
}

MENU_STYLE = """
    QMenu {
        background-color: rgba(230, 248, 235, 235);
        border: 1px solid rgba(120, 200, 140, 0.5);
        border-radius: 10px;
        padding: 6px;
        color: #1a3a2a;
    }
    QMenu::item {
        padding: 8px 20px;
        border-radius: 6px;
    }
    QMenu::item:selected {
        background-color: rgba(60, 179, 113, 80);
    }
"""


# ============================================================
# 工具函数
# ============================================================
def log_error(error_msg: str) -> None:
    """记录错误到日志文件"""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*50}\n{datetime.now()}\n{error_msg}")
    except Exception:
        pass


def exception_hook(exctype, value, tb):
    """全局异常处理钩子"""
    import traceback as tb_mod
    error_msg = ''.join(tb_mod.format_exception(exctype, value, tb))
    print(f"未捕获异常:\n{error_msg}")
    log_error(error_msg)


def paste_content(widget, content: str, show_after: bool = False) -> None:
    """
    复制到剪贴板并模拟 Ctrl+V
    
    RDP环境下的正确时序：
    1. setText（窗口还在，RDP正常同步）
    2. 等200ms让RDP同步完成
    3. hide（焦点回到目标窗口）
    4. 等200ms让焦点稳定
    5. Ctrl+V（粘贴到目标窗口）
    """
    global _is_pasting

    def _do_ctrl_v():
        """步骤5: 发送 Ctrl+V"""
        global _is_pasting
        try:
            from pynput.keyboard import Controller, Key
            keyboard = Controller()
            
            # 确保 Alt 键已释放
            keyboard.release(Key.alt)
            keyboard.release(Key.alt_l)
            keyboard.release(Key.alt_r)
            
            # 发送 Ctrl+V
            with keyboard.pressed(Key.ctrl):
                keyboard.tap('v')
            
            if show_after:
                widget.show()
                widget.raise_()
            
            QTimer.singleShot(300, lambda: globals().update({'_is_pasting': False}))
        except Exception as e:
            log_error(f"Ctrl+V 失败: {e}")
            _is_pasting = False

    def _do_hide():
        """步骤3-4: 隐藏窗口，等200ms后再Ctrl+V"""
        widget.hide()
        QTimer.singleShot(200, _do_ctrl_v)

    def _do_paste():
        """步骤1-2: 设置剪贴板，等200ms让RDP同步"""
        global _is_pasting
        _is_pasting = True
        QApplication.clipboard().setText(content)
        QTimer.singleShot(200, _do_hide)

    _is_pasting = True
    QTimer.singleShot(50, _do_paste)

    # ================================================================
    # 备用方案: keyboard.write 逐字输入（不依赖剪贴板）
    # 如需切换，取消下面的注释并注释掉上面的 Ctrl+V 部分
    # ================================================================
    # import keyboard
    # text = content.replace('\n', ' ').replace('\r', '')
    # keyboard.write(text, delay=0.01)
    # ================================================================


def build_item_widget(lines: list, item_height: int = 60, bg_color: str = '') -> QWidget:
    """构建 QListWidget 的自定义项 widget，内容垂直居中"""
    widget = QWidget()
    widget.setMinimumHeight(item_height)
    # 如果有自定义背景色，设置圆角背景
    if bg_color:
        widget.setStyleSheet(f"""
            QWidget {{
                background-color: {bg_color};
                border: 1px solid rgba(0, 0, 0, 0.08);
                border-radius: 10px;
                margin: 2px 4px;
            }}
        """)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(14, 6, 14, 6)
    layout.setSpacing(2)

    layout.addStretch(1)
    for text, style in lines:
        label = QLabel(text)
        label.setStyleSheet(f"{style} background: transparent; border: none;")
        label.setWordWrap(True)
        layout.addWidget(label)
    layout.addStretch(1)

    return widget


# ============================================================
# 数据存储
# ============================================================
class StorageManager:
    """SQLite 数据存储管理器"""

    def __init__(self, data_dir: str = None):
        self.data_dir = data_dir or DATA_DIR
        os.makedirs(self.data_dir, exist_ok=True)
        self.db_path = os.path.join(self.data_dir, "data.db")
        self._init_db()

    def _init_db(self):
        """初始化数据库表结构"""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL, category TEXT DEFAULT 'default',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    color TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS memos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL, content TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    remind_time TEXT,
                    color TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS clipboard_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL, timestamp TEXT NOT NULL,
                    is_favorite INTEGER DEFAULT 0,
                    color TEXT DEFAULT ''
                );
            ''')
            # 迁移：为旧表添加 color 列
            for table in ('favorites', 'memos', 'clipboard_history'):
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN color TEXT DEFAULT ''")
                except Exception:
                    pass

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _query(self, sql: str, params: tuple = (), fetch: bool = False):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql, params)
            conn.commit()
            if fetch:
                return [dict(r) for r in cursor.fetchall()]

    # 收藏操作
    def add_favorite(self, content: str, category: str = "default"):
        now = self._now()
        self._query("INSERT INTO favorites (content, category, created_at, updated_at) VALUES (?,?,?,?)",
                    (content, category, now, now))

    def get_favorites(self, category: str = None):
        if category:
            return self._query("SELECT * FROM favorites WHERE category=? ORDER BY updated_at DESC", (category,), fetch=True)
        return self._query("SELECT * FROM favorites ORDER BY updated_at DESC", fetch=True)

    def remove_favorite(self, fav_id: int = None, content: str = None):
        if fav_id:
            self._query("DELETE FROM favorites WHERE id=?", (fav_id,))
        elif content:
            self._query("DELETE FROM favorites WHERE content=?", (content,))

    def is_favorite(self, content: str) -> bool:
        return bool(self._query("SELECT id FROM favorites WHERE content=?", (content,), fetch=True))

    def clear_favorites(self):
        self._query("DELETE FROM favorites")

    # 备忘录操作
    def add_memo(self, title: str, content: str):
        now = self._now()
        self._query("INSERT INTO memos (title, content, created_at, updated_at) VALUES (?,?,?,?)",
                    (title, content, now, now))

    def get_memos(self):
        return self._query("SELECT * FROM memos ORDER BY updated_at DESC", fetch=True)

    def update_memo(self, memo_id: int, title: str, content: str):
        self._query("UPDATE memos SET title=?, content=?, updated_at=? WHERE id=?",
                    (title, content, self._now(), memo_id))

    def remove_memo(self, memo_id: int):
        self._query("DELETE FROM memos WHERE id=?", (memo_id,))

    def clear_memos(self):
        self._query("DELETE FROM memos")

    # 提醒操作
    def set_remind_time(self, memo_id: int, remind_time: str = None):
        """设置备忘录提醒时间，格式 HH:MM，传 None 取消提醒"""
        self._query("UPDATE memos SET remind_time=?, updated_at=? WHERE id=?",
                    (remind_time, self._now(), memo_id))

    def get_pending_reminders(self):
        """获取今天待提醒的备忘录（remind_time >= 当前时间）"""
        now_time = datetime.now().strftime("%H:%M")
        return self._query(
            "SELECT * FROM memos WHERE remind_time IS NOT NULL AND remind_time != '' "
            "AND remind_time >= ? ORDER BY remind_time",
            (now_time,), fetch=True)

    # 剪切板历史操作
    def add_history(self, content: str):
        now = self._now()
        with sqlite3.connect(self.db_path) as conn:
            existing = conn.execute("SELECT id FROM clipboard_history WHERE content=?", (content,)).fetchone()
            if existing:
                conn.execute("UPDATE clipboard_history SET timestamp=? WHERE id=?", (now, existing[0]))
            else:
                conn.execute("INSERT INTO clipboard_history (content, timestamp) VALUES (?,?)", (content, now))
            conn.execute("DELETE FROM clipboard_history WHERE id NOT IN (SELECT id FROM clipboard_history ORDER BY timestamp DESC LIMIT 200)")
            conn.commit()

    def get_history(self, limit: int = 50):
        return self._query("SELECT * FROM clipboard_history ORDER BY timestamp DESC LIMIT ?", (limit,), fetch=True)

    def delete_history_item(self, item_id: int):
        self._query("DELETE FROM clipboard_history WHERE id=?", (item_id,))

    def set_item_color(self, item_type: str, item_id: int, color: str):
        """设置条目的背景颜色"""
        table_map = {"clipboard": "clipboard_history", "favorite": "favorites", "memo": "memos"}
        table = table_map.get(item_type)
        if table:
            self._query(f"UPDATE {table} SET color=? WHERE id=?", (color, item_id))

    def clear_history(self):
        self._query("DELETE FROM clipboard_history")


# ============================================================
# 剪切板监听
# ============================================================
class ClipboardMonitor(QThread):
    """后台剪切板监听线程"""
    new_clip = pyqtSignal(str)

    def __init__(self, storage: StorageManager):
        super().__init__()
        self.storage = storage
        self._running = True

    def run(self):
        clipboard = QApplication.clipboard()
        last = clipboard.text() or ""
        while self._running:
            try:
                # 如果正在粘贴操作，跳过本次检测
                if globals().get('_is_pasting', False):
                    self.msleep(100)
                    continue

                text = clipboard.text()
                if text and text != last:
                    last = text
                    self.storage.add_history(text)
                    self.new_clip.emit(text)
            except Exception as e:
                print(f"剪切板监听异常: {e}")
                log_error(f"剪切板监听异常: {e}")
            self.msleep(300)

    def stop(self):
        self._running = False
        self.wait()


# ============================================================
# 单实例检测
# ============================================================
class SingleInstance:
    """Windows 单实例互斥锁"""

    def __init__(self):
        self.mutex = None

    def acquire(self) -> bool:
        try:
            import ctypes
            self.mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\SmartClipboard_SingleInstance")
            return ctypes.windll.kernel32.GetLastError() != 183
        except Exception:
            return True

    def release(self):
        if self.mutex:
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(self.mutex)
            except Exception:
                pass


# ============================================================
# 全局快捷键监听 - 使用 keyboard 库（支持 suppress 拦截）
# ============================================================
class HotkeyListener(QObject):
    """Alt+Q / Alt+W 全局快捷键监听 - 使用 keyboard 库"""
    toggle_requested = pyqtSignal()
    favorites_requested = pyqtSignal()

    def __init__(self, callback, favorites_callback=None):
        super().__init__()
        self.toggle_requested.connect(callback)
        if favorites_callback:
            self.favorites_requested.connect(favorites_callback)
        
        self._hotkey_thread = None
        self._running = False

    def _hotkey_loop(self):
        """在独立线程中运行热键监听"""
        try:
            import keyboard
            
            # 注册 Alt+Q - suppress=True 表示拦截热键，不传递给其他程序
            keyboard.add_hotkey('alt+q', self._on_toggle, suppress=True, trigger_on_release=False)
            
            # 注册 Alt+W
            keyboard.add_hotkey('alt+w', self._on_favorites, suppress=True, trigger_on_release=False)
            
            # 保持线程运行
            while self._running:
                time.sleep(0.1)
                
        except Exception as e:
            print(f"热键监听错误: {e}")

    def _on_toggle(self):
        """Alt+Q 回调"""
        self.toggle_requested.emit()

    def _on_favorites(self):
        """Alt+W 回调"""
        self.favorites_requested.emit()

    def start(self) -> bool:
        """启动热键监听"""
        try:
            self._running = True
            
            # 在后台线程中运行热键监听
            import threading
            self._hotkey_thread = threading.Thread(target=self._hotkey_loop, daemon=True)
            self._hotkey_thread.start()
            
            return True
        except Exception as e:
            print(f"热键监听启动失败: {e}")
            return False

    def stop(self):
        """停止热键监听"""
        self._running = False
        
        try:
            import keyboard
            keyboard.unhook_all()
        except:
            pass
        
        # 等待线程结束
        if self._hotkey_thread and self._hotkey_thread.is_alive():
            self._hotkey_thread.join(timeout=1.0)


# ============================================================
# 主悬浮窗口
# ============================================================
class FloatingWindow(QWidget):
    """毛玻璃风格悬浮剪切板主窗口"""

    def __init__(self, storage: StorageManager, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.current_mode = "clipboard"
        self.pinned = False
        self.memo_editor = None
        self._drag_pos = None
        self._resize_edge = None
        self._resize_start_pos = None
        self._resize_start_geo = None
        self._resize_margin = 6

        self.setMinimumSize(200, 250)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._init_ui()
        self._apply_style()
        self._load_data()

    def _init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.resize(440, 580)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.container = QFrame()
        self.container.setObjectName("container")
        cl = QVBoxLayout(self.container)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(8)

        # 标题栏
        tb = QHBoxLayout()
        tb.setSpacing(8)
        self.btn_pin = QPushButton("📌")
        self.btn_pin.setObjectName("pinBtn")
        self.btn_pin.setFixedSize(32, 32)
        self.btn_pin.setToolTip("钉住窗口")
        self.btn_pin.clicked.connect(self._toggle_pin)
        tb.addWidget(self.btn_pin)

        self.title_label = QLabel("📋 剪切板")
        self.title_label.setObjectName("titleLabel")
        tb.addWidget(self.title_label)
        tb.addStretch()

        self.mode_buttons = {}
        for mode, label in [("clipboard", "📋 历史"), ("favorites", "⭐ 收藏"), ("memos", "📝 备忘")]:
            btn = QPushButton(label)
            btn.setObjectName("modeBtn")
            btn.clicked.connect(lambda checked, m=mode: self._switch_mode(m))
            tb.addWidget(btn)
            self.mode_buttons[mode] = btn
        self.mode_buttons["clipboard"].setProperty("active", True)

        cl.addLayout(tb)

        # 搜索框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索...")
        self.search_input.setObjectName("searchInput")
        self.search_input.textChanged.connect(self._on_search)
        cl.addWidget(self.search_input)

        # 列表
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("listWidget")
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list_widget.setSpacing(4)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        cl.addWidget(self.list_widget)

        # 底部按钮
        bb = QHBoxLayout()
        bb.setSpacing(8)
        self.btn_add_memo = QPushButton("➕ 新建备忘")
        self.btn_add_memo.setObjectName("bottomBtn")
        self.btn_add_memo.clicked.connect(self._add_memo)
        self.btn_add_memo.setVisible(False)
        bb.addWidget(self.btn_add_memo)

        self.btn_clear = QPushButton("🗑️ 清空")
        self.btn_clear.setObjectName("bottomBtn")
        self.btn_clear.clicked.connect(self._clear_current)
        bb.addWidget(self.btn_clear)

        self.btn_close = QPushButton("✕ 关闭")
        self.btn_close.setObjectName("closeBtn")
        self.btn_close.clicked.connect(self.hide)
        bb.addWidget(self.btn_close)
        cl.addLayout(bb)

        main_layout.addWidget(self.container)

    def _apply_style(self):
        """应用浅绿色透明 Glassmorphism 风格"""
        self.setStyleSheet("""
            QWidget {
                font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
                font-size: 16px;
            }
            #container {
                background: rgba(220, 245, 225, 0.65);
                border: 1px solid rgba(120, 200, 140, 0.4);
                border-radius: 20px;
            }
            #titleLabel {
                color: #1a3a2a;
                font-size: 19px;
                font-weight: 600;
                padding: 4px;
            }
            #searchInput {
                background: rgba(255, 255, 255, 0.55);
                border: 1px solid rgba(120, 200, 140, 0.5);
                border-radius: 12px;
                padding: 10px 14px;
                color: #1a3a2a;
                font-size: 16px;
            }
            #searchInput:focus {
                background: rgba(255, 255, 255, 0.75);
                border: 1px solid rgba(60, 160, 90, 0.8);
            }
            #searchInput::placeholder {
                color: rgba(60, 100, 70, 0.5);
            }
            #listWidget {
                background: transparent;
                border: none;
                outline: none;
                padding: 4px;
            }
            #listWidget::item {
                background: rgba(255, 255, 255, 0.45);
                border: 1px solid rgba(120, 200, 140, 0.3);
                border-radius: 12px;
                padding: 2px 4px;
                color: #1a3a2a;
                min-height: 40px;
                margin: 2px 0;
            }
            #listWidget::item:hover {
                background: rgba(144, 238, 144, 0.4);
                border: 1px solid rgba(60, 179, 113, 0.6);
            }
            #listWidget::item:selected {
                background: rgba(60, 179, 113, 0.45);
                border: 1px solid rgba(60, 179, 113, 0.9);
            }
            QScrollBar:vertical {
                background: transparent;
                width: 6px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(60, 160, 90, 60);
                border-radius: 3px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(60, 160, 90, 120);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            #modeBtn {
                background: rgba(255, 255, 255, 0.45);
                border: 1px solid rgba(120, 200, 140, 0.4);
                border-radius: 10px;
                padding: 6px 14px;
                color: #2d5a3d;
                font-size: 15px;
                font-weight: 500;
            }
            #modeBtn:hover {
                background: rgba(255, 255, 255, 0.65);
                color: #1a3a2a;
                border: 1px solid rgba(60, 179, 113, 0.6);
            }
            #modeBtn[active="true"] {
                background: rgba(60, 179, 113, 0.7);
                border: 1px solid rgba(60, 179, 113, 1.0);
                color: #ffffff;
                font-weight: 600;
            }
            #bottomBtn {
                background: rgba(255, 255, 255, 0.45);
                border: 1px solid rgba(120, 200, 140, 0.4);
                border-radius: 10px;
                padding: 8px 16px;
                color: #2d5a3d;
                font-size: 15px;
                font-weight: 500;
            }
            #bottomBtn:hover {
                background: rgba(220, 80, 80, 0.75);
                border: 1px solid rgba(220, 80, 80, 1.0);
                color: #ffffff;
            }
            #closeBtn {
                background: rgba(60, 179, 113, 0.5);
                border: 1px solid rgba(60, 179, 113, 0.7);
                border-radius: 10px;
                padding: 8px 16px;
                color: #1a3a2a;
                font-size: 12px;
                font-weight: 600;
            }
            #closeBtn:hover {
                background: rgba(220, 80, 80, 0.7);
                border: 1px solid rgba(220, 80, 80, 0.9);
                color: #ffffff;
            }
            #pinBtn {
                background: rgba(255, 255, 255, 0.45);
                border: 1px solid rgba(120, 200, 140, 0.4);
                border-radius: 10px;
                font-size: 16px;
                padding: 4px;
            }
            #pinBtn:hover {
                background: rgba(245, 180, 60, 0.6);
                border: 1px solid rgba(245, 180, 60, 0.8);
            }
            #pinBtn[pinned="true"] {
                background: rgba(245, 180, 60, 0.75);
                border: 2px solid rgba(245, 180, 60, 1.0);
            }
        """)

    def _switch_mode(self, mode: str):
        self.current_mode = mode
        self.search_input.clear()
        for m, btn in self.mode_buttons.items():
            btn.setProperty("active", m == mode)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.title_label.setText(MODE_TITLES.get(mode, "📋 剪切板"))
        self.btn_add_memo.setVisible(mode == "memos")
        self._load_data()

    def _load_data(self):
        self.list_widget.clear()
        if self.current_mode == "clipboard":
            for item in self.storage.get_history(50):
                self._add_list_item(item['content'], item['timestamp'], item['id'], "clipboard",
                                    item.get('color', ''))
        elif self.current_mode == "favorites":
            for item in self.storage.get_favorites():
                self._add_list_item(item['content'], item['created_at'], item['id'], "favorite",
                                    item.get('color', ''))
        elif self.current_mode == "memos":
            for item in self.storage.get_memos():
                self._add_memo_item(item['title'], item['content'], item['id'],
                                    item.get('remind_time'), item.get('color', ''))

    def _add_list_item(self, content: str, timestamp: str, item_id: int, item_type: str,
                       bg_color: str = ''):
        display = content.replace('\n', ' ')
        if len(display) > 60:
            display = display[:60] + "..."
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, content)
        item.setData(Qt.ItemDataRole.UserRole + 1, item_id)
        item.setData(Qt.ItemDataRole.UserRole + 2, item_type)
        item.setData(Qt.ItemDataRole.UserRole + 3, bg_color)
        w = build_item_widget([
            (display, "color: #1a3a2a; font-size: 16px;"),
        ], bg_color=bg_color)
        item.setSizeHint(QSize(400, 56))
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, w)

    def _add_memo_item(self, title: str, content: str, memo_id: int,
                       remind_time: str = None, bg_color: str = ''):
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, content)
        item.setData(Qt.ItemDataRole.UserRole + 1, memo_id)
        item.setData(Qt.ItemDataRole.UserRole + 2, "memo")
        item.setData(Qt.ItemDataRole.UserRole + 3, bg_color)
        preview = content.replace('\n', ' ')
        if len(preview) > 50:
            preview = preview[:50] + "..."
        lines = [
            (f"📝 {title}", "color: #1a6b3a; font-size: 16px; font-weight: bold;"),
            (preview, "color: rgba(60, 100, 70, 0.7); font-size: 15px;"),
        ]
        if remind_time:
            lines.append((f"⏰ 今天 {remind_time}", "color: #e67e22; font-size: 14px;"))
        item_height = 82 if remind_time else 60
        w = build_item_widget(lines, item_height, bg_color=bg_color)
        item.setSizeHint(QSize(400, item_height))
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, w)

    def _on_search(self, text: str):
        if not text:
            self._load_data()
            return
        self.list_widget.clear()
        t = text.lower()
        if self.current_mode == "clipboard":
            for item in self.storage.get_history(200):
                if t in item['content'].lower():
                    self._add_list_item(item['content'], item['timestamp'], item['id'], "clipboard",
                                        item.get('color', ''))
        elif self.current_mode == "favorites":
            for item in self.storage.get_favorites():
                if t in item['content'].lower():
                    self._add_list_item(item['content'], item['created_at'], item['id'], "favorite",
                                        item.get('color', ''))
        elif self.current_mode == "memos":
            for item in self.storage.get_memos():
                if t in item['title'].lower() or t in item['content'].lower():
                    self._add_memo_item(item['title'], item['content'], item['id'],
                                        item.get('remind_time'), item.get('color', ''))

    def _on_item_clicked(self, item: QListWidgetItem):
        content = item.data(Qt.ItemDataRole.UserRole)
        item_type = item.data(Qt.ItemDataRole.UserRole + 2)
        if item_type == "memo" or not content:
            return
        paste_content(self, content, show_after=self.pinned)

    def _on_item_double_clicked(self, item: QListWidgetItem):
        if item.data(Qt.ItemDataRole.UserRole + 2) != "memo":
            return
        content = item.data(Qt.ItemDataRole.UserRole)
        if content:
            paste_content(self, content)

    def _add_memo(self):
        if self.memo_editor and self.memo_editor.isVisible():
            self.memo_editor.raise_()
            self.memo_editor.activateWindow()
            self.hide()
            return

        self.memo_editor = MemoEditorWindow(self.storage, parent=None)
        self.memo_editor.show_at_cursor()
        self.hide()

    def _clear_current(self):
        name = CLEAR_CONFIRM.get(self.current_mode)
        if not name:
            return
        reply = QMessageBox.question(self, "确认清空", f"确定要清空所有{name}吗？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        clear_fn = {"clipboard": self.storage.clear_history, "favorites": self.storage.clear_favorites,
                    "memos": self.storage.clear_memos}
        clear_fn[self.current_mode]()
        self._load_data()

    def _toggle_pin(self):
        self.pinned = not self.pinned
        self.btn_pin.setProperty("pinned", self.pinned)
        self.btn_pin.setText("📍" if self.pinned else "📌")
        self.btn_pin.setToolTip("取消钉住" if self.pinned else "钉住窗口")
        self.btn_pin.style().unpolish(self.btn_pin)
        self.btn_pin.style().polish(self.btn_pin)

    def refresh(self):
        self._load_data()

    # 鼠标事件处理
    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        edge = self._get_resize_edge(event.pos())
        if edge:
            self._resize_edge = edge
            self._resize_start_pos = event.globalPos()
            self._resize_start_geo = self.geometry()
            event.accept()
            return
        if self._is_in_title_bar(event.pos()):
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.NoButton:
            edge = self._get_resize_edge(event.pos())
            if edge and edge in RESIZE_CURSORS:
                self.setCursor(RESIZE_CURSORS[edge])
            elif self._is_in_title_bar(event.pos()):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.unsetCursor()
            return
        if event.buttons() == Qt.MouseButton.LeftButton:
            if self._resize_edge:
                self._do_resize(event.globalPos())
                event.accept()
                return
            if self._drag_pos is not None:
                self.move(event.globalPos() - self._drag_pos)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        self._resize_edge = None
        self._resize_start_pos = None
        self._resize_start_geo = None
        super().mouseReleaseEvent(event)

    def _is_in_title_bar(self, pos) -> bool:
        return pos.y() < 50 and self.container.rect().contains(pos)

    def _get_resize_edge(self, pos):
        m = self._resize_margin
        edges = []
        if pos.y() < m: edges.append('top')
        if pos.y() > self.height() - m: edges.append('bottom')
        if pos.x() < m: edges.append('left')
        if pos.x() > self.width() - m: edges.append('right')
        return '_'.join(edges) if len(edges) == 2 else (edges[0] if len(edges) == 1 else None)

    def _do_resize(self, global_pos):
        if not self._resize_start_geo or not self._resize_start_pos:
            return
        delta = global_pos - self._resize_start_pos
        geo = self._resize_start_geo
        min_w, min_h = self.minimumWidth(), self.minimumHeight()
        x, y, w, h = geo.x(), geo.y(), geo.width(), geo.height()
        if 'right' in self._resize_edge: w = max(min_w, w + delta.x())
        if 'bottom' in self._resize_edge: h = max(min_h, h + delta.y())
        if 'left' in self._resize_edge:
            w = max(min_w, w - delta.x())
            if w > min_w: x = geo.x() + delta.x()
        if 'top' in self._resize_edge:
            h = max(min_h, h - delta.y())
            if h > min_h: y = geo.y() + delta.y()
        self.setGeometry(x, y, w, h)

    def show_at_cursor(self):
        pos = QCursor.pos()
        screen = QApplication.primaryScreen().geometry()
        x = pos.x() - self.width() // 2
        y = pos.y() - 20
        x = max(screen.left() + 10, min(x, screen.right() - self.width() - 10))
        y = max(screen.top() + 10, min(y, screen.bottom() - self.height() - 10))
        self.move(x, y)
        self.show()
        self.raise_()
        # 延迟激活窗口，确保 Alt 键已释放，避免键盘事件被错误传递
        QTimer.singleShot(100, self.activateWindow)


# ============================================================
# 钉出小窗口
# ============================================================
class PinnedItemWindow(QDialog):
    """单条内容钉出小窗口"""
    _active_windows = []
    _keyboard = None
    
    # 预设颜色方案: (名称, 背景色rgba, 边框色rgba)
    COLOR_PRESETS = [
        ("🟢 薄荷绿", "rgba(220, 245, 225, 230)", "rgba(60, 179, 113, 0.7)"),
        ("🔵 天空蓝", "rgba(220, 240, 255, 230)", "rgba(70, 130, 180, 0.7)"),
        ("🟡 柠檬黄", "rgba(255, 250, 205, 230)", "rgba(218, 165, 32, 0.7)"),
        ("🟠 蜜桃橙", "rgba(255, 228, 196, 230)", "rgba(210, 105, 30, 0.7)"),
        ("🔴 樱花粉", "rgba(255, 220, 230, 230)", "rgba(220, 20, 60, 0.7)"),
        ("🟣 薰衣草", "rgba(230, 220, 245, 230)", "rgba(128, 0, 128, 0.7)"),
        ("⚪ 珍珠白", "rgba(245, 245, 245, 230)", "rgba(128, 128, 128, 0.7)"),
        ("⚫ 暗夜灰", "rgba(60, 60, 60, 230)", "rgba(100, 100, 100, 0.7)"),
    ]

    def __init__(self, content: str, parent=None):
        super().__init__(parent, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.content = content
        self._drag_pos = None
        self._is_pasting = False
        self._current_bg_color = self.COLOR_PRESETS[0][1]  # 默认第一个颜色
        self._current_border_color = self.COLOR_PRESETS[0][2]
        self._init_ui()
        self._apply_style()

        if PinnedItemWindow._keyboard is None:
            try:
                from pynput.keyboard import Controller
                PinnedItemWindow._keyboard = Controller()
            except Exception:
                pass

        PinnedItemWindow._active_windows.append(self)
        self.finished.connect(self._on_finished)
        self.destroyed.connect(self._on_destroyed)

    def _init_ui(self):
        self.setWindowTitle("钉出内容")
        self.setFixedSize(220, 100)

        # Create container for styled background
        self.container = QFrame(self)
        self.container.setObjectName("pinnedContainer")
        self.container.setGeometry(0, 0, 220, 100)
        
        # 启用右键菜单
        self.container.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.container.customContextMenuRequested.connect(self._show_context_menu)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.content_btn = QPushButton(self._truncate_content(self.content, 40))
        self.content_btn.setObjectName("contentBtn")
        self.content_btn.setFixedHeight(36)
        tooltip_text = "点击粘贴: " + self.content[:100]
        if len(self.content) > 100:
            tooltip_text += "..."
        self.content_btn.setToolTip(tooltip_text)
        self.content_btn.clicked.connect(self._on_paste)
        layout.addWidget(self.content_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        copy_btn = QPushButton("📋 复制")
        copy_btn.setObjectName("smallBtn")
        copy_btn.clicked.connect(self._on_copy)
        btn_layout.addWidget(copy_btn)
        btn_layout.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setObjectName("closeBtn")
        close_btn.setFixedSize(28, 28)
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        # Add container to dialog's main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.container)
    
    def _show_context_menu(self, position):
        """显示右键菜单 - 选择背景颜色"""
        menu = QMenu(self)
        menu.setStyleSheet(MENU_STYLE)
        
        # 添加标题
        title_action = menu.addAction("🎨 选择背景颜色")
        title_action.setEnabled(False)
        menu.addSeparator()
        
        # 添加颜色选项
        for name, bg_color, border_color in self.COLOR_PRESETS:
            action = menu.addAction(name)
            action.triggered.connect(lambda checked, b=bg_color, bd=border_color: self._set_color(b, bd))
        
        menu.exec(self.container.mapToGlobal(position))
    
    def _set_color(self, bg_color, border_color):
        """设置窗口背景颜色"""
        self._current_bg_color = bg_color
        self._current_border_color = border_color
        self._apply_style()

    def _apply_style(self):
        # 根据当前颜色动态生成样式
        self.setStyleSheet(f"""
            QDialog {{
                background: transparent;
                border: none;
            }}
            #pinnedContainer {{
                background-color: {self._current_bg_color};
                border: 2px solid {self._current_border_color};
                border-radius: 12px;
            }}
            #contentBtn {{
                background-color: rgba(255, 255, 255, 0.55);
                border: 1px solid rgba(120, 200, 140, 0.5);
                border-radius: 8px;
                padding: 0px 12px;
                color: #1a3a2a;
                font-size: 13px;
                text-align: center;
            }}
            #contentBtn:hover {{
                background-color: rgba(255, 255, 255, 0.75);
                border: 1px solid rgba(60, 179, 113, 0.7);
            }}
            #smallBtn {{
                background-color: rgba(255, 255, 255, 0.45);
                border: 1px solid rgba(120, 200, 140, 0.4);
                border-radius: 6px;
                padding: 4px 10px;
                color: #2d5a3d;
                font-size: 11px;
            }}
            #smallBtn:hover {{
                background-color: rgba(255, 255, 255, 0.65);
            }}
            #closeBtn {{
                background-color: rgba(220, 80, 80, 0.4);
                border: none;
                border-radius: 6px;
                color: #b03030;
                font-size: 12px;
                font-weight: bold;
            }}
            #closeBtn:hover {{
                background-color: rgba(220, 80, 80, 0.7);
                color: #ffffff;
            }}
        """)

    def _truncate_content(self, content: str, max_len: int) -> str:
        display = content.replace(chr(10), " ").replace(chr(13), "")
        if len(display) > max_len:
            return display[:max_len] + "..."
        return display

    def _on_paste(self):
        self.hide()
        QTimer.singleShot(TYPE_DELAY_MS, self._do_paste)

    def _do_paste(self):
        """RDP环境下粘贴：setText → 等200ms → hide → 等200ms → Ctrl+V"""
        if self._is_pasting:
            return
        
        def _do_ctrl_v():
            try:
                from pynput.keyboard import Controller, Key
                keyboard = Controller()
                keyboard.release(Key.alt)
                keyboard.release(Key.alt_l)
                keyboard.release(Key.alt_r)
                with keyboard.pressed(Key.ctrl):
                    keyboard.tap('v')
                QTimer.singleShot(300, lambda: globals().update({'_is_pasting': False}))
            except Exception as e:
                log_error(f"PinnedItem Ctrl+V 失败: {e}")
                globals()['_is_pasting'] = False
            self._is_pasting = False

        def _do_hide():
            self.hide()
            QTimer.singleShot(200, _do_ctrl_v)

        def _do_paste_inner():
            self._is_pasting = True
            globals()['_is_pasting'] = True
            QApplication.clipboard().setText(self.content)
            QTimer.singleShot(200, _do_hide)

        _do_paste_inner()

        # ================================================================
        # 备用方案: keyboard.write 逐字输入（不依赖剪贴板）
        # ================================================================
        # import keyboard
        # text = self.content.replace('\n', ' ').replace('\r', '')
        # keyboard.write(text, delay=0.01)
        # ================================================================

    def _on_copy(self):
        QApplication.clipboard().setText(self.content)
        self.content_btn.setText("✓ 已复制")
        QTimer.singleShot(1000, lambda: self.content_btn.setText(self._truncate_content(self.content, 40)))

    def _on_finished(self):
        self._remove_from_active()

    def _on_destroyed(self):
        self._remove_from_active()

    def _remove_from_active(self):
        try:
            if self in PinnedItemWindow._active_windows:
                PinnedItemWindow._active_windows.remove(self)
        except ValueError:
            pass

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def show_near_cursor(self):
        pos = QCursor.pos()
        screen = QApplication.primaryScreen().geometry()
        x = pos.x() + 15
        y = pos.y() + 15

        if x + self.width() > screen.right():
            x = screen.right() - self.width() - 10
        if y + self.height() > screen.bottom():
            y = screen.bottom() - self.height() - 10

        self.move(max(screen.left() + 10, x), max(screen.top() + 10, y))
        self.show()
        self.raise_()
        self.activateWindow()


# ============================================================
# 备忘录编辑窗口
# ============================================================
class MemoEditorWindow(QWidget):
    """独立的浮动备忘录编辑窗口，支持自动保存"""

    def __init__(self, storage: StorageManager, memo_id: int = None, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.memo_id = memo_id
        self._drag_pos = None
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.timeout.connect(self._auto_save)
        self.pinned = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.resize(400, 350)

        self._init_ui()
        self._apply_style()

        if memo_id:
            self._load_memo_data()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.container = QFrame()
        self.container.setObjectName("memoEditorContainer")
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # 标题栏
        tb = QHBoxLayout()
        tb.setSpacing(8)

        self.btn_pin = QPushButton("📌")
        self.btn_pin.setObjectName("memoEditorPinBtn")
        self.btn_pin.setFixedSize(32, 32)
        self.btn_pin.setToolTip("钉住窗口")
        self.btn_pin.clicked.connect(self._toggle_pin)
        tb.addWidget(self.btn_pin)

        title_label = QLabel("📝 新建备忘录" if not self.memo_id else "📝 编辑备忘录")
        title_label.setObjectName("memoEditorTitle")
        tb.addWidget(title_label)
        tb.addStretch()

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("memoEditorCloseBtn")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.clicked.connect(self.close)
        tb.addWidget(self.close_btn)

        layout.addLayout(tb)

        # 标题输入
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("标题（可选，不填将自动提取）")
        self.title_input.setObjectName("memoEditorTitleInput")
        self.title_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.title_input)

        # 内容输入
        self.content_input = QTextEdit()
        self.content_input.setPlaceholderText("输入备忘录内容...")
        self.content_input.setObjectName("memoEditorContentInput")
        self.content_input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.content_input)

        # 状态栏
        self.status_label = QLabel("")
        self.status_label.setObjectName("memoEditorStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        main_layout.addWidget(self.container)

    def _apply_style(self):
        self.setStyleSheet("""
            #memoEditorContainer {
                background-color: rgba(220, 245, 225, 230);
                border: 1px solid rgba(120, 200, 140, 0.5);
                border-radius: 16px;
            }
            #memoEditorTitle {
                color: #1a3a2a;
                font-size: 16px;
                font-weight: bold;
                background: transparent;
                border: none;
            }
            #memoEditorTitleInput {
                background-color: rgba(255, 255, 255, 0.55);
                border: 1px solid rgba(120, 200, 140, 0.5);
                border-radius: 8px;
                padding: 10px 12px;
                color: #1a3a2a;
                font-size: 13px;
            }
            #memoEditorTitleInput:focus {
                border: 1px solid rgba(60, 179, 113, 0.8);
            }
            #memoEditorContentInput {
                background-color: rgba(255, 255, 255, 0.55);
                border: 1px solid rgba(120, 200, 140, 0.5);
                border-radius: 8px;
                padding: 10px 12px;
                color: #1a3a2a;
                font-size: 13px;
            }
            #memoEditorContentInput:focus {
                border: 1px solid rgba(60, 179, 113, 0.8);
            }
            #memoEditorStatus {
                color: rgba(60, 140, 80, 0.7);
                font-size: 11px;
                background: transparent;
                border: none;
            }
            #memoEditorPinBtn {
                background-color: rgba(255, 255, 255, 0.45);
                border: 1px solid rgba(120, 200, 140, 0.4);
                border-radius: 8px;
                font-size: 16px;
            }
            #memoEditorPinBtn:hover {
                background-color: rgba(245, 180, 60, 0.6);
            }
            #memoEditorPinBtn[pinned="true"] {
                background-color: rgba(245, 180, 60, 0.75);
                border: 2px solid rgba(245, 180, 60, 1.0);
            }
            #memoEditorCloseBtn {
                background-color: rgba(220, 80, 80, 0.4);
                border: none;
                border-radius: 6px;
                color: #b03030;
                font-size: 14px;
                font-weight: bold;
            }
            #memoEditorCloseBtn:hover {
                background-color: rgba(220, 80, 80, 0.7);
                color: #ffffff;
            }
        """)

    def _load_memo_data(self):
        for m in self.storage.get_memos():
            if m['id'] == self.memo_id:
                self.title_input.setText(m['title'])
                self.content_input.setPlainText(m['content'])
                break

    def _on_text_changed(self):
        self._auto_save_timer.stop()
        self._auto_save_timer.start(3000)
        self.status_label.setText("编辑中...")

    def _auto_save(self):
        title = self.title_input.text().strip()
        content = self.content_input.toPlainText().strip()

        if not content:
            self.status_label.setText("")
            return

        if not title:
            title = content[:20] + "..." if len(content) > 20 else content

        if self.memo_id:
            self.storage.update_memo(self.memo_id, title, content)
        else:
            self.storage.add_memo(title, content)
            memos = self.storage.get_memos()
            if memos:
                self.memo_id = memos[0]['id']

        self.status_label.setText(f"已自动保存 ✓ {datetime.now().strftime('%H:%M:%S')}")

    def _toggle_pin(self):
        self.pinned = not self.pinned
        self.btn_pin.setProperty("pinned", self.pinned)
        self.btn_pin.setText("📍" if self.pinned else "📌")
        self.btn_pin.setToolTip("取消钉住" if self.pinned else "钉住窗口")
        self.btn_pin.style().unpolish(self.btn_pin)
        self.btn_pin.style().polish(self.btn_pin)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def show_at_cursor(self):
        pos = QCursor.pos()
        screen = QApplication.primaryScreen().geometry()
        x = max(screen.left() + 10, min(pos.x() - self.width() // 2, screen.right() - self.width() - 10))
        y = max(screen.top() + 10, min(pos.y() - 20, screen.bottom() - self.height() - 10))
        self.move(x, y)
        self.show()
        self.raise_()
        # 延迟激活窗口，确保 Alt 键已释放，避免键盘事件被错误传递
        QTimer.singleShot(100, self.activateWindow)


# ============================================================
# 备忘录对话框
# ============================================================
class MemoDialog(QDialog):
    """备忘录编辑对话框"""

    def __init__(self, storage: StorageManager, memo_id: int = None, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.memo_id = memo_id
        self._init_ui()
        self._apply_style()

        if memo_id:
            for m in storage.get_memos():
                if m['id'] == memo_id:
                    self.title_input.setText(m['title'])
                    self.content_input.setPlainText(m['content'])
                    break
            self.setWindowTitle("编辑备忘录")
        else:
            self.setWindowTitle("新建备忘录")

    def _init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(400, 350)

        container = QFrame()
        container.setObjectName("memoContainer")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title_label = QLabel("📝 备忘录")
        title_label.setObjectName("memoTitle")
        layout.addWidget(title_label)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("标题")
        self.title_input.setObjectName("memoTitleInput")
        layout.addWidget(self.title_input)

        self.content_input = QTextEdit()
        self.content_input.setPlaceholderText("内容...")
        self.content_input.setObjectName("memoContentInput")
        layout.addWidget(self.content_input)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("memoCancelBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        save_btn = QPushButton("保存")
        save_btn.setObjectName("memoSaveBtn")
        save_btn.clicked.connect(self._save)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(container)

    def _apply_style(self):
        self.setStyleSheet("""
            #memoContainer { background-color: rgba(220, 245, 225, 235); border: 1px solid rgba(120, 200, 140, 0.5); border-radius: 16px; }
            #memoTitle { color: #1a3a2a; font-size: 16px; font-weight: bold; background: transparent; border: none; }
            #memoTitleInput { background-color: rgba(255, 255, 255, 0.55); border: 1px solid rgba(120, 200, 140, 0.5); border-radius: 8px; padding: 8px 12px; color: #1a3a2a; font-size: 13px; }
            #memoContentInput { background-color: rgba(255, 255, 255, 0.55); border: 1px solid rgba(120, 200, 140, 0.5); border-radius: 8px; padding: 8px 12px; color: #1a3a2a; font-size: 13px; }
            #memoCancelBtn { background-color: rgba(255, 255, 255, 0.45); border: 1px solid rgba(120, 200, 140, 0.4); border-radius: 8px; padding: 8px 20px; color: #2d5a3d; }
            #memoCancelBtn:hover { background-color: rgba(255, 255, 255, 0.65); color: #1a3a2a; }
            #memoSaveBtn { background-color: rgba(60, 179, 113, 0.6); border: 1px solid rgba(60, 179, 113, 0.9); border-radius: 8px; padding: 8px 20px; color: #ffffff; font-weight: bold; }
            #memoSaveBtn:hover { background-color: rgba(60, 179, 113, 0.8); }
        """)

    def _save(self):
        title = self.title_input.text().strip()
        content = self.content_input.toPlainText().strip()
        if not title:
            self.title_input.setFocus()
            return
        if not content:
            self.content_input.setFocus()
            return
        if self.memo_id:
            self.storage.update_memo(self.memo_id, title, content)
        else:
            self.storage.add_memo(title, content)
        self.accept()


# ============================================================
# 右键菜单
# ============================================================
class TimePickerDialog(QDialog):
    """选择当天提醒时间的对话框"""

    def __init__(self, current_time: str = None, parent=None):
        super().__init__(parent)
        self.selected_time = current_time  # None 表示取消提醒
        self._init_ui(current_time)
        self.setWindowTitle("设置提醒时间")
        self.setFixedSize(280, 180)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def _init_ui(self, current_time: str):
        # 容器
        container = QFrame(self)
        container.setObjectName("pickerContainer")
        container.setStyleSheet("""
            #pickerContainer {
                background-color: rgba(230, 248, 235, 240);
                border: 1px solid rgba(120, 200, 140, 0.5);
                border-radius: 12px;
            }
            QLabel { color: #1a3a2a; background: transparent; border: none; }
            QPushButton {
                background-color: rgba(60, 179, 113, 120);
                color: white; border: none; border-radius: 6px;
                padding: 8px 16px; font-size: 13px;
            }
            QPushButton:hover { background-color: rgba(60, 179, 113, 180); }
            QPushButton#btnCancel {
                background-color: rgba(180, 180, 180, 120);
            }
            QPushButton#btnCancel:hover { background-color: rgba(180, 180, 180, 180); }
        """)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # 提示标签
        hint = QLabel("选择今天的提醒时间")
        hint.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(hint)

        # 时间选择器
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setTimeRange(QTime(0, 0, 0), QTime(23, 59, 0))
        if current_time:
            parts = current_time.split(":")
            self.time_edit.setTime(QTime(int(parts[0]), int(parts[1])))
        else:
            # 默认时间为 17:00
            self.time_edit.setTime(QTime(17, 0))
        self.time_edit.setStyleSheet("""
            QTimeEdit {
                background-color: rgba(255, 255, 255, 200);
                border: 1px solid rgba(120, 200, 140, 0.5);
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 18px;
                color: #1a3a2a;
            }
        """)
        layout.addWidget(self.time_edit)

        # 按钮行
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_cancel = QPushButton("取消提醒")
        btn_cancel.setObjectName("btnCancel")
        btn_cancel.clicked.connect(self._cancel_reminder)
        btn_layout.addWidget(btn_cancel)

        btn_ok = QPushButton("确定")
        btn_ok.clicked.connect(self._confirm_time)
        btn_layout.addWidget(btn_ok)

        layout.addLayout(btn_layout)

        # 对话框主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(container)

    def _confirm_time(self):
        time = self.time_edit.time()
        self.selected_time = time.toString("HH:mm")
        self.accept()

    def _cancel_reminder(self):
        self.selected_time = None
        self.accept()


class ListContextMenu(QMenu):
    """列表项右键上下文菜单"""

    # 预设颜色方案: (名称, 背景色)
    COLOR_PRESETS = [
        ("🚫 无颜色", ""),
        ("🟢 薄荷绿", "rgba(200, 240, 210, 200)"),
        ("🔵 天空蓝", "rgba(200, 230, 255, 200)"),
        ("🟡 柠檬黄", "rgba(255, 248, 190, 200)"),
        ("🟠 蜜桃橙", "rgba(255, 225, 190, 200)"),
        ("🔴 樱花粉", "rgba(255, 215, 225, 200)"),
        ("🟣 薰衣草", "rgba(225, 215, 245, 200)"),
    ]

    def __init__(self, storage: StorageManager, list_widget, floating_window, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.floating_window = floating_window
        self._pinned_windows = []
        self.setStyleSheet(MENU_STYLE)

    def show_menu(self, pos, item: QListWidgetItem):
        self.clear()
        content = item.data(Qt.ItemDataRole.UserRole)
        item_type = item.data(Qt.ItemDataRole.UserRole + 2)
        item_id = item.data(Qt.ItemDataRole.UserRole + 1)

        self.addAction("⌨️ 模拟输入到光标").triggered.connect(lambda: paste_content(self.floating_window, content))
        self.addAction("📋 复制到剪贴板").triggered.connect(lambda: QApplication.clipboard().setText(content))
        self.addAction("📌 钉出到小窗口").triggered.connect(lambda: self._pin_item(content))

        # 颜色子菜单
        color_menu = self.addMenu("🎨 设置颜色")
        for name, color in self.COLOR_PRESETS:
            action = color_menu.addAction(name)
            action.triggered.connect(lambda checked, c=color, it=item, t=item_type, i=item_id: self._set_item_color(c, it, t, i))

        if item_type == "clipboard":
            if self.storage.is_favorite(content):
                self.addAction("💔 取消收藏").triggered.connect(lambda: self._remove_favorite(content))
            else:
                self.addAction("⭐ 添加收藏").triggered.connect(lambda: self._add_favorite(content))
            self.addAction("🗑️ 删除").triggered.connect(lambda: self._delete_history_item(item_id))
        elif item_type == "favorite":
            self.addAction("💔 取消收藏").triggered.connect(lambda: self._remove_favorite_by_id(item_id))
        elif item_type == "memo":
            self.addAction("⏰ 设置提醒").triggered.connect(lambda: self._set_reminder(item_id))
            self.addAction("✏️ 编辑").triggered.connect(lambda: self._edit_memo(item_id))
            self.addAction("🗑️ 删除").triggered.connect(lambda: self._remove_memo(item_id))

        self.exec_(pos)

    def _set_item_color(self, color: str, item: QListWidgetItem, item_type: str, item_id: int):
        """设置条目背景颜色"""
        # 保存到数据库
        self.storage.set_item_color(item_type, item_id, color)
        # 更新当前显示
        self.floating_window.refresh()

    def _add_favorite(self, content: str):
        self.storage.add_favorite(content)
        self.floating_window.refresh()

    def _remove_favorite(self, content: str):
        self.storage.remove_favorite(content=content)
        self.floating_window.refresh()

    def _remove_favorite_by_id(self, fav_id: int):
        self.storage.remove_favorite(fav_id=fav_id)
        self.floating_window.refresh()

    def _delete_history_item(self, item_id: int):
        self.storage.delete_history_item(item_id)
        self.floating_window.refresh()

    def _remove_memo(self, memo_id: int):
        self.storage.remove_memo(memo_id)
        self.floating_window.refresh()

    def _pin_item(self, content: str):
        win = PinnedItemWindow(content)
        self._pinned_windows.append(win)
        self.floating_window.hide()
        win.show_near_cursor()

    def _set_reminder(self, memo_id: int):
        """打开时间选择对话框设置提醒"""
        memos = self.storage._query(
            "SELECT remind_time FROM memos WHERE id=?", (memo_id,), fetch=True
        )
        current_time = memos[0].get('remind_time') if memos else None

        dialog = TimePickerDialog(current_time, parent=self.floating_window)
        result = dialog.exec_()

        if result == QDialog.DialogCode.Accepted:
            self.storage.set_remind_time(memo_id, dialog.selected_time)
            self.floating_window.refresh()

    def _edit_memo(self, memo_id: int):
        dialog = MemoDialog(self.storage, memo_id=memo_id, parent=self.floating_window)
        if dialog.exec_() == QDialog.DialogCode.Accepted:
            self.floating_window.refresh()


# ============================================================
# 开机自启动管理
# ============================================================
class AutoStartManager:
    """Windows 开机自启动快捷方式管理"""

    @staticmethod
    def _path() -> str:
        return os.path.join(os.environ.get('APPDATA', ''),
                            r'Microsoft\Windows\Start Menu\Programs\Startup', "SmartClipboard.lnk")

    @staticmethod
    def is_enabled() -> bool:
        return os.path.exists(AutoStartManager._path())

    @staticmethod
    def enable(exe_path: str) -> bool:
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortCut(AutoStartManager._path())
            shortcut.Targetpath = exe_path
            shortcut.WorkingDirectory = os.path.dirname(exe_path)
            shortcut.WindowStyle = 7
            shortcut.save()
            return True
        except ImportError:
            try:
                import subprocess
                subprocess.run(['powershell', '-Command',
                    f'$ws = New-Object -ComObject WScript.Shell; '
                    f'$s = $ws.CreateShortcut("{AutoStartManager._path()}"); '
                    f'$s.TargetPath = "{exe_path}"; '
                    f'$s.WorkingDirectory = "{os.path.dirname(exe_path)}"; '
                    f'$s.WindowStyle = 7; $s.Save()'],
                    capture_output=True, check=True)
                return True
            except Exception as e:
                print(f"创建启动快捷方式失败: {e}")
                return False

    @staticmethod
    def disable() -> bool:
        if os.path.exists(AutoStartManager._path()):
            os.remove(AutoStartManager._path())
            return True
        return False


# ============================================================
# 主应用
# ============================================================
class SmartClipboardApp:
    """智能剪切板应用主类"""

    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self.storage = StorageManager()
        self.floating_window = FloatingWindow(self.storage)

        self.context_menu = ListContextMenu(self.storage, self.floating_window.list_widget, self.floating_window)
        self.floating_window.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.floating_window.list_widget.customContextMenuRequested.connect(self._show_context_menu)

        self.clipboard_monitor = ClipboardMonitor(self.storage)
        self.clipboard_monitor.new_clip.connect(self._on_new_clip)
        self.clipboard_monitor.start()

        self._setup_tray()
        self._setup_hotkey()
        self._setup_reminder_timer()

    def _setup_tray(self):
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor("#3cb371")))
        painter.setPen(QPen(QColor("#3cb371"), 2))
        painter.drawRoundedRect(4, 2, 24, 28, 4, 4)
        painter.setBrush(QBrush(QColor("#d4f5dc")))
        painter.drawRoundedRect(8, 6, 16, 20, 2, 2)
        painter.setPen(QPen(QColor("#3cb371"), 1.5))
        for y in [11, 15, 19]:
            painter.drawLine(10, y, 22, y)
        painter.end()

        self.tray_icon = QSystemTrayIcon(QIcon(pixmap), self.app)
        self.tray_icon.setToolTip("智能剪切板 - Alt+Q 调出")

        tray_menu = QMenu()
        tray_menu.setStyleSheet(MENU_STYLE)
        tray_menu.addAction("📋 显示剪切板").triggered.connect(self.floating_window.show_at_cursor)
        tray_menu.addSeparator()
        self.autostart_action = QAction("🚀 开机自启动", tray_menu)
        self.autostart_action.setCheckable(True)
        self.autostart_action.setChecked(AutoStartManager.is_enabled())
        self.autostart_action.triggered.connect(self._toggle_autostart)
        tray_menu.addAction(self.autostart_action)
        tray_menu.addSeparator()
        tray_menu.addAction("❌ 退出").triggered.connect(self._quit)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(lambda r: self.floating_window.show_at_cursor() if r == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray_icon.show()

    def _setup_hotkey(self):
        self.hotkey_listener = HotkeyListener(self._toggle_window, self._open_favorites)
        if not self.hotkey_listener.start():
            print("快捷键注册失败，请检查 pynput 是否正确安装")

    def _toggle_window(self):
        fw = self.floating_window
        if fw.isVisible():
            if fw.current_mode == "clipboard":
                fw.hide()
            else:
                fw._switch_mode("clipboard")
        else:
            fw._switch_mode("clipboard")
            fw.show_at_cursor()

    def _open_favorites(self):
        fw = self.floating_window
        if fw.isVisible():
            if fw.current_mode == "favorites":
                fw.hide()
            else:
                fw._switch_mode("favorites")
        else:
            fw._switch_mode("favorites")
            fw.show_at_cursor()

    def _show_context_menu(self, pos):
        item = self.floating_window.list_widget.itemAt(pos)
        if item:
            self.context_menu.show_menu(self.floating_window.list_widget.mapToGlobal(pos), item)

    def _on_new_clip(self, content: str):
        if self.floating_window.current_mode == "clipboard":
            self.floating_window.refresh()

    def _toggle_autostart(self, checked: bool):
        if checked:
            exe_path = os.path.abspath(sys.argv[0])
            if exe_path.endswith('.py'):
                exe_path = os.path.join(os.path.dirname(exe_path), "SmartClipboard.exe")
            if not AutoStartManager.enable(exe_path):
                self.autostart_action.setChecked(False)
                QMessageBox.warning(None, "提示", "设置开机自启动失败，打包为exe后重试")
        else:
            AutoStartManager.disable()

    def _setup_reminder_timer(self):
        """设置提醒检查定时器，每30秒检查一次"""
        self._reminder_timer = QTimer(self.app)
        self._reminder_timer.timeout.connect(self._check_reminders)
        self._reminder_timer.start(30000)
        self._notified_reminders: set = set()

    def _check_reminders(self):
        """检查是否有需要提醒的备忘录"""
        try:
            reminders = self.storage.get_pending_reminders()
            now_str = datetime.now().strftime("%H:%M")
            for r in reminders:
                rid = r['id']
                if rid in self._notified_reminders:
                    continue
                if r.get('remind_time') == now_str:
                    self._notified_reminders.add(rid)
                    self.tray_icon.showMessage(
                        "备忘录提醒",
                        f"⏰ {r['title']}",
                        QIcon(),
                        5000
                    )
            # 每天零点重置已通知集合
            if now_str == "00:00":
                self._notified_reminders.clear()
        except Exception as e:
            print(f"提醒检查异常: {e}")

    def _quit(self):
        if self.clipboard_monitor.isRunning():
            self.clipboard_monitor.stop()
        if hasattr(self, 'hotkey_listener'):
            self.hotkey_listener.stop()
        self.tray_icon.hide()
        self.app.quit()

    def run(self):
        sys.exit(self.app.exec_())


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    sys.excepthook = exception_hook

    single = SingleInstance()
    if not single.acquire():
        print("已有实例在运行，退出...")
        sys.exit(0)

    try:
        SmartClipboardApp().run()
    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        print(f"程序异常退出:\n{error_msg}")
        log_error(error_msg)
    finally:
        single.release()
