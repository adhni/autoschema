fixtures <- system.file("validation", package = "autoschemaR")
manifest <- jsonlite::read_json(file.path(fixtures, "manifest.json"), simplifyVector = FALSE)
for (case in manifest$cases) {
  test_that(paste("shared dataset contract:", case$id), {
    parent <- new_output()
    dir.create(parent)
    result <- .shared_check_case(case, fixtures, parent)
    expect_identical(result$status, "pass")
  })
}
