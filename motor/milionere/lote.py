"""Lote automático do canal: N vídeos end-to-end por rodada, alternando formatos, sem repetir tema.

    python lote.py --qtd 2                              # 2 vídeos; o formato menos usado vai primeiro
    python lote.py --qtd 3 --formatos historia,personagem
    python lote.py --status                             # quantos temas ainda restam por formato

Um vídeo que falha não para o lote. No fim, as imagens e os roteiros aprovados entram nos bancos
(banco_imagens / banco_roteiros) e a fila de postagem é atualizada em <PRODUCAO>/fila_postagem.md.
Para rodar todo dia: agendador do Windows ou cron (ver SETUP.md, "Lote automático").
"""

import argparse
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import biblia  # noqa: E402
import pipeline  # noqa: E402
from caminhos import PRODUCAO  # noqa: E402

FILA = PRODUCAO / "fila_postagem.md"
FALHAS = PRODUCAO / "falhas_temas.json"  # "formato:tema" -> nº de falhas; 2+ sai do sorteio até alguém revisar


def falhas() -> dict[str, int]:
    import json
    return json.loads(FALHAS.read_text(encoding="utf-8")) if FALHAS.exists() else {}


def anotar_falha(chave: str) -> None:
    import json
    f = falhas()
    f[chave] = f.get(chave, 0) + 1
    FALHAS.write_text(json.dumps(f, ensure_ascii=False, indent=2), encoding="utf-8")


def livres(formatos: dict) -> dict[str, int]:
    usados = pipeline.usados()
    return {f: sum(1 for t in biblia.temas().get(v["catalogo"], []) if f"{f}:{t['id']}" not in usados)
            for f, v in formatos.items()}


def proximo_formato(formatos: dict, permitidos: list[str]) -> str | None:
    """O formato com menos vídeos feitos (entre os que ainda têm tema livre): o canal fica variado."""
    usados, restam = pipeline.usados(), livres(formatos)
    # falha pesa como 2 vídeos feitos: o formato que está falhando cede a vez (a noite de 24/09 ficou presa na parábola)
    feitos = {f: sum(1 for u in usados if u.startswith(f"{f}:")) + 2 * sum(n for k, n in falhas().items()
              if k.startswith(f"{f}:")) for f in permitidos}
    candidatos = list(permitidos)  # catálogo vazio não sai da rotação: biblia.sortear repõe com temas novos da Bíblia
    return min(candidatos, key=lambda f: (feitos[f], -restam[f])) if candidatos else None


def alimentar_bancos() -> str:
    try:
        import banco_imagens
        import banco_roteiros
        return f"bancos: +{banco_imagens.indexar_repo()} imagens, +{banco_roteiros.indexar_repo()} roteiros"
    except Exception as e:  # noqa: BLE001 - banco é bônus, não pode derrubar o lote
        return f"bancos: não alimentados ({e})"


def anotar_fila(prontos: list[Path]) -> None:
    novo = not FILA.exists()
    with FILA.open("a", encoding="utf-8") as f:
        if novo:
            f.write("# Fila de postagem\n\nAssista antes de postar (1 min em 2x). Marque [x] quando postar.\n"
                    "Versão com música: YouTube. Versão *_sem-musica*: TikTok (use um som em alta do app).\n\n")
        for p in prontos:
            f.write(f"- [ ] {datetime.now():%d/%m %H:%M} · `{p.name}` · post: `{p.with_suffix('.txt').name}`\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qtd", type=int, default=1)
    ap.add_argument("--formatos", help="lista separada por vírgula (padrão: todos)")
    ap.add_argument("--musica", choices=["com", "sem", "ambas"], default="sem",
                    help="um vídeo só (com ou sem música); ambas = monta uma vez e mistura a música numa 2ª cópia")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--postar", action="store_true", help="no fim, sobe como PRIVADO no YouTube o que ficou pronto sem aviso")
    a = ap.parse_args()

    formatos = pipeline.carregar("formatos.json")
    permitidos = a.formatos.split(",") if a.formatos else list(formatos)
    if a.status:
        for f, n in livres(formatos).items():
            print(f"{f:12} {formatos[f]['nome']:35} {n} temas livres")
        return

    inicio, prontos, erros = time.time(), [], []
    tentados: set[str] = set()  # tema que falhou não é sorteado de novo nesta rodada (amanhã tenta outra vez)
    for i in range(1, a.qtd + 1):
        fmt = proximo_formato(formatos, permitidos)
        if not fmt:
            pipeline.log("LOTE: acabaram os temas dos formatos pedidos; cadastre novos em dados/biblia/temas.json")
            break
        try:
            travados = {k for k, n in falhas().items() if n >= 2}
            tema = biblia.sortear(fmt, formatos[fmt]["catalogo"], pipeline.usados() | tentados | travados)
        except RuntimeError:
            permitidos = [f for f in permitidos if f != fmt]
            continue
        tentados.add(f"{fmt}:{tema['id']}")
        pipeline.log(f"LOTE {i}/{a.qtd}: {fmt} · {tema['id']}")
        try:
            # roteiro já aprovado antes (a rodada caiu depois dele): retoma, não paga outro roteiro
            aprovado = sorted(PRODUCAO.glob(f"roteiros/*_{fmt}-{tema['id']}.json"))
            if aprovado:
                pipeline.log(f"retomando roteiro já aprovado: {aprovado[-1].name}")
                feitos = pipeline.imagens_e_video(aprovado[-1], a.musica)
            else:
                feitos = pipeline.um_video(fmt, None, tema["id"], a.musica)
            prontos += feitos
            if not feitos:
                erros.append(f"{fmt}:{tema['id']}: roteiro reprovado")
                anotar_falha(f"{fmt}:{tema['id']}")
        except BaseException as e:  # noqa: BLE001 - inclui sys.exit (ComfyUI não subiu): um vídeo ruim não para os outros
            if isinstance(e, KeyboardInterrupt):
                raise
            traceback.print_exc()
            erros.append(f"{fmt}:{tema['id']}: {type(e).__name__}: {e}")
            anotar_falha(f"{fmt}:{tema['id']}")
    if prontos:
        anotar_fila(prontos)
    if a.postar:
        try:
            import postar
            ids = postar.postar_pendentes()
            pipeline.log(f"YouTube: {len(ids)} vídeo(s) enviados como privados: {[f'https://youtu.be/{i}' for i in ids]}")
        except BaseException as e:  # noqa: BLE001 - sys.exit do postar (sem token) não pode derrubar o lote
            pipeline.log(f"YouTube: não postei ({e})")
    pipeline.log(alimentar_bancos())
    pipeline.log(f"LOTE FIM em {(time.time() - inicio) / 60:.1f} min: {len(prontos)} arquivo(s) de vídeo, "
                 f"{len(erros)} falha(s)" + (f" -> {erros}" if erros else ""))
    pipeline.log(f"fila de postagem: {FILA}")


if __name__ == "__main__":
    main()
