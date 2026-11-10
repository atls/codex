from dataclasses import dataclass

from model_fit.application.switch.types.state import ProcessSnapshot


@dataclass(frozen=True)
class ReconciledHandoff:
    pending_transfer: ProcessSnapshot | None
