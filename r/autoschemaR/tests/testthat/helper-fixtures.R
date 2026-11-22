fixture <- function() data.frame(row_id = 1:12, customer_id = rep(c("A", "B"), 6),
                                 city = rep(c("London", "Paris"), 6), check.names = FALSE)
new_output <- function() {
  path <- tempfile("autoschema-test-")
  withr::defer(unlink(path, recursive = TRUE), envir = parent.frame())
  path
}
expect_same_rows <- function(actual, expected) {
  expect_identical(names(actual), names(expected))
  canonical <- function(frame) sort(do.call(paste, c(lapply(frame, as.character), sep = "|")))
  expect_identical(canonical(actual), canonical(expected))
}

# Execute each SQL statement while respecting semicolons inside quoted strings.
execute_dump <- function(path) {
  sql <- rawToChar(readBin(path, "raw", n = file.info(path)$size))
  Encoding(sql) <- "UTF-8"
  chars <- strsplit(sql, "", fixed = TRUE)[[1L]]
  quoted <- FALSE
  statements <- character()
  begin <- 1L
  index <- 1L
  while (index <= length(chars)) {
    if (chars[index] == "'") {
      if (quoted && index < length(chars) && chars[index + 1L] == "'") {
        index <- index + 2L
        next
      }
      quoted <- !quoted
    }
    if (!quoted && chars[index] == ";") {
      statements <- c(statements, paste(chars[begin:index], collapse = ""))
      begin <- index + 1L
    }
    index <- index + 1L
  }
  con <- DBI::dbConnect(RSQLite::SQLite(), ":memory:")
  on.exit(DBI::dbDisconnect(con))
  for (statement in statements) DBI::dbExecute(con, statement)
  expect_equal(nrow(DBI::dbGetQuery(con, "PRAGMA foreign_key_check")), 0L)
  DBI::dbGetQuery(con, "SELECT * FROM dataset")
}

