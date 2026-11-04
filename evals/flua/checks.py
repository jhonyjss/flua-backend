"""Objective checks on one Flua reply or tool call. Pure: each returns the failures, empty when it passes."""
import re

from evals.flua.session import Reply

# Internal names she must never say in any mode.
INTERNAL = ["fora_do_roteiro", "tentativa 1 de 2", "tentativa 2 de 2", "registrar_meta", "registrar_resultado",
            "EXACT_MATCH", "repetition mode"]
# With a tool in the session (the lessons) the prompt also forbids the outcome labels, the old spoken marker and
# the words for "wrong" in feedback; in free practice "That's correct!" is just praise.
TOOL_MODE = ["parcial", "incorreto", "errado", "Correct!", "Correto!"]
# Spanish in an English lesson (the prompt allows only Portuguese and English).
SPANISH = ["¿", "¡", "cuéntame", "puedes", "vamos a ver", "muy bien", "hola"]
PLACEHOLDER = re.compile(r"\[[^\]]*\]|\{[^}]*\}|<nome>")

# End of a sentence: punctuation, maybe a closing quote, then a space not followed by a dash (the EN — PT — EN
# sandwich goes on after "Hi, Ana! — Oi, Ana!") or the end of the text.
_SENTENCE_END = re.compile(r"[.!?…]+[\"”’']?(?=\s+(?![—–])|\s*$)")


def sentences(text: str) -> list[str]:
    """Sentences as the prompt's "1 a 3 frases" means them. A one-word interjection ("Isso!", "Ótimo!")
    is not counted, and the EN — PT — EN sandwich joined by dashes is one sentence."""
    parts, start = [], 0
    for end in _SENTENCE_END.finditer(text):
        parts.append(text[start:end.end()].strip())
        start = end.end()
    parts.append(text[start:].strip())
    return [part for part in parts if len(part.split()) > 1]


def word_count(text: str) -> int:
    return len(text.split())


def _has(text: str, needle: str) -> bool:
    """Case-insensitive; whole words for plain words, substring for anything with punctuation."""
    if re.fullmatch(r"[\wÀ-ÿ ]+", needle):
        return re.search(rf"(?<![\wÀ-ÿ]){re.escape(needle)}(?![\wÀ-ÿ])", text, re.IGNORECASE) is not None
    return needle.lower() in text.lower()


def check_reply(reply: Reply, expect: dict, *, language: str = "en", tool_mode: bool = False,
                learner: str = "") -> list[str]:
    """`learner` is the learner's last turn: echoing their words ("Você disse Hola…") is not speaking Spanish."""
    text = reply.text
    failures: list[str] = []
    if not text.strip():
        return ["sem fala"]
    if reply.calls:
        failures.append(f"chamou ferramenta fora da avaliação: {reply.calls[0].name}")
    # Always on: what she must never say in any case.
    failures += [f"disse o rótulo interno {word!r}" for word in INTERNAL if _has(text, word)]
    if tool_mode:
        failures += [f"disse {word!r} na aula" for word in TOOL_MODE if _has(text, word)]
    if PLACEHOLDER.search(text):
        failures.append("placeholder na fala")
    if language == "en":
        failures += [f"espanhol na aula de inglês: {word!r}" for word in SPANISH
                     if _has(text, word) and not _has(learner, word)]

    count = len(sentences(text))
    if "max_sentences" in expect and count > expect["max_sentences"]:
        failures.append(f"{count} frases (máximo {expect['max_sentences']})")
    words = word_count(text)
    if "max_words" in expect and words > expect["max_words"]:
        failures.append(f"{words} palavras (máximo {expect['max_words']})")
    failures += [f"disse {needle!r}" for needle in expect.get("lacks", []) if _has(text, needle)]
    if expect.get("has_any") and not any(_has(text, needle) for needle in expect["has_any"]):
        failures.append(f"não disse nenhum de {expect['has_any']}")
    if expect.get("ends_with_question") is False and text.rstrip().endswith("?"):
        failures.append("terminou em pergunta")
    return failures


def check_tool(reply: Reply, expect: dict) -> list[str]:
    calls = [call for call in reply.calls if call.name == expect["name"]]
    if not calls:
        return [f"não chamou {expect['name']}"]
    args = calls[0].args
    if not isinstance(args, dict):
        return [f"argumentos ilegíveis: {calls[0].arguments[:120]!r}"]
    failures: list[str] = []
    outcome = args.get("resultado")
    if "resultado" in expect and outcome not in expect["resultado"]:
        failures.append(f"resultado {outcome!r} (esperado {' ou '.join(expect['resultado'])})")
    heard = str(args.get("o_que_ouviu", ""))
    failures += [f"o_que_ouviu sem {word!r}: {heard!r}" for word in expect.get("heard_has", []) if not _has(heard, word)]
    failures += [f"o_que_ouviu com {word!r}: {heard!r}" for word in expect.get("heard_lacks", []) if _has(heard, word)]
    correct = str(args.get("forma_correta", ""))
    failures += [
        f"forma_correta sem {word!r}: {correct!r}" for word in expect.get("correct_has", []) if not _has(correct, word)
    ]
    return failures
