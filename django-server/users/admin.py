import jwt
from datetime import datetime
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from django.conf import settings

from .models import User, QRCode


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Django Admin configuration for User model"""

    list_display = ['username', 'status', 'whatsapp_jid', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['username', 'whatsapp_jid']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('WhatsApp', {'fields': ('status', 'whatsapp_jid')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2'),
        }),
    )
    actions = ['show_qr_code', 'generate_api_key']

    def show_qr_code(self, request, queryset):
        """Admin action: Display QR code in popup"""
        if queryset.count() != 1:
            self.message_user(request, "Please select exactly one user.")
            return
        user = queryset.first()
        qr = QRCode.objects.filter(user=user, verified=False).last()
        if qr:
            self.message_user(
                request,
                format_html(
                    '<h3>QR Code for {}</h3>'
                    '<img src="data:image/png;base64,{}" style="max-width:300px;" />'
                    '<p>Expires at: {}</p>',
                    user.username,
                    qr.image_data,
                    qr.expires_at
                )
            )
        else:
            self.message_user(request, f"No pending QR code for {user.username}")

    show_qr_code.short_description = "Show WhatsApp QR"

    def generate_api_key(self, request, queryset):
        """Admin action: Generate and display JWT API key"""
        if queryset.count() != 1:
            self.message_user(request, "Please select exactly one user.")
            return
        user = queryset.first()
        payload = {
            "user_id": str(user.id),
            "iat": datetime.utcnow(),
        }
        token = jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
        self.message_user(
            request,
            format_html(
                '<h3>API Key for {}</h3>'
                '<textarea readonly style="width:100%;height:100px;">{}</textarea>'
                '<p>Copy this token to configure your LLM client.</p>',
                user.username,
                token
            )
        )

    generate_api_key.short_description = "Generate API Key"


@admin.register(QRCode)
class QRCodeAdmin(admin.ModelAdmin):
    """Django Admin configuration for QRCode model"""

    list_display = ['user', 'created_at', 'expires_at', 'verified']
    list_filter = ['verified', 'created_at']
    search_fields = ['user__username']
    readonly_fields = ['created_at']