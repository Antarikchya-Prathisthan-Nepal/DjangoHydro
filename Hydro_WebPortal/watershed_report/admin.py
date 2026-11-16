from django.contrib import admin

from .models import WatershedReport


@admin.register(WatershedReport)
class WatershedReportAdmin(admin.ModelAdmin):
    list_display  = ('id', 'display_name', 'user', 'area_km2', 'created_at')
    list_filter   = ('created_at', 'user')
    search_fields = ('name', 'user__email')
    ordering      = ('-created_at',)
    readonly_fields = ('geometry', 'results', 'area_km2', 'created_at')

    fieldsets = (
        (None, {
            'fields': ('user', 'name', 'area_km2', 'created_at'),
        }),
        ('Stored Data', {
            'fields': ('geometry', 'results'),
            'classes': ('collapse',),
        }),
    )
