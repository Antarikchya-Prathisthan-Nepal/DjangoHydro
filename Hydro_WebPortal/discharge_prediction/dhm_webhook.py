"""
Webhook view for triggering the DHM discharge fetch management command.

Called by the GitHub Actions workflow daily_fetch.yml.
Authentication is via a Bearer token stored in settings.DHM_WEBHOOK_TOKEN.
The command is run synchronously in a background thread so the HTTP 202
response is returned immediately to the caller.
"""

import logging
import threading

from django.conf import settings
from django.core.management import call_command
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


def _verify_token(request) -> bool:
    """Validate the Bearer token from the Authorization header."""
    expected = getattr(settings, "DHM_WEBHOOK_TOKEN", None)
    if not expected:
        logger.error("DHM_WEBHOOK_TOKEN is not configured in settings.")
        return False
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("Bearer "):
        return False
    incoming = auth_header[len("Bearer "):]
    # Constant-time comparison to prevent timing attacks
    import hmac
    return hmac.compare_digest(incoming.strip(), expected.strip())


def _run_fetch():
    """Run the management command in a background thread."""
    try:
        logger.info("DHM webhook: starting fetch_dhm_discharge command")
        call_command("fetch_dhm_discharge")
        logger.info("DHM webhook: fetch_dhm_discharge completed successfully")
    except Exception as exc:
        logger.error("DHM webhook: fetch_dhm_discharge failed: %s", exc, exc_info=True)


@csrf_exempt
@require_POST
def dhm_fetch_trigger(request):
    """
    POST /api/dhm/trigger/

    Triggers the DHM daily discharge scrape.
    Returns 202 Accepted immediately; the fetch runs in a background thread.
    """
    if not _verify_token(request):
        logger.warning(
            "DHM webhook: unauthorized request from %s",
            request.META.get("REMOTE_ADDR"),
        )
        return JsonResponse({"error": "Unauthorized"}, status=401)

    thread = threading.Thread(target=_run_fetch, daemon=True)
    thread.start()

    logger.info(
        "DHM webhook: fetch_dhm_discharge enqueued (from %s)",
        request.META.get("REMOTE_ADDR"),
    )
    return JsonResponse({"status": "accepted", "message": "DHM fetch started"}, status=202)
