from django.contrib import admin

from .models import Canal, Job, Pauta, Producao


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("id", "tipo", "status", "etapa", "custo_brl", "mensagem", "criado")
    list_filter = ("tipo", "status")
    readonly_fields = ("entrada", "saida", "custos", "erro", "criado", "atualizado")

    @admin.display(description="custo (R$)")
    def custo_brl(self, obj):
        return (obj.custos or {}).get("brl", "")


@admin.register(Canal)
class CanalAdmin(admin.ModelAdmin):
    list_display = ("nicho", "ativo", "meta_dia", "musica")


@admin.register(Pauta)
class PautaAdmin(admin.ModelAdmin):
    list_display = ("titulo", "nicho", "formato", "origem", "usado", "falhas")
    list_filter = ("nicho", "formato", "origem", "usado")
    search_fields = ("titulo",)


@admin.register(Producao)
class ProducaoAdmin(admin.ModelAdmin):
    list_display = ("tema", "nicho", "formato", "status", "custo_brl", "criado")
    list_filter = ("nicho", "status")
    readonly_fields = ("log", "custos", "erro", "videos", "criado", "iniciado", "terminado")

    @admin.display(description="custo (R$)")
    def custo_brl(self, obj):
        return (obj.custos or {}).get("brl", "")
