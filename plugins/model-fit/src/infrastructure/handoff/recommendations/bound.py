from pathlib import Path

import model_fit.infrastructure.handoff.recommendations.files as recommendation


class FilePending:
    def __init__(self, path: Path):
        self.path = path

    def load(self):
        return recommendation.load_pending(self.path)

    def clear(self, *, missing_ok=False):
        self.path.unlink(missing_ok=missing_ok)

    def save(self, request, result):
        recommendation.save_pending(self.path, request, result)
