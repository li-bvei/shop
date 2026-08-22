from django.db import transaction
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from common.permissions import BranchScopedQuerysetMixin

from .models import PaymentMethodDef
from .serializers import PaymentMethodDefSerializer


class PaymentMethodDefViewSet(BranchScopedQuerysetMixin, viewsets.ModelViewSet):
    """Per-branch master data. BranchScopedQuerysetMixin already keeps a
    branch account's list/retrieve/update/delete confined to its own rows
    (anything outside that queryset 404s) and forces `branch` to the
    caller's own on create. perform_update below closes the one gap the
    mixin doesn't cover: a branch account editing a row it does own could
    otherwise still smuggle a different `branch` value through the same
    PATCH and walk the record out to another branch."""

    queryset = PaymentMethodDef.objects.all()
    serializer_class = PaymentMethodDefSerializer
    filterset_fields = ['branch']

    def perform_update(self, serializer):
        serializer.save(branch=serializer.instance.branch)

    def perform_destroy(self, instance):
        if instance.protected:
            raise ValidationError('this payment method cannot be deleted.')
        instance.delete()

    @action(detail=False, methods=['post'])
    def reorder(self, request):
        """Atomically rewrites sort_order for one branch's full payment
        method list from a dragged-and-dropped id order. `order` must be
        exactly the branch's existing ids, each once — a partial list would
        leave the rest with stale/colliding sort_order values, and any id
        this account can't already see (wrong branch, wrong Organization)
        is silently excluded from `qs` by BranchScopedQuerysetMixin, which
        then fails the "exactly the existing ids" check instead of quietly
        reordering someone else's branch."""
        branch_id = request.data.get('branch')
        order = request.data.get('order')
        if not branch_id or not isinstance(order, list) or not order:
            raise ValidationError({'order': ['branch and a non-empty order list of ids are required.']})

        try:
            order_ids = [int(pk) for pk in order]
        except (TypeError, ValueError):
            raise ValidationError({'order': ['Must be a list of ids.']})
        if len(order_ids) != len(set(order_ids)):
            raise ValidationError({'order': ['Duplicate ids are not allowed.']})

        qs = self.get_queryset().filter(branch_id=branch_id)
        objects_by_id = {obj.id: obj for obj in qs}
        if set(order_ids) != set(objects_by_id.keys()):
            raise ValidationError(
                {'order': ['Must include exactly the existing payment methods for this branch, each exactly once.']},
            )

        with transaction.atomic():
            for index, pk in enumerate(order_ids):
                objects_by_id[pk].sort_order = index
            PaymentMethodDef.objects.bulk_update(objects_by_id.values(), ['sort_order'])

        result = PaymentMethodDef.objects.filter(branch_id=branch_id).order_by('sort_order', 'code')
        return Response(self.get_serializer(result, many=True).data)
