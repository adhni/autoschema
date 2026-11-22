.new_result <- function(output, report) {
  output <- normalizePath(output, winslash = "/", mustWork = TRUE)
  structure(list(output_dir = output, database_path = file.path(output, "dataset.sqlite"),
                 report_path = file.path(output, "report.html"), report = report),
            class = "autoschema_result")
}

.assert_result <- function(result) {
  if (!inherits(result, "autoschema_result")) stop("result must be an autoschema_result.", call. = FALSE)
}

#' Work with conversion results and reopen saved output
#'
#' @param result An autoschema_result returned by a conversion or load_result.
#' @param name Physical table name, or the reconstructed dataset view.
#' @param sql SQL query to execute through a read-only SQLite connection.
#' @param parameters NULL, or a list of DBI bound parameters (for example list("C01")).
#' @param out Result directory or its schema.json file.
#' @return read_table and query return ordinary data.frames. load_result returns
#'   an autoschema_result without retaining a database connection.
#' @details load_result validates metadata, physical table names and view columns.
#'   It does not recompare rows against the original source or rerun inference.
#'   Move the complete result directory before loading if needed. SQLite reports
#'   from the Python library with format 1 are also readable; DuckDB is unsupported.
#'   Use explicit parameters instead of interpolating untrusted values into SQL.
#' @examples
#' out <- tempfile("autoschema-query-")
#' result <- convert_dataframe(data.frame(id = 1:3, category = c("A", "B", "A")), out)
#' query(result, "SELECT * FROM dataset WHERE category = ?", list("A"))
#' reopened <- load_result(out)
#' read_table(reopened)
#' unlink(out, recursive = TRUE)
#' @export
read_table <- function(result, name = "dataset") {
  .assert_result(result)
  if (!.scalar_string(name) || !name %in% c(names(result$report$table_rows), "dataset")) {
    stop("Unknown table.", call. = FALSE)
  }
  query(result, paste0("SELECT * FROM ", .quote(name)))
}

#' @rdname read_table
#' @export
query <- function(result, sql, parameters = NULL) {
  .assert_result(result)
  if (!.scalar_string(sql) || !nzchar(trimws(sql))) stop("sql must be a nonempty query.", call. = FALSE)
  con <- DBI::dbConnect(RSQLite::SQLite(), result$database_path, flags = RSQLite::SQLITE_RO)
  on.exit(DBI::dbDisconnect(con))
  DBI::dbExecute(con, "PRAGMA query_only=ON")
  if (is.null(parameters)) DBI::dbGetQuery(con, sql) else DBI::dbGetQuery(con, sql, params = parameters)
}

#' @rdname read_table
#' @export
load_result <- function(out) {
  if (!.scalar_string(out)) .abort("out must name a result directory.", "autoschema_invalid_result")
  if (basename(out) == "schema.json" && file.exists(out)) out <- dirname(out)
  report <- tryCatch(.restore_report(jsonlite::read_json(file.path(out, "schema.json"), simplifyVector = FALSE)),
                     error = function(e) .abort("Cannot read result metadata.", "autoschema_invalid_result"))
  valid <- is.list(report) && identical(report$engine, "sqlite") &&
    (is.null(report$report_format_version) || identical(as.numeric(report$report_format_version), 1)) &&
    isTRUE(report$reconstruction_exact) && is.character(report$columns) && length(report$columns) > 0L &&
    !anyNA(report$columns) && !any(!nzchar(report$columns)) && !anyDuplicated(tolower(report$columns)) &&
    is.list(report$table_rows) && "records" %in% names(report$table_rows) &&
    all(vapply(report$table_rows, function(n) is.numeric(n) && length(n) == 1L &&
                 !is.na(n) && is.finite(n) && n >= 0 && n == floor(n), logical(1)))
  if (!valid || !file.exists(file.path(out, "dataset.sqlite"))) {
    .abort("Incomplete or unsupported result; expected verified SQLite artifacts.", "autoschema_invalid_result")
  }
  result <- .new_result(out, report)
  tryCatch({
    con <- DBI::dbConnect(RSQLite::SQLite(), result$database_path, flags = RSQLite::SQLITE_RO)
    on.exit(DBI::dbDisconnect(con))
    DBI::dbExecute(con, "PRAGMA query_only=ON")
    for (name in names(report$table_rows)) DBI::dbGetQuery(con, paste0("SELECT * FROM ", .quote(name), " LIMIT 0"))
    if (!identical(names(DBI::dbGetQuery(con, "SELECT * FROM dataset LIMIT 0")), report$columns)) {
      stop("Reported columns do not match the dataset view.")
    }
  }, error = function(e) .abort(paste("Invalid database:", conditionMessage(e)), "autoschema_invalid_result"))
  result
}

#' Summarize and visualize a completed conversion
#' @param object,x An autoschema_result.
#' @param ... Reserved for S3 compatibility; passed to barplot by plot.
#' @param type Plot cell counts, stage timings, or actual file sizes.
#' @return summary returns the metadata list. print returns its input invisibly.
#'   plot draws a base R bar chart and invisibly returns the bar positions.
#' @details Cell counts measure repeated-value reduction, not byte compression.
#'   Byte comparisons require CSV input; DataFrame inputs have no source file size.
#' @export
summary.autoschema_result <- function(object, ...) {
  object$report
}

#' @rdname summary.autoschema_result
#' @export
print.autoschema_result <- function(x, ...) {
  report <- x$report
  cat(sprintf("AutoSchema R: %s rows x %s columns -> %s SQL tables\n",
              report$input_rows, report$input_columns, length(report$table_rows)))
  cat(sprintf("Exact reconstruction: %s | Stored cells reduced: %.2f%%\n",
              if (isTRUE(report$reconstruction_exact)) "PASS" else "unverified", report$cell_reduction_percent))
  cat("Database:", x$database_path, "\nReport:", x$report_path, "\n")
  invisible(x)
}

#' @rdname summary.autoschema_result
#' @export
plot.autoschema_result <- function(x, type = c("cells", "timings", "bytes"), ...) {
  type <- match.arg(type)
  report <- x$report
  if (type == "cells") {
    values <- c(Input = report$input_cells, Stored = report$stored_cells)
    title <- "Logical cell counts"
    label <- "Cells"
  } else if (type == "timings") {
    values <- unlist(report$timings_seconds)
    title <- "Processing stages"
    label <- "Seconds"
  } else {
    if (is.null(report$source$bytes)) stop("Byte comparison needs CSV input.", call. = FALSE)
    values <- c(CSV = report$source$bytes, Database = report$database_bytes) / 1024
    title <- "Actual file sizes (exports excluded)"
    label <- "KiB"
  }
  invisible(graphics::barplot(values, main = title, ylab = label, col = "#18755b", ...))
}
