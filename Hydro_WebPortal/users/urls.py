from django.urls import path
from . import views
from django.contrib.auth import views as auth_views
from .forms import CustomLoginForm

app_name = 'users'  # Define app_name for namespace

urlpatterns = [
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),
    path('register/', views.register, name='register'),
    path('register-free/', views.register_free, name='register_free'),
    path('profile/', views.profile, name='profile'),
    path('my-stations/', views.my_stations, name='my_stations'),
    path('verify-email/<uuid:token>/', views.verify_email, name='verify_email'),
    path('auth-status/',               views.auth_status,  name='auth_status'),
    path('ajax-login/',                views.ajax_login,   name='ajax_login'),
    path('request-access/',            views.request_access, name='request_access'),

    # Password reset views
    path('password-reset/', 
         auth_views.PasswordResetView.as_view(
             template_name='users/password_reset.html',
             email_template_name='users/password_reset_email.html',
             subject_template_name='users/password_reset_subject.txt',
             html_email_template_name=None,  # Disable HTML email
             success_url='/users/password-reset/done/'
         ), 
         name='password_reset'),
    path('password-reset/done/', 
         auth_views.PasswordResetDoneView.as_view(
             template_name='users/password_reset_done.html'
         ), 
         name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', 
         auth_views.PasswordResetConfirmView.as_view(
             template_name='users/password_reset_confirm.html',
             success_url='/users/password-reset-complete/'
         ), 
         name='password_reset_confirm'),
    path('password-reset-complete/', 
         auth_views.PasswordResetCompleteView.as_view(
             template_name='users/password_reset_complete.html'
         ), 
         name='password_reset_complete'),
]
