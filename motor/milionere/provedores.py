"""Camada trocável de imagem: mesma interface do imagens.py (ComfyUI), escolhendo o provedor pela config.

    MILIONERE_IMAGEM=auto    -> plano pago/chave_propria: Gemini (reserva: ComfyUI); grátis: ComfyUI
    MILIONERE_IMAGEM=comfy   -> sempre ComfyUI local
    MILIONERE_IMAGEM=gemini  -> Gemini (reserva: ComfyUI)
    MILIONERE_IMAGEM=manual  -> não gera nada: grava prompts.txt e espera o usuário subir as imagens

Imagens que o usuário já colocou em producao/midia/<slug>/cena_NN.* têm prioridade sempre
(o pipeline só pede as cenas que faltam).
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos  # noqa: E402
import imagens  # noqa: E402


def modo() -> str:
    if caminhos.IMAGEM != "auto":
        return caminhos.IMAGEM
    return "gemini" if caminhos.PLANO in ("pago", "chave_propria") else "comfy"


class Sessao:
    """Liga o ComfyUI só quando for preciso (no Gemini, só se cair na reserva) e desliga no fim."""

    def __init__(self):
        self.proc = None
        self.comfy_ligado = False
        self.gemini_ok = modo() == "gemini"

    def comfy(self):
        if not self.comfy_ligado:
            self.proc = imagens.garantir_comfy()
            self.comfy_ligado = True


def garantir_comfy() -> Sessao:
    s = Sessao()
    if modo() == "comfy":
        s.comfy()
    return s


def derrubar(s: Sessao | None) -> None:
    if s and s.proc:
        imagens.derrubar(s.proc)


_SESSAO: Sessao | None = None


def _sessao() -> Sessao:
    global _SESSAO
    _SESSAO = _SESSAO or Sessao()
    return _SESSAO


def _prompts_manuais(roteiro: dict, nome_estilo: str, pasta: Path, cenas: list[int]) -> None:
    estilo = imagens.estilos()[nome_estilo]
    pers = {p["id"]: p for p in roteiro.get("personagens", [])}
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "prompts.txt").write_text("\n\n".join(
        f"cena_{n:02d}.jpg\nGenerate ONE single image, vertical 9:16. "
        f"{imagens.prompt_cena(roteiro['cenas'][n - 1], pers, estilo, roteiro.get('cenario_en', ''))}"
        for n in cenas), encoding="utf-8")


def _uma(roteiro: dict, nome_estilo: str, n: int, destino: Path, seed: int) -> Path:
    s = _sessao()
    if s.gemini_ok:
        import imagem_gemini
        try:
            return imagem_gemini.gerar_cena(roteiro, nome_estilo, n, destino, imagem_gemini.chave())
        except imagem_gemini.SemCota as e:
            print(f"  Gemini indisponível ({e}); usando o ComfyUI como reserva")
            s.gemini_ok = False
    s.comfy()
    return imagens._gerar_cena(roteiro, nome_estilo, n, destino, seed)


def gerar_cenas(roteiro: dict, nome_estilo: str, pasta: Path, so: list[int] | None = None,
                nova_seed: bool = False) -> list[Path]:
    alvo = [n for n in range(1, len(roteiro["cenas"]) + 1) if not so or n in so]
    if modo() == "manual":
        _prompts_manuais(roteiro, nome_estilo, pasta, alvo)
        raise SystemExit(f"modo manual: gere as cenas {alvo} com os prompts de {pasta / 'prompts.txt'}, "
                         "salve como cena_NN.jpg nessa pasta e rode de novo com --retomar")
    base = imagens._seed_fixa(roteiro["slug"])
    feitos = []
    for n in alvo:
        for velho in pasta.glob(f"cena_{n:02d}*"):
            velho.unlink()
        seed = base + n + (random.randint(1, 10**6) if nova_seed else 0)
        feitos.append(_uma(roteiro, nome_estilo, n, pasta / f"cena_{n:02d}.png", seed))
    return feitos


def gerar_opcoes(roteiro: dict, nome_estilo: str, pasta: Path, n: int, k: int = 3) -> list[Path]:
    destino = pasta / "opcoes"
    destino.mkdir(parents=True, exist_ok=True)
    for velho in destino.glob(f"cena_{n:02d}_*"):
        velho.unlink()
    return [_uma(roteiro, nome_estilo, n, destino / f"cena_{n:02d}_{j}.png", random.randint(0, 2**31 - 1))
            for j in range(1, k + 1)]
