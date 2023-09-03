from django.contrib import admin
from .models import promoCode

class PromoCodeAdmin(admin.ModelAdmin):
    list_display = ('codeName', 'limits', 'isActive')

    # Определите, какие поля вы хотите видеть при редактировании исключительно
    fields = ('codeName', 'limits', 'isActive')

    # Если вам нужно исключить какие-либо поля, используйте `exclude`
    # exclude = ('userId', 'activationDate')

    search_fields = ('codeName',)
    list_filter = ('isActive',)

admin.site.register(promoCode, PromoCodeAdmin)

admin.site.site_header = "Администрирование Сонника"



