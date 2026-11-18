# moodle-notion-sync

Puxa as pendências do Moodle da UFOP (tarefas, questionários, fóruns com prazo) para o database **Pendências Moodle** no Notion (dentro de *Faculdade 4° período.*).

- Item novo no Moodle → cria linha com Status "A fazer"
- Prazo/nome mudou → atualiza (o Status que você marcou nunca é sobrescrito)
- Sumiu da lista de ações do Moodle antes do prazo → marca "Entregue" automaticamente

## Setup (uns 10 min)

### 1. Token do Moodle
Descubra a URL do Moodle que você usa (a do navegador, ex. `https://moodlepresencial.ufop.br`) e rode:

```bash
curl -s "https://SEU_MOODLE/login/token.php" \
  --data-urlencode "username=SEU_LOGIN" \
  --data-urlencode "password=SUA_SENHA" \
  --data-urlencode "service=moodle_mobile_app"
```

Retorna `{"token":"..."}`. Se der erro de serviço desabilitado, veja "Plano B" abaixo.

### 2. Integração do Notion
1. https://www.notion.so/profile/integrations → **New integration** (Internal) → copie o secret.
2. Abra a página **Faculdade 4° período.** → `•••` → **Connections** → adicione a integração.

### 3. Teste local
```bash
export MOODLE_URL=https://SEU_MOODLE MOODLE_TOKEN=... NOTION_TOKEN=...
DRY_RUN=1 python3 sync.py   # só mostra
python3 sync.py             # escreve
```

### 4. Automatizar (GitHub Actions)
Crie um repo **privado**, suba estes arquivos e cadastre em *Settings → Secrets → Actions*:
`MOODLE_URL`, `MOODLE_TOKEN`, `NOTION_TOKEN`, `NOTION_DB_ID` (`41cb47e9b6d181859d60cd9e14903f6a`).

Roda a cada 4h; dá pra disparar na mão em *Actions → Run workflow*.

## Plano B (se o token for bloqueado)
Se a UFOP usar login via SSO e o `token.php` não funcionar: pegue o token pelo app Moodle Mobile (ou pelo cookie de sessão + `lib/ajax/service.php`, que aceita a mesma função `core_calendar_get_action_events_by_timesort`). Me chama que eu adapto.

## Notas
- Disciplina é extraída do código no nome do curso (`BCC203`, `MTM112`...). Códigos novos viram opção nova no select sozinhos.
- Para provas presenciais (que não estão no Moodle), adicione linhas manuais sem `Moodle ID`: o script ignora.
