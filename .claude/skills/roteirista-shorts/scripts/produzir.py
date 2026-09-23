"""Gera os vídeos de um roteiros.json pelo MoneyPrinterTurbo e organiza a saída.

Uso:
    python produzir.py roteiros.json            # gera todos
    python produzir.py roteiros.json --so-audio # só narração, para ouvir antes
    python produzir.py roteiros.json --seco     # só mostra o que faria

Formato de cada item em roteiros.json (modo sincronizado, recomendado):
    {
      "slug": "agua-viva-imortal",
      "nicho": "curiosidades",            # chave de presets.json
      "titulo": "...",
      "cenas": [                           # uma cena = um trecho da fala + a imagem dele
        {"fala": "Esse animal não morre de velhice.", "busca": "jellyfish"},
        {"fala": "Quando fica velha, volta a ser bebê.", "busca": "jellyfish close up|baby jellyfish"}
      ],
      "descricao": "...",
      "hashtags": ["#curiosidades", "#shorts"],
      "comentario_fixado": "...",          # opcional
      "fontes": ["..."],                   # opcional, só registro
      "ajustes": {"voice_rate": 1.2}       # opcional, sobrescreve o preset
    }
  "busca" aceita alternativas separadas por "|".

Modo antigo (sem sincronia): trocar "cenas" por "roteiro" (texto) + "keywords" (lista).

Saída: videos_prontos/<data>_<slug>.mp4 e <data>_<slug>.txt (texto do post).
"""

import argparse
import json
import random
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import renderizar as render  # noqa: E402
import sincronizar as sync  # noqa: E402

SKILL = Path(__file__).resolve().parents[1]
RAIZ = Path(__file__).resolve().parents[4]
MPT = RAIZ / "MoneyPrinterTurbo"
# Windows usa o .venv original; Linux/WSL usa o .venv-linux (criado com `UV_PROJECT_ENVIRONMENT=.venv-linux uv sync --frozen`)
PYTHON = MPT / (".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv-linux/bin/python")
SAIDA = RAIZ / "videos_prontos"
LOCAL_VIDEOS = MPT / "storage" / "local_videos"
PALAVRAS_POR_SEGUNDO = 1.95  # medido: Edge TTS pt-BR a 1.0x, com as pausas dos pontos finais


def roteiro_de(r: dict) -> str:
    if "cenas" in r:
        return " ".join(c["fala"].strip() for c in r["cenas"])
    return r["roteiro"].strip()


def escolher_musica(prefixo: str) -> str | None:
    pasta = MPT / "storage" / "bgm"
    opcoes = [p.name for p in pasta.glob(f"{prefixo}*") if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg"}]
    return random.choice(opcoes) if opcoes else None


def montar_tarefa(r: dict, preset: dict) -> tuple[dict, list[str]]:
    avisos = []
    tarefa = dict(preset["params"])
    roteiro = roteiro_de(r)
    tarefa.update(video_subject=r["titulo"], video_script=roteiro)
    if "cenas" in r:
        # preenchido só para o MoneyPrinter não pedir termos a um LLM; a busca real é por cena
        tarefa["video_terms"] = ", ".join(c["busca"].split("|")[0].strip() for c in r["cenas"])
    else:
        tarefa["video_terms"] = ", ".join(r["keywords"])
    musica = escolher_musica(preset["bgm_prefixo"])
    if musica:
        tarefa.update(bgm_type="custom", bgm_file=musica)
    else:
        tarefa["bgm_type"] = ""  # vazio = sem música para o MoneyPrinter
        avisos.append(f"sem música '{preset['bgm_prefixo']}*' em storage/bgm; vídeo sai sem música")
    tarefa.update(r.get("ajustes", {}))

    palavras = len(roteiro.split())
    segundos = palavras / (PALAVRAS_POR_SEGUNDO * float(tarefa.get("voice_rate", 1.0)))
    if not preset["palavras_min"] <= palavras <= preset["palavras_max"]:
        avisos.append(f"{palavras} palavras, fora da faixa {preset['palavras_min']}-{preset['palavras_max']}")
    modo = f"{len(r['cenas'])} cenas sincronizadas" if "cenas" in r else "modo antigo (sem sincronia)"
    avisos.insert(0, f"{palavras} palavras, cerca de {segundos:.0f}s de narração, {modo}")
    return tarefa, avisos


def texto_post(r: dict) -> str:
    partes = [f"TÍTULO:\n{r['titulo']}", f"DESCRIÇÃO:\n{r['descricao']}\n\n{' '.join(r['hashtags'])}"]
    if r.get("comentario_fixado"):
        partes.append(f"COMENTÁRIO FIXADO:\n{r['comentario_fixado']}")
    if r.get("_creditos"):
        partes.append("CRÉDITOS (colar no fim da descrição):\n" + "\n".join(f"- {c}" for c in r["_creditos"]))
    partes.append("LEMBRETE: marcar 'Conteúdo alterado ou sintético = Sim' (voz de IA).")
    return "\n\n".join(partes) + "\n"


def rodar_cli(tarefas: list[dict], stop_at: str | None = None) -> dict:
    lotes = MPT / "storage" / "lotes"
    lotes.mkdir(parents=True, exist_ok=True)
    manifesto = lotes / f"lote_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    manifesto.write_text(json.dumps(tarefas, ensure_ascii=False, indent=2), encoding="utf-8")
    cmd = [str(PYTHON), "cli.py", "--batch-file", str(manifesto)]
    if stop_at:
        cmd += ["--stop-at", stop_at]
    proc = subprocess.run(cmd, cwd=MPT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        sys.exit(f"não consegui ler o resultado do cli.py (código {proc.returncode}):\n{proc.stdout[-2000:]}")


def pasta_tarefa(item: dict) -> Path:
    return MPT / "storage" / "tasks" / item["task_id"]


def falhou(item: dict, slug: str) -> bool:
    if item["status"] != "succeeded" and item.get("error"):
        print(f"FALHOU [{slug}] no estágio {item.get('failed_stage')}: {item.get('error')}")
        return True
    return False


def entregar(r: dict, pasta: Path, so_audio: bool) -> None:
    SAIDA.mkdir(exist_ok=True)
    base = SAIDA / f"{date.today():%Y-%m-%d}_{r['slug']}{r.get('_sufixo', '')}"
    if so_audio:
        audio = next(pasta.glob("audio*.mp3"), None)
        if audio:
            shutil.copy(audio, base.with_suffix(".mp3"))
            print(f"ÁUDIO  [{r['slug']}] {base.with_suffix('.mp3')}")
        return
    video = next(iter(sorted(pasta.glob("final*.mp4"))), None)
    if not video:
        print(f"FALHOU [{r['slug']}] vídeo final não encontrado em {pasta}")
        return
    shutil.copy(video, base.with_suffix(".mp4"))
    base.with_suffix(".txt").write_text(texto_post(r), encoding="utf-8")
    print(f"PRONTO [{r['slug']}] {base.with_suffix('.mp4')}")


def produzir_sincronizado(r: dict, tarefa: dict, preset: dict, so_audio: bool, render_mpt: bool = False) -> None:
    """Etapa A (MoneyPrinter): narração + legenda. Etapa B: clipes cortados no tempo de cada cena,
    montados por render.py (ffmpeg + placa de vídeo) ou, com --render-mpt, pelo MoneyPrinter (lento)."""
    item = rodar_cli([tarefa], stop_at="subtitle")["tasks"][0]
    if falhou(item, r["slug"]):
        return
    pasta_a = pasta_tarefa(item)
    if so_audio:
        entregar(r, pasta_a, so_audio=True)
        return

    for p in sync.respirar(r["cenas"], pasta_a / "audio.mp3", pasta_a / "subtitle.srt"):
        print(f"AVISO  [{r['slug']}] {p}")
    dur = sync.duracao_audio(pasta_a / "audio.mp3")
    tempos, avisos = sync.tempos_das_cenas(r["cenas"], sync.ler_srt(pasta_a / "subtitle.srt"), dur)
    for a in avisos:
        print(f"AVISO  [{r['slug']}] {a}")

    pexels = sync.Pexels(MPT / "config.toml", LOCAL_VIDEOS / "pexels_cache")
    cur_arq = RAIZ / "producao" / "curadoria" / r["slug"] / "candidatos.json"
    curadoria = json.loads(cur_arq.read_text(encoding="utf-8")) if cur_arq.exists() else None
    midia = RAIZ / "producao" / "midia" / r["slug"]
    sem_escolha = [i for i, c in enumerate(r["cenas"], 1)
                   if not c.get("escolha") and not (midia.exists() and any(midia.glob(f"cena_{i:02d}*")))]
    if sem_escolha:
        print(f"AVISO  [{r['slug']}] cenas sem curadoria (busca automática): {sem_escolha}")
    tomadas, relatorio = sync.montar_tomadas(
        r["cenas"], tempos, float(preset.get("corte_max", 3.0)), pexels, LOCAL_VIDEOS / "sync" / r["slug"],
        preset.get("evitar_termos"), curadoria, RAIZ / "producao" / "midia" / r["slug"],
    )
    creditos_bgm = MPT / "storage" / "bgm" / "creditos.json"
    if tarefa.get("bgm_file") and creditos_bgm.exists():
        musica_cred = json.loads(creditos_bgm.read_text(encoding="utf-8")).get(tarefa["bgm_file"])
        if musica_cred:
            r.setdefault("_creditos", []).append(musica_cred)
    if curadoria:
        por_ref = {c["ref"]: c for lista in curadoria.values() for c in lista}
        usados = [por_ref[ref] for c in r["cenas"] for ref in c.get("escolha", []) if ref in por_ref]
        r["_creditos"] = list(dict.fromkeys(r.get("_creditos", []) + [c["credito"] for c in usados if c["credito"] not in ("Pexels", "Pixabay", "NASA")]))
    print(f"linha do tempo [{r['slug']}] narração {dur:.1f}s, {len(tomadas)} tomadas:")
    print("\n".join(relatorio))

    if not render_mpt:
        pasta_sync = LOCAL_VIDEOS / "sync" / r["slug"]
        musica = MPT / "storage" / "bgm" / tarefa["bgm_file"] if tarefa.get("bgm_type") == "custom" else None
        saida = pasta_sync / "final.mp4"
        inicio = datetime.now()
        encoder = render.renderizar(
            [Path(t["url"]) for t in tomadas], sum(t["frames"] for t in tomadas), pasta_a / "audio.mp3",
            pasta_a / "subtitle.srt", musica, tarefa, pasta_sync, MPT / "resource" / "fonts", saida,
        )
        print(f"render [{r['slug']}] {encoder} em {(datetime.now() - inicio).total_seconds():.0f}s")
        sync.painel([Path(t["url"]) for t in tomadas], pasta_sync / "painel.png")
        print(f"painel [{r['slug']}] {pasta_sync / 'painel.png'}  <- REVISAR as imagens antes de entregar")
        entregar(r, pasta_sync, so_audio=False)
        return

    for t in tomadas:
        t.pop("frames", None)
    final = dict(tarefa)
    final.pop("video_terms", None)
    final.update(
        video_source="local",
        video_materials=tomadas,
        video_concat_mode="sequential",
        match_materials_to_script=False,
        video_clip_duration=max(t["duration"] for t in tomadas) + 1,
        video_clip_speed=1.0,
    )
    item = rodar_cli([final])["tasks"][0]
    if not falhou(item, r["slug"]):
        entregar(r, pasta_tarefa(item), so_audio=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("arquivo")
    ap.add_argument("--so-audio", action="store_true", help="para no estágio de áudio")
    ap.add_argument("--seco", action="store_true", help="não executa, só mostra")
    ap.add_argument("--sem-musica", action="store_true", help="versão sem música (p/ usar áudio do TikTok); salva como <slug>_sem-musica")
    ap.add_argument("--render-mpt", action="store_true", help="monta pelo MoneyPrinter (lento), em vez do ffmpeg")
    args = ap.parse_args()

    presets = json.loads((SKILL / "presets.json").read_text(encoding="utf-8"))
    roteiros = json.loads(Path(args.arquivo).read_text(encoding="utf-8"))

    planos = []
    for r in roteiros:
        if r["nicho"] not in presets or r["nicho"].startswith("_"):
            sys.exit(f"nicho desconhecido em '{r['slug']}': {r['nicho']}")
        tarefa, avisos = montar_tarefa(r, presets[r["nicho"]])
        if args.sem_musica:
            tarefa["bgm_type"] = ""
            tarefa.pop("bgm_file", None)
            r["_sufixo"] = "_sem-musica"
            avisos.append("SEM música (versão TikTok)")
        planos.append((r, tarefa))
        print(f"[{r['slug']}] " + " | ".join(avisos))
    if args.seco:
        return

    antigos = [(r, t) for r, t in planos if "cenas" not in r]
    if antigos:
        resumo = rodar_cli([t for _, t in antigos], stop_at="audio" if args.so_audio else None)
        for item in resumo["tasks"]:
            r = antigos[item["index"]][0]
            if not falhou(item, r["slug"]):
                entregar(r, pasta_tarefa(item), args.so_audio)

    for r, tarefa in planos:
        if "cenas" in r:
            produzir_sincronizado(r, tarefa, presets[r["nicho"]], args.so_audio, args.render_mpt)


if __name__ == "__main__":
    main()
