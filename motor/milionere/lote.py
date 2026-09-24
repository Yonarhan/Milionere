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


def livres(formatos: dict) -> dict[str, int]:
    usados = pipeline.usados()
    return {f: sum(1 for t in biblia.temas().get(v["catalogo"], []) if f"{f}:{t['id']}" not in usados)
            for f, v in formatos.items()}


def proximo_formato(formatos: dict, permitidos: list[str]) -> str | None:
    """O formato com menos vídeos feitos (entre os que ainda têm tema livre): o canal fica variado."""
    usados, restam = pipeline.usados(), livres(formatos)
    feitos = {f: sum(1 for u in usados if u.startswith(f"{f}:")) for f in permitidos}
    candidatos = [f for f in permitidos if restam.get(f, 0) > 0]
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
    ap.add_argument("--musica", choices=["com", "sem", "ambas"], default="ambas")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()

    formatos = pipeline.carregar("formatos.json")
    permitidos = a.formatos.split(",") if a.formatos else list(formatos)
    if a.status:
        for f, n in livres(formatos).items():
            print(f"{f:12} {formatos[f]['nome']:35} {n} temas livres")
        return

    inicio, prontos, falhas = time.time(), [], []
    tentados: set[str] = set()  # tema que falhou não é sorteado de novo nesta rodada (amanhã tenta outra vez)
    for i in range(1, a.qtd + 1):
        fmt = proximo_formato(formatos, permitidos)
        if not fmt:
            pipeline.log("LOTE: acabaram os temas dos formatos pedidos; cadastre novos em dados/biblia/temas.json")
            break
        try:
            tema = biblia.sortear(fmt, formatos[fmt]["catalogo"], pipeline.usados() | tentados)
        except RuntimeError:
            permitidos = [f for f in permitidos if f != fmt]
            continue
        tentados.add(f"{fmt}:{tema['id']}")
        pipeline.log(f"LOTE {i}/{a.qtd}: {fmt} · {tema['id']}")
        try:
            feitos = pipeline.um_video(fmt, None, tema["id"], a.musica)
            prontos += feitos
            if not feitos:
                falhas.append(f"{fmt}:{tema['id']}: roteiro reprovado")
        except Exception as e:  # noqa: BLE001 - um vídeo ruim não para os outros
            traceback.print_exc()
            falhas.append(f"{fmt}:{tema['id']}: {type(e).__name__}: {e}")
    if prontos:
        anotar_fila(prontos)
    pipeline.log(alimentar_bancos())
    pipeline.log(f"LOTE FIM em {(time.time() - inicio) / 60:.1f} min: {len(prontos)} arquivo(s) de vídeo, "
                 f"{len(falhas)} falha(s)" + (f" -> {falhas}" if falhas else ""))
    pipeline.log(f"fila de postagem: {FILA}")


if __name__ == "__main__":
    main()
