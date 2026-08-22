from rest_framework import serializers

from .models import PaymentMethodDef


class PaymentMethodDefSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMethodDef
        fields = ['id', 'branch', 'code', 'custom_name', 'i18n_key', 'sort_order', 'protected']
        read_only_fields = ['protected']

    def validate(self, attrs):
        if self.instance and self.instance.protected:
            # Cash stays undeletable and unrenamable, but it's still a row
            # in the list — the user must be able to drag it to a different
            # position like any other method.
            blocked_fields = set(attrs.keys()) - {'sort_order'}
            if blocked_fields:
                raise serializers.ValidationError('this payment method cannot be modified.')
        return attrs
