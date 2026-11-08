import model_fit.infrastructure.adapters.filesystem.pending as recommendation


class FileRecommendations:
    def load(self, thread_id):
        return recommendation.load_pending(recommendation.pending_path(thread_id))

    def save(self, thread_id, request, result):
        recommendation.save_pending(
            recommendation.pending_path(thread_id), request, result
        )

    def clear(self, thread_id):
        recommendation.pending_path(thread_id).unlink()

    def unsafe(self, thread_id):
        return recommendation.pending_path(thread_id).is_symlink()
