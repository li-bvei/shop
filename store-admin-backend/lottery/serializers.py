from rest_framework import serializers

from .models import DabingPerson, DabingRecord, DabingStore, KyotoDrawBatch, KyotoPerson, KyotoRecord


def last_four(phone):
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    return digits[-4:] if digits else ''


class DabingStoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = DabingStore
        fields = ['id', 'name', 'sort_order', 'is_active']


class DabingPersonSerializer(serializers.ModelSerializer):
    phone_last_four = serializers.SerializerMethodField()

    class Meta:
        model = DabingPerson
        fields = ['id', 'name', 'phone', 'contact', 'phone_last_four', 'birthday', 'mobile_model', 'note', 'is_active']

    def get_phone_last_four(self, obj):
        return last_four(obj.phone)


class DabingRecordSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    person_name = serializers.CharField(source='person.name', read_only=True)
    phone = serializers.CharField(source='phone_snapshot', read_only=True)
    contact = serializers.CharField(source='contact_snapshot', read_only=True)
    phone_last_four = serializers.SerializerMethodField()
    mobile_model = serializers.CharField(source='mobile_model_snapshot', read_only=True)
    birthday = serializers.DateField(source='birthday_snapshot', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True, default=None)

    class Meta:
        model = DabingRecord
        fields = [
            'id', 'store', 'store_name', 'person', 'person_name', 'draw_date', 'draw_time',
            'phone', 'contact', 'phone_last_four', 'mobile_model', 'birthday', 'created_by_name', 'created_at',
        ]
        read_only_fields = ['phone', 'contact', 'phone_last_four', 'mobile_model', 'birthday', 'created_by_name']

    def get_phone_last_four(self, obj):
        return last_four(obj.phone_snapshot)

    def validate(self, attrs):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        store = attrs.get('store', getattr(self.instance, 'store', None))
        person = attrs.get('person', getattr(self.instance, 'person', None))
        if user and store and store.organization_id != user.organization_id:
            raise serializers.ValidationError({'store': ['store-outside-organization']})
        if user and person and person.organization_id != user.organization_id:
            raise serializers.ValidationError({'person': ['person-outside-organization']})
        return attrs


class KyotoPersonSerializer(serializers.ModelSerializer):
    phone_last_four = serializers.SerializerMethodField()

    class Meta:
        model = KyotoPerson
        fields = ['id', 'name', 'phone', 'phone_last_four', 'note', 'is_active']

    def get_phone_last_four(self, obj):
        return last_four(obj.phone)


class KyotoDrawBatchSerializer(serializers.ModelSerializer):
    display_label = serializers.ReadOnlyField()

    class Meta:
        model = KyotoDrawBatch
        fields = ['id', 'draw_start_date', 'draw_end_date', 'publish_date', 'label', 'display_label', 'is_active']

    def validate(self, attrs):
        start = attrs.get('draw_start_date', getattr(self.instance, 'draw_start_date', None))
        end = attrs.get('draw_end_date', getattr(self.instance, 'draw_end_date', None))
        if start and end and end < start:
            raise serializers.ValidationError({'draw_end_date': ['draw-end-before-start']})
        return attrs


class KyotoRecordSerializer(serializers.ModelSerializer):
    batch_label = serializers.CharField(source='batch.display_label', read_only=True)
    draw_start_date = serializers.DateField(source='batch.draw_start_date', read_only=True)
    draw_end_date = serializers.DateField(source='batch.draw_end_date', read_only=True)
    publish_date = serializers.DateField(source='batch.publish_date', read_only=True)
    person_name = serializers.CharField(source='person.name', read_only=True)
    phone = serializers.CharField(source='phone_snapshot', read_only=True)
    phone_last_four = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source='created_by.username', read_only=True, default=None)

    class Meta:
        model = KyotoRecord
        fields = [
            'id', 'batch', 'batch_label', 'draw_start_date', 'draw_end_date', 'publish_date',
            'person', 'person_name', 'phone', 'phone_last_four', 'quantity', 'created_by_name', 'created_at',
        ]
        read_only_fields = ['batch_label', 'draw_start_date', 'draw_end_date', 'publish_date', 'phone', 'phone_last_four', 'created_by_name']

    def get_phone_last_four(self, obj):
        return last_four(obj.phone_snapshot)

    def validate(self, attrs):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        batch = attrs.get('batch', getattr(self.instance, 'batch', None))
        person = attrs.get('person', getattr(self.instance, 'person', None))
        if user and batch and batch.organization_id != user.organization_id:
            raise serializers.ValidationError({'batch': ['batch-outside-organization']})
        if user and person and person.organization_id != user.organization_id:
            raise serializers.ValidationError({'person': ['person-outside-organization']})
        return attrs
