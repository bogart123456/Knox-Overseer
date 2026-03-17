import json
import builtins
from app.ui.stats_tab import StatsTab


def test_resolve_stats_paths_use_knox_data_folder(qapp):
    tab = StatsTab()
    ini = r"C:\\Users\\Xander\\Zomboid\\Server\\servertest.ini"

    stats_path = tab._resolve_stats_path(ini)
    cache_path = tab._resolve_players_cache_path(ini)

    stats_norm = stats_path.replace("\\", "/")
    cache_norm = cache_path.replace("\\", "/")
    assert stats_norm.endswith("Zomboid/Lua/KnoxOverseer/data/ServerStats.json")
    assert cache_norm.endswith("Zomboid/Lua/KnoxOverseer/data/PlayersCache.json")


def test_merge_with_cached_players_adds_offline(qapp):
    tab = StatsTab()
    tab._cached_players = [{"name": "Alice", "hoursSurvived": "1.00", "kills": 2, "lastSeen": "y", "location": "x"}]

    merged = tab._merge_with_cached_players([])
    assert any(p.get("name") == "Alice" for p in merged)
    assert merged[0]["status"] in ("Offline", "Online")


def test_save_players_cache_skips_unchanged(qapp, tmp_path, monkeypatch):
    tab = StatsTab()
    tab._players_cache_path = str(tmp_path / "PlayersCache.json")
    players = [{"name": "A"}]
    tab._players_cache_signature = tab._players_signature(players)

    def fail_open(*args, **kwargs):
        raise AssertionError("open() should not be called for unchanged payload")

    monkeypatch.setattr(builtins, "open", fail_open)
    tab._save_players_cache(players)


def test_refresh_stats_ignores_invalid_json(qapp, tmp_path):
    tab = StatsTab()
    path = tmp_path / "ServerStats.json"
    path.write_text("{", encoding="utf-8")
    tab._stats_path = str(path)

    tab.refresh_stats()
    assert tab._latest_payload == {}
