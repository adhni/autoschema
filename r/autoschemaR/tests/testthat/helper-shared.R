.shared_options <- function(case) {
  options <- case$options
  if (!is.null(options$key_columns)) options$key_columns <- as.character(unlist(options$key_columns))
  options
}

.shared_lexical_rows <- function(frame) {
  values <- as.data.frame(lapply(frame, function(x) enc2utf8(as.character(x))),
                          stringsAsFactors = FALSE, check.names = FALSE)
  sort(apply(values, 1L, function(row) as.character(jsonlite::toJSON(
    unname(as.list(row)), auto_unbox = TRUE))))
}

.shared_has_dependency <- function(report, dependency) {
  any(vapply(report$dependencies, function(item) {
    setequal(item$keys, unlist(dependency$keys)) && all(unlist(dependency$attributes) %in% item$attributes)
  }, logical(1)))
}

.shared_expected <- function(case, fixtures) {
  if (!is.null(case$expected_records)) {
    values <- do.call(rbind, lapply(case$expected_records, function(row) as.character(unlist(row))))
    result <- as.data.frame(values, stringsAsFactors = FALSE, check.names = FALSE)
    names(result) <- as.character(unlist(case$expected$columns))
    return(result)
  }
  delimiter <- if (is.null(case$options$delimiter)) "," else case$options$delimiter
  utils::read.csv(file.path(fixtures, case$file), sep = delimiter,
                  colClasses = "character", na.strings = NULL, check.names = FALSE,
                  row.names = NULL, fileEncoding = "UTF-8-BOM", fill = FALSE)
}

.shared_check_case <- function(case, fixtures, parent) {
  source <- file.path(fixtures, case$file)
  stopifnot(unname(tools::md5sum(source)) == case$md5)
  output <- file.path(parent, case$id)
  options <- .shared_options(case)
  if (!is.null(case$expected_error)) {
    for (fun in list(autoschemaR::preview_csv, autoschemaR::convert_csv)) {
      arguments <- c(list(csv_path = source), options)
      if (identical(fun, autoschemaR::convert_csv)) arguments$out <- output
      error <- tryCatch({ do.call(fun, arguments); NULL }, error = identity)
      stopifnot(inherits(error, "autoschema_invalid_data"), !dir.exists(output))
    }
    return(list(id = case$id, status = "pass", outcome = "rejected_invalid_data"))
  }
  preview <- do.call(autoschemaR::preview_csv, c(list(csv_path = source), options))
  stopifnot(is.null(preview$reconstruction_exact), is.null(preview$database_bytes), !dir.exists(output))
  started <- proc.time()[["elapsed"]]
  result <- do.call(autoschemaR::convert_csv, c(list(csv_path = source, out = output), options))
  elapsed <- unname(proc.time()[["elapsed"]] - started)
  report <- summary(result)
  for (name in c("tables", "table_rows", "selected_key", "dimensions", "stored_cells")) {
    stopifnot(identical(preview[[name]], report[[name]]))
  }
  expected <- .shared_expected(case, fixtures)
  actual <- autoschemaR::read_table(result)
  stopifnot(identical(names(actual), as.character(unlist(case$expected$columns))),
            identical(names(actual), names(expected)), nrow(actual) == case$expected$rows,
            identical(.shared_lexical_rows(actual), .shared_lexical_rows(expected)),
            isTRUE(report$reconstruction_exact), report$blank_cells == case$expected$blank_cells,
            report$duplicate_rows == case$expected$duplicate_rows)
  reopened <- autoschemaR::load_result(output)
  stopifnot(identical(.shared_lexical_rows(autoschemaR::read_table(reopened)), .shared_lexical_rows(expected)))
  if (!is.null(options$key_columns)) stopifnot(identical(report$selected_key, options$key_columns))
  for (dependency in case$required_dependencies) stopifnot(.shared_has_dependency(report, dependency))
  for (dependency in case$forbidden_dependencies) stopifnot(!.shared_has_dependency(report, dependency))
  if (!is.null(case$expected_dimensions)) stopifnot(length(report$dimensions) == case$expected_dimensions)
  if (isTRUE(case$expect_search_warning)) stopifnot(any(grepl("budget|limited", report$warnings)))
  max_checks <- if (is.null(options$max_checks)) 2000L else options$max_checks
  stopifnot(report$search$dependency_checks <= max_checks, report$search$key_checks <= max_checks,
            all(file.exists(file.path(output, c("dataset.sql", "schema.sql", "schema.json", "report.html")))))
  list(id = case$id, status = "pass", outcome = "converted", conversion_seconds = round(elapsed, 6L),
       rows = report$input_rows, columns = report$input_columns, tables = length(report$tables),
       cell_reduction_percent = report$cell_reduction_percent)
}
