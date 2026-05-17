from rest_framework import serializers
from .models import User, QRCode


class QRCodeSerializer(serializers.ModelSerializer):
    """Serializer for QRCode model"""

    class Meta:
        model = QRCode
        fields = ['id', 'image_data', 'created_at', 'expires_at', 'verified']
        read_only_fields = ['id', 'created_at']

    def to_representation(self, instance):
        if instance is None:
            return None
        return super().to_representation(instance)


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model"""

    class Meta:
        model = User
        fields = [
            'id', 'username', 'status', 'whatsapp_jid',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class UserCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a new user"""

    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ['id', 'username', 'password', 'status', 'whatsapp_jid']
        read_only_fields = ['id']

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class UserStatusUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating user status"""

    class Meta:
        model = User
        fields = ['status', 'whatsapp_jid']