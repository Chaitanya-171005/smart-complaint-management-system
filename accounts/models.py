from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


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
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150)
    user_type = models.CharField(
        max_length=10, choices=UserType.choices, default=UserType.STUDENT
    )
    hostel_block = models.CharField(max_length=20, blank=True)
    hostel_room = models.CharField(max_length=20, blank=True)
    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.COMPLAINANT
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.PROTECT
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]
    objects = UserManager()

    def __str__(self):
        return self.email
