from typing import Any, Protocol


class ProfileCatalog(Protocol):
    def supported(self, profile: dict[str, Any]) -> bool: ...
