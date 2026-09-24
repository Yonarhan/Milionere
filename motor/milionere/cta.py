"""Fechamento (CTA) com rodízio. O YouTube recusa monetização de canal com cara de "produzido em massa / com modelo"
(política de conteúdo não original, jul/2025): a mesma frase no fim de todo vídeo pesa contra na revisão humana.
A regra do gospel continua (amém + inscrição, conferida em validar.checar_cta_gospel); o que muda é a frase.
Cada prompt recebe 2 exemplos sorteados e a ordem de adaptar ao tema, nunca copiar.
"""

import random

GOSPEL = [
    "Escreve amém. E se inscreve pra continuar sendo abençoado.",
    "Se isso falou com você, deixa um amém. E se inscreve pra não perder a próxima.",
    "Amém? Escreve aí. E se inscreve pra receber mais palavra assim.",
    "Deixa seu amém por quem precisa ouvir isso hoje. E se inscreve no canal.",
    "Se você crê, escreve amém. Inscreve-se pra caminhar com a gente.",
    "Comenta amém se Deus já fez isso na sua vida. E se inscreve pra ouvir a próxima história.",
    "Escreve amém e marca quem precisa ouvir isso. Se inscreve pra mais histórias da Bíblia.",
    "Um amém pra quem tá esperando a virada. E se inscreve pra continuar com a gente.",
]
GOSPEL_PARTE = [
    "Escreve amém. E se inscreve pra ver a parte {prox}.",
    "Deixa seu amém. A parte {prox} já tá no canal: se inscreve pra não perder.",
    "Amém? Então se inscreve, que a parte {prox} conta o que aconteceu depois.",
    "Comenta amém e se inscreve. Na parte {prox} a história vira.",
]
OUTROS = [
    "Comenta o que você faria.",
    "Manda pra alguém que precisa saber disso.",
    "Salva pra mostrar pra alguém depois.",
    "Segue pra mais coisas assim.",
    "Qual dessas você não sabia? Comenta.",
    "Compartilha com quem vai duvidar disso.",
]
OUTROS_PARTE = ["Segue pra ver a parte {prox}.", "A parte {prox} responde isso. Segue pra não perder."]


def exemplos(nicho: str, prox: int | None = None, n: int = 2) -> list[str]:
    """prox = número da próxima parte numa série (None = vídeo único ou parte final)."""
    gospel = nicho == "gospel"
    lista = (GOSPEL_PARTE if gospel else OUTROS_PARTE) if prox else (GOSPEL if gospel else OUTROS)
    return [e.format(prox=prox) for e in random.sample(lista, min(n, len(lista)))]


def bloco(nicho: str, prox: int | None = None) -> str:
    ex = " | ".join(f"'{e}'" for e in exemplos(nicho, prox))
    if nicho == "gospel":
        regra = ("As 2 últimas cenas pedem o amém E a inscrição" + (f", chamando pra parte {prox}" if prox else "") + ". ")
    else:
        regra = "A última cena é um CTA curto" + (f" que chama pra parte {prox}" if prox else "") + ". "
    return (f"# Fechamento\n{regra}Exemplos de tom (NÃO copie: escreva uma frase nova, ligada ao tema deste vídeo, "
            f"porque vídeos com o mesmo fechamento parecem feitos em série): {ex}")
