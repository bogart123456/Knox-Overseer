from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QLockFile
import sys
import os
import ctypes
import tempfile
from ui.main_window import MainWindow


def _apply_windows_chrome_theme(window):
    if sys.platform != "win32":
        return

    try:
        dwmapi = ctypes.windll.dwmapi
        hwnd = int(window.winId())
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20

        dark_mode = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode))
    except Exception:
        # Ignore unsupported Windows versions.
        pass


def _resource_path(*parts):
    if getattr(sys, "frozen", False):
        base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    else:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, *parts)


def _create_single_instance_lock():
    mutex_handle = None
    kernel32 = None
    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool

        mutex_handle = kernel32.CreateMutexW(None, False, "Local\\KnoxOverseerAppMutex")
        if not mutex_handle:
            return None
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(mutex_handle)
            return None

    lock_path = os.path.join(tempfile.gettempdir(), "knox_overseer.lock")
    lock = QLockFile(lock_path)
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        if mutex_handle is not None and kernel32 is not None:
            kernel32.CloseHandle(mutex_handle)
        return None
    return {
        "lock": lock,
        "mutex": mutex_handle,
    }

# -----------------------------
# Main Application
# -----------------------------
def main():
    app = QApplication(sys.argv)

    single_instance_lock = _create_single_instance_lock()
    if single_instance_lock is None:
        QMessageBox.warning(None, "Knox Overseer", "Knox Overseer is already running.")
        return
    app._single_instance_lock = single_instance_lock

    app_icon_path = _resource_path("assets", "icons", "icon.png")
    if os.path.isfile(app_icon_path):
        app.setWindowIcon(QIcon(app_icon_path))
    app.setStyle("Fusion")
    app.setStyleSheet("""
        QWidget {
            background-color: #181818;
            color: #f0f0f0;
            font-family: Corbel;
            font-size: 10.5pt;
            selection-background-color: #ff8500;
            selection-color: #ffffff;
        }

        QMainWindow, QDialog {
            background-color: #111214;
            border: 1px solid #2a2a2a;
        }

        QFrame {
            background-color: transparent;
        }

        QStatusBar {
            background-color: #111214;
            color: #c8c8c8;
            border-top: 1px solid #2a2a2a;
        }

        QTableWidget {
            background-color: #131313;
            alternate-background-color: #181818;
            color: #f0f0f0;
            gridline-color: #2a2a2a;
            border: 1px solid #2a2a2a;
            border-radius: 4px;
        }

        QHeaderView::section {
            background-color: #1c1c1c;
            color: #f0f0f0;
            border: 1px solid #2a2a2a;
            padding: 5px;
            font-weight: bold;
        }

        QPushButton {
            background-color: #24272b;
            color: #f0f0f0;
            border: 1px solid #383c42;
            border-radius: 4px;
            padding: 6px 10px;
            font-weight: 600;
        }

        QPushButton:hover {
            background-color: #2e3237;
            border-color: #4b5058;
        }

        QPushButton:pressed {
            background-color: #1d2024;
            border-color: #383c42;
            padding-top: 7px;
            padding-bottom: 5px;
        }

        QPushButton:disabled {
            background-color: #16181b;
            color: #8a8d91;
            border-color: #2e3136;
        }

        QPushButton[modToggle="true"] {
            background: #111111;
            color: #36d977;
            border: 1px solid #383c42;
            border-radius: 0;
            padding: 0;
            font-size: 12pt;
            font-weight: 700;
        }

        QPushButton[modToggle="true"]:hover {
            border-color: #ff9d33;
            background: #191c20;
        }

        QPushButton[modToggle="true"]:checked {
            background: #172019;
            color: #4ee78c;
            border: 1px solid #59b383;
        }

        QPushButton[modToggle="true"]:pressed {
            padding: 0;
            background: #0f1113;
        }

        QPushButton[modToggle="true"]:disabled {
            background: #141516;
            color: #4d6a5a;
            border-color: #2a2a2a;
        }

        QLineEdit, QTextEdit {
            background-color: #121212;
            color: #f0f0f0;
            border: 1px solid #2a2a2a;
            border-radius: 4px;
            padding: 4px;
        }

        QPlainTextEdit {
            background-color: #121212;
            color: #f0f0f0;
            border: 1px solid #2a2a2a;
            border-radius: 4px;
        }

        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
            border: 1px solid #ff8500;
        }

        QComboBox, QSpinBox {
            background-color: #121212;
            color: #f0f0f0;
            border: 1px solid #2a2a2a;
            border-radius: 4px;
            padding: 4px;
        }

        QToolTip {
            background-color: #1b1b1b;
            color: #f0f0f0;
            border: 1px solid #353535;
        }

        QGroupBox {
            color: #f0f0f0;
            border: 1px solid #2a2a2a;
            border-radius: 5px;
            margin-top: 10px;
            padding-top: 12px;
            font-weight: 600;
        }

        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
            color: #cccccc;
        }

        QCheckBox {
            color: #f0f0f0;
            spacing: 8px;
            background: transparent;
            padding: 0;
            margin: 0;
        }

        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border-radius: 3px;
            border: 1px solid #6c6c6c;
            background: #121212;
            margin: 0;
            padding: 0;
        }

        QCheckBox::indicator:checked {
            background: #ff8500;
            border: 2px solid #ffb066;
        }

        QCheckBox::indicator:unchecked:hover,
        QCheckBox::indicator:checked:hover {
            border-color: #ffc27f;
        }

        QCheckBox::indicator:disabled {
            background: #1a1c1f;
            border-color: #353535;
        }

        QLabel {
            color: #f0f0f0;
        }

        QTabWidget::pane {
            border: 1px solid #2a2a2a;
            background: #111214;
            top: -1px;
        }

        QTabBar::tab {
            background-color: #1a1a1d;
            color: #d0d0d0;
            border: 1px solid #2a2a2a;
            border-bottom: none;
            min-width: 90px;
            padding: 7px 10px;
            margin-right: 1px;
        }

        QTabBar::tab:selected {
            background-color: #0f0f10;
            color: #ffffff;
            border-color: #ff8500;
        }

        QTabBar::tab:hover:!selected {
            background-color: #24282d;
        }

        QScrollBar:vertical {
            background: #111214;
            width: 12px;
            margin: 2px;
            border: 1px solid #2a2a2a;
            border-radius: 5px;
        }

        QScrollBar::handle:vertical {
            background: #2e3237;
            min-height: 24px;
            border-radius: 4px;
            border: 1px solid #4b5058;
        }

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
            background: none;
            border: none;
        }

        QProgressBar {
            border: 1px solid #2a2a2a;
            border-radius: 4px;
            background-color: #121212;
            text-align: center;
            color: #f0f0f0;
        }

        QProgressBar::chunk {
            background-color: #ff8500;
        }

        QMenu {
            background-color: #1a1a1d;
            color: #f0f0f0;
            border: 1px solid #2a2a2a;
        }

        QMenu::item:selected {
            background-color: #ff8500;
        }
    """)

    window = MainWindow()
    if os.path.isfile(app_icon_path):
        window.setWindowIcon(QIcon(app_icon_path))

    # -----------------------------
    # Show the window
    # -----------------------------
    window.show()
    _apply_windows_chrome_theme(window)
    sys.exit(app.exec())

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass