from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from .models import Organization, OrganizationMembership
from .services import (
    LastOwnerError,
    MembershipError,
    OrganizationPermissionError,
    RoleEscalationError,
    add_user_to_organization,
    get_active_membership,
    get_user_organizations,
    remove_member_from_organization,
    toggle_membership_active,
    transfer_organization_ownership,
    update_membership_role,
)

User = get_user_model()


class OrganizationModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='model_user', email='model@test.com', password='password123')

    def test_organization_creation_and_auto_slug(self):
        org = Organization.objects.create(name='Acme Corporation')
        self.assertEqual(org.slug, 'acme-corporation')
        self.assertTrue(org.is_active)
        self.assertEqual(str(org), 'Acme Corporation')

        # Duplicate name creates unique slug
        org2 = Organization.objects.create(name='Acme Corporation')
        self.assertNotEqual(org.slug, org2.slug)
        self.assertTrue(org2.slug.startswith('acme-corporation-'))

    def test_unique_user_organization_membership_constraint(self):
        org = Organization.objects.create(name='Unique Org')
        OrganizationMembership.objects.create(
            user=self.user,
            organization=org,
            role=OrganizationMembership.ROLE_OWNER,
        )

        with self.assertRaises(IntegrityError):
            OrganizationMembership.objects.create(
                user=self.user,
                organization=org,
                role=OrganizationMembership.ROLE_MEMBER,
            )

    def test_membership_properties(self):
        org = Organization.objects.create(name='Props Org')
        membership_owner = OrganizationMembership.objects.create(
            user=self.user,
            organization=org,
            role=OrganizationMembership.ROLE_OWNER,
            is_active=True,
        )
        self.assertTrue(membership_owner.is_owner)
        self.assertTrue(membership_owner.is_admin)
        self.assertTrue(membership_owner.can_manage_members)
        self.assertTrue(membership_owner.can_manage_organization)

        membership_owner.role = OrganizationMembership.ROLE_ADMIN
        self.assertFalse(membership_owner.is_owner)
        self.assertTrue(membership_owner.is_admin)
        self.assertTrue(membership_owner.can_manage_members)
        self.assertFalse(membership_owner.can_manage_organization)

        membership_owner.role = OrganizationMembership.ROLE_MEMBER
        self.assertFalse(membership_owner.is_owner)
        self.assertFalse(membership_owner.is_admin)
        self.assertFalse(membership_owner.can_manage_members)
        self.assertFalse(membership_owner.can_manage_organization)

        # Inactive membership loses privileges
        membership_owner.role = OrganizationMembership.ROLE_OWNER
        membership_owner.is_active = False
        self.assertFalse(membership_owner.is_owner)
        self.assertFalse(membership_owner.is_admin)
        self.assertFalse(membership_owner.can_manage_members)


class OrganizationServiceTests(TestCase):
    def setUp(self):
        self.owner_user = User.objects.create_user(username='org_owner', email='owner@test.com', password='password123')
        self.admin_user = User.objects.create_user(username='org_admin', email='admin@test.com', password='password123')
        self.member_user = User.objects.create_user(username='org_member', email='member@test.com', password='password123')
        self.outsider_user = User.objects.create_user(username='outsider', email='outsider@test.com', password='password123')

        self.org = Organization.objects.create(name='Test Workspace', slug='test-workspace')
        self.owner_membership = OrganizationMembership.objects.create(
            user=self.owner_user,
            organization=self.org,
            role=OrganizationMembership.ROLE_OWNER,
            is_active=True,
        )
        self.admin_membership = OrganizationMembership.objects.create(
            user=self.admin_user,
            organization=self.org,
            role=OrganizationMembership.ROLE_ADMIN,
            is_active=True,
        )
        self.member_membership = OrganizationMembership.objects.create(
            user=self.member_user,
            organization=self.org,
            role=OrganizationMembership.ROLE_MEMBER,
            is_active=True,
        )

    def test_add_user_to_organization_success(self):
        new_user = User.objects.create_user(username='newbie', email='newbie@test.com', password='password123')
        membership = add_user_to_organization(
            organization=self.org,
            user=new_user,
            role=OrganizationMembership.ROLE_MEMBER,
            actor=self.admin_user,
        )
        self.assertEqual(membership.user, new_user)
        self.assertEqual(membership.role, OrganizationMembership.ROLE_MEMBER)
        self.assertTrue(membership.is_active)

    def test_add_user_rejects_duplicate_active_membership(self):
        with self.assertRaises(MembershipError):
            add_user_to_organization(
                organization=self.org,
                user=self.member_user,
                actor=self.owner_user,
            )

    def test_add_user_reactivates_inactive_membership(self):
        self.member_membership.is_active = False
        self.member_membership.save(update_fields=['is_active'])

        membership = add_user_to_organization(
            organization=self.org,
            user=self.member_user,
            role=OrganizationMembership.ROLE_MEMBER,
            actor=self.admin_user,
            is_active=True,
        )
        self.assertTrue(membership.is_active)
        self.assertEqual(membership.pk, self.member_membership.pk)

    def test_add_user_prevents_role_escalation(self):
        new_user = User.objects.create_user(username='candidate', email='cand@test.com', password='password123')

        # Member cannot add members
        with self.assertRaises(OrganizationPermissionError):
            add_user_to_organization(
                organization=self.org,
                user=new_user,
                role=OrganizationMembership.ROLE_MEMBER,
                actor=self.member_user,
            )

        # Admin cannot create an Owner
        with self.assertRaises(RoleEscalationError):
            add_user_to_organization(
                organization=self.org,
                user=new_user,
                role=OrganizationMembership.ROLE_OWNER,
                actor=self.admin_user,
            )

        # Owner can create an Owner
        owner_created = add_user_to_organization(
            organization=self.org,
            user=new_user,
            role=OrganizationMembership.ROLE_OWNER,
            actor=self.owner_user,
        )
        self.assertEqual(owner_created.role, OrganizationMembership.ROLE_OWNER)

    def test_last_owner_cannot_be_demoted(self):
        # Only 1 active owner in self.org
        self.assertEqual(self.org.active_owner_count, 1)

        with self.assertRaises(LastOwnerError):
            update_membership_role(
                membership=self.owner_membership,
                new_role=OrganizationMembership.ROLE_ADMIN,
                actor=self.owner_user,
            )

    def test_last_owner_cannot_be_deactivated(self):
        with self.assertRaises(LastOwnerError):
            toggle_membership_active(
                membership=self.owner_membership,
                actor=self.owner_user,
            )

    def test_last_owner_cannot_be_removed(self):
        with self.assertRaises(LastOwnerError):
            remove_member_from_organization(
                membership=self.owner_membership,
                actor=self.owner_user,
            )

    def test_owner_demotion_allowed_when_another_owner_exists(self):
        second_owner = User.objects.create_user(username='owner2', email='owner2@test.com', password='password123')
        second_membership = OrganizationMembership.objects.create(
            user=second_owner,
            organization=self.org,
            role=OrganizationMembership.ROLE_OWNER,
            is_active=True,
        )
        self.assertEqual(self.org.active_owner_count, 2)

        # Now first owner can be demoted by another owner
        updated = update_membership_role(
            membership=self.owner_membership,
            new_role=OrganizationMembership.ROLE_ADMIN,
            actor=second_owner,
        )
        self.assertEqual(updated.role, OrganizationMembership.ROLE_ADMIN)
        self.assertEqual(self.org.active_owner_count, 1)

    def test_admin_cannot_demote_or_deactivate_owner(self):
        second_owner = User.objects.create_user(username='owner2', email='owner2@test.com', password='password123')
        OrganizationMembership.objects.create(
            user=second_owner,
            organization=self.org,
            role=OrganizationMembership.ROLE_OWNER,
            is_active=True,
        )

        with self.assertRaises(OrganizationPermissionError):
            update_membership_role(
                membership=self.owner_membership,
                new_role=OrganizationMembership.ROLE_ADMIN,
                actor=self.admin_user,
            )

        with self.assertRaises(OrganizationPermissionError):
            toggle_membership_active(
                membership=self.owner_membership,
                actor=self.admin_user,
            )

    def test_admin_cannot_promote_to_owner(self):
        with self.assertRaises(RoleEscalationError):
            update_membership_role(
                membership=self.member_membership,
                new_role=OrganizationMembership.ROLE_OWNER,
                actor=self.admin_user,
            )

    def test_member_cannot_modify_roles(self):
        with self.assertRaises(OrganizationPermissionError):
            update_membership_role(
                membership=self.admin_membership,
                new_role=OrganizationMembership.ROLE_MEMBER,
                actor=self.member_user,
            )

    def test_transfer_organization_ownership(self):
        old_owner_mem, new_owner_mem = transfer_organization_ownership(
            organization=self.org,
            current_owner_user=self.owner_user,
            new_owner_user=self.admin_user,
            demote_to_role=OrganizationMembership.ROLE_ADMIN,
        )
        old_owner_mem.refresh_from_db()
        new_owner_mem.refresh_from_db()

        self.assertEqual(new_owner_mem.role, OrganizationMembership.ROLE_OWNER)
        self.assertTrue(new_owner_mem.is_active)
        self.assertEqual(old_owner_mem.role, OrganizationMembership.ROLE_ADMIN)
        self.assertEqual(self.org.active_owner_count, 1)

    def test_transfer_ownership_requires_active_owner(self):
        with self.assertRaises(OrganizationPermissionError):
            transfer_organization_ownership(
                organization=self.org,
                current_owner_user=self.admin_user,
                new_owner_user=self.member_user,
            )

    def test_get_active_membership_and_user_organizations(self):
        self.assertEqual(get_active_membership(self.owner_user, self.org), self.owner_membership)
        self.assertIsNone(get_active_membership(self.outsider_user, self.org))

        user_orgs = get_user_organizations(self.owner_user)
        self.assertIn(self.org, user_orgs)

        outsider_orgs = get_user_organizations(self.outsider_user)
        self.assertEqual(outsider_orgs.count(), 0)

