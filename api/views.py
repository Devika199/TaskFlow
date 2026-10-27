from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import exceptions, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.models import Notification
from notifications.services import create_notification
from tasks.models import Task, TaskActivityLog, TaskComment
from .serializers import (NotificationSerializer, TaskCommentSerializer,
                          TaskSerializer, TaskStatusUpdateSerializer,
                          UserSummarySerializer)

User = get_user_model()


class CurrentUserAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserSummarySerializer(request.user)
        return Response(serializer.data)


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Task.objects.select_related('created_by', 'assigned_to').prefetch_related('comments')
        today = timezone.now().date()

        # Strict RBAC: Members can ONLY access tasks assigned to them
        if not self.request.user.is_admin_role:
            qs = qs.filter(assigned_to=self.request.user)

        # Query filters
        q = self.request.query_params.get('search') or self.request.query_params.get('q')
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))

        status_param = self.request.query_params.get('status')
        if status_param in dict(Task.STATUS_CHOICES):
            qs = qs.filter(status=status_param)

        priority_param = self.request.query_params.get('priority')
        if priority_param in dict(Task.PRIORITY_CHOICES):
            qs = qs.filter(priority=priority_param)

        # Assignee filter (only admins can query other members' assigned tasks)
        if self.request.user.is_admin_role:
            assignee = self.request.query_params.get('assigned_to')
            if assignee == 'me':
                qs = qs.filter(assigned_to=self.request.user)
            elif assignee == 'unassigned':
                qs = qs.filter(assigned_to__isnull=True)
            elif assignee and assignee.isdigit():
                qs = qs.filter(assigned_to_id=int(assignee))

        overdue = self.request.query_params.get('overdue')
        if overdue in ['true', '1', 'True']:
            qs = qs.filter(due_date__lt=today).exclude(status=Task.STATUS_COMPLETED)

        ordering = self.request.query_params.get('ordering', '-created_at')
        return qs.order_by(ordering)

    def perform_create(self, serializer):
        # Strict RBAC: Only Admin can create tasks
        if not self.request.user.is_admin_role:
            raise exceptions.PermissionDenied("Only administrators can create tasks.")

        task = serializer.save(created_by=self.request.user)
        TaskActivityLog.objects.create(
            task=task,
            actor=self.request.user,
            action='CREATED',
            details=f"Task '{task.title}' created via API."
        )
        if task.assigned_to and task.assigned_to != self.request.user:
            create_notification(
                recipient=task.assigned_to,
                actor=self.request.user,
                verb=f"assigned you to task '{task.title}'",
                task=task,
                notification_type=Notification.TYPE_ASSIGNMENT
            )

    def perform_update(self, serializer):
        # Strict RBAC: Only Admin can edit task details or reassign
        if not self.request.user.is_admin_role:
            raise exceptions.PermissionDenied("Only administrators can edit task details.")

        task = self.get_object()
        old_status = task.status
        old_assignee = task.assigned_to
        updated_task = serializer.save()

        changes = []
        if old_status != updated_task.status:
            changes.append(f"Status changed from {old_status} to {updated_task.status}")
            if updated_task.assigned_to:
                create_notification(
                    recipient=updated_task.assigned_to,
                    actor=self.request.user,
                    verb=f"updated status of '{updated_task.title}' to {updated_task.get_status_display()}",
                    task=updated_task,
                    notification_type=Notification.TYPE_STATUS_CHANGE
                )

        if old_assignee != updated_task.assigned_to:
            new_name = updated_task.assigned_to.display_name if updated_task.assigned_to else "Unassigned"
            changes.append(f"Reassigned to {new_name}")
            if updated_task.assigned_to:
                create_notification(
                    recipient=updated_task.assigned_to,
                    actor=self.request.user,
                    verb=f"assigned you to task '{updated_task.title}'",
                    task=updated_task,
                    notification_type=Notification.TYPE_ASSIGNMENT
                )

        TaskActivityLog.objects.create(
            task=updated_task,
            actor=self.request.user,
            action='UPDATED',
            details="; ".join(changes) if changes else "Task updated via API."
        )

    def perform_destroy(self, instance):
        # Strict RBAC: Only Admin can delete tasks
        if not self.request.user.is_admin_role:
            raise exceptions.PermissionDenied("Only administrators can delete tasks.")
        instance.delete()

    @action(detail=True, methods=['patch'], url_path='update-status')
    def update_status(self, request, pk=None):
        task = self.get_object()
        # Explicit status update permission: Admin or Assigned Member
        if not task.can_update_status(request.user):
            raise exceptions.PermissionDenied("You do not have permission to change this task status.")

        serializer = TaskStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_status = serializer.validated_data['status']
        old_status = task.status
        if old_status != new_status:
            task.status = new_status
            task.save()

            TaskActivityLog.objects.create(
                task=task,
                actor=request.user,
                action='STATUS_CHANGE',
                details=f"Moved status from {old_status} to {new_status}"
            )

            # Send notification
            target = task.created_by if request.user == task.assigned_to else task.assigned_to
            if target:
                create_notification(
                    recipient=target,
                    actor=request.user,
                    verb=f"moved '{task.title}' to {task.get_status_display()}",
                    task=task,
                    notification_type=Notification.TYPE_STATUS_CHANGE
                )

        return Response({
            'success': True,
            'id': task.id,
            'status': task.status,
            'status_display': task.get_status_display(),
            'completed_at': task.completed_at,
            'is_overdue': task.is_overdue,
            'message': f"Task status updated to {task.get_status_display()}."
        })


class TaskCommentViewSet(viewsets.ModelViewSet):
    serializer_class = TaskCommentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = TaskComment.objects.select_related('author', 'task')
        # Strict RBAC: Members can only list comments on tasks assigned to them
        if not self.request.user.is_admin_role:
            qs = qs.filter(task__assigned_to=self.request.user)

        task_id = self.request.query_params.get('task')
        if task_id:
            qs = qs.filter(task_id=task_id)
        return qs

    def perform_create(self, serializer):
        task = serializer.validated_data['task']
        # Strict RBAC: Member can only comment on tasks assigned to them
        if not task.can_comment(self.request.user):
            raise exceptions.PermissionDenied("You are not authorized to comment on this task.")

        comment = serializer.save(author=self.request.user)

        TaskActivityLog.objects.create(
            task=task,
            actor=self.request.user,
            action='COMMENT_ADDED',
            details=f"Comment added by {self.request.user.display_name}."
        )

        recipients = set(filter(None, [task.assigned_to, task.created_by]))
        for recipient in recipients:
            create_notification(
                recipient=recipient,
                actor=self.request.user,
                verb=f"commented on '{task.title}'",
                task=task,
                notification_type=Notification.TYPE_COMMENT
            )

    def perform_destroy(self, instance):
        if not instance.can_delete(self.request.user):
            raise exceptions.PermissionDenied("You cannot delete this comment.")
        instance.delete()


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Strict isolation: Only current user's notifications
        qs = self.request.user.notifications.select_related('actor', 'task')
        if self.request.query_params.get('unread_only') in ['true', '1']:
            qs = qs.filter(is_read=False)
        return qs

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        unread_count = request.user.notifications.filter(is_read=False).count()

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            response.data['unread_count'] = unread_count
            return response

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'unread_count': unread_count,
            'results': serializer.data
        })

    @action(detail=True, methods=['post'], url_path='mark-read')
    def mark_read(self, request, pk=None):
        notif = self.get_object()
        notif.is_read = True
        notif.save(update_fields=['is_read'])
        unread_count = request.user.notifications.filter(is_read=False).count()
        return Response({'success': True, 'unread_count': unread_count})

    @action(detail=False, methods=['post'], url_path='mark-all-read')
    def mark_all_read(self, request):
        count = request.user.notifications.filter(is_read=False).update(is_read=True)
        return Response({'success': True, 'marked_count': count, 'unread_count': 0})


class AnalyticsOverviewAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        today = timezone.now().date()
        if request.user.is_admin_role:
            tasks = Task.objects.all()
        else:
            tasks = Task.objects.filter(assigned_to=request.user)

        total = tasks.count()
        completed = tasks.filter(status=Task.STATUS_COMPLETED).count()
        in_progress = tasks.filter(status=Task.STATUS_IN_PROGRESS).count()
        todo = tasks.filter(status=Task.STATUS_TODO).count()
        overdue = tasks.filter(
            due_date__lt=today,
            status__in=[Task.STATUS_TODO, Task.STATUS_IN_PROGRESS]
        ).count()

        return Response({
            'total_tasks': total,
            'completed_tasks': completed,
            'in_progress_tasks': in_progress,
            'todo_tasks': todo,
            'overdue_tasks': overdue,
            'completion_rate': round((completed / total * 100), 1) if total > 0 else 0,
            'status_distribution': {
                'TODO': todo,
                'IN_PROGRESS': in_progress,
                'COMPLETED': completed,
            },
            'priority_distribution': {
                'LOW': tasks.filter(priority=Task.PRIORITY_LOW).count(),
                'MEDIUM': tasks.filter(priority=Task.PRIORITY_MEDIUM).count(),
                'HIGH': tasks.filter(priority=Task.PRIORITY_HIGH).count(),
            }
        })


class AnalyticsWorkloadAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.is_admin_role:
            raise exceptions.PermissionDenied("Administrator privileges are required to view team workload.")

        today = timezone.now().date()
        workloads = User.objects.filter(is_active=True).annotate(
            total_assigned=Count('assigned_tasks'),
            todo=Count('assigned_tasks', filter=Q(assigned_tasks__status=Task.STATUS_TODO)),
            in_progress=Count('assigned_tasks', filter=Q(assigned_tasks__status=Task.STATUS_IN_PROGRESS)),
            completed=Count('assigned_tasks', filter=Q(assigned_tasks__status=Task.STATUS_COMPLETED)),
            overdue=Count('assigned_tasks', filter=Q(assigned_tasks__due_date__lt=today, assigned_tasks__status__in=[Task.STATUS_TODO, Task.STATUS_IN_PROGRESS]))
        ).order_by('-total_assigned')

        data = [
            {
                'user_id': u.id,
                'name': u.display_name,
                'username': u.username,
                'role': u.role,
                'department': u.department,
                'total_assigned': u.total_assigned,
                'todo': u.todo,
                'in_progress': u.in_progress,
                'completed': u.completed,
                'overdue': u.overdue,
            }
            for u in workloads
        ]
        return Response(data)


class UsersListAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.is_admin_role:
            raise exceptions.PermissionDenied("Administrator privileges are required.")
        users = User.objects.filter(is_active=True).order_by('first_name', 'username')
        serializer = UserSummarySerializer(users, many=True)
        return Response(serializer.data)
