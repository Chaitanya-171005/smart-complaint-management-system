from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


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
