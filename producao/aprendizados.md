# Aprendizados

Regras que vieram de feedback real. A skill `roteirista-shorts` lê este arquivo antes de cada lote.

## Geral
- 2026-09-22: primeiro vídeo (água-viva, ~45s) ficou longo demais. Alvo: 18–28s em curiosidades.
- 2026-09-22: música aleatória do MoneyPrinter saiu triste. Nunca usar `random`; usar músicas escolhidas em `MoneyPrinterTurbo/storage/bgm` com prefixo do nicho, ou sem música e adicionar som em alta no app.
- 2026-09-22: voz Antonio em 1.0x ficou "mansa demais" para curiosidade. Usar 1.15x+ ou outra voz (ver `amostras_voz/`).

- 2026-09-22: polvo (Antonio 1.15x): voz e roteiro aprovados. Legenda no centro exato não agradou → agora custom ~62–66% do topo.
- 2026-09-22: imagens não acompanhavam a fala (MoneyPrinter troca clipe em ritmo fixo). Solução: roteiro em `cenas` + montagem sincronizada.

- 2026-09-22: imagens automáticas 'não conexas' com a fala. Solução: curadoria visual por cena (Claude olha folhas de candidatos e escolhe) + fontes de arte/foto histórica/NASA.

## Curiosidades

## Astronomia
- 2026-09-22: Vênus (dia > ano) ficou "maneiro" mas o fato foi morno. Escolher fatos que passem no teste do uau (ganchos.md) e usar imagens do Gemini para o impossível.

## Gospel
- 2026-09-22: "man praying"/"hands praying" no Pexels trazem muçulmanos em mesquita. Usar "with bible"/"christian" na busca (+ filtro `evitar_termos` no preset).
- 2026-09-22: "friends hugging" traz gente rindo. Para dor/consolo: "comforting sad friend", "consoling crying woman".
- 2026-09-22: 90 palavras a 1.0x = 48s (longo). Mirar ~65 palavras ou voz 1.1x.
- 2026-09-22: para histórias bíblicas, pinturas clássicas (Rembrandt, Rubens, Van Gogh) e fotos históricas do lugar (Túmulo de Lázaro, Betânia) ilustram muito melhor que vídeo de banco.
- 2026-09-22: imagens geradas no app do Gemini (1 prompt por mensagem, mesmo Jesus) = melhor resultado até agora para cenas bíblicas. Banco de imagens não tem os momentos exatos da história.
