.abort <- function(message, class = "autoschema_invalid_data") {
  stop(structure(list(message = message, call = NULL),
                 class = c(class, "autoschema_error", "error", "condition")))
}

.scalar_string <- function(value) {
  is.character(value) && length(value) == 1L && !is.na(value) && nzchar(value)
}

.validate_options <- function(max_dependency_width, max_key_width,
                              max_candidate_columns, max_checks, key_columns) {
  for (name in c("max_dependency_width", "max_key_width", "max_candidate_columns", "max_checks")) {
    value <- get(name)
    if (!is.numeric(value) || length(value) != 1L || is.na(value) ||
        !is.finite(value) || value != floor(value) || value < 1 ||
        (name %in% c("max_dependency_width", "max_key_width") && value > 3)) {
      .abort(paste(name, "must be a positive integer; widths are limited to 1-3."),
             "autoschema_configuration_error")
    }
  }
  if (!is.null(key_columns) && (!is.character(key_columns) || !length(key_columns) ||
                              anyNA(key_columns) || any(!nzchar(key_columns)))) {
    .abort("key_columns must be NULL or a nonempty character vector.",
           "autoschema_configuration_error")
  }
}

.numeric_text <- function(x) {
  vapply(x, function(value) {
    if (is.na(value)) return("")
    candidate <- as.character(value)
    if (isTRUE(suppressWarnings(as.numeric(candidate)) == value)) candidate else sprintf("%.17g", value)
  }, character(1), USE.NAMES = FALSE)
}

.normalize <- function(frame) {
  if (!is.data.frame(frame)) stop("frame must be a data.frame.", call. = FALSE)
  if (!nrow(frame) || !ncol(frame)) .abort("The dataset must have at least one row and column.")
  columns <- names(frame)
  if (is.null(columns) || anyNA(columns) || any(!nzchar(trimws(columns))) ||
      anyDuplicated(tolower(columns))) {
    .abort("Column names must be nonempty and unique, ignoring case.")
  }
  result <- as.data.frame(frame, stringsAsFactors = FALSE, check.names = FALSE)
  for (column in columns) {
    x <- frame[[column]]
    if (!is.atomic(x) || is.complex(x) || !is.null(dim(x))) {
      .abort("List, matrix and complex columns are unsupported.")
    }
    if (is.numeric(x) && is.null(attr(x, "class")) && !anyNA(x) && all(is.finite(x))) {
      result[[column]] <- x
      next
    }
    text <- if (is.numeric(x) && is.null(attr(x, "class"))) .numeric_text(x) else enc2utf8(as.character(x))
    text[is.na(x)] <- ""
    numeric <- suppressWarnings(as.numeric(text))
    integer <- all(grepl("^-?(0|[1-9][0-9]*)$", text)) &&
      all(is.finite(numeric)) && all(abs(numeric) <= .Machine$integer.max)
    decimal <- all(grepl("^-?(0|[1-9][0-9]*)\\.[0-9]+$", text)) &&
      all(is.finite(numeric)) && !any(numeric == 0 & startsWith(text, "-"))
    roundtrip <- (integer || decimal) && identical(as.character(numeric), text)
    result[[column]] <- if (roundtrip && integer) as.integer(numeric) else if (roundtrip) numeric else text
  }
  rownames(result) <- NULL
  result
}

.identifier <- function(columns) {
  grepl("(^id$|^code$|^key$|^uuid$|_id$|_code$|_key$|_uuid$)", tolower(columns))
}

.candidates <- function(columns, limit) {
  head(columns[order(!.identifier(columns), seq_along(columns))], limit)
}

.sql_type <- function(x) {
  if (is.integer(x)) "INTEGER" else if (is.numeric(x)) "DOUBLE" else "VARCHAR"
}

.profile <- function(data) {
  lapply(names(data), function(column) {
    x <- data[[column]]
    profile <- list(name = column, sql_type = .sql_type(x), distinct = length(unique(x)),
                    distinct_percent = round(100 * length(unique(x)) / nrow(data), 2),
                    blank_count = sum(x == ""))
    if (is.numeric(x)) profile <- c(profile, list(min = min(x), max = max(x), mean = mean(x)))
    profile
  })
}

# Integer codes avoid delimiter collisions in arbitrary text, including newlines.
.column_codes <- function(data) lapply(data, function(x) match(x, unique(x)))
.row_codes <- function(codes) do.call(paste, c(unname(codes), sep = ":"))
.subset <- function(x, y) all(x %in% y)

# Enumerate lazily, so a small search budget also bounds combination allocation.
.combinations <- function(columns, width, visit) {
  n <- length(columns)
  if (width > n) return(TRUE)
  indices <- seq_len(width)
  repeat {
    if (!visit(columns[indices])) return(FALSE)
    position <- width
    while (position > 0L && indices[position] == n - width + position) position <- position - 1L
    if (!position) return(TRUE)
    indices[position] <- indices[position] + 1L
    if (position < width) indices[(position + 1L):width] <- indices[position] + seq_len(width - position)
  }
}

.discover <- function(data, candidates, max_width, max_checks) {
  codes <- .column_codes(data)
  cardinality <- vapply(codes, max, integer(1))
  minimal <- setNames(vector("list", ncol(data)), names(data))
  dependencies <- list()
  checks <- 0L
  truncated <- FALSE
  for (width in seq_len(max_width)) {
    complete <- .combinations(candidates, width, function(keys) {
      if (checks >= max_checks) return(FALSE)
      checks <<- checks + 1L
      if (any(vapply(data[keys], function(x) any(x == ""), logical(1)))) return(TRUE)
      signatures <- .row_codes(codes[keys])
      groups <- match(signatures, unique(signatures))
      count <- max(groups)
      if (count <= 1L || count >= nrow(data)) return(TRUE)
      attributes <- names(data)[vapply(names(data), function(column) {
        !column %in% keys && cardinality[[column]] > 1L &&
          !any(vapply(minimal[[column]], .subset, logical(1), y = keys)) &&
          length(unique(paste(groups, codes[[column]], sep = ":"))) == count
      }, logical(1))]
      if (length(attributes)) {
        dependencies[[length(dependencies) + 1L]] <<- list(
          keys = keys, attributes = attributes, distinct_keys = count)
        for (attribute in attributes) minimal[[attribute]][[length(minimal[[attribute]]) + 1L]] <<- keys
      }
      TRUE
    })
    if (!complete) { truncated <- TRUE; break }
  }
  list(dependencies = dependencies, checks = checks, truncated = truncated)
}

.plan <- function(data, dependencies, protected) {
  remaining <- names(data)
  dimensions <- list()
  used_names <- c("records", "dataset")
  direct <- lapply(dependencies, function(dependency) {
    attributes <- dependency$attributes
    for (bridge in dependencies) {
      if (.subset(bridge$keys, union(dependency$keys, attributes)) &&
          !.subset(dependency$keys, union(bridge$keys, bridge$attributes))) {
        attributes <- setdiff(attributes, bridge$attributes)
      }
    }
    dependency$attributes <- attributes
    dependency
  })
  repeat {
    options <- list()
    for (index in seq_along(direct)) {
      dependency <- direct[[index]]
      keys <- dependency$keys
      if (!.subset(keys, remaining)) next
      attributes <- setdiff(intersect(dependency$attributes, remaining), protected)
      savings <- (nrow(data) - dependency$distinct_keys) * length(attributes) -
        dependency$distinct_keys * length(keys)
      if (length(attributes) && savings > 0) {
        options[[length(options) + 1L]] <- list(
          keys = keys, attributes = attributes, cells_saved = savings,
          rows = dependency$distinct_keys, identifiers = sum(.identifier(keys)), index = index)
      }
    }
    if (!length(options)) break
    score <- function(field) vapply(options, function(x) x[[field]], numeric(1))
    best <- order(-score("cells_saved"), -score("identifiers"),
                  vapply(options, function(x) length(x$keys), integer(1)), score("index"))[1L]
    selected <- options[[best]]
    base <- substr(paste0("dim_", gsub("[^A-Za-z0-9_]", "_", paste(selected$keys, collapse = "_"))), 1L, 70L)
    name <- base
    suffix <- 2L
    while (tolower(name) %in% used_names) {
      name <- paste0(base, "_", suffix)
      suffix <- suffix + 1L
    }
    used_names <- c(used_names, tolower(name))
    dimensions[[length(dimensions) + 1L]] <- list(
      table = name, keys = selected$keys, attributes = selected$attributes,
      cells_saved = selected$cells_saved, rows = selected$rows)
    protected <- union(protected, selected$keys)
    remaining <- setdiff(remaining, selected$attributes)
  }
  list(remaining = remaining, dimensions = dimensions)
}

.find_keys <- function(data, columns, max_width, max_checks, explicit = NULL) {
  if (!is.null(explicit)) {
    if (anyDuplicated(explicit) || !.subset(explicit, names(data))) {
      .abort("key_columns must contain distinct existing column names.")
    }
    if (any(vapply(data[explicit], function(x) any(x == ""), logical(1))) ||
        anyDuplicated(data[explicit])) {
      .abort("key_columns must uniquely identify every row and contain no blanks.")
    }
    return(list(keys = list(explicit), checks = 1L, truncated = FALSE))
  }
  keys <- list()
  checks <- 0L
  truncated <- FALSE
  for (width in seq_len(max_width)) {
    complete <- .combinations(columns, width, function(combination) {
      if (any(vapply(keys, .subset, logical(1), y = combination))) return(TRUE)
      if (checks >= max_checks) return(FALSE)
      checks <<- checks + 1L
      if (!any(vapply(data[combination], function(x) any(x == ""), logical(1))) &&
          !anyDuplicated(data[combination])) keys[[length(keys) + 1L]] <<- combination
      TRUE
    })
    if (!complete) { truncated <- TRUE; break }
  }
  if (length(keys)) keys <- keys[order(
    !vapply(keys, function(x) any(.identifier(x)), logical(1)), lengths(keys),
    -vapply(keys, function(x) sum(.identifier(x)), integer(1)))]
  list(keys = keys, checks = checks, truncated = truncated)
}
