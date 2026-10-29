def organization_context(request):
    """Provide organization and membership details to template context."""
    if hasattr(request, 'user') and request.user.is_authenticated:
        active_org = getattr(request, 'organization', None)
        active_membership = getattr(request, 'membership', None)
        user_memberships = request.user.organization_memberships.filter(
            is_active=True,
            organization__is_active=True,
        ).select_related('organization')

        return {
            'active_organization': active_org,
            'active_membership': active_membership,
            'user_organizations': [m.organization for m in user_memberships],
            'user_memberships': user_memberships,
        }

    return {
        'active_organization': None,
        'active_membership': None,
        'user_organizations': [],
        'user_memberships': [],
    }

