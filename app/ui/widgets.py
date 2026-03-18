from PySide6.QtWidgets import QPushButton, QComboBox, QSpinBox, QDoubleSpinBox, QListView


class CheckMarkBox(QPushButton):
    def __init__(self, checked=False):
        super().__init__()
        self.setCheckable(True)
        self.setProperty("modToggle", True)
        self.setFixedSize(18, 18)
        self.toggled.connect(self._sync_appearance)
        self.setChecked(checked)

    def _sync_appearance(self, checked):
        self.setText("✓" if checked else "")


class NoWheelComboBox(QComboBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setView(QListView())  # Qt-rendered popup so QSS hover rules apply

    def wheelEvent(self, event):
        event.ignore()


class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()