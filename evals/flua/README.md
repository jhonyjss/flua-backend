# Avaliação da Flua

Avaliação de regressão do prompt de voz (etapa 2a, `docs/flua-tutor/02-medir-e-enxugar.md` no
repo `flueai`). Nenhuma mudança de prompt entra sem rodar aqui contra o baseline.

## Como rodar

Precisa de `OPENAI_API_KEY` no ambiente ou no `.env` do backend (e de `ANTHROPIC_API_KEY` se o
juiz for Claude), e dos mesmos modelos de voz da produção (`OPENAI_REALTIME_MODEL`,
`OPENAI_REALTIME_MODEL_ADVANCED`; sem eles valem os padrões de `app/core/config.py`). Roda à
mão, fora do CI: custa e varia entre rodadas.

```bash
python -m evals.flua run                      # todos os casos, 3 rodadas, compara com o baseline
python -m evals.flua run --mode lesson        # só um modo
python -m evals.flua run --case aula-sim      # só um caso (repetível)
python -m evals.flua run --save-baseline      # grava como baseline.json (só com todos os casos)
python -m evals.flua audit                    # contradições e regras sem efeito em cada modo
```

O resultado vai para `results/` (fora do git). Com `baseline.json` presente, `run` sai com erro
se houver regressão. Rodada perdida por erro da API ou do juiz (crédito, limite, conexão caída)
não conta como falha da Flua, mas impede gravar o baseline e comparar com ele: rode de novo.
Antes de gastar com a voz, `run` confere se o juiz responde.

## Como funciona

- Cada caso monta a sessão com `session_config` (a mesma da produção) e conversa em texto pela
  Realtime API. O aluno "digita": em texto não dá para testar sotaque, ruído nem detecção de turno.
- A Flua também responde em texto, não em voz. Na produção, só a avaliação é em texto; as
  outras falas são áudio. O tamanho medido aqui pode diferir do falado. Medir em áudio custaria
  bem mais por rodada; ficou em texto por decisão de custo (2026-11-04).
- Os textos do cliente (pedido de avaliação, resposta da ferramenta, avisos) são cópias dos
  clientes, que são os donos deles: `lessonGoalMachine.ts` e `LessonExperience.vue` no `flueai`,
  `guided-lesson-machine.ts` no `flueai-app`. Mudou lá, atualize em `cases.py`.
- Checagens objetivas em código (`checks.py`): ferramenta e `resultado`, frases, palavras,
  rótulos internos, placeholder, espanhol na aula de inglês (repetir a fala do aluno não conta).
  "parcial", "errado" e "Correct!" só são proibidos nas aulas com ferramenta. Uma interjeição de
  uma palavra ("Isso!") não conta como frase.
- O resto é julgado por `gpt-5.5` (`judge.py`; `FLUA_EVAL_JUDGE_MODEL` troca, inclusive por um
  Claude, que seria melhor por ser de outra família; vale também no `.env`). O juiz recebe a
  conversa com as instruções do app entre colchetes e cita o trecho da fala.
- Cada rodada termina com os tokens gastos por modelo.
- Regra para aceitar um prompt novo: nenhuma categoria passa menos rodadas que o baseline e
  nenhum caso que passava todas cai abaixo de 2/3 delas. As rodadas variam de um dia para o outro
  (a abertura foi de 5/15 a 2/15 sem mudar o prompt): rode o prompt antigo e o novo na mesma
  sessão, com `--runs 5`, e compare com `--against <resultado do antigo>`. O `baseline.json` é o
  prompt atual (desde a 2c, 5 rodadas).
- Os casos de abertura descrevem o alvo da etapa 2d (D1 = B). O baseline falha em parte deles de
  propósito.

## Tempo e ritmo da voz (`voice_timing.py`)

O eval em texto não vê a detecção de turno nem a fala. `python -m evals.flua.voice_timing` toca áudio
de verdade pela Realtime com a `session_config` da aula guiada: a fala do aluno sai do `say` do macOS
(voz pt-BR falando inglês), vai em tempo real, e o script faz os passos do app (`use-flua-voice.ts`):
transcrição → `registrar_resultado` forçado → resposta da ferramenta → a Flua fala. Mede, a partir do
fim da fala do aluno: fechamento do turno (VAD), transcrição, avaliação, primeiro áudio e o silêncio
total; e a fala dela em segundos, palavras e palavras por segundo.

- Falas avaliadas (`--only judged`): 3 turnos da aula, com a resposta da ferramenta copiada do app.
- Fechamento do turno (`--only vad`): 20 respostas curtas (duas vozes) e 5 frases com pausa de
  800–1100 ms no meio. Mais de um commit numa frase com pausa = o turno foi cortado.
- As configurações vêm do ambiente, como na produção (`OPENAI_REALTIME_LESSON_VAD_EAGERNESS`,
  `OPENAI_REALTIME_GUIDED_VOICE_SPEED`). Para comparar, rode as duas no mesmo horário: a latência
  da API varia ao longo do dia.
- Só macOS (precisa do `say`). Custa pouco: modelo mini e áudios curtos. Os áudios ficam em
  `results/voice-clips/`.

