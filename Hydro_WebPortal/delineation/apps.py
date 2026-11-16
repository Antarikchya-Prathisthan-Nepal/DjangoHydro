from django.apps import AppConfig
import os   #
import sys  #
import threading    #
import logging      #


logger = logging.getLogger(__name__)    #


class DelineationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'delineation'
    ##
    _warmup_started = False

    def ready(self):
        if DelineationConfig._warmup_started:
            return

        # For manage.py commands, warmup is useful only for runserver.
        if len(sys.argv) > 1 and sys.argv[0].endswith('manage.py') and sys.argv[1] != 'runserver':
            return

        # Django runserver spawns a parent/child process in debug; warm only in child.
        if os.environ.get('RUN_MAIN') not in (None, 'true'):
            return

        from .utils import get_startup_warmup_config, warmup_delineation_cache

        config = get_startup_warmup_config()
        if not config['enabled']:
            logger.info('Delineation startup warmup is disabled.')
            return

        DelineationConfig._warmup_started = True

        def _run_warmup():
            warmup_delineation_cache(
                preload_basins=config['preload_basins'],
                preload_all=config['preload_all'],
            )

        thread = threading.Thread(target=_run_warmup, name='delineation-warmup', daemon=True)
        thread.start()
##