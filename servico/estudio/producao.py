"""Produção automática do nosso canal: um vídeo por vez, seguindo a meta diária de cada nicho.

Quem roda é o `manage.py produtor` (processo separado do site). O painel /canal só lê e muda o estado.
Gospel com tema do catálogo: pipeline bíblico completo (texto exato da Bíblia, ComfyUI, 4 camadas).
Os outros nichos (e temas livres): roteirista guiado + juiz, imagens do banco/Pexels, mesma montagem do site.
"""

import os
import subprocess
import threading
import time
import traceback
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from . import jobs
from .models import Canal, Pauta, Producao, Produtor

NICHOS = ["gospel", "astronomia", "animais"]
MAX_FALHAS_DIA = 3  # um nicho que falhou 3 vezes hoje descansa até amanhã (não fica gastando em loop)
ATIVOS = [Producao.Status.FILA, Producao.Status.GERANDO]


def _motor():
    sp = jobs._pipeline()  # põe motor/milionere no sys.path
    import biblia
    import pipeline
    return sp, pipeline, biblia


# ------------------------------------------------------------------ pauta

def preparar() -> None:
    """Cria os canais e traz para a pauta os temas do catálogo que ainda não estão lá (idempotente)."""
    sp, pipeline, biblia = _motor()
    for n in NICHOS:
        Canal.objects.get_or_create(nicho=n)
    usados = pipeline.usados()
    repo = settings.BASE_DIR.parent / "producao" / "usados.json"  # o que o time já produziu fora do site
    if repo.exists():
        import json
        usados |= set(json.loads(repo.read_text(encoding="utf-8")))
    formatos = {k: v for k, v in pipeline.carregar("formatos.json").items() if not k.startswith("_")}
    for fid, f in formatos.items():
        for t in biblia.temas().get(f["catalogo"], []):
            titulo = f"{t['titulo']} · {t['ref']}" if t.get("ref") and fid != "personagem" else t["titulo"]
            Pauta.objects.get_or_create(nicho="gospel", formato=fid, titulo=titulo[:200], defaults={
                "formato_nome": f["nome"], "tema_id": t["id"], "prioridade": t.get("prioridade", 1),
                "usado": f"{fid}:{t['id']}" in usados})
    cat = sp.catalogo()
    for n in NICHOS[1:]:
        for fid, f in cat["nichos"][n].get("formatos", {}).items():
            for tid, titulo in f["temas"]:
                Pauta.objects.get_or_create(nicho=n, formato=fid, titulo=titulo[:200], defaults={
                    "formato_nome": f["nome"], "tema_id": tid, "usado": tid in cat["prontos"]})


def formatos_do_nicho(nicho: str) -> dict[str, str]:
    sp, _, _ = _motor()
    return {fid: f["nome"] for fid, f in sp.catalogo()["nichos"][nicho].get("formatos", {}).items() if fid != "sermao"}


def escolher_pauta(nicho: str) -> Pauta | None:
    """O formato com menos vídeos vai primeiro (canal variado); dentro dele, a maior prioridade e o mais antigo."""
    ocupadas = Producao.objects.filter(status__in=ATIVOS).values_list("pauta_id", flat=True)
    livres = list(Pauta.objects.filter(nicho=nicho, usado=False, falhas__lt=2).exclude(pk__in=ocupadas))
    if not livres:
        return None
    feitos = {}
    for fmt in Producao.objects.filter(nicho=nicho).exclude(status=Producao.Status.FALHOU).values_list("formato", flat=True):
        feitos[fmt] = feitos.get(fmt, 0) + 1
    return min(livres, key=lambda p: (feitos.get(p.formato, 0), -p.prioridade, p.criado))


def hoje(nicho: str) -> tuple[int, int]:
    """(vídeos que contam para a meta de hoje, falhas de hoje)."""
    q = Producao.objects.filter(nicho=nicho, criado__date=timezone.localdate())
    feitos = q.exclude(status__in=[Producao.Status.FALHOU, Producao.Status.REPROVADO]).count()
    return feitos, q.filter(status=Producao.Status.FALHOU).count()


def enfileirar(nicho: str, pauta: Pauta | None = None) -> Producao | None:
    pauta = pauta or escolher_pauta(nicho)
    if not pauta:
        return None
    return Producao.objects.create(pauta=pauta, nicho=nicho, formato=pauta.formato, tema=pauta.titulo)


def proxima() -> Producao | None:
    """Pedido manual do painel primeiro; senão, o nicho ativo mais longe da meta de hoje (respeitando o descanso)."""
    manual = Producao.objects.filter(status=Producao.Status.FILA).order_by("criado").first()
    if manual:
        return manual
    ultimo = Producao.objects.exclude(terminado=None).order_by("-terminado").first()
    if ultimo and timezone.now() - ultimo.terminado < timedelta(minutes=Produtor.get().intervalo_min):
        return None
    candidatos = []
    for c in Canal.objects.filter(ativo=True):
        feitos, falhas = hoje(c.nicho)
        if falhas < MAX_FALHAS_DIA and feitos < c.meta_dia:
            ult = Producao.objects.filter(nicho=c.nicho).order_by("-criado").values_list("criado", flat=True).first()
            candidatos.append((c.meta_dia - feitos, -(ult.timestamp() if ult else 0), c.nicho))
    for _, _, nicho in sorted(candidatos, reverse=True):
        p = enfileirar(nicho)
        if p:
            return p
    return None


# ------------------------------------------------------------------ execução

class _Diario:
    """Guarda o log da produção e mostra a última linha no painel."""

    def __init__(self, prod_id):
        self.id, self.linhas = prod_id, []

    def __call__(self, msg: str, etapa: str | None = None) -> None:
        msg = (msg or "").strip()
        if msg:
            self.linhas += [f"[{timezone.localtime():%H:%M:%S}] {l}" for l in msg.splitlines()]
        campos = {"log": "\n".join(self.linhas[-500:])}
        if msg:
            campos["mensagem"] = msg.splitlines()[-1][:300]
        if etapa:
            campos["etapa"] = etapa
        Producao.objects.filter(pk=self.id).update(**campos)


def _etapa_gospel(msg: str) -> str | None:
    m = msg.lower()
    if m.startswith(("imagens:", "camada 3", "refação", "  cena")):
        return "imagens"
    if m.startswith(("render", "  camada 4")):
        return "montagem"
    return None


def _gospel(prod: Producao, musica: str, diario: _Diario) -> list[Path]:
    _, pipeline, _ = _motor()
    original = pipeline.log

    def log(msg):
        original(msg)
        diario(msg, _etapa_gospel(msg))
    pipeline.log = log
    try:
        videos = pipeline.um_video(prod.formato, None, prod.pauta.tema_id, musica)
    finally:
        pipeline.log = original
    if not videos:
        raise RuntimeError("o roteiro ou o render não passou nas validações (veja o log)")
    return videos


def _generico(prod: Producao, musica: str, diario: _Diario) -> list[Path]:
    sp, _, _ = _motor()
    import caminhos

    log = lambda etapa, msg: diario(msg or etapa, etapa)  # noqa: E731
    pauta = prod.pauta
    r = sp._roteiro_generico({"nicho": prod.nicho, "formato": prod.formato,
                              "formato_nome": pauta.formato_nome if pauta else prod.formato, "tema_livre": prod.tema}, log)
    if r.get("_avisos"):
        raise RuntimeError("o juiz reprovou o roteiro nas 3 tentativas: " + " | ".join(r["_avisos"][:3]))
    diario("roteiro aprovado:\n" + "\n".join(f"  «{c['fala']}»" for c in r["cenas"]), "roteiro")
    entrada = {"nicho": prod.nicho, "formato": prod.formato, "tema_livre": prod.tema, "dono": "canal",
               "cenas": [{"fala": c["fala"], "busca": c.get("busca", ""), "imagem": c.get("imagem", "")} for c in r["cenas"]],
               "post": {"titulo": r["titulo"], "desc": r["descricao"], "tags": " ".join(r["hashtags"]),
                        "comentario": r["comentario_fixado"]},
               "mus": "sem" if musica == "sem" else "com"}
    pasta = Path(settings.MEDIA_ROOT) / "canal" / str(prod.id)
    saida = sp.gerar_video(entrada, pasta, log)
    videos = [Path(saida["video"])]
    if musica == "ambas":  # a mesma montagem de novo, sem música (TikTok)
        diario("render sem música (TikTok)", "montagem")
        proc = subprocess.run([str(caminhos.PYTHON_MOTOR), str(Path(sp.__file__).with_name("produzir.py")),
                               str(pasta / "roteiro.json"), "--sem-musica"], cwd=caminhos.MOTOR, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        sem = next((Path(l.split("] ", 1)[1].strip()) for l in proc.stdout.splitlines() if l.startswith("PRONTO")), None)
        if sem and sem.exists():
            videos.append(sem)
        else:
            diario("AVISO: a versão sem música falhou; ficou só a com música")
    return videos


def _url(p: Path) -> str:
    try:
        return settings.MEDIA_URL + p.resolve().relative_to(Path(settings.MEDIA_ROOT).resolve()).as_posix()
    except ValueError:
        return ""


def _titulo(post: str) -> str:
    linhas = [l.strip() for l in post.splitlines()]
    for i, l in enumerate(linhas):
        if l.upper().startswith("TÍTULO") and i + 1 < len(linhas):
            return linhas[i + 1]
    return ""


def executar(prod: Producao) -> None:
    _motor()
    import medidor

    canal = Canal.objects.filter(nicho=prod.nicho).first()
    musica = canal.musica if canal else "ambas"
    diario = _Diario(prod.pk)
    Producao.objects.filter(pk=prod.pk).update(status=Producao.Status.GERANDO, etapa="roteiro", iniciado=timezone.now(),
                                               mensagem="começando")
    with medidor.medir() as m:
        try:
            biblico = prod.nicho == "gospel" and prod.pauta and prod.pauta.tema_id and prod.pauta.origem == "catalogo"
            videos = (_gospel if biblico else _generico)(prod, musica, diario)
            videos.sort(key=lambda p: "_sem-musica" in p.stem)  # com música primeiro
            post = next((p.with_suffix(".txt").read_text(encoding="utf-8") for p in videos if p.with_suffix(".txt").exists()), "")
            Producao.objects.filter(pk=prod.pk).update(
                status=Producao.Status.REVISAR, etapa="post", mensagem="pronto para revisar", post=post,
                titulo=_titulo(post)[:200], terminado=timezone.now(), custos=m.resumo(),
                videos=[{"nome": p.name, "url": _url(p), "variante": "sem" if "_sem-musica" in p.stem else "com"} for p in videos])
            if prod.pauta_id:
                Pauta.objects.filter(pk=prod.pauta_id).update(usado=True)
        except BaseException as e:  # noqa: BLE001 - SystemExit do pipeline também vira falha legível
            if isinstance(e, KeyboardInterrupt):
                Producao.objects.filter(pk=prod.pk).update(status=Producao.Status.FALHOU, erro="produtor interrompido",
                                                           terminado=timezone.now())
                raise
            diario(f"FALHOU: {e}")
            Producao.objects.filter(pk=prod.pk).update(status=Producao.Status.FALHOU, mensagem=str(e)[:300],
                                                       erro=f"{e}\n\n{traceback.format_exc()[-4000:]}",
                                                       terminado=timezone.now(), custos=m.resumo())
            if prod.pauta_id:
                Pauta.objects.filter(pk=prod.pauta_id).update(falhas=prod.pauta.falhas + 1)


# ------------------------------------------------------------------ o processo

def _batimento(parar: threading.Event) -> None:
    while not parar.is_set():
        try:
            Produtor.objects.filter(pk=1).update(batimento=timezone.now())
        except Exception:  # noqa: BLE001 - banco ocupado: tenta no próximo batimento
            pass
        finally:
            close_old_connections()
        parar.wait(20)


def rodar(uma_vez: bool = False, log=print) -> None:
    preparar()
    Produtor.get()
    presas = Producao.objects.filter(status=Producao.Status.GERANDO)
    if presas.exists():  # o produtor anterior caiu no meio: essas não vão terminar sozinhas
        presas.update(status=Producao.Status.FALHOU, mensagem="o produtor foi reiniciado no meio", terminado=timezone.now())
    parar = threading.Event()
    threading.Thread(target=_batimento, args=(parar,), daemon=True).start()
    log("produtor no ar: um vídeo por vez, seguindo as metas do painel /canal (Ctrl+C para parar)")
    try:
        while True:
            prod = None if Produtor.get().pausado else proxima()
            if prod:
                log(f"{timezone.localtime():%H:%M} gerando: {prod.nicho} · {prod.tema}")
                executar(prod)
                prod.refresh_from_db()
                log(f"{timezone.localtime():%H:%M} {prod.get_status_display()}: {prod.mensagem}")
                if uma_vez:
                    return
                continue
            if uma_vez:
                log("nada para gerar agora (metas cumpridas, pausado ou em descanso)")
                return
            time.sleep(30)
    finally:
        parar.set()


# ------------------------------------------------------------------ painel

def sugerir(nicho: str, n: int = 10) -> int:
    """A IA propõe temas novos para a pauta, sem repetir o que já temos."""
    _motor()
    import llm

    formatos = formatos_do_nicho(nicho)
    existentes = list(Pauta.objects.filter(nicho=nicho).values_list("titulo", flat=True))
    prompt = (
        f"Você monta a pauta de um canal de Shorts/TikTok em português do Brasil, nicho **{nicho}**.\n"
        f"Sugira {n} temas NOVOS, distribuídos entre estes formatos (id: nome): "
        + "; ".join(f"{k}: {v}" for k, v in formatos.items()) + ".\n"
        "Regras: o fato central tem que ser verdadeiro e verificável; curiosidade forte que faz parar de rolar o feed; "
        "título curto (até 60 caracteres), no mesmo tom dos que já temos; nada repetido nem parecido com a lista abaixo.\n"
        + ("No gospel, só histórias e personagens que estão de fato na Bíblia, com a referência no título "
           "(ex.: 'O homem que subiu na árvore · Lucas 19:1-10').\n" if nicho == "gospel" else "")
        + "\n# Já temos\n" + "\n".join(f"- {t}" for t in existentes))
    schema = {"type": "object", "additionalProperties": False, "required": ["temas"], "properties": {"temas": {
        "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["formato", "titulo"],
                                   "properties": {"formato": {"type": "string", "enum": list(formatos)},
                                                  "titulo": {"type": "string"}}}}}}
    novos = 0
    for t in llm.chamar(prompt, schema, papel="juiz")["temas"]:
        _, criado = Pauta.objects.get_or_create(nicho=nicho, formato=t["formato"], titulo=t["titulo"].strip()[:200],
                                                defaults={"formato_nome": formatos.get(t["formato"], ""), "origem": "ia"})
        novos += criado
    return novos


def _prod(p: Producao, log: bool = False) -> dict:
    d = {"id": str(p.pk), "nicho": p.nicho, "formato": p.formato, "tema": p.tema, "status": p.status,
         "status_nome": p.get_status_display(), "etapa": p.etapa, "mensagem": p.mensagem, "titulo": p.titulo, "post": p.post,
         "videos": p.videos, "custo_brl": (p.custos or {}).get("brl"), "motivo": p.motivo,
         "criado": p.criado.isoformat(), "iniciado": p.iniciado.isoformat() if p.iniciado else None,
         "terminado": p.terminado.isoformat() if p.terminado else None,
         "youtube": bool(p.postado_youtube), "tiktok": bool(p.postado_tiktok), "erro": p.mensagem if p.status == "falhou" else ""}
    if log:
        d["log"] = "\n".join(p.log.splitlines()[-60:])
    return d


def estado() -> dict:
    if not Canal.objects.exists():
        preparar()
    sp, _, _ = _motor()
    cat = sp.catalogo()["nichos"]
    prod = Produtor.get()
    vivo = bool(prod.batimento and timezone.now() - prod.batimento < timedelta(seconds=75))
    canais = []
    for c in Canal.objects.filter(nicho__in=NICHOS):
        feitos, falhas = hoje(c.nicho)
        livres = Pauta.objects.filter(nicho=c.nicho, usado=False, falhas__lt=2)
        canais.append({"nicho": c.nicho, "nome": cat[c.nicho]["nome"], "cor": cat[c.nicho]["cor"], "ativo": c.ativo,
                       "meta_dia": c.meta_dia, "musica": c.musica, "hoje": feitos, "falhas_hoje": falhas,
                       "restantes": livres.count(), "formatos": formatos_do_nicho(c.nicho),
                       "pauta": [{"id": p.pk, "titulo": p.titulo, "formato": p.formato, "origem": p.origem}
                                 for p in livres[:40]]})
    canais.sort(key=lambda c: NICHOS.index(c["nicho"]))
    q = Producao.objects.all()
    atual = q.filter(status=Producao.Status.GERANDO).first()
    return {"produtor": {"vivo": vivo, "pausado": prod.pausado, "intervalo_min": prod.intervalo_min},
            "canais": canais, "atual": _prod(atual, log=True) if atual else None,
            "fila": [_prod(p) for p in q.filter(status=Producao.Status.FILA).order_by("criado")],
            "revisar": [_prod(p) for p in q.filter(status=Producao.Status.REVISAR)],
            "aprovados": [_prod(p) for p in q.filter(status=Producao.Status.APROVADO)],
            "historico": [_prod(p) for p in q.exclude(status__in=ATIVOS)[:40]]}
