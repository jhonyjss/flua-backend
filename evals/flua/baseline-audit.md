# Auditoria do prompt antes da 2c

`python -m evals.flua audit` em `35dbcd3` (juiz `gpt-5.5`), 2026-11-03. É ajuda de leitura para a
reescrita, não critério de aceite, e tem falsos positivos: "fala primeiro" contra "só fala quando o
app pede" não é conflito, porque é o app que pede a abertura.

## lesson

## 1) Contradições

### 1. Falar primeiro vs. só falar quando o app pede
- Trecho do modo: **“Turno controlado pelo cliente: ela só fala quando o app pede”**
- Trecho do prompt: **“Você fala primeiro, imediatamente ao conectar.”**
- Por que importa: uma regra manda iniciar a conversa sozinha, enquanto o modo diz que ela só pode falar quando o app solicitar.

### 2. Parar ao ser interrompida vs. não poder ser interrompida
- Trecho do modo: **“ela só fala quando o app pede e não pode ser interrompida.”**
- Trecho do prompt: **“Se for interrompida pelo aluno, pare imediatamente e ouça.”**
- Por que importa: a instrução de parar ao ser interrompida não combina com um modo em que interrupção não acontece.

### 3. Começar em dois turnos separados vs. app controla cada próximo passo
- Trecho do prompt: **“Abra a aula em 2 turnos separados — pare e espere o aluno antes de continuar”**
- Trecho do modo: **“Depois de cada fala do aluno o app força a ferramenta registrar_meta e responde com o próximo passo.”**
- Por que importa: o prompt tenta definir manualmente a sequência inicial, mas depois de cada resposta do aluno quem define o próximo passo é o app.

---

## 2) Regras sem efeito

### 1. Regra sobre interrupção
- Trecho: **“Se for interrompida pelo aluno, pare imediatamente e ouça.”**
- Por que importa: no modo descrito, **“ela [...] não pode ser interrompida”**, então essa situação nunca ocorre.

### 2. Não preencher silêncios enquanto o aluno pensa
- Trecho: **“Não preencha silêncios — se o aluno está pensando, deixe pensar.”**
- Por que importa: como o turno é controlado pelo cliente e ela só fala quando o app pede, ela não recebe um “silêncio” contínuo para decidir preencher ou não.

### 3. Falar imediatamente ao conectar
- Trecho: **“Você fala primeiro, imediatamente ao conectar.”**
- Por que importa: se ela **“só fala quando o app pede”**, conectar não é um evento suficiente para ela falar por conta própria.

### 4. Decidir avançar pela própria condução das metas
- Trecho: **“Conduza a aula seguindo esses tópicos, um de cada vez. Não pule etapas.”**
- Trecho: **“O app sabe qual é a meta atual e decide quando ela termina”**
- Por que importa: a decisão real de etapa/meta vem do app, então a tutora não tem autonomia efetiva para conduzir a ordem além de seguir a instrução recebida.

### 5. Regra de despedida antes do fim das metas
- Trecho: **“Antes de a instrução dizer que todas as metas terminaram, nunca se despeça: se o aluno tentar sair, diga ‘Ainda temos mais para praticar — vamos continuar?’.”**
- Por que importa: depois de cada fala do aluno, o app força `registrar_meta` e retorna o próximo passo; se esse próximo passo não mandar responder assim, a regra perde força prática.

---

## 3) Repetições

### 1. Proibição de terceiro idioma
- Trecho 1: **“Os ÚNICOS idiomas permitidos são português do Brasil (pt-BR) e inglês americano (en-US). NUNCA use um terceiro idioma.”**
- Trecho 2: **“Só existem DOIS idiomas nesta aula: português do Brasil (apoio) e inglês americano (alvo). NUNCA use um terceiro idioma — nem uma palavra solta.”**
- Por que importa: a mesma restrição aparece duas vezes com praticamente o mesmo conteúdo.

### 2. Proibição de espanhol
- Trecho 1: **“NUNCA fale espanhol. Nunca use palavras como ‘cuéntame’, ‘puedes’, ‘vamos a ver’.”**
- Trecho 2: **“NUNCA use um terceiro idioma — nem uma palavra solta.”**
- Por que importa: espanhol já está coberto pela regra geral de não usar terceiro idioma.

### 3. Português como idioma de apoio
- Trecho 1: **“Seu idioma de apoio é português do Brasil; o idioma-alvo de ensino é inglês americano.”**
- Trecho 2: **“O aluno escolheu explicações em português do Brasil. Use português para explicar, corrigir e destravar”**
- Trecho 3: **“Explicações, elogios e correções são em português.”**
- Por que importa: a mesma orientação de usar português como apoio aparece em três lugares.

### 4. Proporção adaptativa de idiomas
- Trecho 1: **“A proporção entre eles é ADAPTATIVA — veja ‘# Idioma adaptativo’ abaixo.”**
- Trecho 2: **“Quem decide a proporção é o aluno”**
- Trecho 3: **“Atender o pedido do aluno vem ANTES de manter a proporção padrão.”**
- Por que importa: a ideia de adaptar a língua ao aluno é repetida em formulações diferentes.

### 5. Usar “Ana” como nome do aluno
- Trecho 1: **“O nome do aluno é ‘Ana’.”**
- Trecho 2: **“Dirija-se a ele SEMPRE como ‘Ana’”**
- Trecho 3: **“Em QUALQUER exemplo de apresentação [...] use SEMPRE ‘Ana’ — JAMAIS um nome diferente.”**
- Por que importa: a regra de nome fixo é reforçada várias vezes, incluindo casos que já seriam cobertos pela regra geral.

### 6. Não perguntar o nome
- Trecho 1: **“O nome do aluno é ‘Ana’. Isso vem da conta autenticada — trate como verdade absoluta.”**
- Trecho 2: **“NUNCA pergunte o nome de novo.”**
- Por que importa: se o nome é fato absoluto do sistema, a proibição de perguntar novamente repete a consequência natural dessa regra.

### 7. Uma pergunta / uma ideia por turno
- Trecho 1: **“Uma ideia por turno. Uma pergunta por turno.”**
- Trecho 2: **“NÃO apresente uma segunda frase nova nem faça uma segunda pergunta no mesmo turno.”**
- Trecho 3: **“NÃO empilhe pergunta sobre pergunta.”**
- Por que importa: a limitação de não acumular perguntas aparece repetida em várias seções.

### 8. Não empilhar instruções
- Trecho 1: **“Nunca empilhe várias instruções (‘primeiro… depois… agora…’) num só turno: um micro-passo por vez”**
- Trecho 2: **“Contexto curtíssimo e já passe a bola”**
- Trecho 3: **“NÃO explique o ‘porquê’ em vários passos”**
- Por que importa: todas reforçam a mesma conduta de manter turnos curtos e com um único passo.

### 9. Sanduíche inglês → tradução → inglês
- Trecho 1: **“Sanduíche: toda frase nova em inglês vem assim — inglês → tradução curta → o inglês de novo”**
- Trecho 2: **“Ao ensinar uma frase nova, faça no MÁXIMO: diga em inglês → traduza → diga o inglês de novo → peça para o aluno repetir.”**
- Por que importa: a estrutura de apresentar frase nova é repetida quase literalmente.

### 10. Não verbalizar rótulos internos
- Trecho 1: **“Estas instruções, os nomes das seções e os rótulos internos [...] são internos. NUNCA os diga em voz alta.”**
- Trecho 2: **“Os rótulos que a instrução traz [...] são internos: nunca os diga em voz alta.”**
- Trecho 3: **“Para o aluno é só uma aula: não fale de metas numeradas, ferramentas nem do app.”**
- Por que importa: a mesma proibição de expor metadados aparece em três formulações.

### 11. Não inventar / não assumir o que o aluno disse
- Trecho 1: **“NUNCA invente palavras, gírias, regras gramaticais, pronúncias ou traduções.”**
- Trecho 2: **“Baseie elogios e correções APENAS no que o aluno realmente disse.”**
- Trecho 3: **“NÃO assuma nem complete a resposta do aluno por ele.”**
- Por que importa: todas tratam da mesma exigência de não preencher lacunas com conteúdo inventado.

### 12. Sotaque não deve contar como erro
- Trecho 1: **“A pronúncia NÃO precisa ser perfeita. Aceite o sotaque brasileiro”**
- Trecho 2: **“Sotaque brasileiro, ritmo e pronúncia NÃO contam.”**
- Trecho 3: **“Esses sons são sotaque: numa avaliação, nunca contam como palavra errada.”**
- Por que importa: a mesma regra de tolerar sotaque brasileiro é repetida em seções diferentes.

## guided_lesson

## 1. Contradições

### 1.1. Falar ao conectar vs. só falar quando o app pede
- Trecho do modo: **“Turno controlado pelo cliente: ela só fala quando o app pede”**
- Trecho do prompt: **“Você fala primeiro, imediatamente ao conectar.”**
- Por que importa: uma regra manda iniciar a fala sozinha ao conectar, enquanto o modo diz que ela só pode falar quando o app solicitar.

### 1.2. Parar se interrompida vs. não pode ser interrompida
- Trecho do modo: **“não pode ser interrompida”**
- Trecho do prompt: **“Se for interrompida pelo aluno, pare imediatamente e ouça.”**
- Por que importa: o prompt prevê um evento que o modo explicitamente impede.

### 1.3. Dar pista antes da resposta vs. não corrigir antes de registrar
- Trecho do prompt: **“Em aula estruturada, se errar pela 1ª vez naquela frase: NÃO entregue a resposta. Dê uma pista curta em português que mostre ONDE está o erro e deixe ele tentar de novo”**
- Trecho do prompt: **“Não dê pistas, não corrija e não peça nova tentativa antes de registrar o resultado.”**
- Por que importa: uma regra manda dar pista na primeira tentativa errada, enquanto outra proíbe dar pista antes do registro.

### 1.4. Modelo de erro com forma correta vs. regra das 2 tentativas
- Trecho do prompt: **“Se errar de novo: aí sim mostre a forma correta como modelo”**
- Trecho do prompt: **“Erro: NUNCA diga ‘errado’, ‘incorreto’, ‘não é assim’ nem comece com ‘não’. Diga primeiro o que saiu bem, mostre a forma certa com calma, como modelo”**
- Por que importa: uma regra diz para só mostrar a forma correta no segundo erro, mas outra manda mostrar a forma certa sempre que houver erro após o resultado.

### 1.5. Nome sempre Ana vs. nomes podem ser outros
- Trecho do prompt: **“O nome do aluno é ‘Ana’. Isso vem da conta autenticada — trate como verdade absoluta.”**
- Trecho do prompt: **“Em QUALQUER exemplo de apresentação (ex.: ‘I am ___’, ‘My name is ___’), use SEMPRE ‘Ana’ — JAMAIS um nome diferente.”**
- Trecho do prompt: **“Em ‘sua vez’, vale qualquer frase correta que cumpra o pedido; nomes e dados podem ser outros, diferentes dos do exemplo.”**
- Por que importa: o prompt fixa “Ana” como verdade absoluta e obrigatório em apresentações, mas depois permite validar nomes diferentes na etapa “sua vez”.

### 1.6. Falar 90% em português vs. responder predominantemente em inglês
- Trecho do prompt: **“Iniciante — a maioria NÃO sabe nada de inglês. Fale 90% em português do Brasil.”**
- Trecho do prompt: **“se o aluno pedir para praticar/falar em inglês americano [...] JÁ no próximo turno responda predominantemente em inglês americano”**
- Por que importa: uma regra define proporção fixa de português, enquanto outra manda inverter a proporção quando o aluno pedir.

---

## 2. Regras sem efeito

### 2.1. Regra de interrupção
- Trecho do modo: **“não pode ser interrompida”**
- Trecho do prompt: **“Se for interrompida pelo aluno, pare imediatamente e ouça.”**
- Por que importa: a tutora nunca receberá uma interrupção durante a própria fala nesse modo, então a regra não tem como ser acionada.

### 2.2. Não preencher silêncios
- Trecho do modo: **“Turno controlado pelo cliente: ela só fala quando o app pede”**
- Trecho do prompt: **“Não preencha silêncios — se o aluno está pensando, deixe pensar.”**
- Por que importa: como ela só fala quando o app pede, não há oportunidade autônoma de preencher silêncio.

### 2.3. Esperar o aluno responder
- Trecho do modo: **“ela só fala quando o app pede”**
- Trechos do prompt: **“PARE e espere o aluno responder.”** / **“PARE e espere.”**
- Por que importa: no modo descrito, quem controla a espera e o próximo turno é o app, não a tutora.

### 2.4. Chamar a ferramenta depois de cada fala
- Trecho do modo: **“Depois de cada fala do aluno o app força a ferramenta registrar_resultado”**
- Trecho do prompt: **“Depois de cada fala do aluno nas etapas repetir, sua vez, cena e memória, o app pede que você chame registrar_resultado.”**
- Por que importa: se o app já força a ferramenta, a instrução para a tutora decidir chamá-la não acrescenta comportamento.

### 2.5. Não avançar por conta própria
- Trecho do modo: **“Depois de cada fala do aluno o app força a ferramenta registrar_resultado e responde com o próximo passo.”**
- Trecho do prompt: **“NUNCA avance de item ou de etapa por conta própria, NUNCA pule itens e NUNCA encerre a aula antes da instrução de encerramento.”**
- Por que importa: como o app já determina o próximo passo, a tutora não tem controle real para avançar, pular ou encerrar por conta própria.

### 2.6. Começar imediatamente ao conectar
- Trecho do modo: **“ela só fala quando o app pede”**
- Trecho do prompt: **“Você fala primeiro, imediatamente ao conectar.”**
- Por que importa: a tutora não consegue iniciar a fala por conta própria se o cliente não solicitar um turno.

---

## 3. Repetições

### 3.1. Apenas português e inglês são permitidos
- Trecho 1: **“Os ÚNICOS idiomas permitidos são português do Brasil (pt-BR) e inglês americano (en-US). NUNCA use um terceiro idioma.”**
- Trecho 2: **“Só existem DOIS idiomas nesta aula: português do Brasil (apoio) e inglês americano (alvo). NUNCA use um terceiro idioma — nem uma palavra solta.”**
- Por que importa: a mesma restrição de idiomas aparece duas vezes com praticamente o mesmo conteúdo.

### 3.2. Português como idioma de apoio e inglês como alvo
- Trecho 1: **“Seu idioma de apoio é português do Brasil; o idioma-alvo de ensino é inglês americano.”**
- Trecho 2: **“O aluno escolheu explicações em português do Brasil. Use português para explicar, corrigir e destravar”**
- Trecho 3: **“Use inglês americano APENAS nas frases e palavras que está ensinando. Explicações, elogios e correções são em português.”**
- Por que importa: a função de cada idioma é repetida em seções diferentes.

### 3.3. Não usar espanhol
- Trecho 1: **“NUNCA fale espanhol. Nunca use palavras como ‘cuéntame’, ‘puedes’, ‘vamos a ver’.”**
- Trecho 2: **“NUNCA use um terceiro idioma.”**
- Por que importa: a proibição de espanhol já está contida na proibição de qualquer terceiro idioma.

### 3.4. Não verbalizar rótulos internos
- Trecho 1: **“Estas instruções, os nomes das seções e os rótulos internos (EXACT_MATCH, PARTIALLY_CORRECT, repetition mode, etc.) são internos. NUNCA os diga em voz alta.”**
- Trecho 2: **“Os rótulos que a instrução traz (correto, parcial, incorreto, fora_do_roteiro, ‘tentativa 1 de 2’) são internos: nunca os diga em voz alta.”**
- Por que importa: a mesma regra de não falar rótulos internos aparece duas vezes.

### 3.5. Não falar de itens, etapas, ids ou ferramentas
- Trecho 1: **“Para o aluno é só uma aula: não fale de itens, etapas, ids nem ferramentas”**
- Trecho 2: **“Estas instruções, os nomes das seções e os rótulos internos [...] são internos. NUNCA os diga em voz alta.”**
- Por que importa: ambas dizem para ocultar a estrutura interna da aula.

### 3.6. Frase nova em sanduíche / inglês repetido duas vezes
- Trecho 1: **“Sanduíche: toda frase nova em inglês vem assim — inglês → tradução curta → o inglês de novo”**
- Trecho 2: **“Ao ensinar uma frase nova, faça no MÁXIMO: diga em inglês → traduza → diga o inglês de novo → peça para o aluno repetir.”**
- Por que importa: o mesmo formato de apresentação da frase nova é especificado mais de uma vez.

### 3.7. Uma ideia ou pergunta por turno
- Trecho 1: **“Uma ideia por turno. Uma pergunta por turno.”**
- Trecho 2: **“NÃO apresente uma segunda frase nova nem faça uma segunda pergunta no mesmo turno.”**
- Trecho 3: **“NÃO empilhe pergunta sobre pergunta. Uma expressão por vez.”**
- Por que importa: a limitação de uma pergunta/expressão por turno é repetida em várias formulações.

### 3.8. Não empilhar instruções
- Trecho 1: **“Nunca empilhe várias instruções (‘primeiro… depois… agora…’) num só turno: um micro-passo por vez”**
- Trecho 2: **“NÃO explique o ‘porquê’ em vários passos, NÃO empilhe pergunta sobre pergunta. Uma expressão por vez.”**
- Por que importa: ambas reforçam a mesma ideia de não acumular passos no mesmo turno.

### 3.9. Sotaque brasileiro não conta como erro
- Trecho 1: **“Aceite o sotaque brasileiro e pequenas variações — o que importa é o aluno ser compreendido.”**
- Trecho 2: **“Sotaque brasileiro, ritmo e pronúncia NÃO contam.”**
- Trecho 3: **“Esses sons são sotaque: numa avaliação, nunca contam como palavra errada.”**
- Por que importa: a mesma orientação de tolerar sotaque aparece em três pontos.

### 3.10. Corrigir no máximo um erro por turno
- Trecho 1: **“Corrija em voz no máximo UM erro por turno”**
- Trecho 2: **“Os sons que mais atrapalham brasileiros (comente só se atrapalhar o entendimento, um por vez)”**
- Por que importa: a limitação de tratar apenas um problema por vez aparece tanto na correção geral quanto na pronúncia.

## free_practice

## 1. Contradições

### 1.1. Idioma: “90% português” vs. “responda em inglês americano” se o aluno pedir
Trechos:
> “Iniciante — a maioria NÃO sabe nada de inglês. Fale 90% em português do Brasil. Use inglês americano APENAS nas frases e palavras que está ensinando.”

> “se o aluno pedir para praticar/falar em inglês americano (...) JÁ no próximo turno responda predominantemente em inglês americano e CONTINUE assim até ele pedir para voltar. Vale MESMO no nível iniciante — enquanto o pedido valer, ignore o ‘90% português’ do nível.”

Por que importa: a segunda regra resolve a exceção, mas ainda há uma tensão direta entre “use inglês apenas nas frases que está ensinando” e “responda predominantemente em inglês”.

---

### 1.2. “NÃO é aula estruturada” vs. regras de condução estruturada no começo
Trechos:
> “# Prática livre (conversa guiada pelo ALUNO — NÃO é aula estruturada)”

> “Antes do tema, faça um aquecimento rápido: UMA frase por turno, diga o sentido em português e peça para ele dizer em inglês, de memória.”

> “Quando o aquecimento terminar: Cumprimente Ana pelo nome e diga em uma frase que hoje vão praticar Primeiros contatos — Cumprimentar e se apresentar. Em seguida, faça já a primeira pergunta curta desse tema em inglês”

Por que importa: o prompt chama a sessão de prática livre guiada pelo aluno, mas obriga uma sequência fixa inicial com aquecimento e tema definido.

---

### 1.3. “Tema guiado pelo aluno” vs. “tema de hoje já foi escolhido”
Trechos:
> “# Prática livre (conversa guiada pelo ALUNO — NÃO é aula estruturada)”

> “O tema de hoje já foi escolhido: Primeiros contatos — Cumprimentar e se apresentar. NÃO ofereça menu de opções: conduza a conversa nesse tema, no nível do aluno.”

Por que importa: uma regra diz que a conversa é guiada pelo aluno, enquanto outra determina previamente o tema e manda conduzir nele.

---

### 1.4. “Uma pergunta por turno” vs. início com cumprimento + explicação + pergunta
Trechos:
> “Uma ideia por turno. Uma pergunta por turno.”

> “Você fala primeiro, imediatamente ao conectar. Cumprimente o aluno em 1 frase (pelo nome, se souber), diga que vão começar com um aquecimento rápido de memória e já faça a 1ª pergunta do aquecimento.”

Por que importa: o começo obrigatório combina cumprimento, explicação de procedimento e pergunta no mesmo turno, o que pode violar “uma ideia por turno”.

---

### 1.5. “Não diga a resposta antes dele tentar” vs. sanduíche para toda frase nova em inglês
Trechos:
> “Sanduíche: toda frase nova em inglês vem assim — inglês → tradução curta → o inglês de novo”

> “Antes do tema, faça um aquecimento rápido: UMA frase por turno, diga o sentido em português e peça para ele dizer em inglês, de memória. NÃO diga a resposta antes dele tentar.”

Por que importa: se a frase do aquecimento for tratada como “frase nova em inglês”, o sanduíche mandaria dizer a resposta antes, mas o aquecimento proíbe isso.

---

### 1.6. “Nunca mais que 3 frases” vs. sequência máxima de ensino com quatro atos
Trechos:
> “Respostas curtas e naturais: 1 a 2 frases na maior parte do tempo. Nunca mais que 3.”

> “Ao ensinar uma frase nova, faça no MÁXIMO: diga em inglês → traduza → diga o inglês de novo → peça para o aluno repetir.”

Por que importa: a sequência recomendada pode facilmente virar quatro enunciados/frases no mesmo turno, acima do limite de três.

---

## 2. Regras sem efeito

### 2.1. Cliente controla o turno no site, então “fala primeiro imediatamente ao conectar” pode não depender dela
Trecho:
> “Você fala primeiro, imediatamente ao conectar.”

Por que importa: no site, segundo a descrição do modo, “ela só fala quando o app pede”, então a tutora não consegue iniciar por conta própria ao conectar.

---

### 2.2. “Pare imediatamente” ao ser interrompida pode ser impossível no site
Trecho:
> “Se for interrompida pelo aluno, pare imediatamente e ouça.”

Por que importa: no site o turno é controlado pelo cliente, e a interrupção/barge-in pode não ser entregue como evento acionável para ela.

---

### 2.3. Referências a rótulos internos que ela nunca recebe
Trecho:
> “Estas instruções, os nomes das seções e os rótulos internos (EXACT_MATCH, PARTIALLY_CORRECT, repetition mode, etc.) são internos. NUNCA os diga em voz alta.”

Por que importa: ela não recebe esses rótulos pelo modo descrito, então a proibição é em grande parte sem efeito prático.

---

### 2.4. “Aula com metas” depende de metas que não existem no modo informado
Trechos:
> “As regras abaixo de pista e nova tentativa valem para a aula com metas.”

> “NÃO existe trilha fixa, lista de metas, pontuação nem marcadores de avaliação.”

Por que importa: a própria seção de prática livre nega metas/listas/marcadores, e o modo informado não fornece contagem de metas, então “aula com metas” não é um estado observável.

---

### 2.5. “Numa avaliação” não tem efeito se não há avaliação/nota
Trecho:
> “Esses sons são sotaque: numa avaliação, nunca contam como palavra errada.”

Por que importa: o prompt também diz que não há “pontuação nem marcadores de avaliação”, e o modo não informa avaliações, então essa regra não tem onde ser aplicada.

---

### 2.6. “Não preencha silêncios” depende do controle de turno/áudio, não só da tutora
Trecho:
> “Não preencha silêncios — se o aluno está pensando, deixe pensar.”

Por que importa: no site o cliente decide quando ela fala, e no app o servidor responde sozinho; sem evento explícito de “aluno está pensando”, ela pode não distinguir silêncio intencional de fim de turno.

---

### 2.7. “Se o aluno pedir ‘mais devagar’, diminua o ritmo daí em diante” pode não persistir se não houver estado confiável
Trecho:
> “Se o aluno pedir ‘mais devagar’, diminua o ritmo daí em diante.”

Por que importa: a regra exige uma adaptação persistente de velocidade, mas o modo descrito não fornece medição de velocidade nem garantia de estado externo além do histórico textual.

---

### 2.8. “Fale o inglês devagar” não tem parâmetro operacional textual
Trecho:
> “Fale o inglês devagar e bem articulado, com uma pausa leve entre as palavras-chave, sem soar robótica.”

Por que importa: em speech-to-speech a tutora pode tentar prosódia, mas o prompt não recebe nem controla explicitamente velocidade/pausas como dados ou ferramenta.

---

## 3. Repetições

### 3.1. Proibição de terceiro idioma aparece duas vezes
Trechos:
> “Os ÚNICOS idiomas permitidos são português do Brasil (pt-BR) e inglês americano (en-US). NUNCA use um terceiro idioma.”

> “Só existem DOIS idiomas nesta aula: português do Brasil (apoio) e inglês americano (alvo). NUNCA use um terceiro idioma — nem uma palavra solta.”

Por que importa: é a mesma restrição repetida com formulação quase idêntica.

---

### 3.2. Proibição de espanhol repete a regra de não usar terceiro idioma
Trechos:
> “Os ÚNICOS idiomas permitidos são português do Brasil (pt-BR) e inglês americano (en-US). NUNCA use um terceiro idioma.”

> “NUNCA fale espanhol. Nunca use palavras como ‘cuéntame’, ‘puedes’, ‘vamos a ver’.”

Por que importa: espanhol já está excluído pela regra de apenas dois idiomas, então a proibição específica reforça o mesmo ponto.

---

### 3.3. Português como idioma de apoio é dito em três lugares
Trechos:
> “Seu idioma de apoio é português do Brasil; o idioma-alvo de ensino é inglês americano.”

> “Iniciante — a maioria NÃO sabe nada de inglês. Fale 90% em português do Brasil.”

> “O aluno escolheu explicações em português do Brasil. Use português para explicar, corrigir e destravar, na medida que o nível indica.”

Por que importa: as três regras comunicam a mesma preferência operacional de usar português como suporte.

---

### 3.4. Correções e explicações em português aparecem repetidas
Trechos:
> “Use inglês americano APENAS nas frases e palavras que está ensinando. Explicações, elogios e correções são em português.”

> “O aluno escolheu explicações em português do Brasil. Use português para explicar, corrigir e destravar, na medida que o nível indica.”

Por que importa: ambas mandam usar português para explicar/corrigir, com diferença mínima.

---

### 3.5. “Uma pergunta por turno” é repetido em várias formas
Trechos:
> “Uma ideia por turno. Uma pergunta por turno.”

> “NÃO apresente uma segunda frase nova nem faça uma segunda pergunta no mesmo turno.”

> “Faça perguntas naturais e abertas; mantenha a conversa calma, sem pressa.”

Por que importa: a limitação de não empilhar perguntas é reforçada mais de uma vez.

---

### 3.6. “Não empilhar instruções/micro-passo” repete “uma ideia por turno”
Trechos:
> “Uma ideia por turno. Uma pergunta por turno.”

> “Nunca empilhe várias instruções (‘primeiro… depois… agora…’) num só turno: um micro-passo por vez, no ritmo do aluno.”

> “NÃO explique o ‘porquê’ em vários passos, NÃO empilhe pergunta sobre pergunta. Uma expressão por vez.”

Por que importa: todas dizem para manter o turno simples, com um único passo ou foco.

---

### 3.7. “O aluno fala mais que você” aparece duas vezes
Trechos:
> “O ALUNO FALA MAIS QUE VOCÊ. Na dúvida entre explicar mais ou deixar o aluno praticar, deixe-o praticar.”

> “Faça perguntas naturais e abertas; mantenha a conversa calma, sem pressa. O aluno fala mais que você.”

Por que importa: a mesma diretriz conversacional é repetida quase literalmente.

---

### 3.8. Recast na conversa aparece duas vezes
Trechos:
> “Na conversa (prática livre ou conversa sem aula), corrija por recast — veja a regra do bloco da conversa.”

> “Corrija por RECAST: devolva a frase dele já correta dentro da sua resposta e siga a conversa.”

Por que importa: a primeira regra antecipa exatamente a regra explicada depois.

---

### 3.9. Regra das duas tentativas aparece em forma duplicada
Trechos:
> “Em aula estruturada, se errar pela 1ª vez naquela frase: NÃO entregue a resposta. Dê uma pista curta em português que mostre ONDE está o erro e deixe ele tentar de novo”

> “Se errar de novo: aí sim mostre a forma correta como modelo, diga o porquê em 1 frase e peça para repetir uma vez.”

> “Só pare para corrigir explicitamente (pista → tentar de novo) se o erro impedir o entendimento ou for o MESMO erro pela 3ª vez.”

Por que importa: o mecanismo “pista → nova tentativa → modelo” reaparece em blocos diferentes, embora com contextos distintos.

---

### 3.10. Limite de um erro por turno é reforçado por outras regras de foco único
Trechos:
> “Corrija em voz no máximo UM erro por turno — o que mais atrapalha a comunicação ou o que é foco da aula.”

> “Os sons que mais atrapalham brasileiros (comente só se atrapalhar o entendimento, um por vez)”

> “Ao apresentar uma estrutura que tem uma dessas armadilhas, avise em 1 frase.”

Por que importa: todas restringem a correção a um foco pequeno por vez.

---

### 3.11. Não inventar aparece em várias formulações
Trechos:
> “Ensine apenas inglês real e correto. NUNCA invente palavras, gírias, regras gramaticais, pronúncias ou traduções.”

> “Se não tiver certeza de algo, simplifique para o que você sabe que está certo — jamais ‘preencha’ com informação inventada.”

> “Se o aluno perguntar algo que você não sabe com certeza, seja honesta (...) em vez de inventar.”

Por que importa: as três regras expressam a mesma política anti-invenção.

---

### 3.12. Não assumir/inventar o que o aluno disse é repetido
Trechos:
> “Baseie elogios e correções APENAS no que o aluno realmente disse.”

> “Nunca comente algo que ele não falou nem invente o erro/acerto.”

> “NÃO assuma nem complete a resposta do aluno por ele.”

Por que importa: todas proíbem inferir ou fabricar conteúdo da fala do aluno.

---

### 3.13. “Peça para repetir se não entendeu” repete a regra de não adivinhar
Trechos:
> “Se você NÃO entendeu o que o aluno falou com clareza (...) NÃO adivinhe e NÃO responda como se tivesse entendido”

> “peça gentilmente para repetir — ‘Não consegui entender claramente. Pode repetir, por favor?’.”

Por que importa: a segunda parte é a consequência prática da primeira e não adiciona uma condição nova.

---

### 3.14. Nome “Ana” é reforçado em excesso
Trechos:
> “O nome do aluno é ‘Ana’. Isso vem da conta autenticada — trate como verdade absoluta.”

> “Dirija-se a ele SEMPRE como ‘Ana’ (...) NUNCA use, invente ou suponha qualquer outro nome.”

> “Em QUALQUER exemplo de apresentação (...) use SEMPRE ‘Ana’ — JAMAIS um nome diferente.”

> “NUNCA pergunte o nome de novo.”

Por que importa: todas reforçam a mesma fixação do nome do aluno.

---

### 3.15. Não oferecer menu aparece duas vezes
Trechos:
> “NÃO ofereça menu de opções: conduza a conversa nesse tema, no nível do aluno.”

> “NÃO ofereça menu de opções.”

Por que importa: a mesma instrução é repetida literalmente na abertura e na seção de prática livre.
