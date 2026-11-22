# Run from a working directory where you want to save results.
library(autoschemaR)
source_csv <- system.file("examples", "customers.csv", package = "autoschemaR")
plan <- preview_csv(source_csv, key_columns = "row_id")
print(plan$table_rows)
print(plan$cell_reduction_percent)

# Use a fresh visible folder, preserving previous runs.
parent <- file.path(getwd(), "results")
dir.create(parent, recursive = TRUE, showWarnings = FALSE)
output <- tempfile("r-customers-", tmpdir = parent)
result <- convert_csv(source_csv, out = output, key_columns = "row_id")
print(result)
print(summary(result)$column_profiles)
print(read_table(result, "dim_customer_id"))
print(query(result, "SELECT * FROM dataset WHERE customer_id = ?", list("C01")))

if (interactive()) {
  plot(result)
  plot(result, type = "timings")
  plot(result, type = "bytes")
  browseURL(result$report_path)
}
reopened <- load_result(output)
stopifnot(summary(reopened)$reconstruction_exact)
cat("All artifacts are saved in:", result$output_dir, "\n")
