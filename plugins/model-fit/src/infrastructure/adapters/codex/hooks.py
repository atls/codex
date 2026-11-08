"Read current hook admission from Codex without starting a turn."

import json
import os
from pathlib import Path

from model_fit.infrastructure.adapters.codex.transport.reader import AppServerReader


def hook_enabled(event_name: str, cwd: str) -> bool | None:
    root = Path(
        os.environ.get("CODEX_PLUGIN_ROOT") or Path(__file__).resolve().parents[4]
    )
    definition = (root / "hooks/hooks.json").resolve()
    with AppServerReader(cwd, hook_inventory=True) as app:
        config = app.call("config/read", {"includeLayers": False, "cwd": cwd}, 2)[
            "config"
        ]
        if (config.get("features") or {}).get("hooks") is False:
            return False
        groups = app.call("hooks/list", {"cwds": [cwd]}, 2)["data"]
    owned = [
        hook
        for group in groups
        for hook in group["hooks"]
        if hook.get("sourcePath") and Path(hook["sourcePath"]).resolve() == definition
    ]
    if not owned:
        manifest = root / ".codex-plugin/plugin.json"
        name = (
            json.loads(manifest.read_text()).get("name") if manifest.is_file() else None
        )
        registered = config.get("plugins") or {}
        return (
            False
            if name and any((key.partition("@")[0] == name for key in registered))
            else None
        )
    plugins = config.get("plugins") or {}
    if any(
        (
            (plugins.get(hook.get("pluginId")) or {}).get("enabled") is False
            for hook in owned
        )
    ):
        return False
    hooks = [hook for hook in owned if hook["eventName"].lower() == event_name.lower()]
    if not hooks:
        return False
    return all((hook["enabled"] and hook["trustStatus"] == "trusted" for hook in hooks))
