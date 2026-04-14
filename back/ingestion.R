#' @title ONA Data Ingestion Pipeline
#' @description
#' This script manages the authentication and retrieval of raw datasets from the ONA API.
#' It defines a standardized fetching mechanism and orchestrates the download of
#' multiple form IDs across different projects (EiA, SNS, Solidaridad, etc.).
#' @section Environment Variables:
#' - `TOKEN1`: The ONA API token used for authentication.

# 0. Setup Environment and Dependencies

# Load environment variables if TOKEN1 is missing (handles session initialization)
if (Sys.getenv("TOKEN1") == "") {
  if (file.exists(".Renviron")) readRenviron(".Renviron")
  if (file.exists("../.Renviron")) readRenviron("../.Renviron")
}

# Ensure 'okapi' is installed (must be installed via GitHub)
if (!requireNamespace("okapi", quietly = TRUE)) {
  if (!requireNamespace("remotes", quietly = TRUE)) {
    install.packages("remotes", repos = "http://cran.us.r-project.org")
  }
  remotes::install_github("rapidsurveys/odktools")
}

suppressMessages(suppressWarnings(library(okapi)))

## 1. Authentication Setup
# Map the secure TOKEN1 to ONA_TOKEN for compatibility with the okapi package
Sys.setenv("ONA_TOKEN" = Sys.getenv("TOKEN1"))

#' Fetch Raw Data from ONA
#'
#' A wrapper around \code{\link[okapi]{ona_data_get}} that provides centralized configuration
#' and error handling. It allows the pipeline to log progress and gracefully
#' handle missing or inaccessible forms without terminating the entire script.
#'
#' @param form_id Numeric/Integer. The unique ID for the ONA form.
#' @param label Character. A descriptive name for the dataset for logging purposes.
#'
#' @return A \code{data.frame} if successful, or \code{NULL} if an error occurs.
#'
#' @examples
#' \dontrun{
#'   data <- fetch_raw_ona(808709, "DEMO-EN")
#' }
fetch_raw_ona <- function(form_id, label = "") {
  message(sprintf("[%s] Fetching ONA form ID: %s...", label, form_id))
  
  tryCatch({
    data <- ona_data_get(
      base_url = "https://api.ona.io",
      auth_mode = "token",
      form_id = form_id
    )
    return(data)
  }, error = function(e) {
    message(sprintf("Error fetching form %s (%s): %s", form_id, label, e$message))
    return(NULL)
  })
}

# --- 2. Data Ingestion by Project ---

# EiA Demo Validation
DEMO.Register_EN       <- fetch_raw_ona(808709, "DEMO-EN")
DEMO.RegisterVerify_HH  <- fetch_raw_ona(808710, "DEMO-HH")
DEMO.valData            <- fetch_raw_ona(808706, "DEMO-VAL")

# SNS Rwanda
Register_EN             <- fetch_raw_ona(750671, "RW-EN")
RegisterVerify_HH       <- fetch_raw_ona(750672, "RW-HH")
valTest                 <- fetch_raw_ona(752552, "RW-VAL")

# Solidaridad
NOTSol                 <- fetch_raw_ona(780907, "SOL-NOT")
valSol                 <- fetch_raw_ona(780906, "SOL-VAL")
f.seg_malawi           <- fetch_raw_ona(755562, "SOL-MW")
f.seg_mozambique       <- fetch_raw_ona(756460, "SOL-MZ")
f.seg_zambia           <- fetch_raw_ona(755802, "SOL-ZM")

# KALRO
KL.Register_EN         <- fetch_raw_ona(789929, "KL-EN")
KL.RegisterVerify_HH    <- fetch_raw_ona(789933, "KL-HH")
KL.valData              <- fetch_raw_ona(793461, "KL-VAL")

# Mercy Corps Sprout
MC.Register_EN         <- fetch_raw_ona(805762, "MC-EN")
MC.RegisterVerify_HH    <- fetch_raw_ona(805781, "MC-HH")
MC.valData              <- fetch_raw_ona(808517, "MC-VAL")

# GH CerLeg Esoko
CE.Register_EN         <- fetch_raw_ona(802688, "CE-EN")
CE.RegisterVerify_HH    <- fetch_raw_ona(804928, "CE-HH")
CE.valData              <- fetch_raw_ona(804068, "CE-VAL")
CE.ICData               <- fetch_raw_ona(803455, "CE-IC")

# BioSSA
BS.NOTData_banana      <- fetch_raw_ona(801786, "BS-BAN-1")
BS.NOTData_bananaS2    <- fetch_raw_ona(822732, "BS-BAN-2")
BS.NOTData_cassava     <- fetch_raw_ona(801595, "BS-CAS-1")
BS.NOTData_cassavaS2   <- fetch_raw_ona(822730, "BS-CAS-2")
BS.NOTData_legumes     <- fetch_raw_ona(808612, "BS-LEG-1")
BS.NOTData_legumesS2   <- fetch_raw_ona(822746, "BS-LEG-2")
BS.NOTData_yam         <- fetch_raw_ona(801783, "BS-YAM-1")
BS.NOTData_yamS2       <- fetch_raw_ona(822731, "BS-YAM-2")

message("Data ingestion complete.")
