#' @title ETL Backend Utilities
#' @description Shared functions for data cleaning and storage egress.

#' Remove ONA System Variables
#' @param df A data frame.
#' @return A data frame without ONA system columns.
remove_system_vars <- function(df) {
  system_vars <- c(
    "_tags", "_uuid", "_notes", "_edited", "_status", "_version", "_duration", "_xform_id",
    "_attachments", "_geolocation", "_media_count", "_total_media", "formhub/uuid",
    "_id", "_submitted_by", "_date_modified", "meta/instanceID", "_submission_time",
    "intro/geopoint_household", "_xform_id_string", "_bamboo_dataset_id",
    "intro/in_the_field", "_media_all_received"
  )
  df %>% dplyr::select(-dplyr::any_of(system_vars))
}

#' Upload Data Frame to Azure Blob Storage
#' @param df The data frame to upload.
#' @param dest_name The destination filename (e.g., "data.csv").
#' @param container The AzureStor container object.
upload_to_azure <- function(df, dest_name, container) {
  message(sprintf("Uploading %s to Azure...", dest_name))
  
  # Use a text connection to avoid writing to physical disk
  w_con <- textConnection("foo", "w")
  write.csv(df, w_con, row.names = FALSE)
  r_con <- textConnection(textConnectionValue(w_con))
  
  # Ensure connections are closed even if upload fails
  on.exit({
    close(w_con)
    close(r_con)
  })
  
  AzureStor::upload_blob(
    container = container,
    src = r_con,
    dest = paste0(Sys.getenv("dest_path"), dest_name)
  )
}

#' Convert empty strings to NA
#' Ported from support_fun.R
blank2na <- function(x) {
  if (is.character(x) || is.factor(x)) {
    x[x == "" | x == "."] <- NA
  }
  return(x)
}

#' Flatten List-Columns in a Data Frame
#' @description Converts list-columns to comma-separated strings for CSV export.
#' @param df A data frame.
#' @return A data frame with flattened character columns.
flatten_list_columns <- function(df) {
  df <- as.data.frame(df)
  df[] <- lapply(df, function(x) {
    if (is.list(x)) {
      sapply(x, function(y) paste(na.omit(y), collapse = ","))
    } else {
      x
    }
  })
  return(df)
}

#' Standardized EN and HH Registration Merger
#' @description Standardizes the logic for merging enumerator and household registration data.
#' @param en_df Enumerator registration data frame.
#' @param hh_df Household registration data frame.
#' @param en_map Named character vector for renaming EN columns.
#' @param hh_map Named character vector for renaming HH columns.
#' @param test_ids Vector of ENIDs to exclude (optional).
#' @return A joined and cleaned data frame.
merge_id_registration <- function(en_df, hh_df, en_map, hh_map, test_ids = NULL) {
  
  # 1. Process Enumerators
  en_proc <- en_df %>%
    dplyr::rename(!!!en_map) %>%
    dplyr::select(dplyr::any_of(c("ENtoday", "ENID", "ENfirstName", "ENSurname", "ENphoneNo"))) %>%
    dplyr::arrange(ENID, dplyr::desc(ENtoday)) %>%
    dplyr::distinct(ENID, .keep_all = TRUE)
  
  if (!is.null(test_ids)) {
    en_proc <- en_proc %>% dplyr::filter(!ENID %in% test_ids)
  }

  # 2. Process Households
  hh_proc <- hh_df %>%
    dplyr::rename(!!!hh_map)
  
  # Handle Geopoint separation if present
  if ("geopoint" %in% names(hh_proc)) {
    hh_proc <- hh_proc %>%
      tidyr::separate(geopoint, into = c("LAT", "LON", "ALT", "ERR"), sep = " ", fill = "right")
  }
  
  hh_proc <- hh_proc %>%
    dplyr::select(dplyr::any_of(c("today", "ENID", "HHID", "LAT", "LON", "Country", "HHfirstName", "HHSurname", "HHphoneNo", "Site Selection"))) %>%
    dplyr::distinct(ENID, HHID, .keep_all = TRUE) %>%
    dplyr::filter(!is.na(HHID))
  
  # Sort by today if it exists, otherwise just by ENID
  if ("today" %in% names(hh_proc)) {
    hh_proc <- hh_proc %>% dplyr::arrange(ENID, dplyr::desc(today))
  } else {
    hh_proc <- hh_proc %>% dplyr::arrange(ENID)
  }

  if (!is.null(test_ids)) {
    hh_proc <- hh_proc %>% dplyr::filter(!ENID %in% test_ids)
  }

  # 3. Join and Finalize
  result <- en_proc %>%
    dplyr::full_join(hh_proc, by = "ENID") %>%
    dplyr::mutate(
      Stage = "Validation"
    )
  
  # Conditionally add DateId and Site Selection if today exists
  if ("today" %in% names(result)) {
    result <- result %>%
      dplyr::mutate(
        DateId = dplyr::coalesce(today, ENtoday),
        `Site Selection` = today,
        `Site Selection` = ifelse(is.na(HHID), NA, `Site Selection`)
      ) %>%
      dplyr::select(-dplyr::any_of(c("today", "ENtoday")))
  } else {
    result <- result %>%
      dplyr::mutate(
        DateId = ENtoday
      ) %>%
      dplyr::select(-dplyr::any_of(c("ENtoday")))
  }
  
  result %>% suppressWarnings()
}
