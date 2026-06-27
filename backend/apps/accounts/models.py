"""Custom user model — email login, admin-approval gating, Auth0 migration fields.

Replaces the R app's Auth0-only identity. A new user is inactive until they
verify their email AND a Platform Admin approves them and assigns use-case
roles (see apps.rbac.UseCaseMembership). The ``legacy_eia_apps`` / ``auth0_sub``
fields support the one-time migration off Auth0 (see Phase 9).
"""
from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra):
        if not email:
            raise ValueError("Users must have an email address")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        extra.setdefault("is_active", False)  # pending approval by default
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_active", True)
        extra.setdefault("email_verified", True)
        if extra.get("is_staff") is not True or extra.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_staff=True and is_superuser=True")
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Stable, human-readable platform identity. The mobile app stamps this on each
    # submission so a collector's data links to their account (see collected_by).
    user_id = models.CharField(max_length=16, unique=True, blank=True)
    # The institution this user belongs to (one user → one organization). A hub
    # operator (superuser) has none and spans all tenants. Set when the user is
    # first granted access (their first membership's scope determines the org).
    organization = models.ForeignKey(
        "usecases.Organization", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="users",
    )
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=32, blank=True)

    is_staff = models.BooleanField(default=False)
    # Inactive until email-verified AND admin-approved.
    is_active = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)

    approved_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_users"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # --- Auth0 migration support (Phase 9) ---
    auth0_sub = models.CharField(max_length=255, null=True, blank=True, unique=True)
    legacy_eia_apps = models.JSONField(default=dict, blank=True)

    last_login_country = models.CharField(max_length=8, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        ordering = ["email"]

    def save(self, *args, **kwargs):
        if not self.user_id:
            self.user_id = self._new_user_id()
        super().save(*args, **kwargs)

    @staticmethod
    def _new_user_id() -> str:
        return "U-" + uuid.uuid4().hex[:8].upper()

    def __str__(self) -> str:
        return self.email

    @property
    def is_platform_admin(self) -> bool:
        """Platform Admin = Django superuser (global control)."""
        return self.is_superuser

    def approve(self, by: User) -> None:
        self.is_active = True
        self.approved_by = by
        self.approved_at = timezone.now()
        self.save(update_fields=["is_active", "approved_by", "approved_at", "updated_at"])


class UserProfile(models.Model):
    """The 'register once' identity captured in-app instead of via the ODK
    00_RegisterEnumerator form in the field — demographics, contact and consents
    a user provides a single time and the platform reuses everywhere.
    """

    class Gender(models.TextChoices):
        FEMALE = "female", "Female"
        MALE = "male", "Male"
        OTHER = "other", "Other / prefer not to say"

    class Education(models.TextChoices):
        NO_SCHOOL = "no_school", "No school"
        PRIMARY = "primary", "Primary"
        SECONDARY = "secondary", "Secondary (high school or academy)"
        POST_SECONDARY = "post_secondary", "Post-secondary (college / university)"
        ADULT = "adult_education", "Adult education / literacy / religious school"
        NO_ANSWER = "no_answer", "No answer / prefer not to say"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")

    # Name parts (User.full_name stays the display name, kept in sync on save).
    first_name = models.CharField(max_length=128, blank=True)
    second_name = models.CharField(max_length=128, blank=True)
    family_name = models.CharField(max_length=128, blank=True)

    gender = models.CharField(max_length=8, choices=Gender.choices, blank=True)
    age = models.PositiveSmallIntegerField(null=True, blank=True)
    education_level = models.CharField(max_length=20, choices=Education.choices, blank=True)

    phone_alt = models.CharField(max_length=32, blank=True)
    country = models.CharField(max_length=64, blank=True)
    # The physical Enumerator card barcode assigned in the field (13 chars), if any.
    enumerator_card_id = models.CharField(max_length=32, blank=True)

    consent_personal_info = models.BooleanField(default=False)
    consent_followup = models.BooleanField(default=False)
    consent_photos = models.BooleanField(default=False)

    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Profile of {self.user.email}"

    @property
    def is_complete(self) -> bool:
        return self.completed_at is not None

    def mark_complete(self) -> None:
        self.completed_at = timezone.now()
        # Keep the account's display name in sync with the name parts.
        parts = [self.first_name, self.second_name, self.family_name]
        full = " ".join(p for p in parts if p).strip()
        if full and full != self.user.full_name:
            self.user.full_name = full
            self.user.save(update_fields=["full_name", "updated_at"])
        self.save()
