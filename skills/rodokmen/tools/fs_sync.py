"""Opakovatelná offline příprava synchronizace FamilySearch. Síť obstarává fs_prohlizec.js.

snapshot-import SOUBOR; diff [SNAPSHOT]; map PLAN; log VYSLEDEK --plan PLAN.
Pracovní snapshoty a plány nejsou dokladem. Do dat se zapisují pouze ID a deník změn.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import runpy
import sys
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gedcom_export as ged
import pribuzni
import velka_rodina as vr
import vetve
import web_pohledy as wp
import zapis

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://gedcomx.org/"
SCHEMA = "rodokmen.fs-"
PID = re.compile(r"[A-Z0-9]{4}-[A-Z0-9]{2,4}")
FACTS = {"*": "Birth", "†": "Death", "pokřtěn": "Christening", "pokřtěna": "Christening", "×": "Marriage",
         "pohřben": "Burial", "pohřbena": "Burial", "pohřeb": "Burial"}
KINDS = {"Birth": "N", "Christening": "N", "Death": "Z", "Burial": "Z", "Marriage": "O"}
MONTHS = "january february march april may june july august september october november december".split()
CZ_MONTHS = "ledna unora brezna dubna kvetna cervna cervence srpna zari rijna listopadu prosince".split()
DE_MONTHS = "januar februar marz april mai juni juli august september oktober november dezember".split()
BURIAL = r"\b(?:pohreb\w*|pohrben\w*|pochov\w*|pochowan\w*|begraben|begrab\.?|begrabnis\w*|beerdigung|sepult\w*|sep\.|burial|buried)"
DEATH = r"\b(?:zemr\.|(?:umrti|zemrel[ao]?|zemreni|zesnul[ao]?|obiit|gestorben|sterbetag|death|died)\b)"
EVENT_DATE = re.compile(r"(?<![\d\[?])(\d{1,2})\.\s*(?:(\d{1,2})\.|([a-z]+))"
                        r"(?:\s*(\d{4}))?(?!\d|\s*\?)")


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        if default is None:
            raise
        return default


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def save_json(path, obj):
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


def digest(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def url_key(url):
    """Sjednoť známé adresy téhož snímku; query (Matricula ?pg=) určuje snímek."""
    p = urlsplit(url or "")
    scheme, host, path = p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/")
    if host == "data.matricula-online.eu":
        scheme = "https"
        path = re.sub(r"^/(en|de|cs|sk|pl)(?=/)", "", path)
        # Matricula používá v signaturách čárky; staré citace je kódují dvakrát.
        path = re.sub(r"%(?:25)*2c", ",", path, flags=re.I)
        path = re.sub(r"%(?:25)*2f", "%2F", path, flags=re.I)
    if host in ("familysearch.org", "www.familysearch.org") and re.fullmatch(
            r"/ark:/61903/(?:1:1|3:1):[A-Z0-9-]+", path):
        scheme, host = "https", "familysearch.org"
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not k.startswith("utm_")]
    return urlunsplit((scheme, host, path, urlencode(sorted(query)), ""))


def image_url(url):
    p = urlsplit(url or "")
    return bool(p.scheme in ("http", "https") and p.netloc)


def date_key(value):
    """Přesné datum v GEDCOM X, češtině, angličtině nebo GEDCOMu; odhady nepřijímá."""
    if isinstance(value, dict):
        return date_key(value.get("formal") or value.get("original"))
    text = (value or "").strip()
    if re.fullmatch(r"\+?\d{4}(?:-\d{2}(?:-\d{2})?)?", text):
        result = "+" + text.lstrip("+")
    else:
        m = re.fullmatch(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", text)
        if m:
            d, mo, y = map(int, m.groups())
            result = f"+{y:04d}-{mo:02d}-{d:02d}"
        else:
            m = re.fullmatch(r"(?:(\d{1,2})\s+)?([A-Za-z]+)\s+(\d{4})", text)
            if not m:
                return None
            d, mo, y = m.groups()
            mo = next((i + 1 for i, name in enumerate(MONTHS) if mo.lower() in (name, name[:3])), None)
            if not mo:
                return None
            result = f"+{int(y):04d}-{mo:02d}" + (f"-{int(d):02d}" if d else "")
    try:
        dt.date.fromisoformat(result[1:] + {5: "-01-01", 8: "-01", 11: ""}[len(result)])
    except (ValueError, KeyError):
        return None
    return result


def remote_name(p):
    return next((f.get("fullText", "") for n in p.get("names", []) for f in n.get("nameForms", [])
                 if f.get("fullText")), p.get("display", {}).get("name", ""))


def date_refines(exact, previous):
    """Pouze zpřesnění celým dnem, nikdy odlišný rok/měsíc ani časová mez."""
    if not re.fullmatch(r"\+\d{4}-\d{2}-\d{2}", exact or "") or not date_key(exact):
        return False
    if not previous:
        return True
    old = date_key(previous)
    if old:
        return len(old) < len(exact) and exact.startswith(old + "-")
    text = previous.get("formal") or previous.get("original", "")
    about = re.fullmatch(r"A\+(\d{4})", text) or re.fullmatch(
        r"(?:about|abt\.?|circa|ca\.?|asi)\s+(\d{4})", text, re.I)
    return bool(about and exact[1:5] == about[1])


def name_key(name):
    words = wp.fold(re.sub(r"\([^)]*\)", "", name or "")).split()
    return (pribuzni.first_key(" ".join(words)), " ".join(words[1:]))


def rel_pairs(snapshot):
    pairs = set()
    for r in snapshot.get("relationships", []):
        if r.get("type") == BASE + "ParentChild":
            pairs.add((r.get("person1", {}).get("resourceId"), r.get("person2", {}).get("resourceId")))
    for r in snapshot.get("childAndParentsRelationships", []):
        child = r.get("child", {}).get("resourceId")
        for role in ("father", "mother"):
            if r.get(role, {}).get("resourceId"):
                pairs.add((r[role]["resourceId"], child))
    # Děti zesnulých přečtené volbou neighbours (jen k dohledání ID).
    for parent, kids in (snapshot.get("children") or {}).items():
        pairs.update((parent, kid) for kid in kids)
    return pairs


def couple_pairs(snapshot):
    return {frozenset((r.get("person1", {}).get("resourceId"), r.get("person2", {}).get("resourceId")))
            for r in snapshot.get("relationships", []) if r.get("type") == BASE + "Couple"}


def family_links(p, local, pairs, couples):
    """FS osoby navázané na namapovaného rodiče, manžela nebo dítě místní osoby: {FS ID: druh vazby}."""
    links = {}
    fs_of = lambda keys: {local[x].get("fs") for x in keys if x in local} - {None}
    for par in fs_of(p.get("parents", [])):
        links.update({b: "rodič" for a, b in pairs if a == par})
    # Citace FamilySearch u osoby v GEDCOMu (MyHeritage) je jen cizí odkaz: vazba pro revizi, nikdy automatika.
    for cited in p.get("fs_cited", []):
        links.setdefault(cited, "citace")
    for sp in fs_of(p.get("spouses", [])):
        for pair in couples:
            if sp in pair and len(pair) == 2:
                links.setdefault(next(iter(pair - {sp})), "manžel")
    me = next((k for k, v in local.items() if v is p), None)
    children = [k for k, v in local.items() if me in v.get("parents", [])]
    for child in fs_of(children):
        for a, b in pairs:
            if b == child:
                links.setdefault(a, "dítě")
    links.pop(None, None)
    return links


def ged_citations(path):
    """{GEDCOM ID: {(jméno, FS ID)}} z citací „entry for <jméno>, person ID XXXX-XXX“ (MyHeritage)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"\r?\n\d+ CONC ", "", text)
    text = re.sub(r"\r?\n\d+ CONT ", " ", text)
    out, cur = {}, None
    for line in text.splitlines():
        if line.startswith("0 "):
            m = re.match(r"0 (@[^@]+@) INDI", line)
            cur = m.group(1) if m else None
            continue
        if cur:
            for name, pid in re.findall(r"entry for ([^,<]+), person ID ([A-Z0-9]{4}-[A-Z0-9]{2,4})", line):
                out.setdefault(cur, set()).add((name.strip(), pid))
    return out


def remote_birth(r):
    return next((date_key(f.get("date")) for f in r.get("facts", []) if f.get("type") == BASE + "Birth"
                 and date_key(f.get("date"))), None)


def birth_year_match(local_birth, fs_birth):
    """Přesná data se musí shodovat celá; je-li některé jen rok či měsíc, stačí stejný rok."""
    if not local_birth or not fs_birth:
        return False
    if len(local_birth) == len(fs_birth) == 11:
        return local_birth == fs_birth
    return local_birth[:5] == fs_birth[:5]


def loose_name(name):
    """Křestní jméno přes skupiny jmen a kmen příjmení (Urbanová = Urban, Nováková = Novák)."""
    words = wp.fold(re.sub(r"\([^)]*\)", "", name or "")).split()
    if not words:
        return ("", "")
    stem = words[-1] if len(words) > 1 else ""
    for end in ("ova", "a", "y", "i"):
        if stem.endswith(end) and len(stem) > len(end) + 2:
            stem = stem[: -len(end)]
            break
    return (pribuzni.first_key(words[0]), stem)


def eligible(p):
    return p.get("st") == "doc" and p.get("living") is False


def item(kind, pid, evidence, **values):
    out = dict(kind=kind, pid=pid, st="doc", living=False, **values)
    out.update(image=evidence["image"], record=evidence.get("record", ""),
               reason=evidence["reason"] + " " + evidence["image"])
    out["id"] = digest(out)
    return out


def relation_priorities(local):
    """Blízkost jen po rodičích a dětech, nikdy přes partnera."""
    direct = {key for key, p in local.items() if any(g == "kekule" for g, k in p.get("keys", []))}
    direct_parents = {par for key in direct for par in local[key].get("parents", [])}
    close = {key for key, p in local.items() if set(p.get("parents", [])) & (direct | direct_parents)}
    return {key: 0 if key in direct else 1 if key in close else 2 for key in local}


def is_close(rank, key, closeness, threshold):
    """Bez hranice (výchozí od 20. 11. 2026) se řeší všichni; s hranicí jen blízká rodina."""
    if threshold is None:
        return True
    # Známou rodinu přiženěných nepovýší příznivá hodnota z FS na blízkou rodinu.
    close = rank < 2 or (key is None and closeness is not None and closeness <= threshold)
    return close and not (closeness is not None and closeness > threshold)


def task_rows(snapshot, local, priorities, threshold):
    raw = snapshot.get("tasks_raw", snapshot.get("tasks", []))
    rows = raw if isinstance(raw, list) else next((raw[k] for k in ("personSummaries", "summaries", "opportunities")
                                                 if isinstance(raw, dict) and isinstance(raw.get(k), list)), None)
    if rows is None:
        return [], False
    by_fs = {p["fs"]: key for key, p in local.items() if p.get("fs")}
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        person = row.get("person") if isinstance(row.get("person"), dict) else {}
        pid = row.get("personId") or person.get("id") or row.get("id")
        if not isinstance(pid, str) or not re.fullmatch(r"[A-Z0-9]{4}-[A-Z0-9]{2,4}", pid):
            continue
        key = by_fs.get(pid)
        name = local[key]["name"] if key else (row.get("name") or person.get("name")
                or remote_name(snapshot.get("persons", {}).get(pid, {})) or "jméno nenačteno")
        try:
            closeness = float(row.get("closeness"))
            if not 0 <= closeness < float("inf"):
                closeness = None
        except (ValueError, TypeError):
            closeness = None
        rank = priorities.get(key, 3)
        close = is_close(rank, key, closeness, threshold)
        hints = row.get("recordTypes") or (row.get("opportunities") if isinstance(row.get("opportunities"), dict) else row)
        for typ in ("NEW_PERSON", "NEW_SOURCE", "NEW_CONCLUSION", "OTHER"):
            values = hints.get(typ)
            if values is None:
                continue
            values = values if isinstance(values, list) else [values]
            records = [v if isinstance(v, str) else v.get("recordId") or v.get("id")
                       for v in values if isinstance(v, (str, dict))]
            if not any(records):
                continue
            result.append(dict(fs=pid, name=name, local=key, closeness=closeness,
                               relation=("přímá linie", "sourozenec nebo dítě přímé linie", "ostatní", "místně neurčeno")[rank],
                               priority=rank, hint_type=typ, record_ids=[r for r in records if r], close=close))
    result.sort(key=lambda t: (t["priority"], t["closeness"] if t["closeness"] is not None else float("inf"),
                               t["name"], t["fs"], t["hint_type"]))
    # Neznámá struktura se nesmí vydávat za prázdný seznam úkolů.
    return result, bool(snapshot.get("tasks_read")) and (not rows or bool(result))


def task_closeness(snapshot):
    raw = snapshot.get("tasks_raw", snapshot.get("tasks", []))
    rows = raw if isinstance(raw, list) else next((raw[k] for k in ("personSummaries", "summaries", "opportunities")
                                                 if isinstance(raw, dict) and isinstance(raw.get(k), list)), [])
    out = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("personId"), str):
            try:
                value = float(row.get("closeness"))
            except (TypeError, ValueError):
                continue
            if 0 <= value < float("inf"):
                out[row["personId"]] = value
    return out


def myheritage_rows(snapshot, local, priorities, threshold):
    """Shody MyHeritage jsou jen stopa. Řazení a hranice blízkosti stejně jako u úkolů."""
    read = snapshot.get("myheritage") or {}
    by_fs = {p["fs"]: key for key, p in local.items() if p.get("fs")}
    by_fs.update({new: by_fs[old] for old, new in (snapshot.get("merged") or {}).items()
                  if new and old in by_fs and new not in by_fs})
    closeness = task_closeness(snapshot)
    rows = []
    for pid, hint in read.items():
        if not isinstance(hint, dict) or not isinstance(hint.get("totalHints"), int) or hint["totalHints"] <= 0:
            continue
        key = by_fs.get(pid)
        details = [d for d in hint.get("hintDetails") or [] if isinstance(d, dict) and isinstance(d.get("name"), str)]
        link = hint.get("link") if isinstance(hint.get("link"), str) else ""
        link = link if re.match(r"https://www\.myheritage\.[a-z.]+/", link) else None
        rank = priorities.get(key, 3)
        near = closeness.get(pid)
        close = is_close(rank, key, near, threshold)
        record_adds = [d["name"] for d in details if d.get("type") == "record"]
        rows.append(dict(fs=pid, name=local[key]["name"] if key else
                         (remote_name(snapshot.get("persons", {}).get(pid, {})) or "jméno nenačteno"),
                         local=key, closeness=near, priority=rank, close=close,
                         relation=("přímá linie", "sourozenec nebo dítě přímé linie", "ostatní", "místně neurčeno")[rank],
                         total=hint["totalHints"], record=bool(record_adds), record_adds=record_adds,
                         other_adds=[d["name"] for d in details if d.get("type") != "record"],
                         factors=hint.get("factorsDescription") or "", link=link))
    rows.sort(key=lambda r: (r["priority"], r["closeness"] if r["closeness"] is not None else float("inf"),
                             r["name"], r["fs"]))
    # Nečtené = naše nežijící osoby s FS ID bez odpovědi (i mimo omezený běh), ne osoby z úkolů FS.
    merged = snapshot.get("merged") or {}
    ours = {merged.get(p["fs"]) or p["fs"] for p in local.values() if p.get("fs") and p.get("living") is False}
    summary = dict(read=len(read), with_hints=len(rows),
                   zero=sum(1 for h in read.values() if isinstance(h, dict) and h.get("totalHints") == 0),
                   unread=sum(1 for pid in ours if pid not in read))
    return rows, summary


def cached_matches(snapshot, max_age_days, now=None, field="record_matches"):
    if snapshot.get("schema") != SCHEMA + "snapshot.v1" or max_age_days < 0:
        raise ValueError("Neplatný snapshot nebo stáří shod")
    now = now or dt.datetime.now(dt.timezone.utc)
    out = {}
    for pid, data in (snapshot.get(field) or {}).items():
        stamp = (snapshot.get(field + "_read") or {}).get(pid, snapshot.get("captured_at"))
        try:
            read_at = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            age = now - read_at
        except (AttributeError, TypeError, ValueError):
            continue
        if data is not None and dt.timedelta(0) <= age < dt.timedelta(days=max_age_days):
            out[pid] = dict(data=data, read_at=stamp)
    return out


def build_plan(local, snapshot, ledger=None, task_closeness=None):
    """Čistý diff. Konflikty nikdy neobsahují instrukci k přepsání či odpojení na FS."""
    people = snapshot["persons"]
    pairs = rel_pairs(snapshot)
    plan = dict(schema=SCHEMA + "plan.v1", reviewed=False, snapshot_at=snapshot.get("captured_at"),
                snapshot_complete=snapshot.get("complete", False), mappings=[], missing_ids=[], missing_ids_other=[], items=[],
                conflicts=[], unread=[], manual=[], id_changes=[], tasks_raw=snapshot.get("tasks_raw"),
                snapshot_errors=snapshot.get("errors", []), task_closeness=task_closeness,
                record_matches=snapshot.get("record_matches", {}))
    plan["mapping_review"] = []
    # Kandidáti na ID: čtené osoby i sousedé (relatives); sousedé se jinak neporovnávají.
    pool = {**(snapshot.get("relatives") or {}), **people}
    couples = couple_pairs(snapshot)
    mapped = {p["fs"] for p in local.values() if p.get("fs")}
    priorities = relation_priorities(local)
    plan["tasks"], plan["tasks_read"] = task_rows(snapshot, local, priorities, task_closeness)
    plan["tasks_close"] = [t for t in plan["tasks"] if t["close"]]
    plan["tasks_distant"] = [t for t in plan["tasks"] if not t["close"]]
    plan["myheritage"], plan["myheritage_summary"] = myheritage_rows(snapshot, local, priorities, task_closeness)
    done = ledger or {}
    for key, p in sorted(local.items()):
        if p.get("living") is not False:
            continue
        pid = p.get("fs")
        if p.get("mapping_conflicts"):
            plan["conflicts"].append(dict(local=key, fs=pid, reason="Různá místní FS ID", ids=p["mapping_conflicts"]))
            continue
        if not pid:
            # Jméno + přesné narození + známý rodič nebo manžel. Samotné pořadí v ancestry nestačí.
            links = family_links(p, local, pairs, couples)
            strict = [r for r in pool.values() if r.get("living") is False and r["id"] not in mapped
                      and name_key(remote_name(r)) == name_key(p["name"])
                      and re.fullmatch(r"\+\d{4}-\d{2}-\d{2}", p.get("birth") or "") and any(f.get("type") == BASE + "Birth"
                          and date_key(f.get("date")) == p["birth"] for f in r.get("facts", []))
                      and links.get(r["id"]) in ("rodič", "manžel")]
            # Slabší shoda (jen rok narození, ženský tvar příjmení, vazba přes dítě) jde jen k ruční revizi.
            loose = [] if strict else [r for r in pool.values() if r.get("living") is False
                                       and r["id"] not in mapped and r["id"] in links
                                       and loose_name(remote_name(r)) == loose_name(p["name"])
                                       and birth_year_match(p.get("birth"), remote_birth(r))]
            if len(strict) == 1:
                plan["mappings"].extend(dict(local=key, group=g, key=k, fs=strict[0]["id"])
                                        for g, k in p["keys"])
            elif len(loose) == 1:
                r = loose[0]
                plan["mapping_review"].append(dict(local=key, name=p["name"], birth=p.get("birth"), priority=priorities[key],
                                                   fs=r["id"], fs_name=remote_name(r), fs_birth=remote_birth(r),
                                                   link=links[r["id"]], keys=[list(x) for x in p["keys"]]))
            else:
                group = "missing_ids" if p.get("st") == "doc" and (p.get("records") or p.get("sources")) else "missing_ids_other"
                plan[group].append(dict(local=key, name=p["name"], priority=priorities[key],
                                        candidates=sorted(r["id"] for r in strict or loose)))
            continue
        if pid in snapshot.get("merged", {}):
            plan["id_changes"].append(dict(local=key, name=p["name"], old=pid, new=snapshot["merged"][pid],
                reason="ID změněno, aktualizujte data/familysearch.json po ověření jména, narození a rodiče"))
            continue
        r = people.get(pid)
        if not r:
            plan["unread"].append(dict(local=key, fs=pid, reason="Osoba není ve snapshotu"))
            continue
        if r.get("living") is not False:
            plan["unread"].append(dict(local=key, fs=pid, reason="FS nepotvrdil zemřelou osobu"))
            continue
        # Doplň i chybějící druhý klíč již známé osoby (Kekulé / GEDCOM / poznámka).
        plan["mappings"].extend(dict(local=key, group=g, key=k, fs=pid) for g, k in p.get("unmapped_keys", []))
        if not eligible(p):
            continue
        for f in p.get("facts", []):
            if not image_url(f.get("image")) or not f.get("reason") or not date_key(f.get("date")):
                continue
            extra, target = {}, r
            if f["type"] == "Marriage":
                spouse = local.get(f.get("spouse"), {})
                spid = spouse.get("fs")
                if (not eligible(spouse) or spouse.get("mapping_conflicts") or spid == pid
                        or people.get(spid, {}).get("living") is not False):
                    plan["manual"].append(dict(local=key, reason="Sňatek bez ověřeného partnera",
                                               date=f["date"], record=f.get("record"), spouse=spid))
                    continue
                copies = [rel for rel in snapshot.get("relationships", []) if rel.get("type") == BASE + "Couple"
                          and {rel.get("person1", {}).get("resourceId"), rel.get("person2", {}).get("resourceId")} == {pid, spid}]
                if not copies:
                    if pid not in snapshot.get("relationships_read", list(people) if snapshot.get("complete") else []):
                        plan["unread"].append(dict(fs=pid, reason="Vztahy nejsou načtené"))
                        continue
                    plan["items"].append(item("couple", pid, f, type="Marriage", date=f["date"], spouse=spid))
                    plan["items"].append(item("fact", pid, f, type="Marriage", date=f["date"], spouse=spid))
                    continue
                # Tentýž vztah může být nejdřív načten bez faktů přes rodiče dítěte.
                facts = {digest(v): v for rel in copies for v in rel.get("facts", [])}
                # Některé odpovědi obsahují jen stručnou kopii faktu bez ID.
                # Odstraň ji pouze tehdy, když všechna její pole odpovídají úplnému faktu.
                target = dict(facts=[v for v in facts.values() if v.get("id") or not any(
                    other.get("id") and all(other.get(k) == value for k, value in v.items())
                    for other in facts.values())])
                extra = dict(spouse=spid)
                relationship_ids = {rel.get("id") for rel in copies}
                if len(relationship_ids) == 1 and None not in relationship_ids:
                    extra["relationship_id"] = next(iter(relationship_ids))
            old = [v for v in target.get("facts", []) if v.get("type") == BASE + f["type"]]
            if any(date_key(v.get("date")) == f["date"] for v in old):
                continue
            if (len(old) == 1 and old[0].get("id") and date_refines(f["date"], old[0].get("date"))
                    and (f["type"] != "Marriage" or extra.get("relationship_id"))):
                plan["items"].append(item("fact-update", pid, f, type=f["type"], date=f["date"],
                                          fact_id=old[0]["id"], previous_date=old[0].get("date", {}), **extra))
            elif old:
                plan["conflicts"].append(dict(local=key, fs=pid, type=f["type"], local_date=f["date"],
                                              fs_dates=[v.get("date", {}) for v in old]))
            else:
                plan["items"].append(item("fact", pid, f, type=f["type"], date=f["date"], **extra))
        if pid not in snapshot.get("sources", {}):
            plan["unread"].append(dict(fs=pid, reason="Zdroje nejsou načtené"))
        else:
            urls = {url_key(s.get("about")) for s in snapshot["sources"][pid]}
            for s in p.get("sources", []):
                if image_url(s.get("url")) and url_key(s["url"]) not in urls:
                    ev = dict(image=s["url"], record=s.get("record", ""), reason=s["reason"])
                    plan["items"].append(item("source", pid, ev, url=s["url"], title=s["title"]))
        for parent_key in p.get("parents", []):
            parent = local.get(parent_key, {})
            parid = parent.get("fs")
            if not parid or (parid, pid) in pairs or not eligible(parent):
                continue
            if people.get(parid, {}).get("living") is not False or parent.get("mapping_conflicts"):
                continue
            # Bez úplného čtení vztahů nelze říci, že rodič chybí.
            if pid not in snapshot.get("relationships_read", list(people) if snapshot.get("complete") else []):
                plan["unread"].append(dict(fs=pid, reason="Vztahy nejsou načtené"))
                continue
            other = [a for a, b in pairs if b == pid and a != parid]
            ev = p.get("relation_evidence", {}).get(parent_key)
            if not ev or not image_url(ev.get("image")):
                plan["manual"].append(dict(local=key, parent=parent_key, reason="Vazba vyžaduje kontrolu dokladu"))
                continue
            # Dva jiní rodiče nebo jiný rodič stejného pohlaví: jen nahlásit.
            sex = people[parid].get("gender", {}).get("type")
            if len(other) >= 2 or any(not sex or not people.get(a, {}).get("gender", {}).get("type")
                                     or people[a]["gender"]["type"] == sex for a in other):
                plan["conflicts"].append(dict(local=key, parent=parid, fs_parents=other))
                continue
            plan["items"].append(item("relationship", pid, ev, parent=parid, child=pid))
    unique = {i["id"]: i for i in plan["items"]}
    for group in ("missing_ids", "missing_ids_other", "mapping_review"):
        plan[group].sort(key=lambda p: (p["priority"], p["name"], p["local"]))
    plan["items"] = [i for k, i in unique.items() if done.get(k, {}).get("status") not in ("applied", "skipped")]
    plan["id"] = digest(plan)
    return plan


def patch_value(text, key, value):
    """Změň jednu hodnotu JSON. Stejný parser a vkládání jako tools/zapis.py."""
    return zapis.zapis_text(text, "fs_sync", key, value)[0]


def write_mappings(path, mappings):
    """Ulož mapování do data/familysearch.json pod zámkem zapis.py."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zapis.zamceno(path):
        _write_mappings(path, mappings)


def _write_mappings(path, mappings):
    text = path.read_text(encoding="utf-8-sig") if path.exists() else '{\n "kekule": {},\n "ged": {}\n}\n'
    for m in mappings:
        group, key, pid = m["group"], str(m["key"]), m["fs"]
        if group not in ("kekule", "ged") or not PID.fullmatch(pid):
            raise ValueError("Neplatné mapování ID")
        data = json.loads(text)
        old = data.get(group, {}).get(key)
        if old and old != pid:
            raise ValueError(f"konflikt {group}/{key}: {old} × {pid}")
        if old == pid:
            continue
        if group not in data:
            text = patch_value(text, group, {})
        _, start, end = next(p for p in zapis.polozky(text) if p[0] == group)
        nested = text[start:end]
        # Zachovej odsazení i cizí mezery uvnitř ostatních položek.
        nested = patch_value(nested, key, pid).rstrip("\n")
        text = text[:start] + nested + text[end:]
    if not path.exists() or path.read_text(encoding="utf-8-sig") != text:
        zapis.prepis(path, text)


def log_result(result, plan, ledger_path, research_log):
    if result.get("schema") != SCHEMA + "result.v1" or result.get("plan_id") != plan["id"]:
        raise ValueError("Výsledek nepatří k plánu")
    allowed = {i["id"]: i for i in plan["items"]}
    entries = result.get("items", [])
    if any(e.get("id") not in allowed for e in entries):
        raise ValueError("Výsledek obsahuje položku mimo plán")
    ledger_path, research_log = Path(ledger_path), Path(research_log)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    # Stav i deník čte, mění a přepisuje pod zámky zapis.py (vždy v tomto pořadí, aby se vlákna nezablokovala).
    with zapis.zamceno(ledger_path), zapis.zamceno(research_log):
        _log_result(result, plan, allowed, entries, ledger_path, research_log)


def _log_result(result, plan, allowed, entries, ledger_path, research_log):
    text = ledger_path.read_text(encoding="utf-8-sig") if ledger_path.exists() else "{}\n"
    successful = [e for e in entries if e.get("status") in ("applied", "skipped")]
    for e in successful:
        if e["id"] in json.loads(text):
            continue
        source = allowed[e["id"]]
        text = patch_value(text, e["id"], dict(status=e["status"], plan=plan["id"], kind=source["kind"],
                                              fs=source["pid"], image=source["image"]))
    # Marker dovolí zopakovat i běh přerušený mezi zápisem stavu a deníku.
    marker = "<!-- fs-sync:" + digest(result) + " -->"
    log = research_log.read_text(encoding="utf-8") if research_log.exists() else ""
    if successful and marker not in log:
        lines = [f"\n### FamilySearch synchronizace ({dt.date.today().isoformat()})", marker,
                 f"Plán {plan['id']}: {len(successful)} potvrzených položek."]
        for e in successful:
            source = allowed[e["id"]]
            lines.append(f"- {e['status']}: {source['kind']} {source['pid']}. {source['reason']}")
        zapis.prepis(research_log, log.rstrip() + "\n" + "\n".join(lines) + "\n")
    if not ledger_path.exists() or ledger_path.read_text(encoding="utf-8-sig") != text:
        zapis.prepis(ledger_path, text)


def evidence(record):
    return dict(image=record.get("odkaz", ""), reason=record.get("nazev", "Čtený zápis"), record=record["klic"])


def event_dates(text, reference):
    """Čti jen data s označením události; nejasný den nikdy nedoplňuj z †."""
    result = {"Death": set(), "Burial": set()}
    # fold() pro jména maže nové řádky i (?), v dokladu je potřebujeme zachovat.
    text = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))

    def dates(part, year):
        found = []
        for m in EVENT_DATE.finditer(part):
            day, month, word, explicit_year = m.groups()
            if word:
                names = next((names for names in (CZ_MONTHS, MONTHS, DE_MONTHS) if word in names), None)
                if names is None:
                    continue
                month = names.index(word) + 1
            # Otazník těsně za datem zneplatní datum, nikoli jiné čtení v zápisu.
            if re.match(r"\s*\(?\?", part[m.end():]):
                continue
            date = date_key(f"{day}. {month}. {explicit_year or year}")
            if date:
                found.append((m, date))
        return found

    for line in re.split(r"[;\n]", text):
        # Běžná hlavička přepisu: [Úmrtí / pohřeb] 1886, 30. března / 1. dubna.
        pair = re.search(r"\[\s*(?:" + DEATH + r")\s*/\s*(?:" + BURIAL + r")\s*\]"
                         r"\s*(?:(\d{4}),\s*)?([^/]+)/(.+)", line)
        if pair:
            year = pair[1] or reference[1:5]
            first = pair[2]
            shared = EVENT_DATE.search(pair[3])
            if re.fullmatch(r"\s*\d{1,2}\.\s*", first) and shared:
                first = first.strip() + " " + pair[3][shared.end(1) + 1:]
            result["Death"].update(date for m, date in dates(first, year))
            result["Burial"].update(date for m, date in dates(pair[3], year))
            continue
        labels = list(re.finditer("(" + DEATH + ")|(" + BURIAL + ")", line))
        nearest = {}
        for match, date in dates(line, reference[1:5]):
            candidates = []
            for label in labels:
                if label.end() <= match.start():
                    between, order = line[label.end():match.start()], 0
                elif match.end() <= label.start():
                    between, order = line[match.end():label.start()], 1
                else:
                    continue
                # Datum musí přiléhat k označení události. Datum narození a datum
                # další osoby ve zbytku věty nejsou údaje tohoto úmrtí či pohřbu.
                if re.fullmatch(r"[\s\[\]:,]*(?:(?:dne|den|byl[ao]?|v noci|am|on|ist|est|honeste|wurde)\s+)*", between):
                    candidates.append((len(between), order, label.start(), "Death" if label[1] else "Burial"))
            if candidates:
                distance, order, position, typ = min(candidates)
                candidate = (distance, order, typ, date)
                if position not in nearest or candidate < nearest[position]:
                    nearest[position] = candidate
        for distance, order, typ, date in nearest.values():
            result[typ].add(date)
    return result


def death_facts(fact, typ, date, record, transcript):
    texts = [record.get("nazev", ""), record.get("shrnuti", ""),
             transcript.get("orig", ""), transcript.get("cs", "")]
    burial = typ == "Burial" or re.search(BURIAL, wp.fold("\n".join(texts + [fact])))
    if not burial:
        return [(typ, date)]
    explicit = {"Death": set(), "Burial": set()}
    transcript_deaths = set()
    for index, text in enumerate(texts[1:], 1):
        for kind, values in event_dates(text, date).items():
            explicit[kind].update(values)
            if index >= 2 and kind == "Death":
                transcript_deaths.update(values)
    transcript_text = wp.fold("\n".join(texts[2:]))
    transcript_burial = re.search(BURIAL, transcript_text)
    if transcript_burial:
        # Obecný název „úmrtí“ ani shrnutí nepřebijí pohřební přepis.
        explicit["Death"] = transcript_deaths
    # Pokud chybí čitelné označené datum pohřbu, datum pohřebního zápisu je pohřeb.
    # Výjimkou je výslovně nejisté datum, např. Urbanův „[4?]“ / „den 1 nebo 4“.
    uncertain = re.search(r"\[[^\]\n]*\d[^\]\n]*\?|\bden\s+\d+\s+nebo\s+\d+",
                          wp.fold("\n".join(texts)))
    mentions_death = re.search(DEATH + r"|\bmrtv[ey]\b", wp.fold("\n".join(texts[1:])))
    burial_record = (typ == "Burial" or re.search(BURIAL, wp.fold(fact + " " + texts[0]))
                     or (transcript_burial and not re.search(DEATH + r"|\bmrtv[ey]\b", transcript_text)))
    if (not explicit["Burial"] and not uncertain and not explicit["Death"]
            and (burial_record or not mentions_death)):
        explicit["Burial"].add(date)
    return [(kind, next(iter(values))) for kind, values in explicit.items() if len(values) == 1]


def backed_facts(p, recs, transcripts=None):
    out = []
    transcripts = transcripts or {}
    for fact in p.get("f", []):
        if "?" in fact or "podle stromu" in fact or "nejist" in fact:
            continue
        m = re.match(r"^(\*|†|×|pokřtěna?|pohřbena?|pohřeb)\s+(\d{1,2}\.\s*\d{1,2}\.\s*\d{4}|\d{4})(?=\s|$)", fact)
        if not m:
            continue
        typ, date = FACTS[m[1]], date_key(m[2])
        if not date:
            continue
        # * před 1784 nerozhodne, zda jde o narození, nebo křest. Vyžaduj výslovné „pokřtěn“.
        if typ == "Birth" and int(date[1:5]) < 1784:
            continue
        for key in p.get("r", []):
            r = recs.get(key, {})
            if r.get("druh") == KINDS[typ] and date_key(r.get("datum")) == date and image_url(r.get("odkaz")):
                events = death_facts(fact, typ, date, r, transcripts.get(key, {})) if typ in ("Death", "Burial") else [(typ, date)]
                out.extend(dict(type=kind, date=value, **evidence(r)) for kind, value in events)
                if typ == "Marriage":
                    out[-1]["text"] = fact
                break
    return list({digest(f): f for f in out}.values())


def load_local(root=ROOT):
    """Čti zdrojová data, nikoli zastarávající vygenerovaný web/public/velka-rodina.json."""
    root = Path(root)
    ns = runpy.run_path(str(root / "data/osoby.py"))
    P, same, side = ns["P"], ns.get("SAME", {}), ns.get("SIDE", [])
    fsmap = read_json(root / "data/familysearch.json", {})
    cfg = read_json(root / "data/web.json").get("velka_rodina", {})
    records = {r["klic"]: r for r in read_json(root / "data/zaznamy.json")}
    transcript_path = root / "data/prepisy.json"
    transcripts = read_json(transcript_path) if transcript_path.exists() else {}
    recs, cites = {}, {}
    if cfg.get("ged"):
        cfg = dict(cfg, ged=str(root / cfg["ged"]),
                   doplnky=str(root / cfg.get("doplnky", "data/doplnky_rodiny.ged")))
        recs = vr.load_tree(cfg, side=side)
        cites = ged_citations(cfg["ged"])
    indi = {i: r for i, r in recs.items() if r["tag"] == "INDI"}
    families = {i: r for i, r in recs.items() if r["tag"] == "FAM"}
    aliases = vr.merge_duplicates(indi, families, cfg)
    A = lambda i: aliases.get(i, i)
    living = vetve.living_map({**indi, **families}, dt.date.today().year)
    overeno = {A(i) for i in cfg.get("overeno", [])}
    # Čísla předků určuje stejný průchod jako ve Velké rodině; SAME sjednotí implex.
    queue, kek = [(A(cfg.get("koren", "@I1@")), 1)], {}
    while queue:
        gid, k = queue.pop(0)
        if gid in kek or gid not in indi:
            continue
        kek[gid] = same.get(k, k)
        for fid in indi[gid]["famc"][:1]:
            f = families.get(fid, {})
            queue += [(x, 2 * k) for x in f.get("husb", [])[:1]] + [(x, 2 * k + 1) for x in f.get("wife", [])[:1]]
    local = {}
    for k, p in P.items():
        if p.get("st") == "unk" or str(p.get("note", "")).startswith("ODPOJENO"):
            continue
        canonical = same.get(k, k)
        if canonical != k:
            continue
        f = backed_facts(p, records, transcripts)
        by = next((x["date"] for x in f if x["type"] == "Birth"), None)
        if not by:
            by = next((date_key(m[1]) for t in p.get("f", [])
                       for m in [re.match(r"^\* (\d{1,2}\.\s*\d{1,2}\.\s*\d{4}|\d{4})(?=\s|$)", t)] if m and "?" not in t), None)
        unknown_age = not re.search(r"\d{4}", p.get("y", "")) and not any(t.startswith("†") for t in p.get("f", []))
        local[f"k:{k}"] = dict(name=p["n"], st=p.get("st"), living=wp.is_living(p, dt.date.today().year) or unknown_age,
                                 birth=by, keys=[["kekule", str(k)]], fs=ged.fs_id(fsmap, k=k, note=p.get("note")),
                                 facts=f, sources=[], parents=[], relation_evidence={}, records=p.get("r", []))
    for alias, canonical in same.items():
        if f"k:{canonical}" in local:
            local[f"k:{canonical}"]["keys"].append(["kekule", str(alias)])
    gid_key = {}
    for gid, r in indi.items():
        k = kek.get(gid)
        key = f"k:{k}" if f"k:{k}" in local else "g:" + gid
        gid_key[gid] = key
        if key not in local:
            facts = [prefix + " " + vr.cz_date(r["ev"][tag][0]) for tag, prefix in
                     (("BIRT", "*"), ("CHR", "pokřtěn"), ("DEAT", "†")) if tag in r["ev"]]
            refs = r.get("zaz", [])
            local[key] = dict(name=r["name"], st="doc" if gid in overeno or refs else "mh", living=living[gid],
                              birth=date_key(r["ev"].get("BIRT", [None])[0]), keys=[], fs=None, facts=[], sources=[],
                              parents=[], relation_evidence={}, records=list(refs), raw_facts=facts)
        local[key]["keys"].append(["ged", gid])
    for alias, canonical in aliases.items():
        if canonical in gid_key:
            local[gid_key[canonical]]["keys"].append(["ged", alias])
    # Stejná logika stránek příbuzných včetně SIDE a _ZAZNAM. Nevytváříme web ani neměníme data.
    page_people = {}
    for gid, r in indi.items():
        p = local[gid_key[gid]]
        page_people[gid] = dict(name=p["name"], by=vr.year_of(r["ev"].get("BIRT", [""])[0]),
                               birth=[vr.cz_date(r["ev"].get("BIRT", [""])[0]), ""],
                               death=[vr.cz_date(r["ev"].get("DEAT", [""])[0]), ""],
                               living=p["living"], st=p["st"], k=kek.get(gid), records=p["records"], parents=[], children=[])
    for f in families.values():
        for child in f["chil"]:
            if child in page_people:
                page_people[child]["parents"] += [x for x in f["husb"] + f["wife"] if x in page_people]
                for par in page_people[child]["parents"]:
                    page_people[par]["children"].append(child)
    pages = pribuzni.pages(dict(people=page_people), side, records, wp.side_keys(side, records))
    for page in pages.values():
        p = local[gid_key[page["id"]]]
        p["records"] = list(dict.fromkeys(p["records"] + page["records"]))
        if page["doc"] and p["st"] == "mh" and p["records"]:
            p["st"] = "doc"
        p["raw_facts"] = p.get("raw_facts", []) + page["facts"]
    for gid, r in indi.items():
        p = local[gid_key[gid]]
        p["parents"] = list(dict.fromkeys(gid_key[x] for fid in r["famc"] for x in
                                         families.get(fid, {}).get("husb", []) + families.get(fid, {}).get("wife", [])
                                         if x in gid_key))
        p["spouses"] = list(dict.fromkeys(p.get("spouses", []) + [gid_key[x] for fid in r.get("fams", []) for x in
                                         families.get(fid, {}).get("husb", []) + families.get(fid, {}).get("wife", [])
                                         if x in gid_key and gid_key[x] != gid_key[gid]]))
        own = [pid for name, pid in sorted(cites.get(gid, ())) if loose_name(name) == loose_name(p["name"])]
        p["fs_cited"] = list(dict.fromkeys(p.get("fs_cited", []) + own))
    for key, p in local.items():
        if key.startswith("k:"):
            k = int(key[2:])
            p["parents"] = [f"k:{same.get(x, x)}" for x in (2*k, 2*k+1) if f"k:{same.get(x, x)}" in local]
            for par in p["parents"]:
                refs = P[k].get("napojeni", {}).get("r", [])
                doc = next((records[x] for x in refs if x in records and image_url(records[x].get("odkaz"))), None)
                if doc:
                    p["relation_evidence"][par] = evidence(doc)
        p["keys"] = [list(v) for v in dict.fromkeys(tuple(x) for x in p["keys"])]
        ids = {fsmap.get(g, {}).get(k) for g, k in p["keys"]} - {None}
        if p.get("fs"):
            ids.add(p["fs"])
        p["fs"] = next(iter(ids)) if len(ids) == 1 else p.get("fs")
        if len(ids) > 1:
            p["mapping_conflicts"] = sorted(ids)
        p["unmapped_keys"] = [[g, k] for g, k in p["keys"] if not fsmap.get(g, {}).get(k)]
        if p.get("raw_facts"):
            p["facts"] = backed_facts(dict(f=p["raw_facts"], r=p["records"]), records, transcripts)
        # Partner patří ke konkrétnímu faktu, nikoli k libovolnému sňatku osoby.
        for f in p["facts"]:
            if f["type"] != "Marriage":
                continue
            named, dated = set(), set()
            for fid in (indi[gid]["fams"] for gid in indi if gid_key[gid] == key):
                for family_id in fid:
                    family = families.get(family_id, {})
                    for partner in family.get("husb", []) + family.get("wife", []):
                        partner_key = gid_key.get(partner)
                        if partner_key and partner_key != key:
                            name = wp.fold(local[partner_key]["name"])
                            if name and name in wp.fold(f["text"]):
                                named.add(partner_key)
                            if date_key(family.get("ev", {}).get("MARR", [None])[0]) == f["date"]:
                                dated.add(partner_key)
            candidates = named & dated if named and dated else named or dated
            if len(candidates) == 1:
                f["spouse"] = next(iter(candidates))
        p["sources"] = [dict(url=records[x]["odkaz"], title=records[x].get("nazev", x), record=x,
                              reason="Zápis přečtený ze snímku") for x in p["records"]
                        if x in records and image_url(records[x].get("odkaz"))]
    # Větve jsou obsažené i mimo komponentu kořene. Načtení ověří, že žádný zakladatel nechybí.
    for branches in read_json(root / "data/vetve.json", {}).values():
        for branch in branches:
            if A(branch["zakladatel"]) not in gid_key:
                raise ValueError("Zakladatel větve chybí: " + branch["zakladatel"])
    return local


def markdown(plan):
    lines = ["# Plán synchronizace FamilySearch", "", f"Snapshot: {plan.get('snapshot_at')}",
             f"Úplný snapshot: {'ano' if plan['snapshot_complete'] else 'ne'}", "",
             f"ID k dohledání: {len(plan['missing_ids'])}; ID k uložení: {len(plan['mappings'])}; "
             f"doložené položky k zápisu: {len(plan['items'])}; rozpory: {len(plan['conflicts'])}; "
             f"úkoly FS: {len(plan['tasks']) if plan['tasks_read'] else 'nezjištěno'}.",
             f"Ostatní bez FS ID: {len(plan['missing_ids_other'])} (seznam pouze v JSON).", "",
             "Konflikty pouze přečti. Pro zápis zkontroluj JSON a nastav reviewed na true."]
    if plan["snapshot_errors"]:
        lines += ["", "Chyby snapshotu: " + "; ".join(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                                                     for v in plan["snapshot_errors"])]
    for field, title in (("missing_ids", "ID k dohledání"), ("mappings", "ID k uložení"),
                         ("mapping_review", "ID ke kontrole (slabší shoda; do mappings jen po kontrole)"), ("items", "Zápisy"),
                         ("conflicts", "Rozpory"), ("unread", "Nenačtené údaje"), ("manual", "Vazby k ověření"),
                         ("id_changes", "Změněná ID"), ("tasks_close", "Úkoly: řešit"),
                         ("tasks_distant", "Úkoly: jen vypsat"), ("record_matches", "Shody záznamů")):
        lines += ["", "## " + title, ""]
        values = plan.get(field, [])
        if isinstance(values, dict):
            values = [dict(fs=k, matches=v) for k, v in values.items()]
        lines += ["- " + json.dumps(v, ensure_ascii=False) for v in values] or ["Žádné."]
    lines += myheritage_markdown(plan)
    return "\n".join(lines) + "\n"


def myheritage_markdown(plan):
    s = plan.get("myheritage_summary") or dict(read=0, with_hints=0, zero=0, unread=0)
    lines = ["", "## Shody MyHeritage", "",
             f"Osob se shodami: {s['with_hints']}; bez shod: {s['zero']}; nečteno: {s['unread']}.",
             "Shoda je jen stopa: k záznamu najdi originál (FamilySearch, archiv), přečti ho na snímku a zapiš "
             "běžným postupem. Stránku shod na MyHeritage otevře uživatel ručně."]
    for title, close in (("Řešit", True), ("Jen vypsat", False)):
        rows = [r for r in plan.get("myheritage", []) if r["close"] is close]
        lines += ["", "### " + title, ""]
        for r in rows:
            where = ", ".join(x for x in (f"`{r['local']}`" if r["local"] else "místně neznámá", "FS " + r["fs"],
                                          r["relation"], f"closeness {r['closeness']:g}" if r["closeness"] is not None else "")
                              if x)
            adds = "; ".join(x for x in ("záznam: " + ", ".join(r["record_adds"]) if r["record_adds"] else "",
                                         "ostatní: " + ", ".join(r["other_adds"]) if r["other_adds"] else "") if x)
            link = f"[stránka shod]({r['link']})" if r["link"] else "odkaz chybí"
            word = "shoda" if r["total"] == 1 else "shody" if 2 <= r["total"] <= 4 else "shod"
            lines.append(f"- **{r['name']}** ({where}): {r['total']} {word}{'; ' + adds if adds else ''}. {link}")
        if not rows:
            lines.append("Žádné.")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snapshot-import").add_argument("file", type=Path)
    d = sub.add_parser("diff")
    d.add_argument("snapshot", type=Path, nargs="?")
    d.add_argument("--task-closeness", type=int, default=None,
                   help="Nejvyšší FS closeness pro řešené úkoly; výchozí bez hranice (řešit všechny, nejbližší první)")
    m = sub.add_parser("map")
    m.add_argument("plan", type=Path)
    l = sub.add_parser("log")
    l.add_argument("result", type=Path)
    l.add_argument("--plan", required=True, type=Path)
    s = sub.add_parser("scope", help="Konfigurace snapshotu včetně ID širší rodiny")
    s.add_argument("--root", help="ID výchozí osoby na FamilySearch pro čtení předků (jinak ID osoby č. 1, pokud je známé)")
    s.add_argument("--max-persons", type=int, default=0, help="0 = bez omezení; nenulové = částečná kontrola")
    s.add_argument("--since", type=Path, help="Převezmi nedávno čtené record-matches z tohoto snapshotu")
    s.add_argument("--matches-max-age-days", type=int, default=7, help="Shody mladší než N dní se znovu nečtou (7)")
    s.add_argument("--myheritage-max-age-days", type=int, default=7,
                   help="S --since: shody MyHeritage mladší než N dní se znovu nečtou (7)")
    s.add_argument("--no-myheritage", action="store_true", help="Shody MyHeritage vůbec nečti")
    s.add_argument("--no-neighbours", action="store_true",
                   help="Nečti sousedy (rodiče, manžele, děti) k dohledání chybějících FS ID")
    s.add_argument("--pace", type=int, default=2000, help="Nejméně ms mezi požadavky (2000; minimum 1100)")
    args = parser.parse_args(argv)
    work = ROOT / "pracovni/fs_sync"
    stamp = dt.date.today().isoformat()
    if args.cmd == "snapshot-import":
        snap = read_json(args.file)
        if snap.get("schema") != SCHEMA + "snapshot.v1" or not isinstance(snap.get("persons"), dict):
            raise ValueError("Neplatný snapshot; použij fs.syncSnapshotNaPozadi")
        target = work / ("snapshot-" + stamp + ".json")
        if target.exists() and read_json(target) != snap:
            target = target.with_name(target.stem + "-" + digest(snap) + ".json")
        save_json(target, snap)
        print(target)
    elif args.cmd == "diff":
        paths = sorted(work.glob("snapshot-*.json"), key=lambda p: p.stat().st_mtime)
        path = args.snapshot or (paths[-1] if paths else None)
        if not path:
            raise ValueError("Chybí snapshot. Nejprve snapshot-import.")
        ledger = ROOT / "data/fs_sync_stav.json"
        plan = build_plan(load_local(), read_json(path), read_json(ledger) if ledger.exists() else {}, args.task_closeness)
        plan["snapshot_file"] = str(path)
        target = work / ("plan-" + stamp + ".json")
        if target.exists() and read_json(target) != plan:
            target = target.with_name(target.stem + "-" + plan["id"] + ".json")
        save_json(target, plan)
        write_text(target.with_suffix(".md"), markdown(plan))
        print(target.with_suffix(".md"))
        counts = {k: len(plan[k]) for k in ("missing_ids", "missing_ids_other", "mappings", "mapping_review", "items", "conflicts", "unread", "id_changes", "tasks_close", "tasks_distant")}
        counts["tasks"] = len(plan["tasks"]) if plan["tasks_read"] else None
        counts["myheritage"] = plan["myheritage_summary"]
        print(json.dumps(counts, ensure_ascii=False))
    elif args.cmd == "map":
        plan = read_json(args.plan)
        if plan.get("reviewed") is not True:
            raise ValueError("Nejdřív zkontroluj plán a nastav reviewed: true")
        # Znovu odvoď shody z aktuálních dat a původního snapshotu. Nevěř ručně dopsaným ID.
        current = build_plan(load_local(), read_json(plan["snapshot_file"]))
        fsmap = read_json(ROOT / "data/familysearch.json", {})
        # Slabší shody přijme jen ze zkontrolované kopie, kam je revizor přesunul z mapping_review.
        reviewed = {(r["local"], g, k, r["fs"]) for r in current.get("mapping_review", []) for g, k in r["keys"]}
        mappings = []
        for row in plan["mappings"]:
            if "keys" in row:
                keys = row["keys"]
            else:
                keys = [(row["group"], row["key"])]
            for group, key in keys:
                mapping = dict(local=row["local"], group=group, key=key, fs=row["fs"])
                if (mapping not in current["mappings"] and (row["local"], group, key, row["fs"]) not in reviewed
                        and fsmap.get(group, {}).get(key) != row["fs"]):
                    raise ValueError("Mapování už neodpovídá aktuálním datům; spusť diff")
                mappings.append(mapping)
        write_mappings(ROOT / "data/familysearch.json", mappings)
        print(f"Uloženo {len(mappings)} mapování. Spusť nový diff.")
    elif args.cmd == "log":
        log_result(read_json(args.result), read_json(args.plan), ROOT / "data/fs_sync_stav.json", ROOT / "data/research_log.md")
        print("Výsledek uložen. Spusť nový snapshot a diff.")
    elif args.cmd == "scope":
        local = load_local()
        ids = sorted({p["fs"] for p in local.values() if p.get("fs") and p["living"] is False})
        root = args.root or local.get("k:1", {}).get("fs")
        if root and not PID.fullmatch(root):
            parser.error("Neplatné ID výchozí osoby na FamilySearch")
        cfg = dict(root=root, generations=8, ids=ids, maxPersons=args.max_persons, tasks=bool(root or ids), matches=True,
                   myheritage=not args.no_myheritage, neighbours=not args.no_neighbours, pace=max(1100, args.pace))
        # Kandidáti z citací GEDCOMu u osob bez ID: snapshot je jen přečte, diff je dá ke kontrole.
        mapped = {p["fs"] for p in local.values() if p.get("fs")}
        cfg["lookup"] = sorted({c for p in local.values() if not p.get("fs") and p.get("living") is False
                                for c in p.get("fs_cited", [])} - mapped)
        if args.since:
            previous = read_json(args.since)
            cfg["cachedMatches"] = cached_matches(previous, args.matches_max_age_days)
            if not args.no_myheritage:
                cfg["cachedMyHeritage"] = cached_matches(previous, args.myheritage_max_age_days, field="myheritage")
        target = work / "scope.json"
        save_json(target, cfg)
        print(target)
        print(f"{len(local)} místních osob, {len(ids)} FS ID nežijících osob")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as e:
        sys.exit(str(e))
