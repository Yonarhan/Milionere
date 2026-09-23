from django.contrib import admin

from .models import Job


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("id", "tipo", "status", "etapa", "mensagem", "criado")
    list_filter = ("tipo", "status")
    readonly_fields = ("entrada", "saida", "erro", "criado", "atualizado")
