from django.core.management.base import BaseCommand
import importlib
import traceback

# Try import in both common locations so the command works whether
# manage.py's cwd is the project package dir or its parent.
run_main = None
_import_err = None
for _mod in (
    'automate_sequences_and_predictions',
    'Hydro_WebPortal.automate_sequences_and_predictions',
):
    try:
        mod = importlib.import_module(_mod)
        run_main = getattr(mod, 'main')
        break
    except Exception:
        _import_err = traceback.format_exc()


class Command(BaseCommand):
    help = "Run automated forecast sequence creation & predictions."

    def handle(self, *args, **options):
        if run_main is None:
            self.stderr.write("Failed to import automate_sequences_and_predictions module:\n")
            if _import_err:
                self.stderr.write(_import_err)
            else:
                self.stderr.write('Unknown import error')
            return
        # Call the main function
        run_main()
