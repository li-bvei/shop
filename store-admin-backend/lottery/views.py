from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from .models import DabingPerson, DabingRecord, DabingStore, KyotoDrawBatch, KyotoPerson, KyotoRecord
from .serializers import (
    DabingPersonSerializer,
    DabingRecordSerializer,
    DabingStoreSerializer,
    KyotoDrawBatchSerializer,
    KyotoPersonSerializer,
    KyotoRecordSerializer,
)


class OrganizationScopedViewSet(viewsets.ModelViewSet):
    """Lottery is an organization-level module, intentionally independent
    from the existing operational Branch model."""

    # Lottery work is shared across the organization. Staff accounts are
    # allowed here explicitly, while every queryset still remains tenant
    # scoped below.
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return super().get_queryset().filter(organization_id=self.request.user.organization_id)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class DabingStoreViewSet(OrganizationScopedViewSet):
    serializer_class = DabingStoreSerializer
    queryset = DabingStore.objects.all()
    filterset_fields = ['is_active']

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        if not qs.exists():
            for index, name in enumerate(('天王寺', '高岛屋', '梅田')):
                DabingStore.objects.get_or_create(
                    organization=request.user.organization, name=name,
                    defaults={'sort_order': index},
                )
            qs = self.get_queryset()
        return super().list(request, *args, **kwargs)


class DabingPersonViewSet(OrganizationScopedViewSet):
    serializer_class = DabingPersonSerializer
    queryset = DabingPerson.objects.all()
    filterset_fields = ['is_active']

    def get_queryset(self):
        qs = super().get_queryset()
        keyword = self.request.query_params.get('search', '').strip()
        if keyword:
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=keyword) | Q(phone__icontains=keyword))
        return qs


class DabingRecordViewSet(OrganizationScopedViewSet):
    serializer_class = DabingRecordSerializer
    queryset = DabingRecord.objects.select_related('store', 'person', 'created_by').all()
    filterset_fields = ['store', 'draw_date', 'person']

    def perform_create(self, serializer):
        person = serializer.validated_data['person']
        store = serializer.validated_data['store']
        if not store.is_active:
            raise ValidationError({'store': ['store-inactive']})
        if DabingRecord.objects.filter(
            organization=self.request.user.organization,
            store=store,
            person=person,
            draw_date=serializer.validated_data['draw_date'],
            draw_time=serializer.validated_data.get('draw_time', ''),
        ).exists():
            raise ValidationError({'code': ['record-already-exists']})
        serializer.save(
            organization=self.request.user.organization,
            phone_snapshot=person.phone,
            contact_snapshot=person.contact,
            mobile_model_snapshot=person.mobile_model,
            birthday_snapshot=person.birthday,
            created_by=self.request.user,
        )

    def perform_update(self, serializer):
        person = serializer.validated_data.get('person', serializer.instance.person)
        store = serializer.validated_data.get('store', serializer.instance.store)
        if not store.is_active:
            raise ValidationError({'store': ['store-inactive']})
        serializer.save(
            store=store,
            person=person,
            phone_snapshot=person.phone,
            contact_snapshot=person.contact,
            mobile_model_snapshot=person.mobile_model,
            birthday_snapshot=person.birthday,
        )


class KyotoPersonViewSet(OrganizationScopedViewSet):
    serializer_class = KyotoPersonSerializer
    queryset = KyotoPerson.objects.all()
    filterset_fields = ['is_active']

    def get_queryset(self):
        qs = super().get_queryset()
        keyword = self.request.query_params.get('search', '').strip()
        if keyword:
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=keyword) | Q(phone__icontains=keyword))
        return qs


class KyotoDrawBatchViewSet(OrganizationScopedViewSet):
    serializer_class = KyotoDrawBatchSerializer
    queryset = KyotoDrawBatch.objects.all()
    filterset_fields = ['is_active', 'publish_date']


class KyotoRecordViewSet(OrganizationScopedViewSet):
    serializer_class = KyotoRecordSerializer
    queryset = KyotoRecord.objects.select_related('batch', 'person', 'created_by').all()
    filterset_fields = ['batch', 'person']

    def perform_create(self, serializer):
        person = serializer.validated_data['person']
        batch = serializer.validated_data['batch']
        if not batch.is_active:
            raise ValidationError({'batch': ['batch-inactive']})
        if KyotoRecord.objects.filter(
            organization=self.request.user.organization, batch=batch, person=person,
        ).exists():
            raise ValidationError({'code': ['record-already-exists']})
        serializer.save(
            organization=self.request.user.organization,
            phone_snapshot=person.phone,
            created_by=self.request.user,
        )

    def perform_update(self, serializer):
        person = serializer.validated_data.get('person', serializer.instance.person)
        batch = serializer.validated_data.get('batch', serializer.instance.batch)
        if not batch.is_active:
            raise ValidationError({'batch': ['batch-inactive']})
        serializer.save(batch=batch, person=person, phone_snapshot=person.phone)
