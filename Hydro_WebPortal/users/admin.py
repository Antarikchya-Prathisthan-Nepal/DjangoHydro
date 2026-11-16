from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from .models import User, StationAccess, PendingRegistration, EmailVerificationToken, AccessRequest
from discharge_prediction.models import DischargeStation


class StationAccessInline(admin.TabularInline):
    model = StationAccess
    extra = 1
    fk_name = 'user'


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Define admin model for custom User model with email as the username field."""

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Personal info'), {'fields': ('first_name', 'last_name', 'organization', 'phone_number')}),
        (_('Account'), {'fields': ('account_tier', 'email_verified', 'is_approved')}),
        (_('Permissions'), {'fields': ('is_active', 'is_staff', 'is_superuser',
                                       'groups', 'user_permissions')}),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'account_tier', 'is_approved'),
        }),
    )
    list_display = ('email', 'first_name', 'last_name', 'organization',
                    'account_tier', 'email_verified', 'is_approved', 'is_staff', 'date_joined')
    list_filter = ('account_tier', 'is_approved', 'email_verified', 'is_staff', 'is_active')
    search_fields = ('email', 'first_name', 'last_name', 'organization')
    ordering = ('-date_joined',)
    inlines = [StationAccessInline]
    actions = ['approve_users', 'unapprove_users', 'set_tier_free', 'set_tier_full']

    def approve_users(self, request, queryset):
        queryset.update(is_approved=True)
    approve_users.short_description = "Approve selected users"

    def unapprove_users(self, request, queryset):
        queryset.update(is_approved=False)
    unapprove_users.short_description = "Revoke approval for selected users"

    def set_tier_free(self, request, queryset):
        queryset.update(account_tier='free')
    set_tier_free.short_description = "Set account tier → Free"

    def set_tier_full(self, request, queryset):
        queryset.update(account_tier='full')
    set_tier_full.short_description = "Set account tier → Full"


@admin.register(StationAccess)
class StationAccessAdmin(admin.ModelAdmin):
    list_display = ('user', 'station', 'access_level', 'granted_at', 'granted_by')
    list_filter = ('access_level', 'station')
    search_fields = ('user__email', 'station__name')
    raw_id_fields = ('user', 'station', 'granted_by')


@admin.register(PendingRegistration)
class PendingRegistrationAdmin(admin.ModelAdmin):
    list_display = ('email', 'first_name', 'last_name', 'tier', 'station', 'created_at', 'is_valid')
    list_filter = ('tier',)
    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('-created_at',)
    readonly_fields = ('token', 'password_hash', 'created_at')
    fields = ('email', 'first_name', 'last_name', 'organization',
              'phone_number', 'tier', 'station', 'token', 'password_hash', 'created_at')

    def is_valid(self, obj):
        return obj.is_valid()
    is_valid.boolean = True
    is_valid.short_description = 'Link valid?'


@admin.register(EmailVerificationToken)
class EmailVerificationTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'token', 'created_at', 'is_valid')
    search_fields = ('user__email',)
    ordering = ('-created_at',)
    readonly_fields = ('token', 'created_at')

    def is_valid(self, obj):
        return obj.is_valid()
    is_valid.boolean = True
    is_valid.short_description = 'Token valid?'


@admin.register(AccessRequest)
class AccessRequestAdmin(admin.ModelAdmin):
    list_display  = ('user', 'user_tier', 'organization', 'contact_number', 'station', 'status', 'created_at', 'reviewed_by')
    list_filter   = ('status',)
    search_fields = ('user__email', 'user__first_name', 'user__last_name', 'organization', 'message')
    ordering      = ('-created_at',)
    readonly_fields = ('user', 'organization', 'contact_number', 'message', 'station', 'created_at')
    fields = ('user', 'organization', 'contact_number', 'station', 'message',
              'status', 'admin_note', 'reviewed_by', 'reviewed_at', 'created_at')
    actions = ['approve_and_grant_full', 'reject_requests']

    def user_tier(self, obj):
        return obj.user.account_tier
    user_tier.short_description = 'Current tier'

    def approve_and_grant_full(self, request, queryset):
        """Approve selected requests: upgrade user to full-tier, mark approved, create StationAccess."""
        approved = 0
        for ar in queryset.filter(status=AccessRequest.STATUS_PENDING):
            user = ar.user
            user.account_tier = 'full'
            user.is_approved = True
            user.save(update_fields=['account_tier', 'is_approved'])
            if ar.station:
                StationAccess.objects.get_or_create(
                    user=user, station=ar.station,
                    defaults={'access_level': 'viewer', 'granted_by': request.user},
                )
            ar.status      = AccessRequest.STATUS_APPROVED
            ar.reviewed_by = request.user
            ar.reviewed_at = timezone.now()
            ar.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
            approved += 1
        self.message_user(request, f'{approved} request(s) approved and users upgraded to Full tier.')
    approve_and_grant_full.short_description = 'Approve: upgrade to Full tier + grant station access'

    def reject_requests(self, request, queryset):
        updated = queryset.filter(status=AccessRequest.STATUS_PENDING).update(
            status=AccessRequest.STATUS_REJECTED,
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
        )
        self.message_user(request, f'{updated} request(s) rejected.')
    reject_requests.short_description = 'Reject selected requests'
