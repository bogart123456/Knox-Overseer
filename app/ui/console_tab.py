from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QTextEdit, QHBoxLayout, QLineEdit, QPushButton, QTreeWidget, QTreeWidgetItem
from PySide6.QtCore import Signal, Qt

class ConsoleTab(QWidget):
    input_sent = Signal(str)
    rcon_command = Signal(str)
    log_selected = Signal(str)

    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        sub_tab = QTabWidget()

        # Terminal tab
        terminal_widget = QWidget()
        terminal_layout = QVBoxLayout(terminal_widget)
        self.terminal_output = QTextEdit()
        self.terminal_output.setReadOnly(True)
        terminal_layout.addWidget(self.terminal_output)
        input_layout = QHBoxLayout()
        self.input_line = QLineEdit()
        self.input_line.returnPressed.connect(self.send_input)
        input_layout.addWidget(self.input_line)
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_input)
        input_layout.addWidget(self.send_button)
        terminal_layout.addLayout(input_layout)
        sub_tab.addTab(terminal_widget, "Terminal")

        # RCON tab
        self.rcon_widget = QWidget()
        rcon_layout = QVBoxLayout(self.rcon_widget)
        self.rcon_output = QTextEdit()
        self.rcon_output.setReadOnly(True)
        rcon_layout.addWidget(self.rcon_output)
        rcon_input_layout = QHBoxLayout()
        self.rcon_input = QLineEdit()
        self.rcon_input.returnPressed.connect(self.send_rcon)
        rcon_input_layout.addWidget(self.rcon_input)
        self.rcon_send = QPushButton("Send")
        self.rcon_send.clicked.connect(self.send_rcon)
        rcon_input_layout.addWidget(self.rcon_send)
        rcon_layout.addLayout(rcon_input_layout)
        sub_tab.addTab(self.rcon_widget, "RCON")

        # Logs tab
        logs_widget = QWidget()
        logs_layout = QHBoxLayout(logs_widget)
        self.log_tree = QTreeWidget()
        self.log_tree.setHeaderHidden(True)
        self.log_tree.itemClicked.connect(self.on_log_selected)
        logs_layout.addWidget(self.log_tree)
        self.log_content = QTextEdit()
        self.log_content.setReadOnly(True)
        logs_layout.addWidget(self.log_content)
        sub_tab.addTab(logs_widget, "Logs")

        layout.addWidget(sub_tab)

        # Start disabled until the server process is active.
        self.set_rcon_enabled(False)

    def send_input(self):
        text = self.input_line.text()
        if text:
            self.input_sent.emit(text)
            self.input_line.clear()

    def send_rcon(self):
        text = self.rcon_input.text()
        if text:
            self.rcon_command.emit(text)
            self.rcon_input.clear()

    def set_rcon_enabled(self, enabled):
        self.rcon_widget.setEnabled(enabled)

    def set_log_groups(self, current_logs, folder_logs):
        """Populate logs tree with root logs first and folder logs under collapsed nodes."""
        self.log_tree.clear()

        for display_name, abs_path in current_logs:
            item = QTreeWidgetItem([display_name])
            item.setData(0, Qt.UserRole, abs_path)
            self.log_tree.addTopLevelItem(item)

        for folder_name in sorted(folder_logs.keys()):
            children = folder_logs[folder_name]
            parent = QTreeWidgetItem([folder_name])
            parent.setData(0, Qt.UserRole, None)
            self.log_tree.addTopLevelItem(parent)
            for child_display, abs_path in children:
                child = QTreeWidgetItem([child_display])
                child.setData(0, Qt.UserRole, abs_path)
                parent.addChild(child)
            parent.setExpanded(False)

    def on_log_selected(self, item, _column):
        if item is None:
            return
        path = item.data(0, Qt.UserRole)
        if path:
            self.log_selected.emit(path)