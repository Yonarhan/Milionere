import json
import os

from django.views.decorators.cache import never_cache
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from . import jobs
from .models import Job


@ensure_csrf_cookie
def index(request):
    return render(request, "estudio/index.html")


@require_GET
def api_catalogo(request):
    return JsonResponse(jobs._pipeline().catalogo())


@require_POST
def api_roteiro(request):
    entrada = json.loads(request.body or "{}")
    pronto = None if entrada.get("tema_livre") else jobs._pipeline().roteiro_pronto(entrada.get("tema", ""))
    if pronto:
        return JsonResponse({"roteiro": pronto})
    job = Job.objects.create(tipo=Job.Tipo.ROTEIRO, entrada=entrada)
    jobs.disparar(job)
    return JsonResponse({"job": str(job.pk)}, status=202)


@require_POST
def api_gerar(request):
    entrada = json.loads(request.body or "{}")
    if not any((c.get("fala") or "").strip() for c in entrada.get("cenas", [])):
        return JsonResponse({"erro": "Escreva pelo menos uma fala antes de gerar."}, status=400)
    if not request.session.session_key:
        request.session.save()
    entrada["dono"] = request.session.session_key  # uploads privados voltam só para quem subiu (até existir login)
    job = Job.objects.create(tipo=Job.Tipo.VIDEO, entrada=entrada, etapa="roteiro")
    jobs.disparar(job)
    return JsonResponse({"job": str(job.pk)}, status=202)


@require_GET
def api_job(request, job_id):
    try:
        job = Job.objects.get(pk=job_id)
    except (Job.DoesNotExist, ValueError):
        raise Http404
    return JsonResponse({"id": str(job.pk), "tipo": job.tipo, "status": job.status, "etapa": job.etapa,
                         "mensagem": job.mensagem, "etapas": job.etapas(), "saida": job.saida, "custos": job.custos,
                         "erro": job.mensagem if job.status == Job.Status.ERRO else ""})


def banco(request):
    """O banco de imagens de cada nicho: o que já foi aprovado e quantas vezes foi reusado."""
    from django.conf import settings

    jobs._pipeline()  # garante o motor no sys.path
    import banco_imagens
    nicho = request.GET.get("nicho") or None
    itens = banco_imagens.listar(nicho)
    for i in itens:
        i["url"] = f"{settings.MEDIA_URL}producao/banco/{i['rel']}"
    nichos = sorted({i["nicho"] for i in banco_imagens.listar()})
    return render(request, "estudio/banco.html", {"itens": itens, "nicho": nicho, "nichos": nichos, "total": len(itens)})


# ------------------------------------------------------------------ painel do nosso canal

@never_cache
@ensure_csrf_cookie
def canal(request):
    return render(request, "estudio/canal.html")


@require_GET
def api_canal(request):
    from . import producao
    return JsonResponse({**producao.estado(), "vozes": producao.VOZES})


def api_voz_previa(request):
    """GET ?nicho=astronomia&voz=pt-BR-AntonioNeural-Male -> mp3 com a voz no tom e na velocidade do nicho."""
    from django.http import FileResponse

    from . import producao
    try:
        arq = producao.previa_voz(request.GET.get("nicho", ""), request.GET.get("voz", ""))
    except Exception as e:  # noqa: BLE001
        return JsonResponse({"erro": f"não consegui gerar a prévia: {e}"}, status=400)
    return FileResponse(open(arq, "rb"), content_type="audio/mpeg")


@require_POST
def api_canal_acao(request):
    """Todas as mudanças do painel: metas, pausa, gerar agora, revisão, postagem e pauta."""
    from django.utils import timezone

    from . import producao
    from .models import Canal, Pauta, Producao, Produtor, Serie

    d = json.loads(request.body or "{}")
    acao = d.get("acao")
    if acao == "canal":
        c = Canal.objects.get(pk=d["nicho"])
        if "musica" in d and d["musica"] not in ("com", "sem"):  # um vídeo só: com ou sem música
            return JsonResponse({"erro": "Escolha com ou sem música."}, status=400)
        if "imagens" in d and d["imagens"] not in ("ia", "nativo", "ia_pod"):
            return JsonResponse({"erro": "Imagens: ia ou nativo."}, status=400)
        if "modo" in d and d["modo"] not in producao.MODOS:
            return JsonResponse({"erro": "Modo desconhecido."}, status=400)
        if "legenda" in d and d["legenda"] not in ("padrao", "karaoke", "word_by_word"):
            return JsonResponse({"erro": "Legenda desconhecida."}, status=400)
        if "voz" in d and d["voz"] and d["voz"] not in dict(producao.VOZES):
            return JsonResponse({"erro": "Voz desconhecida."}, status=400)
        if "roteiro" in d and d["roteiro"] not in ("padrao", "narrado"):
            return JsonResponse({"erro": "Roteiro: padrão ou narrado."}, status=400)
        if "estilo_pod" in d and d["estilo_pod"] and d["estilo_pod"] not in producao.ESTILOS_POD:
            return JsonResponse({"erro": "Estilo desconhecido."}, status=400)
        limites = {"meta_dia": (0, 12), "serie_max": (2, 5), "serie_cada": (1, 20)}
        for campo in ("ativo", "meta_dia", "musica", "imagens", "modo", "serie_max", "serie_cada", "legenda", "efeitos", "volume", "voz", "roteiro", "estilo_pod"):
            if campo in d:
                setattr(c, campo, max(limites[campo][0], min(limites[campo][1], int(d[campo]))) if campo in limites else d[campo])
        c.save()
    elif acao == "produtor":
        p = Produtor.get()
        if "llm" in d:
            if d["llm"] not in ("claude-cli", "api"):
                return JsonResponse({"erro": "Provedor de IA inválido."}, status=400)
            if d["llm"] == "api":
                jobs._pipeline()
                if not os.environ.get("ANTHROPIC_API_KEY"):
                    return JsonResponse({"erro": "Preencha ANTHROPIC_API_KEY no .env da raiz."}, status=400)
            p.llm = d["llm"]
        if "pausado" in d:
            p.pausado = bool(d["pausado"])
        if "intervalo_min" in d:
            p.intervalo_min = max(0, min(240, int(d["intervalo_min"])))
        p.save()
    elif acao == "gerar":
        pauta = Pauta.objects.filter(pk=d["pauta"]).first() if d.get("pauta") else None
        serie_max = max(0, min(5, int(d.get("serie_max") or 0)))  # 0 = vídeo único; 2 a 5 = série
        if not producao.enfileirar(d["nicho"], pauta, serie_max):
            return JsonResponse({"erro": "Acabaram os temas desse nicho: adicione na pauta."}, status=400)
        if not producao.vivo():  # pedido manual: não espera alguém ligar o produtor
            producao.ligar_produtor()
    elif acao in ("aprovar", "reprovar") and d.get("serie"):  # a série é revisada como um bloco só
        s = Serie.objects.get(pk=d["serie"])
        if acao == "aprovar":
            s.status = Producao.Status.APROVADO
        else:
            s.status, s.motivo = Producao.Status.REPROVADO, (d.get("motivo") or "")[:300]
            if s.motivo:
                jobs._pipeline()
                import banco_roteiros
                banco_roteiros.registrar_erros(s.nicho, s.formato, [f"(revisão humana, série) {s.motivo}"])
        s.save()
        s.partes.update(status=s.status, motivo=s.motivo)
    elif acao in ("aprovar", "reprovar", "youtube", "tiktok", "voltar"):
        p = Producao.objects.get(pk=d["id"])
        if acao == "aprovar":
            p.status = Producao.Status.APROVADO
        elif acao == "reprovar":
            p.status, p.motivo = Producao.Status.REPROVADO, (d.get("motivo") or "")[:300]
            if p.motivo:  # o motivo vira lição para o roteirista do nicho
                jobs._pipeline()
                import banco_roteiros
                banco_roteiros.registrar_erros(p.nicho, p.formato, [f"(revisão humana) {p.motivo}"])
        elif acao == "voltar":
            p.status, p.postado_youtube, p.postado_tiktok = Producao.Status.REVISAR, None, None
        else:
            campo = f"postado_{acao}"
            if acao == "youtube" and not p.postado_youtube and not d.get("forcar"):
                n = Producao.objects.filter(nicho=p.nicho, postado_youtube__date=timezone.localdate()).count()
                if n >= producao.MAX_POSTS_YT_DIA:
                    return JsonResponse({"limite": True, "erro": f"Já são {n} vídeos de {p.nicho} no YouTube hoje. Mais que "
                                         f"{producao.MAX_POSTS_YT_DIA} por dia dá cara de canal produzido em massa na revisão "
                                         "da monetização. Melhor deixar este para amanhã."}, status=409)
            setattr(p, campo, None if getattr(p, campo) else timezone.now())
            if p.postado_youtube and p.postado_tiktok:
                p.status = Producao.Status.POSTADO
            elif p.status == Producao.Status.POSTADO:
                p.status = Producao.Status.APROVADO
        p.save()
    elif acao == "ligar_produtor":
        if not producao.ligar_produtor():
            return JsonResponse({"erro": "O produtor já está rodando."}, status=400)
    elif acao == "tentar_de_novo" and (d.get("serie") or Serie.objects.filter(pk=d["id"], status=Producao.Status.FALHOU).exists()):
        falha = Serie.objects.get(pk=d.get("serie") or d["id"], status=Producao.Status.FALHOU)
        if falha.pauta_id:
            Pauta.objects.filter(pk=falha.pauta_id).update(falhas=0, usado=False)
        Serie.objects.create(pauta=falha.pauta, nicho=falha.nicho, formato=falha.formato, tema=falha.tema,
                             max_partes=falha.max_partes)
        if not producao.vivo():
            producao.ligar_produtor()
    elif acao == "tentar_de_novo":
        falha = Producao.objects.get(pk=d["id"], status=Producao.Status.FALHOU)
        if falha.pauta_id:
            Pauta.objects.filter(pk=falha.pauta_id).update(falhas=0, usado=False)
        Producao.objects.create(pauta=falha.pauta, nicho=falha.nicho, formato=falha.formato, tema=falha.tema)
        if not producao.vivo():
            producao.ligar_produtor()
    elif acao == "cancelar_atual" and Serie.objects.filter(pk=d["id"], status=Producao.Status.GERANDO).exists():
        # série: marca como cancelada na hora (sai do "Gerando agora"); o produtor vê e derruba as chamadas
        Serie.objects.filter(pk=d["id"]).update(status=Producao.Status.FALHOU, mensagem="cancelado por você",
                                                terminado=timezone.now())
        Producao.objects.filter(serie_id=d["id"], status__in=[Producao.Status.GERANDO, Producao.Status.FILA]).update(
            status=Producao.Status.FALHOU, mensagem="cancelado por você", terminado=timezone.now())
    elif acao == "cancelar_atual":
        p = Producao.objects.filter(pk=d["id"], status=Producao.Status.GERANDO).first()
        if not p:
            return JsonResponse({"erro": "Esse vídeo não está gerando."}, status=400)
        if producao.vivo():  # o produtor interrompe e marca como cancelado
            Producao.objects.filter(pk=p.pk).update(cancelar=True, mensagem="cancelando…")
        else:  # nada rodando de verdade (o produtor caiu no meio): só marca
            Producao.objects.filter(pk=p.pk).update(cancelar=True, status=Producao.Status.FALHOU,
                                                    mensagem="cancelado por você", terminado=timezone.now())
    elif acao == "zerar_falhas":
        Produtor.objects.filter(pk=Produtor.get().pk).update(falhas_zeradas_em=timezone.now())
        Pauta.objects.filter(usado=False, falhas__gt=0).update(falhas=0)
    elif acao == "iniciar_agora":
        return JsonResponse({"ok": True, "msg": producao.iniciar_agora(d["id"])})
    elif acao == "cancelar":
        Producao.objects.filter(pk=d["id"], status=Producao.Status.FILA).delete()
        Serie.objects.filter(pk=d["id"], status=Producao.Status.FILA).delete()
    elif acao == "pauta_add":
        titulo = (d.get("titulo") or "").strip()
        if not titulo:
            return JsonResponse({"erro": "Escreva o tema."}, status=400)
        fmts = producao.formatos_do_nicho(d["nicho"])
        fmt = d.get("formato") if d.get("formato") in fmts else next(iter(fmts))
        Pauta.objects.get_or_create(nicho=d["nicho"], formato=fmt, titulo=titulo[:200],
                                    defaults={"formato_nome": fmts[fmt], "origem": "manual", "prioridade": 2})
    elif acao == "pauta_remover":
        Pauta.objects.filter(pk=d["id"]).update(usado=True)
    elif acao == "sugerir":
        try:
            n = producao.sugerir(d["nicho"])
        except Exception as e:  # noqa: BLE001
            return JsonResponse({"erro": f"A IA não conseguiu sugerir agora: {e}"}, status=500)
        return JsonResponse({"ok": True, "novos": n})
    else:
        return JsonResponse({"erro": "ação desconhecida"}, status=400)
    return JsonResponse({"ok": True})
