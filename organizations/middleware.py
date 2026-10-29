from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin
from .models import Organization, OrganizationMembership


def resolve_request_organization(request, user=None):
    """
    Resolves and validates the active organization for the given request and user.
    Enforces active membership.
    Returns tuple: (organization, membership, is_unauthorized_explicit).
    """
    if user is None:
        user = getattr(request, '_force_auth_user', None) or getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return None, None, False

    header_org_id = request.headers.get('X-Organization-ID')
    header_org_slug = request.headers.get('X-Organization-Slug')
    query_org = request.GET.get('org')
    session = getattr(request, 'session', {})
    session_org_id = session.get('active_organization_id') if hasattr(session, 'get') else None

    requested_org_id = None
    requested_org_slug = None
    is_explicit_request = False

    if header_org_id:
        try:
            requested_org_id = int(header_org_id)
            is_explicit_request = True
        except (ValueError, TypeError):
            pass
    elif header_org_slug:
        requested_org_slug = header_org_slug.strip()
        is_explicit_request = True
    elif query_org:
        if query_org.isdigit():
            requested_org_id = int(query_org)
        else:
            requested_org_slug = query_org.strip()
        is_explicit_request = True
    elif session_org_id:
        try:
            requested_org_id = int(session_org_id)
        except (ValueError, TypeError):
            pass

    active_memberships = OrganizationMembership.objects.filter(
        user=user,
        is_active=True,
        organization__is_active=True,
    ).select_related('organization')

    membership = None
    if requested_org_id is not None:
        membership = active_memberships.filter(organization_id=requested_org_id).first()
    elif requested_org_slug:
        membership = active_memberships.filter(organization__slug=requested_org_slug).first()

    is_unauthorized_explicit = is_explicit_request and (membership is None)

    if not membership:
        membership = active_memberships.first()

    org = membership.organization if membership else None
    return org, membership, is_unauthorized_explicit


class TenantMiddleware(MiddlewareMixin):
    """
    Resolves and validates the active organization for authenticated requests.
    Enforces that users can only access organizations where they have an active membership.
    Attaches `request.organization` and `request.membership`.
    """

    def process_request(self, request):
        request.organization = None
        request.membership = None

        user = getattr(request, '_force_auth_user', None) or getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return None

        org, membership, is_unauthorized_explicit = resolve_request_organization(request, user)

        if is_unauthorized_explicit:
            if request.path.startswith('/api/'):
                return JsonResponse(
                    {'detail': 'You do not have access to the requested organization.'},
                    status=403,
                )

        if membership:
            request.organization = membership.organization
            request.membership = membership
            if hasattr(request, 'session') and request.session.get('active_organization_id') != membership.organization_id:
                request.session['active_organization_id'] = membership.organization_id

        return None
