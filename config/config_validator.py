import os


def validate():
    """Validate all required environment variables at startup."""

    required_env = [
        "LINE_TOKEN",
        "SHEET_ID",
        "GOOGLE_CREDENTIALS",
    ]

    missing = [env for env in required_env if not os.getenv(env)]

    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    print("CONFIG VALIDATION PASSED")
