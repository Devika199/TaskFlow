from django.contrib.auth import get_user_model
from rest_framework import serializers
from notifications.models import Notification
from tasks.models import Task, TaskActivityLog, TaskComment

User = get_user_model()


class UserSummarySerializer(serializers.ModelSerializer):
    display_name = serializers.ReadOnlyField()
    initials = serializers.ReadOnlyField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'display_name', 'initials', 'avatar_color', 'role',
            'department', 'job_title'
        ]


class TaskCommentSerializer(serializers.ModelSerializer):
    author = UserSummarySerializer(read_only=True)
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = TaskComment
        fields = ['id', 'task', 'author', 'parent', 'content', 'created_at', 'updated_at', 'can_delete']
        read_only_fields = ['id', 'author', 'created_at', 'updated_at']

    def get_can_delete(self, obj):
        request = self.context.get('request')
        if request and request.user:
            return obj.can_delete(request.user)
        return False


class TaskSerializer(serializers.ModelSerializer):
    created_by = UserSummarySerializer(read_only=True)
    assigned_to_detail = UserSummarySerializer(source='assigned_to', read_only=True)
    comments_count = serializers.IntegerField(source='comments.count', read_only=True)
    is_overdue = serializers.ReadOnlyField()
    due_status = serializers.ReadOnlyField()
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'id', 'title', 'description', 'status', 'priority',
            'due_date', 'completed_at', 'created_by', 'assigned_to',
            'assigned_to_detail', 'comments_count', 'is_overdue',
            'due_status', 'created_at', 'updated_at', 'can_edit', 'can_delete'
        ]
        read_only_fields = ['id', 'completed_at', 'created_by', 'created_at', 'updated_at']

    def get_can_edit(self, obj):
        request = self.context.get('request')
        if request and request.user:
            return obj.can_edit(request.user)
        return False

    def get_can_delete(self, obj):
        request = self.context.get('request')
        if request and request.user:
            return obj.can_delete(request.user)
        return False


class TaskStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Task.STATUS_CHOICES)


class NotificationSerializer(serializers.ModelSerializer):
    actor = UserSummarySerializer(read_only=True)
    task_title = serializers.CharField(source='task.title', read_only=True)

    class Meta:
        model = Notification
        fields = ['id', 'actor', 'task', 'task_title', 'verb', 'notification_type', 'is_read', 'created_at']
        read_only_fields = ['id', 'actor', 'created_at']
