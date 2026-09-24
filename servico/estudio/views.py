import json

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

@ensure_csrf_cookie
def canal(request):
    return render(request, "estudio/canal.html")


@require_GET
def api_canal(request):
    from . import producao
    return JsonResponse(producao.estado())


@require_POST
def api_canal_acao(request):
    """Todas as mudanças do painel: metas, pausa, gerar agora, revisão, postagem e pauta."""
    from django.utils import timezone

    from . import producao
    from .models import Canal, Pauta, Producao, Produtor

    d = json.loads(request.body or "{}")
    acao = d.get("acao")
    if acao == "canal":
        c = Canal.objects.get(pk=d["nicho"])
        for campo in ("ativo", "meta_dia", "musica"):
            if campo in d:
                setattr(c, campo, max(0, min(12, int(d[campo]))) if campo == "meta_dia" else d[campo])
        c.save()
    elif acao == "produtor":
        p = Produtor.get()
        if "pausado" in d:
            p.pausado = bool(d["pausado"])
        if "intervalo_min" in d:
            p.intervalo_min = max(0, min(240, int(d["intervalo_min"])))
        p.save()
    elif acao == "gerar":
        pauta = Pauta.objects.filter(pk=d["pauta"]).first() if d.get("pauta") else None
        if not producao.enfileirar(d["nicho"], pauta):
            return JsonResponse({"erro": "Acabaram os temas desse nicho: adicione na pauta."}, status=400)
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
            setattr(p, campo, None if getattr(p, campo) else timezone.now())
            if p.postado_youtube and p.postado_tiktok:
                p.status = Producao.Status.POSTADO
            elif p.status == Producao.Status.POSTADO:
                p.status = Producao.Status.APROVADO
        p.save()
    elif acao == "cancelar":
        Producao.objects.filter(pk=d["id"], status=Producao.Status.FILA).delete()
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
