# Shared across every page. Uses prefers-color-scheme so it looks right
# in both light and dark mode without any JavaScript or external
# stylesheet - the ESP32 has no internet access to fetch one anyway.
# Lives in its own module (rather than in webserver.py) so every page
# module can import it without creating a circular import with
# WebServer.webserver, which imports the page modules.
STYLE = """<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {
  color-scheme: light dark;
  --bg: #f4f5f6;
  --fg: #1c1f22;
  --muted: #5b6470;
  --card: #ffffff;
  --border: #dde1e4;
  --accent: #2f7d6e;
  --accent-fg: #ffffff;
  --stripe: #eef1f2;
  --error: #b3392c;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #15181b;
    --fg: #e7e9ea;
    --muted: #9aa4ac;
    --card: #1f2327;
    --border: #333a40;
    --accent: #52b3a0;
    --accent-fg: #0d1513;
    --stripe: #272c31;
    --error: #e0806f;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 1.5rem 1rem;
  background: var(--bg);
  color: var(--fg);
  font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.5;
}
.card {
  max-width: 640px;
  margin: 0 auto;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.25rem 1.5rem 1.5rem;
}
h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
h2 { font-size: 1.05rem; margin: 1.5rem 0 .5rem; padding-top: 1rem; border-top: 1px solid var(--border); }
h2:first-of-type { margin-top: .75rem; padding-top: 0; border-top: none; }
a { color: var(--accent); }
nav, .nav { margin-top: 1.5rem; padding-top: 1rem; border-top: 1px solid var(--border); font-size: .9rem; color: var(--muted); }
label { display: block; margin: .75rem 0 .25rem; font-size: .85rem; color: var(--muted); }
label.check { display: flex; align-items: center; gap: .5rem; margin: .5rem 0; font-size: .95rem; color: var(--fg); }
label.check input { width: auto; }
input[type=text], input[type=password], input[type=number], select {
  width: 100%;
  padding: .5rem .6rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
  color: var(--fg);
  font-size: 1rem;
}
input:focus, select:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
button {
  margin-top: 1rem;
  padding: .55rem 1.3rem;
  border: none;
  border-radius: 8px;
  background: var(--accent);
  color: var(--accent-fg);
  font-size: 1rem;
  cursor: pointer;
}
button:active { opacity: .85; }
table { width: 100%; border-collapse: collapse; margin-top: .5rem; font-size: .85rem; }
th, td { padding: .4rem .5rem; text-align: left; border-bottom: 1px solid var(--border); }
tr:nth-child(even) td { background: var(--stripe); }
.msg { padding: .6rem .9rem; border-radius: 8px; background: var(--stripe); margin: .75rem 0; }
.msg.err { color: var(--error); }
svg rect { fill: var(--accent); }
svg text { fill: var(--fg); }
</style>"""
