# Monitor do Diário Oficial do MPMG

Todo dia, este robô baixa a edição do [Diário Oficial do MPMG](https://www.mpmg.mp.br/portal/menu/servicos/diario-oficial/),
procura o seu nome e, se encontrar, manda um aviso para o seu celular (app **ntfy**) com o texto
completo da publicação e o link do PDF.

Roda de graça no GitHub Actions, às 09:00, 12:00 e 16:00 (horário de Brasília), mesmo com o
computador desligado. Avisa uma única vez por edição e não manda nada quando o nome não aparece.

## Como usar

1. Clique em **Use this template → Create a new repository**, escolha **Private** e crie.
2. No seu repositório: **Settings → Secrets and variables → Actions → New repository secret**:
   - `NOMES`: seu nome como sai no Diário, ex. `Maria da Silva Souza` (vários: separe por `;`)
   - `NTFY_TOPICO`: um nome secreto e difícil de adivinhar, ex. `mpmg-do-k7q2x9w4m1p8`
3. No app **ntfy** do celular, assine o mesmo tópico (servidor padrão `ntfy.sh`).
4. Teste em **Actions → Monitor Diario Oficial MPMG → Run workflow**, informando a data de uma
   edição em que seu nome saiu (formato `AAAA-MM-DD`).

O nome é procurado sem diferenciar maiúsculas, minúsculas ou acentos.

## Reserva no próprio computador (opcional)

Para rodar também no Windows, com Python 3 e `pip install pymupdf`: crie um `config.json` nesta pasta

```json
{ "nomes": ["Maria da Silva Souza"], "ntfy_topico": "mpmg-do-k7q2x9w4m1p8" }
```

e execute `instalar_agendamento.ps1`. A tarefa roda às 10:00, 13:00 e 17:00; o aviso não se repete
se o GitHub já tiver avisado.
