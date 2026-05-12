# Optional R validation scaffold for Option 2.
# Run after installing R + packages: tidyverse, quanteda, broom.
# Example:
#   Rscript scripts/r_validation.R outputs/option2_YYYYMMDD_HHMMSS/enriched_tickets.csv

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) stop("Usage: Rscript scripts/r_validation.R <enriched_tickets.csv>")
input <- args[[1]]

suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(ggplot2)
  library(quanteda)
  library(broom)
})

df <- read_csv(input, show_col_types = FALSE)

manager_test <- df %>%
  mutate(
    manager = as.factor(manager),
    category = as.factor(category),
    question_kind = as.factor(question_kind),
    role = as.factor(role),
    status_en = as.factor(status_en),
    month = as.factor(month)
  ) %>%
  lm(context_depth_score ~ manager + category + question_kind + role + status_en + month, data = .) %>%
  tidy()

write_csv(manager_test, file.path(dirname(input), "r_adjusted_manager_context_terms.csv"))

corp <- corpus(df, text_field = "question_flat")
dfm_basic <- corp %>%
  tokens(remove_punct = TRUE, remove_symbols = TRUE, remove_numbers = FALSE) %>%
  tokens_tolower() %>%
  tokens_remove(stopwords("en")) %>%
  dfm()

kw <- textstat_frequency(dfm_basic, n = 200)
write_csv(kw, file.path(dirname(input), "r_quanteda_top_terms.csv"))

cat("R validation complete. Wrote r_adjusted_manager_context_terms.csv and r_quanteda_top_terms.csv\n")
