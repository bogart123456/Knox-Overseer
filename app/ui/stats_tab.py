import json
import os
import re
from datetime import datetime
from PySide6.QtGui import QKeySequence
from PySide6.QtCore import QFileSystemWatcher, QTimer, Qt
from PySide6.QtWidgets import QApplication, QAbstractItemView, QMenu, QTableWidget, QWidget, QTableWidgetItem, QMessageBox


class CopyableTableWidget(QTableWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, position):
        menu = QMenu(self)
        copy_action = menu.addAction("Copy")
        selected_action = menu.exec(self.viewport().mapToGlobal(position))
        if selected_action == copy_action:
            self.copy_selection_to_clipboard()

    def keyPressEvent(self, event):
        is_ctrl = bool(event.modifiers() & Qt.ControlModifier)
        is_copy = event.matches(QKeySequence.Copy) or (is_ctrl and event.key() in (Qt.Key_C, Qt.Key_Insert))
        if is_copy:
            self.copy_selection_to_clipboard()
            return
        super().keyPressEvent(event)

    def copy_selection_to_clipboard(self):
        ranges = self.selectedRanges()
        if not ranges:
            current = self.currentItem()
            if current is None:
                return
            QApplication.clipboard().setText(current.text())
            return

        blocks = []
        for selected_range in ranges:
            rows = []
            for row in range(selected_range.topRow(), selected_range.bottomRow() + 1):
                values = []
                for column in range(selected_range.leftColumn(), selected_range.rightColumn() + 1):
                    item = self.item(row, column)
                    values.append(item.text() if item is not None else "")
                rows.append("\t".join(values))
            blocks.append("\n".join(rows))

        QApplication.clipboard().setText("\n\n".join(blocks))

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        # Prevent stale highlight visuals when table is no longer active.
        self.clearSelection()
        self.setCurrentItem(None)


class StatsTab(QWidget):
    def __init__(self):
        super().__init__()
        self._ini_path = ""
        self._stats_path = ""
        self._players_cache_path = ""
        self._cached_players = []
        self._real_uptime_seconds = None
        self._latest_payload = {}
        self._latest_players = []
        self._latest_total_online = 0
        self._players_cache_signature = None
        self._has_loaded_payload_once = False
        self._file_watcher = QFileSystemWatcher()
        self._file_watcher.fileChanged.connect(self._on_stats_file_changed)
        self.setup_ui()

    def setup_ui(self):
        from PySide6.QtWidgets import QVBoxLayout, QLabel, QGridLayout, QHeaderView, QSizePolicy, QHBoxLayout, QPushButton

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(6)
        self.label_server_name = QLabel("Server: -")
        self.label_uptime = QLabel("Snapshot: -")
        self.label_ingame_date = QLabel("In-Game Date: -")
        self.label_ingame_time = QLabel("In-Game Time: -")
        self.label_weather = QLabel("Weather: -")
        self.label_temperature = QLabel("Temperature: -")

        for label in [
            self.label_server_name,
            self.label_uptime,
            self.label_ingame_date,
            self.label_ingame_time,
            self.label_weather,
            self.label_temperature,
        ]:
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        grid.addWidget(self.label_server_name, 0, 0)
        grid.addWidget(self.label_uptime, 0, 1)
        grid.addWidget(self.label_ingame_date, 1, 0)
        grid.addWidget(self.label_ingame_time, 1, 1)
        grid.addWidget(self.label_weather, 2, 0)
        grid.addWidget(self.label_temperature, 2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        self.players_count_label = QLabel("Players: -/-")
        self.players_count_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.players_count_label)

        actions_layout = QHBoxLayout()
        actions_layout.addStretch(1)
        self.clear_stats_button = QPushButton("Clear Stats Data")
        self.clear_stats_button.clicked.connect(self._confirm_clear_stats_data)
        actions_layout.addWidget(self.clear_stats_button)
        layout.addLayout(actions_layout)

        self.players_table = CopyableTableWidget()
        self.players_table.setColumnCount(6)
        self.players_table.setHorizontalHeaderLabels([
            "Name", "Status", "Hours Survived", "Kills", "Last Seen", "Location"
        ])
        self.players_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.players_table.setAlternatingRowColors(True)
        self.players_table.verticalHeader().setVisible(False)
        header = self.players_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.players_table)

        # Slow fallback timer: only used to detect when the stats file first appears
        # on disk (before the mod has created it). Once the file exists the watcher
        # takes over and this timer stops.
        self._appear_timer = QTimer()
        self._appear_timer.timeout.connect(self._poll_until_file_appears)
        self._appear_timer.start(3000)

    def set_real_uptime_seconds(self, seconds):
        if seconds is None:
            self._real_uptime_seconds = None
            return
        try:
            self._real_uptime_seconds = max(0, int(seconds))
        except Exception:
            self._real_uptime_seconds = None

    def set_ini_path(self, ini_path):
        self._ini_path = (ini_path or "").strip()

        # Drop any previously watched paths before resolving new ones.
        watched = self._file_watcher.files()
        if watched:
            self._file_watcher.removePaths(watched)

        self._stats_path = self._resolve_stats_path(self._ini_path)
        self._players_cache_path = self._resolve_players_cache_path(self._ini_path)
        self._cached_players = self._load_players_cache()
        self._players_cache_signature = self._players_signature(self._cached_players)
        self._update_server_name_from_ini()
        self._attach_watcher()
        self.refresh_stats()

    def _players_signature(self, players):
        try:
            return json.dumps(players, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return None

    def _attach_watcher(self):
        """Add the stats file to the watcher if it exists; ensure the fallback
        timer runs only when the file is absent."""
        if self._stats_path and os.path.isfile(self._stats_path):
            self._file_watcher.addPath(self._stats_path)
            self._appear_timer.stop()
        else:
            self._appear_timer.start(3000)

    def _poll_until_file_appears(self):
        """Called every 3 s while the stats file doesn't exist yet.
        As soon as it appears, hand off to the file watcher."""
        if self._stats_path and os.path.isfile(self._stats_path):
            self._file_watcher.addPath(self._stats_path)
            self._appear_timer.stop()
            self.refresh_stats()

    def _on_stats_file_changed(self, path):
        """Called by QFileSystemWatcher whenever the stats file is written.
        Some writers atomically replace a file (temp + rename), which causes the
        watcher to lose track. Re-add the path unconditionally so we never miss
        a subsequent update."""
        if self._stats_path and os.path.isfile(self._stats_path):
            # Re-add in case an atomic replace removed it from the watch list.
            if self._stats_path not in self._file_watcher.files():
                self._file_watcher.addPath(self._stats_path)
        self.refresh_stats()

    def _update_server_name_from_ini(self):
        if not self._ini_path:
            self.label_server_name.setText("Server: -")
            return
        ini_name = os.path.splitext(os.path.basename(self._ini_path))[0]
        self.label_server_name.setText(f"Server: {ini_name or '-'}")

    def _resolve_stats_path(self, ini_path):
        if not ini_path:
            return ""

        server_dir = os.path.dirname(ini_path)
        zomboid_root = os.path.dirname(server_dir)
        base_dir = os.path.join(zomboid_root, "Lua", "KnoxOverseer", "data")
        return os.path.join(base_dir, "ServerStats.json")

    def _resolve_players_cache_path(self, ini_path):
        if not ini_path:
            return ""

        server_dir = os.path.dirname(ini_path)
        zomboid_root = os.path.dirname(server_dir)
        base_dir = os.path.join(zomboid_root, "Lua", "KnoxOverseer", "data")
        return os.path.join(base_dir, "PlayersCache.json")

    def _load_players_cache(self):
        if not self._players_cache_path or not os.path.isfile(self._players_cache_path):
            return []
        try:
            with open(self._players_cache_path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            rows = payload.get('players', []) if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                return []
            out = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                out.append({
                    'name': row.get('name', 'Unknown'),
                    'status': row.get('status', 'Offline'),
                    'hoursSurvived': str(row.get('hoursSurvived', '0.00')),
                    'kills': row.get('kills', 0),
                    'lastSeen': row.get('lastSeen', 'Unknown'),
                    'location': row.get('location', 'Unknown')
                })
            return out
        except Exception:
            return []

    def _save_players_cache(self, players):
        if not self._players_cache_path:
            return

        new_signature = self._players_signature(players)
        if new_signature is not None and new_signature == self._players_cache_signature:
            return

        try:
            os.makedirs(os.path.dirname(self._players_cache_path), exist_ok=True)
            with open(self._players_cache_path, 'w', encoding='utf-8') as f:
                json.dump({'players': players}, f, ensure_ascii=False, indent=2)
            self._players_cache_signature = new_signature
        except Exception:
            pass

    def _confirm_clear_stats_data(self):
        result = QMessageBox.warning(
            self,
            "Clear Server Stats Data",
            "This will permanently clear server stats data, including the entire player table. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result != QMessageBox.Yes:
            return
        self.clear_stats_data()

    def clear_stats_data(self):
        if not self._stats_path:
            self._set_no_data_state("No stats path resolved")
            return

        cleared_payload = {
            "irlTimestamp": "-",
            "totalOnline": 0,
            "playersTable": [],
            "onlinePlayers": [],
            "allPlayers": {},
            "serverTime": {},
            "weather": {},
        }

        try:
            os.makedirs(os.path.dirname(self._stats_path), exist_ok=True)
            with open(self._stats_path, 'w', encoding='utf-8') as f:
                json.dump(cleared_payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._set_no_data_state(f"Failed clearing stats file: {e}")
            return

        self._cached_players = []
        self._save_players_cache([])
        self._apply_payload(cleared_payload)

    def refresh_stats(self):
        if not self._stats_path:
            if not self._has_loaded_payload_once:
                self._set_no_data_state("No stats path resolved")
            return

        if not os.path.isfile(self._stats_path):
            if not self._has_loaded_payload_once:
                self._set_no_data_state(f"Stats file not found: {self._stats_path}")
            return

        try:
            with open(self._stats_path, 'r', encoding='utf-8') as f:
                raw = f.read()
        except Exception as e:
            if not self._has_loaded_payload_once:
                self._set_no_data_state(f"Failed reading stats: {e}")
            return

        if not raw or not raw.strip():
            # Writer may have truncated before finishing current frame; keep last good UI state.
            if not self._has_loaded_payload_once:
                self._set_no_data_state("Stats file is temporarily empty")
            return

        try:
            payload = json.loads(raw)
        except Exception:
            # Partial JSON frame while writer is updating; keep previous valid data.
            if not self._has_loaded_payload_once:
                self._set_no_data_state("Stats JSON is temporarily invalid")
            return

        if not isinstance(payload, dict):
            if not self._has_loaded_payload_once:
                self._set_no_data_state("Stats payload is not an object")
            return

        self._has_loaded_payload_once = True
        self._apply_payload(payload)

    def _set_no_data_state(self, message):
        self._latest_payload = {}
        self._latest_players = []
        self._latest_total_online = 0
        self.label_uptime.setText("Snapshot: -")
        self.label_ingame_date.setText("In-Game Date: -")
        self.label_ingame_time.setText("In-Game Time: -")
        self.label_weather.setText("Weather: -")
        self.label_temperature.setText("Temperature: -")
        self.players_count_label.setText("Players: -/-")
        self.players_table.setRowCount(0)

    def _merge_with_cached_players(self, current_rows):
        current_by_name = {}
        for row in current_rows:
            name = str(row.get('name', '')).strip()
            if not name:
                continue
            current_by_name[name] = dict(row)

        cache_by_name = {}
        for row in self._cached_players:
            name = str(row.get('name', '')).strip()
            if not name:
                continue
            cache_by_name[name] = dict(row)

        # Bring forward players from cache that are not in current payload.
        for name, cached in cache_by_name.items():
            if name in current_by_name:
                continue
            current_by_name[name] = {
                'name': name,
                'status': 'Offline',
                'hoursSurvived': str(cached.get('hoursSurvived', '0.00')),
                'kills': cached.get('kills', 0),
                'lastSeen': cached.get('lastSeen', 'Unknown'),
                'location': cached.get('location', 'Unknown')
            }

        merged = list(current_by_name.values())
        merged.sort(key=lambda p: (0 if str(p.get('status')) == 'Online' else 1, str(p.get('name', '')).lower()))
        return merged

    def _format_ingame_date_time(self, payload):
        st = payload.get('serverTime', {})
        if not isinstance(st, dict):
            return "-", "-"
        year = st.get('year', st.get('yearsss', '-'))
        month = st.get('month', '-')
        day = st.get('day', '-')
        hour = st.get('hour', '-')
        minute = st.get('minute', '-')
        second = st.get('second', None)

        try:
            month_i = int(month)
            day_i = int(day)
            hour_i = int(hour)
            minute_i = int(minute)
            if second is None:
                return f"{year}-{month_i:02d}-{day_i:02d}", f"{hour_i:02d}:{minute_i:02d}"
            second_i = int(second)
            return f"{year}-{month_i:02d}-{day_i:02d}", f"{hour_i:02d}:{minute_i:02d}:{second_i:02d}"
        except Exception:
            return "-", "-"

    def _extract_weather_fields(self, payload):
        weather = payload.get('weather', {})
        if not isinstance(weather, dict):
            return "-", "-"

        summary = str(weather.get('summary', '')).strip()
        temp = weather.get('temperatureC')

        temp_text = "-"
        if temp is not None:
            try:
                temp_text = f"{float(temp):.1f} C"
            except Exception:
                temp_text = "-"

        return (summary or "-"), temp_text

    def _format_hours(self, value):
        try:
            return f"{float(value):.2f}"
        except Exception:
            return "0.00"

    def _format_unix_time(self, value):
        try:
            return datetime.fromtimestamp(float(value)).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            return "Unknown"

    def _apply_payload(self, payload):
        snapshot = payload.get('irlTimestamp', '-')
        total_online = int(payload.get('totalOnline', 0) or 0)

        table_has_focus = self.players_table.hasFocus()
        selected_cells = []
        current_row = -1
        current_col = -1
        if table_has_focus:
            selected_cells = [(idx.row(), idx.column()) for idx in self.players_table.selectedIndexes()]
            current_row = self.players_table.currentRow()
            current_col = self.players_table.currentColumn()

        players = self._build_players_table_from_payload(payload)
        players = self._merge_with_cached_players(players)
        total_known = len(players)
        ingame_date, ingame_time = self._format_ingame_date_time(payload)
        weather_summary, temperature_text = self._extract_weather_fields(payload)

        self._latest_payload = payload if isinstance(payload, dict) else {}
        self._cached_players = players
        self._latest_players = players
        self._latest_total_online = total_online
        self._save_players_cache(players)

        self.label_uptime.setText(f"Snapshot: {snapshot}")
        self.label_ingame_date.setText(f"In-Game Date: {ingame_date}")
        self.label_ingame_time.setText(f"In-Game Time: {ingame_time}")
        self.label_weather.setText(f"Weather: {weather_summary}")
        self.label_temperature.setText(f"Temperature: {temperature_text}")
        self.players_count_label.setText(f"Players: {total_online}/{total_known}")

        self.players_table.setRowCount(len(players))
        for row, p in enumerate(players):
            row_values = [
                str(p.get('name', 'Unknown')),
                str(p.get('status', 'Offline')),
                str(p.get('hoursSurvived', '0.00')),
                str(p.get('kills', 0)),
                str(p.get('lastSeen', 'Unknown')),
                str(p.get('location', 'Unknown')),
            ]
            for col, value in enumerate(row_values):
                item = self.players_table.item(row, col)
                if item is None:
                    self.players_table.setItem(row, col, QTableWidgetItem(value))
                    continue
                if item.text() != value:
                    item.setText(value)

        if table_has_focus and current_row >= 0 and current_row < self.players_table.rowCount():
            safe_col = current_col if 0 <= current_col < self.players_table.columnCount() else 0
            self.players_table.setCurrentCell(current_row, safe_col)

        if table_has_focus and selected_cells:
            self.players_table.clearSelection()
            for row, col in selected_cells:
                item = self.players_table.item(row, col)
                if item is not None:
                    item.setSelected(True)
        elif not table_has_focus:
            self.players_table.clearSelection()
            self.players_table.setCurrentItem(None)

    def _build_players_table_from_payload(self, payload):
        players_table = payload.get('playersTable', [])
        if isinstance(players_table, list) and players_table:
            rows = []
            for p in players_table:
                if not isinstance(p, dict):
                    continue

                hours_value = p.get('hoursSurvived', None)
                if hours_value is None and p.get('playtime'):
                    hours_text = str(p.get('playtime'))
                else:
                    hours_text = self._format_hours(hours_value if hours_value is not None else 0)

                rows.append({
                    'name': p.get('name', 'Unknown'),
                    'status': p.get('status', 'Offline'),
                    'hoursSurvived': hours_text,
                    'kills': p.get('kills', p.get('zombiesKilled', 0)),
                    'lastSeen': p.get('lastSeen', 'Unknown'),
                    'location': p.get('location', p.get('lastLocation', 'Unknown'))
                })

            rows.sort(key=lambda p: (0 if str(p.get('status')) == 'Online' else 1, str(p.get('name', '')).lower()))
            return rows

        rows = []

        online = payload.get('onlinePlayers', [])
        if isinstance(online, list):
            for p in online:
                rows.append({
                    'name': p.get('name', 'Unknown'),
                    'status': 'Online',
                    'hoursSurvived': self._format_hours(p.get('hoursSurvived', 0)),
                    'kills': p.get('zombiesKilled', 0),
                    'lastSeen': 'Now',
                    'location': p.get('location', 'Unknown')
                })

        known_names = {str(r.get('name', '')) for r in rows}
        all_players = payload.get('allPlayers', {})
        if isinstance(all_players, dict):
            for name, p in all_players.items():
                if name in known_names:
                    continue
                last_seen = self._format_unix_time(p.get('lastSeen'))
                rows.append({
                    'name': name,
                    'status': 'Offline',
                    'hoursSurvived': self._format_hours(p.get('hoursSurvived', 0)),
                    'kills': p.get('zombiesKilled', 0),
                    'lastSeen': last_seen,
                    'location': p.get('location', 'Unknown')
                })

        rows.sort(key=lambda p: (0 if str(p.get('status')) == 'Online' else 1, str(p.get('name', '')).lower()))
        return rows

    def _weather_icon_for_summary(self, summary):
        text = (summary or "").strip().lower()
        mapping = {
            "clear": ":sunny:",
            "cloudy": ":white_sun_cloud:",
            "rain": ":cloud:",
            "heavy rain": ":cloud_rain:",
            "storm": ":cloud_lightning:",
            "thunderstorm": ":thunder_cloud_rain:",
            "thunder storm": ":thunder_cloud_rain:",
            "fog": ":fog:",
            "snow": ":snowflake:",
            "hail": ":cloud_snow:",
        }
        return mapping.get(text, ":sunny:")

    def _extract_xy_from_location(self, location):
        text = str(location or "").strip()
        nums = re.findall(r"-?\d+(?:\.\d+)?", text)
        if len(nums) >= 2:
            try:
                x = int(float(nums[0]))
                y = int(float(nums[1]))
                return x, y
            except Exception:
                return None, None
        return None, None

    def _format_discord_player_block(self, player):
        name = self._sanitize_discord_text(player.get('name', 'Unknown'))
        alive = self._format_alive_duration(player.get('hoursSurvived', '0'))
        kills = self._sanitize_discord_text(player.get('kills', 0))
        location = self._sanitize_discord_text(player.get('location', 'Unknown'))
        x, y = self._extract_xy_from_location(location)

        lines = [
            f"**• {name}**",
            f"*Alive: {alive}*",
            f"*Kills: {kills}*",
        ]
        if x is not None and y is not None:
            lines.append(f"*[:round_pushpin:Location](<https://b42map.com/?{x}x{y}x5>)*")
        else:
            lines.append(f"*Location: {location}*")
        return "\n".join(lines)

    def _format_alive_duration(self, hours_value):
        try:
            total_hours = int(float(hours_value))
        except Exception:
            total_hours = 0

        if total_hours < 24:
            return f"{total_hours}h"

        days = total_hours // 24
        hours = total_hours % 24
        return f"{days}d {hours}h"

    def _sanitize_discord_text(self, value):
        text = str(value if value is not None else "")
        # Keep Discord markdown readable while avoiding control/newline breaks from source data.
        text = text.replace("\r", " ").replace("\n", " ").strip()
        return text or "-"

    def _format_discord_ingame_date(self):
        payload = self._latest_payload if isinstance(self._latest_payload, dict) else {}
        st = payload.get('serverTime', {}) if isinstance(payload.get('serverTime', {}), dict) else {}
        try:
            year = int(st.get('year'))
            month = int(st.get('month'))
            day = int(st.get('day'))
            return datetime(year, month, day).strftime("%B %d, %Y")
        except Exception:
            raw = self.label_ingame_date.text().replace("In-Game Date: ", "").strip()
            return self._sanitize_discord_text(raw or "-")

    def _format_discord_ingame_time(self):
        payload = self._latest_payload if isinstance(self._latest_payload, dict) else {}
        st = payload.get('serverTime', {}) if isinstance(payload.get('serverTime', {}), dict) else {}
        try:
            hour = int(st.get('hour'))
            minute = int(st.get('minute'))
            return f"{hour:02d}:{minute:02d}"
        except Exception:
            raw = self.label_ingame_time.text().replace("In-Game Time: ", "").strip()
            parts = raw.split(":")
            if len(parts) >= 2:
                return self._sanitize_discord_text(f"{parts[0]}:{parts[1]}")
            return self._sanitize_discord_text(raw or "-")

    def get_discord_template_context(self):
        payload = self._latest_payload if isinstance(self._latest_payload, dict) else {}
        players = list(self._latest_players or [])

        online = []
        offline = []
        for p in players:
            status = str(p.get('status', 'Offline')).strip().lower()
            if status == 'online':
                online.append(p)
            else:
                offline.append(p)

        online_text = "\n".join(self._format_discord_player_block(p) for p in online) or "No players online"
        offline_text = "\n".join(self._format_discord_player_block(p) for p in offline) or "No offline players"

        weather = payload.get('weather', {}) if isinstance(payload.get('weather', {}), dict) else {}
        weather_summary = self._sanitize_discord_text(weather.get('summary', 'Unknown') or 'Unknown')
        temperature_c = weather.get('temperatureC', '-')
        try:
            temperature_text = f"{float(temperature_c):.1f}"
        except Exception:
            temperature_text = "-"

        return {
            "server_name": self._sanitize_discord_text(os.path.splitext(os.path.basename(self._ini_path))[0] if self._ini_path else "-"),
            "online_count": str(int(self._latest_total_online or 0)),
            "online_players_formatted": online_text,
            "offline_players_formatted": offline_text,
            "ingame_date": self._format_discord_ingame_date(),
            "ingame_time": self._format_discord_ingame_time(),
            "weather": weather_summary,
            "weather_icon": self._weather_icon_for_summary(weather_summary),
            "temperature_c": temperature_text,
        }
