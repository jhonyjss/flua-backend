"""The regression cases (docs/flua-tutor/02-medir-e-enxugar.md in flueai, 2a).

A case is a session request plus what the client does, in order:
- ("flua", text) / ("aluno", text) / ("call", name, args) in `history`: the class so far.
- steps: {"open"} Flua speaks first · {"say"} a learner turn, no reply · {"evaluate", "tool"} the client asks
  for the evaluation, forcing the tool · {"tool_output"} the client's answer to her last call · {"respond"} a
  plain reply · {"instruct"} a system direction (time warning, silence nudge, resume).
- A step's `expect` holds `tool` checks (on the call) or `reply` checks (on the text, objective) and
  `rubric` criteria (judged by Claude).

The client strings (evaluation contexts, tool outputs, instructions) are copied from the clients, which own
them: flueai `app/utils/lessonGoalMachine.ts` and `LessonExperience.vue` (site), flueai-app
`src/services/flua/guided-lesson-machine.ts` (app). Opening cases describe the 2d target (D1 = B): the
prompt before 2d is expected to fail some of them.
"""

NAME = "Ana"

# What the site's lesson page sends as lessonContext (classroom/[lessonId].vue, realtimeContext).
LESSON_CONTEXT = (
    'Tema da aula: Verbo to be. Gramática: I am, you are, he/she is — o verbo to be no presente. '
    'Vocabulário de apoio: name, teacher, student, happy, tired, friend, from, Brazil. '
    'Frases de apoio para praticar: "I am Ana" (Eu sou a Ana); "She is a teacher" (Ela é professora); '
    '"Are you tired?" (Você está cansado?). \nMetas desta aula (conduza UMA por vez, na ordem):\n'
    '1. Dizer quem você é\n2. Falar de outra pessoa\n3. Fazer uma pergunta com to be'
)
GOALS = ["Dizer quem você é", "Falar de outra pessoa", "Fazer uma pergunta com to be"]

# The app's guided lesson plan (flueai-app guided-plan.ts shape).
PLAN = {
    "title": "Apresentações",
    "skill": "se apresentar",
    "items": [
        {"id": "c-i-am", "english": "I am Ana.", "portuguese": "Eu sou Ana.", "note": "I sempre vem com am."},
        {
            "id": "c-my-name-is", "english": "My name is Ana.", "portuguese": "Meu nome é Ana.",
            "note": "My name sempre vem com is.", "cue": "Diga o seu nome para a Flua.",
            "accepts": ["My name is <nome>.", "I am <nome>."],
        },
        {"id": "c-nice", "english": "Nice to meet you.", "portuguese": "Prazer em te conhecer.",
         "note": "Diga ao conhecer alguém."},
    ],
}

# Typed answers are the only text path the clients have; the eval has no audio, so every judged turn is one.
TYPED = " O aluno digitou esta resposta: avalie o texto dela."


def lesson(**patch) -> dict:
    return {"mode": "lesson", "goalTool": True, "lessonContext": LESSON_CONTEXT, "studentName": NAME, **patch}


def guided(**patch) -> dict:
    return {"mode": "guided_lesson", "lessonId": "eval-apresentacoes", "plan": PLAN, "studentName": NAME, **patch}


def free(**patch) -> dict:
    return {"mode": "free_practice", "studentName": NAME, **patch}


# ── The site's lesson (lessonGoalMachine.ts) ─────────────────────────────────

def goal_context(n: int) -> str:
    return (f'Avalie a última fala do aluno contra a meta {n} de {len(GOALS)}: "{GOALS[n - 1]}". '
            f"Vale qualquer frase correta que cumpra a meta, com nomes e dados próprios.{TYPED}")


def teach_goal(n: int) -> str:
    return (f'ensine a meta {n}: "{GOALS[n - 1]}". Em até 2 frases, mostre o modelo com a tradução e peça '
            "para o aluno dizer. PARE e espere.")


ALL_DONE = ("Todas as metas da aula terminaram: parabenize o aluno pelo progresso em 1 frase e pergunte se ele "
            "quer continuar praticando com mais exemplos ou prefere encerrar.")
SILENCE_NUDGE = "O aluno ficou em silêncio. Repita o pedido atual de forma mais simples, em 1 frase curta."
TIME_UP = ("Resta cerca de 1 minuto de aula. Faça agora o encerramento em até 4 frases curtas: 3 aprendizados "
           "desta aula e uma despedida gentil.")

TAUGHT_1 = ("Oi, Ana! Hoje a gente vai aprender o verbo to be. Para dizer quem você é: I am Ana — eu sou a Ana. "
            "Agora você: diga quem você é em inglês.")
TAUGHT_2 = ("Agora para falar de outra pessoa: She is a teacher — ela é professora. Fale de alguém que você "
            "conhece.")
TAUGHT_3 = "Para perguntar, o verbo vem antes: Are you tired? — você está cansada? Faça uma pergunta para mim."


def judged(case_id: str, history: list, said: str, goal: int, outcomes: list[str], **tool) -> dict:
    return {
        "id": case_id, "category": "julgamento", "request": lesson(), "history": history,
        "steps": [
            {"say": said},
            {"evaluate": goal_context(goal), "tool": "registrar_meta",
             "expect": {"tool": {"name": "registrar_meta", "resultado": outcomes, **tool}}},
        ],
    }


def answered(case_id: str, history: list, output: str, *, reply: dict | None = None, rubric: list[str]) -> dict:
    return {
        "id": case_id, "category": "resposta à ferramenta", "request": lesson(), "history": history,
        "steps": [{"tool_output": output, "expect": {"reply": reply or {"max_sentences": 4}, "rubric": rubric}}],
    }


GOAL_1 = [("flua", TAUGHT_1)]
GOAL_2 = [*GOAL_1, ("aluno", "I am Ana."),
          ("call", "registrar_meta", {"meta": "1", "resultado": "correto", "o_que_ouviu": "I am Ana"}),
          ("flua", "Isso! Esse I am Ana saiu perfeito. " + TAUGHT_2)]
GOAL_3 = [*GOAL_2, ("aluno", "She is a teacher."),
          ("call", "registrar_meta", {"meta": "2", "resultado": "correto", "o_que_ouviu": "She is a teacher"}),
          ("flua", "Muito bem! " + TAUGHT_3)]

LESSON_CASES = [
    judged("aula-curta-certa", GOAL_1, "I'm Ana.", 1, ["correto"]),
    judged("aula-forma-plena", GOAL_1, "I am Ana.", 1, ["correto"]),
    # Another correct sentence that says who she is, not the model: the goal, not the phrase, is judged.
    judged("aula-outra-frase-certa", GOAL_1, "I'm a student.", 1, ["correto"]),
    judged("aula-sem-sujeito", GOAL_1, "Am Ana.", 1, ["parcial", "incorreto"], correct_has=["I"]),
    judged("aula-literal-no-que-ouviu", GOAL_1, "I Ana.", 1, ["parcial", "incorreto"], heard_lacks=["am"]),
    judged("aula-sem-artigo", GOAL_2, "She is teacher.", 2, ["parcial", "incorreto"], correct_has=["a teacher"]),
    judged("aula-pergunta-sem-inversao", GOAL_3, "You are tired?", 3, ["parcial", "incorreto"]),
    judged("aula-pergunta-certa", GOAL_3, "Is she happy?", 3, ["correto"]),
    judged("aula-sim", GOAL_1, "Sim.", 1, ["fora_do_roteiro"]),
    judged("aula-duvida-em-portugues", GOAL_1, "Como eu falo 'eu sou' mesmo?", 1, ["fora_do_roteiro"]),
    judged("aula-resposta-em-portugues", GOAL_1, "Eu sou a Ana.", 1, ["fora_do_roteiro"]),
    judged("aula-ansiedade", GOAL_1, "Ai, não consigo, sou péssima nisso.", 1, ["fora_do_roteiro"]),
    judged("aula-ruido", GOAL_1, "hmm… ãh…", 1, ["fora_do_roteiro"]),
    {**judged("aula-intermediario-certa", GOAL_1, "I'm Ana.", 1, ["correto"]), "request": lesson(level="intermediate")},

    answered(
        "aula-acerto-ensina-a-proxima", [*GOAL_1, ("aluno", "I'm Ana."),
                                         ("call", "registrar_meta", {"meta": "1", "resultado": "correto",
                                                                     "o_que_ouviu": "I'm Ana"})],
        f"correto. Elogie em 1 frase curta e específica. Agora {teach_goal(2)}",
        rubric=["Elogia algo específico da fala da aluna (o I'm Ana).",
                "Mostra um modelo em inglês para falar de outra pessoa, com a tradução.",
                "Termina pedindo que a aluna diga algo, sem outra pergunta depois do pedido."],
    ),
    answered(
        "aula-primeiro-erro-pista", [*GOAL_1, ("aluno", "Am Ana."),
                                     ("call", "registrar_meta", {"meta": "1", "resultado": "parcial",
                                                                 "o_que_ouviu": "Am Ana", "forma_correta": "I am Ana."})],
        "parcial (tentativa 1 de 2). NÃO diga a resposta: dê uma pista curta de onde está o erro "
        '(a forma certa, só para você, é "I am Ana.") e peça para ele tentar de novo.',
        reply={"max_sentences": 4, "lacks": ["I am Ana", "I'm Ana"]},
        rubric=[("Dá uma pista em inglês simples sobre onde está o erro (falta quem faz a ação, o I), sem dizer a "
                "frase certa."),
                "Pede para a aluna tentar de novo.",
                "Começa pelo que saiu bem ou de forma acolhedora, sem começar com 'não'."],
    ),
    answered(
        "aula-segundo-erro-resposta", [*GOAL_1, ("aluno", "Am Ana."), ("flua", "Quase! Falta uma palavrinha antes do am. Tenta de novo?"),
                                       ("aluno", "Am Ana."),
                                       ("call", "registrar_meta", {"meta": "1", "resultado": "parcial",
                                                                   "o_que_ouviu": "Am Ana", "forma_correta": "I am Ana."})],
        'parcial pela segunda vez. Elogie o esforço e diga a forma certa "I am Ana.", sem pedir para repetir. '
        f"Agora {teach_goal(2)}",
        reply={"max_sentences": 4, "has_any": ["I am Ana", "I'm Ana"]},
        rubric=["Diz a forma certa, I am Ana.",
                "Não pede para a aluna repetir essa frase.",
                "Passa a ensinar a meta 2 (falar de outra pessoa) com um modelo e a tradução."],
    ),
    answered(
        "aula-duvida-volta-a-meta", [*GOAL_1, ("aluno", "Como fala 'eu sou'?"),
                                     ("call", "registrar_meta", {"meta": "1", "resultado": "fora_do_roteiro",
                                                                 "o_que_ouviu": "Como fala eu sou"})],
        'fora_do_roteiro. Responda em até 2 frases e volte à meta 1 ("Dizer quem você é"): se ainda não a '
        "ensinou, ensine com o modelo e a tradução; se já ensinou, peça para ele tentar. PARE.",
        rubric=["Responde a dúvida: eu sou é I am.", "Pede para a aluna dizer quem ela é em inglês."],
    ),
    answered(
        "aula-todas-as-metas", [*GOAL_3, ("aluno", "Is she happy?"),
                                ("call", "registrar_meta", {"meta": "3", "resultado": "correto",
                                                            "o_que_ouviu": "Is she happy"})],
        f"correto. Elogie em 1 frase curta e específica. {ALL_DONE}",
        rubric=["Parabeniza a aluna pelo progresso na aula.",
                "Pergunta se ela quer continuar praticando ou prefere encerrar.",
                "Não se despede."],
    ),
    answered(
        "aula-quer-sair-antes-do-fim", [*GOAL_2, ("aluno", "Acho que já chega por hoje, tchau!"),
                                        ("call", "registrar_meta", {"meta": "2", "resultado": "fora_do_roteiro",
                                                                    "o_que_ouviu": "Acho que já chega por hoje tchau"})],
        'fora_do_roteiro. Responda em até 2 frases e volte à meta 2 ("Falar de outra pessoa"): se ainda não a '
        "ensinou, ensine com o modelo e a tradução; se já ensinou, peça para ele tentar. PARE.",
        rubric=["Não se despede: convida a aluna a continuar, porque ainda há o que praticar.",
                "Volta ao pedido de falar de outra pessoa."],
    ),
    {
        "id": "aula-aviso-de-tempo", "category": "resposta à ferramenta", "request": lesson(), "history": GOAL_3,
        "steps": [{"instruct": TIME_UP, "expect": {
            "reply": {"max_sentences": 4},
            "rubric": ["Revisa três aprendizados da aula (o que a aluna praticou ou acertou).",
                       "Se despede com gentileza."],
        }}],
    },
    {
        "id": "aula-silencio", "category": "resposta à ferramenta", "request": lesson(), "history": GOAL_2,
        "steps": [{"instruct": SILENCE_NUDGE, "expect": {
            "reply": {"max_sentences": 2},
            "rubric": ["Repete o pedido de falar de outra pessoa de um jeito mais simples.",
                       "É curta e acolhedora, sem cobrar a aluna."],
        }}],
    },
    {
        "id": "aula-retomada", "category": "resposta à ferramenta", "request": lesson(), "history": GOAL_2,
        "steps": [{"instruct": "A conexão caiu e a aula voltou. Em 1 frase, diga que vão continuar de onde "
                               f"pararam e {teach_goal(2)}", "expect": {
            "reply": {"max_sentences": 3},
            "rubric": ["Diz que vão continuar de onde pararam, sem recomeçar a aula.",
                       "Ensina a meta 2 (falar de outra pessoa) com modelo e tradução e pede para a aluna dizer."],
        }}],
    },
]

# ── The app's guided lesson (guided-lesson-machine.ts) ────────────────────────

def item_context(n: int, stage: str) -> str:
    item = PLAN["items"][n - 1]
    head = f"Avalie a última fala do aluno no item {n} ({item['id']}), etapa {stage}:"
    if stage == "repetir":
        return f'{head} ele devia repetir "{item["english"]}".{TYPED}'
    return (f'{head} o pedido foi "{item["cue"]}" (modelo: {" / ".join(item["accepts"])}); vale qualquer frase '
            f"correta que cumpra o pedido, com nomes e dados diferentes dos do exemplo.{TYPED}")


TAUGHT_ITEM_1 = "Para se apresentar, a gente diz: I am Ana — eu sou a Ana. Repete comigo: I am Ana."
TAUGHT_ITEM_3 = "Quando conhece alguém, diga: Nice to meet you — prazer em te conhecer. Repete comigo: Nice to meet you."
ALONE_ITEM_2 = "Agora é a sua vez: diga o seu nome para mim, em inglês."


def guided_judged(case_id: str, history: list, said: str, n: int, stage: str, outcomes: list[str], **tool) -> dict:
    return {
        "id": case_id, "category": "julgamento", "request": guided(), "history": history,
        "steps": [
            {"say": said},
            {"evaluate": item_context(n, stage), "tool": "registrar_resultado",
             "expect": {"tool": {"name": "registrar_resultado", "resultado": outcomes, **tool}}},
        ],
    }


GUIDED_CASES = [
    guided_judged("guiada-repetir-certa", [("flua", TAUGHT_ITEM_1)], "I am Ana.", 1, "repetir", ["correto"]),
    guided_judged("guiada-repetir-outra-palavra", [("flua", TAUGHT_ITEM_3)], "Nice to see you.", 3, "repetir",
                  ["parcial", "incorreto"], correct_has=["meet"]),
    guided_judged("guiada-sim-no-lugar-de-repetir", [("flua", TAUGHT_ITEM_1)], "Sim, vamos!", 1, "repetir",
                  ["fora_do_roteiro"]),
    guided_judged("guiada-sozinho-dados-proprios", [("flua", ALONE_ITEM_2)], "My name is Pedro.", 2, "sozinho",
                  ["correto"]),
    guided_judged("guiada-sozinho-sem-verbo", [("flua", ALONE_ITEM_2)], "My name Pedro.", 2, "sozinho",
                  ["parcial", "incorreto"], heard_lacks=["is"]),
    {
        "id": "guiada-acerto-vai-para-sua-vez", "category": "resposta à ferramenta", "request": guided(),
        "history": [("flua", TAUGHT_ITEM_1), ("aluno", "I am Ana."),
                    ("call", "registrar_resultado", {"item_id": "c-i-am", "etapa": "repetir", "resultado": "correto",
                                                     "o_que_ouviu": "I am Ana"})],
        "steps": [{"tool_output": 'correto. Elogie em 1 frase curta. Etapa sua vez do item 1: peça em português '
                                  'para ele dizer a frase "I am Ana." trocando UMA informação (outro nome, país, '
                                  'número ou objeto, você escolhe e diz qual), sem dizer a resposta. PARE e espere.',
                   "expect": {"reply": {"max_sentences": 4}, "rubric": [
                       "Pede em português para a aluna dizer a frase trocando uma informação e diz qual trocar.",
                       "Não diz a frase-resposta pronta em inglês com a troca feita."]}}],
    },
    {
        "id": "guiada-primeiro-erro-pista", "category": "resposta à ferramenta", "request": guided(),
        "history": [("flua", ALONE_ITEM_2), ("aluno", "My name Pedro."),
                    ("call", "registrar_resultado", {"item_id": "c-my-name-is", "etapa": "sozinho",
                                                     "resultado": "parcial", "o_que_ouviu": "My name Pedro",
                                                     "forma_correta": "My name is Pedro."})],
        # Copy of flueai-app guided-lesson-machine.ts after stage 04 (flueai-app#22): the hint is no longer forced
        # into Portuguese, so it follows the prompt (simple English).
        "steps": [{"tool_output": 'parcial (tentativa 1 de 2). NÃO diga a resposta: dê uma pista curta de onde está '
                                  'o erro (a forma certa, só para você, é "My name is Pedro.") e peça para ele '
                                  "tentar de novo.",
                   "expect": {"reply": {"max_sentences": 4, "lacks": ["My name is Pedro"]}, "rubric": [
                       "Dá uma pista em inglês simples de onde está o erro (falta o is), sem dizer a frase certa.",
                       "Pede para tentar de novo."]}}],
    },
]

# ── Free practice: the site (goal menu) and the app (topic, review, memory) ────

TOPIC = "Primeiros contatos — Cumprimentar e se apresentar"

FREE_CASES = [
    {
        "id": "livre-recast", "category": "prática livre", "request": free(topic=TOPIC),
        "history": [("flua", "Nice! And how old are you? Quantos anos você tem?")],
        "steps": [{"say": "I have 30 years."}, {"respond": True, "expect": {
            "reply": {"max_sentences": 4},
            "rubric": ["Usa a forma certa (I'm 30 ou I am 30 years old) dentro da própria resposta.",
                       "Corrige no máximo dois pontos.", "Segue a conversa com algo para a aluna responder."],
        }}],
    },
    {
        "id": "livre-mesmo-erro-pela-terceira-vez", "category": "prática livre", "request": free(topic=TOPIC),
        "history": [("flua", "How old are you?"), ("aluno", "I have 30 years."),
                    ("flua", "Oh, you're 30 — a gente diz I'm 30, não I have. And your sister?"),
                    ("aluno", "She have 25 years."),
                    ("flua", "She's 25, nice — idade usa to be. And your brother?")],
        "steps": [{"say": "He have 20 years."}, {"respond": True, "expect": {
            "reply": {"max_sentences": 4},
            "rubric": [("Para e corrige de forma explícita (idade em inglês usa to be), em vez de só repetir a "
                       "forma certa de passagem."),
                       "Pede para a aluna tentar de novo ou dá o modelo He's 20."],
        }}],
    },
    {
        "id": "livre-pedido-so-ingles", "category": "prática livre", "request": free(topic=TOPIC),
        "history": [("flua", "Oi, Ana! Hoje vamos praticar cumprimentos. How are you today?")],
        "steps": [{"say": "Let's practice only in English, please."}, {"respond": True, "expect": {
            "reply": {"max_sentences": 4},
            "rubric": ["A resposta é toda ou quase toda em inglês."],
        }}],
    },
    {
        "id": "livre-muda-de-assunto", "category": "prática livre", "request": free(topic=TOPIC),
        "history": [("flua", "Oi, Ana! Hoje vamos praticar cumprimentos. How are you today?")],
        "steps": [{"say": "Na verdade eu queria treinar pedir comida num restaurante."}, {"respond": True, "expect": {
            "reply": {"max_sentences": 4},
            "rubric": ["Aceita o novo assunto (pedir comida num restaurante) e começa a praticá-lo.",
                       "Não insiste no tema anterior."],
        }}],
    },
    {
        "id": "livre-nem-tudo-e-pergunta", "category": "prática livre", "request": free(topic=TOPIC),
        "history": [("flua", "What do you do on weekends?")],
        "steps": [
            {"say": "I like to cook with my family."}, {"respond": True},
            {"say": "Yes, I cook pasta every Sunday."}, {"respond": True},
            {"say": "My mother makes the sauce."}, {"respond": True},
        ],
        "across": {"some_reply_without_question": True},
    },
    {
        "id": "livre-nao-sabe-nao-inventa", "category": "prática livre", "request": free(topic=TOPIC),
        "history": [("flua", "Hi, Ana! What would you like to talk about?")],
        "steps": [{"say": "Qual é a origem exata da expressão 'raining cats and dogs'?"}, {"respond": True, "expect": {
            "reply": {"max_sentences": 4},
            "rubric": [("Não apresenta uma origem inventada como fato: diz que a origem é incerta ou fala só do "
                       "significado (chover muito).")],
        }}],
    },
    {
        "id": "livre-espanhol-na-aula-de-ingles", "category": "prática livre", "request": free(topic=TOPIC),
        "history": [("flua", "Hi, Ana! How are you today?")],
        "steps": [{"say": "Hola, ¿cómo estás?"}, {"respond": True, "expect": {"reply": {"max_sentences": 4}}}],
    },
    {
        "id": "livre-intermediario-recast", "category": "prática livre", "request": free(topic=TOPIC, level="intermediate"),
        "history": [("flua", "So, what did you do yesterday?")],
        "steps": [{"say": "Yesterday I go to the beach with my friends."}, {"respond": True, "expect": {
            "reply": {"max_sentences": 4},
            "rubric": ["Usa a forma certa (went) dentro da própria resposta.", "Segue a conversa."],
        }}],
    },
]

# ── Openings: Flua speaks first ──────────────────────────────────────────────

OPENING_CASES = [
    {
        "id": "abertura-aula-do-site", "category": "abertura", "request": lesson(),
        "steps": [{"open": True, "expect": {
            "reply": {"max_sentences": 4},
            "rubric": ["Cumprimenta a Ana pelo nome.",
                       "Diz em 1 frase o que ela vai conseguir fazer na aula.",
                       "Termina pedindo que a aluna diga algo em inglês (um modelo para repetir ou um pedido claro)."],
        }}],
    },
    {
        "id": "abertura-guiada", "category": "abertura", "request": guided(),
        "steps": [{"open": True, "expect": {
            "reply": {"max_sentences": 4},
            "rubric": ["Cumprimenta a Ana pelo nome.",
                       "Ensina a frase I am Ana com a tradução.",
                       "A última coisa da fala é a frase-modelo para repetir, sem nada depois dela."],
        }}],
    },
    {
        "id": "abertura-livre-com-tema", "category": "abertura", "request": free(topic=TOPIC),
        "steps": [{"open": True, "expect": {
            "reply": {"max_sentences": 3},
            "rubric": ["Cumprimenta a Ana pelo nome e diz o tema (cumprimentar e se apresentar).",
                       "Faz uma primeira pergunta curta em inglês sobre o tema.",
                       "Não oferece um menu de assuntos."],
        }}],
    },
    {
        "id": "abertura-livre-sem-tema", "category": "abertura", "request": free(),
        "steps": [{"open": True, "expect": {
            "reply": {"max_sentences": 3},
            "rubric": ["Cumprimenta a Ana pelo nome.", "Pergunta o que ela quer praticar."],
        }}],
    },
    {
        "id": "abertura-aquecimento", "category": "abertura",
        "request": free(topic=TOPIC, reviewPhrases=[{"english": "Good morning", "portuguese": "Bom dia"},
                                                    {"english": "How are you?", "portuguese": "Como vai?"}]),
        "steps": [{"open": True, "expect": {
            "reply": {"max_sentences": 3, "lacks": ["Good morning"]},
            "rubric": ["Pede, em português, que a aluna diga em inglês, de memória, como se diz bom dia.",
                       "Não diz a resposta antes da aluna tentar."],
        }}],
    },
]

# Memory of earlier mistakes (learner_memory.recent) for the app's free practice, on an error no case tests, so
# what a case measures (recast, explicit correction) is not the memory block at work.
for case in FREE_CASES:
    case.setdefault("mistakes", [{"said": "I am agree", "natural": "I agree", "tip": "agree já é verbo, sem am"}])

# ── The voice-teacher policy (flueai docs/flua-tutor/04-professor-por-voz.md) ──────────────────────────────
# English by default at every level, Portuguese on request, the free-practice modes chosen by voice, slang with a
# professional alternative, and the closing review. New in 04: not in the 2c baseline.

def voiced(case_id: str, history: list, said: str, *, reply: dict | None = None, rubric: list[str],
           **request) -> dict:
    return {
        "id": case_id, "category": "professor por voz", "request": free(topic=TOPIC, **request), "history": history,
        "steps": [{"say": said}, {"respond": True, "expect": {"reply": reply or {"max_sentences": 4}, "rubric": rubric}}],
    }


GREETED = [("flua", "Hi, Ana! Today we're practicing greetings. How are you today?")]
WEEKEND = [("flua", "What do you do on weekends?"), ("aluno", "I like to cook with my family."),
           ("flua", "That's lovely! What do you cook?"), ("aluno", "I cook pasta every Sunday."),
           ("flua", "Pasta every Sunday sounds perfect.")]

VOICE_CASES = [
    voiced("voz-ingles-por-padrao-iniciante", GREETED, "I'm fine, thank you. And you?",
           rubric=["A resposta é em inglês, sem frases em português."]),
    voiced("voz-portugues-quando-pede", GREETED, "Não entendi o que é 'how are you', explica em português?",
           rubric=["Explica em português que how are you é como você está.", "A explicação é curta."]),
    voiced("voz-volta-ao-ingles",
           [*GREETED, ("aluno", "Não entendi, explica em português?"),
            ("flua", "Claro! How are you quer dizer como você está. É o jeito mais comum de cumprimentar.")],
           "Ah, entendi! I'm good, thanks!",
           rubric=["Volta a falar em inglês: a resposta é toda ou quase toda em inglês."]),
    voiced("voz-mais-devagar", GREETED, "Can you speak more slowly, please?",
           rubric=["Aceita o pedido e segue com frases curtas e simples, em inglês."]),
    voiced("voz-correcao-guiada",
           [("aluno", "Can you correct me after every sentence, please?"),
            ("flua", "Sure! I'll correct you after each sentence. So, what did you do yesterday?")],
           "Yesterday I go to the office and I have a meeting with my boss.",
           rubric=["Corrige de forma explícita os verbos no passado (went, had), no máximo 2 pontos.",
                   "Segue a conversa sobre o dia ou a reunião da aluna."]),
    voiced("voz-shadowing", GREETED, "Can we practice listening and shadowing?",
           reply={"max_sentences": 5},
           rubric=["Conta uma história curta em inglês (3 a 4 frases) e faz uma pergunta de compreensão.",
                   "Não pede para repetir um trecho longo."]),
    voiced("voz-giria", GREETED, "My friend said 'I'm beat'. What does it mean?", level="intermediate",
           rubric=["Explica que significa estar muito cansado.", "Diz que é uma expressão informal.",
                   "Dá uma alternativa profissional (ex.: I'm exhausted, I'm very tired)."]),
    voiced("voz-revisao-final", WEEKEND, "I need to go now, bye!",
           rubric=["Revisa três aprendizados ou pontos da conversa.", "Se despede."]),
]

CASES = [*LESSON_CASES, *GUIDED_CASES, *FREE_CASES, *OPENING_CASES, *VOICE_CASES]
