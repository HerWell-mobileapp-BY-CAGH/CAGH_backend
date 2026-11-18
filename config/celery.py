import os
from celery import Celery
from celery.signals import task_prerun, task_postrun
from django.db import close_old_connections

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')

app = Celery('cagh_backend')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()


@task_prerun.connect
def close_db_connection_before_task(*args, **kwargs):
    """Ensure dead or stale connections are closed before executing a Celery task."""
    close_old_connections()


@task_postrun.connect
def close_db_connection_after_task(*args, **kwargs):
    """
    Release database connection immediately after Celery task execution.
    Prevents background worker processes from holding persistent, idle connections
    in Supabase poolers.
    """
    close_old_connections()
