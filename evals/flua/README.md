# Avaliação da Flua

Avaliação de regressão do prompt de voz (etapa 2a, `docs/flua-tutor/02-medir-e-enxugar.md` no
repo `flueai`). Nenhuma mudança de prompt entra sem rodar aqui contra o baseline.

## Como rodar

Precisa de `OPENAI_API_KEY` e `ANTHROPIC_API_KEY` no ambiente ou no `.env` do backend, e dos
mesmos modelos de voz da produção (`OPENAI_REALTIME_MODEL`, `OPENAI_REALTIME_MODEL_ADVANCED`; sem
eles valem os padrões de `app/core/config.py`). Roda à mão, fora do CI: custa e varia entre
rodadas.

```bash
python -m evals.flua run                      # todos os casos, 3 rodadas, compara com o baseline
python -m evals.flua run --mode lesson        # só um modo
python -m evals.flua run --case aula-sim      # só um caso (repetível)
python -m evals.flua run --save-baseline      # grava o resultado como baseline.json
python -m evals.flua audit                    # contradições e regras sem efeito em cada modo
```

O resultado vai para `results/` (fora do git). Com `baseline.json` presente, `run` sai com erro
se houver regressão.

## Como funciona

- Cada caso monta a sessão com `session_config` (a mesma da produção) e conversa em texto pela
  Realtime API. O aluno "digita": em texto não dá para testar sotaque, ruído nem detecção de turno.
- Os textos do cliente (pedido de avaliação, resposta da ferramenta, avisos) são cópias dos
  clientes, que são os donos deles: `lessonGoalMachine.ts` e `LessonExperience.vue` no `flueai`,
  `guided-lesson-machine.ts` no `flueai-app`. Mudou lá, atualize em `cases.py`.
- Checagens objetivas em código (`checks.py`): ferramenta e `resultado`, frases, palavras,
  rótulos internos, placeholder, espanhol na aula de inglês. Uma interjeição de uma palavra
  ("Isso!") não conta como frase.
- O resto é julgado por Claude (`judge.py`, `FLUA_EVAL_JUDGE_MODEL`), que cita o trecho da fala.
- Cada caso roda 3 vezes. Regra para aceitar um prompt novo: nenhuma categoria passa menos
  rodadas que o baseline e nenhum caso que passava 3 de 3 cai para menos de 2 de 3.
- Os casos de abertura descrevem o alvo da etapa 2d (D1 = B). O baseline falha em parte deles de
  propósito.
