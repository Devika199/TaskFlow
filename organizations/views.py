from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Organization, OrganizationMembership
from .services import (
    LastOwnerError,
    MembershipError,
    OrganizationPermissionError,
    RoleEscalationError,
    add_user_to_organization,
    get_active_membership,
    remove_member_from_organization,
    toggle_membership_active,
    transfer_organization_ownership,
    update_membership_role,
)

User = get_user_model()


@login_required
@require_POST
def switch_organization_view(request, org_id):
    """Switch the current active organization session for the logged-in user."""
    target_org = get_object_or_404(Organization, id=org_id, is_active=True)
    membership = get_active_membership(request.user, target_org)

    if not membership:
        raise PermissionDenied("You do not have access to that organization.")

    request.session['active_organization_id'] = target_org.id
    messages.success(request, f"Switched to workspace '{target_org.name}'.")

    next_url = request.POST.get('next') or request.GET.get('next') or 'dashboard'
    return redirect(next_url)


@login_required
def organization_settings_view(request):
    """View and update organization settings (Owner only)."""
    org = getattr(request, 'organization', None)
    membership = getattr(request, 'membership', None)

    if not org or not membership:
        messages.error(request, "No active organization selected.")
        return redirect('dashboard')

    if not membership.is_owner:
        raise PermissionDenied("Only the organization owner can manage workspace settings.")

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if name:
            org.name = name
            org.save(update_fields=['name', 'updated_at'])
            messages.success(request, "Workspace name updated.")
            return redirect('organization_settings')
        else:
            messages.error(request, "Workspace name cannot be empty.")

    return render(request, 'organizations/settings.html', {
        'organization': org,
        'membership': membership,
    })

