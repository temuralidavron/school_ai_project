from django.db import models
from apps.common.models import BaseModel


class Classifier(BaseModel):
    hemis_id = models.BigIntegerField(null=True, blank=True)
    name = models.CharField(max_length=255, null=True, blank=True)
    classifier = models.CharField(max_length=255, null=True, blank=True)
    version = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "classifier"

    def __str__(self):
        return self.name or f"Classifier {self.pk}"


class Reference(BaseModel):
    hemis_id = models.CharField(max_length=255, null=True, blank=True)
    code = models.CharField(max_length=255, null=True, blank=True)
    name = models.CharField(max_length=255, null=True, blank=True)
    parent = models.CharField(max_length=255, null=True, blank=True)
    active = models.BooleanField(null=True, blank=True)
    extra_data = models.JSONField(null=True, blank=True)
    classifier = models.ForeignKey(
        Classifier,
        on_delete=models.SET_NULL,
        db_column="classifier_id",
        null=True,
        blank=True,
        related_name="references",
    )

    class Meta:
        db_table = "reference"

    def __str__(self):
        return self.name or f"Reference {self.pk}"


class Department(BaseModel):
    hemis_id = models.BigIntegerField(null=True, blank=True)
    name = models.CharField(max_length=255, null=True, blank=True)
    code = models.CharField(max_length=255, null=True, blank=True)
    parent = models.BigIntegerField(null=True, blank=True)
    active = models.BooleanField(null=True, blank=True)
    locality_type = models.ForeignKey(
        Reference,
        on_delete=models.SET_NULL,
        db_column="localityType_id",
        null=True,
        blank=True,
        related_name="department_locality_types",
    )
    structure_type = models.ForeignKey(
        Reference,
        on_delete=models.SET_NULL,
        db_column="structureType_id",
        null=True,
        blank=True,
        related_name="department_structure_types",
    )

    class Meta:
        db_table = "department"

    def __str__(self):
        return self.name or f"Department {self.pk}"


class University(BaseModel):
    name = models.CharField(max_length=255, null=True, blank=True)
    api_key = models.CharField(max_length=255, null=True, blank=True)
    api_url = models.CharField(max_length=255, null=True, blank=True)
    logo = models.CharField(max_length=255, null=True, blank=True)
    location = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "university"

    def __str__(self):
        return self.name or f"University {self.pk}"


class Subject(BaseModel):
    hemis_id = models.BigIntegerField(null=True, blank=True)
    code = models.CharField(max_length=255, null=True, blank=True)
    name = models.CharField(max_length=255, null=True, blank=True)
    active = models.BooleanField(null=True, blank=True)
    education_type = models.ForeignKey(
        Reference,
        on_delete=models.SET_NULL,
        db_column="educationType_id",
        null=True,
        blank=True,
        related_name="subject_education_types",
    )
    subject_group = models.ForeignKey(
        Reference,
        on_delete=models.SET_NULL,
        db_column="subjectGroup_id",
        null=True,
        blank=True,
        related_name="subject_groups",
    )

    class Meta:
        db_table = "subject"

    def __str__(self):
        return self.name or f"Subject {self.pk}"


class Employee(BaseModel):
    hemis_id = models.BigIntegerField(null=True, blank=True)
    full_name = models.CharField(max_length=255, null=True, blank=True)
    first_name = models.CharField(max_length=255, null=True, blank=True)
    second_name = models.CharField(max_length=255, null=True, blank=True)
    third_name = models.CharField(max_length=255, null=True, blank=True)
    short_name = models.CharField(max_length=255, null=True, blank=True)
    birth_date = models.BigIntegerField(null=True, blank=True)
    contract_date = models.BigIntegerField(null=True, blank=True)
    contract_number = models.CharField(max_length=255, null=True, blank=True)
    decree_date = models.BigIntegerField(null=True, blank=True)
    decree_number = models.CharField(max_length=255, null=True, blank=True)
    employee_id_number = models.CharField(max_length=255, null=True, blank=True)
    hash = models.CharField(max_length=255, null=True, blank=True)
    image = models.CharField(max_length=255, null=True, blank=True)
    meta_id = models.BigIntegerField(null=True, blank=True)
    speciality = models.CharField(max_length=255, null=True, blank=True)
    year_of_enter = models.BigIntegerField(null=True, blank=True)
    hemis_status = models.CharField(max_length=16)

    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="employees")
    faculty = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="faculty_employees", db_column="faculty_id")
    academic_degree = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="employee_academic_degrees", db_column="academicDegree_id")
    academic_rank = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="employee_academic_ranks", db_column="academicRank_id")
    employee_status = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="employee_statuses", db_column="employeeStatus_id")
    employee_type = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="employee_types", db_column="employeeType_id")
    employment_form = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="employee_employment_forms", db_column="employmentForm_id")
    employment_staff = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="employee_employment_staffs", db_column="employmentStaff_id")
    gender = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="employee_genders")
    staff_position = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="employee_staff_positions", db_column="staffPosition_id")

    class Meta:
        db_table = "employee"

    def __str__(self):
        return self.full_name or f"Employee {self.pk}"


class Group(BaseModel):
    hemis_id = models.BigIntegerField(null=True, blank=True)
    name = models.CharField(max_length=255, null=True, blank=True)
    hemis_status = models.CharField(max_length=16)

    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="groups")
    specialty = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="group_specialties")
    tutor = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name="tutor_groups")

    class Meta:
        db_table = "group"

    def __str__(self):
        return self.name or f"Group {self.pk}"


class Student(BaseModel):
    hemis_id = models.BigIntegerField(null=True, blank=True)
    curriculum_id = models.BigIntegerField(null=True, blank=True)
    full_name = models.CharField(max_length=255, null=True, blank=True)
    avg_gpa = models.FloatField(null=True, blank=True)
    avg_grade = models.FloatField(null=True, blank=True)
    birth_date = models.BigIntegerField(null=True, blank=True)
    student_id_number = models.CharField(max_length=255, null=True, blank=True)
    first_name = models.CharField(max_length=255, null=True, blank=True)
    second_name = models.CharField(max_length=255, null=True, blank=True)
    third_name = models.CharField(max_length=255, null=True, blank=True)
    short_name = models.CharField(max_length=255, null=True, blank=True)
    hash = models.CharField(max_length=255, null=True, blank=True)
    image = models.CharField(max_length=255, null=True, blank=True)
    is_graduate = models.BooleanField(null=True, blank=True)
    other = models.CharField(max_length=255, null=True, blank=True)
    roommate_count = models.BigIntegerField(null=True, blank=True)
    total_acload = models.BigIntegerField(null=True, blank=True)
    total_credit = models.BigIntegerField(null=True, blank=True)
    validate_url = models.CharField(max_length=255, null=True, blank=True)
    year_of_enter = models.BigIntegerField(null=True, blank=True)
    hemis_status = models.CharField(max_length=16)

    accommodation = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_accommodations")
    citizenship = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_citizenships")
    country = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_countries")
    current_district = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_current_districts", db_column="currentDistrict_id")
    current_province = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_current_provinces", db_column="currentProvince_id")
    current_terrain = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_current_terrains", db_column="currentTerrain_id")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="students")
    district = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_districts")
    education_form = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_education_forms", db_column="educationForm_id")
    education_type = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_education_types", db_column="educationType_id")
    education_year = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_education_years", db_column="educationYear_id")
    gender = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_genders")
    level = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_levels")
    payment_form = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_payment_forms", db_column="paymentForm_id")
    province = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_provinces")
    semester = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_semesters")
    social_category = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_social_categories", db_column="socialCategory_id")
    specialty = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_specialties")
    student_status = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_statuses", db_column="studentStatus_id")
    student_type = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_types", db_column="studentType_id")
    terrain = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_terrains")
    university = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_universities")
    group = models.ForeignKey(Group, on_delete=models.SET_NULL, null=True, blank=True, related_name="students")

    class Meta:
        db_table = "student"

    def __str__(self):
        return self.full_name or f"Student {self.pk}"


class Schedule(BaseModel):
    hemis_id = models.BigIntegerField(null=True, blank=True)
    lesson_pair = models.JSONField(null=True, blank=True, db_column="lessonPair")
    lesson_date = models.BigIntegerField(null=True, blank=True)
    hemis_status = models.CharField(max_length=16)

    auditorium = models.ForeignKey(
        "cameras.Auditorium",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="schedules",
    )
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="schedules")
    employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name="schedules")
    faculty = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="faculty_schedules", db_column="faculty_id")
    semester = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="schedule_semesters")
    training_type = models.ForeignKey(Reference, on_delete=models.SET_NULL, null=True, blank=True, related_name="schedule_training_types", db_column="trainingType_id")
    group = models.ForeignKey(Group, on_delete=models.SET_NULL, null=True, blank=True, related_name="schedules")
    subject = models.ForeignKey(Subject, on_delete=models.SET_NULL, null=True, blank=True, related_name="schedules")

    class Meta:
        db_table = "schedule"