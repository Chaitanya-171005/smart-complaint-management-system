from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

NEVER_DELETED = "Reference data is deactivated, never deleted (BR-05, REQ-ADM-01)."


class ReferenceQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError(NEVER_DELETED)


class Department(models.Model):
    """Administrator-managed department, retained by deactivation (BR-05)."""

    name = models.CharField(max_length=50, unique=True)
    active = models.BooleanField(default=True)

    objects = ReferenceQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(Lower("name"), name="department_name_ci_unique"),
        ]

    def delete(self, *args, **kwargs):
        raise ValidationError(NEVER_DELETED)

    def __str__(self):
        return self.name


class Location(models.Model):
    """Administrator-managed campus location (SRS B-2: block 20, floor 10, room/area 30).

    ``code`` is the stable canonical location code other modules store and route on
    (B17 normalizes routing codes with strip().upper(); this does the same). A renamed
    block or room keeps its code.
    """

    code = models.CharField(max_length=100, unique=True)
    block = models.CharField(max_length=20)
    floor = models.CharField(max_length=10, blank=True)
    room_area = models.CharField(max_length=30)
    active = models.BooleanField(default=True)

    objects = ReferenceQuerySet.as_manager()

    class Meta:
        ordering = ["block", "floor", "room_area", "pk"]
        constraints = [
            models.UniqueConstraint(
                Lower("block"), Lower("floor"), Lower("room_area"),
                name="location_place_ci_unique",
            ),
        ]

    @staticmethod
    def normalize_code(value):
        return (value or "").strip().upper()

    def save(self, *args, **kwargs):
        self.code = self.normalize_code(self.code)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(NEVER_DELETED)

    @property
    def label(self):
        return " / ".join(v for v in (self.block, self.floor, self.room_area) if v)

    def __str__(self):
        return f"{self.code} ({self.label})"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", "ADMIN")
        if extra.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    """Single custom user model for SCMS (REQ-AUTH-01, REQ-ACC-01, BR-04)."""

    class Role(models.TextChoices):
        COMPLAINANT = "COMPLAINANT", "Complainant"
        STAFF = "STAFF", "Department Staff"
        HEAD = "HEAD", "Department Head"
        ADMIN = "ADMIN", "Administrator"

    class UserType(models.TextChoices):
        STUDENT = "STUDENT", "Student"
        FACULTY = "FACULTY", "Faculty"
        STAFF = "STAFF", "Non-teaching staff"

    username = None
    email = models.EmailField(max_length=120, unique=True)
    full_name = models.CharField(max_length=100)
    user_type = models.CharField(
        max_length=20, choices=UserType.choices, default=UserType.STUDENT
    )
    hostel_block = models.CharField(max_length=20, blank=True)
    hostel_room = models.CharField(max_length=10, blank=True)
    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.COMPLAINANT
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.PROTECT
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]
    objects = UserManager()

    class Meta(AbstractUser.Meta):
        constraints = [
            # Email is unique in the database, ignoring case, so an account created
            # outside the registration form (admin, shell) cannot duplicate one either.
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique"),
        ]

    def __str__(self):
        return self.email


class LoginThrottle(models.Model):
    """Failed-login counter and lockout state per login identifier (REQ-AUTH-02).

    Keyed by the lower-cased email that was typed, whether or not an account
    exists, so a lockout looks identical for known and unknown emails and does
    not reveal which accounts exist (REQ-SEC-06).
    """

    email = models.CharField(max_length=254, unique=True)
    failure_count = models.PositiveIntegerField(default=0)
    window_start = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"throttle:{self.email}"


class SecurityEvent(models.Model):
    """Append-only security event record (REQ-SEC-08).

    Never stores passwords, session tokens or anonymous-report references.
    The final event policy is owned by Q03; this covers authentication events.
    """

    class EventType(models.TextChoices):
        LOGIN_SUCCESS = "LOGIN_SUCCESS", "Login success"
        LOGIN_FAILURE = "LOGIN_FAILURE", "Login failure"
        LOGIN_LOCKOUT = "LOGIN_LOCKOUT", "Lockout started"
        LOGIN_BLOCKED = "LOGIN_BLOCKED", "Login refused during lockout"
        AUTHORIZATION_REFUSED = "AUTHORIZATION_REFUSED", "Authorization refused"
        ROLE_CHANGED = "ROLE_CHANGED", "Role or department membership changed"
        ROLE_CHANGE_REFUSED = "ROLE_CHANGE_REFUSED", "Role or membership change refused"

    event_type = models.CharField(max_length=30, choices=EventType.choices)
    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    identifier = models.CharField(max_length=254, blank=True)
    detail = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.event_type} {self.identifier}"


class ConfigAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Configuration audit records cannot be edited.")

    def delete(self):
        raise ValidationError("Configuration audit records cannot be deleted.")


class ConfigAuditEvent(models.Model):
    """Append-only record of an administrative configuration change (REQ-ADM-04, B29).

    Separate from complaint history (workflow.ComplaintHistory). Stores the acting
    Administrator, the entity, old/new values and the time; never credentials.
    """

    class Action(models.TextChoices):
        CREATE = "CREATE", "Created"
        UPDATE = "UPDATE", "Edited"
        DEACTIVATE = "DEACTIVATE", "Deactivated"
        REACTIVATE = "REACTIVATE", "Reactivated"

    actor = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor_identifier = models.CharField(max_length=254)
    entity_type = models.CharField(max_length=50, db_index=True)
    entity_id = models.CharField(max_length=50)
    action = models.CharField(max_length=12, choices=Action.choices)
    old_values = models.JSONField(default=dict, blank=True)
    new_values = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = ConfigAuditQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Configuration audit records cannot be edited.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Configuration audit records cannot be deleted.")

    def __str__(self):
        return f"{self.action} {self.entity_type}#{self.entity_id}"
