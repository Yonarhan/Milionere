from django.contrib import admin

from .models import Job


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("id", "tipo", "status", "etapa", "custo_brl", "mensagem", "criado")
    list_filter = ("tipo", "status")
    readonly_fields = ("entrada", "saida", "custos", "erro", "criado", "atualizado")

    @admin.display(description="custo (R$)")
    def custo_brl(self, obj):
        return (obj.custos or {}).get("brl", "")
