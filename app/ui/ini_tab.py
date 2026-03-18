from __future__ import annotations

import re

from .sandbox_tab import SandboxVarsTab


def parse_ini(raw_text: str):
    """Parse a simple INI-style key/value file while preserving raw line indexes."""
    original_lines = raw_text.splitlines()

    root_fields: list = []
    all_sections: list = [{"name": "General", "fields": root_fields}]
    current_fields = root_fields
    pending_comments: list = []

    for line_idx, line in enumerate(original_lines):
        stripped = line.strip()

        if not stripped:
            pending_comments = []
            continue

        if stripped.startswith("#") or stripped.startswith(";"):
            pending_comments.append(stripped[1:].strip())
            continue

        if stripped.startswith("[") and stripped.endswith("]"):
            section_name = stripped[1:-1].strip() or "General"
            current_fields = []
            all_sections.append({"name": section_name, "fields": current_fields})
            pending_comments = []
            continue

        match = re.match(r"^([^=]+?)\s*=\s*(.*)$", stripped)
        if not match:
            pending_comments = []
            continue

        key = match.group(1).strip()
        if not key:
            pending_comments = []
            continue

        current_fields.append(
            {
                "key": key,
                "raw_value": match.group(2).strip(),
                "comments": list(pending_comments),
                "line_idx": line_idx,
            }
        )
        pending_comments = []

    return all_sections, original_lines


class IniTab(SandboxVarsTab):
    def _editor_name(self) -> str:
        return "INI"

    def _placeholder_text(self) -> str:
        return "Select a server INI file in Settings to load the INI configuration."

    def _parse_text(self, raw_text: str):
        return parse_ini(raw_text)

    def _read_only_keys(self) -> set[str]:
        return set()

    def _schema_can_change_externally(self) -> bool:
        return False

    def _uses_collapsible_sections(self) -> bool:
        return False

    def _filter_sections_during_search(self) -> bool:
        # Keep section containers visible in INI to avoid extra layout churn.
        return False