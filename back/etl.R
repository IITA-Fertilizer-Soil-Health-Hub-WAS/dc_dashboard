#' @title Consolidated ETL Pipeline
#' @description Re-designed ETL process for field monitoring data.

source('back/ingestion.R')
source('back/clean_utils.R')

# 1. Dependency Management
# In production, these should be handled by the Docker image build.
libs <- c("httr", "jsonlite", "tidyr", "purrr", "dplyr", "data.table", "readr", "stringr", "R.utils", "AzureStor")
suppressMessages(suppressWarnings({
  lapply(libs, library, character.only = TRUE)
}))

# 2. Azure Storage Initialization
bl_endp_key <- storage_endpoint(Sys.getenv("account_endpoint"), key=Sys.getenv("account_key"))
cont <- storage_container(bl_endp_key, Sys.getenv("container_name"))

##########################SNS-RWANDA######################################################
message(">>> Processing SNS-RWANDA...")
#ID DATA (Enumerators and households)
EN.HH_data <- merge_id_registration(
  en_df = Register_EN,
  hh_df = RegisterVerify_HH,
  en_map = c(ENID = "purpose/enumerator_ID", ENSurname = "purpose/surname", 
             ENphoneNo = "purpose/phone_number", ENfirstName = "purpose/first_name", ENtoday = "today"),
  hh_map = c(today = "today",
             ENID = "enumerator_ID_dataSCRIBEcode_a1e28af2b2a745b6bb29467aa015164c_ENDDS",
             HHID = "new_barcode_dataSCRIBEcode_02c9e5d2f2504f57ae636de562b9f837_ENDDS/household_ID_dataSCRIBEcode_85e11f6972e14bd0bfc5282a6d6b226f_ENDDS",
             geopoint = "new_barcode_dataSCRIBEcode_02c9e5d2f2504f57ae636de562b9f837_ENDDS/household_geopoint_dataSCRIBEcode_46dd9da06bc541a0a2917f8b4fcf0bd8_ENDDS",
             Country = "country_ID_dataSCRIBEcode_95be8089f5c845e183a371095d44a55e_ENDDS"),
  test_ids = "RSENRW000001"
)

#Validation data

data<-valTest #from ona api download (okapi2.R)

data <- remove_system_vars(data)

# Update HHID #scanned vs typed ids issue    ...merge vars: scanned - `intro/wrong_ID`, typed-`intro/barcodehousehold_1`...`intro/barcodehousehold`
data$`intro/barcodehousehold_1` <- sub("RSHHRW1", "RSHHRW0", data$`intro/barcodehousehold_1`)
data$`intro/wrong_ID` <- sub("LSHH", "RSHH", data$`intro/wrong_ID`)
data$`intro/wrong_ID`<- ifelse(is.na(data$`intro/wrong_ID`) & data$`intro/barcodehousehold_1` != "RSHHRWNaN",
                               data$`intro/barcodehousehold_1`,
                               data$`intro/wrong_ID`)
data$`intro/wrong_ID`<- ifelse(is.na(data$`intro/wrong_ID`) & data$`intro/barcodehousehold` != "RSHHRWNaN",
                               data$`intro/barcodehousehold`,
                               data$`intro/wrong_ID`)

# plant stand data
Plant_stand_data<- data %>% 
  dplyr::select(start,today,`intro/country` ,`intro/event`,`intro/latitude`,`intro/longitude`,`intro/altitude`,`intro/wrong_ENID`,`intro/wrong_ID`,crop,grep("planting.*", names(data), value = TRUE))

#Plot data
plot_data<- data %>% 
  dplyr::select(start,today,`intro/country` ,`intro/event`,`intro/latitude`,`intro/longitude`,`intro/altitude`,crop,`intro/wrong_ENID`,`intro/wrong_ID`,crop,grep("plotDescription.*", names(data), value = TRUE))

plot1<- plot_data %>% 
  gather(v, value, 12:33) %>% 
  mutate(treat=ifelse(v %in% grep("*.AEZ.*",v, value=T),"AEZ",
                      ifelse(v %in% grep("*.BR.*",v, value=T),"BR",
                             ifelse(v %in% grep("*.SSR.*",v, value=T),"SSR", NA)))) %>% 
  separate(v, c("details","var", "col"),"/") %>% 
  select(-details) %>% 
  mutate(col1=gsub("\\_aez|\\_BR|\\_ssr|\\_control", "", col)) %>% 
  mutate(col1=gsub("_SSR","",col1)) %>% select(-c(col,var))

# clean col to reshape wide
reshaped_data <- plot1 %>% 
  pivot_wider(
    id_cols = c( "start","today","intro/country","intro/event","intro/latitude","intro/longitude","intro/altitude","intro/wrong_ENID", "intro/wrong_ID", "crop", "plotDescription/plotSizeDetails/row_number","treat"),
    names_from = col1,
    values_from = value
  )

#drop rows that are entirely missing
reshaped_data <- reshaped_data[rowSums(is.na(reshaped_data)) <= ncol(reshaped_data)-5-1, ]

# land preparation data
land_prep_data<- data %>% 
  dplyr::select(start,today,`intro/country`,`intro/event` ,`intro/latitude`,`intro/longitude`,`intro/altitude`,`intro/wrong_ENID`,`intro/wrong_ID`,crop,grep("LandPreparation*", names(data), value = TRUE))

# crop management data

crop_mgt_data<- data %>% 
  dplyr::select(start,today,`intro/country`,`intro/event` ,`intro/latitude`,`intro/longitude`,`intro/altitude`,`intro/wrong_ENID`,`intro/wrong_ID`,crop,grep("cropManagement*", names(data), value = TRUE))

# merge all the datasets
df_list<- list(reshaped_data,Plant_stand_data,land_prep_data,crop_mgt_data) 

full_data<-df_list %>% reduce(full_join, by=c("start","today","intro/country","intro/event","intro/latitude","intro/longitude","intro/altitude","intro/wrong_ENID", "intro/wrong_ID","crop")) %>% 
  rename_with(
    ~stringr::str_replace_all(.x, c("plot_plot/"), ""))

full_data <- full_data%>%
  mutate(Trial = "Fertilizer Recommendation")%>%
  rename(
    ENID = `intro/wrong_ENID`,
    HHID = `intro/wrong_ID`,
    todayVal = today,
    Crop = crop,
    plantingDate = `planting/plantingDetails/planting_date`
  )#%>%mutate(todayVal2 = todayVal)

VAL_data <- full_data %>%
  dplyr::select(todayVal, ENID, HHID, Trial, treat,Crop, `intro/event`) %>%
  distinct(ENID, HHID, Trial, treat, `intro/event`, .keep_all = TRUE)%>%
  pivot_wider(names_from = `intro/event`, values_from = todayVal) %>%
  arrange(ENID, HHID, Trial, treat) %>%
  left_join(
    full_data %>%
      distinct(ENID, HHID, Trial, treat, `intro/event`, .keep_all = TRUE) %>%
      dplyr::select(ENID, HHID, Trial, treat, plantingDate) %>%
      filter(!is.na(plantingDate)),
    by = c("ENID", "HHID", "Trial", "treat")
  ) %>%
  left_join(
    full_data %>%
      distinct(ENID, HHID, Trial, treat, `intro/event`, .keep_all = TRUE) %>%
      dplyr::select(ENID, HHID, Trial, treat, todayVal) ,
    by = c("ENID", "HHID", "Trial", "treat")
  ) %>% distinct(ENID, HHID, Trial, treat, .keep_all = TRUE)%>% 
  mutate(event1 = plantingDate)%>% select(-(plantingDate))%>% suppressWarnings()

# Join Identifiers+Validation Data
RWA.VAL_data <- EN.HH_data %>%
  left_join(VAL_data, by = c("ENID","HHID")) %>% #join identifiers and val data while keeping all enumerators/households
  mutate(Date = coalesce(todayVal, DateId))%>%select(-c(DateId,todayVal))%>%
  suppressWarnings()

dataev<-data%>%
  dplyr::select(today, `intro/wrong_ENID`,`intro/wrong_ID` ,crop, `intro/event`,  `planting/plantingDetails/planting_date`) 
dataev <- dataev%>%
  mutate(Trial = "Fertilizer Recommendation")%>%
  rename(
    ENID = `intro/wrong_ENID`,
    HHID = `intro/wrong_ID`,
    todayVal = today,
    Crop = crop,
    plantingDate = `planting/plantingDetails/planting_date`
  )
dataev1 <- dataev%>%
  dplyr::select(todayVal, ENID, HHID, Trial,Crop,  `intro/event`) %>%
  distinct(ENID, HHID, Trial, `intro/event`, .keep_all = TRUE)%>%
  pivot_wider(names_from = `intro/event`, values_from = todayVal) %>%
  arrange(ENID, HHID, Trial) %>%
  left_join(
    dataev %>%
      distinct(ENID, HHID, Trial, `intro/event`, .keep_all = TRUE) %>%
      dplyr::select(ENID, HHID, Trial, plantingDate) %>%
      filter(!is.na(plantingDate)),
    by = c("ENID", "HHID", "Trial")
  ) %>%
  left_join(
    dataev %>%
      distinct(ENID, HHID, Trial,  `intro/event`, .keep_all = TRUE) %>%
      dplyr::select(ENID, HHID, Trial, todayVal) ,
    by = c("ENID", "HHID", "Trial")
  ) %>% distinct(ENID, HHID, Trial, .keep_all = TRUE)%>% 
  mutate(event1 = plantingDate)%>% select(-(plantingDate))%>%
  suppressWarnings()

RWA.SUM_data <- EN.HH_data %>%
  left_join(dataev1, by = c("ENID","HHID")) %>% #join identifiers and val data while keeping all enumerators/households
  mutate(Date = coalesce(todayVal, DateId))%>%select(-c(DateId,todayVal))%>%
  suppressWarnings()

#Validation Data
RWA.O_data<-valTest %>% 
  remove_system_vars() %>% 
  select(-c(start,`intro/barcodehousehold_1`))%>% 
  rename(Country = `intro/country`,
         Crop = crop,
         HHID = `intro/wrong_ID`)%>% 
  rename_with(
  ~stringr::str_replace_all(.x, c("intro/"), ""))%>% 
  mutate(Trial = "Fertilizer Recommendation",
         Stage = "Validation"
         )

# via azure storage
upload_to_azure(RWA.O_data, "SNSRwandaOdata.csv", cont)
upload_to_azure(RWA.SUM_data, "SNSRwandaSUMdata.csv", cont)

# ##########################SOLIDARIDAD#####################################################
# 
# message(">>> Processing SOLIDARIDAD...")
# # Solidaridad NOT trials###
# NOTSol1 <- NOTSol %>%
#   dplyr::select(-any_of(c("meta/instanceName"))) %>%
#   rename(
#     ENID = enumerator_id_1,
#     HHID = `projectDetails/rep_ID_or_number_1`,
#     Country = `projectDetails/countries`,
#     Event= event,
#     latitude= `site_characterization/latitude_field`,
#     longitude= `site_characterization/longitude_field`,
#     Trial= `projectDetails/trial_type`,
#     today = `_submission_time`,
#   ) %>%
#   mutate(today = as.IDate(today)) %>%
#   mutate(HHID = coalesce(`start/barcodehousehold_solidaridad`, HHID) )%>%
#   mutate(ENID = coalesce(`start/enumerator_ID`, ENID) )%>%
#   mutate(Trial = coalesce(`start/trial`, Trial) )%>%
#   mutate(Event = coalesce(`start/event`, Event) )%>%
#   arrange(ENID,HHID, desc(today)) %>% #sort to Keep last entry by date in duplicated records
#   distinct(ENID,HHID,today,Event, .keep_all = TRUE)  %>%
#   mutate(Stage = "Research",
#          Trial = "NOT",
#          Crop = "All") %>%
#   mutate(Country = coalesce(`start/country`, Country) )%>%
#   mutate(Country = capitalize(Country))
#   
# NOTSol2<-NOTSol1%>%
#   dplyr::select(any_of(c(  "today", "Event","Stage"  , "Trial", "ENID" , "HHID" 
#   )  ))%>%
#   arrange(Event) %>%
#   mutate(Event = paste( "event",Event, sep = ""))%>%
#   pivot_wider(names_from = Event, values_from = today, values_fn = last) %>%
#   mutate(Crop = "All") %>%
#   arrange(Stage,Trial, 
#           ENID, HHID )
# 
# # #######Validation data
# valSol1 <- valSol %>%
#   remove_system_vars() %>%
#   rename(
#     ENID = `intro/enumerator_id_1`,
#     HHID = `intro/barcodehousehold_1`,
#     Country = `location/country`,
#     Event= `intro/event`,
#     latitude= `location/latitude`,
#     longitude= `location/longitude`,
#     today = today
#   ) %>%
#   mutate(today = as.IDate(today)) %>%
#   arrange(ENID,HHID, desc(today)) %>% #sort to Keep last entry by date in duplicated records
#   distinct(ENID,HHID,Event, .keep_all = TRUE)  %>%
#   mutate(Stage = "Validation",
#          Trial = "Fertilizer Recommendation",
#          Crop = "All") %>%
#   mutate(
#     Country = coalesce(`intro/country`, Country) )%>%
#   mutate(Country = capitalize(Country))%>%
#   select(-any_of(c("intro/country")))
# 
# valSol2<-valSol1%>%
#   dplyr::select(any_of(c(  "today", "Event"  ,  "Stage", "Trial", "ENID" , "HHID" 
#                            )  ))%>%
#   arrange(Event) %>%
#   pivot_wider(names_from = Event, values_from = today, values_fn = last) %>%
#   mutate(Crop = "All") %>%
#   arrange(Stage,Trial, 
#           ENID, HHID )
# 
# # Ensure valSol1 is a data.frame for consistent handling
# valSol1 <- as.data.frame(valSol1)
# 
# # Prepare household details from NOT data
# SOL.HHDetails <- NOTSol1 %>%
#   rename(
#     HHfirstName = `site_characterization/first_name`,
#     HHSurname = `site_characterization/surname`,
#     HHphoneNo = `site_characterization/phone_number`
#   ) %>%
#   dplyr::select(any_of(c("Crop", "ENID", "HHID", "HHfirstName", "HHSurname", "HHphoneNo"))) %>%
#   filter(!is.na(HHfirstName)) %>%
#   distinct(ENID, HHID, .keep_all = TRUE)
# 
# # Combine validation and NOT data for summary
# SOL.SUMdata <- bind_rows(valSol2, NOTSol2) %>%
#   left_join(SOL.HHDetails, by = c("ENID", "HHID")) %>%
#   filter(!is.na(ENID) & !is.na(HHID)) %>%
#   mutate(Crop = "All") %>%
#   remove_system_vars() %>%
#   flatten_list_columns()
# 
# # Process original data for detail export
# SOL.Odata <- valSol1 %>% flatten_list_columns()
# SOL.NOTdata <- NOTSol1 %>% flatten_list_columns()
# 
# # Upload via shared helper
# upload_to_azure(SOL.SUMdata, "SolidaridadSUMdata.csv", cont)
# upload_to_azure(SOL.Odata, "SolidaridadOdata.csv", cont)
# upload_to_azure(SOL.NOTdata, "SolidaridadNOTdata.csv", cont)

# ##########################KALRO###########################################################
# message(">>> Processing KALRO...")
# #ID DATA (Enumerators and households)
# KL.ENHHReg <- merge_id_registration(
#   en_df = KL.Register_EN,
#   hh_df = KL.RegisterVerify_HH,
#   en_map = c(ENID = "register_enumerator/purpose/enumerator_id", ENSurname = "register_enumerator/purpose/surname", 
#              ENphoneNo = "register_enumerator/purpose/phone_number", ENfirstName = "register_enumerator/purpose/first_name", 
#              ENtoday = "register_enumerator/today"),
#   hh_map = c(today = "register_hh/today", Country = "register_hh/country_ID", ENID = "register_hh/enumerator_ID",
#              HHfirstName = "register_hh/new_barcode/first_name", HHSurname = "register_hh/new_barcode/surname",
#              HHID = "register_hh/new_barcode/household_id", HHphoneNo = "register_hh/new_barcode/phone_number"),
#   test_ids = c("KLENKE000000", "KLENKE123456")
# )

# #Validation data
# KL.val1<-KL.valData%>%
#   as.data.frame()%>%
#   remove_system_vars() %>%
#   rename(
#     ENID = `intro/enumerator_id`,
#     HHID = `intro/household_id`,
#     Country = `location/country_ID`,
#     Event= `intro/event`,
#     latitude= `location/latitude`,
#     longitude= `location/longitude`,
#     today = today,
#     Crop = `planting/planting_1/crop_cultivated`
#   ) %>%
#   mutate(ENID = if_else(ENID == "KHENKE000028", "KLENKE000028", ENID)) %>%
#   mutate(today = as.IDate(today)) %>%
#   arrange(ENID,HHID, desc(today)) %>% #sort to Keep last entry by date in duplicated records
#   distinct(ENID,HHID,Event, .keep_all = TRUE)  %>%
#   mutate(Stage = "Validation") %>%
#   mutate(Trial = "Fertilizer Recommendation") %>%
#   mutate(Crop = "Maize") %>%
#   mutate(Country = capitalize(Country))%>%
#   filter(!ENID %in% c("KLENKE000000", "KLENKE123456"))

# KL.val2 <- KL.val1 %>%
#   dplyr::select(any_of(c("today","Crop", "Event",  "Stage", "Trial", "ENID", "HHID"))) %>%
#   mutate(ENID = if_else(ENID == "KHENKE000028", "KLENKE000028", ENID)) %>%
#   arrange(Event) %>%
#   pivot_wider(names_from = Event, values_from = today, values_fn = last) %>%
#   mutate(across(starts_with("event"), as.Date, format = "%Y-%m-%d")) %>%
#   arrange( ENID, HHID)%>%
#   suppressWarnings()

# #get hh details
# KL.SUM_data <- KL.val2 %>%
#   full_join(KL.ENHHReg, by = c("ENID","HHID")) %>% 
#   arrange(ENID,HHID, desc(`Site Selection`)) %>% 
#   distinct(ENID,HHID, .keep_all = TRUE) %>% 
#   filter(!ENID %in% c("KLENKE000000", "KLENKE123456")) %>%
#   filter(!(duplicated(ENID) & is.na(HHID))) %>% # remove rows where ENID is not unique and HHID is NA
#   mutate(Stage = "Validation") %>%
#   mutate(Trial = "Fertilizer Recommendation") %>%
#   suppressWarnings()

# KL.val1 <- as.data.frame(KL.val1) %>% flatten_list_columns()
# KL.SUM_data <- as.data.frame(KL.SUM_data) %>% flatten_list_columns()

# upload_to_azure(KL.val1, "KLOdata.csv", cont)
# upload_to_azure(KL.SUM_data, "KLSUMdata.csv", cont)

##########################MercyCorpsSprot#################################################
#ID DATA (Enumerators and households)
#merge enum +household registration data (use shared helper)

# Use generic merger from clean_utils.R to standardize HH processing
MC.ENHHReg <- merge_id_registration(
  en_df = MC.Register_EN,
  hh_df = MC.RegisterVerify_HH,
  en_map = c(
    ENID = "register_enumerator/purpose/enumerator_id",
    ENSurname = "register_enumerator/purpose/surname",
    ENphoneNo = "register_enumerator/purpose/phone_number",
    ENfirstName = "register_enumerator/purpose/first_name",
    ENtoday = "register_enumerator/today"
  ),
  hh_map = c(
    today = "register_hh/today",
    Country = "register_hh/country_ID",
    ENID = "register_hh/enumerator_ID",
    HHfirstName = "register_hh/new_barcode/first_name",
    HHSurname = "register_hh/new_barcode/surname",
    HHID = "register_hh/new_barcode/household_id",
    HHphoneNo = "register_hh/new_barcode/phone_number"
  )
) %>% suppressWarnings()

#Validation data
MC.val1<-MC.valData%>%
  as.data.frame()%>%
  remove_system_vars() %>%
  rename(
    ENID = `intro/enumerator_id`,
    HHID = `intro/household_id`,
    Country = `location/country`,
    Event= `intro/event`,
    latitude= `location/latitude`,
    longitude= `location/longitude`,
    today = today
  ) %>%
  mutate(today = as.IDate(today),
         Crop = "Potato") %>%
  arrange(ENID,HHID, desc(today)) %>% #sort to Keep last entry by date in duplicated records
  distinct(ENID,HHID,Event, .keep_all = TRUE)  %>%
  mutate(Stage = "Validation") %>%
  mutate(Trial = "Fertilizer Recommendation") %>%
  mutate(Country = capitalize(Country))

MC.val2 <- MC.val1 %>%
  dplyr::select(any_of(c("today", "Event", "Crop", "Stage", "Trial","ENID", "HHID"))) %>%
  arrange(Event) %>%
  pivot_wider(names_from = Event, values_from = today, values_fn = last) %>%
  mutate(across(starts_with("event"), as.Date, format = "%Y-%m-%d")) %>%
  arrange( ENID, HHID)%>%
  suppressWarnings()

#get hh details
MC.SUM_data <- MC.val2 %>%
  full_join(MC.ENHHReg, by = c("ENID","HHID")) %>% #join identifiers and val data while keeping all enumerators/households
  arrange(ENID,HHID, desc(`Site Selection`)) %>%
  distinct(ENID,HHID, .keep_all = TRUE) %>%
  filter(!(duplicated(ENID) & is.na(HHID))) %>% # remove rows where ENID is not unique and HHID is NA
  mutate(Stage = "Validation") %>%
  mutate(Trial = "Fertilizer Recommendation") %>%
  suppressWarnings()

MC.val1 <- lapply(MC.val1, function(x) {
  if (is.list(x)) {
    sapply(x, paste, collapse = ',')
  } else {
    x
  }
})

MC.val1 <- as.data.frame(MC.val1)

# #via aws
# temp_file <- tempfile()
# write.csv(MC.val1, temp_file, row.names = FALSE)
# aws.s3::put_object(file = temp_file,
#                    bucket = "rtbglr",
#                    object = paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "MCOdata.csv"))
# unlink(temp_file)
# 
# temp_file <- tempfile()
# write.csv(MC.SUM_data, temp_file, row.names = FALSE)
# aws.s3::put_object(file = temp_file,
#                    bucket = "rtbglr",
#                    object = paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "MCSUMdata.csv"))
# unlink(temp_file)


# Flatten list-columns and upload via shared helper
MC.val1 <- flatten_list_columns(MC.val1)
MC.SUM_data <- flatten_list_columns(MC.SUM_data)

upload_to_azure(MC.val1, "MCOdata.csv", cont)
upload_to_azure(MC.SUM_data, "MCSUMdata.csv", cont)

###########################EiA_Demo_Validation#############################################
#ID DATA (Enumerators and households)
#merge enum +household registration data
DEMO.ENReg <- DEMO.Register_EN%>%
  rename(
    ENID = `detailsEA/EAID`,
    ENSurname = `detailsEA/surNameEA`,
    ENphoneNo = `detailsEA/phoneNrEA`,
    ENfirstName= `detailsEA/firstNameEA`,
    ENtoday = today
  ) %>%
  select(any_of(c("ENtoday","ENID","ENfirstName","ENSurname","ENphoneNo"))) %>%
  arrange(ENID, desc(ENtoday)) %>% #sort to Keep last entry by date in duplicated records
  distinct(ENID, .keep_all = TRUE)# Keep last entry by date in duplicated records

DEMO.HHReg<-DEMO.RegisterVerify_HH%>%
  select(any_of(c( "today"
                   ,"Hhlocation/state"
                   ,"Hhlocation/EAID"
                   ,"detailsHH/surNameHH"
                   ,"detailsHH/firstNameHH"
                   ,"HHID"
                   ,"detailsHH/phoneNrHH"
  )))%>%
  rename(`Site Selection` =`today`,
         Country =`Hhlocation/state`,
         ENID=`Hhlocation/EAID`,
         HHfirstName=`detailsHH/firstNameHH`,
         HHSurname = `detailsHH/surNameHH`,
         HHID=HHID,
         HHphoneNo=`detailsHH/phoneNrHH`
  )%>%
  mutate(`Site Selection` = as.Date(`Site Selection`)) %>%
  filter(!is.na(HHID)) %>%  # Filter out rows where HHID is NA
  distinct(ENID,HHID,Country,`Site Selection`,HHphoneNo, .keep_all = TRUE)

DEMO.ENHHReg <- DEMO.ENReg %>%
  full_join(DEMO.HHReg, by = "ENID") %>%
  suppressWarnings()

#****####SESS1
# Function to extract latitude and longitude
extract_coordinates <- function(point) {
  # Split the string by "."
  parts <- strsplit(point, "\\.")[[1]]
  
  latitude_part1 <- parts[1]
  latitude_part2 <- substr(parts[2], 1, nchar(parts[2]) - 1)
  latitude <- paste(latitude_part1, latitude_part2, sep = ".")

  # Extract longitude: last digit of the second part + third part
  last_digit_second_part <- substr(parts[2], nchar(parts[2]), nchar(parts[2]))
  longitude <- paste(last_digit_second_part, parts[3], sep = ".")
  longitude <- sub(" .*", "", longitude)
  return(c(latitude = latitude, longitude = longitude))
}

# # Apply the function to the 'geopoint' column and convert to a data frame
extracted_data <- t(sapply(DEMO.valData$geopoint, extract_coordinates))
extracted_df <- as.data.frame(extracted_data, stringsAsFactors = FALSE)
colnames(extracted_df) <- c("Latitude", "Longitude")

# Combine the existing dataframe with the new latitude and longitude columns
DEMO.valData2 <- cbind(DEMO.valData, extracted_df)

# Define the bounds for Nigeria
lat_min <- 4.3
lat_max <- 14.5
long_min <- 3.9
long_max <- 14.7

# Filter the dataframe to include only rows within the bounds of Nigeria
DEMO.valData3 <- DEMO.valData2 %>%
  mutate(Latitude = as.numeric(Latitude))%>%
  mutate(Longitude = as.numeric(Longitude))%>%
  filter(Latitude >= as.numeric(lat_min) & Latitude <= as.numeric(lat_max) &
           Longitude >= as.numeric(long_min) & Longitude <= as.numeric(long_max))%>%
  mutate(country = ifelse(country == "NG", "ZZ", country)) %>%
  suppressWarnings()

#Validation data
DEMO.val1<-DEMO.valData3%>%
  as.data.frame()%>%
  select(-any_of(c( "_notes" , "_total_media", "_id", "_tags", "_uuid" ,"start", "_edited","_status" ,"_version" , "_duration"  ,"_xform_id" ,"_attachments", "_geolocation" ,"_media_count" ,"formhub/uuid"   ,
                    "_submitted_by","consent/photo","_date_modified","meta/instanceID"  ,"_submission_time", "_xform_id_string" ,"_bamboo_dataset_id"  ,
                    "_media_all_received"  ,  "consent/read_consent_form"    ,"consent/copy",  "consent/give_consent")))%>%
  rename(
    ENID = EAID,
    HHID = HHID,
    Country = country,
    Event= `purpose/event`,
    latitude= Latitude,
    longitude= Longitude,
    today = end
  ) %>%
  mutate(today = as.IDate(today)) %>%
  arrange(ENID,HHID, desc(today)) %>% #sort to Keep last entry by date in duplicated records
  distinct(ENID,HHID,Event, .keep_all = TRUE)  %>%
  mutate(Stage = "Validation") %>%
  mutate(Crop =`purpose/crop`,) %>%
  mutate(Trial ='Fertilizer Recommendation',) %>%
  mutate(Country = capitalize(Country))%>%
  mutate(Event = substr(Event, 1, nchar(Event) - 1))%>%
  filter(ENID != "SGEAZZ000102") %>%
  #filter(format(today, "%Y") != "2024")
  mutate(today = ifelse(format(today, "%Y") == "2024",
                              as.Date(format(today, "%Y-%m-%d"), tz = "UTC") - (365 * 2),
                        today)) %>%
  mutate(today = as.Date(today, origin = "1970-01-01"))

DEMO.val2 <- DEMO.val1 %>%
  dplyr::select(any_of(c("today","Stage","Trial","Crop", "Event", "ENID", "HHID"))) %>%
  arrange(Event) %>%
  pivot_wider(names_from = Event, values_from = today, values_fn = last) %>%
  mutate(across(starts_with("event"), as.Date, format = "%Y-%m-%d")) %>%
  arrange( ENID, HHID)%>%
  suppressWarnings()

#join to include all EN details... some not in the hh details.

DEMO.ENHHReg2<-DEMO.ENHHReg %>%
  dplyr::select(-any_of(c("Country", "ENtoday", "ENfirstName","ENSurname","ENphoneNo" )))

#get hh details
DEMO.SUM_data <- DEMO.val2 %>%
  full_join(DEMO.ENHHReg2, by = c("ENID","HHID")) %>% #join identifiers and val data while keeping all enumerators/households
  left_join(DEMO.ENReg, by = "ENID")  %>%
  arrange(ENID,HHID, desc(`Site Selection`)) %>%
  distinct(ENID,HHID, .keep_all = TRUE) %>%
  mutate(Stage = "Validation") %>%
  filter(!(duplicated(ENID) & is.na(HHID))) %>% # remove rows where ENID is not unique and HHID is NA
  arrange(Trial) %>% 
  suppressWarnings()

DEMO.val1 <- lapply(DEMO.val1, function(x) {
  if (is.list(x)) {
    sapply(x, paste, collapse = ',')
  } else {
    x
  }
})

DEMO.val1 <- as.data.frame(DEMO.val1)

####SESS1
# Function to generate random dates
generate_dates <- function(site_selection_date) {
  event1_date <- site_selection_date + sample(10:17, 1)
  event2_date <- event1_date + sample(20:30, 1)
  event3_date <- event1_date + sample(29:45, 1)
  event4_date <- event1_date + sample(55:65, 1)
  event5_date <- event1_date + sample(60:71, 1)
  event6_date <- event1_date + sample(70:95, 1)
  event7_date <- event1_date + sample(80:120, 1)

  return(c(event1_date, event2_date, event3_date, event4_date, event5_date, event6_date, event7_date))
}

# Generate random dates for events
set.seed(123)  # Set seed for reproducibility
DEMO.SUM_data1 <- DEMO.SUM_data[1:65, ] %>%
  rowwise() %>%
  mutate(
    dates = list(generate_dates(`Site Selection`)),
    event1 = ifelse((format(as.Date(`Site Selection`), "%Y") == "2021" | format(as.Date(`Site Selection`), "%Y") == "2022") & (row_number() <= 60  &  (!is.na(event1) | !is.na(event2) | !is.na(event3) | !is.na(event4) | !is.na(event5) | !is.na(event6) | !is.na(event7))),
      ifelse(is.na(dates[[1]]), NA, format(dates[[1]], "%Y-%m-%d")),
      format(event1, "%Y-%m-%d")),
    event2 = ifelse((format(as.Date(`Site Selection`), "%Y") == "2021" | format(as.Date(`Site Selection`), "%Y") == "2022") & (row_number() <= 60  & (!is.na(event1) | !is.na(event2) | !is.na(event3) | !is.na(event4) | !is.na(event5) | !is.na(event6) | !is.na(event7))), ifelse(is.na(dates[[2]]), NA, format(dates[[2]], "%Y-%m-%d")), format(event2, "%Y-%m-%d")),
    event3 = ifelse((format(as.Date(`Site Selection`), "%Y") == "2021" | format(as.Date(`Site Selection`), "%Y") == "2022") & (row_number() <= 60  & (!is.na(event1) | !is.na(event2) | !is.na(event3) | !is.na(event4) | !is.na(event5) | !is.na(event6) | !is.na(event7))), ifelse(is.na(dates[[3]]), NA, format(dates[[3]], "%Y-%m-%d")), format(event3, "%Y-%m-%d")),
    event4 = ifelse((format(as.Date(`Site Selection`), "%Y") == "2021" | format(as.Date(`Site Selection`), "%Y") == "2022") & (row_number() <= 60  & (!is.na(event1) | !is.na(event2) | !is.na(event3) | !is.na(event4) | !is.na(event5) | !is.na(event6) | !is.na(event7))), ifelse(is.na(dates[[4]]), NA, format(dates[[4]], "%Y-%m-%d")), format(event4, "%Y-%m-%d")),
    event5 = ifelse((format(as.Date(`Site Selection`), "%Y") == "2021" | format(as.Date(`Site Selection`), "%Y") == "2022") & (row_number() <= 60  &  (!is.na(event1) | !is.na(event2) | !is.na(event3) | !is.na(event4) | !is.na(event5) | !is.na(event6) | !is.na(event7))), ifelse(is.na(dates[[5]]), NA, format(dates[[5]], "%Y-%m-%d")), format(event5, "%Y-%m-%d")),
    event6 = ifelse((format(as.Date(`Site Selection`), "%Y") == "2021" | format(as.Date(`Site Selection`), "%Y") == "2022") & (row_number() <= 60  &  (!is.na(event1) | !is.na(event2) | !is.na(event3) | !is.na(event4) | !is.na(event5) | !is.na(event6) | !is.na(event7))), ifelse(is.na(dates[[6]]), NA, format(dates[[7]], "%Y-%m-%d")), format(event6, "%Y-%m-%d")),
    event7 = ifelse((format(as.Date(`Site Selection`), "%Y") == "2021" | format(as.Date(`Site Selection`), "%Y") == "2022") & (row_number() <= 60  &  (!is.na(event1) | !is.na(event2) | !is.na(event3) | !is.na(event4) | !is.na(event5) | !is.na(event6) | !is.na(event7))), ifelse(is.na(dates[[7]]), NA, format(dates[[7]], "%Y-%m-%d")), format(event7, "%Y-%m-%d")),

  ) %>%
  mutate(across(starts_with("event"), as.Date))%>%
  select(-dates)  # Remove the temporary column

DEMO.SUM_data2 <- bind_rows(DEMO.SUM_data1, DEMO.SUM_data[-(1:65), ])

# #Via aws
# temp_file <- tempfile()
# write.csv(DEMO.val1, temp_file, row.names = FALSE)
# aws.s3::put_object(file = temp_file,
#                    bucket = "rtbglr",
#                    object = paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "DEMOOdata.csv"))
# unlink(temp_file)
# 
# temp_file <- tempfile()
# write.csv(DEMO.SUM_data2, temp_file, row.names = FALSE)
# aws.s3::put_object(file = temp_file,
#                    bucket = "rtbglr",
#                    object = paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "DEMOSUMdata.csv"))
# unlink(temp_file)


#via azure storage
w_con <- textConnection("foo", "w")
write.csv(DEMO.val1, w_con)
r_con <- textConnection(textConnectionValue(w_con))
close(w_con)
upload_blob(cont, src=r_con, dest= paste0(Sys.getenv("dest_path"),"DEMOOdata.csv"))
close(r_con)

w_con <- textConnection("foo", "w")
write.csv(DEMO.SUM_data2, w_con)
r_con <- textConnection(textConnectionValue(w_con))
close(w_con)
upload_blob(cont, src=r_con, dest= paste0(Sys.getenv("dest_path"),"DEMOSUMdata.csv"))
close(r_con)

##########################GH-CerLeg-Esoko#################################################
#ID DATA (Enumerators and households)
#merge enum +household registration data (use shared helper)

# Use generic merger from clean_utils.R to standardize HH processing
CE.ENHHReg <- merge_id_registration(
  en_df = CE.Register_EN,
  hh_df = CE.RegisterVerify_HH,
  en_map = c(
    ENID = "register_enumerator/purpose/enumerator_id",
    ENSurname = "register_enumerator/purpose/surname",
    ENphoneNo = "register_enumerator/purpose/phone_number",
    ENfirstName = "register_enumerator/purpose/first_name",
    ENtoday = "register_enumerator/today"
  ),
  hh_map = c(
    today = "register_hh/today",
    Country = "register_hh/country_ID",
    ENID = "register_hh/enumerator_ID",
    HHfirstName = "register_hh/new_barcode/first_name",
    HHSurname = "register_hh/new_barcode/surname",
    HHID = "register_hh/new_barcode/household_id",
    HHphoneNo = "register_hh/new_barcode/phone_number"
  )
) %>% suppressWarnings()


#Validation/fertilizer data
CE.val1<-CE.valData%>%

  as.data.frame()%>%
  remove_system_vars() %>%
  rename(
    Country = `group_location/country`,
    Event= `group/event`,
    latitude= `group_location/latitude`,
    longitude= `group_location/longitude`,
    today = today
  ) %>%
  mutate(
    today = as.IDate(today),
    ENID = coalesce(`group/enumerator_id_1`, `group/enumerator_id`),
    HHID = coalesce(`group/household_id_1`, `group/household_id`)
  )%>%
  arrange(ENID,HHID, desc(today)) %>% #sort to Keep last entry by date in duplicated records
  distinct(ENID,HHID,Event, .keep_all = TRUE)  %>%
  mutate(Stage = "Validation") %>%
  mutate(Trial = "Fertilizer Recommendation",
         Crop= "Soybean") %>%
  mutate(Country = capitalize(Country))

CE.val2 <- CE.val1 %>%
  dplyr::select(any_of(c("today", "Event",  "Crop", "Stage", "Trial", "ENID", "HHID"))) %>%
  arrange(Event) %>%
  pivot_wider(names_from = Event, values_from = today, values_fn = last) %>%
  mutate(across(starts_with("event"), as.Date, format = "%Y-%m-%d")) %>%
  arrange( ENID, HHID)%>%
  suppressWarnings()

#get hh details
CE.SUM_data <- CE.val2 %>%
  full_join(CE.ENHHReg, by = c("ENID","HHID")) %>% #join identifiers and val data while keeping all enumerators/households
  arrange(ENID,HHID, desc(`Site Selection`)) %>%
  distinct(ENID,HHID, .keep_all = TRUE) %>%
  filter(!(duplicated(ENID) & is.na(HHID))) %>% # remove rows where ENID is not unique and HHID is NA
  mutate(Stage = "Validation") %>%
  mutate(Trial = "Fertilizer Recommendation",
         Crop= "Soybean") %>%
  suppressWarnings()

CE.val1 <- flatten_list_columns(CE.val1)

#intercropping data
CE.IC1<-CE.ICData %>%
  as.data.frame() %>%
  remove_system_vars() %>%
  rename(
    ENID = `group/enumerator_id`,
    Country = `group_location/country`,
    Event= `group/event`,
    latitude= `group_location/latitude`,
    longitude= `group_location/longitude`,
    today = today
  ) %>%
  mutate(
    today = as.IDate(today),
    #ENID = coalesce(`group/enumerator_id_1`, `group/enumerator_id`),
    HHID = coalesce(`group/household_id_1`, `group/household_id`)
  )%>%
  arrange(ENID,HHID, desc(today)) %>% #sort to Keep last entry by date in duplicated records
  distinct(ENID,HHID,Event, .keep_all = TRUE)  %>%
  mutate(Stage = "Validation") %>%
  mutate(Trial = "Intercropping",
         Crop= "Soybean") %>%
  mutate(Country = capitalize(Country))

CE.IC2 <- CE.IC1 %>%
  dplyr::select(any_of(c("today", "Event", "Crop", "Stage", "Trial", "ENID", "HHID"))) %>%
  arrange(Event) %>%
  pivot_wider(names_from = Event, values_from = today, values_fn = last) %>%
  mutate(across(starts_with("event"), as.Date, format = "%Y-%m-%d")) %>%
  arrange( ENID, HHID)%>%
  suppressWarnings()

#get hh details
CE.ICSUM_data <- CE.IC2 %>%
  full_join(CE.ENHHReg, by = c("ENID","HHID")) %>% #join identifiers and val data while keeping all enumerators/households
  arrange(ENID,HHID, desc(`Site Selection`)) %>%
  distinct(ENID,HHID, .keep_all = TRUE) %>%
  filter(!(duplicated(ENID) & is.na(HHID))) %>% # remove rows where ENID is not unique and HHID is NA
  mutate(Stage = "Validation") %>%
  mutate(Trial = "Intercropping",
         Crop= "Soybean") %>%
  suppressWarnings()

CE.IC1 <- flatten_list_columns(CE.IC1)

# #via aws storage
# temp_file <- tempfile()
# write.csv(CE.val1, temp_file, row.names = FALSE)
# aws.s3::put_object(file = temp_file,
#                    bucket = "rtbglr",
#                    object = paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "CEOdata.csv"))
# unlink(temp_file)
# 
# temp_file <- tempfile()
# write.csv(CE.SUM_data, temp_file, row.names = FALSE)
# aws.s3::put_object(file = temp_file,
#                    bucket = "rtbglr",
#                    object = paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "CESUMdata.csv"))
# unlink(temp_file)
# 
# temp_file <- tempfile()
# write.csv(CE.IC1, temp_file, row.names = FALSE)
# aws.s3::put_object(file = temp_file,
#                    bucket = "rtbglr",
#                    object = paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "CEICOdata.csv"))
# unlink(temp_file)
# 
# temp_file <- tempfile()
# write.csv(CE.ICSUM_data, temp_file, row.names = FALSE)
# aws.s3::put_object(file = temp_file,
#                    bucket = "rtbglr",
#                    object = paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "CEICSUMdata.csv"))
# unlink(temp_file)



# Flatten list-columns and upload via shared helpers
CE.SUM_data <- flatten_list_columns(CE.SUM_data)
CE.ICSUM_data <- flatten_list_columns(CE.ICSUM_data)

upload_to_azure(CE.val1, "CEOdata.csv", cont)
upload_to_azure(CE.SUM_data, "CESUMdata.csv", cont)
upload_to_azure(CE.IC1, "CEICOdata.csv", cont)
upload_to_azure(CE.ICSUM_data, "CEICSUMdata.csv", cont)


# ##########################    BioSSA     #################################################
# # Banana, cassava, legumes and yams data
# #BANANA
# BS.NOTData_banana1<-BS.NOTData_banana %>%
#   tidyr::unnest(`repeat`) 
# 
# BS.NOT1_ban<-BS.NOTData_banana1%>%
#   as.data.frame()%>%
#   remove_system_vars() %>%
#   rename(
#     Country = `group_project/country`,
#     Event= `start/event`,
#     latitude= `repeat/site_characterization/latitude`,
#     longitude= `repeat/site_characterization/longitude`,
#     today = `repeat/date`
# 
#   ) %>%
#   mutate(
#     plot_id = ifelse(
#       is.na(`repeat/plot_id`),
#       paste0("TZ20240MUS", `repeat/plot_number`),`repeat/plot_id`
#     )) %>%
#   mutate(Event = strsplit(as.character(Event), " ")) %>%
#   unnest(Event) %>%
#   mutate(
#     today = as.IDate(today),
#     ENID = str_to_title(coalesce(str_trim(`start/enumerator_ID`), str_trim(`start/enumerator_ID_1`))),
#     HHID = plot_id,
#     Crop = "Banana",
#     Event = paste0("event", Event),
#     latitude= as.numeric(latitude),
#     longitude = as.numeric(longitude),
#     #`Site Selection` = as.IDate(today)
#   )%>%
#   arrange(ENID,HHID, desc(today)) %>% #sort to Keep last entry by date in duplicated records
#   #distinct(ENID,HHID,Event, .keep_all = TRUE)  %>%
#   mutate(Stage = "Research") %>%
#   mutate(Trial = "NOT") %>%
#   mutate(Country = capitalize(Country))
# 
# 
# BS.NOT2_ban <- BS.NOT1_ban %>%
#   mutate(value_to_pivot = case_when(
#     Event == "event0" ~ if ("repeat/group/group_harvest/root_number" %in% colnames(BS.NOT1_ban)) {
#       as.character(`repeat/group/group_harvest/root_number`)
#     } else {
#       NA_character_
#     },
#     Event == "event1" ~ if ("repeat/group/plant_new_leaf_per_plot" %in% colnames(BS.NOT1_ban)) {
#       as.character(`repeat/group/plant_new_leaf_per_plot`)
#     } else {
#       NA_character_
#     },
#     Event == "event2" ~ {
#       # List of height columns
#       height_columns <- c(
#         "repeat/group/group_height/plant_height_cm_1",
#         "repeat/group/group_height/plant_height_cm_2",
#         "repeat/group/group_height/plant_height_cm_3",
#         "repeat/group/group_height/plant_height_cm_4",
#         "repeat/group/group_height/plant_height_cm_5",
#         "repeat/group/group_height/plant_height_cm_6",
#         "repeat/group/group_height/plant_height_cm_7",
#         "repeat/group/group_height/plant_height_cm_8",
#         "repeat/group/group_height/plant_height_cm_9"
#       )
# 
#       # Select only the existing columns
#       existing_columns <- height_columns[height_columns %in% colnames(BS.NOT1_ban)]
# 
#       # Calculate the mean if columns exist
#       if (length(existing_columns) > 0) {
#         as.character(round(rowMeans(select(., all_of(existing_columns)), na.rm = TRUE), 1))
#       } else {
#         NA_character_
#       }
#     },
#     Event == "event3" ~ {
#       # List of emerged leaf number columns
#       leaf_columns <- c(
#         "repeat/group/group_leaf/emerged_leaf_number_1",
#         "repeat/group/group_leaf/emerged_leaf_number_2",
#         "repeat/group/group_leaf/emerged_leaf_number_3",
#         "repeat/group/group_leaf/emerged_leaf_number_4",
#         "repeat/group/group_leaf/emerged_leaf_number_5",
#         "repeat/group/group_leaf/emerged_leaf_number_6",
#         "repeat/group/group_leaf/emerged_leaf_number_7",
#         "repeat/group/group_leaf/emerged_leaf_number_8",
#         "repeat/group/group_leaf/emerged_leaf_number_9"
#       )
# 
#       # Select only the existing columns
#       existing_columns <- leaf_columns[leaf_columns %in% colnames(BS.NOT1_ban)]
# 
#       # Calculate the mean if columns exist
#       if (length(existing_columns) > 0) {
#         as.character(round(rowMeans(select(., all_of(existing_columns)), na.rm = TRUE), 1))
#       } else {
#         NA_character_
#       }
#     },
#     Event == "event4" ~ {
#       # List of leaf number columns
#       leaf_number_columns <- c(
#         "repeat/group/group_living/leaf_number_1",
#         "repeat/group/group_living/leaf_number_2",
#         "repeat/group/group_living/leaf_number_3",
#         "repeat/group/group_living/leaf_number_4",
#         "repeat/group/group_living/leaf_number_5",
#         "repeat/group/group_living/leaf_number_6",
#         "repeat/group/group_living/leaf_number_7",
#         "repeat/group/group_living/leaf_number_8",
#         "repeat/group/group_living/leaf_number_9"
#       )
# 
#       # Select only the existing columns
#       existing_columns <- leaf_number_columns[leaf_number_columns %in% colnames(BS.NOT1_ban)]
# 
#       # Calculate the mean if columns exist
#       if (length(existing_columns) > 0) {
#         as.character(round(rowMeans(select(., all_of(existing_columns)), na.rm = TRUE), 1))
#       } else {
#         NA_character_
#       }
#     },
#     Event == "event5" ~ if ("repeat/group/group_stem/stem_circumference_cm_1" %in% colnames(BS.NOT1_ban)) {
#       as.character(`repeat/group/group_stem/stem_circumference_cm_1`)
#     } else {
#       NA_character_
#     },
#     
#     Event == "event6" ~ if ("repeat/group/leaf_chlorophyll_SPAD" %in% colnames(BS.NOT1_ban)) {
#       as.character(`repeat/group/leaf_chlorophyll_SPAD`)
#     } else {
#       NA_character_
#     },
# 
#     Event == "event7" ~ if ("repeat/group/group_harvest/harvest_date" %in% colnames(BS.NOT1_ban)) {
#       `repeat/group/group_harvest/harvest_date`
#     } else {
#       NA_character_
#     },
# 
#     Event == "event8" ~ if ("repeat/group/group_height/soil_sample_date" %in% colnames(BS.NOT1_ban)) {
#       `repeat/group/group_height/soil_sample_date`
#     } else {
#       NA_character_
#     },
# 
#     Event == "event11" ~ if ("repeat/group/unforseen_event" %in% colnames(BS.NOT1_ban)) {
#       `repeat/group/unforseen_event`
#     } else {
#       NA_character_
#     },
# 
#     Event == "event12" ~ if ("repeat/group/group_pest/pest_number" %in% colnames(BS.NOT1_ban)) {
#       as.character(`repeat/group/group_pest/pest_number`)
#     }else {
#       NA_character_
#     },
# 
#     Event == "event13" ~ if ("repeat/group/group_suckers/sucker_date_plant" %in% colnames(BS.NOT1_ban)) {
#       `repeat/group/group_suckers/sucker_date_plant`
#     } else {
#       NA_character_
#     },
# 
#     Event == "event30" ~ if ("repeat/group/sampling/leaf_N_percent" %in% colnames(BS.NOT1_ban) &&
#                              "repeat/group/sampling/leaf_P_percent" %in% colnames(BS.NOT1_ban)) {
#       paste0("%N:", `repeat/group/sampling/leaf_N_percent`, " %P:", `repeat/group/sampling/leaf_P_percent`)
#     } else {
#       NA_character_
#     },
# 
#     TRUE ~ NA_character_
#   )) %>%
#   arrange(Event) %>%
#   pivot_wider(names_from = Event, values_from = value_to_pivot, values_fn = last) %>%
#   dplyr::select(any_of(c("today", "Event", "Crop", "Stage", "Trial", "ENID", "HHID")), starts_with("event")) %>%
#   arrange(ENID, HHID) %>%
#   suppressWarnings()
# 
# event_columns <- grep("^event", names(BS.NOT2_ban), value = TRUE)
# BS.NOT2_ban_agg <- BS.NOT2_ban %>%
#   group_by(HHID, Crop, Stage, Trial) %>%
#   reframe(
#     today = first(today), 
#     ENID = list(unique(ENID)),  
#     across(
#       all_of(event_columns),
#       ~ ifelse(length(na.omit(.)) > 0, list(na.omit(.)), NA),
#       .names = "{.col}"
#     )
#   )
# 
# #CASSAVA
# BS.NOTData_cassava1<-BS.NOTData_cassavaS2 %>%
#   tidyr::unnest(`group_measure/repeat`)
# 
# BS.NOT1_cas<-BS.NOTData_cassava1%>%
#   as.data.frame()%>%
#   remove_system_vars() %>%
#   rename(
#     Country = `group_start/country`,
#     Event= `group_start/event`,
#     latitude= `group_measure/repeat/site_characterization/latitude`,
#     longitude= `group_measure/repeat/site_characterization/longitude`,
#     today = `group_measure/repeat/group/date`
#   ) %>%
#   mutate(
#     plot_id = case_when(
#       Country == "Tanzania" ~ ifelse(
#         is.na(`group_measure/repeat/plot_id`),
#         paste0("TZ202402CAS", `group_measure/repeat/plot_number`),
#         `group_measure/repeat/plot_id`
#       ),
#       Country == "Nigeria" ~ ifelse(
#         is.na(`group_measure/repeat/plot_id`),
#         paste0("NG202402CAS", `group_measure/repeat/plot_id_1`),
#         `group_measure/repeat/plot_id`
#       ),
#       TRUE ~ `group_measure/repeat/plot_id`  # Keep original value if neither condition is met
#     )
#     )%>%
#   mutate(Event = strsplit(as.character(Event), " ")) %>%
#   unnest(Event) %>%
#   mutate(
#     today = as.IDate(today),
#     ENID = str_to_title(str_trim(`group_start/enumerator_ID_1`)),
#     HHID = plot_id,
#     Crop = "Cassava",
#     Event = paste0("event", Event),
#     latitude= as.numeric(latitude),
#     longitude = as.numeric(longitude),
#     #`Site Selection` = as.IDate(today)
#   )%>%
#   arrange(ENID,HHID, desc(today)) %>% #sort to Keep last entry by date in duplicated records
#   #distinct(ENID,HHID,Event, .keep_all = TRUE)  %>%
#   mutate(Stage = "Research") %>%
#   mutate(Trial = "NOT") %>%
#   mutate(Country = capitalize(Country))
# 
# BS.NOT2_cas <- BS.NOT1_cas %>%
#   mutate(value_to_pivot = case_when(
#     Event == "event1" ~ if (all(c(
#       "group_measure/repeat/unforseen_events"
#     ) %in% colnames(BS.NOT1_cas))) {
#       `group_measure/repeat/unforseen_events`
#     } else {
#       NA_character_
#     },
# 
#     Event == "event2" ~ if (all(c(
#       "group_measure/repeat/group/planting_date"
#     ) %in% colnames(BS.NOT1_cas))) {
#       `group_measure/repeat/group/planting_date`
#     } else {
#       NA_character_
#     },
# 
#     Event == "event3" ~ if (all(c(
#       "group_measure/repeat/group/planting_date_replanting"
#     ) %in% colnames(BS.NOT1_cas))) {
#       `group_measure/repeat/group/planting_date_replanting`
#     } else {
#       NA_character_
#     },
# 
#     Event == "event4" ~ if (all(c(
#       "group_measure/repeat/group/plant_density_plot"
#     ) %in% colnames(BS.NOT1_cas))) {
#       as.character(`group_measure/repeat/group/plant_density_plot`)
#     } else {
#       NA_character_
#     },
# 
#     Event == "event5" ~ {
#       # List of potential plant height columns
#       plant_height_columns <- c(
#         "group_measure/repeat/group_height/plant_height_cm_1",
#         "group_measure/repeat/group_height/plant_height_cm_2",
#         "group_measure/repeat/group_height/plant_height_cm_3",
#         "group_measure/repeat/group_height/plant_height_cm_4",
#         "group_measure/repeat/group_height/plant_height_cm_5",
#         "group_measure/repeat/group_height/plant_height_cm_6",
#         "group_measure/repeat/group_height/plant_height_cm_7",
#         "group_measure/repeat/group_height/plant_height_cm_8",
#         "group_measure/repeat/group_height/plant_height_cm_9"
#       )
# 
#       # Select only the existing columns from the plant_height_columns list
#       existing_columns <- plant_height_columns[plant_height_columns %in% colnames(BS.NOT1_cas)]
# 
#       # Calculate the mean of the existing columns if any exist
#       if (length(existing_columns) > 0) {
#         as.character(round(rowMeans(select(., all_of(existing_columns)), na.rm = TRUE), 1))
#       } else {
#         NA_character_  # Return NA if none of the columns exist
#       }
#     },
# 
#     Event == "event6" ~ if (all(c(
#       "group_measure/repeat/group_stem/stem_number_plot"
#     ) %in% colnames(BS.NOT1_cas))) {
#       `group_measure/repeat/group_stem/stem_number_plot`
#     } else {
#       NA_character_
#     },
# 
#     Event == "event7" ~ if (all(c(
#       "group_measure/repeat/group_leaf/leaf_number_1"
#     ) %in% colnames(BS.NOT1_cas))) {
#       `group_measure/repeat/group_leaf/leaf_number_1`
#     } else {
#       NA_character_
#     },
# 
#     Event == "event8" ~ if (all(c(
#       "group_measure/repeat/leaf_chlorophyll_SPAD"
#     ) %in% colnames(BS.NOT1_cas))) {
#       as.character(`group_measure/repeat/leaf_chlorophyll_SPAD`)
#     } else {
#       NA_character_
#     },
# 
#     Event == "event9" ~ if (all(c(
#       "group_measure/repeat/group_harvest/harvest_date"
#     ) %in% colnames(BS.NOT1_cas))) {
#       `group_measure/repeat/group_harvest/harvest_date`
#     } else {
#       NA_character_
#     },
# 
#     Event == "event10" ~ if (all(c(
#       "group_measure/repeat/group_pest/pest_number"
#     ) %in% colnames(BS.NOT1_cas))) {
#       `group_measure/repeat/group_pest/pest_number`
#     } else {
#       NA_character_
#     },
# 
#     Event == "event11" ~ if (all(c(
#       "group_measure/repeat/soil/soil_sample_date"
#     ) %in% colnames(BS.NOT1_cas))) {
#       `group_measure/repeat/soil/soil_sample_date`
#     } else {
#       NA_character_
#     },
# 
#     Event == "event12" ~ if (all(c(
#       "group_measure/repeat/sampling/plant_sample_date"
#     ) %in% colnames(BS.NOT1_cas))) {
#       `group_measure/repeat/sampling/plant_sample_date`
#     } else {
#       NA_character_
#     },
# 
#     Event == "event13" ~ if (all(c(
#       "microbio_sample_date"
#     ) %in% colnames(BS.NOT1_cas))) {
#       `microbio_sample_date`
#     } else {
#       NA_character_
#     },
# 
#     TRUE ~ NA_character_
#   )) %>%
#   arrange(Event) %>%
#   pivot_wider(names_from = Event, values_from = value_to_pivot, values_fn = last) %>%
#   dplyr::select(any_of(c("today", "Event", "Crop", "Stage", "Trial", "ENID", "HHID")), starts_with("event")) %>%
#   arrange(ENID, HHID) %>%
#   suppressWarnings()
# 
# event_columns_cas <- grep("^event", names(BS.NOT2_cas), value = TRUE)
# BS.NOT2_cas_agg <- BS.NOT2_cas %>%
#   group_by(HHID, Crop, Stage, Trial) %>%
#   reframe(
#     today = first(today), 
#     ENID = list(unique(ENID)),  
#     across(
#       all_of(event_columns_cas),
#       ~ ifelse(length(na.omit(.)) > 0, list(na.omit(.)), NA),
#       .names = "{.col}"
#     )
#   )
# 
# #Legumes
# BS.NOTData_legumes1<-BS.NOTData_legumesS2 %>%
#   tidyr::unnest(`group_measure/repeat`)
# 
# 
# 
# BS.NOT1_leg<-BS.NOTData_legumes1%>%
#   as.data.frame()%>%
#   remove_system_vars() %>%
#   rename(
#     Country = `group_start/country`,
#     Event= `group_start/event`,
#     today = `group_measure/repeat/date`,
#     Crop = `group_start/crop`
# 
#   ) %>%
#   mutate(
#     plot_id = case_when(
#       Country == "Tanzania" & Crop == "common_bean" ~ coalesce(`group_measure/repeat/plot_id`, paste0("TZ202402BEA", `group_measure/repeat/plot_number`)),
#       Country == "Tanzania" & Crop == "soybean" ~ coalesce(`group_measure/repeat/plot_id`, paste0("TZ202402SOY", `group_measure/repeat/plot_number`)),
#       Country == "Tanzania" & Crop == "cowpea" ~ coalesce(`group_measure/repeat/plot_id`, paste0("TZ202402CWP", `group_measure/repeat/plot_number`)),
#       Country == "Nigeria" & Crop == "common_bean" ~ coalesce(`group_measure/repeat/plot_id`, paste0("NG202402BEA", `group_measure/repeat/plot_number`)),
#       Country == "Nigeria" & Crop == "soybean" ~ coalesce(`group_measure/repeat/plot_id`, paste0("NG202402SOY", `group_measure/repeat/plot_number`)),
#       Country == "Nigeria" & Crop == "cowpea" ~ coalesce(`group_measure/repeat/plot_id`, paste0("NG202402CWP", `group_measure/repeat/plot_number`)),
#       TRUE ~ `group_measure/repeat/plot_id`  # Keep original plot_id if no condition matches
#     )
#   )%>%
#   mutate(Event = strsplit(as.character(Event), " ")) %>%
#   unnest(Event) %>%
#   mutate(
#     today = as.IDate(today),
#     ENID = str_to_title(str_trim(`group_start/enumerator_ID_1`)),
#     HHID = plot_id,
#     Event = paste0("event", Event),
#     latitude= -6,
#     longitude= 37,
#     #`Site Selection` = as.IDate(today)
#   )%>%
#   arrange(ENID,HHID, desc(today)) %>% #sort to Keep last entry by date in duplicated records
#   #distinct(ENID,HHID,Event, .keep_all = TRUE)  %>%
#   mutate(Stage = "Research") %>%
#   mutate(Trial = "NOT") %>%
#   mutate(Country = capitalize(Country))
# 
# BS.NOT2_leg <- BS.NOT1_leg %>%
#   mutate(value_to_pivot = case_when(
#     Event == "event1" ~ {
#       # List of plant height columns
#       plant_height_columns <- c(
#         "group_measure/repeat/group_height/plant_height_cm_1",
#         "group_measure/repeat/group_height/plant_height_cm_2",
#         "group_measure/repeat/group_height/plant_height_cm_3",
#         "group_measure/repeat/group_height/plant_height_cm_4",
#         "group_measure/repeat/group_height/plant_height_cm_5",
#         "group_measure/repeat/group_height/plant_height_cm_6",
#         "group_measure/repeat/group_height/plant_height_cm_7",
#         "group_measure/repeat/group_height/plant_height_cm_8",
#         "group_measure/repeat/group_height/plant_height_cm_9",
#         "group_measure/repeat/group_height/plant_height_cm_10",
#         "group_measure/repeat/group_height/plant_height_cm_11",
#         "group_measure/repeat/group_height/plant_height_cm_12",
#         "group_measure/repeat/group_height/plant_height_cm_13",
#         "group_measure/repeat/group_height/plant_height_cm_14",
#         "group_measure/repeat/group_height/plant_height_cm_15"
#       )
#       # Select only the existing columns
#       existing_columns <- plant_height_columns[plant_height_columns %in% colnames(BS.NOT1_leg)]
#       # Calculate the mean if any columns exist
#       if (length(existing_columns) > 0) {
#         as.character(round(rowMeans(select(., all_of(existing_columns)), na.rm = TRUE), 1))
#       } else {
#         NA_character_
#       }
#     },
# 
#     Event == "event2" ~ {
#       # List of diameter columns
#       diameter_columns <- c(
#         "group_measure/repeat/group_diameter/plant_diameter_cm_1",
#         "group_measure/repeat/group_diameter/plant_diameter_cm_2",
#         "group_measure/repeat/group_diameter/plant_diameter_cm_3",
#         "group_measure/repeat/group_diameter/plant_diameter_cm_4",
#         "group_measure/repeat/group_diameter/plant_diameter_cm_5"
#       )
#       # Select only the existing columns
#       existing_columns <- diameter_columns[diameter_columns %in% colnames(BS.NOT1_leg)]
#       # Calculate the mean if columns exist
#       if (length(existing_columns) > 0) {
#         as.character(round(rowMeans(select(., all_of(existing_columns)), na.rm = TRUE), 1))
#       } else {
#         NA_character_
#       }
#     },
# 
#     Event == "event3" ~ if ("group_measure/repeat/leaf_chlorophyll_SPAD" %in% colnames(BS.NOT1_leg)) {
#       as.character(`group_measure/repeat/leaf_chlorophyll_SPAD`)
#     } else {
#       NA_character_
#     },
# 
#     Event == "event4" ~ if ("group_measure/repeat/soil/soil_sample_date" %in% colnames(BS.NOT1_leg)) {
#       as.character(`group_measure/repeat/soil/soil_sample_date`)
#     } else {
#       NA_character_
#     },
# 
#     Event == "event5" ~ if ("microbio_sample_date" %in% colnames(BS.NOT1_leg)) {
#       as.character(`microbio_sample_date`)
#     } else {
#       NA_character_
#     },
# 
#     Event == "event6" ~ if ("group_measure/repeat/group_plot/plant_density_plot" %in% colnames(BS.NOT1_leg)) {
#       as.character(`group_measure/repeat/group_plot/plant_density_plot`)
#     } else {
#       NA_character_
#     },
# 
#     Event == "event7" ~ if ("group_measure/repeat/group_harvest/harvest_date" %in% colnames(BS.NOT1_leg)) {
#       as.character(`group_measure/repeat/group_harvest/harvest_date`)
#     } else {
#       NA_character_
#     },
# 
#     Event == "event8" ~ if ("group_measure/repeat/group_sample/plant_sample_date" %in% colnames(BS.NOT1_leg)) {
#       as.character(`group_measure/repeat/group_sample/plant_sample_date`)
#     } else {
#       NA_character_
#     },
# 
#     Event == "event9" ~ if ("group_measure/repeat/group_pest/abiotic_stress" %in% colnames(BS.NOT1_leg)) {
#       as.character(`group_measure/repeat/group_pest/abiotic_stress`)
#     } else {
#       NA_character_
#     },
# 
#     Event == "event11" ~ if ("group_measure/repeat/group_plot/flowering_date" %in% colnames(BS.NOT1_leg)) {
#       as.character(`group_measure/repeat/group_plot/flowering_date`)
#     } else {
#       NA_character_
#     },
# 
#     Event == "event26" ~ if ("group_measure/repeat/unforseen_event" %in% colnames(BS.NOT1_leg)) {
#       as.character(`group_measure/repeat/unforseen_event`)
#     } else {
#       NA_character_
#     },
# 
#     Event == "event31" ~ if ("group_measure/repeat/group_pest/pest_number" %in% colnames(BS.NOT1_leg)) {
#       as.character(`group_measure/repeat/group_pest/pest_number`)
#     } else {
#       NA_character_
#     },
# 
#     TRUE ~ NA_character_
#   )) %>%
#   arrange(Event) %>%
#   pivot_wider(names_from = Event, values_from = value_to_pivot, values_fn = last) %>%
#   dplyr::select(any_of(c("today", "Event", "Crop", "Stage", "Trial", "ENID", "HHID")), starts_with("event")) %>%
#   arrange(ENID, HHID) %>%
#   suppressWarnings()
# 
# event_columns_leg <- grep("^event", names(BS.NOT2_leg), value = TRUE)
# BS.NOT2_leg_agg <- BS.NOT2_leg %>%
#   group_by(HHID, Crop, Stage, Trial) %>%
#   reframe(
#     today = first(today), 
#     ENID = list(unique(ENID)),  
#     across(
#       all_of(event_columns_leg),
#       ~ ifelse(length(na.omit(.)) > 0, list(na.omit(.)), NA),
#       .names = "{.col}"
#     )
#   )
# 
# ##yam
# # BS.NOTData_yam1<-BS.NOTData_yamS2 %>%
# #   tidyr::unnest(`group_measure/repeat`)
# #
# # BS.NOT1_yam<-BS.NOTData_yam1%>%
# #   as.data.frame()%>%
# #   select(-any_of(c( "_notes" , "_total_media", "_id", "_tags", "_uuid" ,"start", "_edited","_status" ,"_version" , "_duration"  ,"_xform_id" ,"_attachments", "_geolocation" ,"_media_count" ,"formhub/uuid"   ,
# #                     "_submitted_by","consent/photo","_date_modified","meta/instanceID"  ,"_submission_time", "_xform_id_string" ,"_bamboo_dataset_id"  ,
# #                     "_media_all_received"  ,  "consent/read_consent_form"    ,"consent/copy",  "consent/give_consent")))%>%
# #   rename(
# #     Country = `group_start/country`,
# #     Event= `group_start/event`,
# #     today = `group_measure/repeat/date`
# #
# #   ) %>%
# #   mutate(
# #     today = as.IDate(today),
# #     ENID = `group_start/enumerator_ID_1`,
# #     HHID = `group_measure/repeat/plot_number`,
# #     Crop = `group_start/crop`,
# #     Event = paste0("event", Event),
# #     latitude= -6,
# #     longitude= 37,
# #     `Site Selection` = as.IDate(today)
# #   )%>%
# #   arrange(ENID,HHID, desc(today)) %>% #sort to Keep last entry by date in duplicated records
# #   #distinct(ENID,HHID,Event, .keep_all = TRUE)  %>%
# #   mutate(Stage = "Research") %>%
# #   mutate(Trial = "NOT") %>%
# #   mutate(Country = capitalize(Country))
# #
# #
# # BS.NOT2_yam <- BS.NOT1_yam %>%
# #   dplyr::select(any_of(c("today", "Event",  "Crop", "Stage", "Trial", "ENID", "HHID"))) %>%
# #   arrange(Event) %>%
# #   pivot_wider(names_from = Event, values_from = today, values_fn = last) %>%
# #   mutate(across(starts_with("event"), as.Date, format = "%Y-%m-%d")) %>%
# #   arrange( ENID, HHID)%>%
# #   suppressWarnings()
# 
# BS.NOT1 <- dplyr::bind_rows(BS.NOT1_ban,BS.NOT1_cas,BS.NOT1_leg)
# BS.NOT2 <- dplyr::bind_rows(BS.NOT2_ban_agg,BS.NOT2_cas_agg,BS.NOT2_leg_agg)
# 
# BS.NOT2 <- flatten_list_columns(BS.NOT2)
# 
# 
# #via aws storage
# # temp_file <- tempfile()
# # write.csv(BS.NOT1, temp_file, row.names = FALSE)
# # aws.s3::put_object(file = temp_file,
# #                    bucket = "rtbglr",
# #                    object = paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "BSOdata.csv"))
# # unlink(temp_file)
# # 
# # temp_file <- tempfile()
# # write.csv(BS.NOT2, temp_file, row.names = FALSE)
# # aws.s3::put_object(file = temp_file,
# #                    bucket = "rtbglr",
# #                    object = paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "BSSUMdata.csv"))
# # unlink(temp_file)
# 
# 
# # Flatten BS.NOT1 and upload via shared helper
# BS.NOT1 <- flatten_list_columns(BS.NOT1)
# 
# upload_to_azure(BS.NOT1, "BSOdata.csv", cont)
# upload_to_azure(BS.NOT2, "BSSUMdata.csv", cont)
