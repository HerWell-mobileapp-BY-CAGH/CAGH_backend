from .base import *

import dj_database_url

DEBUG = True


def _running_in_docker() -> bool:
    return os.path.exists("/.dockerenv")


# Host-machine development: `.env` often still points at the Docker service
# hostname `db`, which is not resolvable outside the compose network.
# Default to SQLite unless USE_POSTGRES=true (with host remapped to localhost).
if not _running_in_docker():
    database_url = os.environ.get("DATABASE_URL", "")
    postgres_host = os.environ.get("POSTGRES_HOST", "")
    docker_host_configured = postgres_host == "db" or "@db:" in database_url
    use_postgres = os.environ.get("USE_POSTGRES", "false").lower() == "true"
    # Prefer SQLite on the host by default; only use Postgres when explicitly requested.
    use_sqlite = os.environ.get(
        "USE_SQLITE",
        "false" if use_postgres else "true",
    ).lower() == "true"

    if use_sqlite:
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": BASE_DIR / "db.sqlite3",
            }
        }
    elif docker_host_configured:
        if database_url and "@db:" in database_url:
            remapped_url = database_url.replace("@db:", "@localhost:")
            DATABASES = {
                "default": dj_database_url.config(
                    default=remapped_url,
                    conn_max_age=600,
                    conn_health_checks=True,
                )
            }
        elif postgres_host == "db":
            DATABASES["default"]["HOST"] = "localhost"
