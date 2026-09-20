#!/usr/bin/env python3
"""Check thelittle.org/primetime/ for newly-on-sale tickets and push a notification via ntfy.sh.

Run on a schedule (see .github/workflows/check-tickets.yml). Keeps state in
data/state.json (committed back to the repo by the workflow) so it can tell
"new since last check" apart from "already on sale last time we looked".
"""
import datetime
import json
import os
import re
import sys
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

URL = os.environ.get("PRIMETIME_URL", "https://thelittle.org/primetime/")
STATE_PATH = os.environ.get("STATE_PATH", "data/state.json")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
MOVIE_KEYWORDS = [k.strip().lower() for k in os.environ.get("MOVIE_KEYWORDS", "").split(",") if k.strip()]
FORCE_TEST = os.environ.get("FORCE_TEST_NOTIFICATION") == "1"

# Heuristics for spotting "buy tickets" links without knowing the exact markup
# of the page up front (verify/tune against the workflow's first-run log).
TICKET_LINK_TEXT_RE = re.compile(r"buy\s*ticket|get\s*ticket|purchase\s*ticket|tickets?\b|order\s*ticket|reserve", re.I)
TICKET_HREF_RE = re.compile(
    r"ticket|boxoffice|box-office|eventbrite|veezi|vendini|ticketleap|audienceview|frontrow|fevo|showclix|eventive",
    re.I,
)
ONSALE_PHRASES = ["on sale now", "tickets on sale", "buy tickets now", "now on sale"]
HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5")


def fetch_page(url: str) -> str:
    resp = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; PrimetimeTicketWatcher/1.0)"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.text


def nearby_title(tag) -> str:
    """Best-effort: walk up the DOM from a ticket link to find the movie/event heading."""
    node = tag
    for _ in range(6):
        if node is None:
            break
        heading = node.find(HEADING_TAGS) if hasattr(node, "find") else None
        if heading and heading.get_text(strip=True):
            return heading.get_text(strip=True)
        node = node.parent
    text = tag.get_text(strip=True)
    return text if text else "(untitled)"


def extract_ticket_links(html: str, base_url: str):
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True)
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        if TICKET_LINK_TEXT_RE.search(text) or TICKET_HREF_RE.search(href):
            abs_url = urljoin(base_url, href)
            found[abs_url] = {"title": nearby_title(a), "text": text}
    return found


def onsale_phrase_count(html: str) -> int:
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True).lower()
    return sum(text.count(p) for p in ONSALE_PHRASES)


def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH) as f:
        return json.load(f)


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH) or ".", exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


def send_ntfy(title: str, message: str, click_url: str = None, priority: str = "high", tags: str = "ticket"):
    if not NTFY_TOPIC:
        print(f"NTFY_TOPIC not set; would have sent -> [{priority}] {title}: {message}")
        return
    headers = {"Title": title, "Priority": priority, "Tags": tags}
    if click_url:
        headers["Click"] = click_url
    resp = requests.post(f"{NTFY_SERVER}/{NTFY_TOPIC}", data=message.encode("utf-8"), headers=headers, timeout=15)
    resp.raise_for_status()
    print(f"Sent notification: {title}")


def matches_keywords(item) -> bool:
    if not MOVIE_KEYWORDS:
        return True
    haystack = f"{item['title']} {item['text']}".lower()
    return any(k in haystack for k in MOVIE_KEYWORDS)


def main():
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    state = load_state()
    is_first_run = "known_links" not in state

    if FORCE_TEST:
        send_ntfy(
            "Primetime Ticket Watcher -- Test",
            f"This is a test notification from your ticket watcher, checking {URL}.",
            click_url=URL,
            priority="default",
            tags="test_tube",
        )
        return

    try:
        html = fetch_page(URL)
    except Exception as e:
        print(f"ERROR fetching {URL}: {e}", file=sys.stderr)
        failure_count = state.get("consecutive_failures", 0) + 1
        state["consecutive_failures"] = failure_count
        # Only alert once the failure streak is confirmed (avoid noise from one-off blips).
        if failure_count == 3:
            send_ntfy(
                "Primetime watcher can't reach the page",
                f"Failed 3 checks in a row fetching {URL}: {e}",
                click_url=URL,
                priority="default",
                tags="warning",
            )
        save_state(state)
        sys.exit(0)

    state["consecutive_failures"] = 0

    links = extract_ticket_links(html, URL)
    current_urls = set(links.keys())
    known_urls = set(state.get("known_links", []))
    new_urls = current_urls - known_urls

    current_phrase_count = onsale_phrase_count(html)
    prev_phrase_count = state.get("onsale_phrase_count", 0)

    if is_first_run:
        summary = "\n".join(f"- {links[u]['title']}" for u in sorted(current_urls)) or "(no ticket links detected yet)"
        send_ntfy(
            "Primetime Ticket Watcher started",
            f"Now watching {URL}.\nCurrently detected ticket-like links:\n{summary}",
            click_url=URL,
            priority="default",
            tags="movie_camera",
        )
    else:
        alertable_new = [u for u in new_urls if matches_keywords(links[u])]
        if alertable_new:
            lines = [f"- {links[u]['title']}: {u}" for u in sorted(alertable_new)]
            send_ntfy(
                "Tickets just went on sale!",
                "New ticket link(s) detected on the Primetime page:\n" + "\n".join(lines),
                click_url=URL,
                priority="urgent",
                tags="tada,ticket",
            )
        elif current_phrase_count > prev_phrase_count:
            send_ntfy(
                "Possible ticket update at The Little",
                f"Detected new 'on sale' wording on {URL} -- worth a look.",
                click_url=URL,
                priority="high",
                tags="eyes",
            )
        else:
            print("No new ticket links or on-sale phrases detected.")

    state["known_links"] = sorted(current_urls | known_urls)
    state["onsale_phrase_count"] = current_phrase_count
    state["last_checked"] = now
    save_state(state)


if __name__ == "__main__":
    main()
