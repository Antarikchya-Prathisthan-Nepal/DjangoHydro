import json
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.urls import reverse
from django.db.models import Q
from django.views.decorators.csrf import csrf_protect, csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.hashers import make_password
from .forms import UserRegistrationForm, UserProfileForm, CustomLoginForm, FreeRegistrationForm
from .models import User, StationAccess, PendingRegistration, AccessRequest

logger = logging.getLogger(__name__)
from discharge_prediction.models import DischargeStation


def _send_verification_email(request, email, first_name, token):
    """Send a pre-registration verification link to the prospective user."""
    verify_url = request.build_absolute_uri(
        reverse('users:verify_email', kwargs={'token': str(token)})
    )
    subject = 'Verify your Hydro Portal email address'
    message = (
        f"Hello {first_name or email},\n\n"
        f"Thank you for registering with the Hydro WebPortal.\n\n"
        f"Please click the link below to verify your email and complete your registration:\n"
        f"{verify_url}\n\n"
        f"This link will expire in 24 hours. If you did not request this, please ignore this email.\n\n"
        f"Best regards,\nHydro WebPortal Team"
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False)


@csrf_protect
def user_login(request):
    """View for user login"""
    # Check if user has just logged out, but only for initial page loads, not for form submissions
    logged_out = False
    if request.method == 'GET' and 'logged_out_successfully' in request.session:
        logged_out = request.session.pop('logged_out_successfully', False)
    
    if request.method == 'POST':
        form = CustomLoginForm(request, data=request.POST)
        if form.is_valid():
            email = form.cleaned_data.get('username')  # In AuthenticationForm, username field is used for email
            password = form.cleaned_data.get('password')
            remember_me = request.POST.get('remember', False)
            user = authenticate(request, username=email, password=password)
            
            if user is not None and user.is_approved:
                login(request, user)
                
                # Set session expiry based on remember_me
                if not remember_me:
                    # Session expires when browser is closed
                    request.session.set_expiry(0)
                # If remember_me is True, Django will use the default session expiry (2 weeks)
                
                # Free-tier users land on home; full-tier users land on dashboard
                if user.account_tier == 'free':
                    default_next = reverse('home')
                else:
                    default_next = reverse('discharge_prediction:dashboard')
                next_url = request.GET.get('next', default_next)
                return redirect(next_url)
            else:
                messages.error(request, 'Login failed. Please check your credentials or account approval status.')
    else:
        form = CustomLoginForm()
    
    return render(request, 'users/login.html', {'form': form, 'logged_out': logged_out})


def user_logout(request):
    """View for user logout"""
    logout(request)
    
    # Store logout success in session instead of using messages framework
    # This prevents the message from showing up on login form
    request.session['logged_out_successfully'] = True
    
    return redirect('home')


@csrf_protect
def register(request):
    """Full-tier registration — organisation, phone, station, and admin approval required."""
    if request.user.is_authenticated:
        return redirect('discharge_prediction:dashboard')

    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            first_name = form.cleaned_data['first_name']

            # Replace any existing pending registration for this email
            PendingRegistration.objects.filter(email=email).delete()

            pending = PendingRegistration.objects.create(
                email=email,
                first_name=first_name,
                last_name=form.cleaned_data['last_name'],
                organization=form.cleaned_data['organization'],
                phone_number=form.cleaned_data.get('phone_number', ''),
                station=form.cleaned_data['station'],
                password_hash=make_password(form.cleaned_data['password1']),
            )
            try:
                _send_verification_email(request, email, first_name, pending.token)
                messages.success(
                    request,
                    f'A verification email has been sent to {email}. '
                    'Please click the link in the email to complete your registration. '
                    'The link expires in 24 hours.'
                )
            except Exception:
                pending.delete()
                messages.error(
                    request,
                    'Could not send the verification email. Please try again or contact the administrator.'
                )
            return redirect('users:login')
    else:
        form = UserRegistrationForm()
    return render(request, 'users/register.html', {'form': form})


@csrf_protect
@ensure_csrf_cookie
def register_free(request):
    """Free-tier registration — name, email, and password only.

    No admin approval required.  The account is activated automatically when
    the user clicks the verification link in the email.  Free-tier users can
    download delineation GeoJSON files and watershed analysis reports.
    """
    if request.user.is_authenticated:
        return redirect(request.GET.get('next', reverse('home')))

    next_url = request.GET.get('next', '')

    if request.method == 'POST':
        # `next` may come from the POST body (hidden field) or from the query string.
        next_url = request.POST.get('next', request.GET.get('next', ''))
        form = FreeRegistrationForm(request.POST)
        if form.is_valid():
            email      = form.cleaned_data['email']
            first_name = form.cleaned_data['first_name']

            # Replace any stale pending registration for this email
            PendingRegistration.objects.filter(email=email).delete()

            pending = PendingRegistration.objects.create(
                email=email,
                first_name=first_name,
                last_name=form.cleaned_data['last_name'],
                organization='',
                phone_number='',
                station=None,
                password_hash=make_password(form.cleaned_data['password1']),
                tier='free',
            )
            try:
                _send_verification_email(request, email, first_name, pending.token)
                messages.success(
                    request,
                    f'A verification email has been sent to {email}. '
                    'Click the link in the email to activate your account — it expires in 24 hours.',
                )
            except Exception as exc:
                logger.exception('Failed to send verification email to %s', email)
                messages.error(
                    request,
                    'Your account has been created but we could not send the verification email '
                    f'({type(exc).__name__}: {exc}). '
                    'Please contact the administrator or try registering again.',
                )
            return redirect(
                reverse('users:login') + ('?next=' + next_url if next_url else '')
            )
    else:
        form = FreeRegistrationForm()

    return render(request, 'users/register_free.html', {'form': form, 'next': next_url})


@login_required
def profile(request):
    """View for user profile management"""
    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile has been updated successfully.')
            return redirect('users:profile')
    else:
        form = UserProfileForm(instance=request.user)
    
    # Get stations user has access to
    user_stations = DischargeStation.objects.filter(
        user_accesses__user=request.user
    ).order_by('name')
    
    context = {
        'form': form,
        'user_stations': user_stations
    }
    
    return render(request, 'users/profile.html', context)


@login_required
def my_stations(request):
    """View for displaying all stations the user has access to"""
    # If user is admin, show all stations
    if request.user.is_superuser or request.user.is_staff:
        stations = DischargeStation.objects.all().order_by('name')
    else:
        # Otherwise show only stations with access
        stations = DischargeStation.objects.filter(
            user_accesses__user=request.user
        ).order_by('name')
    
    context = {
        'stations': stations
    }
    
    return render(request, 'users/my_stations.html', context)


def verify_email(request, token):
    """Complete registration after the user clicks the email verification link."""
    try:
        pending = PendingRegistration.objects.select_related('station').get(token=token)
    except PendingRegistration.DoesNotExist:
        return render(request, 'users/email_verification_invalid.html',
                      {'reason': 'The verification link is invalid.'})

    if not pending.is_valid():
        pending.delete()
        return render(request, 'users/email_verification_invalid.html',
                      {'reason': 'The verification link has expired (24 hours). Please register again.'})

    # Guard against duplicate emails (edge case: registered via another path)
    if User.objects.filter(email=pending.email).exists():
        pending.delete()
        messages.info(request, 'This email is already registered. Please log in.')
        return redirect('users:login')

    # Create the verified user account
    user = User(
        email=pending.email,
        first_name=pending.first_name,
        last_name=pending.last_name,
        organization=pending.organization,
        phone_number=pending.phone_number,
        account_tier=pending.tier,
        is_approved=(pending.tier == 'free'),   # free tier: auto-approved
        email_verified=True,
    )
    user.password = pending.password_hash   # already hashed by make_password
    user.save()

    # Station access is only relevant for full-tier users
    if pending.tier == 'full' and pending.station:
        StationAccess.objects.create(
            user=user,
            station=pending.station,
            access_level='viewer',
            granted_by=None,
        )
    pending.delete()

    return render(request, 'users/email_verified.html', {'user': user})


@require_GET
def auth_status(request):
    """Return current authentication state as JSON (used by AJAX download gates)."""
    return JsonResponse({
        'authenticated': request.user.is_authenticated,
        'email': request.user.email if request.user.is_authenticated else None,
        'account_tier': request.user.account_tier if request.user.is_authenticated else None,
    })


@csrf_protect
@require_POST
def ajax_login(request):
    """AJAX login — accepts JSON {email, password}, returns JSON, no redirect.

    Used by the auth modal on public pages so users can log in without
    leaving the page (e.g. to download a watershed report or GeoJSON).
    """
    try:
        body     = json.loads(request.body)
        email    = body.get('email', '').strip()
        password = body.get('password', '')
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)

    form = CustomLoginForm(request, data={'username': email, 'password': password})
    if form.is_valid():
        user = form.get_user()
        login(request, user)
        return JsonResponse({
            'success':      True,
            'email':        user.email,
            'full_name':    user.get_full_name(),
            'is_staff':     user.is_staff,
            'account_tier': user.account_tier,
        })

    errors = form.errors.get('__all__') or form.errors.get('password') or ['Invalid credentials.']
    return JsonResponse({'success': False, 'error': str(errors[0])}, status=401)


@login_required
@require_POST
@csrf_protect
def request_access(request):
    """AJAX endpoint: submit a full-tier access request.

    A free-tier (or no-station full-tier) user can explain why they need access.
    The request is stored and an email notification is sent to the admin.
    Returns JSON so the glass-card modal on access_denied.html can show inline feedback.
    """
    user = request.user

    # Prevent duplicate pending requests
    if AccessRequest.objects.filter(user=user, status=AccessRequest.STATUS_PENDING).exists():
        return JsonResponse(
            {'success': False, 'error': 'You already have a pending access request.'},
            status=400,
        )

    organization   = request.POST.get('organization', '').strip()[:255]
    contact_number = request.POST.get('contact_number', '').strip()[:20]
    message        = request.POST.get('message', '').strip()[:2000]
    station_id     = request.POST.get('station', '').strip()

    # Server-side validation for required fields
    errors = {}
    if not organization:
        errors['organization'] = 'Organization is required.'
    if not contact_number:
        errors['contact_number'] = 'Contact number is required.'
    if not message:
        errors['message'] = 'Please describe why you need access.'
    if not station_id:
        errors['station'] = 'Please select a station.'
    if errors:
        return JsonResponse({'success': False, 'errors': errors,
                             'error': 'Please fill in all required fields.'}, status=400)

    station = DischargeStation.objects.filter(pk=station_id, is_active=True).first()
    if not station:
        return JsonResponse({'success': False, 'error': 'Selected station not found.'}, status=400)

    access_req = AccessRequest.objects.create(
        user=user,
        organization=organization,
        contact_number=contact_number,
        message=message,
        station=station,
    )

    # Email notification to admin (best-effort — never fail the request if email fails)
    try:
        from django.conf import settings as django_settings
        admin_email = django_settings.EMAIL_HOST_USER or django_settings.DEFAULT_FROM_EMAIL
        subject = f'[Hydro Portal] New access request from {user.email}'
        body = (
            f"A user has submitted an access request.\n\n"
            f"User         : {user.get_full_name() or user.email} ({user.email})\n"
            f"Organisation : {organization}\n"
            f"Contact      : {contact_number}\n"
            f"Tier         : {user.account_tier}\n"
            f"Station      : {station.name}\n"
            f"Message      :\n{message}\n\n"
            f"Review it in the admin panel:\n"
            f"{request.build_absolute_uri('/admin/users/accessrequest/')}"
        )
        from django.core.mail import send_mail
        send_mail(subject, body, django_settings.DEFAULT_FROM_EMAIL, [admin_email], fail_silently=True)
    except Exception:
        pass  # non-blocking

    return JsonResponse({'success': True, 'request_id': access_req.pk})
