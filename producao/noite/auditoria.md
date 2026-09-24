# Turno da noite — notas de auditoria por rodada

## Antes da noite (base)
- Elias (Flux, 23/09 20:00): 46,9 min, 55% 1ª passada, 36 imagens/11 cenas.
- José (Z-Image, 21:08): 50,1 min; roteiro 15,8 min (claude -p lento + tema sem Gn 42); juiz reprovando pelas regras de escrita; bug "ninguém"; cenário com Egito.
- Correções antes da rodada 1: juiz só reprova por defeito/combina; "sem personagem" aceita anônimo; cenario_en só época/paisagem; tema José com Gn 42; medidor ligado.

## Rodada 01 — Ana (Z-Image) 22:48–23:15
- 27,4 min | 91% 1ª passada | 12 imagens/11 cenas | roteiro 11,3 min (2 tentativas; claude -p ~3-4 min por chamada) | imagens 12,8 min (~62 s/img GPU).
- Revisão visual: Ana e Eli consistentes, sem defeito. CTA final genérica (homem com pergaminho). APROVADO para postar.
- Bug achado: medidor não via chamadas do juiz em threads (contava 6). Corrigido (contextvars.copy_context) antes da rodada 02. Custo da rodada 01 (US$ 0,80) está subestimado.
- Gargalo agora: roteiro (41% do tempo), todo em espera do claude -p.

## Rodada 02 — cego Bartimeu (Flux) 23:16–23:22 — FALHOU
- Limite de uso da assinatura do Claude (429 "session limit", renovou 00:20) no juiz do roteiro, tentativa 2. Nenhum vídeo.
- O limite é compartilhado com a sessão do Claude Code que conduz a noite.
- Correção: rodada.sh espera 30 min e tenta de novo ao bater no limite; comfy.log só entra na métrica se for da rodada.

## Rodada 03 — cego Bartimeu (Flux) 01:18–01:37 — DESISTIU no roteiro
- 4 tentativas, 19,2 min, US$ 1,37, 8 chamadas, 0 imagens.
- Causa: o juiz reprova como "ordem" (critério rígido) o gancho que antecipa o clímax, que é justamente o que o formato pede (o próprio título do tema é esse gancho). A Ana teve a mesma reprovação na tentativa 1.
- Correção: critério "ordem" vale da cena 2 em diante; a cena 1 (gancho) pode antecipar qualquer momento.

## Rodada 04 — mulher do fluxo de sangue (Flux) 01:38–02:21
- 43,2 min | 30% 1ª passada (7 de 10 reprovadas) | 25 imagens/13 cenas | 34 chamadas | US$ 1,96 | GPU 21 min (50 s/img).
- Roteiro 11,8 min (3 tentativas; a correção de "ordem" funcionou: nenhuma reprovação por gancho).
- Banco reusou 3 imagens de OUTRA história (Jesus andando sobre as águas) com nota 0,58–0,70: busca só pela fala. Juiz pegou as 3. Correção: busca usa fala + prompt visual, limiar 0,70.
- Flux põe infraestrutura moderna no fundo de vilas (poste, antena, fio, caixa elétrica): 5 das reprovações.
- Revisão visual: cinematográfico, sem defeito. APROVADO. Ressalvas: "na multidão" com 2 pessoas (regra "máx. 2 figuras" conflita com cenas de multidão); CTA genérica (homem escrevendo) repetida.
- Decisão: restante da noite só com Z-Image (Ana: 91% 1ª passada) para garantir vídeos postáveis.

## Rodada 05 — Jesus dormindo na tempestade (Z-Image) 02:22–03:01
- 39,2 min | 45% 1ª passada | 23 imagens/12 cenas (1 do banco: CTA) | 31 chamadas | US$ 1,89 | GPU 15,9 min (41 s/img).
- Roteiro 13,9 min (3 tentativas) = 35% do tempo, GPU parada nesse período.
- Reprovações: pés em primeiro plano em cena de barco (3), objeto moderno no barco/areia (4), imagem que contradiz a fala (3: mar calmo na tempestade, Jesus acordado quando dormia).
- Mudança: ESTEIRA. pipeline --so-roteiro escreve o roteiro da rodada N+1 enquanto a GPU faz o vídeo N; a rodada seguinte entra direto em imagens (--retomar). Regras novas de multidão (só ao fundo) e CTA (momento forte da história, não pessoa escrevendo) valem da rodada 06.

## Rodada 06 — Agar e Ismael no deserto (Z-Image) 03:03–03:29
- 26,0 min | 82% 1ª passada | 14 imagens/11 cenas | 19 chamadas | US$ 1,20 | GPU 10,5 min (45 s/img).
- Reprovações: cantil metálico (2), chinelo de borracha (2). Guia visual passa a citar "odre de couro".
- Esteira: roteiro da rodada 07 (Bartimeu) escrito em paralelo, 16,4 min, US$ 1,15. Passou com ordem 5: a correção do gancho funcionou (o mesmo tema desistiu na rodada 03).
- Revisão visual Agar: APROVADO. Mãe e menino consistentes; anjo com a ficha nova (jovem, loiro, asas) já não parece Jesus. Ressalva: garrafa escura com cara de vidro perto do menino (cena 3).
- Revisão visual Tempestade (rodada 05): APROVADO. Jesus consistente. Ressalvas: pés grandes em primeiro plano na cena 1; "a água enchia tudo" mostra barco na areia.

## Rodada 07 — Bartimeu — PERDIDA por limite de uso (03:29–06:02)
- Limite da assinatura do Claude às 03:48 ("resets 6:10am"). As 4 esperas de 30 min terminaram antes do reset: ~2h30 sem produção.
- O limite é compartilhado com a sessão que conduz a noite, e a esteira faz 2 processos chamarem o Claude ao mesmo tempo, o que antecipa o limite.
- Correções: esteira não refaz roteiro já na fila; métricas não quebram sem log; SEM_PROXIMO=1 desliga o roteiro paralelo nas últimas rodadas.
- Rodada 07 retomada às 06:17 (limite renovou 06:10): 11,8 min (imagens iniciais já feitas às 03:29), 5 reprovadas, 7 refações, US$ 0,61 nesta parte (+ roteiro US$ 1,15).
- Banco trouxe 3 cenas da tempestade (Jesus dormindo no barco) para o Bartimeu com nota 0,73–0,78, mesmo com o limiar novo. A busca por significado (MiniLM) não separa histórias com o mesmo personagem. Correção: só cenas SEM personagem (paisagem, objeto, chamada) se reusam do banco.
- Revisão visual Bartimeu: APROVADO. Bartimeu e Jesus consistentes; sem a venda depois da cura. Cegueira mostrada com faixa sobre os olhos.

## Rodada 08 — Zaqueu (Z-Image, roteiro da esteira) 06:30–06:54
- 23,7 min | 54% 1ª passada (6 de 13) | 21 imagens/14 cenas | US$ 2,11 (roteiro 1,29 + vídeo 0,82) | GPU 16,2 min (46 s/img). Roteiro em paralelo: 17,8 min, fora do tempo da rodada.
- Reprovações: iluminação moderna (poste, arandela, luminária) 4; imagem que não acompanha a fala 3; mocassim 1.
- Banco: cena de multidão sem personagem recebeu imagem COM Jesus e Bartimeu (nota 0,84). Correção: a imagem do banco também precisa ser sem personagem.
- Revisão visual Zaqueu: Zaqueu consistente (careca, túnica azul). ERRO na cena 6 ("hoje fico na sua casa"): Jesus sentado na árvore e Zaqueu embaixo, papéis invertidos; o juiz aprovou. Refazer só a cena 6 depois da rodada 09.

## Rodada 09 — ladrão na cruz (Z-Image) 06:54–07:09 — DESISTIU no roteiro
- 4 tentativas, 14,8 min, US$ 1,10. Juiz do roteiro (Haiku) tratou omissão como erro factual ("omite 'a ti mesmo'") apesar da instrução contrária; 12 e 16 problemas em tentativas seguidas. 2 desistências em 9 rodadas, as duas no juiz do roteiro.

## Conserto da cena 6 do Zaqueu 07:10–07:28 (fora das rodadas)
- 3 retomadas (9,7 + 4,5 + 3,0 min). O juiz aprovou 2 vezes a cena com papéis invertidos (Jesus na árvore) e 1 vez com Zaqueu duplicado ao fundo.
- Causa: as fichas entram no prompt na ordem de `personagens` (jesus, zaqueu) e o modelo associa a 1ª ficha à 1ª figura descrita (a da árvore). Invertendo para (zaqueu, jesus) saiu certo de primeira.
- Correção: roteirista lista `personagens` na mesma ordem em que o prompt descreve as figuras.
