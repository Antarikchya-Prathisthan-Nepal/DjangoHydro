from django.urls import path
from . import views

app_name = 'watershed_report'

urlpatterns = [
    path('',                                    views.index,         name='index'),
    path('analyze/',                            views.analyze,       name='analyze'),
    path('save/',                               views.save_report,   name='save_report'),
    path('history/',                            views.history,       name='history'),
    path('report/<int:report_id>/',             views.report_detail, name='report_detail'),
    path('report/<int:report_id>/rename/',      views.report_rename, name='report_rename'),
    path('report/<int:report_id>/delete/',      views.report_delete, name='report_delete'),
    path('report/<int:report_id>/download/',    views.report_print,  name='report_print'),
]
