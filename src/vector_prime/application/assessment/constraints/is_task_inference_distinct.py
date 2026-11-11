def is_task_inference_distinct(inference: str | None, guidance: str) -> bool:
    return (
        inference is not None
        and bool(inference.strip())
        and inference.strip() != guidance.strip()
    )
