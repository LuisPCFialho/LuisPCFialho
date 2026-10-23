#!/usr/bin/env python3
"""Render assets/generated/stats.svg for the profile README.

Runs daily in GitHub Actions (stdlib only). Text is drawn from glyph
outlines in glyphs.json so the card looks the same on every device.

Online:   GITHUB_TOKEN=... GH_USER=LuisPCFialho python3 scripts/build_stats.py
Offline:  python3 scripts/build_stats.py --offline contrib.json langs.json
"""
import datetime as dt
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "assets", "generated", "stats.svg")
G = json.load(open(os.path.join(HERE, "glyphs.json"), encoding="utf-8"))

SKIP_LANGS = {"HTML", "CSS", "SCSS", "Batchfile", "PowerShell", "Shell", "Dockerfile",
              "Makefile", "Procfile", "Inno Setup", "NSIS", "Jupyter Notebook"}
PALETTE = ["#FFB547", "#5EEAD4", "#A78BFA", "#F472B6", "#38BDF8", "#86EFAC"]
OTHER = "#3B4757"


# ------------------------------------------------------------------ data
def _post(url, payload, token):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST", headers={
        "Authorization": f"bearer {token}", "Content-Type": "application/json",
        "User-Agent": "profile-stats"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }
    }
    repositories(first: 100, ownerAffiliations: OWNER, privacy: PUBLIC, isFork: false) {
      nodes { stargazerCount languages(first: 15, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name } } } }
    }
  }
}"""


def fetch_online(user, token):
    res = _post("https://api.github.com/graphql", {"query": QUERY, "variables": {"login": user}}, token)
    if "errors" in res:
        raise SystemExit(f"GraphQL error: {res['errors']}")
    u = res["data"]["user"]
    cal = u["contributionsCollection"]["contributionCalendar"]
    days = [d["contributionCount"] for w in cal["weeks"] for d in w["contributionDays"]]
    langs = {}
    for repo in u["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            langs[e["node"]["name"]] = langs.get(e["node"]["name"], 0) + e["size"]
    html_days = fetch_calendar_html(user)
    if html_days:
        days = html_days
    return days, langs


def fetch_calendar_html(user):
    """Public contributions calendar, which includes private contributions when the
    profile shows them (the API with GITHUB_TOKEN only sees public ones)."""
    import re
    try:
        req = urllib.request.Request(f"https://github.com/users/{user}/contributions",
                                     headers={"User-Agent": "profile-stats"})
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        print(f"calendar html unavailable: {e}")
        return None
    tips = {}
    for m in re.finditer(r'<tool-tip\b[^>]*\bfor="([^"]+)"[^>]*>([^<]*)</tool-tip>', html):
        n = re.match(r"\s*([\d,]+) contribution", m.group(2))
        tips[m.group(1)] = int(n.group(1).replace(",", "")) if n else 0
    cells = []
    for m in re.finditer(r"<td\b[^>]*>", html):
        tag = m.group(0)
        d = re.search(r'data-date="(\d{4}-\d{2}-\d{2})"', tag)
        i = re.search(r'\bid="([^"]+)"', tag)
        if d and i:
            cells.append((d.group(1), tips.get(i.group(1), 0)))
    if len(cells) < 300 or not tips:
        print(f"calendar html parse failed ({len(cells)} days, {len(tips)} tips)")
        return None
    cells.sort()
    print(f"calendar html: {len(cells)} days, {sum(c for _, c in cells)} contributions")
    return [c for _, c in cells]


def fetch_offline(contrib_path, langs_path):
    days = json.load(open(contrib_path))["counts"]
    langs = json.load(open(langs_path))
    return days, langs


def metrics(days):
    total = sum(days)
    seq = list(days)
    if seq and seq[-1] == 0:  # today not started yet: keep yesterday's streak
        seq = seq[:-1]
    cur = 0
    for v in reversed(seq):
        if v <= 0:
            break
        cur += 1
    best = run = 0
    for v in days:
        run = run + 1 if v > 0 else 0
        best = max(best, run)
    active = sum(1 for v in days if v > 0)
    return total, cur, best, active


# ------------------------------------------------------------------ text
class Text:
    def __init__(self):
        self.used = set()

    def width(self, font, s, size, tracking=0.0):
        f = G[font]
        adv = sum(f["g"].get(c, f["g"]["?"])[0] for c in s)
        return adv * size / f["upem"] + tracking * max(len(s) - 1, 0)

    def draw(self, font, s, x, y, size, fill, tracking=0.0, anchor="start"):
        f = G[font]
        if anchor != "start":
            w = self.width(font, s, size, tracking)
            x -= w / 2 if anchor == "middle" else w
        k = size / f["upem"]
        out = []
        for c in s:
            adv, d = f["g"].get(c, f["g"]["?"])
            if d:
                gid = f"{font}-{ord(c)}"
                self.used.add((gid, d))
                out.append(f'<use xlink:href="#{gid}" transform="translate({x:.1f} {y:.1f}) scale({k:.5f} {-k:.5f})"/>')
            x += adv * k + tracking
        return f'<g fill="{fill}">{"".join(out)}</g>'

    def defs(self):
        return "".join(f'<path id="{gid}" d="{d}"/>' for gid, d in sorted(self.used))


def fmt(n):
    return f"{n:,}"


# ------------------------------------------------------------------ render
def render(days, langs, today):
    total, cur, best, active = metrics(days)
    T = Text()
    W, H = 1200, 300
    parts = []

    parts.append(T.draw("mono5", "LAST 12 MONTHS", 32, 44, 13, "#FFB547", tracking=2))
    parts.append(T.draw("mono4", f"updated {today} UTC", W - 32, 44, 12.5, "#5E6B7B", anchor="end"))

    tiles = [
        ("Contributions", fmt(total), "", "#FFB547"),
        ("Current streak", str(cur), "day" if cur == 1 else "days", "#5EEAD4"),
        ("Longest streak", str(best), "day" if best == 1 else "days", "#A78BFA"),
        ("Active days", str(active), "of the year", "#86EFAC"),
    ]
    tw, gap, ty, th = 272, 16, 64, 112
    for i, (label, num, unit, acc) in enumerate(tiles):
        x = 32 + i * (tw + gap)
        parts.append(f'<rect x="{x}" y="{ty}" width="{tw}" height="{th}" rx="16" fill="#111A26" stroke="#1C2735"/>')
        parts.append(f'<circle cx="{x + tw - 24}" cy="{ty + 24}" r="10" fill="{acc}" fill-opacity=".14"/>'
                     f'<circle cx="{x + tw - 24}" cy="{ty + 24}" r="4.5" fill="{acc}"/>')
        parts.append(T.draw("disp7", num, x + 22, ty + 66, 46, "#F2F6FA", tracking=-.5))
        if unit:
            nw = T.width("disp7", num, 46, -.5)
            parts.append(T.draw("sans5", unit, x + 22 + nw + 9, ty + 66, 16, "#8796A8"))
        parts.append(T.draw("sans5", label, x + 22, ty + 94, 14, "#8796A8"))

    # languages
    items = sorted(((k, v) for k, v in langs.items() if k not in SKIP_LANGS and v > 0), key=lambda kv: -kv[1])
    tot = sum(v for _, v in items) or 1
    top = items[:5]
    rest = sum(v for _, v in items[5:])
    segs = [(k, v / tot, PALETTE[i]) for i, (k, v) in enumerate(top)]
    if rest / tot >= .005:
        segs.append(("Other", rest / tot, OTHER))

    parts.append(T.draw("mono5", "TOP LANGUAGES  ·  PUBLIC REPOS", 32, 212, 12.5, "#5E6B7B", tracking=2))
    bx, by, bw, bh = 32, 226, W - 64, 10
    parts.append(f'<clipPath id="bar"><rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="5"/></clipPath>')
    parts.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="5" fill="#16202D"/>')
    x = bx
    bar = []
    for i, (name, share, col) in enumerate(segs):
        w = bw * share
        last = i == len(segs) - 1
        bar.append(f'<rect x="{x:.1f}" y="{by}" width="{max(w - (0 if last else 3), 1):.1f}" height="{bh}" fill="{col}"/>')
        x += w
    parts.append(f'<g clip-path="url(#bar)">{"".join(bar)}</g>')

    lx = 32
    for name, share, col in segs:
        pct = f"{share * 100:.1f}%"
        wn = T.width("sans5", name, 14)
        wp = T.width("mono4", pct, 12.5)
        if lx + 16 + wn + 8 + wp > W - 32:
            break
        parts.append(f'<circle cx="{lx + 5}" cy="{267}" r="5" fill="{col}"/>')
        parts.append(T.draw("sans5", name, lx + 16, 272, 14, "#C9D4E0"))
        parts.append(T.draw("mono4", pct, lx + 16 + wn + 8, 272, 12.5, "#6F7D8E"))
        lx += 16 + wn + 8 + wp + 30

    title = f"GitHub stats: {fmt(total)} contributions in the last year, current streak {cur} days, longest streak {best} days"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img" aria-label="{title}"><title>{title}</title>'
        f'<defs>{T.defs()}<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="#0F1722"/><stop offset="1" stop-color="#0A1018"/></linearGradient></defs>'
        f'<rect x=".75" y=".75" width="{W - 1.5}" height="{H - 1.5}" rx="22" fill="url(#bg)" stroke="#1C2735" stroke-width="1.5"/>'
        f'{"".join(parts)}</svg>\n'
    )


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == "--offline":
        days, langs = fetch_offline(sys.argv[2], sys.argv[3])
    else:
        token = os.environ.get("GITHUB_TOKEN")
        user = os.environ.get("GH_USER")
        if not token or not user:
            raise SystemExit("GITHUB_TOKEN and GH_USER are required")
        days, langs = fetch_online(user, token)
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(render(days, langs, today))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
