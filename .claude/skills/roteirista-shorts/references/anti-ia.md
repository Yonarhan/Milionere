# Passe anti-IA para roteiro falado (pt-BR)

Adaptado da skill `humanizer` do Hermes Agent (MIT, Siqi Chen / blader), que por sua vez
segue o guia "Signs of AI writing" da Wikipédia. Aqui o alvo é texto que vai ser **falado por
TTS em 20–40 segundos**, então os problemas mudam um pouco: o ouvido pega repetição e
formalidade muito mais rápido que o olho.

## Remova

| Padrão | Exemplo ruim | Troque por |
|---|---|---|
| Vocabulário de IA | "fascinante", "incrível jornada", "desvendar", "crucial", "notável", "intrigante", "vasto universo", "mistérios do cosmos" | palavra comum: "estranho", "bizarro", "doido", "enorme" |
| Exagero de importância | "um marco na história da ciência" | diga o fato e pronto |
| "Não apenas X, mas Y" / "Não é só X, é Y" | "Não é apenas uma água-viva, é um milagre" | uma afirmação só |
| Regra de três forçada | "rápido, eficiente e surpreendente" | um adjetivo que importa |
| Sinônimos rodando | "a água-viva… o animal… a criatura… o ser" | repita "ela" |
| Pergunta retórica + resposta | "E sabe o que é mais incrível? É que…" | vá direto pro fato |
| Conclusão genérica | "Realmente a natureza é surpreendente." | final com virada, piada ou pergunta |
| Especialista vago | "Cientistas acreditam que…" | "Um estudo de 1996 mostrou…" ou tire |
| Travessão (—) e ponto e vírgula | o TTS lê mal e fica robótico | ponto final, vírgula |
| Frases do mesmo tamanho | 5 frases de 12 palavras | varie: 3 palavras. Depois 15. Depois 6. |
| Norma culta de livro | "Deve-se considerar que", "a qual", "cujo" | "pensa comigo", "que" |

## Coloque

- **Fala de gente:** "pra", "tá", "cê" (com moderação), "sério", "olha só", "pensa comigo".
- **Reação, não só relato:** "Isso é meio assustador." / "E ninguém sabe explicar."
- **Ritmo de narrador de Shorts:** frases curtas, mas LIGADAS, como alguém contando uma história de uma vez. Cada fala continua a anterior com conectivo ("então", "aí", "mas", "na hora", "e"). Cada ponto final vira uma pausa de quase 1s no TTS: ponto só onde a ideia fecha; dentro da mesma ação, use "e" ou vírgula ("Pedro saiu do barco e andou na água.", não "Desceu do barco. Andou na água.").
- **Nada de fragmento telegráfico** sem sujeito ou verbo ("Teve medo.", "Primeiro segurou.") fora do gancho. Se não cabe tudo ligado, conte MENOS fatos, não corte os conectivos.
- **Números por extenso quando curtos** ("três"), algarismos quando grandes ("2 trilhões"). Evite siglas.
- **Um "você" por vídeo pelo menos.** Coloca o espectador dentro.

## Teste final (obrigatório)

Leia o roteiro em voz alta mentalmente e responda em 1 linha: *"o que ainda soa como IA ou como
livro?"*. Corrija isso. Depois confira se não sobrou nenhum termo da coluna "Remova".
