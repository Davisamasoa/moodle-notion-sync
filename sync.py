#!/usr/bin/env python3
"""
Sincroniza pendências do Moodle (UFOP) -> database "Pendências Moodle" no Notion.

Só usa a stdlib. Variáveis de ambiente:
  MOODLE_URL       ex.: https://moodlepresencial.ufop.br  (sem barra no final)
  MOODLE_TOKEN     token do serviço moodle_mobile_app (veja README)
  NOTION_TOKEN     secret da integração interna do Notion
  NOTION_DB_ID     id do database (padrão: o já criado)
  DRY_RUN=1        só mostra o que faria, sem escrever no Notion
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

MOODLE_URL = os.environ.get("MOODLE_URL", "").rstrip("/")
MOODLE_TOKEN = os.environ.get("MOODLE_TOKEN", "")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_DB_ID = os.environ.get("NOTION_DB_ID", "41cb47e9b6d181859d60cd9e14903f6a")
DRY_RUN = os.environ.get("DRY_RUN") == "1"

BRT = timezone(timedelta(hours=-3))
LOOKBACK_DAYS = 14  # também traz atrasadas recentes

TIPOS = {"assign": "Tarefa", "quiz": "Questionário", "forum": "Fórum"}
COURSE_CODE = re.compile(r"\b([A-Z]{3}\s?\d{3})\b")


# ---------------------------------------------------------------- HTTP

def _request(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"{e.code} {url}: {e.read().decode()[:500]}") from None
    raise RuntimeError(f"falhou após retries: {url}")


# ---------------------------------------------------------------- Moodle

def moodle(function, **params):
    body = {"wstoken": MOODLE_TOKEN, "wsfunction": function, "moodlewsrestformat": "json", **params}
    res = _request(
        f"{MOODLE_URL}/webservice/rest/server.php",
        data=urllib.parse.urlencode(body).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if isinstance(res, dict) and res.get("exception"):
        raise RuntimeError(f"Moodle {function}: {res.get('message')}")
    return res


def fetch_moodle_events():
    """Eventos 'de ação' = coisas que ainda pedem algo de você (entregar, responder...)."""
    since = int((datetime.now(BRT) - timedelta(days=LOOKBACK_DAYS)).timestamp())
    events, after = [], 0
    while True:
        params = {"timesortfrom": since, "limitnum": 50}
        if after:
            params["aftereventid"] = after
        res = moodle("core_calendar_get_action_events_by_timesort", **params)
        batch = res.get("events", [])
        events.extend(batch)
        if len(batch) < 50:
            return events
        after = batch[-1]["id"]


def disciplina(course):
    for field in ("shortname", "fullname", "idnumber"):
        m = COURSE_CODE.search((course or {}).get(field, "") or "")
        if m:
            return m.group(1).replace(" ", "")
    return ((course or {}).get("shortname") or "Outra")[:100]


# ---------------------------------------------------------------- Notion

def notion(method, path, payload=None):
    return _request(
        f"https://api.notion.com/v1{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        method=method,
    )


def existing_pages():
    """{moodle_id: {page_id, status, prazo}}"""
    out, cursor = {}, None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        res = notion("POST", f"/databases/{NOTION_DB_ID}/query", body)
        for p in res["results"]:
            props = p["properties"]
            mid = props.get("Moodle ID", {}).get("number")
            if mid is None:
                continue
            out[int(mid)] = {
                "page_id": p["id"],
                "status": ((props.get("Status") or {}).get("status") or {}).get("name"),
                "prazo": ((props.get("Prazo") or {}).get("date") or {}).get("start"),
            }
        if not res.get("has_more"):
            return out
        cursor = res["next_cursor"]


def props_for(ev):
    due = datetime.fromtimestamp(ev["timesort"], BRT).isoformat()
    name = ev.get("activityname") or ev.get("name") or "Sem nome"
    return {
        "Nome": {"title": [{"text": {"content": name[:2000]}}]},
        "Disciplina": {"select": {"name": disciplina(ev.get("course"))}},
        "Prazo": {"date": {"start": due}},
        "Tipo": {"select": {"name": TIPOS.get(ev.get("modulename"), "Outro")}},
        "Link": {"url": ev.get("url") or None},
        "Moodle ID": {"number": ev["id"]},
    }


# ---------------------------------------------------------------- main

def main():
    missing = [k for k in ("MOODLE_URL", "MOODLE_TOKEN", "NOTION_TOKEN") if not os.environ.get(k)]
    if missing:
        sys.exit(f"Faltando variáveis: {', '.join(missing)}")

    events = fetch_moodle_events()
    pages = existing_pages()
    seen = set()
    created = updated = done = 0

    for ev in events:
        seen.add(ev["id"])
        props = props_for(ev)
        page = pages.get(ev["id"])
        if page is None:
            print(f"+ {props['Disciplina']['select']['name']}: {props['Nome']['title'][0]['text']['content']}")
            if not DRY_RUN:
                props["Status"] = {"status": {"name": "A fazer"}}
                notion("POST", "/pages", {"parent": {"database_id": NOTION_DB_ID}, "properties": props})
            created += 1
        else:
            # Atualiza dados do Moodle, nunca mexe no Status que você marcou
            if not DRY_RUN:
                notion("PATCH", f"/pages/{page['page_id']}", {"properties": props})
            updated += 1

    # Sumiu da lista de ações do Moodle antes do prazo => provavelmente você entregou
    now = datetime.now(BRT)
    for mid, page in pages.items():
        if mid in seen or page["status"] == "Entregue" or not page["prazo"]:
            continue
        prazo = datetime.fromisoformat(page["prazo"])
        if prazo.tzinfo is None:
            prazo = prazo.replace(tzinfo=BRT)
        if prazo > now:
            print(f"✓ marcando como Entregue: Moodle ID {mid}")
            if not DRY_RUN:
                notion("PATCH", f"/pages/{page['page_id']}",
                       {"properties": {"Status": {"status": {"name": "Entregue"}}}})
            done += 1

    print(f"{len(events)} eventos | {created} novos | {updated} atualizados | {done} entregues"
          + (" (dry run)" if DRY_RUN else ""))


if __name__ == "__main__":
    main()
