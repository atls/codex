import model_fit.infrastructure.adapters.filesystem.pending as recommendation


class FileRecommendations:
    def __init__(self, path_for_thread=recommendation.pending_path):
        self.path_for_thread = path_for_thread

    def load(self, thread_id):
        return recommendation.load_pending(self.path_for_thread(thread_id))

    def save(self, thread_id, request, result):
        recommendation.save_pending(self.path_for_thread(thread_id), request, result)

    def clear(self, thread_id, *, missing_ok=False):
        self.path_for_thread(thread_id).unlink(missing_ok=missing_ok)

    def unsafe(self, thread_id):
        return self.path_for_thread(thread_id).is_symlink()
