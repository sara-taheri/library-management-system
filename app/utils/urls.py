"""URL helpers."""


def safe_redirect_target(target: str | None, fallback: str = "/") -> str:
    """Return *target* only if it is a same-site relative path.

    Blocks open-redirect attacks such as ``?next=https://evil.example``
    or protocol-relative ``//evil.example`` after login.
    """
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return fallback
