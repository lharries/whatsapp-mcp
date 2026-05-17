import logging
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.utils import timezone
from datetime import timedelta

from .models import User, QRCode
from .serializers import (
    UserSerializer,
    UserCreateSerializer,
    UserStatusUpdateSerializer,
    QRCodeSerializer
)
from .authentication import ServiceKeyAuthentication

logger = logging.getLogger(__name__)


class UserViewSet(viewsets.ModelViewSet):
    """ViewSet for User CRUD operations"""

    queryset = User.objects.all()
    authentication_classes = [ServiceKeyAuthentication]
    permission_classes = [AllowAny]

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        elif self.action in ['update_status', 'partial_update_status']:
            return UserStatusUpdateSerializer
        return UserSerializer

    def create(self, request, *args, **kwargs):
        logger.info(f"Creating new user: {request.data.get('username')}")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        logger.info(f"User created successfully: {user.username} (id={user.id})")
        return Response(
            UserSerializer(user).data,
            status=status.HTTP_201_CREATED
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        username = instance.username
        user_id = instance.id
        self.perform_destroy(instance)
        logger.info(f"User deleted: {username} (id={user_id})")
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get', 'patch'])
    def qr(self, request, pk=None):
        """Get or update QR code for user"""
        user = self.get_object()

        if request.method == 'GET':
            qr = QRCode.objects.filter(user=user, verified=False).first()
            serializer = QRCodeSerializer(qr)
            return Response(serializer.data)

        elif request.method == 'PATCH':
            image_data = request.data.get('image_data')

            if not image_data:
                return Response(
                    {'detail': 'image_data is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            expires_at = request.data.get('expires_at')
            if expires_at:
                from django.utils.dateformat import parse_datetime
                expires_at = parse_datetime(expires_at)
            else:
                expires_at = timezone.now() + timedelta(minutes=5)

            QRCode.objects.create(
                user=user,
                image_data=image_data,
                expires_at=expires_at
            )

            user.status = 'pending_handshake'
            user.save()

            logger.info(f"QR code updated for user: {user.username}")
            return Response({'detail': 'QR code updated'})

    @action(detail=True, methods=['patch'], url_path='status')
    def update_status(self, request, pk=None):
        """Update user status and whatsapp_jid"""
        user = self.get_object()
        serializer = UserStatusUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        old_status = user.status
        new_status = request.data.get('status', old_status)
        whatsapp_jid = request.data.get('whatsapp_jid')

        logger.info(
            f"User status updated: {user.username} "
            f"status={old_status}->{new_status}"
        )

        return Response(UserSerializer(user).data)

    def perform_update(self, serializer):
        instance = serializer.save()
        logger.info(f"User updated: {instance.username}")


class QRCodeViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for QRCode read operations"""

    queryset = QRCode.objects.all()
    serializer_class = QRCodeSerializer
    authentication_classes = [ServiceKeyAuthentication]
    permission_classes = [AllowAny]