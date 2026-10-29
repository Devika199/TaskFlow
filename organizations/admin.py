from django.contrib import admin
from .models import Organization, OrganizationMembership


class OrganizationMembershipInline(admin.TabularInline):
    model = OrganizationMembership
    extra = 1
    fields = ('user', 'role', 'is_active', 'created_at')
    readonly_fields = ('created_at',)
    raw_id_fields = ('user',)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'member_count', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [OrganizationMembershipInline]

    def member_count(self, obj):
        return obj.memberships.count()
    member_count.short_description = 'Members'


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'organization', 'role', 'is_active', 'created_at')
    list_filter = ('role', 'is_active', 'organization')
    search_fields = ('user__username', 'user__email', 'organization__name')
    raw_id_fields = ('user', 'organization')

