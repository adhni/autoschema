.html <- function(value) {
  text <- paste(as.character(value), collapse = ", ")
  for (pair in list(c("&", "&amp;"), c("<", "&lt;"), c(">", "&gt;"),
                    c('"', "&quot;"), c("'", "&#39;"))) {
    text <- gsub(pair[1L], pair[2L], text, fixed = TRUE)
  }
  text
}

.render_report <- function(report) {
  card <- function(value, label) paste0('<div class="card"><strong>', .html(value),
                                        '</strong><br>', label, '</div>')
  cards <- paste0(card(report$input_rows, "Input rows"), card(report$input_columns, "Input columns"),
                   card(length(report$tables), "SQL tables"),
                   card(paste0(report$cell_reduction_percent, "%"), "Fewer stored cells"))
  bar <- function(label, value, maximum, unit = "") {
    paste0('<div class="bar"><span>', .html(label), '</span><div class="track"><i style="width:',
           sprintf("%.3f", 100 * value / max(maximum, 1)), '%"></i></div><b>',
           .html(paste(format(value, trim = TRUE, big.mark = ","), unit)), '</b></div>')
  }
  cells <- paste0(bar("Input cells", report$input_cells, report$input_cells),
                   bar("Stored cells", report$stored_cells, report$input_cells))
  bytes <- if (!is.null(report$source$bytes)) {
    maximum <- max(report$source$bytes, report$database_bytes) / 1024
    paste0('<h3>Actual file sizes</h3>', bar("Source CSV", report$source$bytes / 1024, maximum, "KiB"),
           bar("SQLite database", report$database_bytes / 1024, maximum, "KiB"),
           '<p>SQL and CSV exports are additional files, excluded here.</p>')
  } else ""
  timings <- unlist(report$timings_seconds)
  stages <- paste(vapply(names(timings), function(name) bar(name, timings[[name]], max(timings), "s"),
                         character(1)), collapse = "")
  tables <- paste(vapply(report$tables, function(table) {
    columns <- paste(vapply(table$columns, function(column) {
      pk <- if (column %in% table$primary_key) " <b>PK</b>" else ""
      fk <- if (any(vapply(table$foreign_keys, function(f) column %in% f$columns, logical(1)))) " <b>FK</b>" else ""
      paste0("<li><code>", .html(column), "</code>", pk, fk, "</li>")
    }, character(1)), collapse = "")
    joins <- paste(vapply(table$foreign_keys, function(fk) paste0("<p>", .html(fk$columns),
                                                                 " &rarr; ", .html(fk$references), "</p>"), character(1)), collapse = "")
    paste0('<article><h3>', .html(table$name), '</h3><p>', table$rows, ' rows</p><ul>',
           columns, '</ul>', joins, '</article>')
  }, character(1)), collapse = "")
  profiles <- paste(vapply(report$column_profiles, function(profile) {
    stats <- if (is.null(profile$mean)) "-" else paste(signif(c(profile$min, profile$mean, profile$max), 5), collapse = " / ")
    paste0("<tr><td>", .html(profile$name), "</td><td>", .html(profile$sql_type), "</td><td>",
           profile$distinct, "</td><td>", profile$blank_count, "</td><td>", .html(stats), "</td></tr>")
  }, character(1)), collapse = "")
  dependencies <- paste(vapply(report$dependencies, function(d) paste0("<li><code>", .html(d$keys),
                                                                                     " &rarr; ", .html(d$attributes), "</code></li>"), character(1)), collapse = "")
  warnings <- paste0("<li>", vapply(report$warnings, .html, character(1)), "</li>", collapse = "")
  links <- paste0('<a href="', vapply(names(report$table_rows), .html, character(1)), '.csv">',
                   vapply(names(report$table_rows), .html, character(1)), '.csv</a>', collapse = " ")
  paste0('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
    '<title>AutoSchema R - ', .html(report$source$name), '</title><style>',
    '*{box-sizing:border-box}body{margin:0;background:#f1f6f3;color:#19382d;font:15px/1.6 system-ui,sans-serif}',
    'main{max-width:1100px;margin:auto;padding:32px 20px}h1{font-size:40px;line-height:1.15}h2{font-size:24px}h3{overflow-wrap:anywhere}article{min-width:0}',
    'section,.card,article{background:white;border:1px solid #d6e3da;border-radius:12px;padding:20px;margin:16px 0}',
    '.metrics,.tables{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}.card strong{font-size:30px}',
    '.bar{display:grid;grid-template-columns:140px 1fr 130px;gap:12px;align-items:center;margin:12px 0}.track{background:#e4eee7;height:20px;border-radius:4px}',
    '.track i{display:block;background:#18755b;height:100%;border-radius:4px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse}',
    'td,th{padding:10px;text-align:left;border-bottom:1px solid #dae5de}code,li{overflow-wrap:anywhere}a{color:#11614a;margin-right:8px}',
    '@media(max-width:600px){.bar{grid-template-columns:100px 1fr 80px;font-size:12px}h1{font-size:30px}}',
    '</style></head><body><main><header><p>AutoSchema R ', .html(report$version), '</p><h1>From rows to relationships.</h1><p>',
    .html(report$source$name), ' &middot; SQLite &middot; Exact reconstruction verified</p></header><div class="metrics">', cards,
    '</div><section><h2>Processing stages</h2><p>Read &rarr; profile &rarr; discover &rarr; plan &rarr; write &rarr; verify &rarr; export</p>', stages,
    '</section><section><h2>Tables and relationships</h2><p>PK = primary key; FK = foreign key. Multiple columns form composite keys.</p><div class="tables">', tables,
    '</div><p>The <code>dataset</code> view joins records to dimensions to reconstruct the original columns. Row order is unspecified.</p></section>',
    '<section><h2>Reduction and storage</h2>', cells, '<p>Cell counts measure repeated values, not byte compression.</p>', bytes,
    '</section><section><h2>Column statistics</h2><p>', report$duplicate_rows, ' duplicate rows; ', report$blank_cells,
    ' blank cells.</p><div class="scroll"><table><thead><tr><th>Column</th><th>SQL type</th><th>Distinct</th><th>Blanks</th><th>Min / Mean / Max</th></tr></thead><tbody>', profiles,
    '</tbody></table></div></section><section><h2>Discovered dependencies</h2><ul>', dependencies,
    '</ul><p>Checked ', report$search$dependency_checks, ' dependency candidates and ', report$search$key_checks, ' key candidates.</p></section>',
    '<section><h2>Output files</h2><a href="dataset.sqlite">SQLite database</a><a href="dataset.sql">Complete SQL</a><a href="schema.sql">Schema</a><a href="schema.json">Statistics</a>', links,
    '</section><section><h2>Interpretation and limits</h2><ul>', warnings,
    '</ul></section><footer>Generated natively in R. No external scripts, fonts or network requests.</footer></main></body></html>')
}
