from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QInputDialog, QMessageBox, QHeaderView, QAbstractItemView, QLineEdit
from PySide6.QtCore import Qt, Signal
from datetime import datetime
import requests
import re
import sys
from .widgets import CheckMarkBox

MANDATORY_WORKSHOP_ID = "3686757561"
MANDATORY_MOD_ID = "KnoxOverseer"
STEAM_API_TIMEOUT_SECONDS = 8

class ModsTab(QWidget):
    refresh_requested = Signal()

    def __init__(self, settings_tab):
        super().__init__()
        self.settings_tab = settings_tab
        self.mod_data_list = []  # Store mod data for each row
        self.enabled_checkboxes = []  # Store checkboxes for enabled state
        self._mod_details_cache = {}
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Search/filter controls
        search_layout = QHBoxLayout()
        search_label = QLabel("Search:")
        search_layout.addWidget(search_label)
        self.search_input = self._build_search_input()
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # Main layout with table and info box
        main_layout = QHBoxLayout()
        self.mods_table = QTableWidget()
        self.mods_table.setColumnCount(5)
        self.mods_table.setHorizontalHeaderLabels(["Name", "Mod ID", "Workshop ID", "Updated", " "])
        self.mods_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)  # Name
        self.mods_table.setColumnWidth(0, 200)
        self.mods_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)  # Mod ID
        self.mods_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Workshop ID
        self.mods_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Update
        self.mods_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)  # Enabled
        self.mods_table.setColumnWidth(4, 30)  # Small fixed width for enabled checkbox
        self.mods_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.mods_table.setSelectionMode(QAbstractItemView.SingleSelection)
        main_layout.addWidget(self.mods_table)

        # Mod info box
        info_box = QGroupBox("Workshop Info")
        info_layout = QVBoxLayout(info_box)
        self.mod_title_label = QLabel("Title:")
        info_layout.addWidget(self.mod_title_label)
        self.mod_updated_label = QLabel("Last Updated:")
        info_layout.addWidget(self.mod_updated_label)
        self.mod_author_label = QLabel("Author:")
        info_layout.addWidget(self.mod_author_label)
        self.mod_description = QTextEdit()
        self.mod_description.setReadOnly(True)
        info_layout.addWidget(self.mod_description)
        main_layout.addWidget(info_box)

        layout.addLayout(main_layout)

        # Buttons
        buttons_layout = QHBoxLayout()
        self.add_mod_button = QPushButton("Add Mod")
        self.add_mod_button.clicked.connect(self.add_mod)
        buttons_layout.addWidget(self.add_mod_button)
        self.remove_mod_button = QPushButton("Remove Mod")
        self.remove_mod_button.clicked.connect(self.remove_mod)
        buttons_layout.addWidget(self.remove_mod_button)
        self.move_up_button = QPushButton("Move Up")
        self.move_up_button.clicked.connect(self.move_up)
        buttons_layout.addWidget(self.move_up_button)
        self.move_down_button = QPushButton("Move Down")
        self.move_down_button.clicked.connect(self.move_down)
        buttons_layout.addWidget(self.move_down_button)
        self.refresh_mods_button = QPushButton("Refresh Mods")
        self.refresh_mods_button.clicked.connect(self.refresh_requested.emit)
        buttons_layout.addWidget(self.refresh_mods_button)
        self.save_config_button = QPushButton("Save Config")
        self.save_config_button.clicked.connect(self.save_config)
        buttons_layout.addWidget(self.save_config_button)
        layout.addLayout(buttons_layout)

        self.mods_table.itemSelectionChanged.connect(self.update_selected_mod_info)

    def _build_search_input(self):
        search_input = QLineEdit()
        search_input.setPlaceholderText("Filter by name, mod ID, or workshop ID")
        search_input.textChanged.connect(self._apply_search_filter)
        return search_input

    def _row_matches_search(self, row, query):
        if not query:
            return True

        query = query.lower()
        for col in (0, 1, 2):
            item = self.mods_table.item(row, col)
            if item and query in item.text().lower():
                return True
        return False

    def _select_first_visible_row(self):
        for row in range(self.mods_table.rowCount()):
            if not self.mods_table.isRowHidden(row):
                self.mods_table.setCurrentCell(row, 0)
                return
        self.mods_table.clearSelection()
        self.mod_title_label.setText("Title:")
        self.mod_updated_label.setText("Last Updated:")
        self.mod_author_label.setText("Author:")
        self.mod_description.clear()

    def _apply_search_filter(self, query):
        query = (query or "").strip()
        current_row = self.mods_table.currentRow()
        for row in range(self.mods_table.rowCount()):
            self.mods_table.setRowHidden(row, not self._row_matches_search(row, query))

        if current_row < 0 or self.mods_table.isRowHidden(current_row):
            self._select_first_visible_row()

    def set_mod_actions_enabled(self, enabled):
        self.add_mod_button.setEnabled(enabled)
        self.remove_mod_button.setEnabled(enabled)
        self.move_up_button.setEnabled(enabled)
        self.move_down_button.setEnabled(enabled)

    def _is_mandatory_mod_enforced(self):
        # Linux servers should be able to disable KnoxOverseer while troubleshooting.
        return not sys.platform.startswith("linux")

    def load_mods(self, ini_path=None):
        if ini_path:
            self.settings_tab.ini_path.setText(ini_path)
        ini_path = self.settings_tab.ini_path.text()
        if not ini_path:
            return
        try:
            with open(ini_path, 'r', encoding='utf-8') as f:
                content = f.read()
            # Find WorkshopItems and Mods lines
            workshop_ids = []
            mods_list = []
            enabled_mods = set()
            for line in content.splitlines():
                if line.startswith("WorkshopItems="):
                    workshop_items = line.split("=", 1)[1]
                    workshop_ids = workshop_items.split(";") if workshop_items else []
                elif line.startswith("Mods="):
                    mods_str = line.split("=", 1)[1]
                    mods_list = [mod_id.strip() for mod_id in mods_str.split(";") if mod_id.strip()] if mods_str else []
                    enabled_mods = set(mods_list)

            self.populate_mods_table(workshop_ids, enabled_mods, mods_list)
        except FileNotFoundError:
            return
        except Exception:
            return

    def refresh_mods(self, workshop_ids=None):
        # Collect unique Workshop IDs and their row indices
        wid_to_rows = {}
        for row in range(self.mods_table.rowCount()):
            workshop_id_item = self.mods_table.item(row, 2)
            if workshop_id_item:
                workshop_id = workshop_id_item.text()
                if workshop_id:
                    if workshop_ids is not None and workshop_id not in workshop_ids:
                        continue
                    if workshop_id not in wid_to_rows:
                        wid_to_rows[workshop_id] = []
                    wid_to_rows[workshop_id].append(row)
        # Fetch and update for each unique Workshop ID
        for workshop_id, rows in wid_to_rows.items():
            mod_data = self.fetch_mod_details(workshop_id, use_cache=False)
            if mod_data:
                for row in rows:
                    self.mod_data_list[row] = mod_data
                    self.mods_table.setItem(row, 0, QTableWidgetItem(mod_data.get('title', 'Unknown')))
                    self.mods_table.setItem(row, 3, QTableWidgetItem(self.format_update_time(mod_data.get('time_updated', 0))))
                    # Mod ID is already set per row, no need to change
                # Update info box if one of the rows is selected
                current_row = self.mods_table.currentRow()
                if current_row in rows:
                    self.update_workshop_info(mod_data)

    def format_update_time(self, unix_timestamp):
        if not unix_timestamp:
            return "Unknown"
        updated_time = datetime.fromtimestamp(int(unix_timestamp))
        return updated_time.strftime('%Y-%m-%d %H:%M:%S')

    def mark_updated_workshop_ids(self, updated_workshop_ids, details_by_workshop=None):
        if details_by_workshop is None:
            details_by_workshop = {}

        updated_set = {str(wid) for wid in updated_workshop_ids}
        current_row = self.mods_table.currentRow()

        for row in range(self.mods_table.rowCount()):
            workshop_id_item = self.mods_table.item(row, 2)
            if workshop_id_item is None:
                continue

            workshop_id = workshop_id_item.text().strip()
            if workshop_id in updated_set:
                mod_data = details_by_workshop.get(workshop_id)
                if mod_data:
                    if row < len(self.mod_data_list):
                        self.mod_data_list[row] = mod_data
                    self.mods_table.setItem(row, 0, QTableWidgetItem(mod_data.get('title', 'Unknown')))
                    self.mods_table.setItem(row, 3, QTableWidgetItem(self.format_update_time(mod_data.get('time_updated', 0))))

                    if current_row == row:
                        self.update_workshop_info(mod_data)

    def update_selected_mod_info(self):
        current_row = self.mods_table.currentRow()
        if current_row >= 0 and current_row < len(self.mod_data_list):
            mod_data = self.mod_data_list[current_row]
            self.update_workshop_info(mod_data)

    def save_config(self):
        success, message = self._write_config(show_message=True)
        return success

    def save_config_silent(self):
        success, _message = self._write_config(show_message=False)
        return success

    def _write_config(self, show_message=True):
        ini_path = self.settings_tab.ini_path.text()
        if not ini_path:
            if show_message:
                QMessageBox.warning(self, "Error", "No INI file selected in Settings.")
            return False, "No INI file selected in Settings."
        try:
            if self._is_mandatory_mod_enforced():
                self._ensure_mandatory_mod_present()
            with open(ini_path, 'r', encoding='utf-8') as f:
                content = f.read()
            lines = content.splitlines()
            # Collect Workshop IDs: unique, in order of first appearance from enabled mods
            seen_wids = set()
            workshop_ids = []
            for row in range(self.mods_table.rowCount()):
                if self._is_row_enabled(row):
                    wid_item = self.mods_table.item(row, 2)
                    if wid_item:
                        wid = wid_item.text().strip()
                        if wid and wid not in seen_wids:
                            seen_wids.add(wid)
                            workshop_ids.append(wid)
            # Collect enabled Mod IDs in table order
            mod_ids = []
            for row in range(self.mods_table.rowCount()):
                if self._is_row_enabled(row):
                    mod_id_item = self.mods_table.item(row, 1)
                    if mod_id_item:
                        mod_id = mod_id_item.text().strip()
                        if mod_id:
                            mod_ids.append(mod_id)

            if self._is_mandatory_mod_enforced():
                if MANDATORY_WORKSHOP_ID not in workshop_ids:
                    workshop_ids.append(MANDATORY_WORKSHOP_ID)
                if MANDATORY_MOD_ID not in mod_ids:
                    mod_ids.append(MANDATORY_MOD_ID)

            # Update or add lines
            workshop_line = f"WorkshopItems={';'.join(workshop_ids)}"
            mods_line = f"Mods={';'.join(mod_ids)}"
            updated_lines = []
            workshop_found = False
            mods_found = False
            for line in lines:
                if line.startswith("WorkshopItems="):
                    updated_lines.append(workshop_line)
                    workshop_found = True
                elif line.startswith("Mods="):
                    updated_lines.append(mods_line)
                    mods_found = True
                else:
                    updated_lines.append(line)
            if not workshop_found:
                updated_lines.append(workshop_line)
            if not mods_found:
                updated_lines.append(mods_line)
            # Write back
            with open(ini_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(updated_lines))
            if show_message:
                QMessageBox.information(self, "Success", "Config saved successfully.")
            return True, "OK"
        except Exception as e:
            if show_message:
                QMessageBox.critical(self, "Error", f"Failed to save config: {str(e)}")
            return False, f"Failed to save config: {str(e)}"

    def _add_mod_row(self, name, mod_id, workshop_id, updated_text, mod_data, enabled, lock_enabled=False):
        row_count = self.mods_table.rowCount()
        self.mods_table.insertRow(row_count)
        self.mod_data_list.append(mod_data)
        self.mods_table.setItem(row_count, 0, QTableWidgetItem(name))
        self.mods_table.setItem(row_count, 1, QTableWidgetItem(mod_id))
        self.mods_table.setItem(row_count, 2, QTableWidgetItem(workshop_id))
        self.mods_table.setItem(row_count, 3, QTableWidgetItem(updated_text))

        checkbox = CheckMarkBox(enabled)
        checkbox.setChecked(lock_enabled or enabled)
        if lock_enabled:
            checkbox.setEnabled(False)
        
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(checkbox, alignment=Qt.AlignCenter)
        self.mods_table.setCellWidget(row_count, 4, container)
        self.enabled_checkboxes.append(checkbox)

    def _sync_enabled_checkboxes_with_table(self):
        synced = []
        for row in range(self.mods_table.rowCount()):
            checkbox = self._get_row_checkbox(row)
            if checkbox is not None:
                synced.append(checkbox)
        self.enabled_checkboxes = synced

    def _get_row_checkbox(self, row):
        if row < 0 or row >= self.mods_table.rowCount():
            return None

        container = self.mods_table.cellWidget(row, 4)
        if container is None:
            return None

        return container.findChild(CheckMarkBox)

    def _is_row_enabled(self, row):
        checkbox = self._get_row_checkbox(row)
        return bool(checkbox and checkbox.isChecked())

    def _swap_checkbox_widgets(self, row_a, row_b):
        checkbox_a = self._get_row_checkbox(row_a)
        checkbox_b = self._get_row_checkbox(row_b)
        if checkbox_a is None or checkbox_b is None:
            return

        checked_a = checkbox_a.isChecked()
        enabled_a = checkbox_a.isEnabled()

        checkbox_a.setChecked(checkbox_b.isChecked())
        checkbox_a.setEnabled(checkbox_b.isEnabled())

        checkbox_b.setChecked(checked_a)
        checkbox_b.setEnabled(enabled_a)

    def _is_mandatory_row(self, row):
        mod_item = self.mods_table.item(row, 1)
        wid_item = self.mods_table.item(row, 2)
        if mod_item is None or wid_item is None:
            return False
        return mod_item.text().strip() == MANDATORY_MOD_ID and wid_item.text().strip() == MANDATORY_WORKSHOP_ID

    def _create_mod_data(self, title, description, creator, mod_ids, time_updated=0):
        """Create a mod data dictionary with standard structure."""
        return {
            'title': title,
            'description': description,
            'creator': creator,
            'time_updated': time_updated,
            'mod_ids': mod_ids,
        }

    def _ensure_mandatory_mod_present(self):
        if not self._is_mandatory_mod_enforced():
            return

        for row in range(self.mods_table.rowCount()):
            if self._is_mandatory_row(row):
                row_checkbox = self._get_row_checkbox(row)
                if row_checkbox is not None:
                    row_checkbox.setChecked(True)
                    row_checkbox.setEnabled(False)
                self._sync_enabled_checkboxes_with_table()
                return

        required_mod_data = self._create_mod_data(
            MANDATORY_MOD_ID,
            'Required by Knox Overseer.',
            'Knox Overseer',
            [MANDATORY_MOD_ID]
        )
        self._add_mod_row(
            MANDATORY_MOD_ID,
            MANDATORY_MOD_ID,
            MANDATORY_WORKSHOP_ID,
            'Required',
            required_mod_data,
            True,
            lock_enabled=True,
        )
        self._sync_enabled_checkboxes_with_table()

    def populate_mods_table(self, workshop_ids, enabled_mods=None, mods_list=None):
        if enabled_mods is None:
            enabled_mods = set()
        if mods_list is None:
            mods_list = []
        self.mods_table.setRowCount(0)
        self.mod_data_list = []
        self.enabled_checkboxes = []

        listed_mod_ids = set()
        for wid in workshop_ids:
            if wid.strip():
                mod_data = self.fetch_mod_details(wid.strip(), use_cache=True)
                for mod_id in mod_data['mod_ids']:
                    clean_mod_id = (mod_id or "").strip()
                    if not clean_mod_id:
                        continue
                    listed_mod_ids.add(clean_mod_id)
                    self._add_mod_row(
                        mod_data.get('title', 'Unknown'),
                        clean_mod_id,
                        wid.strip(),
                        self.format_update_time(mod_data.get('time_updated', 0)),
                        mod_data,
                        clean_mod_id in enabled_mods,
                    )

        # Include local/non-Workshop mods that exist in Mods= but not in WorkshopItems-derived rows.
        for mod_id in mods_list:
            if mod_id in listed_mod_ids:
                continue

            local_mod_data = self._create_mod_data(
                mod_id,
                'Local mod from Mods= (not linked to a Workshop item).',
                'Local',
                [mod_id]
            )
            self._add_mod_row(
                mod_id,
                mod_id,
                '',
                'Local',
                local_mod_data,
                mod_id in enabled_mods,
            )

        self._ensure_mandatory_mod_present()
        self._sync_enabled_checkboxes_with_table()
        self._apply_search_filter(self.search_input.text())

    def add_mod(self):
        workshop_id, ok = QInputDialog.getText(self, "Add Mod", "Enter Workshop ID:")
        if ok and workshop_id.strip():
            workshop_id = workshop_id.strip()
            # Fetch mod details from Steam API
            mod_data = self.fetch_mod_details(workshop_id, use_cache=False)
            for mod_id in mod_data['mod_ids']:
                self._add_mod_row(
                    mod_data.get('title', f'Workshop {workshop_id}'),
                    mod_id,
                    workshop_id,
                    self.format_update_time(mod_data.get('time_updated', 0)),
                    mod_data,
                    True,
                )
            self._ensure_mandatory_mod_present()
            self._sync_enabled_checkboxes_with_table()
            self._apply_search_filter(self.search_input.text())
            # Update workshop info box with the last added mod data
            self.update_workshop_info(mod_data)

    def _unique_mod_ids(self, raw_ids):
        seen = set()
        ordered = []
        for item in raw_ids:
            if item in seen:
                continue
            seen.add(item)
            ordered.append(item)
        return ordered

    def fetch_mod_details(self, workshop_id, use_cache=True):
        workshop_id = (workshop_id or "").strip()
        if not workshop_id:
            return {
                'title': 'Unknown Workshop Item',
                'description': 'Workshop ID is empty.',
                'creator': 'Unknown',
                'time_updated': 0,
                'mod_ids': [],
            }

        if use_cache and workshop_id in self._mod_details_cache:
            return self._mod_details_cache[workshop_id]

        url = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
        data = {
            'itemcount': 1,
            'publishedfileids[0]': workshop_id
        }
        # Fallback for private/unlisted/temporarily inaccessible Workshop entries.
        fallback = {
            'title': f'Workshop {workshop_id}',
            'description': 'Workshop details are unavailable (unlisted/private/API inaccessible).',
            'creator': 'Unknown',
            'time_updated': 0,
            'mod_ids': [workshop_id]
        }
        try:
            response = requests.post(url, data=data, timeout=STEAM_API_TIMEOUT_SECONDS)
            response.raise_for_status()
            json_data = response.json()
            details_list = json_data.get('response', {}).get('publishedfiledetails', [])
            if not details_list:
                self._mod_details_cache[workshop_id] = fallback
                return fallback
            details = details_list[0]
            if details.get('result') == 1:
                description = details.get('description', '')
                # Parse Mod IDs from description (case insensitive, can have spaces)
                mod_ids_raw = re.findall(r'mod id[:\s]*([^\n]+)', description, re.IGNORECASE)
                # Clean markup, split common separators, and preserve source order.
                mod_ids = []
                for raw in mod_ids_raw:
                    cleaned = re.sub(r'\[/?(?:code|b|i|u|br|p|div|span)[^\]]*\]', '', raw, flags=re.IGNORECASE)
                    cleaned = cleaned.strip()
                    if not cleaned:
                        continue
                    for token in re.split(r'[;,]', cleaned):
                        mod_id = token.strip()
                        if mod_id:
                            mod_ids.append(mod_id)
                mod_ids = self._unique_mod_ids(mod_ids)
                if not mod_ids:
                    mod_ids = [workshop_id]  # Fallback to Workshop ID if no Mod ID found
                result = {
                    'title': details.get('title', f'Workshop {workshop_id}'),
                    'description': description,
                    'creator': details.get('creator', ''),
                    'time_updated': details.get('time_updated', 0),
                    'mod_ids': mod_ids
                }
                self._mod_details_cache[workshop_id] = result
                return result
            self._mod_details_cache[workshop_id] = fallback
            return fallback
        except Exception:
            self._mod_details_cache[workshop_id] = fallback
            return fallback
        self._mod_details_cache[workshop_id] = fallback
        return fallback

    def update_workshop_info(self, mod_data):
        self.mod_title_label.setText(f"Title: {mod_data.get('title', 'Unknown')}")
        self.mod_updated_label.setText(f"Last Updated: {self.format_update_time(mod_data.get('time_updated', 0))}")
        self.mod_author_label.setText(f"Author: {mod_data.get('creator', 'Unknown')}")
        self.mod_description.setPlainText(mod_data.get('description', ''))

    def remove_mod(self):
        current_row = self.mods_table.currentRow()
        if current_row >= 0:
            if self._is_mandatory_mod_enforced() and self._is_mandatory_row(current_row):
                QMessageBox.warning(self, "Required Mod", "KnoxOverseer is required and cannot be removed.")
                return

            confirm = QMessageBox.question(
                self,
                "Confirm Removal",
                "Remove selected mod from the list?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return

            self.mods_table.removeRow(current_row)
            if current_row < len(self.mod_data_list):
                del self.mod_data_list[current_row]
            if current_row < len(self.enabled_checkboxes):
                del self.enabled_checkboxes[current_row]
            self._sync_enabled_checkboxes_with_table()
            self._apply_search_filter(self.search_input.text())

    def move_up(self):
        current_row = self.mods_table.currentRow()
        if current_row > 0:
            if self._is_mandatory_mod_enforced() and (self._is_mandatory_row(current_row) or self._is_mandatory_row(current_row - 1)):
                return
            # Swap with previous row
            for col in range(self.mods_table.columnCount() - 1):
                item_above = self.mods_table.takeItem(current_row - 1, col)
                item_current = self.mods_table.takeItem(current_row, col)
                self.mods_table.setItem(current_row - 1, col, item_current)
                self.mods_table.setItem(current_row, col, item_above)
            self._swap_checkbox_widgets(current_row - 1, current_row)
            # Swap mod_data
            self.mod_data_list[current_row - 1], self.mod_data_list[current_row] = self.mod_data_list[current_row], self.mod_data_list[current_row - 1]
            self._sync_enabled_checkboxes_with_table()
            self.mods_table.setCurrentCell(current_row - 1, 0)

    def move_down(self):
        current_row = self.mods_table.currentRow()
        if current_row < self.mods_table.rowCount() - 1 and current_row >= 0:
            if self._is_mandatory_mod_enforced() and (self._is_mandatory_row(current_row) or self._is_mandatory_row(current_row + 1)):
                return
            # Swap with next row
            for col in range(self.mods_table.columnCount() - 1):
                item_below = self.mods_table.takeItem(current_row + 1, col)
                item_current = self.mods_table.takeItem(current_row, col)
                self.mods_table.setItem(current_row + 1, col, item_current)
                self.mods_table.setItem(current_row, col, item_below)
            self._swap_checkbox_widgets(current_row, current_row + 1)
            # Swap mod_data
            self.mod_data_list[current_row + 1], self.mod_data_list[current_row] = self.mod_data_list[current_row], self.mod_data_list[current_row + 1]
            self._sync_enabled_checkboxes_with_table()
            self.mods_table.setCurrentCell(current_row + 1, 0)