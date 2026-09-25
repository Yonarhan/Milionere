# Canal de animações (Bob e o Amigo)

Shorts de ~45–60 s em desenho doodle, sobre qualquer tema, sempre com o mesmo elenco. As imagens são geradas pelo
Z-Image e 3 cenas são animadas pelo Wan 2.2, no ComfyUI do pod da RunPod. Roteiro, voz, legenda e montagem rodam no
PC, como nos outros canais.

Exemplos aprovados: `producao/roteiros/2026-09-25_propria-voz.json` (o piloto de referência) e
`2026-09-25_ultimo-minuto-da-vida-v2.json`.

## A fórmula do roteiro ("narrado")

1. **A narração vem inteira primeiro**, corrida, como alguém contando uma história para um amigo: 110 a 150 palavras.
   - As frases se ligam: "só que", "e aí", "o mais estranho é", "ou seja", "tipo".
   - Fala com quem assiste ("você") e faz perguntas no meio.
2. **O arco:**
   - uma situação que prende ("Você grava um áudio, aperta o play...");
   - a quebra de expectativa ("Pronto, acabou... certo? Não exatamente.");
   - o fato;
   - "e aí vem a parte estranha";
   - um **detalhe concreto e visual** ("o gato branco que dormia na escada da casa da sua avó");
   - a virada, que faz pensar;
   - uma pergunta para os comentários.
3. **Só depois a divisão em cenas**, uma por imagem: 10 a 18 cenas, trocando a cada 2 a 4 s. A troca pode cair no
   meio da frase. Juntando as falas, tem que sair exatamente a narração.

## A fórmula da imagem ("cena ilustrada")

A imagem **encena o momento da fala**; não basta desenhar o assunto. Cada descrição (`imagem`, em inglês) leva:

| Peça | Exemplo (piloto "própria voz") |
|---|---|
| Quem aparece, com **emoção e pose** | Bob recoiling in horror |
| A ideia virando **objeto ou ícone** | a phone playing audio, a speaker with sound waves |
| **Piada curta escrita**, de 1 a 3 palavras, quando ajudar | EU??, NORMAL, ENVIAR? |
| O **outro personagem reagindo** (em parte das cenas) | his friend looking awkward |
| **Ambientação** quando a cena pedir, com `setting: ...` no fim | setting: night sky over green grass; sem isso, parede branca e chão bege |

Não pode: números pequenos, texto longo, caveira ou qualquer coisa assustadora. O Z-Image erra texto miúdo.

## O elenco

Fica em `motor/milionere/dados/presets.json` → `animacoes.elenco`. A ficha entra sozinha no prompt de toda cena
em que o nome aparece.

- **Bob** (`Bob`): protagonista; stick figure, cabeça redonda **branca**, corpo de linha preta.
- **O Amigo** (`his friend`): coadjuvante que reage; mesmo corpo, cabeça redonda **azul**.
- **Cenário padrão** (`cenario_en`): parede branca e chão bege, separados por uma linha preta.

Estilo: `doodle_cena` em `motor/milionere/dados/estilos.json`, com traço de caneta preto meio tremido, cores
chapadas, sem sombra e o jeito de vídeo explicativo em quadro branco.

## Como gerar

1. **Pod:** RunPod com o template "ComfyUI - CUDA 12.8". Num pod novo, rode `bash motor/milionere/instalar_pod.sh`,
   que baixa o Wan 2.2 fp8, o Z-Image Q6 e o nó GGUF (~47 GB).
2. **`.env` do PC:** `MILIONERE_COMFY_URL=https://<id-do-pod>-8188.proxy.runpod.net`.
   - Com essa linha, **todo** ComfyUI do motor vai para o pod, inclusive as imagens e a animação do gospel.
   - Sem ela, volta a usar o ComfyUI local.
3. **Atualizar o código e o banco:** `git pull` e depois `python manage.py migrate` (migrations 0011 e 0012).
   Reinicie o site e o produtor.
4. **Gerar:** em `http://127.0.0.1:8000/canal` (o Estúdio de Animações), clique em **Gerar um agora**. O painel
   completo, com o gospel, fica em `/canal?todos=1`.

Tempo medido na A4500 de 20 GB: ~28 s por imagem e 1 a 5 min por cena animada. Um Short com 15 imagens e 3
animações leva ~15 min.

## O que ainda falta

- O Claude escolher entre 2 opções por cena (hoje, a imagem errada é refeita à mão, com `--so N` no script do piloto).
- Um LoRA do estilo, treinado com ~30 imagens nossas aprovadas.
- O formato longo, de ~8 min.
