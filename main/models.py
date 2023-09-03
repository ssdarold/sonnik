from django.db import models


class promoCode(models.Model):

    codeName = models.CharField(max_length = 1000, verbose_name = "Название промокода", null=False)
    userId = models.IntegerField(verbose_name = "ID пользователя", null=True)
    limits = models.IntegerField(verbose_name = "Количество запросов", null=False)
    isActive = models.BooleanField(null=False, default=False, verbose_name = "Активен")
    activationDate = models.DateTimeField(auto_now_add=False, null=True)

    def __str__(self):
        return "%s" % (self.codeName)

    class Meta:
         verbose_name = "Промо-код"
         verbose_name_plural = "Промо-коды"

    REQUIRED_FIELDS = ['codeName', 'limits']
