from urllib.parse import urlparse


def is_official_source(url: object) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "developers.openai.com"
        and (
            parsed.path.rstrip("/").removesuffix(".md")
            in ("/api/docs/guides/model-selection", "/api/docs/guides/reasoning")
        )
    )
