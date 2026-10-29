from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from organizations.models import Organization, OrganizationMembership
from .forms import (AdminUserCreateForm, UserLoginForm, UserProfileForm,
                    UserRegistrationForm)
from .models import User


def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            default_org = Organization.objects.filter(slug='default').first() or Organization.objects.first()
            if default_org:
                role = OrganizationMembership.ROLE_ADMIN if user.is_admin_role else OrganizationMembership.ROLE_MEMBER
                OrganizationMembership.objects.get_or_create(
                    organization=default_org,
                    user=user,
                    defaults={'role': role, 'is_active': True}
                )
            login(request, user)
            messages.success(request, f"Welcome to TaskFlow, {user.display_name}! Your account is ready.")
            return redirect('dashboard')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = UserRegistrationForm()

    return render(request, 'accounts/register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = UserLoginForm(request, data=request.POST)
        username_or_email = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        # Check if user entered an email address
        if '@' in username_or_email:
            try:
                user_obj = User.objects.get(email__iexact=username_or_email)
                username_to_auth = user_obj.username
            except User.DoesNotExist:
                username_to_auth = username_or_email
        else:
            username_to_auth = username_or_email

        user = authenticate(request, username=username_to_auth, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, f"Welcome back, {user.display_name}!")
            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('dashboard')
        else:
            messages.error(request, "Invalid username/email or password.")
    else:
        form = UserLoginForm()

    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out securely.")
    return redirect('login')


@login_required
def profile_view(request):
    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect('profile')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = UserProfileForm(instance=request.user)

    user_tasks = request.user.assigned_tasks.all()
    stats = {
        'total': user_tasks.count(),
        'completed': user_tasks.filter(status='COMPLETED').count(),
        'in_progress': user_tasks.filter(status='IN_PROGRESS').count(),
        'todo': user_tasks.filter(status='TODO').count(),
    }

    return render(request, 'accounts/profile.html', {
        'form': form,
        'stats': stats,
    })


@login_required
def user_list_view(request):
    """Admin-only view for user management and workload visibility within active organization."""
    org = getattr(request, 'organization', None)
    membership = getattr(request, 'membership', None)
    is_org_admin = (membership and membership.is_admin) or request.user.is_admin_role
    if not is_org_admin:
        raise PermissionDenied("Only administrators can access team user management.")

    if request.method == 'POST':
        create_form = AdminUserCreateForm(request.POST)
        if create_form.is_valid():
            new_user = create_form.save()
            if org:
                role = OrganizationMembership.ROLE_ADMIN if new_user.is_admin_role else OrganizationMembership.ROLE_MEMBER
                OrganizationMembership.objects.get_or_create(
                    organization=org,
                    user=new_user,
                    defaults={'role': role, 'is_active': new_user.is_active}
                )
            messages.success(request, f"User {new_user.username} created successfully.")
            return redirect('user_management')
        else:
            messages.error(request, "Failed to create user. Please check form errors.")
    else:
        create_form = AdminUserCreateForm()

    task_filter = Q(assigned_tasks__organization=org) if org else Q()
    users_qs = User.objects.all()
    if org:
        users_qs = users_qs.filter(organization_memberships__organization=org)

    users = list(users_qs.annotate(
        total_tasks=Count('assigned_tasks', filter=task_filter),
        todo_tasks=Count('assigned_tasks', filter=task_filter & Q(assigned_tasks__status='TODO')),
        in_progress_tasks=Count('assigned_tasks', filter=task_filter & Q(assigned_tasks__status='IN_PROGRESS')),
        completed_tasks=Count('assigned_tasks', filter=task_filter & Q(assigned_tasks__status='COMPLETED')),
    ).distinct().order_by('role', 'username'))

    if org:
        memberships_by_user = {
            m.user_id: m for m in OrganizationMembership.objects.filter(organization=org, user__in=users)
        }
        for u in users:
            m = memberships_by_user.get(u.id)
            if m:
                u.is_active = m.is_active
                u.role = 'ADMIN' if m.is_admin else 'MEMBER'

    return render(request, 'accounts/user_list.html', {
        'users': users,
        'create_form': create_form,
    })


@login_required
@require_POST
def toggle_user_active_view(request, user_id):
    org = getattr(request, 'organization', None)
    membership = getattr(request, 'membership', None)
    is_org_admin = (membership and membership.is_admin) or request.user.is_admin_role
    if not is_org_admin:
        raise PermissionDenied("Only administrators can manage user status.")

    target_user = get_object_or_404(User, id=user_id)
    if target_user.id == request.user.id:
        messages.warning(request, "You cannot deactivate your own account.")
        return redirect('user_management')

    if org:
        target_membership = OrganizationMembership.objects.filter(organization=org, user=target_user).first()
        if target_membership:
            if target_membership.is_owner and target_membership.is_active:
                active_owners = org.memberships.filter(role=OrganizationMembership.ROLE_OWNER, is_active=True).count()
                if active_owners <= 1:
                    messages.error(request, "Cannot deactivate the last active owner of the organization.")
                    return redirect('user_management')
            target_membership.is_active = not target_membership.is_active
            target_membership.save(update_fields=['is_active', 'updated_at'])

            other_active = target_user.organization_memberships.exclude(organization=org).filter(is_active=True).exists()
            if not other_active:
                target_user.is_active = target_membership.is_active
                target_user.save(update_fields=['is_active'])

            status_str = "activated" if target_membership.is_active else "deactivated"
            messages.success(request, f"User {target_user.username} has been {status_str}.")
            return redirect('user_management')

    target_user.is_active = not target_user.is_active
    target_user.save()
    status_str = "activated" if target_user.is_active else "deactivated"
    messages.success(request, f"User {target_user.username} has been {status_str}.")
    return redirect('user_management')




