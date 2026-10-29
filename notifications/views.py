from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .models import Notification


@login_required
def notification_list_view(request):
    notifications = request.user.notifications.select_related('actor', 'task')
    filter_type = request.GET.get('filter', 'all')
    if filter_type == 'unread':
        notifications = notifications.filter(is_read=False)

    return render(request, 'notifications/notification_list.html', {
        'notifications': notifications,
        'current_filter': filter_type,
    })


@login_required
@require_POST
def mark_read_view(request, pk):
    notif = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notif.is_read = True
    notif.save(update_fields=['is_read'])

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
        return JsonResponse({'success': True, 'unread_count': request.user.notifications.filter(is_read=False).count()})

    messages.success(request, "Notification marked as read.")
    return redirect('notification_list')


@login_required
@require_POST
def mark_all_read_view(request):
    updated_count = request.user.notifications.filter(is_read=False).update(is_read=True)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
        return JsonResponse({'success': True, 'marked_count': updated_count, 'unread_count': 0})

    messages.success(request, "All notifications marked as read.")
    return redirect('notification_list')
