from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Extended user model for WhatsApp multi-tenant setup."""

    STATUS_CHOICES = [
        ('pending_init_request', 'Pending Init Request'),
        ('pending_handshake', 'Pending Handshake'),
        ('connected', 'Connected'),
        ('sync_error', 'Sync Error'),
    ]

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending_init_request'
    )
    whatsapp_jid = models.CharField(max_length=100, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.username


class QRCode(models.Model):
    """QR code storage for WhatsApp authentication."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='qrcodes'
    )
    image_data = models.TextField(help_text="Base64 encoded PNG")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    verified = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'QR Codes'

    def __str__(self):
        return f"QR for {self.user.username} - {'verified' if self.verified else 'pending'}"