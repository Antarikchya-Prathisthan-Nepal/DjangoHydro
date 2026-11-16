"""
Production settings for Hydro_WebPortal project on cPanel
"""
import os
from pathlib import Path
import environ

# Initialize environment variables
env = environ.Env()
# .env.production lives one level above Hydro_WebPortal/ (i.e. ~/hydro/)
env_file = Path(__file__).resolve().parent.parent.parent / '.env.production'
if env_file.exists():
    environ.Env.read_env(str(env_file))
else:
    # Fallback: also check inside Hydro_WebPortal/ for local dev copies
    fallback = Path(__file__).resolve().parent.parent / '.env.production'
    if fallback.exists():
        environ.Env.read_env(str(fallback))

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

_allowed = env('ALLOWED_HOSTS', default='127.0.0.1,localhost')
ALLOWED_HOSTS = [h.strip() for h in _allowed.split(',') if h.strip()]

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.gis',  # For GeoDjango support
    'rest_framework',  # Django REST Framework
    'users',  # Custom user app
    'delineation',
    'discharge_prediction',
    'watershed_report',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # For static files
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'Hydro_WebPortal.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.csrf',
            ],
        },
    },
]

WSGI_APPLICATION = 'Hydro_WebPortal.wsgi.application'

# Database configuration for production
DATABASES = {
    'default': {
        'ENGINE': 'django.contrib.gis.db.backends.postgis',
        'NAME': env('DB_NAME'),
        'USER': env('DB_USER'),
        'PASSWORD': env('DB_PASSWORD'),
        'HOST': env('DB_HOST', default='localhost'),
        'PORT': env('DB_PORT', default='5432'),
    }
    # Uncomment and configure if you need a MySQL database as well
    # 'mysql_db': {
    #     'ENGINE': 'django.db.backends.mysql',
    #     'NAME': env('MYSQL_DB_NAME', default=''),
    #     'USER': env('MYSQL_DB_USER', default=''),
    #     'PASSWORD': env('MYSQL_DB_PASSWORD', default=''),
    #     'HOST': env('MYSQL_DB_HOST', default='localhost'),
    #     'PORT': env('MYSQL_DB_PORT', default='3306'),
    # }
}

# Uncomment if using multiple databases with the custom router
# DATABASE_ROUTERS = ['Hydro_WebPortal.routers.DatabaseRouter']

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# GDAL and GEOS settings - these paths will need to be updated for cPanel
GDAL_LIBRARY_PATH = env('GDAL_LIBRARY_PATH', default=None)
GEOS_LIBRARY_PATH = env('GEOS_LIBRARY_PATH', default=None)

# Static files configuration
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Media files configuration
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Data paths
DATA_ROOT = BASE_DIR / 'data'
RASTER_DATA_PATH = DATA_ROOT / 'raster'
SHAPE_DATA_PATH = DATA_ROOT / 'shp'
MERIT_CATCHMENTS_PATH = SHAPE_DATA_PATH / 'merit_catchments' / 'cat_pfaf_45_MERIT_Hydro_v07_Basins_v01.shp'
MERIT_RIVERS_PATH = SHAPE_DATA_PATH / 'merit_rivers' / 'riv_pfaf_45_MERIT_Hydro_v07_Basins_v01.shp'
BASINS_LEVEL2_PATH = SHAPE_DATA_PATH / 'basins_level2' / 'merit_hydro_vect_level2.shp'
CATCHMENTS_SIMPLIFIED_PATH = SHAPE_DATA_PATH / 'catchments_simplified' / 'cat_pfaf_45_MERIT_Hydro_v07_Basins_v01.shp'

# MERIT-Hydro processing settings
HIGH_RES = True
THRESHOLD_SINGLE = 500
THRESHOLD_MULTIPLE = 5000
FILL = True
FILL_THRESHOLD = 100
PIXEL_AREA = 0.000000695
SIMPLIFY = False
SIMPLIFY_TOLERANCE = 0.0008
SEARCH_DIST = 0.025
LOW_RES_THRESHOLD = 50000
MAP_RIVERS = True
NUM_STREAM_ORDERS = 3
VERBOSE = True

# Session settings
SESSION_COOKIE_AGE = 3600  # 1 hour
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_SECURE = True  # Enforce HTTPS for sessions

# Security settings
CSRF_COOKIE_SECURE = True  # Enforce HTTPS for CSRF
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'
_csrf_origins = env('CSRF_TRUSTED_ORIGINS', default='http://127.0.0.1')
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_origins.split(',') if o.strip()]

# Custom user model
AUTH_USER_MODEL = 'users.User'

# Authentication settings
LOGIN_REDIRECT_URL = 'discharge_prediction:dashboard'
LOGIN_URL = 'users:login'
LOGOUT_REDIRECT_URL = 'home'

# Email settings
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = env('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = env('EMAIL_PORT', default=587)
EMAIL_USE_TLS = True
EMAIL_HOST_USER = env('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL')

# Password reset timeout (24 hours)
PASSWORD_RESET_TIMEOUT = 24 * 3600

# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'django_production.log'),
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': True,
        },
        'delineation': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': True,
        },
        'discharge_prediction': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}

# ERA5 Configuration
ERA5_API_KEY = env('CDS_API_KEY', default=None)

# GST (Ground Station Telemetry) receiver configuration
GST_USERNAME = env('GST_USERNAME', default='')
GST_PASSWORD = env('GST_PASSWORD', default='')
GST_SEA_LEVEL_X = float(env('GST_SEA_LEVEL_X', default='835'))
GST_SEA_LEVEL_CONSTANT = float(env('GST_SEA_LEVEL_CONSTANT', default='205300'))
GST_FILTER_THRESHOLD = float(env('GST_FILTER_THRESHOLD', default='5'))
GST_FILTER_INITIAL_DEPTH = float(env('GST_FILTER_INITIAL_DEPTH', default='265'))
# Additional security settings for production
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_SSL_REDIRECT = True
# Nginx terminates SSL and forwards via X-Forwarded-Proto
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'