from PySide6.QtCore import QSettings


NEW_ORG = "KnoxOverseer"
NEW_APP = "Knox Overseer"


def get_app_settings():
    return QSettings(NEW_ORG, NEW_APP)
