# Primetime ticket watcher

Checks https://thelittle.org/primetime/ every ~10 minutes via a GitHub Actions
cron job and pushes a phone notification (through [ntfy.sh](https://ntfy.sh))
the moment a new "buy tickets" link shows up on the page.

## One-time setup (~5 minutes)

1. **Install ntfy on your phone.**
   - [iOS](https://apps.apple.com/us/app/ntfy/id1625396347) / [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)
   - Open the app, tap **+** / "Subscribe to topic", and enter this topic name:

     ```
     thelittle-primetime-060f1ccf31
     ```

     Treat that string like a password — anyone who knows it can also see
     (or send) notifications on it. Feel free to pick your own topic name
     instead; just use the same value everywhere in this setup.

2. **Add the topic as a repo secret** so the workflow can publish to it:
   - GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `NTFY_TOPIC`
   - Value: `thelittle-primetime-060f1ccf31` (or whatever topic you chose)

3. **(Optional) Narrow it to specific movies.** By default you get alerted
   the instant *any* new ticket link appears on the Primetime page. To only
   be notified for specific titles, add a repo **variable** (Settings →
   Secrets and variables → Actions → Variables):
   - Name: `MOVIE_KEYWORDS`
   - Value: comma-separated titles/keywords, e.g. `Jaws, Some Like It Hot`

4. **Push this branch / merge it**, then kick off a first run manually so you
   don't have to wait for the cron schedule:
   - Actions tab → "Check Primetime tickets" → **Run workflow**
   - Check the box for **test_notification** on that first run to confirm a
     push notification actually reaches your phone immediately.
   - Run it again with the box unchecked to do a real check of the page — you
     should get a "Primetime Ticket Watcher started" notification listing
     whatever ticket-like links it currently sees.

That's it — from then on it checks automatically on the schedule in
`.github/workflows/check-tickets.yml` and only pings you again when
something *new* shows up.

## How detection works

The script (`scripts/check_tickets.py`) fetches the page and looks for:

- `<a>` links whose text or URL looks ticket-related ("Buy Tickets", "Get
  Tickets", links to known box-office/ticketing platforms, etc.)
- Phrases like "on sale now" / "tickets on sale" appearing in the page text

It remembers what it has already seen in `data/state.json` (committed back to
the repo by the workflow after every run), and only notifies you about
**links that are new since the last check** — not everything that happens to
already be on sale.

### If it doesn't pick up the right thing

This was built without being able to load the live page from this dev
session (network policy blocked the domain here), so the heuristics above
are a best-effort starting point, not verified against the real markup.
After the first real run:

1. Open the Actions run's log — it prints what it fetched and found.
2. Compare against what the page actually shows.
3. If titles look wrong or a real "buy tickets" link is being missed (or a
   nav link is being falsely flagged), tell Claude what the log shows vs.
   what's on the page and the regexes in `check_tickets.py`
   (`TICKET_LINK_TEXT_RE`, `TICKET_HREF_RE`, `ONSALE_PHRASES`) can be tuned.
4. If the page turns out to be JavaScript-rendered (the fetched HTML doesn't
   contain the ticket links you see in a browser), the fetch step needs to
   switch from a plain HTTP request to a headless-browser render (e.g.
   Playwright) — say so and that can be swapped in.

## Local testing

```bash
pip install -r requirements.txt
NTFY_TOPIC=thelittle-primetime-060f1ccf31 python scripts/check_tickets.py
```

Run it twice in a row — the first run establishes a baseline (and sends a
"started" notification), the second will report "No new ticket links or
on-sale phrases detected" since nothing changed.
