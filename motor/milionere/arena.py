"""Arena de modelos: os mesmos temas, o mesmo roteirista guiado do site, trocando só o modelo.

    python arena.py --estimar                         # só mostra o plano e o custo estimado, não gasta nada
    python arena.py                                   # fase 1 (roteiristas) + fase 2 (juízes)
    python arena.py --escritores haiku,sonnet --temas 4 --sem-juizes --orcamento 10

Fase 1: cada modelo escreve os temas pelo fluxo real (_roteiro_generico: guia -> código -> juiz -> reescrita).
        O juiz é fixo (--juiz, padrão sonnet) para a comparação ser justa.
Fase 2: todos os roteiros finais passam por cada candidato a juiz; a referência é o opus.
        Mede se o juiz barato aprova/reprova igual ao caro e quanto as notas diferem.

Usa a API direta (MILIONERE_LLM=api; ANTHROPIC_API_KEY no .env). Não grava nada nos bancos de roteiros.
Relatório em <PRODUCAO>/arena/<data>.md + .json (o JSON é salvo a cada roteiro).
"""

import argparse
import json
import statistics as st
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import banco_roteiros  # noqa: E402
import caminhos  # noqa: E402
import llm_api  # noqa: E402
import medidor  # noqa: E402
import servico_pipeline as sp  # noqa: E402

TEMAS = [  # (nicho, formato, tema): mistura de nichos e formatos do catálogo
    ("astronomia", "Fato que dá “uau”", "O planeta onde chove vidro de lado"),
    ("animais", "Bicho bizarro", "Três corações e sangue azul"),
    ("astronomia", "E se…?", "E se a Terra parasse de girar?"),
    ("gospel", "Personagem bíblico em 30s", "Sansão"),
    ("animais", "Bicho bizarro", "O animal que não morre de velhice"),
    ("astronomia", "Fato que dá “uau”", "Uma colher de estrela de nêutrons"),
    ("gospel", "História bíblica narrada", "Zaqueu subiu na árvore pra ver Jesus"),
    ("astronomia", "E se…?", "E se a Lua sumisse hoje à noite?"),
]
# tokens estimados por chamada (entrada, saída) para o --estimar; a medição real substitui isso no relatório
ESTIMATIVA = {"roteirista": (7000, 3000), "juiz": (1800, 1200)}
TENTATIVAS_MEDIAS = 1.6


def _custo(modelo: str, papel: str, n: float) -> float:
    ent, sai = llm_api.PRECOS[llm_api.modelo_id(modelo)]
    e, s = ESTIMATIVA[papel]
    return n * (e * ent + s * sai) / 1e6


def estimar(escritores, juiz, juizes, n_temas) -> float:
    usd = 0.0
    for m in escritores:
        usd += _custo(m, "roteirista", n_temas * TENTATIVAS_MEDIAS) + _custo(juiz, "juiz", n_temas * TENTATIVAS_MEDIAS)
    for j in juizes:
        usd += _custo(j, "juiz", n_temas * len(escritores))
    return usd


def _sem_gravar_bancos():
    banco_roteiros.adicionar = lambda *a, **k: None
    banco_roteiros.registrar_erros = lambda *a, **k: None


def _salvar(pasta: Path, nome: str, dados: dict) -> None:
    (pasta / f"{nome}.json").write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")


def fase_escritores(escritores, juiz, temas, orcamento_brl, dados, salvar):
    caminhos.MODELO_JUIZ = juiz
    for modelo in escritores:
        caminhos.MODELO_ROTEIRO = modelo
        for nicho, formato, tema in temas:
            gasto = sum(r["custos"]["brl"] for r in dados["escritores"])
            if gasto >= orcamento_brl:
                print(f"orçamento de R$ {orcamento_brl:.2f} atingido (R$ {gasto:.2f}); parando a fase 1")
                return
            print(f"[{modelo}] {nicho} · {tema}", flush=True)
            entrada = {"nicho": nicho, "formato_nome": formato, "tema_livre": tema}
            def log(_etapa, msg):  # noqa: E306
                print(f"   {msg}", flush=True)
            with medidor.medir() as m:
                inicio = time.time()
                try:
                    r = sp._roteiro_generico(entrada, log)
                    erro = None
                except Exception as e:  # noqa: BLE001 - a arena registra e segue
                    r, erro = None, f"{type(e).__name__}: {e}"
                segundos = time.time() - inicio
            item = {"modelo": modelo, "nicho": nicho, "formato": formato, "tema": tema, "erro": erro,
                    "segundos": round(segundos, 1), "custos": m.resumo()}
            if r:
                item.update(titulo=r["titulo"], falas=[c["fala"] for c in r["cenas"]], notas=r.get("_notas_juiz", {}),
                            tentativas=r.get("_tentativas"), aprovado=not r.get("_avisos"), avisos=r.get("_avisos", []))
            print(f"   -> {'ERRO ' + erro if erro else ('aprovado' if item['aprovado'] else 'reprovado')} "
                  f"em {item.get('tentativas')} tentativa(s) · R$ {item['custos']['brl']:.2f} · {segundos:.0f}s", flush=True)
            dados["escritores"].append(item)
            salvar()


def fase_juizes(juizes, dados, salvar, orcamento_brl):
    finais = [r for r in dados["escritores"] if r.get("falas")]
    for juiz in juizes:
        caminhos.MODELO_JUIZ = juiz
        for r in finais:
            gasto = sum(x["custos"]["brl"] for x in dados["escritores"]) + sum(x["custos"]["brl"] for x in dados["juizes"])
            if gasto >= orcamento_brl:
                print(f"orçamento atingido (R$ {gasto:.2f}); parando a fase 2")
                return
            roteiro = {"cenas": [{"fala": f} for f in r["falas"]]}
            with medidor.medir() as m:
                inicio = time.time()
                try:
                    problemas, notas = sp._juiz(roteiro, {"nicho": r["nicho"]}, r["tema"])
                    erro = None
                except Exception as e:  # noqa: BLE001
                    problemas, notas, erro = [], {}, f"{type(e).__name__}: {e}"
            dados["juizes"].append({"juiz": juiz, "escritor": r["modelo"], "tema": r["tema"], "notas": notas,
                                    "aprova": not problemas and not erro, "problemas": problemas, "erro": erro,
                                    "segundos": round(time.time() - inicio, 1), "custos": m.resumo()})
            print(f"[juiz {juiz}] {r['modelo']} · {r['tema']}: {'aprova' if not problemas else 'reprova'}"
                  f" · R$ {m.resumo()['brl']:.3f}", flush=True)
            salvar()


def _media(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else 0.0


def _tokens(item, etapa, campo):
    return item["custos"]["por_etapa"].get(etapa, {}).get(campo, 0)


def relatorio(dados: dict) -> str:
    L = [f"# Arena de modelos · {dados['data']}", "",
         f"Juiz fixo da fase 1: **{dados['juiz']}** · temas: {len(dados['temas'])} · dólar R$ {medidor.DOLAR}", ""]
    total = sum(x["custos"]["brl"] for x in dados["escritores"] + dados["juizes"])
    L += [f"**Gasto total do teste: R$ {total:.2f}**", "", "## Fase 1: roteiristas", "",
          "| Modelo | Aprovado na 1ª | Aprovado no fim | Tentativas | Nota média | R$ por roteiro (escrita) | R$ total c/ juiz | Tempo | Tokens entrada/saída por escrita |",
          "|---|---|---|---|---|---|---|---|---|"]
    for m in dados["escritores_pedidos"]:
        rs = [r for r in dados["escritores"] if r["modelo"] == m and not r["erro"]]
        if not rs:
            continue
        n = len(rs)
        prim = sum(1 for r in rs if r.get("aprovado") and r.get("tentativas") == 1)
        fim = sum(1 for r in rs if r.get("aprovado"))
        notas = [_media(r["notas"].values()) for r in rs if r.get("notas")]
        chamadas = sum(_tokens(r, "roteiro", "chamadas") for r in rs) or 1
        L.append(f"| {llm_api.modelo_id(m)} | {prim}/{n} | {fim}/{n} | {_media([r['tentativas'] for r in rs]):.1f} "
                 f"| {_media(notas):.2f} | {_media([r['custos']['por_etapa'].get('roteiro', {}).get('brl', 0) for r in rs]):.2f} "
                 f"| {_media([r['custos']['brl'] for r in rs]):.2f} | {_media([r['segundos'] for r in rs]):.0f}s "
                 f"| {sum(_tokens(r, 'roteiro', 'tokens_entrada') for r in rs) // chamadas} / "
                 f"{sum(_tokens(r, 'roteiro', 'tokens_saida') for r in rs) // chamadas} |")
    erros = [r for r in dados["escritores"] if r["erro"]]
    if erros:
        L += ["", "Falhas: " + "; ".join(f"{r['modelo']} · {r['tema']}: {r['erro'][:120]}" for r in erros)]
    if dados["juizes"]:
        ref = {(j["escritor"], j["tema"]): j for j in dados["juizes"] if j["juiz"] == dados["juiz_referencia"]}
        L += ["", f"## Fase 2: juízes (referência: {dados['juiz_referencia']})", "",
              "| Juiz | Aprova | Concorda com a referência | Diferença média de nota | R$ por revisão | Tempo |", "|---|---|---|---|---|---|"]
        for j in dados["juizes_pedidos"]:
            js = [x for x in dados["juizes"] if x["juiz"] == j and not x["erro"]]
            if not js:
                continue
            pares = [(x, ref[(x["escritor"], x["tema"])]) for x in js if (x["escritor"], x["tema"]) in ref]
            conc = sum(1 for a, b in pares if a["aprova"] == b["aprova"])
            dif = _media([_media([abs(a["notas"][k] - b["notas"][k]) for k in a["notas"]]) for a, b in pares if a["notas"] and b["notas"]])
            L.append(f"| {llm_api.modelo_id(j)} | {sum(x['aprova'] for x in js)}/{len(js)} | {conc}/{len(pares)} | {dif:.2f} "
                     f"| {_media([x['custos']['brl'] for x in js]):.3f} | {_media([x['segundos'] for x in js]):.0f}s |")
    L += ["", "## Os roteiros (leia e dê a sua nota: o juiz não substitui o olho humano)", ""]
    for nicho, formato, tema in dados["temas"]:
        L += [f"### {tema} ({nicho} · {formato})", ""]
        for r in dados["escritores"]:
            if r["tema"] != tema:
                continue
            if r["erro"]:
                L += [f"**{r['modelo']}**: falhou ({r['erro'][:150]})", ""]
                continue
            notas = " ".join(f"{k} {v}" for k, v in r.get("notas", {}).items())
            L += [f"**{r['modelo']}** · {r['titulo']} · {'aprovado' if r['aprovado'] else 'REPROVADO'} "
                  f"em {r['tentativas']} · R$ {r['custos']['brl']:.2f} · {notas}", ""]
            L += [f"{i}. {f}" for i, f in enumerate(r["falas"], 1)] + [""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--escritores", default="haiku,sonnet,opus")
    ap.add_argument("--juiz", default="sonnet", help="juiz fixo da fase 1")
    ap.add_argument("--juizes", default="haiku,sonnet,opus", help="candidatos da fase 2 (o último é a referência)")
    ap.add_argument("--sem-juizes", action="store_true", help="pula a fase 2")
    ap.add_argument("--temas", type=int, default=len(TEMAS))
    ap.add_argument("--orcamento", type=float, default=30.0, help="R$: para de chamar a API ao atingir")
    ap.add_argument("--estimar", action="store_true")
    ap.add_argument("--relatorio", help="só regera o .md a partir de um .json já salvo")
    a = ap.parse_args()

    if a.relatorio:
        p = Path(a.relatorio)
        p.with_suffix(".md").write_text(relatorio(json.loads(p.read_text(encoding="utf-8"))), encoding="utf-8")
        print(p.with_suffix(".md"))
        return
    escritores = a.escritores.split(",")
    juizes = [] if a.sem_juizes else a.juizes.split(",")
    temas = TEMAS[:a.temas]
    usd = estimar(escritores, a.juiz, juizes, len(temas))
    print(f"Plano: {len(temas)} temas × escritores {escritores} (juiz fixo {a.juiz})"
          + (f" + fase 2 com juízes {juizes}" if juizes else "")
          + f"\nCusto estimado: US$ {usd:.2f} ≈ R$ {usd * medidor.DOLAR:.2f} (limite: R$ {a.orcamento:.2f})")
    if a.estimar:
        return
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Falta ANTHROPIC_API_KEY: crie em console.anthropic.com e coloque no .env da raiz (ANTHROPIC_API_KEY=...)")

    caminhos.LLM = "api"
    _sem_gravar_bancos()
    pasta = caminhos.PRODUCAO / "arena"
    pasta.mkdir(parents=True, exist_ok=True)
    nome = datetime.now().strftime("%Y-%m-%d_%H%M")
    dados = {"data": nome, "juiz": a.juiz, "juiz_referencia": juizes[-1] if juizes else None, "temas": temas,
             "escritores_pedidos": escritores, "juizes_pedidos": juizes, "escritores": [], "juizes": []}
    salvar = lambda: _salvar(pasta, nome, dados)  # noqa: E731
    fase_escritores(escritores, a.juiz, temas, a.orcamento, dados, salvar)
    if juizes:
        fase_juizes(juizes, dados, salvar, a.orcamento)
    (pasta / f"{nome}.md").write_text(relatorio(dados), encoding="utf-8")
    print(f"\nRelatório: {pasta / (nome + '.md')}")


if __name__ == "__main__":
    main()
