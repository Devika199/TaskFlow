from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

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
    """Admin-only view for user management and workload visibility."""
    if not request.user.is_admin_role:
        raise PermissionDenied("Only administrators can access team user management.")

    if request.method == 'POST':
        create_form = AdminUserCreateForm(request.POST)
        if create_form.is_valid():
            new_user = create_form.save()
            messages.success(request, f"User {new_user.username} created successfully.")
            return redirect('user_management')
        else:
            messages.error(request, "Failed to create user. Please check form errors.")
    else:
        create_form = AdminUserCreateForm()

    users = User.objects.annotate(
        total_tasks=Count('assigned_tasks'),
        todo_tasks=Count('assigned_tasks', filter=Q(assigned_tasks__status='TODO')),
        in_progress_tasks=Count('assigned_tasks', filter=Q(assigned_tasks__status='IN_PROGRESS')),
        completed_tasks=Count('assigned_tasks', filter=Q(assigned_tasks__status='COMPLETED')),
    ).order_by('role', 'username')

    return render(request, 'accounts/user_list.html', {
        'users': users,
        'create_form': create_form,
    })


@login_required
def toggle_user_active_view(request, user_id):
    if not request.user.is_admin_role:
        raise PermissionDenied

    target_user = get_object_or_404(User, id=user_id)
    if target_user.id == request.user.id:
        messages.warning(request, "You cannot deactivate your own account.")
        return redirect('user_management')

    target_user.is_active = not target_user.is_active
    target_user.save()
    status_str = "activated" if target_user.is_active else "deactivated"
    messages.success(request, f"User {target_user.username} has been {status_str}.")
    return redirect('user_management')


#
# set ADMIN_REGISTRATION_CODE=CjxkFEb3MCug9jwJwxirWQ
# python manage.py runserver
