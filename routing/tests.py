from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from accounts.models import Department, SecurityEvent, User

from .models import (
    Category,
    ConfigurationAuditEvent,
    EscalationPolicy,
    MAX_ESCALATION_INTERVAL_MINUTES,
    MAX_ESCALATION_LEVEL,
    MAX_SLA_DURATION_MINUTES,
    Priority,
    RoutingRule,
    SLAConfiguration,
)
from .services import (
    ConfigurationError,
    create_category,
    create_escalation_policy,
    create_routing_rule,
    deactivate_category,
    deactivate_routing_rule,
    deactivate_sla_configuration,
    department_in_use,
    reactivate_category,
    set_sla_configuration,
    update_category,
    update_escalation_policy,
)


class RoutingConfigurationTests(TestCase):
    """B17 / REQ-ADM-03 and REQ-ADM-04 regression tests."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@pes.edu",
            password="Campus123",
            full_name="Admin",
            role=User.Role.ADMIN,
        )
        self.staff = User.objects.create_user(
            email="staff@pes.edu",
            password="Campus123",
            full_name="Staff",
            role=User.Role.STAFF,
        )
        self.maintenance = Department.objects.create(name="Maintenance")
        self.administration = Department.objects.create(name="Administration")

    def test_initial_configuration_is_seeded_from_agreed_d01_values(self):
        self.assertSetEqual(
            set(Category.objects.values_list("name", flat=True)),
            {"Electrical", "Plumbing", "Wi-Fi/Network", "Cleanliness", "Security", "Other"},
        )
        self.assertEqual(Category.objects.get(name="Electrical").minimum_priority, Priority.MEDIUM)
        self.assertEqual(Category.objects.get(name="Security").minimum_priority, Priority.HIGH)
        self.assertEqual(SLAConfiguration.objects.filter(category=None, active=True).count(), 4)
        self.assertFalse(EscalationPolicy.objects.exists())
        self.assertFalse(RoutingRule.objects.exists())

    def test_only_administrator_can_change_configuration(self):
        with self.assertRaises(PermissionDenied):
            create_category(self.staff, name="Lift", minimum_priority=Priority.HIGH)
        self.assertFalse(Category.objects.filter(name="Lift").exists())
        self.assertEqual(
            SecurityEvent.objects.filter(
                user=self.staff,
                event_type=SecurityEvent.EventType.AUTHORIZATION_REFUSED,
            ).count(),
            1,
        )

    def test_refused_sla_configuration_is_logged(self):
        with self.assertRaises(PermissionDenied):
            set_sla_configuration(self.staff, priority=Priority.LOW, duration_minutes=60)
        self.assertEqual(
            SecurityEvent.objects.filter(
                user=self.staff,
                event_type=SecurityEvent.EventType.AUTHORIZATION_REFUSED,
            ).count(),
            1,
        )

    def test_category_name_is_limited_to_fifty_characters(self):
        fifty_character_name = "C" * 50
        category = create_category(self.admin, name=fifty_character_name)
        self.assertEqual(category.name, fifty_character_name)

        fifty_one_character_name = "C" * 51
        with self.assertRaises(ConfigurationError):
            create_category(self.admin, name=fifty_one_character_name)
        with self.assertRaises(ConfigurationError):
            update_category(self.admin, category, name=fifty_one_character_name)

    def test_category_change_is_audited_and_deactivation_preserves_the_row(self):
        category = create_category(self.admin, name="Lift", minimum_priority=Priority.MEDIUM)
        created = ConfigurationAuditEvent.objects.get(entity_type="Category", entity_id=category.pk)
        self.assertEqual(created.actor, self.admin)
        self.assertEqual(created.action, ConfigurationAuditEvent.Action.CREATED)
        self.assertEqual(created.new_values["minimum_priority"], Priority.MEDIUM)

        update_category(self.admin, category, minimum_priority=Priority.HIGH)
        updated = ConfigurationAuditEvent.objects.filter(entity_id=category.pk).first()
        self.assertEqual(updated.action, ConfigurationAuditEvent.Action.UPDATED)
        self.assertEqual(updated.old_values["minimum_priority"], Priority.MEDIUM)
        self.assertEqual(updated.new_values["minimum_priority"], Priority.HIGH)

        deactivate_category(self.admin, category)
        category.refresh_from_db()
        self.assertFalse(category.active)
        self.assertTrue(Category.objects.filter(pk=category.pk).exists())

        reactivate_category(self.admin, category)
        category.refresh_from_db()
        self.assertTrue(category.active)
        self.assertTrue(
            ConfigurationAuditEvent.objects.filter(
                entity_type="Category",
                entity_id=category.pk,
                action=ConfigurationAuditEvent.Action.REACTIVATED,
            ).exists()
        )

    def test_category_deactivation_requires_active_dependents_to_be_disabled_first(self):
        category = Category.objects.get(name="Electrical")
        rule = create_routing_rule(
            self.admin, category=category, department=self.maintenance
        )
        with self.assertRaises(ConfigurationError):
            deactivate_category(self.admin, category)

        deactivate_routing_rule(self.admin, rule)
        override = set_sla_configuration(
            self.admin, category=category, priority=Priority.HIGH, duration_minutes=60
        )
        with self.assertRaises(ConfigurationError):
            deactivate_category(self.admin, category)

        deactivate_sla_configuration(self.admin, override)
        deactivate_category(self.admin, category)
        category.refresh_from_db()
        self.assertFalse(category.active)

    def test_active_duplicate_routing_rule_is_rejected_and_location_is_normalized(self):
        category = Category.objects.get(name="Electrical")
        create_routing_rule(
            self.admin, category=category, department=self.maintenance, precedence=100
        )
        with self.assertRaises(ConfigurationError):
            create_routing_rule(
                self.admin, category=category, department=self.maintenance, precedence=200
            )

        rule = create_routing_rule(
            self.admin,
            category=category,
            location_code=" hostel-a ",
            department=self.maintenance,
            precedence=10,
        )
        self.assertEqual(rule.location_code, "HOSTEL-A")
        self.assertEqual(rule.precedence, 10)

    def test_rule_requires_a_scope_and_an_active_department(self):
        with self.assertRaises(ConfigurationError):
            create_routing_rule(self.admin, department=self.maintenance)

        self.maintenance.active = False
        self.maintenance.save(update_fields=["active"])
        with self.assertRaises(ConfigurationError):
            create_routing_rule(
                self.admin,
                category=Category.objects.get(name="Other"),
                department=self.maintenance,
            )

    def test_sla_duration_enforces_its_permitted_range(self):
        range_message = f"from 1 to {MAX_SLA_DURATION_MINUTES} (one year)"
        for value in (0, MAX_SLA_DURATION_MINUTES + 1, "not-a-number"):
            with self.assertRaises(ConfigurationError) as error:
                set_sla_configuration(self.admin, priority=Priority.LOW, duration_minutes=value)
            self.assertIn(range_message, str(error.exception))

        minimum = set_sla_configuration(self.admin, priority=Priority.LOW, duration_minutes=1)
        self.assertEqual(minimum.duration_minutes, 1)
        maximum = set_sla_configuration(
            self.admin, priority=Priority.LOW, duration_minutes=MAX_SLA_DURATION_MINUTES
        )
        self.assertEqual(maximum.duration_minutes, MAX_SLA_DURATION_MINUTES)

    def test_escalation_interval_and_level_enforce_their_permitted_ranges(self):
        policy = create_escalation_policy(
            self.admin,
            default_department=self.administration,
            interval_minutes=1,
            maximum_level=1,
        )
        self.assertEqual((policy.interval_minutes, policy.maximum_level), (1, 1))

        interval_message = f"from 1 to {MAX_ESCALATION_INTERVAL_MINUTES} (30 days)"
        for value in (0, MAX_ESCALATION_INTERVAL_MINUTES + 1, "not-a-number"):
            with self.assertRaises(ConfigurationError) as error:
                update_escalation_policy(self.admin, policy, interval_minutes=value)
            self.assertIn(interval_message, str(error.exception))
        update_escalation_policy(
            self.admin, policy, interval_minutes=MAX_ESCALATION_INTERVAL_MINUTES
        )
        policy.refresh_from_db()
        self.assertEqual(policy.interval_minutes, MAX_ESCALATION_INTERVAL_MINUTES)

        level_message = f"from 1 to {MAX_ESCALATION_LEVEL}"
        for value in (0, MAX_ESCALATION_LEVEL + 1, "not-a-number"):
            with self.assertRaises(ConfigurationError) as error:
                update_escalation_policy(self.admin, policy, maximum_level=value)
            self.assertIn(level_message, str(error.exception))
        update_escalation_policy(self.admin, policy, maximum_level=MAX_ESCALATION_LEVEL)
        policy.refresh_from_db()
        self.assertEqual(policy.maximum_level, MAX_ESCALATION_LEVEL)

    def test_sla_and_escalation_settings_are_audited(self):
        sla = set_sla_configuration(self.admin, priority=Priority.LOW, duration_minutes=360)
        self.assertEqual(sla.duration_minutes, 360)
        self.assertTrue(
            ConfigurationAuditEvent.objects.filter(
                entity_type="SLAConfiguration", entity_id=sla.pk, action="UPDATED"
            ).exists()
        )

        policy = create_escalation_policy(
            self.admin,
            default_department=self.administration,
            interval_minutes=1440,
            maximum_level=3,
        )
        update_escalation_policy(self.admin, policy, maximum_level=4)
        policy.refresh_from_db()
        self.assertEqual(policy.maximum_level, 4)

    def test_sla_rejects_inactive_categories(self):
        category = create_category(self.admin, name="Lift")
        deactivate_category(self.admin, category)
        with self.assertRaises(ConfigurationError):
            set_sla_configuration(
                self.admin, category=category, priority=Priority.LOW, duration_minutes=60
            )

    def test_department_in_use_reports_active_routing_and_escalation_references(self):
        unused = Department.objects.create(name="Unused")
        self.assertFalse(department_in_use(unused))

        rule = create_routing_rule(
            self.admin,
            category=Category.objects.get(name="Electrical"),
            department=self.maintenance,
        )
        self.assertTrue(department_in_use(self.maintenance))
        deactivate_routing_rule(self.admin, rule)
        self.assertFalse(department_in_use(self.maintenance))

        create_escalation_policy(
            self.admin,
            default_department=self.administration,
            interval_minutes=1440,
            maximum_level=3,
        )
        self.assertTrue(department_in_use(self.administration))

    def test_last_active_default_sla_for_a_priority_cannot_be_deactivated(self):
        default = SLAConfiguration.objects.get(category=None, priority=Priority.LOW)
        with self.assertRaises(ConfigurationError):
            deactivate_sla_configuration(self.admin, default)
        default.refresh_from_db()
        self.assertTrue(default.active)

    def test_database_checks_prevent_nonpositive_configuration(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            SLAConfiguration.objects.create(priority=Priority.LOW, duration_minutes=0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            EscalationPolicy.objects.create(
                key="invalid",
                default_department=self.maintenance,
                interval_minutes=0,
                maximum_level=1,
            )

    def test_database_constraint_prevents_duplicate_active_routing_scope(self):
        category = Category.objects.get(name="Other")
        first = RoutingRule.objects.create(
            category=category, location_code="Hostel-A", department=self.maintenance
        )
        self.assertEqual(first.scope_key, f"{category.pk}:HOSTEL-A")
        with self.assertRaises(IntegrityError), transaction.atomic():
            RoutingRule.objects.create(
                category=category, location_code=" hostel-a ", department=self.maintenance
            )
        first.active = False
        first.save(update_fields=["active"])
        replacement = RoutingRule.objects.create(
            category=category, location_code="hostel-a", department=self.maintenance
        )
        self.assertTrue(replacement.active)

    def test_database_constraints_protect_case_insensitive_category_and_sla_scope(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Category.objects.create(name="electrical")

        category = Category.objects.get(name="Electrical")
        SLAConfiguration.objects.create(
            category=category, priority=Priority.LOW, duration_minutes=60
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            SLAConfiguration.objects.create(
                category=category, priority=Priority.LOW, duration_minutes=120
            )

    def test_audit_records_are_append_only(self):
        category = create_category(self.admin, name="Transport")
        audit = ConfigurationAuditEvent.objects.get(entity_id=category.pk)
        with self.assertRaises(ValidationError):
            audit.save()
        with self.assertRaises(ValidationError):
            ConfigurationAuditEvent.objects.filter(pk=audit.pk).delete()

    def test_configuration_screen_allows_only_admin_and_uses_services(self):
        url = reverse("routing:configuration")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.staff)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.admin)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Routing, SLA and escalation configuration")
        self.assertContains(response, "provisional")
        response = self.client.post(
            url,
            {
                "action": "create_category",
                "name": "Transport",
                "minimum_priority": Priority.MEDIUM,
            },
        )
        self.assertRedirects(response, url)
        category = Category.objects.get(name="Transport")
        self.assertTrue(
            ConfigurationAuditEvent.objects.filter(
                entity_type="Category", entity_id=category.pk, actor=self.admin
            ).exists()
        )

    def test_screen_exposes_all_configuration_actions(self):
        url = reverse("routing:configuration")
        category = Category.objects.get(name="Other")
        rule = create_routing_rule(
            self.admin, category=category, department=self.maintenance, precedence=20
        )
        sla = set_sla_configuration(
            self.admin, category=category, priority=Priority.LOW, duration_minutes=60
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            url,
            {
                "action": "update_category",
                "category_id": category.pk,
                "name": "Miscellaneous",
                "minimum_priority": Priority.MEDIUM,
            },
        )
        self.assertRedirects(response, url)
        category.refresh_from_db()
        self.assertEqual((category.name, category.minimum_priority), ("Miscellaneous", Priority.MEDIUM))

        response = self.client.post(
            url,
            {
                "action": "update_rule",
                "rule_id": rule.pk,
                "category_id": category.pk,
                "location_code": "campus-a",
                "department_id": self.maintenance.pk,
                "precedence": 2,
            },
        )
        self.assertRedirects(response, url)
        rule.refresh_from_db()
        self.assertEqual((rule.location_code, rule.precedence), ("CAMPUS-A", 2))

        response = self.client.post(url, {"action": "deactivate_sla", "sla_id": sla.pk})
        self.assertRedirects(response, url)
        sla.refresh_from_db()
        self.assertFalse(sla.active)

        response = self.client.post(
            url,
            {
                "action": "create_escalation",
                "default_department_id": self.administration.pk,
                "interval_minutes": 1440,
                "maximum_level": 3,
            },
        )
        self.assertRedirects(response, url)
        self.assertTrue(EscalationPolicy.objects.filter(key="default").exists())
