from datetime import date, time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from branches.models import Branch
from scheduling.models import ActualWorkRecord, SchedulePeriod, Shift
from staff.models import StaffMember
from wages.calculation import generate_wage_results
from wages.models import WageMonthlyClosing, WageRule


DEMO_STAFF = (
    ('排班演示・厨房A', 'kitchen', 1200, 800, 1000),
    ('排班演示・厨房B', 'kitchen', 1250, 900, 1500),
    ('排班演示・前厅A', 'hall', 1150, 700, 500),
    ('排班演示・前厅B', 'hall', 1300, 1000, 2000),
)
PATTERN = ('morning', 'afternoon', 'full', 'off', 'morning', 'full', 'afternoon', 'off')


class Command(BaseCommand):
    help = 'Idempotently seed August 2026 scheduling/payroll demo data (DEBUG only).'

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('development-only-command')
        branch = Branch.objects.filter(code='shinsaibashi').first() or Branch.objects.filter(
            name_zh__icontains='心斋桥',
        ).first()
        if not branch:
            raise CommandError('shinsaibashi-branch-not-found')

        with transaction.atomic():
            period, _ = SchedulePeriod.objects.get_or_create(
                branch=branch, month=date(2026, 8, 1),
                defaults={'start_date': date(2026, 8, 1), 'end_date': date(2026, 8, 31)},
            )
            employees = []
            for name, area, rate, transport, _bonus in DEMO_STAFF:
                employee, _ = StaffMember.objects.update_or_create(
                    branch=branch, name=name,
                    defaults={
                        'work_area': area, 'role': '厨房' if area == 'kitchen' else '前厅',
                        'status': StaffMember.Status.ACTIVE,
                        'employment_type': StaffMember.EmploymentType.HOURLY,
                        'hire_date': date(2026, 8, 1),
                    },
                )
                WageRule.objects.update_or_create(
                    employee=employee, effective_from=date(2026, 8, 1),
                    defaults={
                        'hourly_rate': rate, 'transportation_type': WageRule.TransportationType.MONTHLY,
                        'transportation_amount': transport, 'note': 'seed_schedule_wage_demo',
                    },
                )
                employees.append(employee)

            slots = {
                'morning': (time(10, 30), time(15), 0),
                'afternoon': (time(17), time(22), 0),
                'full': (time(10, 30), time(22), 120),
            }
            for emp_index, employee in enumerate(employees):
                for day_index in range(8):
                    state = PATTERN[(day_index + emp_index) % len(PATTERN)]
                    work_date = date(2026, 8, day_index + 1)
                    if state == 'off':
                        continue
                    start, end, break_minutes = slots[state]
                    shift, _ = Shift.objects.update_or_create(
                        period=period, employee=employee, work_date=work_date,
                        defaults={
                            'branch': branch, 'planned_start': start, 'planned_end': end,
                            'planned_break_minutes': break_minutes, 'position': employee.work_area,
                        },
                    )
                    actual_start = start
                    actual_end = end
                    reason = ''
                    if emp_index == 0 and day_index == 0:
                        actual_start, reason = time(10, 45), '演示：实际晚到15分钟'
                    if emp_index == 1 and day_index == 1:
                        actual_end, reason = time(22, 30), '演示：实际晚下班30分钟'
                    ActualWorkRecord.objects.update_or_create(
                        employee=employee, work_date=work_date,
                        defaults={
                            'shift': shift, 'branch': branch, 'actual_start': actual_start,
                            'actual_end': actual_end, 'actual_break_minutes': break_minutes,
                            'absent': False, 'adjustment_reason': reason,
                            'status': ActualWorkRecord.Status.MANAGER_CONFIRMED,
                            'confirmed_at': timezone.now(),
                        },
                    )
            period.status = SchedulePeriod.Status.PUBLISHED
            period.save(update_fields=['status'])
            closing, _ = WageMonthlyClosing.objects.get_or_create(branch=branch, month=date(2026, 8, 1))
            demo_result_count = closing.employee_results.filter(employee__in=employees).count()
            if closing.status == WageMonthlyClosing.Status.LOCKED:
                raise CommandError('demo-wage-closing-is-not-draft')
            if closing.status == WageMonthlyClosing.Status.CONFIRMED and closing.employee_results.exists() and demo_result_count != len(employees):
                raise CommandError('confirmed-closing-already-contains-non-demo-results')
            # A pre-existing empty confirmed demo placeholder is supported:
            # populate it once, preserve its status, then make repeat runs a
            # strict no-op for payroll. A locked or populated real closing is
            # never rewritten.
            if closing.status == WageMonthlyClosing.Status.DRAFT or demo_result_count != len(employees):
                generate_wage_results(closing)
                for employee, spec in zip(employees, DEMO_STAFF):
                    result = closing.employee_results.get(employee=employee)
                    result.bonus_amount = spec[4]
                    result.bonus_note = '排班工资演示奖金'
                    result.estimated_total = result.base_amount + result.transportation_amount + result.bonus_amount
                    result.save(update_fields=['bonus_amount', 'bonus_note', 'estimated_total'])
                closing.last_generated_at = timezone.now()
                closing.save(update_fields=['last_generated_at'])

        self.stdout.write(self.style.SUCCESS(
            f'demo ready: branch={branch.id}, employees={len(employees)}, period={period.id}, closing={closing.id}',
        ))
