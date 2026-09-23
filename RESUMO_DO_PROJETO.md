# Projeto: renda extra com vídeos curtos (Shorts e TikTok) sem aparecer

*Resumo de 23/09/2026*

## 1. A ideia

Criar canais de vídeos curtos (30 a 40 segundos) no **YouTube Shorts** e no **TikTok**, sem mostrar o rosto, e produzir com um sistema quase automático. Queremos postar com frequência e ter custo perto de zero.

A meta é crescer os canais até entrar na monetização das plataformas. Depois disso, dá para pensar em outras fontes de renda, como afiliados ou vender produção de vídeos para terceiros.

## 2. Canais e nichos

| Canal | Conteúdo | Situação |
|---|---|---|
| **Gospel** | Histórias bíblicas contadas como uma virada, com emoção e versículo exato | ✅ **Fórmula validada.** O 1º vídeo teve 20 views nos primeiros 5 minutos |
| **Curiosidades de astronomia** | Fatos que fazem a pessoa dizer "uau" e vídeos do tipo "E se...?" | 🟡 Vídeos prontos, começando a postar |
| Ideias para depois | Mitologia, história bizarra, animais bizarros, psicologia do dia a dia | 💭 Em discussão |

## 3. Como um vídeo é feito hoje

```
Ideia → Roteiro → Imagens → Narração + legenda → Montagem → Postagem
```

1. **Ideia:** escolhida por nós ou garimpada nos Shorts mais vistos de canais grandes em inglês (Zack D. Films, Kurzgesagt, Veritasium). Aproveitamos **só o fato**. Roteiro e imagens são nossos.
2. **Roteiro:** escrito com a ajuda de uma IA (Claude), seguindo regras que aprendemos:
   - gancho forte nos primeiros 2 segundos;
   - frases curtas e linguagem de conversa, sem "cara de IA";
   - o fato central é checado. O resto pode ser dramatizado, em tom de hipótese;
   - o roteiro já sai dividido em **cenas**, com uma imagem para cada frase.
3. **Imagens:** cada cena vem da fonte que melhor ilustra aquela frase:
   - **IA (Gemini):** cenas impossíveis de filmar, como Jesus chorando no túmulo ou um planeta onde chove vidro. Usamos personagens fixos para o mesmo Jesus aparecer em todos os vídeos;
   - **NASA:** imagens e vídeos reais do espaço, em domínio público;
   - **Pexels e Pixabay:** vídeos de banco gratuitos para cenas comuns, como pôr do sol, ampulheta ou uma Bíblia aberta;
   - **Pinturas clássicas:** Wikimedia e Metropolitan Museum, em domínio público.
4. **Narração e legenda:** voz sintética em português, grátis. A legenda sai sincronizada e cada imagem entra **no segundo exato** em que a frase é falada.
5. **Montagem:** automática. Leva menos de 1 minuto por vídeo e usa a placa de vídeo do PC.
6. **Postagem:** manual. Cada vídeo sai com um arquivo de texto com título, descrição, hashtags, comentário para fixar e créditos. No TikTok, postamos **sem música** e escolhemos um áudio do próprio TikTok, o que ajuda no alcance.

## 4. Ferramentas

| Ferramenta | Para que serve | Custo |
|---|---|---|
| **MoneyPrinterTurbo** (open source) | Narração, legenda e base da produção | Grátis |
| **Claude Code** (IA) | Roteiros, escolha das imagens e automação de tudo | Assinatura que já temos |
| **Gemini** (app) | Geração das imagens de IA | Grátis, mas manual |
| Pexels, Pixabay, NASA, Wikimedia | Imagens e vídeos | Grátis |
| Músicas de Kevin MacLeod | Trilha para o YouTube (exige crédito na descrição) | Grátis |

**Custo por vídeo hoje: praticamente zero.**

## 5. Vídeos produzidos

| Vídeo | Nicho | Status |
|---|---|---|
| "Por que Jesus chorou se já sabia o final?" (Lázaro) | Gospel | ✅ Postado. Boa reação inicial |
| "Ele negou Jesus 3 vezes" (Pedro) | Gospel | Pronto |
| "Se você tá com medo hoje, escuta isso" (Isaías 41:10) | Gospel | Pronto, com imagens de banco |
| "O planeta onde chove vidro de lado" | Astronomia | Pronto |
| "E se a Lua sumisse hoje à noite?" | Astronomia ("E se") | Pronto |
| "Em Vênus um dia dura mais que um ano" | Astronomia | Pronto, mas o fato ficou morno |
| A enguia que escapa do estômago do predador | Animais | Roteiro pronto, faltam imagens |

## 6. O que aprendemos

- **Vídeo longo perde audiência.** O ideal fica entre 25 e 35 segundos.
- **As imagens precisam mostrar o que está sendo dito.** Vídeo de banco genérico não funciona. Isso exigiu dois ajustes: sincronizar cada imagem com a sua frase e escolher as imagens a dedo.
- **Para histórias bíblicas, imagens geradas por IA** com personagens consistentes funcionam muito melhor que banco de imagens.
- **O fato precisa passar no "teste do uau":** a pessoa contaria isso para um amigo? "Chove vidro de lado" passa. "Um dia em Vênus é maior que um ano" é curioso, mas morno.
- **Música triste** mata o vídeo de curiosidade. Para gospel, piano emocional funciona.
- **Voz lenta** fica "mansa demais" em curiosidades. Em 1.15x fica melhor.
- **Legenda no centro exato** incomoda. Um pouco abaixo do meio fica melhor.
- **Não dá para baixar e repostar vídeos de outros canais.** Isso gera strike de direitos autorais e impede a monetização.

## 7. Limitações e decisões em aberto

1. **A geração de imagens ainda é manual.** A automação já está pronta, mas a API do Gemini exige ativar o faturamento. O custo estimado é de centavos de dólar por imagem, o que dá menos de US$ 1 por vídeo. **Vale ativar?**
2. **Nome do canal de ciência:** o canal atual tem cara de astronomia. Mantemos o foco ou escolhemos um nome mais amplo, como "Fatos do Universo" ou "Mente Curiosa"?
3. **Quantos canais manter:** a recomendação é **2 canais ativos** (gospel e astronomia) até ter ritmo de postagem. Um 3º canal, de mitologia, viria depois.
4. **Frequência:** a meta é de 3 a 5 vídeos por semana por canal. **Quem posta e quando?**
5. **Transparência:** marcamos sempre "conteúdo gerado por IA" nas plataformas, porque a voz e as imagens são sintéticas.

## 8. Próximos passos

- [ ] Postar os vídeos prontos e acompanhar views e retenção por 48 horas
- [ ] Decidir sobre o faturamento da API de imagens, para automatizar 100%
- [ ] Definir o nome final do canal de ciência
- [ ] Montar uma fila de temas: José do Egito, Jonas, estrela de nêutrons, buraco negro, "E se o Sol apagasse?"
- [ ] Anotar os resultados de cada vídeo, para o sistema aprender o que funciona

## 9. Perguntas para discutir

- Qual nicho tem mais potencial de monetização para nós?
- Vale investir alguns reais por mês para automatizar as imagens?
- Faz sentido oferecer esse tipo de produção como serviço para igrejas, pequenos negócios ou criadores?
- Alguém do grupo quer cuidar da postagem e do engajamento (responder comentários, escolher os áudios do TikTok)?
