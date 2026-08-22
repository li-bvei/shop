from django.conf import settings
from django.db import models


class StaffMember(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        INACTIVE = 'inactive', 'Inactive'

    class EmploymentType(models.TextChoices):
        REGULAR_MONTHLY = 'regular_monthly', 'Regular/monthly salaried'
        HOURLY = 'hourly', 'Hourly'
        TEMPORARY = 'temporary', 'Temporary'

    class WorkArea(models.TextChoices):
        KITCHEN = 'kitchen', 'Kitchen'
        HALL = 'hall', 'Hall'

    name = models.CharField(max_length=100)
    # Doubles as "default branch" for scheduling/shift assignment — a
    # dedicated field would just duplicate this with no behavioral
    # difference, since nothing here supports a staff member belonging to
    # more than one branch at once.
    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='staff_members')
    role = models.CharField(max_length=100, blank=True)
    work_area = models.CharField(max_length=10, choices=WorkArea.choices, default=WorkArea.HALL)
    phone = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    employment_type = models.CharField(
        max_length=20, choices=EmploymentType.choices, default=EmploymentType.REGULAR_MONTHLY,
        help_text='regular_monthly employees only have hours tracked this phase — wages are '
                   'only calculated for hourly/temporary staff.',
    )
    hire_date = models.DateField(null=True, blank=True)
    leave_date = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ['branch_id', 'name']

    def __str__(self):
        return self.name


class StaffTransfer(models.Model):
    """Append-only audit log of an employee moving from one branch to
    another *within the same Organization* — never editable or deletable
    through the normal API once created (StaffTransferViewSet only allows
    GET/POST). Creating one is the transfer: StaffTransferViewSet.
    perform_create also updates StaffMember.branch (and the linked login
    account's User.branch, if any) as part of the same request. Existing
    DailyReport/Shift/ActualWorkRecord/WageEmployeeResult rows are
    unaffected — they each store their own `branch` at the time they were
    created, not derived from the employee's *current* branch, so history
    correctly stays attributed to the branch it actually happened at."""

    employee = models.ForeignKey(StaffMember, on_delete=models.CASCADE, related_name='transfers')
    organization = models.ForeignKey('organizations.Organization', on_delete=models.PROTECT, related_name='staff_transfers')
    from_branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT, related_name='staff_transfers_from')
    to_branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT, related_name='staff_transfers_to')
    effective_date = models.DateField()
    reason = models.CharField(max_length=255, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at']

    def __str__(self):
        return f'{self.employee_id}: {self.from_branch_id} -> {self.to_branch_id} ({self.effective_date})'
