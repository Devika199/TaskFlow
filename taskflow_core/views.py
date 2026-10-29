import logging
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@require_GET
def health_check_view(request):
    """
    Unauthenticated health check endpoint for monitoring systems, load balancers,
    and container orchestrators.
    
    Verifies that the active database connection is functional.
    Returns:
        HTTP 200: {"status": "healthy", "database": "connected"}
        HTTP 503: {"status": "unhealthy", "database": "disconnected"}
    """
    try:
        connection.ensure_connection()
        return JsonResponse(
            {
                "status": "healthy",
                "database": "connected",
            },
            status=200,
        )
    except Exception as exc:
        logger.error("Health check failed - database unavailable: %s", exc)
        return JsonResponse(
            {
                "status": "unhealthy",
                "database": "disconnected",
            },
            status=503,
        )

