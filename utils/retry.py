import time


def retry(func, retries: int = 3, delay: float = 5):
    """Call *func* up to *retries* times, sleeping *delay* seconds between attempts."""

    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            return func()
        except Exception as exc:
            last_error = exc
            print(f"Retry {attempt}/{retries} — {exc}")
            time.sleep(delay)

    raise last_error
