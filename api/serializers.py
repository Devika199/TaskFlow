from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import serializers
from notifications.models import Notification
from tasks.models import (
    Label, Project, Task, TaskActivityLog, TaskChecklistItem, TaskComment,
)

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

    def validate(self, attrs):
        request = self.context.get('request')
        org = getattr(request, 'organization', None) if request else None
        task = attrs.get('task', self.instance.task if self.instance else None)
        parent = attrs.get('parent', self.instance.parent if self.instance else None)
        if parent and task and parent.task_id != task.id:
            raise serializers.ValidationError({
                'parent': 'Replies must belong to the same task as the comment.'
            })
        if org and task and getattr(task, 'organization_id', None) != org.id:
            raise serializers.ValidationError({
                'task': 'Task does not belong to the active organization.'
            })
        return attrs

    def get_can_delete(self, obj):
        request = self.context.get('request')
        if request and request.user:
            return obj.can_delete(request.user)
        return False


class TaskSerializer(serializers.ModelSerializer):
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        allow_null=True
    )
    created_by = UserSummarySerializer(read_only=True)
    assigned_to_detail = UserSummarySerializer(source='assigned_to', read_only=True)
    comments_count = serializers.IntegerField(source='comments.count', read_only=True)
    is_overdue = serializers.ReadOnlyField()
    due_status = serializers.ReadOnlyField()
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    project = serializers.PrimaryKeyRelatedField(
        queryset=Project.objects.all(),
        required=False,
        allow_null=True,
    )
    labels = serializers.PrimaryKeyRelatedField(
        queryset=Label.objects.all(),
        many=True,
        required=False,
    )
    checklist_items = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'id', 'title', 'description', 'status', 'priority',
            'due_date', 'completed_at', 'created_by', 'assigned_to',
            'assigned_to_detail', 'comments_count', 'is_overdue',
            'due_status', 'project', 'labels', 'checklist_items',
            'created_at', 'updated_at', 'can_edit', 'can_delete'
        ]
        read_only_fields = ['id', 'completed_at', 'created_by', 'created_at', 'updated_at']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        org = getattr(request, 'organization', None) if request else None
        if org:
            self.fields['project'].queryset = Project.objects.filter(organization=org)
            self.fields['labels'].queryset = Label.objects.filter(organization=org)
            self.fields['assigned_to'].queryset = User.objects.filter(
                Q(organization_memberships__organization=org, organization_memberships__is_active=True)
                | Q(organization_memberships__isnull=True),
                is_active=True,
            ).distinct()

    def validate(self, attrs):
        request = self.context.get('request')
        org = getattr(request, 'organization', None) if request else None
        if org:
            project = attrs.get('project')
            if project and getattr(project, 'organization_id', None) != org.id:
                raise serializers.ValidationError({'project': 'Project does not belong to the active organization.'})
            labels = attrs.get('labels')
            if labels:
                for label in labels:
                    if getattr(label, 'organization_id', None) != org.id:
                        raise serializers.ValidationError({'labels': f"Label '{label.name}' does not belong to the active organization."})
            assigned_to = attrs.get('assigned_to')
            if assigned_to:
                from tasks.models import _get_user_org_cache
                active_ids, _, has_any = _get_user_org_cache(assigned_to)
                if has_any and org.id not in active_ids:
                    raise serializers.ValidationError({'assigned_to': 'Assignee is not an active member of the active organization.'})
        return attrs

    def validate_project(self, project):
        if project and project.archived and (
            self.instance is None or self.instance.project_id != project.pk
        ):
            raise serializers.ValidationError('Archived projects cannot be assigned to tasks.')
        return project

    def get_checklist_items(self, obj):
        return TaskChecklistItemSerializer(
            obj.checklist_items.all(),
            many=True,
            context=self.context,
        ).data

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


class TaskChecklistItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskChecklistItem
        fields = ['id', 'task', 'title', 'position', 'is_completed', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class TaskChecklistItemStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskChecklistItem
        fields = ['is_completed']


class ProjectSerializer(serializers.ModelSerializer):
    def validate_name(self, name):
        request = self.context.get('request')
        org = getattr(request, 'organization', None) if request else None
        projects = Project.objects.filter(name__iexact=name.strip())
        if org:
            projects = projects.filter(organization=org)
        if self.instance:
            projects = projects.exclude(pk=self.instance.pk)
        if projects.exists():
            raise serializers.ValidationError('A project with this name already exists.')
        return name.strip()

    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'archived', 'created_by', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']


class LabelSerializer(serializers.ModelSerializer):
    def validate_name(self, name):
        request = self.context.get('request')
        org = getattr(request, 'organization', None) if request else None
        labels = Label.objects.filter(name__iexact=name.strip())
        if org:
            labels = labels.filter(organization=org)
        if self.instance:
            labels = labels.exclude(pk=self.instance.pk)
        if labels.exists():
            raise serializers.ValidationError('A label with this name already exists.')
        return name.strip()

    class Meta:
        model = Label
        fields = ['id', 'name', 'color', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class TaskStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Task.STATUS_CHOICES)


class NotificationSerializer(serializers.ModelSerializer):
    actor = UserSummarySerializer(read_only=True)
    task_title = serializers.CharField(source='task.title', read_only=True)

    class Meta:
        model = Notification
        fields = ['id', 'actor', 'task', 'task_title', 'verb', 'notification_type', 'is_read', 'created_at']
        read_only_fields = ['id', 'actor', 'created_at']
