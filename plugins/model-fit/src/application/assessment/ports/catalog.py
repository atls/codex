from typing import Any, Protocol


class Catalog(Protocol):
    def supported(self, profile: dict[str, Any]) -> bool: ...
