import json
from pathlib import Path

from model_fit.infrastructure.adapters.codex.catalog import NativeCatalog

SUITE = Path(__file__).resolve().parents[2]


def catalog_models(sources):
    opening, closing = "<codex_catalog>", "</codex_catalog>"
    if sources.count(opening) != 1 or sources.count(closing) != 1:
        raise ValueError("Expected one Codex catalog in eval sources")
    entries = json.loads(sources.split(opening, 1)[1].split(closing, 1)[0])["models"]
    return NativeCatalog.index_entries(entries)
