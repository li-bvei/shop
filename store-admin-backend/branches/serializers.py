from rest_framework import serializers

from .models import Branch


class BranchSerializer(serializers.ModelSerializer):
    """`organization` is deliberately excluded — it's always forced
    server-side from the requesting admin's own account
    (BranchViewSet.perform_create), never something the client chooses,
    or an admin could create a branch inside another Organization. `code`
    defaults to `id` if the client doesn't supply one (BranchViewSet.
    perform_create) — existing frontend flows only ever generate `id`."""

    class Meta:
        model = Branch
        fields = ['id', 'code', 'name_zh', 'name_ja']
        extra_kwargs = {'code': {'required': False}}
