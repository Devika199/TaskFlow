def notifications_context(request):
    if request.user.is_authenticated:
        unread_count = request.user.notifications.filter(is_read=False).count()
        recent_notifications = request.user.notifications.select_related('actor', 'task')[:6]
        return {
            'unread_notifications_count': unread_count,
            'recent_notifications': recent_notifications,
        }
    return {
        'unread_notifications_count': 0,
        'recent_notifications': [],
    }
