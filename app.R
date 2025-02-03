# Load necessary packages
packages <- c("shiny", "shinyauthr", "shinydashboard", "tidyr", "ggplot2", "sf", "lubridate", 
              "stringr", "plotly", "shinyBS", "shinyjs", "leaflet", "shinyalert", "magrittr", 
              "shinycssloaders", "reactable", "tippy", "shinyWidgets", "auth0", "data.table", 
              "dplyr", "shinydashboardPlus", "shinythemes", "tools", "rmarkdown", "aws.s3", "DT", 
              "gganimate", "promises","future","parallel")

# Install missing packages
new_packages <- packages[!(packages %in% installed.packages()[, "Package"])]
if(length(new_packages)) install.packages(new_packages, repos = 'http://cran.us.r-project.org')

# Load all packages with suppressMessages and suppressWarnings
invisible(lapply(packages, function(pkg) {
  suppressMessages(suppressWarnings(library(pkg, character.only = TRUE)))
}))

# load functions+files
source('support_fun.R')

#### Define UI for application 
ui <- fluidPage(
  shinyjs::useShinyjs(),
  tags$head(
    tags$script(HTML("setTimeout(function() { history.pushState({}, 'Page Title', '/'); }, 2000);"))
  ),
  extendShinyjs(text = jscode, functions = "hrefAuto"),
  uiOutput("conditionalBox"),
  uiOutput("sidebarpanel", padding = 0)
)

#### Define server logic ----------------------
server <- function(input, output, session) {

  keep_alive <- shiny::reactiveTimer(intervalMs = 10000, session = shiny::getDefaultReactiveDomain())
  shiny::observe({keep_alive()})
  
  user_use_case_data <- names(session$userData$auth0_info$eia_apps)

  # Ensure "DEMO" is listed first, if available
  user_use_case_data <- if ("DEMO" %in% user_use_case_data) {
    c("DEMO", user_use_case_data[user_use_case_data != "DEMO"])
  } else {
    user_use_case_data
  }
  
  
  if ("ex-Wcover-Ghana" %in% user_use_case_data) {
    if (!("GH-CerLeg-Esoko" %in% user_use_case_data)) {
      user_use_case_data[user_use_case_data == "ex-Wcover-Ghana"] <- "GH-CerLeg-Esoko"
    }
    
  }
  
  
  # Render UI for conditional box (if no usecase data)
  output$conditionalBox <- renderUI({
    if (is.null(user_use_case_data) || length(user_use_case_data) == 0) {
      tags$div(
        style = "display: flex; justify-content: center; align-items: center; height: 100vh;",
        tags$div(
          class = "alert alert-warning",
          style = "background-color: #fdb415; color: #000; border-radius: 10px; padding: 20px; box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);",
          tags$strong(icon("exclamation-triangle"), " Warning!"),
          tags$p("No usecase data available for this user. Please contact Eduardo Garcia (IITA) at e.bendito@cgiar.org.", style = "margin: 10px 0;")
        )
      )
    } else {
      NULL
    }
  })
  
  ## Define UI render function ----------------------
  # List of active use cases
  active_use_case_list <- c("DEMO", "Mercy-Corps-SPROUT", "Solidaridad-Soy-Advisory", 
                            "GH-CerLeg-Esoko", "ex-Wcover-Ghana", "KALRO", "SNS-RWANDA", "BioSSA")
  
  # Sidebar rendering logic
  output$sidebarpanel <- renderUI({
    # Filter user use case data based on active use cases
    user_use_case_data <- user_use_case_data[user_use_case_data %in% active_use_case_list]
    
    # Header and Navbar Setup
    navbarPage(
      theme = shinytheme("flatly"),
      title = tags$div(
        img(src = "Logo/EiA_logo3.png", height = '50vh'),
        HTML("&nbsp;&nbsp;&nbsp;"), "Data Collection Dashboard"
      ),
      id = "nav",
      windowTitle = "DC Dashboard",
      collapsible = FALSE,
      tags$head(includeCSS("style.css")),
      create_navbarMenu(user_use_case_data)
    )
  })

  
  ##########################################################################################################################################
  #################################################### SERVER FUNCTIONS ####################################################################
  ##########################################################################################################################################
  # Set future to support multi-threading
  plan(multicore)
  
  observeEvent(input$logout, {
    auth0::logoutButton() # Log the user out
  })
  

  valuesapp <- reactiveValues(datacrop = NULL, rawdata = NULL, patternissues= NULL,patternissuesE= NULL,
                              datacrop0 = NULL,datacrop00 = NULL)
  ##Define data for each usecase   
  observeEvent(input$nav, {
    gc()
    
    tryCatch({
      # Define file names and patterns for different use cases
      usecase_files <- list(
        "SNS-RWANDA" = list("datacrop" = "SNSRwandaSUMdata.csv", "rawdata" = "SNSRwandaOdata.csv", "patternissues" = "^RSENRW", "patternissuesE" = "^RSHHRW"),
        "Solidaridad-Soy-Advisory" = list("datacrop" = "SolidaridadSUMdata.csv", "rawdata" = "SolidaridadOdata.csv", "patternissues" = "^SDENMW|SDENZM|SDENMZ", "patternissuesE" = "^SDHHMW|SDHHZM|SDHHMZ|SDRP"),
        "KALRO" = list("datacrop" = "KLSUMdata.csv", "rawdata" = "KLOdata.csv", "patternissues" = "", "patternissuesE" = ""),
        "Mercy-Corps-SPROUT" = list("datacrop" = "MCSUMdata.csv", "rawdata" = "MCOdata.csv", "patternissues" = "", "patternissuesE" = ""),
        "GH-CerLeg-Esoko" = list("datacrop" = "CESUMdata.csv", "rawdata" = "CEOdata.csv", "patternissues" = "", "patternissuesE" = ""),
        "DEMO" = list("datacrop" = "DEMOSUMdata.csv", "rawdata" = "DEMOOdata.csv", "patternissues" = "", "patternissuesE" = ""),
        "BioSSA" = list("datacrop" = "BSSUMdata.csv", "rawdata" = "BSOdata.csv", "patternissues" = "", "patternissuesE" = "")
      )
      
      # Default empty case
      datacrop <- data.frame()
      rawdata <- data.frame()
      columns_to_append <- c()
      patternissues <- ""
      patternissuesE <- ""
      
      # Reset the valuesapp reactiveValues to NULL at the start of each tab change
      valuesapp$datacrop <- NULL
      valuesapp$rawdata <- NULL
      valuesapp$patternissues <- NULL
      valuesapp$patternissuesE <- NULL
      
      
      # Load data for the selected use case in parallel
      if (input$nav %in% names(usecase_files)) {
        case_data <- usecase_files[[input$nav]]
        
        # Use future to load data in parallel
        datacrop_future <- load_data_from_s3(case_data$datacrop)
        rawdata_future <- load_data_from_s3(case_data$rawdata)
        
        # Collect results using `value()` 
        valuesapp$datacrop <- value(datacrop_future)
        valuesapp$rawdata <- value(rawdata_future)
        valuesapp$patternissues <- case_data$patternissues
        valuesapp$patternissuesE <- case_data$patternissuesE
        
      }

    }, error = function(e) NULL)
    
    

    datacrop<-valuesapp$datacrop
    rawdata<-valuesapp$rawdata
    patternissues<-valuesapp$patternissues
    patternissuesE<-valuesapp$patternissuesE
    
    # Initialize UI inputs dynamically for each use case
    selectInput_ids <- list()
    selectInput_values <- list()
    
    dynamic_label <- reactive({
      if (input$nav == "BioSSA") {
        return("Plot Number")
      } else {
        return("Household")
      }
    })
      
    #parallel::mclapply(names(usecases.index), function(k) {
      #i <- usecases.index[names(usecases.index[ k ])]
    i <- usecases.index[input$nav]
      
      # Initialize outputs
      output[[paste0("trials_map_", i)]] <- renderLeaflet({ NULL })
      output[[paste0("submission_trend_", i)]] <- renderPlotly({ NULL })
      output[[paste0("tabledownload_", i)]] <- DT::renderDT({ NULL })
      output[[paste0("tableR_", i)]] <- renderReactable({ NULL })
      output[[paste0("ranking_", i)]] <- renderReactable({ NULL })
      output[[paste0("rankingevents_", i)]] <- renderReactable({ NULL })
      output[[paste0("issues_", i)]] <- renderReactable({ NULL })
      
      # Dynamically create UI elements
      selectInput_ids <- c(selectInput_ids, list(
        stage = paste0("stagefinder_", i),
        experiment = paste0("experimentfinder_", i),
        season = paste0("seasonfinder_", i),
        date = paste0("datefinder_", i),
        enumerator = paste0("enumeratorfinder_", i),
        region = paste0("regionfinder_", i),
        household = paste0("householdfinder_", i)
      ))
      
      # Stage input UI
      output[[paste0("stagefinderr_", i)]] <- renderUI({
        selectInput(paste0("stagefinder_", i), label = "Stage", multiple = FALSE, choices = c('Research', 'Validation', 'Piloting'), selected = sort(unique(datacrop$Stage))[1])
      })
      
      # Experiment input UI
      output[[paste0("experimentfinderr_", i)]] <- renderUI({
        if (!is.null(input[[paste0("stagefinder_", i)]])) {
          stage_choice <- input[[paste0("stagefinder_", i)]]
          experiment_choices <- switch(stage_choice,
                                       'Research' = c('NOT', 'Variety Selection', 'Planting Date'),
                                       'Validation' = c('Fertilizer Recommendation', 'Variety Selection', 'Planting Date', 'Intercropping'),
                                       'Piloting' = c('Fertilizer Recommendation', 'Variety Selection', 'Planting Date')
          )
          selectInput(paste0("experimentfinder_", i), label = "Experiment", multiple = FALSE, choices = experiment_choices, selected = sort(unique(datacrop$Trial))[1])
        } else {
          selectInput(paste0("experimentfinder_", i), label = "Experiment", multiple = FALSE, choices = NULL, selected = NULL)
        }
      })
      
      # Crop input UI
      output[[paste0("cropfinderr_", i)]] <- renderUI({
        selectInput(paste0("cropfinder_", i), label = "Crop", multiple = TRUE, choices = sort(unique(datacrop$Crop)), selected = sort(unique(datacrop$Crop))[1])
      })
      
      # Date input UI
      output[[paste0("datefinderr_", i)]] <- renderUI({
        dateRangeInput(paste0("datefinder_", i), "Date", start = min(na.omit(rawdata$today)), end = Sys.time())
      })
      
      # Enumerator input UI
      output[[paste0("enumeratorfinderr_", i)]] <- renderUI({
        selectInput(paste0("enumeratorfinder_", i), label = "Enumerator", multiple = TRUE, choices = c("All", sort(unique(datacrop$ENID))), selected = "All")
      })
      
      # Region input UI (example; fill with your logic)
      output[[paste0("regionfinderr_", i)]] <- renderUI({
        selectInput(paste0("regionfinder_", i), label = "Country", multiple = FALSE, choices = c()) # Fill in region choices dynamically
      })
      
      # Household input UI
      output[[paste0("householdfinderr_", i)]] <- renderUI({
        selectInput(paste0("householdfinder_", i), label = dynamic_label(), multiple = TRUE, choices = c("All", sort(unique(na.omit(datacrop$HHID)))), selected = "All")
      })
      
      # Total submissions infoBox
      output[[paste0("Totsub_box_", i)]] <- renderUI({
        infoBox("Total submissions", paste0(nrow(rawdata)), icon = icon("list"), color = "olive", width = "100%")
      })
      
      # Country infoBox
      output[[paste0("country_", i)]] <- renderUI({
        infoBox("Country", HTML(paste(unique(na.omit(rawdata$Country)), collapse = ", ")), icon = icon("globe"), color = "olive", width = "100%")
      })
      
      # Project infoBox
      output[[paste0("project_", i)]] <- renderUI({
        infoBox("Usecase", as.character(input$nav), icon = icon("barcode"), color = "olive", width = "100%")
      })
    #})
       

    
    observe({
      input_nav <- input$nav
   
      # parallel::mclapply(names(usecases.index), function(k) {
      #   i <- usecases.index[names(usecases.index[ k ])]
        
        # Collect input values for each use case
        experimentUsecase <- input[[paste0("experimentfinder_", i)]]
        stageUsecase <- input[[paste0("stagefinder_", i)]]
        cropUsecase <- input[[paste0("cropfinder_", i)]]
        dateUsecase <- input[[paste0("datefinder_", i)]]
        enumeratorUsecase <- input[[paste0("enumeratorfinder_", i)]]
        householdUsecase <- input[[paste0("householdfinder_", i)]]
        
        # Special data handling for specific use cases
        if (input_nav == "Solidaridad-Soy-Advisory" && "Research" %in% stageUsecase) {
          rawdata_future <- load_data_from_s3("SolidaridadNOTdata.csv")
          valuesapp$rawdata <- value(rawdata_future)
        }else if (input_nav == "GH-CerLeg-Esoko" && "Intercropping" %in% experimentUsecase) {
          datacrop_future <- load_data_from_s3("CEICSUMdata.csv")
          rawdata_future <- load_data_from_s3("CEICOdata.csv")
          valuesapp$datacrop <- value(datacrop_future)
          valuesapp$rawdata <- value(rawdata_future)
        }
        
        
        
        # Create a reactive expression
        reactive_expr <- reactive({
          req(input_nav, experimentUsecase, stageUsecase, cropUsecase, dateUsecase, enumeratorUsecase, householdUsecase)
        }) %>% bindCache(input_nav, experimentUsecase, stageUsecase, cropUsecase, dateUsecase, enumeratorUsecase, householdUsecase)
        
        observeEvent(reactive_expr(), {
          datacrop<-valuesapp$datacrop
          rawdata<-valuesapp$rawdata
          patternissues<-valuesapp$patternissues
          patternissuesE<-valuesapp$patternissuesE
          
          event_columns <- grep("^event", colnames(datacrop), value = TRUE)
          event_columns <- event_columns[order(as.numeric(gsub("[^0-9]", "", event_columns)))]
          dynamic_event_columns <- reactive({
            if (input$nav == "BioSSA") {
              return(c("ENID", "HHID", "Trial",event_columns))
            } else {
              return(c("ENID", "HHID", "Trial","Site Selection",event_columns))
            }
          })
          columns_to_append <-dynamic_event_columns()
          
          # apply filters
          tryCatch(
            if (stageUsecase %in% stageUsecase ){
              datacrop<-datacrop[datacrop$Stage %in% stageUsecase, ]
              datacropOO<-rawdata[rawdata$Stage %in% stageUsecase, ]
            }
            ,error = function(e) NULL)
          
          tryCatch(
            if (experimentUsecase %in% experimentUsecase){
              datacrop<-datacrop[datacrop$Trial %in% experimentUsecase, ]
              datacropOO<-datacropOO[datacropOO$Trial %in% experimentUsecase, ]
            }
            ,error = function(e) NULL)
          
          
          output[[paste0("Totsub_box_",i)]] <-renderUI({
            infoBox(
              "Total submissions",paste0(nrow(datacropOO)), icon = icon("list"),
              color = "olive", width = "100%"       )
          })
          
          output[[paste0("country_", i)]] <- renderUI({
            unique_countries <- unique(na.omit(datacropOO$Country))
            infoBox(
              "Country", HTML(paste(unique_countries, collapse = ", ")), icon = icon("globe"),
              color = "olive", width = "100%"       
            )
          })
          
          tryCatch(
            if ("All" %in% cropUsecase){
              datacrop<-datacrop
              datacropO<-datacropOO
            }else {
              datacrop<-datacrop[datacrop$Crop %in% cropUsecase, ]
              datacropO<-datacropOO[datacropOO$Crop %in% cropUsecase, ]
            }
            ,error = function(e) NULL)
          
          tryCatch(
            if ("All" %in% enumeratorUsecase ){
              datacrop<-datacrop
              datacropO<-datacropO
            }else {
              datacrop<-datacrop[datacrop$ENID %in% enumeratorUsecase, ]
              datacropO<-datacropO[datacropO$ENID %in% enumeratorUsecase, ]
              
            }
           ,error = function(e) NULL)
          
          tryCatch(
            if ("All" %in% householdUsecase){
              datacrop<-datacrop
              datacropO<-datacropO
            }else{
              datacrop<-datacrop[which(datacrop$HHID %in%  householdUsecase), ]
              datacropO<-datacropO[datacropO$HHID %in% householdUsecase, ]
              
            }
            ,error = function(e) NULL)
          
          tryCatch(
            datacropO <- datacropO[which(datacropO$today >= dateUsecase[1] & datacropO$today <= dateUsecase[2]), ]
            ,error = function(e) NULL)
          
          
          dateleo<-format(Sys.time(), "%Y-%m-%d")
          datestart<-min(na.omit(rawdata$today))
          tryCatch(
            if (dateUsecase[1] == datestart && dateUsecase[2] == dateleo ){
              datacrop <- datacrop
            }else{
              datacrop <- datacrop[datacrop$ENID %in% datacropO$ENID, ]
            }
            ,error = function(e) NULL)
          
          
          tryCatch(
            if (dateUsecase[1] == datestart && dateUsecase[2] == dateleo ){
              datacrop <- datacrop
            }else{
              datacrop <- datacrop[datacrop$HHID %in% datacropO$HHID, ]
            }
            ,error = function(e) NULL)
          
          
          
          #Summary map
          output[[paste0("trials_map_",i)]] <-renderLeaflet({
            leaflet() %>%
              addProviderTiles(providers$CartoDB.Positron) %>%
              addCircles(data = datacropO ,lng = as.numeric(datacropO$longitude), lat = as.numeric(datacropO$latitude),color = "#fdb415") %>%suppressWarnings()
            #fitBounds(max(as.numeric(datacrop$`intro/longitude`)), max(as.numeric(datacrop$`intro/latitude`)),min(as.numeric(datacrop$`intro/longitude`)), min(as.numeric(datacrop$`intro/latitude`)))
          })
          
          ##Summary_submissions trend
          wgroup <-
            tryCatch( 
            datacropO %>%
              mutate(date = as.Date(today)) %>%
              select(date) %>%
              group_by(date) %>%
              count() %>%
              #rename(total_freq = n) %>%
              mutate(date = as.Date(date))
            ,error = function(e) NULL)
          
          
          Ir<-ggplot(wgroup, aes(x=date, y= n, group=1)) +
            geom_line(color="#fdb415")+
            geom_point(color="#fdb415")+
            #scale_x_discrete(labels= paste("Week", c(1:length(ff))))+
            theme_bw(base_size = 24)+
            labs(title="", x="Month", y="Submissions Count")+scale_x_date(date_breaks = "1 month", date_minor_breaks = "1 week", date_labels = "%m-%Y")+them2

          # #plotly -interactive ouput
          output[[paste0("submission_trend_",i)]] <-renderPlotly({
            tryCatch(
              ggplotly(Ir)
              ,error = function(e) NULL)
          })
          
          
          ##Enumerator Ranking
          datacroptableF <- future({
            datacroptable<-datacrop 
            
            # Columns to append
            datacroptable<-as.data.frame(datacroptable)
            
            
            # columns_to_append <- c("ENID", "HHID", "Trial",#"treat",
            #                        "Site Selection",event_columns)
            
            # # Check if columns exist in the dataframe
            missing_columns <- setdiff(columns_to_append, colnames(datacroptable))
            #missing_columns2 <- setdiff(columns_to_append, colnames(datacroptablev))
            
            # 
            # # Append missing columns only
            tryCatch(  
              if (length(missing_columns) > 0) {
              datacroptable[, missing_columns] <- NA
            } 
            ,error = function(e) NULL)
            
            datacroptable<-  
              tryCatch( 
                datacroptable %>%
                  select(any_of(columns_to_append ))
                ,error = function(e) NULL)
            
            colnames(datacroptable) <- toTitleCase(colnames(datacroptable)) #Title case for table headers
            return(datacroptable)
          })
          
          datacroptable<-value(datacroptableF)
          
          
          ranksEVF <- future({
            tryCatch({
              # Summarize the number of submissions per event (excluding ENID, HHID, and Trial columns)
              datacroptable %>%
                select(-any_of(c("ENID", "HHID", "Trial"))) %>%
                summarise(across(.fns = ~sum(!is.na(.)))) %>%
                suppressWarnings()  
            }, error = function(e) NULL)
          })
            
          ranksF <- future({
            tryCatch({
              datacroptable %>%
                select(-any_of(c("HHID", "Trial"))) %>%
                group_by(ENID) %>%
                summarise(across(.fns = ~sum(!is.na(.)))) %>%
                suppressWarnings()  # Suppress warnings during summarization
            }, error = function(e) NULL)
          })
          
          ranks.events<-value(ranksEVF)
          ranks<-value(ranksF)
          
          output[[paste0("rankingevents_",i)]]  <- renderReactable({
            reactable(ranks.events,
                      pagination = FALSE,
                      showPagination = TRUE,
                      paginateSubRows = FALSE,
                      
            )
            
          }) %>%
            bindCache(ranks.events)
          
          output[[paste0("ranking_",i)]]  <- renderReactable({
            reactable(ranks,
                      pagination = FALSE,
                      showPagination = TRUE,
                      paginateSubRows = FALSE,
                      columns = list(
                        ENID = colDef(
                          html = TRUE,
                          show = TRUE,
                          cell =    function(value,index) {
                            s2<-datacrop[which(datacrop$ENID==value ), ]
                            tippy(value,tooltip = paste("NAME:", unique(s2$ENfirstName) , unique(s2$ENSurname), "<br>", "CONTACT:", unique(s2$ENphoneNo)))
                          },
                        )
                      )
            )
          })%>%
            bindCache(ranks)
          
          
          
          ################ISSUES TABLE ################################
              # Create a future for background processing
          datacropissuesF <- future({
            
            # Copying the data for processing
            datacropI <- datacroptable 
            
            # Select relevant columns for further processing
            datacropissues <- datacropI %>%
              dplyr::select(any_of(c("ENID", "HHID")))
            
            # Define event condition function
            event_conditions <- function(row) {
              for (i in 3:length(row)) { # Start from the "event1" column index
                if (is.na(row[i-1]) && !is.na(row[i])) {
                  return(TRUE)
                } else if (!is.na(row[i-1]) && !is.na(row[i])) {
                  break
                }
              }
              return(FALSE)
            }
            
            # Try to process datacropissuesA
            datacropissuesA <- 
              tryCatch({
              datacropissues %>%
                filter(!grepl(patternissues, ENID)) %>%
                mutate(Issues = ifelse(!grepl(patternissues, ENID), "Check ENID", NA)) %>%
                mutate(Issues = as.character(Issues))
            }, error = function(e) NULL)
            
            # Try to process datacropissuesB
            datacropissuesB <- 
              tryCatch({
              datacropissues %>%
                filter(!grepl(patternissuesE, HHID)) %>%
                mutate(Issues = ifelse(!grepl(patternissuesE, HHID), "Check HHID", NA)) %>%
                mutate(Issues = as.character(Issues))
            }, error = function(e) NULL)
            
            # Try to process datacropissuesC
            datacropissuesC <- 
              tryCatch({
              datacropI %>%
                filter(apply(datacropI[, 3:ncol(datacropI)], 1, event_conditions)) %>%
                dplyr::select(any_of(c("ENID", "HHID"))) %>%
                mutate(Issues = "Check submission events")
            }, error = function(e) NULL)
            
            # Combine all data issues into one dataframe
            datacropissues <- bind_rows(datacropissuesA, datacropissuesB, datacropissuesC)
            datacropissues <- as.data.frame(datacropissues)  # Ensure it is a data frame
            
            return(datacropissues)
          })
          datacropissuesP<-value(datacropissuesF)
          
          output[[paste0("issues_",i)]]  <- renderReactable({
            reactable(datacropissuesP,
                      pagination = FALSE,
                      showPagination = TRUE,
                      paginateSubRows = FALSE,
                      columns = list(
                        HHID = colDef(
                          name = dynamic_label()
                        )
                      )
            )
          }) %>%
            bindCache(datacropissuesP)
          
          
          dynamic_color<-reactive({
            if ("Site Selection" %in% colnames(datacroptable)) {
              target_dates <- as.Date(datacroptable$`Site Selection`, format = "%Y-%m-%d") + 14
              if (is.na(target_dates)&& is.na(value) ) {
                color <-"#BE93D4"
              }else if (!is.na(target_dates)&& is.na(value) && current_date >= target_dates){
                color <-"#c3531f"
              }else if (!is.na(target_dates)&& is.na(value) && current_date <= target_dates){
                color <-"#fdb415"
              } else if (!is.na(target_dates)&& !is.na(value) ) {
                color <-"#55b047"
              }else {
                color <-"#c3531f"
              }
            }
            return(color)
          })
          
          
          
          ## Enumerator Tracker Table
          output[[paste0("tableR_", i)]] <- renderReactable({
            if (input_nav == "BioSSA"){
              datacroptable<-datacroptable %>%
                rename(PID=HHID)
            }
            reactable(datacroptable,
                      pagination = FALSE,
                      showPagination = TRUE,
                      paginateSubRows = FALSE,
                      defaultExpanded = TRUE,
                      columns = list(
                        Crop = colDef(filterable = TRUE, style = list(background = "white")),
                        HHID = colDef(
                          html = TRUE,
                          show = TRUE,
                          name = dynamic_label(),
                          cell = function(value, index) {
                            s2 <- datacrop[datacrop$HHID == value, ]
                            tippy(value, tooltip = paste("NAME:", unique(s2$HHfirstName), unique(s2$HHSurname), "<br>", "CONTACT:", unique(s2$HHphoneNo)))
                          },
                          style = list(background = "white")
                        ),
                        `Site Selection` = colDef(
                          style = function(value) {
                            if (is.na(value)) {
                              return(list(background = "#c3531f"))
                            }
                            return(list(background = "#55b047"))
                          }
                        ),
                        Event0 = colDef(
                          
                          style  = function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d")  
                            target_dates <- as.Date(datacroptable$`Site Selection`[index], format = "%Y-%m-%d") + 14
                            
                            if (!"Site Selection" %in% colnames(datacroptable)) {
                              color <-"#fff"
                              list(background =color)
                            }else if (is.na(target_dates)&& is.na(value) ) {
                              color <-"#BE93D4"
                              list(background =color)
                            }else if (!is.na(target_dates)&& is.na(value) && current_date >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            }else if (!is.na(target_dates)&& is.na(value) && current_date <= target_dates){
                              color <-"#fdb415"
                              list(background =color)
                            } else if (!is.na(target_dates)&& !is.na(value) ) {
                              color <-"#55b047"
                              list(background =color)
                            } else if ("Site Selection" %in% colnames(datacroptable)) { 
                              color <-"#fff"
                              list(background =color)
                            }
                            
                          }
                          
                        ),
                        Event1 = colDef(
                          
                          style  = function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d")  
                            target_dates <- as.Date(datacroptable$`Site Selection`[index], format = "%Y-%m-%d") + 14
                            
                            if (!"Site Selection" %in% colnames(datacroptable)) {
                              color <-"#fff"
                              list(background =color)
                            }else if (is.na(target_dates) && is.na(value) ) {
                              color <-"#BE93D4"
                              list(background =color)
                            }else if (!is.na(target_dates)&& is.na(value) && current_date >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            }else if (!is.na(target_dates)&& is.na(value) && current_date <= target_dates){
                              color <-"#fdb415"
                              list(background =color)
                            } else if (!is.na(target_dates)&& !is.na(value) ) {
                              color <-"#55b047"
                              list(background =color)
                            }
                            
                          }
                        ),
                        Event1R = colDef(
                          style  = function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d")  
                            target_dates <- as.Date(datacroptable$`Site Selection`[index], format = "%Y-%m-%d") + 14
                            
                            if (!"Site Selection" %in% colnames(datacroptable)) {
                              color <-"#fff"
                              list(background =color)
                            }else if (is.na(target_dates)&& is.na(value) ) {
                              color <-"#BE93D4"
                              list(background =color)
                            }else if (!is.na(target_dates)&& is.na(value) && current_date >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            }else if (!is.na(target_dates)&& is.na(value) && current_date <= target_dates){
                              color <-"#fdb415"
                              list(background =color)
                            } else if (!is.na(target_dates)&& !is.na(value) ) {
                              color <-"#55b047"
                              list(background =color)
                            }else if ("Site Selection" %in% colnames(datacroptable)) { 
                              color <-"#fff"
                              list(background =color)
                            }
                            
                          }
                        ),
                        Event11 = colDef(
                          style  = function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d")  
                            target_dates <- as.Date(datacroptable$`Site Selection`[index], format = "%Y-%m-%d") + 14
                            
                            if (!"Site Selection" %in% colnames(datacroptable)) {
                              color <-"#fff"
                              list(background =color)
                            }else if (is.na(target_dates)&& is.na(value) ) {
                              color <-"#BE93D4"
                              list(background =color)
                            }else if (!is.na(target_dates)&& is.na(value) && current_date >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            }else if (!is.na(target_dates)&& is.na(value) && current_date <= target_dates){
                              color <-"#fdb415"
                              list(background =color)
                            } else if (!is.na(target_dates)&& !is.na(value) ) {
                              color <-"#55b047"
                              list(background =color)
                            }else if ("Site Selection" %in% colnames(datacroptable)) { 
                              color <-"#fff"
                              list(background =color)
                            }
                            
                          }
                        ),
                        Event2 = colDef(
                          style  =    function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d")  
                            target_dates <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 29
                            
                            if (!"Site Selection" %in% colnames(datacroptable)) {
                              color <-"#fff"
                              list(background =color)
                            }else if (!is.na(target_dates)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates) {
                              color <-"#55b047"
                              list(background =color)
                            } else if (!is.na(target_dates)&& !is.na(value) && as.Date(value , format = "%Y-%m-%d") >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            } else if(!is.na(target_dates)&&  is.na(value) && current_date <= target_dates){
                              color <-"#fdb415"
                              list(background =color)
                            }else if( !is.na(target_dates)&& is.na(value) && current_date >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            } else if (is.na(target_dates)&& is.na(value) ){
                              color <-"#BE93D4"
                              list(background =color)
                            } else {
                              color <-"#fff"
                              list(background =color)
                            }
                          }
                        ),
                        Event3 = colDef(
                          style  = function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d") 
                            target_dates <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 43
                            target_dates_prev <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 29
                            
                            if (!"Site Selection" %in% colnames(datacroptable)) {
                              color <-"#fff"
                              list(background =color)
                            }else if (!is.na(target_dates)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates) {
                              color <-"#55b047"
                              list(background =color)
                            } else if (!is.na(target_dates)&& !is.na(value) && as.Date(value , format = "%Y-%m-%d") >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            } else if(!is.na(target_dates)&&  is.na(value) && current_date <= target_dates && current_date >= target_dates_prev){
                              color <-"#fdb415"
                              list(background =color)
                            } else if(!is.na(target_dates)&&  is.na(value) && current_date <= target_dates && current_date <= target_dates_prev){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if( !is.na(target_dates)&& is.na(value) && current_date >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            } else if (is.na(target_dates)&& is.na(value) ){
                              color <-"#BE93D4"
                              list(background =color)
                            } else {
                              color <-"#fff"
                              list(background =color)
                            }
                          }
                        ),
                        Event4 = colDef(
                          style  = function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d")  
                            target_dates_potato <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 57
                            target_dates_rice <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 64
                            target_dates_prev <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 43
                            target_dates <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 64
                            
                            if (!"Site Selection" %in% colnames(datacroptable)) {
                              color <-"#fff"
                              list(background =color)
                            }else if (!is.na(target_dates)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates) {
                              color <-"#55b047"
                              list(background =color)
                            } else if (!is.na(target_dates)&& !is.na(value) && as.Date(value , format = "%Y-%m-%d") >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            } else if(!is.na(target_dates)&&  is.na(value) && current_date <= target_dates && current_date >= target_dates_prev){
                              color <-"#fdb415"
                              list(background =color)
                            } else if(!is.na(target_dates)&&  is.na(value) && current_date <= target_dates && current_date <= target_dates_prev){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if( !is.na(target_dates)&& is.na(value) && current_date >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            } else if (is.na(target_dates)&& is.na(value) ){
                              color <-"#BE93D4"
                              list(background =color)
                            } else if (datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates_potato) {
                              color <-"#55b047"
                              list(background =color)
                            }else if (datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates_rice) {
                              color <-"#55b047"
                              list(background =color)
                            } else if (datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&& !is.na(value) && as.Date(value , format = "%Y-%m-%d") >= target_dates_potato){
                              color <-"#c3531f"
                              list(background =color)
                            }else if (datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&& !is.na(value) && as.Date(value , format = "%Y-%m-%d") >= target_dates_rice){
                              color <-"#c3531f"
                              list(background =color)
                            }  else if( datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&&  is.na(value) && current_date <= target_dates_potato && current_date >= target_dates_prev){
                              color <-"#fdb415"
                              list(background =color)
                            }  else if( datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&&  is.na(value) && current_date <= target_dates_rice && current_date >= target_dates_prev){
                              color <-"#fdb415"
                              list(background =color)
                            }else if(datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&&  is.na(value) && current_date <= target_dates_potato && current_date <= target_dates_prev){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if(datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&&  is.na(value) && current_date <= target_dates_rice && current_date <= target_dates_prev){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if( datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&& is.na(value) && current_date >= target_dates_potato){
                              color <-"#c3531f"
                              list(background =color)
                            }else if( datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&& is.na(value) && current_date >= target_dates_rice){
                              color <-"#c3531f"
                              list(background =color)
                            } else if (is.na(target_dates_potato)&& is.na(value) ){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if (is.na(target_dates_rice)&& is.na(value) ){
                              color <-"#BE93D4"
                              list(background =color)
                            }else {
                              color <-"#fff"
                              list(background =color)
                            }
                          }
                        ), 
                        Event5 = colDef(
                          style  = function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d") 
                            target_dates_potato <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 71
                            target_dates_rice <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 78
                            target_dates_prev_potato <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 57
                            target_dates_prev_rice <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 64
                            target_dates_prev <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 64
                            target_dates <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 78
                            
                            if (!"Site Selection" %in% colnames(datacroptable)) {
                              color <-"#fff"
                              list(background =color)
                            }else if (!is.na(target_dates)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates) {
                              color <-"#55b047"
                              list(background =color)
                            } else if (!is.na(target_dates)&& !is.na(value) && as.Date(value , format = "%Y-%m-%d") >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            } else if(!is.na(target_dates)&&  is.na(value) && current_date <= target_dates && current_date >= target_dates_prev){
                              color <-"#fdb415"
                              list(background =color)
                            } else if(!is.na(target_dates)&&  is.na(value) && current_date <= target_dates && current_date <= target_dates_prev){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if( !is.na(target_dates)&& is.na(value) && current_date >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            } else if (is.na(target_dates)&& is.na(value) ){
                              color <-"#BE93D4"
                              list(background =color)
                            } else if (datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates_potato) {
                              color <-"#55b047"
                              list(background =color)
                            }else if (datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates_rice) {
                              color <-"#55b047"
                              list(background =color)
                            } else if (datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&& !is.na(value) && as.Date(value , format = "%Y-%m-%d") >= target_dates_potato){
                              color <-"#c3531f"
                              list(background =color)
                            }else if (datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&& !is.na(value) && as.Date(value , format = "%Y-%m-%d") >= target_dates_rice){
                              color <-"#c3531f"
                              list(background =color)
                            }  else if( datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&&  is.na(value) && current_date <= target_dates_potato && current_date >= target_dates_prev_potato){
                              color <-"#fdb415"
                              list(background =color)
                            }  else if( datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&&  is.na(value) && current_date <= target_dates_rice && current_date >= target_dates_prev_rice){
                              color <-"#fdb415"
                              list(background =color)
                            }else if(datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&&  is.na(value) && current_date <= target_dates_potato && current_date <= target_dates_prev_potato){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if(datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&&  is.na(value) && current_date <= target_dates_rice && current_date <= target_dates_prev_rice){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if( datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&& is.na(value) && current_date >= target_dates_potato){
                              color <-"#c3531f"
                              list(background =color)
                            }else if( datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&& is.na(value) && current_date >= target_dates_rice){
                              color <-"#c3531f"
                              list(background =color)
                            }else if (is.na(target_dates_potato)&& is.na(value) ){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if (is.na(target_dates_rice)&& is.na(value) ){
                              color <-"#BE93D4"
                              list(background =color)
                            }else {
                              color <-"#fff"
                              list(background =color)
                            }
                          }
                        ), 
                        Event6 = colDef(
                          style  = function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d")  
                            target_dates_potato <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 85
                            target_dates_rice <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 92
                            target_dates_prev_potato <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 71
                            target_dates_prev_rice <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 78
                            target_dates_prev <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 78
                            target_dates <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 92
                            
                            #print(!is.na(value) && current_date > target_dates)
                            if (!"Site Selection" %in% colnames(datacroptable)) {
                              color <-"#fff"
                              list(background =color)
                            }else if (!is.na(target_dates)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates) {
                              color <-"#55b047"
                              list(background =color)
                            } else if (!is.na(target_dates)&& !is.na(value) && as.Date(value , format = "%Y-%m-%d") >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            } else if(!is.na(target_dates)&&  is.na(value) && current_date <= target_dates && current_date >= target_dates_prev){
                              color <-"#fdb415"
                              list(background =color)
                            } else if(!is.na(target_dates)&&  is.na(value) && current_date <= target_dates && current_date <= target_dates_prev){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if( !is.na(target_dates)&& is.na(value) && current_date >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            } else if (is.na(target_dates)&& is.na(value) ){
                              color <-"#BE93D4"
                              list(background =color)
                            } else if (datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates_potato) {
                              color <-"#55b047"
                              list(background =color)
                            }else if (datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates_rice) {
                              color <-"#55b047"
                              list(background =color)
                            } else if (datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&& !is.na(value) && as.Date(value , format = "%Y-%m-%d") >= target_dates_potato){
                              color <-"#c3531f"
                              list(background =color)
                            }else if (datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&& !is.na(value) && as.Date(value , format = "%Y-%m-%d") >= target_dates_rice){
                              color <-"#c3531f"
                              list(background =color)
                            }  else if( datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&&  is.na(value) && current_date <= target_dates_potato && current_date >= target_dates_prev_potato){
                              color <-"#fdb415"
                              list(background =color)
                            }  else if( datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&&  is.na(value) && current_date <= target_dates_rice && current_date >= target_dates_prev_rice){
                              color <-"#fdb415"
                              list(background =color)
                            }else if(datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&&  is.na(value) && current_date <= target_dates_potato && current_date <= target_dates_prev_potato){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if(datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&&  is.na(value) && current_date <= target_dates_rice && current_date <= target_dates_prev_rice){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if( datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&& is.na(value) && current_date >= target_dates_potato){
                              color <-"#c3531f"
                              list(background =color)
                            }else if( datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&& is.na(value) && current_date >= target_dates_rice){
                              color <-"#c3531f"
                              list(background =color)
                            }else if (is.na(target_dates_potato)&& is.na(value) ){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if (is.na(target_dates_rice)&& is.na(value) ){
                              color <-"#BE93D4"
                              list(background =color)
                            }else {
                              color <-"#fff"
                              list(background =color)
                            }
                          }
                        ), 
                        Event7 = colDef(
                          style  = function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d")  
                            target_dates_potato <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 112
                            target_dates_rice <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 112
                            target_dates_prev_potato <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 85
                            target_dates_prev_rice <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 92
                            target_dates_prev <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 92
                            target_dates <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 112
                            
                            #print(!is.na(value) && current_date > target_dates)
                            if (!"Site Selection" %in% colnames(datacroptable)) {
                              color <-"#fff"
                              list(background =color)
                            }else if (!is.na(target_dates)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates) {
                              color <-"#55b047"
                              list(background =color)
                            } else if (!is.na(target_dates)&& !is.na(value) && as.Date(value , format = "%Y-%m-%d") >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            } else if(!is.na(target_dates)&&  is.na(value) && current_date <= target_dates && current_date >= target_dates_prev){
                              color <-"#fdb415"
                              list(background =color)
                            } else if(!is.na(target_dates)&&  is.na(value) && current_date <= target_dates && current_date <= target_dates_prev){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if( !is.na(target_dates)&& is.na(value) && current_date >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            } else if (is.na(target_dates)&& is.na(value) ){
                              color <-"#BE93D4"
                              list(background =color)
                            } else if (datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates_potato) {
                              color <-"#55b047"
                              list(background =color)
                            }else if (datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates_rice) {
                              color <-"#55b047"
                              list(background =color)
                            } else if (datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&& !is.na(value) && as.Date(value , format = "%Y-%m-%d") >= target_dates_potato){
                              color <-"#c3531f"
                              list(background =color)
                            }else if (datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&& !is.na(value) && as.Date(value , format = "%Y-%m-%d") >= target_dates_rice){
                              color <-"#c3531f"
                              list(background =color)
                            }  else if( datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&&  is.na(value) && current_date <= target_dates_potato && current_date >= target_dates_prev_potato){
                              color <-"#fdb415"
                              list(background =color)
                            }  else if( datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&&  is.na(value) && current_date <= target_dates_rice && current_date >= target_dates_prev_rice){
                              color <-"#fdb415"
                              list(background =color)
                            }else if(datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&&  is.na(value) && current_date <= target_dates_potato && current_date <= target_dates_prev_potato){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if(datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&&  is.na(value) && current_date <= target_dates_rice && current_date <= target_dates_prev_rice){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if( datacroptable$Trial[index]=="potatoIrish" && !is.na(target_dates_potato)&& is.na(value) && current_date >= target_dates_potato){
                              color <-"#c3531f"
                              list(background =color)
                            }else if( datacroptable$Trial[index]=="rice" && !is.na(target_dates_rice)&& is.na(value) && current_date >= target_dates_rice){
                              color <-"#c3531f"
                              list(background =color)
                            } else if (is.na(target_dates_potato)&& is.na(value) ){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if (is.na(target_dates_rice)&& is.na(value) ){
                              color <-"#BE93D4"
                              list(background =color)
                            }else {
                              color <-"#fff"
                              list(background =color)
                            }
                          }
                        ),
                        Event8 = colDef(
                          style  = function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d")  
                            target_dates_prev <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 92
                            target_dates <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 112
                            
                            if (!"Site Selection" %in% colnames(datacroptable)) {
                              color <-"#fff"
                              list(background =color)
                            }else if (!is.na(target_dates)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates) {
                              color <-"#55b047"
                              list(background =color)
                            } else if (!is.na(target_dates)&& !is.na(value) && as.Date(value , format = "%Y-%m-%d") >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            } else if(!is.na(target_dates)&&  is.na(value) && current_date <= target_dates && current_date >= target_dates_prev){
                              color <-"#fdb415"
                              list(background =color)
                            } else if(!is.na(target_dates)&&  is.na(value) && current_date <= target_dates && current_date <= target_dates_prev){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if( !is.na(target_dates)&& is.na(value) && current_date >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            } else if (is.na(target_dates)&& is.na(value) ){
                              color <-"#BE93D4"
                              list(background =color)
                            }else {
                              color <-"#fff"
                              list(background =color)
                            }
                            
                          }
                        ),
                        Event9 = colDef(
                          style  = function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d")  
                            target_dates_prev <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 92
                            target_dates <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 112
                            
                            #print(!is.na(value) && current_date > target_dates)
                            if (!"Site Selection" %in% colnames(datacroptable)) {
                              color <-"#fff"
                              list(background =color)
                            }else if (!is.na(target_dates)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates) {
                              color <-"#55b047"
                              list(background =color)
                            } else if (!is.na(target_dates)&& !is.na(value) && as.Date(value , format = "%Y-%m-%d") >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            } else if(!is.na(target_dates)&&  is.na(value) && current_date <= target_dates && current_date >= target_dates_prev){
                              color <-"#fdb415"
                              list(background =color)
                            } else if(!is.na(target_dates)&&  is.na(value) && current_date <= target_dates && current_date <= target_dates_prev){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if( !is.na(target_dates)&& is.na(value) && current_date >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            } else if (is.na(target_dates)&& is.na(value) ){
                              color <-"#BE93D4"
                              list(background =color)
                            }else {
                              color <-"#fff"
                              list(background =color)
                            }
                            
                          }
                        ),
                        Event10 = colDef(
                          style  = function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d")  
                            target_dates_prev <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 92
                            target_dates <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 112
                            
                            #print(!is.na(value) && current_date > target_dates)
                            if (!"Site Selection" %in% colnames(datacroptable)) {
                              color <-"#fff"
                              list(background =color)
                            }else if (!is.na(target_dates)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates) {
                              color <-"#55b047"
                              list(background =color)
                            } else if (!is.na(target_dates)&& !is.na(value) && as.Date(value , format = "%Y-%m-%d") >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            } else if(!is.na(target_dates)&&  is.na(value) && current_date <= target_dates && current_date >= target_dates_prev){
                              color <-"#fdb415"
                              list(background =color)
                            } else if(!is.na(target_dates)&&  is.na(value) && current_date <= target_dates && current_date <= target_dates_prev){
                              color <-"#BE93D4"
                              list(background =color)
                            }else if( !is.na(target_dates)&& is.na(value) && current_date >= target_dates){
                              color <-"#c3531f"
                              list(background =color)
                            } else if (is.na(target_dates)&& is.na(value) ){
                              color <-"#BE93D4"
                              list(background =color)
                            }else {
                              color <-"#fff"
                              list(background =color)
                            }
                            
                          }
                        ),
                        ENID = colDef(
                          html = TRUE,
                          show = TRUE,
                          cell = function(value, index) {
                            s2 <- datacrop[datacrop$ENID == value, ]
                            tippy(value, tooltip = paste("NAME:", unique(s2$ENfirstName), unique(s2$ENSurname), "<br>", "CONTACT:", unique(s2$ENphoneNo)))
                          },
                          style = list(background = "white")
                        )
                      ),
                      defaultColDef = colDef(
                        align = "center",
                        minWidth = 70,
                        # style = function(value) {
                        #   color <- ifelse(is.na(value), "#BE93D4", "#55b047")
                        #   return(list(background = color))
                        # }
                      ),
                      bordered = TRUE
            )
          }) %>% bindCache(datacroptable)
          
          
          output[[paste0("downloadsummary_",i)]] <- downloadHandler(
            filename = function() {
              paste("summary_",gsub("-", "",Sys.Date()), ".pdf", sep = "")
              #paste("summary.pdf", sep = "")
            },
            content = function(file) {
              withProgress(message = "Downloading...", {
                # Create an R Markdown document
                rmarkdown::render(
                  "./www/Scripts/Summary.Rmd",
                  output_file = file,
                  params = list(df1 = ranks.events, df2 = ranks)
                )
              })
            }
            
          )
          
          ##Data Download
          datacropdown<-datacropOO%>%
            dplyr::rename(any_of(c(Date = "today",Country = "intro/country",      Trial = "Trial")
                                 
            ))
          datacropdown<-datacropdown%>%
            dplyr::rename(!!dynamic_label() := "HHID")
          
          output[[paste0("tabledownload_",i)]] <- DT::renderDT(datacropdown)
          
          output[[paste0("downloadData_",i)]] <- downloadHandler(
            filename = function() {
              paste("data_",gsub("-", "",Sys.Date()), ".csv", sep = "")
            },
            content = function(file) {
              write.csv(datacropdown, file, row.names = FALSE)
            }
          )
        })
          
          outputOptions(output, paste0("trials_map_",i), suspendWhenHidden = FALSE)
          outputOptions(output, paste0("submission_trend_",i), suspendWhenHidden = FALSE)
          outputOptions(output, paste0("tabledownload_",i), suspendWhenHidden = FALSE)
          outputOptions(output, paste0("tableR_",i), suspendWhenHidden = FALSE)
          outputOptions(output, paste0("ranking_",i), suspendWhenHidden = FALSE)
          outputOptions(output, paste0("rankingevents_",i), suspendWhenHidden = FALSE)
          outputOptions(output, paste0("issues_",i), suspendWhenHidden = FALSE)
          
        })
    
    #})
    
    
  })
  
  session$allowReconnect(TRUE)
  
}

# Run the application
#shinyApp(ui = ui, server = server,options = list(port = 8000))    #auth0 rmv
# auth0::shinyAppAuth0(ui = ui, server = server,options = list(port = 8000))   #auth0 put


auth0::shinyAppAuth0(ui = ui, server = server,options = list(port = 8000))

