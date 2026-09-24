"""Camada trocável de imagem: mesma interface do imagens.py (ComfyUI), escolhendo o provedor pela config.

    MILIONERE_IMAGEM=auto        -> pago/chave_propria: Gemini; grátis: ComfyUI se instalado, senão Cloudflare
    MILIONERE_IMAGEM=comfy       -> sempre ComfyUI local
    MILIONERE_IMAGEM=gemini      -> Gemini (reserva: ComfyUI)
    MILIONERE_IMAGEM=cloudflare  -> Cloudflare Workers AI, FLUX.2 klein (cota grátis diária; reserva: Gemini/ComfyUI)
    MILIONERE_IMAGEM=manual      -> não gera nada: grava prompts.txt e espera o usuário subir as imagens

Antes de qualquer gerador, cada cena consulta o BANCO do nicho:
    nota >= banco_imagens.LIMIAR_REUSO (0,55) -> reusa a imagem (custo zero, nada é gerado)
    nota >= LIMIAR_REFERENCIA (0,40)          -> gera usando a imagem do banco como referência de estilo/rosto
    abaixo                                    -> gera do zero (com o retrato do personagem, se houver)
Imagens que o usuário já colocou em producao/midia/<slug>/cena_NN.* têm prioridade sempre
(o pipeline só pede as cenas que faltam).
"""

import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos  # noqa: E402
import imagens  # noqa: E402

LIMIAR_REFERENCIA = 0.40  # parecida o bastante para guiar o estilo e o rosto, mas não para reusar


def modo() -> str:
    if caminhos.IMAGEM != "auto":
        return caminhos.IMAGEM
    if caminhos.PLANO in ("pago", "chave_propria"):
        return "gemini"
    if caminhos.COMFY.exists():
        return "comfy"
    import imagem_cloudflare
    return "cloudflare" if imagem_cloudflare.disponivel() else "comfy"


class Sessao:
    """Liga o ComfyUI só quando for preciso (no Gemini, só se cair na reserva) e desliga no fim."""

    def __init__(self):
        self.proc = None
        self.comfy_ligado = False
        self.gemini_ok = modo() == "gemini"
        self.cloudflare_ok = modo() == "cloudflare"
        self.usados_banco: set[int] = set()  # a mesma imagem do banco não repete dentro de um vídeo

    def comfy(self):
        if not self.comfy_ligado:
            self.proc = imagens.garantir_comfy()
            self.comfy_ligado = True


def garantir_comfy() -> Sessao:
    """Chamado no começo das imagens de cada vídeo: sessão nova (cota do dia e banco zerados)."""
    global _SESSAO
    s = _SESSAO = Sessao()
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


def _consultar_banco(roteiro: dict, n: int) -> dict | None:
    """A imagem do banco do nicho que mais parece com a cena (ou None se o banco não estiver disponível)."""
    try:
        import banco_imagens
        cena = roteiro["cenas"][n - 1]
        nomes = {p["id"]: p.get("nome", "") for p in roteiro.get("personagens", [])}
        texto = " | ".join(x for x in (cena["fala"], " ".join(nomes.get(i, "") for i in cena.get("personagens", [])),
                                       cena.get("imagem", "")) if x.strip())
        nicho = banco_imagens.NICHO_DO_PRESET.get(roteiro.get("nicho", ""), roteiro.get("nicho", ""))
        return next(iter(banco_imagens.buscar(nicho, texto, excluir=_sessao().usados_banco, k=1)), None)
    except Exception as e:  # o banco nunca derruba a geração
        print(f"  banco de imagens indisponível: {e}")
        return None


def _uma(roteiro: dict, nome_estilo: str, n: int, destino: Path, seed: int, banco: bool = True) -> Path:
    import time as _t
    import medidor
    s = _sessao()
    inicio = _t.time()
    achado = _consultar_banco(roteiro, n) if banco else None
    if achado:
        import banco_imagens
        if achado["nota"] >= banco_imagens.LIMIAR_REUSO:
            alvo = destino.with_suffix(achado["arquivo"].suffix)
            shutil.copy(achado["arquivo"], alvo)
            s.usados_banco.add(achado["id"])
            banco_imagens.marcar_uso([achado["id"]])
            medidor.imagem("banco", _t.time() - inicio)
            print(f"  cena {n:>2} BANCO (nota {achado['nota']:.2f})  «{roteiro['cenas'][n - 1]['fala'][:50]}»")
            return alvo
    refs = [achado["arquivo"]] if achado and achado["nota"] >= LIMIAR_REFERENCIA else []
    if refs:
        s.usados_banco.add(achado["id"])
        print(f"  cena {n:>2} referência do banco (nota {achado['nota']:.2f})")
    if s.cloudflare_ok:
        import imagem_cloudflare
        try:
            feito = imagem_cloudflare.gerar_cena(roteiro, nome_estilo, n, destino, refs)
            medidor.imagem("cloudflare-flux2-klein", _t.time() - inicio)
            return feito
        except imagem_cloudflare.SemCota as e:
            print(f"  Cloudflare indisponível ({e}); usando a reserva")
            s.cloudflare_ok = False
            s.gemini_ok = s.gemini_ok or caminhos.PLANO in ("pago", "chave_propria")
    if s.gemini_ok:
        import imagem_gemini
        try:
            feito = imagem_gemini.gerar_cena(roteiro, nome_estilo, n, destino, imagem_gemini.chave())
            medidor.imagem(imagem_gemini.MODELOS[0], _t.time() - inicio)
            return feito
        except imagem_gemini.SemCota as e:
            print(f"  Gemini indisponível ({e}); usando o ComfyUI como reserva")
            s.gemini_ok = False
    s.comfy()
    feito = imagens._gerar_cena(roteiro, nome_estilo, n, destino, seed)
    medidor.imagem("comfy", _t.time() - inicio)
    return feito


def gerar_cenas(roteiro: dict, nome_estilo: str, pasta: Path, so: list[int] | None = None,
                nova_seed: bool = False, banco: bool = True) -> list[Path]:
    """banco=False: não consulta o banco aqui (o pipeline bíblico já consultou, com filtro de cena genérica)."""
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
        feitos.append(_uma(roteiro, nome_estilo, n, pasta / f"cena_{n:02d}.png", seed, banco=banco))
    return feitos


def gerar_opcoes(roteiro: dict, nome_estilo: str, pasta: Path, n: int, k: int = 3) -> list[Path]:
    destino = pasta / "opcoes"
    destino.mkdir(parents=True, exist_ok=True)
    for velho in destino.glob(f"cena_{n:02d}_*"):
        velho.unlink()
    # refação de cena reprovada: gera de novo (reusar do banco traria de volta a mesma imagem ruim)
    return [_uma(roteiro, nome_estilo, n, destino / f"cena_{n:02d}_{j}.png", random.randint(0, 2**31 - 1), banco=False)
            for j in range(1, k + 1)]
