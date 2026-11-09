from dataclasses import FrozenInstanceError

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from accounts.models import ConfigAuditEvent, Department, Location
from routing.models import Category, EscalationPolicy, RoutingDecision, RoutingRule
from routing.resolver import RoutingConfigurationError, route_and_record, route_complaint


class ResolverTests(TestCase):
    def setUp(self):
        self.category = Category.objects.get(name="Electrical")
        self.other = Category.objects.get(name="Other")
        self.department = Department.objects.create(name="Maintenance")
        self.default = Department.objects.create(name="Administration")
        self.policy = EscalationPolicy.objects.create(default_department=self.default, interval_minutes=60, maximum_level=3)
        Location.objects.create(code="HOSTEL-A", block="Hostel", room_area="A")

    def rule(self, category=None, location="", precedence=100, department=None, active=True):
        return RoutingRule.objects.create(category=category, location_code=location, precedence=precedence,
                                          department=department or self.department, active=active)

    def test_tiers_and_normalization(self):
        location = self.rule(location="HOSTEL-A", precedence=1)
        category = self.rule(category=self.category, precedence=5)
        combined = self.rule(category=self.category, location="HOSTEL-A", precedence=100)
        self.assertEqual(route_complaint(self.category, "  hostel-a ").rule, combined)
        combined.active = False
        combined.save()
        self.assertEqual(route_complaint(self.category, "HOSTEL-A").rule, category)
        self.assertEqual(route_complaint(self.other, "HOSTEL-A").rule, location)
        self.assertEqual(route_complaint(None, "HOSTEL-A").rule, location)
        self.assertEqual(route_complaint(self.category, " ").rule, category)
        self.assertTrue(route_complaint(self.other, "").used_default)

    def test_ordering_inside_tier(self):
        # Active scope uniqueness normally prevents these legacy/inconsistent rows.
        first = self.rule(category=self.category, precedence=5)
        second = RoutingRule(category=self.category, department=self.department, precedence=1, scope_key="legacy-1")
        third = RoutingRule(category=self.category, department=self.department, precedence=1, scope_key="legacy-2")
        RoutingRule.objects.bulk_create([second, third])
        self.assertEqual(route_complaint(self.category, "").rule, second)
        RoutingRule.objects.filter(pk=second.pk).update(precedence=5)
        self.assertEqual(route_complaint(self.category, "").rule, third)
        RoutingRule.objects.filter(pk=third.pk).update(active=False)
        self.assertEqual(route_complaint(self.category, "").rule, first)

    def test_inactive_department_and_rule_fallback(self):
        self.rule(category=self.category, location="HOSTEL-A", active=False)
        inactive = Department.objects.create(name="Inactive", active=False)
        self.rule(category=self.category, department=inactive)
        location = self.rule(location="HOSTEL-A")
        self.assertEqual(route_complaint(self.category, "HOSTEL-A").rule, location)
        self.assertTrue(route_complaint(self.category, "").unrouted)

    def test_default_and_missing_configuration(self):
        result = route_complaint(self.category, "")
        self.assertEqual((result.department, result.rule, result.basis, result.used_default, result.unrouted),
                         (self.default, None, "DEFAULT", True, True))
        self.default.active = False
        self.default.save()
        with self.assertRaises(RoutingConfigurationError):
            route_complaint(self.category, "")
        self.policy.delete()
        with self.assertRaises(RoutingConfigurationError):
            route_complaint(self.category, "")

    def test_read_only_query_counts_and_frozen(self):
        self.rule(category=self.category)
        counts = [model.objects.count() for model in (RoutingRule, RoutingDecision, ConfigAuditEvent)]
        with self.assertNumQueries(1):
            result = route_complaint(self.category, "")
        with self.assertNumQueries(2):
            route_complaint(self.other, "HOSTEL-A")
        self.assertEqual(counts, [model.objects.count() for model in (RoutingRule, RoutingDecision, ConfigAuditEvent)])
        with self.assertRaises(FrozenInstanceError):
            result.basis = "DEFAULT"

    def test_record_and_guards(self):
        rule = self.rule(category=self.category)
        with self.assertRaises(ValueError):
            route_and_record("bad", self.category, "")
        with self.assertRaises(ValueError):
            route_and_record("SCMS-٢٠٢٦-000001", self.category, "")
        decision = route_and_record("SCMS-2026-000001", self.category, "")
        with self.assertRaises(IntegrityError), transaction.atomic():
            route_and_record("SCMS-2026-000001", self.category, "")
        for action in (lambda: decision.save(), lambda: decision.delete(),
                       lambda: RoutingDecision.objects.filter(pk=decision.pk).update(reason="changed"),
                       lambda: RoutingDecision.objects.filter(pk=decision.pk).delete()):
            with self.assertRaises(ValidationError):
                action()
        for basis, selected_rule, unrouted in (("DEFAULT", rule, True), ("CATEGORY", None, False)):
            with self.assertRaises(IntegrityError), transaction.atomic():
                RoutingDecision.objects.create(complaint_id="SCMS-2026-000002", department=self.department,
                    rule=selected_rule, basis=basis, unrouted=unrouted, reason="test", decided_at=timezone.now())


class TransactionGuardTests(TransactionTestCase):
    def test_requires_transaction(self):
        from django.db.transaction import TransactionManagementError
        with self.assertRaises(TransactionManagementError):
            route_and_record("SCMS-2026-000001", None, "")
