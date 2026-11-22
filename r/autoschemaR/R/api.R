.read_csv <- function(csv_path, delimiter, encoding) {
  if (!.scalar_string(csv_path) || !file.exists(csv_path) || dir.exists(csv_path)) {
    .abort("csv_path must name an existing file.")
  }
  if (!.scalar_string(delimiter) || nchar(delimiter, type = "bytes") != 1L ||
      delimiter %in% c("\r", "\n", '"')) {
    .abort("delimiter must be one byte, excluding newline and double quote.",
           "autoschema_configuration_error")
  }
  if (!.scalar_string(encoding)) .abort("encoding must be a text encoding name.", "autoschema_configuration_error")
  locale <- tryCatch(withCallingHandlers(
    readr::locale(encoding = encoding),
    warning = function(w) .abort(conditionMessage(w), "autoschema_configuration_error")
  ), error = function(e) {
    .abort(conditionMessage(e), "autoschema_configuration_error")
  })
  stream <- file(csv_path, "rb")
  on.exit(close(stream))
  repeat {
    bytes <- readBin(stream, "raw", n = 1048576L)
    if (!length(bytes)) break
    if (any(bytes == as.raw(0))) .abort("CSV files containing NUL bytes are unsupported.")
  }
  frame <- tryCatch(suppressWarnings(readr::read_delim(
    csv_path, delim = delimiter, col_types = readr::cols(.default = readr::col_character()),
    na = character(), trim_ws = FALSE, name_repair = "minimal", locale = locale,
    num_threads = 1L, lazy = FALSE, show_col_types = FALSE, progress = FALSE
  )), error = function(e) .abort(paste("Invalid CSV:", conditionMessage(e))))
  if (nrow(readr::problems(frame))) .abort("Invalid CSV: malformed fields or inconsistent record widths.")
  as.data.frame(frame, stringsAsFactors = FALSE, check.names = FALSE)
}

.analyze <- function(frame, source, max_dependency_width, max_key_width,
                     max_candidate_columns, max_checks, key_columns, read_seconds = 0) {
  clock <- function() unname(proc.time()[["elapsed"]])
  started <- clock()
  data <- .normalize(frame)
  profile <- .profile(data)
  timings <- list(read = read_seconds, profile = clock() - started)
  started <- clock()
  candidates <- .candidates(names(data), max_candidate_columns)
  search <- .discover(data, candidates, max_dependency_width, max_checks)
  timings$discover <- clock() - started
  started <- clock()
  if (!is.null(key_columns)) .find_keys(data, character(), max_key_width, max_checks, key_columns)
  plan <- .plan(data, search$dependencies, key_columns)
  key_search <- .find_keys(data[plan$remaining], .candidates(plan$remaining, max_candidate_columns),
                           max_key_width, max_checks, key_columns)
  selected <- if (length(key_search$keys)) key_search$keys[[1L]] else character()
  tables <- lapply(plan$dimensions, function(d) list(
    name = d$table, rows = d$rows, columns = c(d$keys, d$attributes),
    primary_key = d$keys, foreign_keys = list(), cells = d$rows * (length(d$keys) + length(d$attributes))))
  tables[[length(tables) + 1L]] <- list(
    name = "records", rows = nrow(data), columns = plan$remaining, primary_key = selected,
    foreign_keys = lapply(plan$dimensions, function(d) list(columns = d$keys, references = d$table)),
    cells = nrow(data) * length(plan$remaining))
  timings$plan <- clock() - started
  warnings <- c(
    "Dependencies describe this input; review relationships before using them with future data.",
    "Processing and exact reconstruction verification hold the complete dataset in memory.")
  if (length(candidates) < ncol(data)) warnings <- c(warnings, "Candidate columns were limited by the search budget.")
  if (search$truncated || key_search$truncated) warnings <- c(warnings, "A search budget was reached; more dependencies or keys may exist.")
  if (!length(selected)) warnings <- c(warnings, "No primary key found within the search bounds; duplicate rows are preserved.")
  if (length(selected) && !any(.identifier(selected)) && is.null(key_columns)) warnings <- c(warnings, "Inferred key has no identifier-like name; consider key_columns.")
  if (!length(plan$dimensions)) warnings <- c(warnings, "No beneficial decomposition found; all columns remain in records.")
  stored_cells <- sum(vapply(tables, function(t) t$cells, numeric(1)))
  report <- list(
    version = as.character(utils::packageVersion("autoschemaR")), implementation = "R",
    report_format_version = 1L, engine = "sqlite", miner = "R", source = source,
    input_rows = nrow(data), input_columns = ncol(data), columns = names(data),
    duplicate_rows = sum(duplicated(data)), blank_cells = sum(vapply(profile, function(p) p$blank_count, numeric(1))),
    column_profiles = profile,
    cardinality = setNames(lapply(profile, function(p) p$distinct), names(data)),
    dependencies = search$dependencies, primary_key_candidates = key_search$keys,
    selected_key = selected, dimensions = plan$dimensions, records_columns = plan$remaining,
    tables = tables, table_rows = setNames(lapply(tables, function(t) t$rows),
                                          vapply(tables, function(t) t$name, character(1))),
    input_cells = nrow(data) * ncol(data), stored_cells = stored_cells,
    cell_reduction_percent = round(100 * (1 - stored_cells / (nrow(data) * ncol(data))), 2),
    database_bytes = NULL, database_to_csv_ratio = NULL, reconstruction_exact = NULL,
    row_order_preserved = FALSE,
    search = list(max_dependency_width = max_dependency_width, max_key_width = max_key_width,
                  max_candidate_columns = max_candidate_columns, max_checks = max_checks,
                  determinant_columns = candidates, dependency_checks = search$checks,
                  key_checks = key_search$checks, dependency_budget_reached = search$truncated,
                  key_budget_reached = key_search$truncated),
    timings_seconds = timings, processing_seconds = sum(unlist(timings)), warnings = warnings)
  list(data = data, report = report)
}

#' Preview or convert tabular data into inferred SQLite tables
#'
#' All inference runs natively in R. Preview functions write no files. Conversion
#' builds a SQLite database, verifies the reconstructed row multiset, then
#' publishes a completed output directory with SQL, CSV, JSON and HTML exports.
#'
#' @param csv_path Path to a CSV with a unique, nonempty header.
#' @param frame A data.frame; factors are accepted, list/matrix/complex columns are not.
#' @param out New output directory; existing paths are never replaced.
#' @param max_dependency_width Maximum determinant columns, 1 to 3.
#' @param max_key_width Maximum inferred primary-key columns, 1 to 3.
#' @param max_candidate_columns Positive candidate-column limit, identifiers first.
#' @param max_checks Positive maximum candidates per dependency/key search.
#' @param key_columns NULL for inference or a character vector of unique, nonblank key columns.
#' @param delimiter One-byte CSV separator, excluding double quote and newline.
#' @param encoding Input encoding (default UTF-8; BOMs are accepted).
#' @return Preview functions return a JSON-compatible list of proposed tables,
#'   profiles, keys, dependencies and cell savings. Database size and reconstruction
#'   status are NULL until conversion. Conversion functions return an
#'   \code{autoschema_result}; use \code{summary()}, \code{read_table()} and \code{query()}.
#' @details Missing values become empty strings. Text is converted to numeric only
#'   when it round-trips through R's character representation. Integers outside
#'   R's 32-bit integer range remain text when read from CSV. Finite native R
#'   numeric columns without missing values retain their numeric precision. Original dtypes, byte formatting and row
#'   order are not preserved; duplicate multiplicities and logical values are.
#'   Dependencies are exact observed patterns, not proven domain rules. Search is
#'   bounded and the greedy star-schema plan is not guaranteed optimal or 3NF/BCNF.
#'   The complete input and verification data must fit in memory. SQL writes happen
#'   only during conversion; preview does not verify SQL reconstruction. Rerun
#'   conversion with the same input/options after review. Editing a preview does
#'   not configure conversion. SQLite is the supported engine in this version.
#'   Errors inherit from \code{autoschema_error}, with configuration, invalid-data,
#'   output, reconstruction and invalid-result subclasses.
#' @examples
#' frame <- data.frame(row_id = 1:12, customer_id = rep(c("A", "B"), 6),
#'                     city = rep(c("London", "Paris"), 6))
#' plan <- preview_dataframe(frame, key_columns = "row_id")
#' plan$table_rows
#' destination <- tempfile("autoschema-example-")
#' result <- convert_dataframe(frame, destination, key_columns = "row_id")
#' summary(result)$reconstruction_exact
#' read_table(result)
#' unlink(destination, recursive = TRUE)
#' @export
preview_dataframe <- function(frame, max_dependency_width = 2L, max_key_width = 2L,
                              max_candidate_columns = 30L, max_checks = 2000L,
                              key_columns = NULL) {
  .validate_options(max_dependency_width, max_key_width, max_candidate_columns, max_checks, key_columns)
  .analyze(frame, list(kind = "dataframe", name = "data.frame", bytes = NULL),
           max_dependency_width, max_key_width, max_candidate_columns, max_checks, key_columns)$report
}

#' @rdname preview_dataframe
#' @export
preview_csv <- function(csv_path, max_dependency_width = 2L, max_key_width = 2L,
                        max_candidate_columns = 30L, max_checks = 2000L,
                        key_columns = NULL, delimiter = ",", encoding = "UTF-8") {
  .validate_options(max_dependency_width, max_key_width, max_candidate_columns, max_checks, key_columns)
  started <- proc.time()[["elapsed"]]
  frame <- .read_csv(csv_path, delimiter, encoding)
  .analyze(frame, list(kind = "csv", name = basename(csv_path), bytes = unname(file.info(csv_path)$size)),
           max_dependency_width, max_key_width, max_candidate_columns, max_checks, key_columns,
           proc.time()[["elapsed"]] - started)$report
}

#' @rdname preview_dataframe
#' @export
convert_dataframe <- function(frame, out = "output", max_dependency_width = 2L, max_key_width = 2L,
                              max_candidate_columns = 30L, max_checks = 2000L,
                              key_columns = NULL) {
  .validate_options(max_dependency_width, max_key_width, max_candidate_columns, max_checks, key_columns)
  .check_destination(out)
  analysis <- .analyze(frame, list(kind = "dataframe", name = "data.frame", bytes = NULL),
                       max_dependency_width, max_key_width, max_candidate_columns, max_checks, key_columns)
  .publish(analysis, out)
}

#' @rdname preview_dataframe
#' @export
convert_csv <- function(csv_path, out = "output", max_dependency_width = 2L, max_key_width = 2L,
                        max_candidate_columns = 30L, max_checks = 2000L,
                        key_columns = NULL, delimiter = ",", encoding = "UTF-8") {
  .validate_options(max_dependency_width, max_key_width, max_candidate_columns, max_checks, key_columns)
  .check_destination(out)
  started <- proc.time()[["elapsed"]]
  frame <- .read_csv(csv_path, delimiter, encoding)
  analysis <- .analyze(frame, list(kind = "csv", name = basename(csv_path), bytes = unname(file.info(csv_path)$size)),
                       max_dependency_width, max_key_width, max_candidate_columns, max_checks, key_columns,
                       proc.time()[["elapsed"]] - started)
  .publish(analysis, out)
}
