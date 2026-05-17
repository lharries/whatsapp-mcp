from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UserViewSet, QRCodeViewSet

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')
router.register(r'qrcodes', QRCodeViewSet, basename='qrcode')

urlpatterns = [
    path('', include(router.urls)),
]