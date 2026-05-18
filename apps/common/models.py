from django.db import models
from django.utils import timezone


class BaseModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'updated_at' not in update_fields:
            kwargs['update_fields'] = list(update_fields) + ['updated_at']
        super().save(*args, **kwargs)

    class Meta:
        abstract = True


class Permission(BaseModel):
    name = models.TextField()
    source = models.TextField()
    description = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "permissions"

    def __str__(self):
        return self.name


class Role(BaseModel):
    name = models.TextField()
    color = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "roles"

    def __str__(self):
        return self.name


class User(BaseModel):
    PROFILE_TYPES = (
        ("student", "Student"),
        ("employee", "Employee"),
        ("admin", "Admin"),
        ("other", "Other"),
    )

    username = models.TextField(unique=True)
    email = models.TextField(unique=True, null=True, blank=True)
    hashed_password = models.TextField()
    is_active = models.BooleanField(null=True, blank=True)
    is_verified = models.BooleanField(null=True, blank=True)
    last_login = models.DateTimeField(null=True, blank=True)
    password_last_updated = models.DateTimeField(null=True, blank=True)
    failed_login_attempts = models.IntegerField(null=True, blank=True)
    is_deleted = models.BooleanField(null=True, blank=True)
    image_verified = models.BooleanField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    profile_type = models.CharField(max_length=16, choices=PROFILE_TYPES)
    employee = models.ForeignKey(
        "academics.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
    )
    student = models.ForeignKey(
        "academics.Student",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
    )

    class Meta:
        db_table = "users"
        constraints = [
            models.UniqueConstraint(fields=["employee"], name="users_employee_id_key"),
            models.UniqueConstraint(fields=["student"], name="users_student_id_key"),
        ]

    def __str__(self):
        return self.username


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="role_permissions")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name="permission_roles")

    class Meta:
        db_table = "role_permissions"
        constraints = [
            models.UniqueConstraint(fields=["role", "permission"], name="role_permissions_role_permission_uniq"),
        ]


class UserPermission(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_permissions")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name="permission_users")

    class Meta:
        db_table = "user_permissions"
        constraints = [
            models.UniqueConstraint(fields=["user", "permission"], name="user_permissions_user_permission_uniq"),
        ]


class UserRole(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_roles")
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="role_users")

    class Meta:
        db_table = "user_roles"
        constraints = [
            models.UniqueConstraint(fields=["user", "role"], name="user_roles_user_role_uniq"),
        ]


class UserRoleScope(BaseModel):
    is_active = models.BooleanField(default=True)
    department = models.ForeignKey(
        "academics.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_role_scopes",
    )
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="scopes")
    speciality = models.ForeignKey(
        "academics.Reference",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_role_scopes",
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="scopes")

    class Meta:
        db_table = "user_role_scopes"