from .base import *

DEBUG = False

# Strict production security settings
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'True').lower() == 'true'
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Production database standard setup
import dj_database_url
if os.environ.get('DATABASE_URL'):
    conn_max_age = int(os.environ.get('DB_CONN_MAX_AGE', os.environ.get('CONN_MAX_AGE', 60)))
    DATABASES['default'] = dj_database_url.config(
        conn_max_age=conn_max_age,
        conn_health_checks=True,
        ssl_require=False,
    )
    if os.environ.get('DISABLE_SERVER_SIDE_CURSORS', '').lower() == 'true':
        DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True


