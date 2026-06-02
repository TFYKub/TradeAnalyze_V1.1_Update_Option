import logging

logger = logging.getLogger(__name__)


def safe_run(func, *args, default=None, **kwargs):
    """Call *func* and return *default* if it raises, logging the error."""

    try:
        return func(*args, **kwargs)
    except Exception as exc:
        logger.error(f"[safe_run] {func.__name__}: {exc}")
        return default
