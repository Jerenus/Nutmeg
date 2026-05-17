# 500.com Page Structure — Recon Note (2026-05-17)

Contract for the `nutmeg/data/fcom500.py` parsers. Every parser is built TDD
against the recorded fixtures in `tests/fixtures/fcom500/`. Recorded on
2026-05-17 with `curl -A "Mozilla/5.0 ..."`; all pages are **gb2312-encoded**
and decoded with `bytes.decode('gb2312', errors='ignore')`.

## Pages recorded

| Fixture file | Source URL | Purpose |
|---|---|---|
| `jczq-list.html` | `https://trade.500.com/jczq/` | 竞彩 match list — 周日NNN numbers + 竞彩 odds + the matchnum↔fid join |
| `ouzhi-{fid}.html` | `https://odds.500.com/fenxi/ouzhi-{fid}.shtml` | 欧赔 — international 1X2 odds |
| `yazhi-{fid}.html` | `https://odds.500.com/fenxi/yazhi-{fid}.shtml` | 亚盘 — international Asian handicap |
| `daxiao-{fid}.html` | `https://odds.500.com/fenxi/daxiao-{fid}.shtml` | 大小球 — international over/under |
| `jqs-{fid}.html` | `https://odds.500.com/fenxi/jqs-{fid}.shtml` | 进球指数 — exact-goal-count odds |
| `bifen-{fid}.html` | `https://odds.500.com/fenxi/bifen-{fid}.shtml` | 比分指数 — correct-score (header only, no static odds) |

Two real matches were recorded: `周日001` (fid `1366371`, 大阪樱花 vs 名古屋鲸八,
日职) and `周日002` (fid `1373152`, 全北现代 vs 金泉尚武, 韩职).

---

## 1. `trade.500.com/jczq/` — the 竞彩 match list (`jczq-list.html`)

**The match list IS in static HTML.** 38 matches on the recorded day. Each match
is a `<tr ... data-matchid="N" data-matchnum="周日NNN" ...>`.

Per-row extraction (use `re.split(r'(?=<tr[^>]*data-matchid=)', html)` to split,
then per block):

- **竞彩号 (join key A)**: `data-matchnum="周日001"` attribute on the `<tr>`.
- **500.com fid (join key B)**: every analysis link in the row carries it, e.g.
  `ouzhi-1366371.shtml` → `re.search(r'ouzhi-(\d+)\.shtml', block)`. The same
  fid appears in `shuju-`, `yazhi-`, `daxiao-`, `bifen-` links.
  **The 竞彩号 ↔ data-fid join is fully established from this single page** — no
  extra fetch needed to pair them.
- **team names**: `<a ... class="team-l" title="大阪樱花">` and
  `class="team-r" title="名古屋鲸八">` → `re.findall(r'class="team-[lr]" title="([^"]+)"', block)`
  returns `[home, away]`.
- **league**: `<a href="https://liansai.500.com/zuqiu-NNNNN/" ... title="日本职业联赛">日职</a>`
  → the `title` is the full league name, the text is the short name.
- **kickoff**: `<td class="td td-endtime" title="05-17 14:00截止">` — this is the
  betting **cutoff**, ~ kickoff. `re.search(r'td-endtime" title="([^"]+)"', block)`.
- **竞彩 official odds (体彩 — NOT independent, do not use as conflict signal)**:
  `<p class="betbtn" data-type="spf" data-value="3|1|0" data-sp="1.39">` is 胜平负
  (value 3=win,1=draw,0=loss). `data-type="nspf"` is 让球胜平负. These are the
  official Sporttery prices — kept for reference only.

## 2. `ouzhi-{fid}.html` — 欧赔 (international 1X2)  ✅ INDEPENDENT

`<table id="datatb" class="pub_table">`. Each bookmaker is a
`<tr class="tr1" id="N" ...>` (also `tr2`). 15 bookmaker rows on the recorded
match.

- **Row id=1 is `竞*官*` (竞彩官方 = 体彩) — SKIP it for the conflict signal.**
  Rows id ∈ {3,5,6,280,1055,...} are international books (bet365, 威廉希尔,
  Pinnacle平博, etc.). Bookmaker *names* are asterisk-masked for logged-out
  users (`**t3*5`, `Pi****le平*`) — **odds values are NOT masked**.
- Per bookmaker row, the **first** `<table class="pl_table_data">` holds the
  odds. It has two `<tr>`: row 1 = 初赔 (opening), row 2 = 即时 (live/current).
  Each `<tr>` has 3 `<td>` = home / draw / away decimal odds.
  Extract: `re.findall(r'<td[^>]*>\s*([\d.]+)\s*</td>', first_pl_table)` → 6
  numbers `[open_h, open_d, open_a, live_h, live_d, live_a]`. **Use the live
  (last 3).**
- bet365 (id=3) recorded live odds for 周日001: `2.35 / 3.40 / 2.87`.

The parser **averages the live 1X2 odds across all international rows** (id≠1)
and de-vigs: `fair_p[k] = (1/avg_odds[k]) / Σ(1/avg_odds)`.

## 3. `yazhi-{fid}.html` — 亚盘 (international Asian handicap)  ✅ INDEPENDENT

`<table id="datatb">`. Each `<tr class="tr1|tr2" id="N">` is one bookmaker
(17 rows). Per row, the first `<table class="pl_table_data">` is the current
盘口: a single `<tr>` with `[<td>up_odds</td>, <td ref="-0.250">平手/半球</td>,
<td>down_odds</td>]`. The `ref` attribute is the **signed handicap line in goals**
(`-0.250` = home gives a quarter-ball-ish line) and the text (`平手/半球`) is the
Chinese line name.

Asian handicap is a **2-way market** (handicap-up = home covers /
handicap-down = away covers; no draw). The model's `handicap_*` markets
(`nutmeg/models/dixon_coles.py`) are *integer-line* 3-way (home/draw/away)
markets. **Asian handicap does not map 1:1 onto the model's handicap buckets.**

Decision (Task A5/A7): the parser extracts the handicap line + up/down odds and
de-vigs to a 2-way fair probability, exposed as a `handicap` market with
outcomes `handicap_home` / `handicap_away`. The conflict engine's
`_market_probabilities` pulls handicap keys from `model_markets.handicap.items()`
which are `handicap_home_{0,plus_N,minus_N}` with home/draw/away outcomes — the
keys differ, so **the handicap market from 500.com will not produce conflicts
against the current model handicap buckets**. It is still emitted in the
`OddsSnapshot` (line + fair probs) so a future model-side Asian-handicap pricer
can consume it; for now it degrades to "carried but unmatched".

## 4. `daxiao-{fid}.html` — 大小球 (international over/under)  ✅ INDEPENDENT

`<table id="datatb">`, same shape as yazhi: `<tr class="tr1|tr2" id="N">` per
bookmaker (17 rows). First `pl_table_data`: `[<td>over_odds</td>,
<td ref="-2.50">2.5</td>, <td>under_odds</td>]`. `ref` = the O/U line.

This is a **line-based** over/under, NOT an exact goal-count distribution. The
model's `total_goals` market is an *exact-count* distribution
(`total_0`..`total_7_plus`). **Over/under does not map onto exact-count buckets
without a Poisson re-distribution** (spec §4 flagged this ⚠️). The parser
extracts the O/U line + over/under fair probs; A7 carries it as a `total_goals`
market only if a clean mapping is implemented, otherwise carries the raw O/U
under market key `over_under` (independent=True) — see §6 verdict.

## 5. `jqs-{fid}.html` — 进球指数 / total-goals exact count  ⚠️ NOT INDEPENDENT

`<table class="pub_table">` with column headers `0球 1球 2球 3球 4球 5球 6球 7+`
— **exactly matching** the model's `total_0`..`total_6`, `total_7_plus`.
Rows are `<tr class="tr1|tr2">`, `<td class="tb_plgs"><p>NAME</p></td>` then 8
`<td>` odds.

**BUT** only 2 rows exist on the static page: `竞彩**` (体彩 official) and
`足球**` (足球彩票 — also a Sporttery/体彩-derived feed). **There are NO
international bookmaker rows for the exact goal-count market.** No bet365 /
Pinnacle exact-goals odds.

## 6. `bifen-{fid}.html` — 比分指数 / correct score  ⚠️ JS-LOADED, NO STATIC ODDS

`<table class="pub_table">` exists with `<th>` score-column headers
(`1:0 2:0 2:1 ... 0:0 1:1 ...`) but the `<tbody>` contains **only the header
`<tr>` — zero odds rows** in static HTML. The correct-score odds are loaded
client-side via JavaScript/AJAX (no inline JSON, no discoverable static
endpoint found during recon). **Correct-score odds are not parseable from
static HTML.**

---

## §4 INDEPENDENCE VERDICT (the spec §4 ⚠️ items — definitively resolved)

| Conflict-engine market | 500.com static source | Independent of 体彩? | Verdict |
|---|---|---|---|
| `match_winner` (胜平负) | `ouzhi-{fid}` 欧赔 — 15 bookmaker rows, ~14 international | **✅ YES** | True conflict signal. Average international live 1X2, de-vig. |
| `handicap` (让球) | `yazhi-{fid}` 亚盘 — 17 international bookmaker rows | **✅ YES** (but Asian-handicap shape) | Independent odds available, but it is 2-way Asian handicap, NOT the model's integer-line 3-way handicap. Carried in the snapshot; will not match current model handicap keys → no conflict produced for now. |
| `total_goals` (总进球, exact count) | `jqs-{fid}` 进球指数 | **❌ NO** | Only 体彩-derived rows (`竞彩**`, `足球**`). The international over/under (`daxiao-{fid}`) IS independent but is a line market, not exact counts. **Exact-count total-goals has NO 体彩-independent odds.** Per spec §4 the parser still returns jqs odds tagged `independent=False` (model-vs-体彩 weak signal). |
| `correct_score` (比分) | `bifen-{fid}` 比分指数 | **❌ N/A** | Correct-score odds are **JS-loaded — absent from static HTML entirely**. Cannot be parsed from a recorded static page. Market is not collected. |

**Bottom line — 2 of the 4 conflict markets are cleanly covered as true,
体彩-independent conflict signals:**

1. **`match_winner`** — ✅ fully clean (international 欧赔).
2. **`handicap`** — ⚠️ independent international odds exist (亚盘) but as a
   2-way Asian-handicap market that does not key-match the model's 3-way
   integer-line handicap; emitted but unmatched.
3. **`total_goals`** — ⚠️ only 体彩-derived exact-count odds (`jqs`); emitted
   with `independent=False`. The independent O/U (`daxiao`) is line-based.
4. **`correct_score`** — ❌ not available in static HTML (JS-rendered); not
   collected.

This is a **partial** result and is reported honestly: `match_winner` is the
one fully clean independent conflict market; `total_goals` degrades to a flagged
weak signal; `correct_score` is dropped; `handicap` is carried but unmatched.
The conflict engine already treats every market except `match_winner` as
optional and degrades gracefully when a market is missing — so this partial
coverage is consumed without crashes.
