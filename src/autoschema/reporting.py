"""Self-contained HTML reports: no server, network requests or JS libraries."""

from html import escape


def render_report(report):
    def text(value):
        return escape(str(value), quote=True)

    def number(value):
        return f"{value:,}"

    def size(value):
        return "Not measured" if value is None else f"{value / 1024:,.1f} KiB"

    def bar(label, value, maximum, annotation=""):
        width = 100 * value / max(maximum, 1)
        return f'<div class="bar-row"><span>{text(label)}</span><div class="track"><div class="fill" style="width:{width:.2f}%"></div></div><strong>{text(annotation or number(value))}</strong></div>'

    stages = [
        ("read", "Read", f"{number(report['input_rows'])} rows"),
        ("profile", "Profile", f"{report['input_columns']} columns"),
        ("discover", "Discover", f"{len(report['dependencies'])} dependencies"),
        ("plan", "Plan", f"{len(report['tables'])} tables"),
        ("write_database", "Write", report["engine"]),
        ("validate", "Verify", "Exact reconstruction"),
        ("export", "Export", "SQL + CSV"),
    ]
    pipeline = "".join(
        f'<div class="stage"><small>0{i + 1}</small><h3>{title}</h3><p>{text(detail)}</p><span>{report["timings_seconds"][key]:.3f}s</span></div>'
        for i, (key, title, detail) in enumerate(stages)
    )
    cards = []
    for table in report["tables"]:
        columns = "".join(
            f"<li><code>{text(c)}</code>"
            + (' <span class="tag">PK</span>' if c in table["primary_key"] else "")
            + (
                ' <span class="tag fk">FK</span>'
                if any(c in fk["columns"] for fk in table["foreign_keys"])
                else ""
            )
            + "</li>"
            for c in table["columns"]
        )
        joins = "".join(
            '<p class="join">'
            + text(", ".join(fk["columns"]))
            + " → "
            + text(fk["references"])
            + "</p>"
            for fk in table["foreign_keys"]
        )
        kind = "Fact table" if table["name"] == "records" else "Dimension"
        cards.append(
            f'<article class="table-card"><small>{kind}</small><h3>{text(table["name"])}</h3><p>{number(table["rows"])} rows · {len(table["columns"])} columns</p><ul>{columns}</ul>{joins}</article>'
        )
    dependencies = (
        "".join(
            "<tr><td><code>"
            + text(" + ".join(d["keys"]))
            + "</code></td><td>"
            + text(", ".join(d["attributes"]))
            + f"</td><td>{number(d['distinct_keys'])}</td></tr>"
            for d in report["dependencies"]
        )
        or '<tr><td colspan="3">No nontrivial dependencies found within the search bounds.</td></tr>'
    )
    profiles = "".join(
        "<tr><td><code>"
        + text(p["name"])
        + f"</code></td><td>{p['sql_type']}</td><td>{number(p['distinct'])}</td><td>{p['distinct_percent']:.1f}%</td><td>{number(p['blank_count'])}</td><td>"
        + (text(f"{p['min']:,.4g} / {p['mean']:,.4g} / {p['max']:,.4g}") if "mean" in p else "—")
        + "</td></tr>"
        for p in report["column_profiles"]
    )
    warnings = "".join(f"<li>{text(warning)}</li>" for warning in report["warnings"])
    file_links = "".join(
        f'<a href="{text(t["name"])}.csv">{text(t["name"])}.csv</a>' for t in report["tables"]
    )
    bytes_comparison = ""
    if report["source"]["bytes"]:
        maximum = max(report["source"]["bytes"], report["database_bytes"])
        bytes_comparison = (
            "<h3>Actual file sizes</h3>"
            + bar("Source CSV", report["source"]["bytes"], maximum, size(report["source"]["bytes"]))
            + bar("Database", report["database_bytes"], maximum, size(report["database_bytes"]))
        )
        bytes_comparison += f'<p class="muted">Database / CSV: {report["database_to_csv_ratio"]:.3f}×. SQL and CSV exports are additional files, excluded from this comparison.</p>'
    sql_key = ", ".join(report["selected_key"]) or "None found"
    stats = [
        (number(report["input_rows"]), "Input rows"),
        (str(report["input_columns"]), "Input columns"),
        (str(len(report["tables"])), "SQL tables"),
        (f"{report['cell_reduction_percent']:.1f}%", "Fewer stored cells"),
    ]
    metric_cards = "".join(
        f'<div class="metric"><strong>{text(value)}</strong><span>{label}</span></div>'
        for value, label in stats
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AutoSchema · {text(report["source"]["name"])}</title>
<style>
:root{{--ink:#172a34;--muted:#526970;--green:#11634f;--line:#d6e2df;--bg:#f2f6f3;--card:#fff}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,sans-serif}}main{{max-width:1220px;margin:auto;padding:46px 26px}}h1{{font-size:clamp(32px,5vw,52px);line-height:1.12;margin:12px 0}}h2{{font-size:23px;margin:0 0 12px}}h3{{margin:4px 0 8px;font-size:17px;overflow-wrap:anywhere}}p{{margin:8px 0}}.eyebrow,small{{text-transform:uppercase;letter-spacing:.12em;font-size:11px;font-weight:700;color:var(--green)}}.muted{{color:var(--muted)}}.badge{{display:inline-block;padding:5px 12px;background:#dbf3e5;color:#075e3e;border-radius:30px;font-weight:600}}header{{margin-bottom:30px}}section{{background:var(--card);padding:25px;border:1px solid var(--line);border-radius:14px;margin:20px 0}}.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}.metric{{background:var(--card);padding:20px;border:1px solid var(--line);border-radius:12px}}.metric strong{{display:block;font-size:32px;color:var(--green)}}.metric span{{color:var(--muted)}}.pipeline{{display:grid;grid-template-columns:repeat(7,1fr);gap:10px}}.stage{{background:#edf5f0;border-radius:9px;padding:12px;border-top:3px solid #23846b}}.stage p{{font-size:12px;min-height:40px}}.stage span{{font-variant-numeric:tabular-nums;color:var(--muted);font-size:12px}}.table-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(245px,1fr));gap:15px;margin-top:20px}}.table-card{{border:1px solid var(--line);border-radius:10px;padding:18px;background:#f9fcfa}}.table-card ul{{list-style:none;padding:0;margin:12px 0}}.table-card li{{border-top:1px solid #e0e9e4;padding:5px 0;overflow-wrap:anywhere}}code{{font:13px ui-monospace,monospace}}.tag{{font-size:10px;padding:2px 5px;background:#d8ede1;border-radius:4px;color:#174b37}}.fk{{background:#dcecf7;color:#174b6f}}.join{{font-size:12px;color:#235a73;overflow-wrap:anywhere}}.view{{padding:15px;background:#e7f3ee;border-radius:8px;text-align:center;margin-top:18px}}.bar-row{{display:grid;grid-template-columns:110px 1fr 100px;gap:12px;align-items:center;margin:14px 0;font-size:13px}}.track{{height:21px;background:#eaf0ec;border-radius:5px;overflow:hidden}}.fill{{height:100%;background:#298369;border-radius:5px}}.bar-row strong{{text-align:right;font-size:12px}}.scroll{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:13px;text-align:left}}th,td{{padding:11px 10px;border-bottom:1px solid #e0e8e3;vertical-align:top}}th{{font-size:11px;text-transform:uppercase;color:var(--muted);white-space:nowrap}}input{{width:min(100%,400px);padding:10px 12px;border:1px solid #bdcec5;border-radius:8px;font:inherit;margin:6px 0 14px}}a{{color:#146e56;text-decoration:underline;text-underline-offset:3px}}.files{{display:flex;flex-wrap:wrap;gap:12px}}footer{{color:var(--muted);font-size:12px;padding:10px 0}}details summary{{cursor:pointer;font-weight:700}}li{{margin:4px 0}}@media(max-width:800px){{.pipeline{{grid-template-columns:repeat(3,1fr)}}.metrics{{grid-template-columns:repeat(2,1fr)}}main{{padding:25px 14px}}section{{padding:18px}}}}@media print{{body{{background:white}}section,.metric{{break-inside:avoid}}input{{display:none}}}}
</style></head><body><main>
<header><span class="eyebrow">AutoSchema · processing report</span><h1>From rows to relationships.</h1><p class="muted">{text(report["source"]["name"])} · {text(report["engine"])} · {report["processing_seconds"]:.3f}s processing time, excluding report rendering</p><span class="badge">✓ Exact reconstruction verified</span></header>
<div class="metrics">{metric_cards}</div>
<section><h2>How the data was processed</h2><p class="muted">Exact observed dependencies become dimension tables when moving attributes saves stored cells. A joining view recovers the original rows.</p><div class="pipeline">{pipeline}</div></section>
<section><h2>Inferred tables and relationships</h2><p class="muted">Primary key in records: <code>{text(sql_key)}</code>. PK marks a primary-key column; FK marks a foreign-key column. Multiple PK or FK columns form a composite key.</p><div class="table-grid">{"".join(cards)}</div><div class="view"><strong>dataset</strong> view ← records JOIN dimension tables<br><span class="muted">{number(report["input_rows"])} reconstructed rows · {report["input_columns"]} original columns · duplicates preserved · row order unspecified</span></div></section>
<section><h2>Reduction and storage</h2>{bar("Input cells", report["input_cells"], report["input_cells"])}{bar("Stored cells", report["stored_cells"], report["input_cells"])}<p class="muted">Cells = rows × columns across physical tables, including repeated keys. This measures fewer repeated values, not byte compression.</p>{bytes_comparison}</section>
<section><h2>Column profiles</h2><p class="muted">{number(report["duplicate_rows"])} duplicate rows beyond the first occurrence · {number(report["blank_cells"])} blank cells. Numeric statistics are shown only for columns safely inferred as numeric.</p><label for="column-filter">Find a column</label><br><input id="column-filter" type="search" placeholder="Type a column name…"><div class="scroll"><table id="profiles"><thead><tr><th>Column</th><th>SQL type</th><th>Distinct</th><th>Distinct %</th><th>Blanks</th><th>Min / Mean / Max</th></tr></thead><tbody>{profiles}</tbody></table></div></section>
<section><details><summary>Discovered dependencies ({len(report["dependencies"])}) and search bounds</summary><p class="muted">Determinant width ≤ {report["search"]["max_dependency_width"]}; key width ≤ {report["search"]["max_key_width"]}; up to {report["search"]["max_candidate_columns"]} determinant columns. Checked {report["search"]["dependency_checks"]} dependency candidates and {report["search"]["key_checks"]} key candidates. A + between determinant columns means they act together.</p><div class="scroll"><table><thead><tr><th>Determines</th><th>Attributes</th><th>Distinct keys</th></tr></thead><tbody>{dependencies}</tbody></table></div></details></section>
<section><h2>Files you can inspect</h2><div class="files"><a href="schema.sql">schema.sql</a><a href="dataset.sql">dataset.sql (schema + data)</a><a href="schema.json">schema.json (full statistics)</a>{file_links}</div><p class="muted">Files are relative to this report. The SQL export targets the same engine as the database.</p></section>
<section><h2>Interpretation and limits</h2><ul>{warnings}</ul></section>
<footer>AutoSchema {text(report["version"])} · Self-contained report. No external scripts, fonts, analytics or network requests.</footer>
</main><script>document.getElementById('column-filter').addEventListener('input', function() {{ const term = this.value.toLowerCase(); document.querySelectorAll('#profiles tbody tr').forEach(row => {{ row.hidden = !row.cells[0].textContent.toLowerCase().includes(term); }}); }});</script></body></html>"""
