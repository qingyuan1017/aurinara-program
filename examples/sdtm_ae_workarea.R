# Example AE Code Workarea program for the current Aurinara staging contract.
#
# This is a runnable structural example, not a reviewed clinical derivation.
# Confirm the study identifier, subject identifier construction, date handling,
# dictionary coding, controlled terminology, and all other mappings before use.

root <- Sys.getenv("AURINARA_WORKSPACE", unset = "/workspace")
input_path <- file.path(root, "inputs", "raw", "AE.csv")
output_path <- file.path(root, "outputs", "AE.csv")

raw <- read.csv(
  input_path,
  check.names = FALSE,
  stringsAsFactors = FALSE,
  colClasses = "character",
  na.strings = c("", "NA")
)

row_count <- nrow(raw)

text_value <- function(name) {
  if (!name %in% names(raw)) return(rep("", row_count))
  value <- as.character(raw[[name]])
  value[is.na(value)] <- ""
  trimws(value)
}

date_time_value <- function(date_name, time_name) {
  date <- text_value(date_name)
  time <- text_value(time_name)
  ifelse(nzchar(date) & nzchar(time), paste0(date, "T", time), date)
}

output_columns <- c(
  "STUDYID", "DOMAIN", "USUBJID", "SPDEVID", "AESEQ", "AEGRPID",
  "AEREFID", "AESPID", "AETERM", "AEMODIFY", "AELLT", "AELLTCD",
  "AEDECOD", "AEPTCD", "AEHLT", "AEHLTCD", "AEHLGT", "AEHLGTCD",
  "AECAT", "AESCAT", "AEPRESP", "AEBODSYS", "AEBDSYCD", "AESOC",
  "AESOCCD", "AELOC", "AESEV", "AESER", "AEACN", "AEACNOTH",
  "AEACNDEV", "AEREL", "AERLDEV", "AERELNST", "AEPATT", "AEOUT",
  "AESCAN", "AESCONG", "AESDISAB", "AESDTH", "AESHOSP", "AESLIFE",
  "AESOD", "AESMIE", "AESINTV", "AEUNANT", "AERLPRT", "AERLPRC",
  "AECONTRT", "AETOXGR", "TAETORD", "EPOCH", "AESTDTC", "AEENDTC",
  "AESTDY", "AEENDY", "AEDUR", "AEENRF", "AEENRTPT", "AEENTPT"
)

numeric_columns <- c(
  "AESEQ", "AELLTCD", "AEPTCD", "AEHLTCD", "AEHLGTCD", "AEBDSYCD",
  "AESOCCD", "TAETORD", "AESTDY", "AEENDY"
)

out <- as.data.frame(
  setNames(
    lapply(output_columns, function(name) {
      if (name %in% numeric_columns) rep(NA_real_, row_count) else rep("", row_count)
    }),
    output_columns
  ),
  check.names = FALSE,
  stringsAsFactors = FALSE
)

# Structural identifiers. Replace SAMPLE-STUDY and review USUBJID construction.
out$STUDYID <- rep("SAMPLE-STUDY", row_count)
out$DOMAIN <- rep("AE", row_count)
out$USUBJID <- text_value("SubjectId")
out$AESEQ <- if (row_count == 0) {
  numeric(0)
} else {
  as.numeric(ave(seq_len(row_count), out$USUBJID, FUN = seq_along))
}

# Direct example mappings from the currently selected Raw AE dataset.
out$AESPID <- text_value("AESPID")
out$AETERM <- text_value("AETERM")
out$AESEV <- text_value("AESEV")
out$AESER <- text_value("AESER")
out$AEACN <- text_value("AEACN")
out$AEACNOTH <- text_value("AEACNOTH")
out$AEREL <- text_value("AEREL")
out$AERELNST <- text_value("AERELNST")
out$AEOUT <- text_value("AEOUT")
out$AESTDTC <- date_time_value("AESTDAT", "AESTTIM")
out$AEENDTC <- date_time_value("AEENDAT", "AEENTIM")

# AEDECOD and the MedDRA hierarchy intentionally remain blank. Populate them
# only from the study's reviewed medical-coding source and terminology version.

order_index <- order(out$STUDYID, out$DOMAIN, out$USUBJID, out$AESEQ, na.last = TRUE)
out <- out[order_index, output_columns, drop = FALSE]

dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)
write.csv(
  out,
  output_path,
  row.names = FALSE,
  na = "",
  quote = TRUE,
  fileEncoding = "UTF-8"
)
