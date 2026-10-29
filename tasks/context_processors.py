from .models import Label, Project


def tasks_context(request):
    """Provide scoped active projects and labels to templates (e.g. quick modals)."""
    if not hasattr(request, 'user') or not request.user.is_authenticated:
        return {
            'modal_projects': [],
            'modal_labels': [],
        }

    org = getattr(request, 'organization', None)

    if request.user.is_admin_role or (hasattr(request, 'membership') and request.membership and request.membership.is_admin):
        projects = Project.objects.filter(archived=False)
    else:
        projects = Project.objects.filter(archived=False, tasks__assigned_to=request.user).distinct()

    labels = Label.objects.all()

    if org:
        projects = projects.filter(organization=org)
        labels = labels.filter(organization=org)

    return {
        'modal_projects': projects.order_by('name'),
        'modal_labels': labels.order_by('name'),
    }

