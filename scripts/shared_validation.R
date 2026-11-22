# Standalone native R worker for the combined validator; no Python calls.
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 2L)
fixtures <- normalizePath(args[[1L]], winslash = "/", mustWork = TRUE)
output <- normalizePath(args[[2L]], winslash = "/", mustWork = TRUE)
script <- sub("^--file=", "", grep("^--file=", commandArgs(), value = TRUE)[[1L]])
repo <- dirname(dirname(normalizePath(script, winslash = "/", mustWork = TRUE)))
library(autoschemaR)
source(file.path(repo, "r/autoschemaR/tests/testthat/helper-shared.R"), local = TRUE)
manifest <- jsonlite::read_json(file.path(fixtures, "manifest.json"), simplifyVector = FALSE)
cases <- lapply(manifest$cases, function(case) {
  tryCatch(.shared_check_case(case, fixtures, output), error = function(e) {
    list(id = case$id, status = "fail", error = conditionMessage(e))
  })
})
report <- list(r_version = as.character(getRversion()), package_version = as.character(packageVersion("autoschemaR")),
               platform = R.version$platform, cases = cases)
jsonlite::write_json(report, file.path(output, "summary.json"), auto_unbox = TRUE,
                      pretty = TRUE, null = "null", digits = NA)
