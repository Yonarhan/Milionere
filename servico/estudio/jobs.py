"""Execução dos jobs. MVP local: threads no próprio processo do Django.

Em produção isto vira tarefas Celery (filas cpu/gpu, ver docs/SERVICO.md). As funções `_rodar_*` já têm
o formato de uma task: recebem o id do job, leem a entrada do banco e gravam progresso e resultado.
"""

import threading
import traceback
from pathlib import Path

from django.conf import settings
from django.db import close_old_connections

from .models import Job

_videos = threading.Semaphore(settings.MILIONERE_VIDEOS_SIMULTANEOS)  # vídeo é pesado: 1 por vez no MVP


def _pipeline():
    import milionere  # noqa: F401  (coloca motor/milionere no sys.path)
    import servico_pipeline

    return servico_pipeline


def _progresso(job_id):
    def log(etapa: str, msg: str) -> None:
        Job.objects.filter(pk=job_id).update(etapa=etapa, mensagem=(msg or "")[:300])
    return log


def _executar(job_id, trabalho):
    close_old_connections()
    try:
        Job.objects.filter(pk=job_id).update(status=Job.Status.RODANDO)
        saida = trabalho()
        Job.objects.filter(pk=job_id).update(status=Job.Status.OK, saida=saida, mensagem="")
    except BaseException as e:  # SystemExit do pipeline também vira erro legível
        Job.objects.filter(pk=job_id).update(status=Job.Status.ERRO, erro=f"{e}\n\n{traceback.format_exc()[-3000:]}",
                                             mensagem=str(e)[:300])
    finally:
        close_old_connections()


def _rodar_roteiro(job_id):
    job = Job.objects.get(pk=job_id)
    entrada = {**job.entrada, "job": str(job_id)[:8]}
    _executar(job_id, lambda: {"roteiro": _pipeline().gerar_roteiro(entrada, _progresso(job_id))})


def _rodar_video(job_id):
    job = Job.objects.get(pk=job_id)
    pasta = Path(settings.MEDIA_ROOT) / "jobs" / str(job_id)

    def trabalho():
        with _videos:
            r = _pipeline().gerar_video(job.entrada, pasta, _progresso(job_id))
        rel = Path(r["video"]).resolve().relative_to(Path(settings.MEDIA_ROOT).resolve()).as_posix()
        return {**r, "video_url": settings.MEDIA_URL + rel}

    _executar(job_id, trabalho)


def disparar(job: Job) -> None:
    alvo = _rodar_video if job.tipo == Job.Tipo.VIDEO else _rodar_roteiro
    threading.Thread(target=alvo, args=(job.pk,), daemon=True).start()
