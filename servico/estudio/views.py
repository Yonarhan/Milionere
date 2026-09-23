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
                         "mensagem": job.mensagem, "etapas": job.etapas(), "saida": job.saida,
                         "erro": job.mensagem if job.status == Job.Status.ERRO else ""})
