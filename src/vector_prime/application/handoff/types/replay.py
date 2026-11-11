from dataclasses import dataclass


@dataclass(frozen=True)
class ReplayBound:
    pass


@dataclass(frozen=True)
class OwnerProfileChanged:
    same_source: bool


@dataclass(frozen=True)
class InputChanged:
    same_source: bool
