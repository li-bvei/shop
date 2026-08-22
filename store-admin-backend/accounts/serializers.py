from rest_framework import serializers

from branches.models import Branch
from staff.models import StaffMember

from .models import User, UserPreference


class MeSerializer(serializers.ModelSerializer):
    account = serializers.CharField(source='username')
    displayName = serializers.SerializerMethodField()
    branchId = serializers.CharField(source='branch_id', allow_null=True)
    staffMemberId = serializers.CharField(source='staff_member_id', allow_null=True)
    organizationId = serializers.SerializerMethodField()
    # Exposed in both locales (matching Branch's own name_zh/name_ja
    # convention) rather than one server-resolved string — this app never
    # picks a display locale on the backend, the frontend always does.
    organizationNameZh = serializers.CharField(source='organization.name_zh', read_only=True)
    organizationNameJa = serializers.CharField(source='organization.name_ja', read_only=True)

    class Meta:
        model = User
        fields = [
            'account', 'displayName', 'role', 'branchId', 'staffMemberId',
            'organizationId', 'organizationNameZh', 'organizationNameJa',
        ]

    def get_displayName(self, obj):
        return (obj.first_name or obj.username)[:1].upper()

    def get_organizationId(self, obj):
        return str(obj.organization_id) if obj.organization_id else None


class UserSerializer(serializers.ModelSerializer):
    """Admin-only account management — create/edit/list accounts. Password
    is write-only and only used on create; changing it afterwards goes
    through the dedicated reset/change-password endpoints so it's never
    silently overwritten by an unrelated PATCH."""

    account = serializers.CharField(source='username')
    password = serializers.CharField(write_only=True, required=False, min_length=6)
    displayName = serializers.CharField(source='first_name')
    branchId = serializers.PrimaryKeyRelatedField(
        source='branch', queryset=Branch.objects.none(), allow_null=True, required=False,
    )
    staffMemberId = serializers.PrimaryKeyRelatedField(
        source='staff_member', queryset=StaffMember.objects.none(), allow_null=True, required=False,
    )

    class Meta:
        model = User
        fields = ['id', 'account', 'password', 'displayName', 'role', 'branchId', 'staffMemberId']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Scoped per-request so an admin can only ever pick a branch/
        # employee inside its own Organization — a cross-org id in the
        # request body simply won't validate, DRF treats it as "does not
        # exist" rather than needing a separate explicit check.
        request = self.context.get('request')
        org_id = getattr(getattr(request, 'user', None), 'organization_id', None)
        if org_id:
            self.fields['branchId'].queryset = Branch.objects.filter(organization_id=org_id)
            self.fields['staffMemberId'].queryset = StaffMember.objects.filter(branch__organization_id=org_id)

    def validate(self, attrs):
        if self.instance is None and not attrs.get('password'):
            raise serializers.ValidationError({'password': ['This field is required when creating an account.']})

        role = attrs.get('role', self.instance.role if self.instance else None)
        if role == User.Role.STAFF:
            staff_member = attrs.get('staff_member', self.instance.staff_member if self.instance else None)
            if not staff_member:
                raise serializers.ValidationError({'staffMemberId': ['Required for staff-role accounts.']})
            existing = User.objects.filter(staff_member=staff_member)
            if self.instance:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError({'staffMemberId': ['This employee already has a login account.']})
            # A staff account's branch is never independently chosen — it
            # always follows the employee record it represents.
            attrs['branch'] = staff_member.branch
        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        validated_data.pop('password', None)
        return super().update(instance, validated_data)


class UserPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPreference
        fields = ['locale', 'theme', 'updated_at']
        read_only_fields = ['updated_at']
