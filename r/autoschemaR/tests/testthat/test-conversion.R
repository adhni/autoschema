test_that("preview matches conversion and does not write artifacts", {
  frame <- fixture()
  original <- frame
  plan <- preview_dataframe(frame, key_columns = "row_id")
  expect_identical(frame, original)
  expect_null(plan$reconstruction_exact)
  expect_null(plan$database_bytes)
  expect_false("validate" %in% names(plan$timings_seconds))
  expect_equal(plan$table_rows$dim_customer_id, 2L)
  result <- convert_dataframe(frame, new_output(), key_columns = "row_id")
  expect_s3_class(result, "autoschema_result")
  for (key in c("tables", "table_rows", "dimensions", "selected_key", "dependencies",
                "input_cells", "stored_cells", "cell_reduction_percent", "search")) {
    expect_identical(plan[[key]], summary(result)[[key]], info = key)
  }
  expect_true(summary(result)$reconstruction_exact)
  expect_same_rows(read_table(result), frame)
  expect_output(print(result), "Exact reconstruction: PASS")
})

test_that("CSV retains quoted blanks, whitespace, leading zeros, NA text and unicode", {
  file <- tempfile(fileext = ".csv")
  withr::defer(unlink(file))
  csv <- paste(c('id;note;price', '001;"Caf\u00e9; A";1.00', '002;"a', 'b";2.00',
               '003;NA;3.00', '004;"";4.00', '005;" padded ";5.00'), collapse = "\n")
  writeBin(charToRaw(enc2utf8(csv)), file)
  result <- convert_csv(file, new_output(), delimiter = ";")
  rows <- read_table(result)
  expect_identical(rows$id, c("001", "002", "003", "004", "005"))
  expect_identical(rows$note, c("Caf\u00e9; A", "a\nb", "NA", "", " padded "))
  expect_identical(rows$price, paste0(1:5, ".00"))
  expect_same_rows(execute_dump(file.path(result$output_dir, "dataset.sql")), rows)
  expect_identical(preview_csv(file, delimiter = ";")$tables, summary(result)$tables)
})

test_that("one-column quoted empty rows are preserved", {
  file <- tempfile(); withr::defer(unlink(file))
  writeLines(c("value", '""', "x"), file)
  result <- convert_csv(file, new_output())
  expect_identical(read_table(result)$value, c("", "x"))
  json <- jsonlite::read_json(file.path(result$output_dir, "schema.json"))
  expect_type(json$columns, "list")
  expect_length(json$columns, 1L)
  expect_identical(read_table(load_result(result$output_dir)), read_table(result))
})

test_that("UTF-8 BOM and escaped identifiers work", {
  file <- tempfile(); withr::defer(unlink(file))
  writeBin(c(as.raw(c(0xef, 0xbb, 0xbf)), charToRaw('id,note\n001,hello\n')), file)
  expect_identical(preview_csv(file)$columns, c("id", "note"))
  frame <- data.frame("select" = 1:8, 'odd "name"' = rep(c("A", "B"), 4),
                      check.names = FALSE)
  result <- convert_dataframe(frame, new_output())
  expect_same_rows(read_table(result), frame)
})

test_that("missing values and duplicate multiplicities survive reconstruction", {
  frame <- data.frame(id = c("001", "001", "002", "003"),
                      price = c("1.00", "1.00", "", "NA"),
                      note = c("O'Brien; caf\u00e9\nnext", "O'Brien; caf\u00e9\nnext", NA, "<script>x</script>"),
                      huge = c("9223372036854775808", "9223372036854775808", "0000", "-0.0"))
  result <- convert_dataframe(frame, new_output())
  frame$note[is.na(frame$note)] <- ""
  expect_equal(summary(result)$duplicate_rows, 1L)
  expect_equal(summary(result)$blank_cells, 2L)
  expect_length(summary(result)$selected_key, 0L)
  expect_same_rows(read_table(result), frame)
  expect_same_rows(execute_dump(file.path(result$output_dir, "dataset.sql")), frame)
  html <- paste(readLines(result$report_path, encoding = "UTF-8"), collapse = "\n")
  expect_false(grepl("<script>x</script>", html, fixed = TRUE))
  escape <- getFromNamespace(".html", "autoschemaR")
  expect_identical(escape("<script>x</script>"), "&lt;script&gt;x&lt;/script&gt;")
})

test_that("numeric inference is conservative about text formatting and R integer limits", {
  frame <- data.frame(id = 1:3, decimal = c("1.5", "2.5", "3.5"),
                      fixed = c("1.00", "2.00", "3.00"), large = rep("2147483648", 3),
                      negative_zero = c("-0", "0", "1"), category = factor(c("A", "B", "A")))
  result <- convert_dataframe(frame, new_output())
  actual <- read_table(result)
  expect_type(actual$id, "integer")
  expect_type(actual$decimal, "double")
  expect_identical(actual$fixed, frame$fixed)
  expect_identical(actual$large, frame$large)
  expect_identical(actual$negative_zero, frame$negative_zero)
  expect_identical(actual$category, as.character(frame$category))
  expect_same_rows(execute_dump(file.path(result$output_dir, "dataset.sql")), actual)
})

test_that("composite dependencies and explicit keys are discovered", {
  withr::local_seed(7)
  frame <- expand.grid(line_number = 1:4, order_id = paste0("O", 1:25), stringsAsFactors = FALSE)
  frame$product_id <- sample(c("A", "B", "C"), nrow(frame), replace = TRUE)
  frame$warehouse_id <- sample(c("X", "Y", "Z"), nrow(frame), replace = TRUE)
  frame$bin <- ifelse((match(frame$product_id, c("A", "B", "C")) +
                        match(frame$warehouse_id, c("X", "Y", "Z"))) %% 2L, "left", "right")
  result <- convert_dataframe(frame, new_output(), key_columns = c("order_id", "line_number"))
  dimensions <- summary(result)$dimensions
  matching <- Filter(function(d) setequal(d$keys, c("product_id", "warehouse_id")) && "bin" %in% d$attributes, dimensions)
  expect_length(matching, 1L)
  expect_identical(summary(result)$selected_key, c("order_id", "line_number"))
  expect_same_rows(read_table(result), frame)
  expect_same_rows(execute_dump(file.path(result$output_dir, "dataset.sql")), frame)
})

test_that("identifier composite keys are preferred to unique measurements", {
  frame <- expand.grid(line_number = 1:3, order_id = paste0("O", 1:5), stringsAsFactors = FALSE)
  frame <- frame[c("order_id", "line_number")]
  frame$measurement <- seq_len(nrow(frame)) + 0.5
  expect_identical(preview_dataframe(frame)$selected_key, c("order_id", "line_number"))
})

test_that("conflicting mappings are not decomposed and dimension keys stay in records", {
  frame <- data.frame(customer_id = c("A", "A", "B", "B", "A", "B"), city = c("X", "Y", "X", "Y", "Y", "X"))
  expect_length(preview_dataframe(frame)$dimensions, 0L)
  frame <- data.frame(row_id = 1:40, a_id = rep(paste0("A", 1:4), 10),
                      b_id = rep(paste0("B", 1:4), 10), city = rep(paste0("City", 1:4), 10))
  result <- convert_dataframe(frame, new_output())
  for (d in summary(result)$dimensions) expect_true(all(d$keys %in% summary(result)$records_columns))
  expect_same_rows(read_table(result), frame)
})

test_that("search budgets are disclosed and do not prevent exact conversion", {
  plan <- preview_dataframe(fixture(), max_checks = 1L, max_candidate_columns = 2L)
  expect_true(plan$search$key_budget_reached || plan$search$dependency_budget_reached)
  expect_true(any(grepl("budget", plan$warnings)))
  result <- convert_dataframe(fixture(), new_output(), max_checks = 1L)
  expect_true(summary(result)$reconstruction_exact)
})

test_that("long and colliding sanitized dimension names export safely", {
  prefix <- paste(rep("x", 280), collapse = "")
  frame <- data.frame(row_id = 1:24, first = rep(c("A", "B"), 12), city = rep(c("London", "Paris"), 12),
                      second = rep(c("C", "C", "D", "D"), 6), name = rep(c("Amina", "Amina", "Yusuf", "Yusuf"), 6))
  names(frame)[c(2L, 4L)] <- c(paste0(prefix, "_first_id"), paste0(prefix, "_second_id"))
  result <- convert_dataframe(frame, new_output(), key_columns = "row_id")
  dimensions <- summary(result)$dimensions
  expect_length(dimensions, 2L)
  names <- vapply(dimensions, function(d) d$table, character(1))
  expect_equal(length(unique(names)), 2L)
  expect_true(all(nchar(names, type = "bytes") <= 80L))
  expect_true(all(file.exists(file.path(result$output_dir, paste0(names, ".csv")))))
  expect_same_rows(read_table(result), frame)
})

test_that("invalid data, columns, keys and options are rejected", {
  expect_error(preview_dataframe(data.frame(x = integer())), class = "autoschema_invalid_data")
  expect_error(preview_dataframe(42), "data.frame")
  frame <- fixture(); names(frame)[2L] <- "ROW_ID"
  expect_error(preview_dataframe(frame), class = "autoschema_invalid_data")
  frame <- fixture(); names(frame)[2L] <- " "
  expect_error(preview_dataframe(frame), class = "autoschema_invalid_data")
  expect_error(preview_dataframe(data.frame(x = I(list(1, 2)))), "List")
  for (key in list(character(), NA_character_, "missing", c("row_id", "row_id"), "customer_id")) {
    expect_error(preview_dataframe(fixture(), key_columns = key), class = "autoschema_error")
  }
  for (value in list(TRUE, NA_real_, Inf, 0, -1, 1.5, "2")) {
    expect_error(preview_dataframe(fixture(), max_checks = value), class = "autoschema_configuration_error")
  }
  expect_error(preview_dataframe(fixture(), max_key_width = 4), class = "autoschema_configuration_error")
})

test_that("malformed CSV, NUL and invalid delimiters are rejected", {
  file <- tempfile(); withr::defer(unlink(file))
  for (contents in c("a,a\n1,2\n", "a,\n1,2\n", "a,b\n1,2,3\n", "a,b\n1\n", 'a,b\n1,"unclosed\n')) {
    writeLines(contents, file)
    expect_error(preview_csv(file), class = "autoschema_invalid_data", info = contents)
  }
  writeBin(c(charToRaw("a,b\n1,"), as.raw(0), charToRaw("x\n")), file)
  expect_error(preview_csv(file), "NUL")
  expect_error(preview_csv(file, delimiter = "||"), class = "autoschema_configuration_error")
  expect_error(preview_csv(file, encoding = "no-such-encoding"), class = "autoschema_configuration_error")
})

test_that("existing output and failures cannot publish incomplete artifacts", {
  output <- new_output(); dir.create(output)
  sentinel <- file.path(output, "keep.txt"); writeLines("keep", sentinel)
  expect_error(convert_dataframe(fixture(), output), class = "autoschema_output_error")
  expect_identical(readLines(sentinel), "keep")
  output <- new_output(); dir.create(output)
  expect_error(convert_dataframe(fixture(), output), class = "autoschema_output_error")
  parent <- new_output(); dir.create(parent)
  output <- file.path(parent, "result")
  testthat::local_mocked_bindings(.render_report = function(...) stop("report failure"), .package = "autoschemaR")
  expect_error(convert_dataframe(fixture(), output), "report failure")
  expect_false(dir.exists(output))
  expect_length(list.files(parent, all.files = TRUE, no.. = TRUE), 0L)
})

test_that("reconstruction compares exact values without string delimiter collisions", {
  same <- getFromNamespace(".same_rows", "autoschemaR")
  x <- data.frame(a = c("a:b", "a"), b = c("c", "b:c"))
  expect_true(same(x, x[2:1, ]))
  expect_false(same(x, x[c(1, 1), ]))
  expect_false(same(data.frame(x = 1.000000000000001), data.frame(x = 1)))
})


test_that("native numeric precision survives SQLite and SQL export", {
  values <- c(1 + .Machine$double.eps, 1.100000000000001, -1.2345678901234567)
  frame <- data.frame(row_id = 1:3, value = values)
  result <- convert_dataframe(frame, new_output())
  expect_identical(read_table(result)$value, values)
  expect_identical(execute_dump(file.path(result$output_dir, "dataset.sql"))$value, values)
  frame$value[3L] <- NA_real_
  result <- convert_dataframe(frame, new_output())
  actual <- read_table(result)$value
  expect_identical(as.numeric(actual[1:2]), values[1:2])
  expect_identical(actual[3L], "")
})


test_that("SQL exports preserve newline bytes in values and column names", {
  frame <- data.frame(row_id = 1:4, text = c("a\r\nb", "x\ny", "c\rd", "caf\u00e9"))
  names(frame)[2L] <- "line\nname"
  result <- convert_dataframe(frame, new_output())
  expect_same_rows(read_table(result), frame)
  expect_same_rows(execute_dump(file.path(result$output_dir, "dataset.sql")), frame)
})
