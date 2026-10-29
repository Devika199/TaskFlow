from django.db import transaction
from django.db.models import Q
from .models import Organization, OrganizationMembership


class OrganizationError(Exception):
    """Base error for organization operations."""
    pass


class MembershipError(OrganizationError):
    """Base error for membership operations."""
    pass


class LastOwnerError(MembershipError):
    """Raised when an action would leave an organization without an active owner."""
    pass


class RoleEscalationError(MembershipError):
    """Raised when an actor attempts an unauthorized role elevation."""
    pass


class OrganizationPermissionError(OrganizationError):
    """Raised when an actor lacks permission to manage an organization or its members."""
    pass


def get_active_membership(user, organization):
    """Return active OrganizationMembership for user in organization, or None."""
    if not user or not user.is_authenticated or not organization:
        return None
    return OrganizationMembership.objects.filter(
        user=user,
        organization=organization,
        is_active=True,
    ).select_related('organization', 'user').first()


def get_user_organizations(user, active_only=True):
    """Return queryset of Organizations the user belongs to."""
    if not user or not user.is_authenticated:
        return Organization.objects.none()

    qs = Organization.objects.filter(memberships__user=user)
    if active_only:
        qs = qs.filter(memberships__is_active=True, is_active=True)
    return qs.distinct().order_by('name')


def add_user_to_organization(organization, user, role=OrganizationMembership.ROLE_MEMBER, actor=None, is_active=True):
    """
    Safely add a user to an organization or reactivate an existing membership.
    Enforces authorization, role escalation prevention, and membership uniqueness.
    """
    if role not in dict(OrganizationMembership.ROLE_CHOICES):
        raise ValueError(f"Invalid role '{role}'.")

    if actor is not None:
        actor_membership = get_active_membership(actor, organization)
        if not actor_membership or not actor_membership.can_manage_members:
            raise OrganizationPermissionError("Only organization owners and administrators can add members.")

        # Prevent role escalation: only OWNER can add another OWNER
        if role == OrganizationMembership.ROLE_OWNER and actor_membership.role != OrganizationMembership.ROLE_OWNER:
            raise RoleEscalationError("Only organization owners can assign the Owner role.")

    with transaction.atomic():
        membership = OrganizationMembership.objects.filter(user=user, organization=organization).first()
        if membership:
            if membership.is_active:
                raise MembershipError(f"User '{user.username}' is already an active member of '{organization.name}'.")
            # Reactivate inactive membership
            membership.is_active = is_active
            membership.role = role
            membership.save(update_fields=['is_active', 'role', 'updated_at'])
            return membership

        membership = OrganizationMembership.objects.create(
            user=user,
            organization=organization,
            role=role,
            is_active=is_active,
        )
        return membership


def update_membership_role(membership, new_role, actor):
    """
    Update a member's role within an organization.
    Enforces role escalation protection and prevents demoting the last active owner.
    """
    if new_role not in dict(OrganizationMembership.ROLE_CHOICES):
        raise ValueError(f"Invalid role '{new_role}'.")

    if membership.role == new_role:
        return membership

    organization = membership.organization
    actor_membership = get_active_membership(actor, organization)

    if not actor_membership or not actor_membership.can_manage_members:
        raise OrganizationPermissionError("You do not have permission to modify roles in this organization.")

    # Only an OWNER can promote anyone to OWNER
    if new_role == OrganizationMembership.ROLE_OWNER and actor_membership.role != OrganizationMembership.ROLE_OWNER:
        raise RoleEscalationError("Only organization owners can promote members to the Owner role.")

    # Only an OWNER can modify another OWNER's role
    if membership.role == OrganizationMembership.ROLE_OWNER and actor_membership.role != OrganizationMembership.ROLE_OWNER:
        raise OrganizationPermissionError("Only organization owners can modify another owner's role.")

    with transaction.atomic():
        # Last-owner protection: cannot demote the last active owner
        if membership.role == OrganizationMembership.ROLE_OWNER and membership.is_active and new_role != OrganizationMembership.ROLE_OWNER:
            other_active_owners = OrganizationMembership.objects.filter(
                organization=organization,
                role=OrganizationMembership.ROLE_OWNER,
                is_active=True,
            ).exclude(pk=membership.pk).count()
            if other_active_owners == 0:
                raise LastOwnerError(
                    "Cannot demote the last active owner of the organization. Transfer ownership before demoting."
                )

        membership.role = new_role
        membership.save(update_fields=['role', 'updated_at'])
        return membership


def toggle_membership_active(membership, actor):
    """
    Toggle a membership between active and inactive.
    Enforces last-owner protection and authorization.
    """
    organization = membership.organization
    actor_membership = get_active_membership(actor, organization)

    if not actor_membership or not actor_membership.can_manage_members:
        raise OrganizationPermissionError("You do not have permission to manage members in this organization.")

    # An admin cannot deactivate an owner
    if membership.role == OrganizationMembership.ROLE_OWNER and actor_membership.role != OrganizationMembership.ROLE_OWNER:
        raise OrganizationPermissionError("Only organization owners can deactivate an owner.")

    with transaction.atomic():
        # Last-owner protection: cannot deactivate the last active owner
        if membership.is_active and membership.role == OrganizationMembership.ROLE_OWNER:
            other_active_owners = OrganizationMembership.objects.filter(
                organization=organization,
                role=OrganizationMembership.ROLE_OWNER,
                is_active=True,
            ).exclude(pk=membership.pk).count()
            if other_active_owners == 0:
                raise LastOwnerError(
                    "Cannot deactivate the last active owner of the organization. Transfer ownership before deactivating."
                )

        membership.is_active = not membership.is_active
        membership.save(update_fields=['is_active', 'updated_at'])
        return membership


def remove_member_from_organization(membership, actor):
    """
    Remove a member from an organization.
    Enforces last-owner protection and authorization.
    """
    organization = membership.organization
    is_self = actor and actor.pk == membership.user_id

    if is_self:
        # A member can leave, unless they are the last active owner
        if membership.is_active and membership.role == OrganizationMembership.ROLE_OWNER:
            other_active_owners = OrganizationMembership.objects.filter(
                organization=organization,
                role=OrganizationMembership.ROLE_OWNER,
                is_active=True,
            ).exclude(pk=membership.pk).count()
            if other_active_owners == 0:
                raise LastOwnerError(
                    "You are the last active owner. Transfer ownership before leaving the organization."
                )
    else:
        actor_membership = get_active_membership(actor, organization)
        if not actor_membership or not actor_membership.can_manage_members:
            raise OrganizationPermissionError("You do not have permission to remove members from this organization.")

        # Admin cannot remove an owner
        if membership.role == OrganizationMembership.ROLE_OWNER and actor_membership.role != OrganizationMembership.ROLE_OWNER:
            raise OrganizationPermissionError("Only organization owners can remove another owner.")

        # Last-owner protection
        if membership.is_active and membership.role == OrganizationMembership.ROLE_OWNER:
            other_active_owners = OrganizationMembership.objects.filter(
                organization=organization,
                role=OrganizationMembership.ROLE_OWNER,
                is_active=True,
            ).exclude(pk=membership.pk).count()
            if other_active_owners == 0:
                raise LastOwnerError(
                    "Cannot remove the last active owner of the organization."
                )

    with transaction.atomic():
        membership.delete()


def transfer_organization_ownership(organization, current_owner_user, new_owner_user, demote_to_role=OrganizationMembership.ROLE_ADMIN):
    """
    Safely transfer organization ownership from current owner to a new owner in an atomic transaction.
    """
    if current_owner_user.pk == new_owner_user.pk:
        raise MembershipError("Cannot transfer ownership to the same user.")

    current_membership = get_active_membership(current_owner_user, organization)
    if not current_membership or current_membership.role != OrganizationMembership.ROLE_OWNER:
        raise OrganizationPermissionError("Only an active organization owner can transfer ownership.")

    with transaction.atomic():
        new_membership = OrganizationMembership.objects.filter(user=new_owner_user, organization=organization).first()
        if new_membership:
            new_membership.role = OrganizationMembership.ROLE_OWNER
            new_membership.is_active = True
            new_membership.save(update_fields=['role', 'is_active', 'updated_at'])
        else:
            new_membership = OrganizationMembership.objects.create(
                user=new_owner_user,
                organization=organization,
                role=OrganizationMembership.ROLE_OWNER,
                is_active=True,
            )

        current_membership.role = demote_to_role
        current_membership.save(update_fields=['role', 'updated_at'])

        return current_membership, new_membership


def ensure_default_organization(name="TaskFlow Workspace", slug="default-workspace"):
    """
    Bootstrap or retrieve the default organization.
    """
    org, created = Organization.objects.get_or_create(
        slug=slug,
        defaults={'name': name, 'is_active': True},
    )
    return org, created

