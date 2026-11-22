# Shared Python/R validation

Python package: 0.4.0a1; Python: 3.9.6; platform: macOS-14.3.1-x86_64-i386-64bit.
R package: 0.1.0.9000; R: 4.3.2.

Conversion times are single observations, excluding preview, validation-runner checks and R startup. These small fixtures do not establish scale limits.

| Case | Python | R | Python seconds | R seconds | Schema grouping |
| --- | --- | --- | --- | --- | --- |
| penguins_original | pass | pass | 0.256678 | 0.504 | same |
| penguins_blank_missing | pass | pass | 0.095027 | 0.078 | same |
| bike_daily | pass | pass | 1.006324 | 0.931 | same |
| messy_orders | pass | pass | 0.280912 | 0.166 | same |
| conflicting_customers | pass | pass | 0.027577 | 0.054 | same |
| wide_bounded_search | pass | pass | 0.613855 | 0.39 | same |
| long_identifiers | pass | pass | 0.092592 | 0.07 | same |
| unusual_text | pass | pass | 0.029877 | 0.041 | same |
| numeric_text_formats | pass | pass | 0.111064 | 0.064 | same |
| quoted_empty_rows | pass | pass | 0.017164 | 0.034 | same |
| duplicate_header | pass | pass | - | - | - |
| case_header | pass | pass | - | - | - |
| ragged | pass | pass | - | - | - |
| unclosed | pass | pass | - | - | - |
| empty | pass | pass | - | - | - |
| nul_bytes | pass | pass | - | - | - |
| invalid_domain_key | pass | pass | - | - | - |

Both implementations must preserve logical CSV values and row multiplicities, including in complete SQL exports. SQL types, table names and complete inferred schemas may differ.
For invalid cases, pass means that preview and conversion both rejected the input without publishing output.
Schema grouping compares column assignments and determinant/attribute sets, ignoring table names and ordering. Detailed name, key and SQL declaration differences are in summary.json; INTEGER versus BIGINT is a declaration difference, not a data-loss finding.
