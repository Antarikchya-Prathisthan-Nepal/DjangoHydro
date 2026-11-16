from django.apps import AppConfig


class DischargePredictionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'discharge_prediction'
    
    def ready(self):
        """Import signals when Django starts"""
        import discharge_prediction.signals
