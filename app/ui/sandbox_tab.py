"""
SandboxVarsTab – robust reader/editor for a Project Zomboid *_SandboxVars.lua file.

Design
──────
Parser   Annotates every key=value line with its absolute line-index in the
         original file so the save operation can update exactly those bytes.
         All other lines (comments, blank lines, structure) are left untouched.
         Mod-added keys are discovered automatically.

Save     Works on a copy of the raw line list; only the *value token* on each
         matched line is replaced, preserving indentation, spacing and commas.
         Written via temp-file → os.replace() for atomicity.  A .bak is made
         before each successful save so corruption is never possible.

Adaptive Any key=value line present in the file (including those added by mods)
         is discovered and rendered automatically with the best-fit widget.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from .widgets import CheckMarkBox, NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox


# ─────────────────────────────────────────────────────────────────────────────
# Lua file parser
# ─────────────────────────────────────────────────────────────────────────────

def _clean_comment(text: str) -> str:
    """Strip PZ-specific in-engine markup from a comment string."""
    text = re.sub(r"<BHC>\s*", "", text)
    text = re.sub(r"<RGB:[^>]+>\s*", "", text)
    text = re.sub(r"\[!\]\s*", "", text)
    return text.strip()


def _decimal_places(raw: str) -> int:
    """Count meaningful decimal places in a float literal, e.g. '0.60' → 1."""
    if "." in raw:
        frac = raw.split(".", 1)[1].rstrip("0")
        return max(1, len(frac))
    return 1


def _format_float(value: float, decimal_places: int) -> str:
    """Serialise a float with exactly *decimal_places* digits after the point."""
    return f"{value:.{decimal_places}f}"


def _apply_value_to_line(orig_line: str, key: str, new_val: str) -> str:
    """
    Replace only the value token on a Lua ``key = old_val,`` line.

    Preserved exactly: leading indentation, key name, ``=`` spacing,
    trailing comma, trailing whitespace.
    Falls back to a safe reconstruction when the regex does not match.
    """
    pattern = rf'^(\s*{re.escape(key)}\s*=\s*)(.+?)(,?\s*)$'
    m = re.match(pattern, orig_line)
    if m:
        return f"{m.group(1)}{new_val}{m.group(3)}"
    # Safe fallback
    leading = len(orig_line) - len(orig_line.lstrip())
    had_comma = orig_line.rstrip().endswith(",")
    return f"{orig_line[:leading]}{key} = {new_val}{',' if had_comma else ''}"


def _extract_enum_options(comments: list) -> list:
    """
    Return [(int_num, label_str), …] when comment lines describe numbered
    options such as ``1 = Insane``, ``2 = Very High``, etc.
    Returns an empty list when fewer than 2 matches are found (not an enum).
    """
    options = []
    for line in comments:
        # Clean markup before matching so tags don't break the pattern
        m = re.match(r"^(\d+)\s*=\s*(.+)$", _clean_comment(line))
        if m:
            options.append((int(m.group(1)), m.group(2).strip()))
    return options if len(options) >= 2 else []


def _extract_min_max(comments: list):
    """Return (min_float, max_float) or (None, None) by scanning comments."""
    for line in comments:
        m = re.search(r"Min:\s*([-\d.]+)\s+Max:\s*([-\d.]+)", line)
        if m:
            return float(m.group(1)), float(m.group(2))
    return None, None


def parse_sandbox_vars(raw_text: str):
    """
    Parse a Project Zomboid ``*_SandboxVars.lua`` file.

    Returns
    -------
    sections : list[dict]
        Each dict has ``'name'`` (str) and ``'fields'`` (list[dict]).
        Each field dict has:
          ``'key'``       – Lua key name
          ``'raw_value'`` – value token as found in the file
          ``'comments'``  – list of preceding ``-- …`` lines (raw)
          ``'line_idx'``  – 0-based index into *original_lines*
    original_lines : list[str]
    """
    original_lines = raw_text.splitlines()

    root_fields: list = []
    all_sections: list = [{"name": "General", "fields": root_fields}]
    current_fields = root_fields
    pending_comments: list = []
    section_depth = 0  # 0 = top-level, 1 = inside a named subtable

    for line_idx, line in enumerate(original_lines):
        stripped = line.strip()

        if not stripped:
            # Blank lines separate logical blocks; flush pending comments so
            # they don't drift onto a different field below the blank line.
            pending_comments = []
            continue

        if stripped.startswith("--"):
            pending_comments.append(stripped[2:].strip())
            continue

        # Outer SandboxVars wrapper line
        if stripped == "SandboxVars = {":
            pending_comments = []
            continue

        # Closing brace (with or without trailing comma) – step up one level
        if re.match(r"^\},?$", stripped):
            if section_depth == 1:
                section_depth = 0
                current_fields = root_fields
            pending_comments = []
            continue

        # Named subtable opening:  Name = {
        if section_depth == 0:
            m = re.match(r"^(\w+)\s*=\s*\{", stripped)
            if m:
                sub_fields: list = []
                all_sections.append({"name": m.group(1), "fields": sub_fields})
                current_fields = sub_fields
                section_depth = 1
                pending_comments = []
                continue

        # Key = value pair (the common case)
        m = re.match(r"^(\w+)\s*=\s*(.+?)(?:,\s*)?$", stripped)
        if m:
            raw_val = m.group(2).strip()
            # Strip a trailing comma only when NOT inside a quoted string.
            # Quoted values end with '"' so rstrip(",") leaves them untouched.
            if not (raw_val.startswith('"') and raw_val.endswith('"')):
                raw_val = raw_val.rstrip(",").strip()
            current_fields.append(
                {
                    "key": m.group(1),
                    "raw_value": raw_val,
                    "comments": list(pending_comments),
                    "line_idx": line_idx,
                }
            )
            pending_comments = []

    return all_sections, original_lines


# ─────────────────────────────────────────────────────────────────────────────
# Tab widget
# ─────────────────────────────────────────────────────────────────────────────

class CollapsibleSection(QWidget):
    def __init__(self, title: str, expanded=True):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.toggle_button = QToolButton()
        self.toggle_button.setText(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.toggle_button.setStyleSheet(
            "text-align: left; padding: 8px 10px; font-weight: 600; border: 1px solid #2a2a2a;"
        )
        self.toggle_button.toggled.connect(self._on_toggled)
        layout.addWidget(self.toggle_button)

        self.body = QFrame()
        self.body.setFrameShape(QFrame.StyledPanel)
        self.body.setStyleSheet("QFrame { border: 1px solid #2a2a2a; border-top: 0; }")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(10, 10, 10, 10)
        self.body_layout.setSpacing(0)
        self.body.setVisible(expanded)
        layout.addWidget(self.body)

    def _on_toggled(self, expanded):
        self.toggle_button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.body.setVisible(expanded)

    def set_expanded(self, expanded: bool):
        if self.toggle_button.isChecked() == expanded:
            return
        self.toggle_button.blockSignals(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.blockSignals(False)
        self._on_toggled(expanded)

    def is_expanded(self) -> bool:
        return self.toggle_button.isChecked()


class FieldRow(QWidget):
    def __init__(self, label_text: str, widget: QWidget, description: str, tooltip: str):
        super().__init__()
        self._is_changed = False
        self._search_active = False
        self._is_match = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(14)

        self.label = QLabel(label_text)
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.label.setFixedWidth(220)
        font = self.label.font()
        font.setBold(True)
        self.label.setFont(font)
        self.label.setToolTip(tooltip)
        top_row.addWidget(self.label)

        self.widget = widget
        self.widget.setToolTip(tooltip)
        if isinstance(self.widget, CheckMarkBox):
            top_row.addWidget(self.widget, 0, Qt.AlignLeft)
            top_row.addStretch(1)
        else:
            top_row.addWidget(self.widget, 1)
        layout.addLayout(top_row)

        self.description = QLabel(description)
        self.description.setWordWrap(True)
        self.description.setContentsMargins(234, 0, 0, 0)
        if description:
            self.description.setStyleSheet("color: #888; font-size: 10px;")
        else:
            self.description.setFixedHeight(4)
        layout.addWidget(self.description)

    def set_changed(self, is_changed: bool):
        self._is_changed = is_changed
        self._refresh_styles()

    def set_search_match(self, search_active: bool, is_match: bool):
        self._search_active = search_active
        self._is_match = is_match
        self._refresh_styles()

    def _refresh_styles(self):
        label_style = ""
        description_style = "color: #888; font-size: 10px;" if self.description.text() else ""
        widget_style = ""

        if self._search_active and self._is_match:
            label_style = "color: #ffd08a;"
            if self.description.text():
                description_style = "color: #dcb075; font-size: 10px;"

        if self._is_changed:
            widget_style = "border: 1px solid #ff9d33; background-color: #241a10;"
            label_style = "color: #ffb25b;"
            if self.description.text():
                description_style = "color: #ffb25b; font-size: 10px;"

        self.widget.setStyleSheet(widget_style)
        self.label.setStyleSheet(label_style)
        if self.description.text():
            self.description.setStyleSheet(description_style)

class SandboxVarsTab(QWidget):
    """
    A full-featured editor for a Project Zomboid ``*_SandboxVars.lua`` file.

    Usage
    -----
    Call :meth:`set_path` whenever the active server INI changes to load the
    corresponding SandboxVars file.  The "Edit Vars" button in SettingsTab
    should also call :meth:`set_path` and then switch the tab into focus.
    """

    def __init__(self):
        super().__init__()
        self._current_path: str = ""
        self._last_loaded_mtime = None
        self._original_lines: list = []
        self._line_sep = "\n"
        self._ends_with_newline = False
        self._runtime_locked = False
        self._changed_fields = set()
        self._section_widgets: dict = {}
        self._pending_search_query = ""
        self._last_applied_search_query = None
        self._base_status_text = ""
        self._pre_search_section_state: dict[str, bool] = {}
        # (section_name, field_key) -> field metadata dict
        self._field_widgets: dict = {}
        self._setup_ui()

    def _editor_name(self) -> str:
        return "Sandbox"

    def _placeholder_text(self) -> str:
        return (
            'Select a server INI file in Settings,\n'
            'then click "Edit Vars" to load the Sandbox variables.'
        )

    def _parse_text(self, raw_text: str):
        return parse_sandbox_vars(raw_text)

    def _read_only_keys(self) -> set[str]:
        return {"VERSION"}

    def _schema_can_change_externally(self) -> bool:
        return True

    def _uses_collapsible_sections(self) -> bool:
        return True

    def _minimum_search_length(self) -> int:
        return 2

    def _apply_search_highlight(self) -> bool:
        return True

    def _filter_sections_during_search(self) -> bool:
        return True

    # ── Public API ────────────────────────────────────────────────────────

    def set_path(self, path: str) -> None:
        """Point the tab at a new file and reload immediately."""
        normalized = os.path.normpath(path) if path else ""
        if normalized == self._current_path:
            self._path_label.setText(path or "No file loaded")
            self.refresh_if_changed()
            return
        self._current_path = normalized
        self._path_label.setText(path or "No file loaded")
        # A new file should start unfiltered to avoid carrying stale search
        # results that can hide every row and look like a render failure.
        self._search_timer.stop()
        self._search_box.clear()
        self._pending_search_query = ""
        self._last_applied_search_query = None
        self._pre_search_section_state = {}
        # Clear the existing form so the next load() does a full rebuild
        self._field_widgets = {}
        self._changed_fields = set()
        self._section_widgets = {}
        self._last_loaded_mtime = None
        if path and os.path.isfile(path):
            self.load()
        else:
            self._set_status("File not found." if path else "")
            self._save_btn.setEnabled(False)
            self._reload_btn.setEnabled(bool(path))

    def refresh_if_changed(self) -> bool:
        """Reload from disk if the backing file changed externally."""
        if not self._current_path or not os.path.isfile(self._current_path):
            return False

        try:
            current_mtime = os.path.getmtime(self._current_path)
        except OSError:
            return False

        if self._last_loaded_mtime is None:
            self.load()
            return True

        if current_mtime == self._last_loaded_mtime:
            return False

        # Avoid clobbering unsaved edits made in the UI.
        if self._changed_fields:
            self._set_status(
                f"{self._editor_name()} changed on disk. You have unsaved local edits; click Save or Reload."
            )
            return False

        self.load()
        self._set_status(f"{self._editor_name()} changed on disk; refreshed automatically.")
        return True

    def load(self) -> None:
        """Read current file from disk and update the settings form."""
        if not self._current_path:
            return
        if not os.path.isfile(self._current_path):
            self._set_status(f"File not found: {self._current_path}")
            return
        try:
            with open(self._current_path, "r", encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
        except OSError as exc:
            self._set_status(f"Error reading file: {exc}")
            return

        sections, original_lines = self._parse_text(raw)
        self._original_lines = original_lines
        try:
            self._last_loaded_mtime = os.path.getmtime(self._current_path)
        except OSError:
            self._last_loaded_mtime = None
        self._line_sep = "\r\n" if "\r\n" in raw else "\n"
        self._ends_with_newline = raw.endswith(("\n", "\r"))
        self._last_applied_search_query = None

        # Sandbox schemas can grow when mods add new settings, so rebuild the
        # form when the discovered field count changes.
        should_rebuild = False
        if self._field_widgets and self._schema_can_change_externally():
            total_existing = len(self._field_widgets)
            total_new = sum(len(s["fields"]) for s in sections)
            if total_new != total_existing:
                should_rebuild = True

        if self._field_widgets and not should_rebuild:
            # Form already built and field count unchanged — refresh values in-place
            self._refresh_widget_values(sections)
        else:
            # First load, field count changed, or rebuilding — build all widgets from scratch
            self._changed_fields = set()
            self._build_form(sections)

        total = sum(len(s["fields"]) for s in sections)
        self._reload_btn.setEnabled(True)
        self._refresh_save_button()
        self._set_status(
            f"Loaded {total} settings from {os.path.basename(self._current_path)}"
        )

    def _refresh_widget_values(self, sections: list) -> None:
        """Update every widget value in-place after a reload of the same file."""
        # Build a flat lookup: (section_name, key) -> field dict
        new_fields: dict = {}
        for section in sections:
            for field in section["fields"]:
                new_fields[(section["name"], field["key"])] = field

        for field_id, metadata in self._field_widgets.items():
            field = new_fields.get(field_id)
            if field is None:
                continue
            raw = field["raw_value"]
            # Update line index in case the file was edited externally
            metadata["line_idx"] = field["line_idx"]
            metadata["original_value"] = raw
            widget = metadata["widget"]
            wtype = metadata["wtype"]
            widget.blockSignals(True)
            try:
                self._set_widget_value(widget, wtype, raw)
            finally:
                widget.blockSignals(False)
            self._set_field_changed(field_id, False)

        self._changed_fields.clear()

    def _set_widget_value(self, widget, wtype, raw: str) -> None:
        """Apply a Lua raw string value to the appropriate widget type."""
        if wtype == "bool":
            widget.setChecked(raw == "true")
        elif wtype == "string":
            widget.setText(raw[1:-1] if raw.startswith('"') and raw.endswith('"') else raw)
        elif wtype == "float":
            try:
                widget.setValue(float(raw))
            except (ValueError, TypeError):
                pass
        elif wtype == "int":
            try:
                widget.setValue(int(raw))
            except (ValueError, TypeError):
                pass
        elif isinstance(wtype, tuple) and wtype[0] == "enum":
            try:
                current = int(raw)
                num_map = {num: i for i, (num, _) in enumerate(wtype[1])}
                widget.setCurrentIndex(num_map.get(current, 0))
            except (ValueError, TypeError):
                pass
        elif wtype == "raw":
            widget.setText(raw)

    def save(self) -> None:
        """
        Write all modified values back to the Lua file.

        Only the value token on each field's line is changed; every other
        byte (comments, indentation, commas, blank lines) is preserved verbatim.
        Written atomically via temp-file → os.replace(); a .bak is kept.
        """
        if not self._current_path or not self._original_lines:
            return

        if not self._changed_fields:
            return

        lines = list(self._original_lines)
        warnings: list = []

        for field_id, metadata in self._field_widgets.items():
            key = metadata["key"]
            widget = metadata["widget"]
            wtype = metadata["wtype"]
            line_idx = metadata["line_idx"]
            new_val = self._get_lua_value(widget, wtype)
            if new_val is None:
                continue

            if line_idx < 0 or line_idx >= len(lines):
                warnings.append(f"'{key}': line index {line_idx} out of range – skipped")
                continue

            orig = lines[line_idx]

            # Integrity check: verify the key is actually on this line
            if not re.match(rf'^\s*{re.escape(key)}\s*=', orig):
                warnings.append(
                    f"'{key}': not found on expected line {line_idx + 1} – skipped"
                )
                continue

            lines[line_idx] = _apply_value_to_line(orig, key, new_val)

        # Atomic write: temp file in same directory → backup → rename
        dir_name = os.path.dirname(os.path.abspath(self._current_path))
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8", errors="replace", newline="") as fh:
                text = self._line_sep.join(lines)
                if self._ends_with_newline:
                    text += self._line_sep
                fh.write(text)

            # Backup before overwriting
            bak_path = self._current_path + ".bak"
            try:
                shutil.copy2(self._current_path, bak_path)
            except OSError:
                pass  # Non-fatal

            os.replace(tmp_path, self._current_path)
            tmp_path = None  # Ownership transferred

        except OSError as exc:
            self._set_status(f"Save failed: {exc}")
            return
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        if warnings:
            self._set_status(
                f"Saved with {len(warnings)} warning(s): {'; '.join(warnings)}"
            )
        else:
            self._set_status(
                f"Saved  ·  {os.path.basename(self._current_path)}  (backup → .bak)"
            )

        self._original_lines = lines
        for field_id, metadata in self._field_widgets.items():
            metadata["original_value"] = self._get_lua_value(metadata["widget"], metadata["wtype"])
            self._set_field_changed(field_id, False)
        self._changed_fields.clear()
        self._refresh_save_button()

    def set_runtime_lock(self, locked: bool) -> None:
        """Disable editing while the server is running."""
        self._runtime_locked = locked
        for metadata in self._field_widgets.values():
            metadata["widget"].setEnabled(metadata["editable"] and not locked)
        self._refresh_save_button()

    # ── Private: UI construction ──────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar ──────────────────────────────────────────────────────────
        top_bar = QWidget()
        top_row = QHBoxLayout(top_bar)
        top_row.setContentsMargins(12, 8, 12, 8)

        file_lbl = QLabel("File:")
        file_lbl.setFixedWidth(30)
        top_row.addWidget(file_lbl)

        self._path_label = QLabel("No file loaded")
        self._path_label.setStyleSheet("color: #999;")
        self._path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        top_row.addWidget(self._path_label)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(140)
        self._search_timer.timeout.connect(self._apply_pending_search_filter)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search settings, comments, or category")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.setMinimumWidth(260)
        self._search_box.textChanged.connect(self._schedule_search_filter)
        top_row.addWidget(self._search_box)

        self._reload_btn = QPushButton("Reload")
        self._reload_btn.setFixedWidth(80)
        self._reload_btn.setEnabled(False)
        self._reload_btn.clicked.connect(self.load)
        top_row.addWidget(self._reload_btn)

        self._save_btn = QPushButton("Save Changes")
        self._save_btn.setFixedWidth(130)
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self.save)
        top_row.addWidget(self._save_btn)

        root.addWidget(top_bar)

        # Status line ──────────────────────────────────────────────────────
        self._status_label = QLabel("")
        self._status_label.setContentsMargins(12, 2, 12, 6)
        self._status_label.setStyleSheet("color: #888; font-size: 10px;")
        root.addWidget(self._status_label)

        # Scrollable form area ─────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)

        placeholder = QLabel(self._placeholder_text())
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("color: #888; font-size: 13px;")
        self._scroll.setWidget(placeholder)

        root.addWidget(self._scroll)

    def _build_form(self, sections: list) -> None:
        previous_query = self._search_box.text().strip().lower()
        read_only_keys = self._read_only_keys()
        content = QWidget()
        vbox = QVBoxLayout(content)
        vbox.setContentsMargins(12, 12, 12, 12)
        vbox.setSpacing(14)
        self._field_widgets = {}
        self._section_widgets = {}

        for section in sections:
            if not section["fields"]:
                continue

            section_panel = self._create_section_container(section["name"])
            self._section_widgets[section["name"]] = section_panel
            for field in section["fields"]:
                field_id = (section["name"], field["key"])
                widget, wtype = self._create_widget(field)
                editable = field["key"] not in read_only_keys

                full_tooltip = self._full_tooltip(field["comments"])
                if not editable:
                    full_tooltip = (full_tooltip + "\n\nRead-only field.").strip()
                if not editable:
                    widget.setEnabled(False)

                desc = self._short_description(field["comments"], wtype)
                row_widget = FieldRow(field["key"], widget, desc, full_tooltip)
                self._section_body_layout(section_panel).addWidget(row_widget)

                self._field_widgets[field_id] = {
                    "key": field["key"],
                    "widget": widget,
                    "wtype": wtype,
                    "line_idx": field["line_idx"],
                    "original_value": field["raw_value"],
                    "editable": editable,
                    "row": row_widget,
                    "section": section["name"],
                    "search_text": " ".join(
                        [
                            section["name"].lower(),
                            field["key"].lower(),
                            self._full_tooltip(field["comments"]).lower(),
                        ]
                    ),
                }
                if editable:
                    self._connect_change_tracking(field_id)
                self._set_field_changed(field_id, False)

            vbox.addWidget(section_panel)

        vbox.addStretch()
        self._scroll.setWidget(content)
        if previous_query:
            self._schedule_search_filter(previous_query)
        self._refresh_save_button()

    def _create_section_container(self, name: str) -> QWidget:
        if self._uses_collapsible_sections():
            return CollapsibleSection(name, expanded=False)

        section_widget = QWidget()
        layout = QVBoxLayout(section_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if name != "General":
            header = QLabel(name)
            header.setStyleSheet(
                "padding: 8px 10px; font-weight: 600; border: 1px solid #2a2a2a;"
            )
            layout.addWidget(header)

        body = QFrame()
        body.setFrameShape(QFrame.StyledPanel)
        body.setStyleSheet("QFrame { border: 1px solid #2a2a2a; }")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 10, 10, 10)
        body_layout.setSpacing(0)
        layout.addWidget(body)

        section_widget._body_layout = body_layout
        return section_widget

    def _section_body_layout(self, section_widget: QWidget):
        if isinstance(section_widget, CollapsibleSection):
            return section_widget.body_layout
        return section_widget._body_layout

    def _set_section_expanded(self, section_widget: QWidget, expanded: bool):
        if isinstance(section_widget, CollapsibleSection):
            section_widget.set_expanded(expanded)

    def _capture_section_state(self) -> dict[str, bool]:
        state = {}
        for name, section_widget in self._section_widgets.items():
            if isinstance(section_widget, CollapsibleSection):
                state[name] = section_widget.is_expanded()
        return state

    def _restore_section_state(self):
        for name, expanded in self._pre_search_section_state.items():
            section_widget = self._section_widgets.get(name)
            if section_widget is not None:
                self._set_section_expanded(section_widget, expanded)
        self._pre_search_section_state = {}

    # ── Private: widget factory ───────────────────────────────────────────

    def _create_widget(self, field: dict):
        """
        Inspect the field's raw value and comments to build the most
        appropriate Qt widget.  Returns (widget, wtype).

        wtype is one of:
          'bool', 'string', 'float', 'int', 'raw',
          ('enum', [(num, label), ...])
        """
        raw = field["raw_value"]
        comments = field["comments"]

        # ── Boolean ────────────────────────────────────────────────────
        if raw in ("true", "false"):
            cb = CheckMarkBox()
            cb.setChecked(raw == "true")
            return cb, "bool"

        # ── Quoted string ──────────────────────────────────────────────
        if raw.startswith('"') and raw.endswith('"'):
            le = QLineEdit(raw[1:-1])
            le.setMinimumWidth(340)
            return le, "string"

        # ── Enum (numbered option list in comments) ────────────────────
        enum_opts = _extract_enum_options(comments)
        if enum_opts:
            cb = NoWheelComboBox()
            for num, label in enum_opts:
                cb.addItem(f"{num}  –  {label}")
            try:
                current = int(raw)
                num_map = {num: i for i, (num, _) in enumerate(enum_opts)}
                cb.setCurrentIndex(num_map.get(current, 0))
            except (ValueError, TypeError):
                pass
            cb.setMinimumWidth(260)
            return cb, ("enum", enum_opts)

        # ── Float ──────────────────────────────────────────────────────
        if "." in raw:
            try:
                val = float(raw)
                dp = _decimal_places(raw)
                sb = NoWheelDoubleSpinBox()
                sb.setDecimals(dp)
                sb.setSingleStep(max(0.1, 10.0 ** -dp))
                self._configure_numeric_widget(sb, val, comments)
                sb.setMinimumWidth(130)
                sb.setProperty("orig_dp", dp)
                return sb, "float"
            except (ValueError, TypeError):
                pass

        # ── Integer ────────────────────────────────────────────────────
        try:
            val = int(raw)
            sb = NoWheelSpinBox()
            self._configure_numeric_widget(sb, val, comments, is_int=True)
            sb.setMinimumWidth(120)
            return sb, "int"
        except (ValueError, TypeError):
            pass

        # ── Fallback: plain text ───────────────────────────────────────
        le = QLineEdit(raw)
        le.setMinimumWidth(300)
        return le, "raw"

    def _configure_numeric_widget(self, widget, value, comments, is_int=False):
        """Configure numeric spinbox with min/max constraints from comments."""
        min_v, max_v = _extract_min_max(comments)
        if is_int:
            widget.setMinimum(int(min_v) if min_v is not None else -2_147_483_647)
            widget.setMaximum(
                int(min(max_v, 2_147_483_647)) if max_v is not None else 2_147_483_647
            )
        else:
            widget.setMinimum(min_v if min_v is not None else -1_000_000.0)
            widget.setMaximum(min(max_v, 1_000_000.0) if max_v is not None else 1_000_000.0)
        widget.setValue(value)

    # ── Private: value serialisation back to Lua ──────────────────────

    def _get_lua_value(self, widget, wtype):
        if wtype == "bool":
            return "true" if widget.isChecked() else "false"
        if wtype == "string":
            # Re-wrap in quotes; inner content taken verbatim
            return f'"{widget.text()}"'
        if wtype == "float":
            dp = widget.property("orig_dp") or 1
            return _format_float(widget.value(), dp)
        if wtype == "int":
            return str(widget.value())
        if isinstance(wtype, tuple) and wtype[0] == "enum":
            idx = widget.currentIndex()
            opts = wtype[1]
            return str(opts[idx][0]) if 0 <= idx < len(opts) else "1"
        if wtype == "raw":
            return widget.text()
        return None

    def _connect_change_tracking(self, field_id):
        metadata = self._field_widgets[field_id]
        widget = metadata["widget"]
        wtype = metadata["wtype"]
        callback = lambda _v, fid=field_id: self._on_field_value_changed(fid)

        if wtype == "bool":
            signal = widget.toggled
        elif wtype in ("int", "float"):
            signal = widget.valueChanged
        elif isinstance(wtype, tuple) and wtype[0] == "enum":
            signal = widget.currentIndexChanged
        else:
            signal = widget.textChanged
        signal.connect(callback)

    def _on_field_value_changed(self, field_id):
        metadata = self._field_widgets[field_id]
        current_value = self._get_lua_value(metadata["widget"], metadata["wtype"])
        is_changed = current_value != metadata["original_value"]
        self._set_field_changed(field_id, is_changed)
        self._refresh_save_button()

    def _set_field_changed(self, field_id, is_changed):
        metadata = self._field_widgets[field_id]
        row = metadata["row"]

        if is_changed:
            self._changed_fields.add(field_id)
        else:
            self._changed_fields.discard(field_id)
        row.set_changed(is_changed)

    def _refresh_save_button(self):
        count = len(self._changed_fields)
        text = f"Save {count} Change{'s' if count != 1 else ''}" if count else "Save Changes"
        self._save_btn.setText(text)
        self._save_btn.setEnabled(bool(count) and not self._runtime_locked)

    def _schedule_search_filter(self, text: str):
        query = (text or "")
        stripped = query.strip()
        if stripped and len(stripped) < self._minimum_search_length():
            self._pending_search_query = ""
            self._search_timer.stop()
            # Keep the current filtered view until the query is either empty
            # or long enough to produce a new result set. This avoids a full
            # unfilter/reflow on the 2 -> 1 character transition.
            return

        if not stripped:
            self._pending_search_query = ""
            self._search_timer.start()
            return

        self._pending_search_query = query
        self._search_timer.start()

    def _apply_pending_search_filter(self):
        self._apply_search_filter(self._pending_search_query)

    def _apply_search_filter(self, text: str):
        query = (text or "").strip().lower()

        if query == self._last_applied_search_query:
            return
        previous_query = self._last_applied_search_query or ""
        self._last_applied_search_query = query

        content = self._scroll.widget()
        if content is not None:
            content.setUpdatesEnabled(False)

        search_active = bool(query)
        if search_active and not previous_query:
            self._pre_search_section_state = self._capture_section_state()

        section_match_counts = {name: 0 for name in self._section_widgets}
        total_matches = 0
        highlight_matches = self._apply_search_highlight()

        for metadata in self._field_widgets.values():
            is_match = not search_active or query in metadata["search_text"]
            row = metadata["row"]
            row.setVisible(is_match)
            if highlight_matches:
                row.set_search_match(search_active, search_active and is_match)
            if is_match:
                total_matches += 1
                section_match_counts[metadata["section"]] = section_match_counts.get(metadata["section"], 0) + 1

        if self._filter_sections_during_search():
            for section_name, section_widget in self._section_widgets.items():
                match_count = section_match_counts.get(section_name, 0)
                section_visible = not search_active or match_count > 0
                if section_widget.isHidden() == section_visible:
                    section_widget.setVisible(section_visible)
                if search_active and match_count > 0:
                    self._set_section_expanded(section_widget, True)

        if not search_active and previous_query:
            self._restore_section_state()

        if search_active:
            matched_sections = sum(1 for count in section_match_counts.values() if count > 0)
            self._status_label.setText(
                f"Search: {total_matches} match{'es' if total_matches != 1 else ''} in {matched_sections} section{'s' if matched_sections != 1 else ''}"
            )
        else:
            self._status_label.setText(self._base_status_text)

        if content is not None:
            content.setUpdatesEnabled(True)
            content.update()

    # ── Private: description helpers ──────────────────────────────────

    def _short_description(self, comments: list, wtype) -> str:
        """
        Return a concise description string for display below the widget.
        For enum widgets the numbered options are omitted (the combo shows them).
        """
        if not comments:
            return ""
        is_enum = isinstance(wtype, tuple) and wtype[0] == "enum"
        out = []
        for raw in comments:
            c = _clean_comment(raw)
            if not c:
                continue
            # Skip the numbered-option lines for enum combos
            if is_enum and re.match(r"^\d+\s*=\s*", c):
                continue
            # Skip bare "Default = …" lines for enums (redundant with selection)
            if is_enum and re.match(r"^Default\s*=", c):
                continue
            out.append(c)
        return " ".join(out)

    def _full_tooltip(self, comments: list) -> str:
        """Return all comment lines joined with newlines (for hover tooltip)."""
        return "\n".join(_clean_comment(c) for c in comments if c.strip())

    def _set_status(self, text: str) -> None:
        self._base_status_text = text
        if not self._last_applied_search_query:
            self._status_label.setText(text)
