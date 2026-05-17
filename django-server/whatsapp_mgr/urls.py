from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse


def health_check(request):
    return JsonResponse({
        'status': 'healthy',
        'service': 'whatsapp-django',
        'version': '0.1.0'
    })


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('users.urls')),
    path('health/', health_check, name='health_check'),
]