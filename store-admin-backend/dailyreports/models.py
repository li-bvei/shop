from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import models


class DailyReport(models.Model):
    """The current/live report for one branch+date. History snapshots are
    kept separately in DailyReportHistory so edits never lose provenance."""

    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='daily_reports')
    date = models.DateField()
    person_in_charge = models.ForeignKey(
        'staff.StaffMember', on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    total_revenue = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    total_customers = models.PositiveIntegerField(default=0)
    group_count = models.PositiveIntegerField(default=0)
    morning_revenue = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    morning_customers = models.PositiveIntegerField(default=0)
    morning_group_count = models.PositiveIntegerField(default=0)
    payment_amounts = models.JSONField(default=dict, blank=True)
    expenses = models.JSONField(default=list, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['branch', 'date'], name='unique_daily_report_per_branch_date'),
        ]
        ordering = ['-date']

    def __str__(self):
        return f'{self.branch_id} {self.date}'

    def save(self, *args, **kwargs):
        # Cash is always total revenue minus every other payment method,
        # matching the frontend's read-only cash field — never trust a
        # client-supplied value for it. payment_amounts is keyed by
        # PaymentMethodDef.id (a string, since JSON keys must be strings) —
        # not the literal 'cash', which stopped meaning anything once
        # payment methods became per-branch with their own numeric ids.
        from paymentmethods.models import PaymentMethodDef

        methods = {str(m.id): m for m in PaymentMethodDef.objects.filter(branch_id=self.branch_id)}
        cash_method = next((method for method in methods.values() if method.protected), None)
        cash_key = str(cash_method.id) if cash_method else None
        updated = {}
        non_cash = Decimal(0)
        for key, raw in (self.payment_amounts or {}).items():
            key = str(key)
            method = methods.get(key)
            if not method or method.protected:
                continue
            try:
                amount = Decimal(str(raw or 0))
            except (InvalidOperation, TypeError, ValueError):
                continue
            if amount < 0:
                continue
            updated[key] = int(amount)
            non_cash += amount
        # JSONField requires plain JSON-serializable values — Decimal isn't one.
        if cash_key:
            updated[cash_key] = int(self.total_revenue) - int(non_cash)
        self.payment_amounts = updated
        super().save(*args, **kwargs)


class DailyReportHistory(models.Model):
    """Append-only edit trail. `saved_at` and `edited_by` are always set from
    the request, never trusted from the client, so the "who/when" record the
    frontend requires can't be spoofed or backdated."""

    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='daily_report_history')
    date = models.DateField()
    saved_at = models.DateTimeField(auto_now_add=True)
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+'
    )
    edited_by_name = models.CharField(max_length=150, blank=True)
    person_in_charge = models.ForeignKey(
        'staff.StaffMember', on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    total_revenue = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    cash_remaining = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    data = models.JSONField()

    class Meta:
        ordering = ['-saved_at']
        verbose_name_plural = 'daily report history'

    def __str__(self):
        return f'{self.branch_id} {self.date} @ {self.saved_at}'
