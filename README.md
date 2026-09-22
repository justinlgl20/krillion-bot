# krillion-bot

A small Discord bot for groups that play [Krillion.io](https://krillion.io) daily.
Paste your result in Discord, the bot records it, posts a leaderboard when the
puzzle closes and keeps a Codeforces-style rating for everyone.

```
Krillion #58 🦐
340

🦑🦑🦑🦑🦑🐟🫧
```

Designed to run on an Oracle Cloud *Always Free* VM: one Python process,
SQLite on disk, ~60 MB RAM, no other services.

## What it does

- **Reads results** from any message containing `Krillion #<n>` followed by the
  score. Reacts 🦐 when recorded. The puzzle number must be the one that is
  live right now (Krillion rolls over at midnight New York = **2pm AEST**, or
  3pm AEST while the US is on standard time). Old / future numbers are refused
  with a short reply; a second paste for the same puzzle keeps the first score.
- **Grace period**: results for the puzzle that just closed are still accepted
  for `LATE_GRACE_MINUTES` (default 10) after the reset, so a paste at 2:03pm
  isn't lost.
- **Daily leaderboard**: once the grace period ends the bot posts the final
  standings for that puzzle with each player's rating change. It is posted to
  `LEADERBOARD_CHANNEL_ID`, or to the channel the results were shared in.
  Days missed while the bot was offline are closed out on the next start.
- **Table image**: leaderboards are rendered as a PNG table (rank, name and
  rating rank, the result's emoji row, score, performance, rating change) in
  the style of the Queens bot, with Pillow. This needs
  DejaVu Sans and Noto Color Emoji (`fonts/NotoColorEmoji.ttf`, fetched by
  the deploy script); if either is missing the same board is sent as text.
  Rendering takes well under 100 ms and a few MB of RAM.
- **Dashboards**: `stats`, `week`, `rating` and `performance` reply with
  matplotlib images in the NeoTLE style (player names coloured by rating
  rank); everything else replies with NeoTLE-style embeds and paged lists.
- **Rating**: the Codeforces-style contest rating used by the Queens bot in
  [mklol/tle-gf](https://github.com/mklol/tle-gf). Everyone starts at
  **1200**. Each day is one contest: submitters are ranked by score (ties
  share a rank), each player's expected seed is computed from the whole
  field, and the rating moves halfway towards the rating that would have
  predicted their actual rank, then the field is corrected so it doesn't
  inflate and the result is damped by `RATING_DAMPING`. Every row also gets a
  *performance* — the rating that day's result was worth. Rating ranks follow
  the Codeforces ladder (Newbie < 1000, Pupil, Specialist, Expert 1200+,
  Candidate Master 1300+, Master 1400+, …, Legendary Grandmaster 2000+). A
  day with a single submitter changes nothing.
- **Inactivity decay**: a rated diver who sits out a day drifts back towards
  1200 (`RATING_DECAY_BASE` of the excess per missed day, growing with the
  streak up to `RATING_DECAY_MAX`; nobody below 1200 drifts *up*). The points
  lost are shared out among that day's submitters.
- **Weekly recap**: after Sunday's puzzle closes, a Monday–Sunday recap (each
  day's winner, weekly standings, highest score, most improved, biggest rating
  moves) is available through `/krillion week`.
- **Slash commands** all live under `/krillion`, ported from the Akari
  minigame in [mklol/tle-gf](https://github.com/mklol/tle-gf) and reshaped
  for Krillion's daily score. Anywhere a puzzle is asked for you can give the
  number (`puzzle:58`) or the date (`date:2026-09-11`); `timeframe` is one of
  all time / this week / this month / this year / last 7 or 30 days.

  Boards
  - `/krillion leaderboard [puzzle|date]` – live scores for today with
    projected rating changes, or the final table for a past puzzle
  - `/krillion ratings [inactive]` – rating rankings; divers who haven't played
    for 30 days are hidden unless `inactive:true`
  - `/krillion top [timeframe] [ties]` – who has won the most days (a day
    needs two or more players to count; `ties:true` ranks by total wins
    including shared days)
  - `/krillion week [when]` – weekly recap for this week, `last`, or the week
    holding a date

  Divers
  - `/krillion stats [member]` – rating, peak, performance, games, wins, best /
    average / median score, perfect 700s, streaks, emoji tallies, weekday
    averages
  - `/krillion rating [member]` / `/krillion performance [member]` – rating
    graph (Codeforces-style rank bands), the latter with each day's
    performance marked
  - `/krillion history [member] [page]` – every rated day, newest first
  - `/krillion streak [member]` – current and longest daily and perfect streaks
  - `/krillion skips [member]` – puzzles missed since their first result
  - `/krillion vs <player1> <player2> [player3] [player4] [timeframe] [missing]`
    – head-to-head on the puzzles everyone played (`missing:true` counts a
    skipped puzzle as a loss)

  Participation
  - `/krillion puzzle` – which puzzle is live and when it resets (in each
    user's local time)

  Admin (`/krillion admin ban`) — for `ADMIN_USER_IDS` and delegated admins
  only; server permissions such as *Manage Server* grant nothing
  - `ban <member> [reason]` – banned divers'
    results are ignored (🚫 reaction) and they are hidden from boards

- **Admins** are the Discord user IDs in `ADMIN_USER_IDS` (default:
  `750888871696269402`), plus delegated admins and members with the *Manage
  Server* permission.

## 1. Create the Discord application

1. <https://discord.com/developers/applications> → **New Application**.
2. **Bot** tab → *Reset Token* → copy it (this is `DISCORD_TOKEN`).
3. Still on **Bot**, under *Privileged Gateway Intents* enable
   **Message Content Intent** (required to read pasted results).
4. **OAuth2 → URL Generator**: scope `bot` + `applications.commands`;
   bot permissions *View Channels*, *Send Messages*, *Read Message History*,
   *Add Reactions*. Open the generated URL and add the bot to your server.

## 2. Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
cp .env.example .env            # put DISCORD_TOKEN in here
.venv/bin/python -m pytest      # tests
.venv/bin/python -m krillion_bot
```

Slash commands are synced on startup; Discord can take a few minutes to show
them the first time.

## 3. Host it on an Oracle Always Free VM

Any free-tier shape works (the `VM.Standard.E2.1.Micro` with 1 GB RAM is
plenty; an Ampere `A1.Flex` is fine too). Use the **Canonical Ubuntu** image
when creating the instance — Oracle Linux also works (`dnf` path). No ingress
ports need to be opened; the bot only makes outbound connections to Discord.

From your machine, with `.env` filled in:

```bash
./deploy/deploy.sh ubuntu@<vm-public-ip> ~/.ssh/<your-oracle-key>
# or:  make deploy HOST=ubuntu@<vm-public-ip> KEY=~/.ssh/<your-oracle-key>
```

(Use `opc@` instead of `ubuntu@` on an Oracle Linux image.)

The script copies the repo to `/opt/krillion-bot` on the VM, seeds `.env` from
your local one (only if the VM doesn't already have one), adds a 2 GB swapfile
if the VM has less than 2 GB of swap, disables the hourly `dnf-makecache`
timer on Oracle Linux (it alone can swap-thrash a 1 GB box), installs Python
and the dependencies into a venv, installs a hardened `systemd` service
(`deploy/krillion-bot.service`) and starts it.
Re-run the same command to deploy updates — the database in
`/opt/krillion-bot/data/` is untouched. On Oracle Linux (SELinux enforcing) the
app directory is also relabelled so systemd is allowed to read `.env` and run
the venv — this is why it lives in `/opt` rather than your home directory.

The 1 GB micro shape is slow: the first run can take 5–10 minutes while the
package manager works (later runs skip it and need no network beyond the
upload). If the VM stops answering ssh
during a first deploy it has run out of memory — reboot it from the Oracle
console and re-run the deploy; the swapfile is created before anything heavy
runs so it won't happen twice.

On the VM:

```bash
sudo journalctl -u krillion-bot -f        # logs
sudo systemctl restart krillion-bot       # restart
sudo systemctl status krillion-bot
nano /opt/krillion-bot/.env               # change config, then restart
```

If you didn't have a local `.env`, ssh in, edit `/opt/krillion-bot/.env`, set
`DISCORD_TOKEN`, and `sudo systemctl restart krillion-bot`.

## Configuration

All settings live in `.env` (see `.env.example`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `DISCORD_TOKEN` | – | Bot token (required) |
| `LEADERBOARD_CHANNEL_ID` | empty | Channel for the daily post; empty = where results were shared |
| `RESULTS_CHANNEL_ID` | empty | Only read results from this channel; empty = all channels |
| `DATABASE_PATH` | `data/krillion.sqlite3` | SQLite file |
| `LATE_GRACE_MINUTES` | `10` | How long after reset the previous puzzle is still accepted |
| `RATING_DAMPING` | `0.25` | Fraction of the raw contest delta applied each day |
| `RATING_DECAY_BASE` | `0.04` | Share of a resting diver's excess over 1200 lost on the first missed day |
| `RATING_DECAY_MAX` | `0.08` | Cap on the per-day decay share as a streak grows |
| `RATING_DECAY_GRACE` | `0` | Missed days before decay starts |
| `ADMIN_USER_IDS` | `750888871696269402` | Comma-separated user IDs allowed to run admin commands |
| `KRILLION_TIMEZONE` | `America/New_York` | Timezone the game resets in |
| `KRILLION_EPOCH_DATE` | `2026-07-16` | Date of Krillion #1 |

The last two mirror how krillion.io numbers its puzzles; only change them if
the game changes.

## Layout

```
krillion_bot/
  parser.py         share-text parser
  puzzle.py         puzzle number <-> date, reset times
  rating.py         Codeforces/Queens-bot contest rating, performance, ranks, decay
  models.py         Result / Player / RatingEntry records
  storage.py        SQLite persistence (results, players, rating history)
  storage_game.py   result queries, bans, delegated admins
  service.py        submissions, grace period, closing a day, replay
  analytics.py      streaks, skips, winners, head-to-head, stats, weekly recap
  formatting.py     leaderboard rows/text
  views.py          embeds and pages for the streak/skips/top/vs/history/rating commands
  render.py         leaderboard PNG
  charts.py         matplotlib theme, rank colours, rating / performance graph
  plot_stats.py     /krillion stats dashboard
  plot_week.py      weekly recap dashboard
  discord_util.py   embeds, pagination, attachments
  commands.py       /krillion public commands
  commands_admin.py /krillion admin ban subgroup
  bot.py            Discord glue (events, scheduler, weekly recap)
deploy/          deploy.sh, setup-vm.sh, systemd unit
tests/
```
