.write_utf8_lines <- function(lines, path) {
  stream <- file(path, open = "wb")
  on.exit(close(stream))
  writeLines(enc2utf8(lines), stream, useBytes = TRUE)
}

.quote <- function(name) paste0('"', gsub('"', '""', name, fixed = TRUE), '"')

.check_destination <- function(out) {
  if (!.scalar_string(out)) .abort("out must be a nonempty directory path.", "autoschema_configuration_error")
  if (file.exists(out) || dir.exists(out)) {
    .abort("Output must be a new directory; existing paths are never overwritten.", "autoschema_output_error")
  }
}

# Compare exact typed row multisets, using a shared value dictionary per column.
.same_rows <- function(expected, actual) {
  if (!identical(names(expected), names(actual)) || nrow(expected) != nrow(actual) || anyNA(actual)) return(FALSE)
  for (name in names(expected)) {
    if (is.character(expected[[name]]) != is.character(actual[[name]])) return(FALSE)
  }
  combined <- rbind(expected, actual)
  keys <- .row_codes(.column_codes(combined))
  n <- nrow(expected)
  identical(sort(keys[seq_len(n)]), sort(keys[n + seq_len(n)]))
}

# Keep array fields as arrays even when they have zero or one element.
.json_report <- function(report) {
  arrays <- c("columns", "keys", "attributes", "selected_key", "records_columns",
              "determinant_columns", "warnings", "primary_key")
  walk <- function(value, field = "") {
    if (field == "primary_key_candidates") return(lapply(value, I))
    if (field %in% arrays) return(I(as.character(value)))
    if (!is.list(value)) return(value)
    if (is.null(names(value))) return(lapply(value, walk))
    for (name in names(value)) value[name] <- list(walk(value[[name]], name))
    value
  }
  walk(report)
}

.restore_report <- function(report) {
  arrays <- c("columns", "keys", "attributes", "selected_key", "records_columns",
              "determinant_columns", "warnings", "primary_key")
  walk <- function(value, field = "") {
    if (field == "primary_key_candidates") return(lapply(value, function(x) as.character(unlist(x))))
    if (field %in% arrays) return(as.character(unlist(value)))
    if (!is.list(value)) return(value)
    if (is.null(names(value))) return(lapply(value, walk))
    for (name in names(value)) value[name] <- list(walk(value[[name]], name))
    value
  }
  walk(report)
}

.write_artifacts <- function(analysis, output) {
  data <- analysis$data
  report <- analysis$report
  database <- file.path(output, "dataset.sqlite")
  con <- DBI::dbConnect(RSQLite::SQLite(), database, synchronous = "full")
  on.exit(DBI::dbDisconnect(con))
  DBI::dbExecute(con, "PRAGMA foreign_keys=ON")
  table_data <- lapply(report$tables, function(table) {
    selected <- data[table$columns]
    if (table$name == "records") selected else unique(selected)
  })
  names(table_data) <- vapply(report$tables, function(t) t$name, character(1))
  schema <- character()
  started <- proc.time()[["elapsed"]]
  DBI::dbWithTransaction(con, {
    for (table in report$tables) {
      definitions <- vapply(table$columns, function(column) {
        paste(.quote(column), .sql_type(data[[column]]))
      }, character(1))
      if (length(table$primary_key)) definitions <- c(definitions,
        paste0("PRIMARY KEY (", paste(.quote(table$primary_key), collapse = ", "), ")"))
      for (fk in table$foreign_keys) {
        columns <- paste(.quote(fk$columns), collapse = ", ")
        definitions <- c(definitions, paste0("FOREIGN KEY (", columns, ") REFERENCES ",
                                             .quote(fk$references), " (", columns, ")"))
      }
      ddl <- paste0("CREATE TABLE ", .quote(table$name), " (", paste(definitions, collapse = ", "), ");")
      DBI::dbExecute(con, ddl)
      DBI::dbAppendTable(con, table$name, table_data[[table$name]])
      schema <- c(schema, ddl)
    }
    owners <- setNames(rep("r", ncol(data)), names(data))
    joins <- character()
    for (index in seq_along(report$dimensions)) {
      dimension <- report$dimensions[[index]]
      alias <- paste0("d", index)
      owners[dimension$attributes] <- alias
      join_keys <- paste0("r.", .quote(dimension$keys), " = ", alias, ".", .quote(dimension$keys))
      joins <- c(joins, paste0("JOIN ", .quote(dimension$table), " AS ", alias, " ON ",
                               paste(join_keys, collapse = " AND ")))
    }
    select <- paste0(owners, ".", .quote(names(data)), " AS ", .quote(names(data)))
    view <- paste0("CREATE VIEW dataset AS SELECT ", paste(select, collapse = ", "),
                   " FROM records AS r ", paste(joins, collapse = " "), ";")
    DBI::dbExecute(con, view)
    schema <- c(schema, view)
    report$timings_seconds$write_database <- unname(proc.time()[["elapsed"]] - started)
    started <- proc.time()[["elapsed"]]
    if (!.same_rows(data, DBI::dbGetQuery(con, "SELECT * FROM dataset"))) {
      .abort("Reconstruction mismatch; no artifacts were published.", "autoschema_reconstruction_error")
    }
    if (nrow(DBI::dbGetQuery(con, "PRAGMA foreign_key_check"))) {
      .abort("Foreign-key validation failed.", "autoschema_reconstruction_error")
    }
    report$timings_seconds$validate <- unname(proc.time()[["elapsed"]] - started)
  })
  started <- proc.time()[["elapsed"]]
  .write_utf8_lines(schema, file.path(output, "schema.sql"))
  stream <- file(file.path(output, "dataset.sql"), open = "wb")
  tryCatch({
    writeLines(enc2utf8(c("BEGIN TRANSACTION;", head(schema, -1L))), stream, useBytes = TRUE)
    for (name in names(table_data)) {
      table <- table_data[[name]]
      readr::write_csv(table, file.path(output, paste0(name, ".csv")), na = "")
      # DBI quotes text; 17 significant digits preserve native R double values.
      literals <- lapply(table, function(x) {
        if (is.numeric(x)) sprintf("%.17g", x) else as.character(DBI::dbQuoteLiteral(con, x))
      })
      values <- do.call(paste, c(unname(literals), sep = ", "))
      writeLines(enc2utf8(paste0("INSERT INTO ", .quote(name), " VALUES (", values, ");")), stream, useBytes = TRUE)
    }
    writeLines(enc2utf8(c(tail(schema, 1L), "COMMIT;")), stream, useBytes = TRUE)
  }, finally = close(stream))
  report$timings_seconds$export <- unname(proc.time()[["elapsed"]] - started)
  report$database_bytes <- unname(file.info(database)$size)
  report["database_to_csv_ratio"] <- list(if (is.null(report$source$bytes) || !report$source$bytes) NULL else
    round(report$database_bytes / report$source$bytes, 3))
  report$reconstruction_exact <- TRUE
  report$timings_seconds <- lapply(report$timings_seconds, round, digits = 6L)
  report$processing_seconds <- round(sum(unlist(report$timings_seconds)), 6L)
  report
}

.publish <- function(analysis, out) {
  .check_destination(out)
  parent <- dirname(path.expand(out))
  if (!dir.exists(parent) && !dir.create(parent, recursive = TRUE)) stop("Cannot create output parent.")
  parent <- normalizePath(parent, winslash = "/", mustWork = TRUE)
  destination <- file.path(parent, basename(out))
  stage <- tempfile(".autoschemaR-", tmpdir = parent)
  if (!dir.create(stage)) stop("Cannot create staging directory.")
  on.exit(unlink(stage, recursive = TRUE))
  report <- .write_artifacts(analysis, stage)
  jsonlite::write_json(.json_report(report), file.path(stage, "schema.json"),
                      auto_unbox = TRUE, pretty = TRUE, null = "null", digits = NA)
  .write_utf8_lines(.render_report(report), file.path(stage, "report.html"))
  .check_destination(destination)
  if (!file.rename(stage, destination)) .abort("Cannot publish output directory.", "autoschema_output_error")
  .new_result(destination, report)
}
