# Install/load packages
suppressMessages(suppressWarnings(library("shiny",character.only = TRUE)))
suppressMessages(suppressWarnings(library("shinyauthr",character.only = TRUE)))
suppressMessages(suppressWarnings(library("shinydashboard",character.only = TRUE)))
suppressMessages(suppressWarnings(library("tidyr",character.only = TRUE)))
suppressMessages(suppressWarnings(library("ggplot2",character.only = TRUE)))
suppressMessages(suppressWarnings(library("sf",character.only = TRUE)))
suppressMessages(suppressWarnings(library("lubridate",character.only = TRUE)))
suppressMessages(suppressWarnings(library("stringr",character.only = TRUE)))
suppressMessages(suppressWarnings(library("plotly",character.only = TRUE)))
suppressMessages(suppressWarnings(library("shinyBS",character.only = TRUE)))
suppressMessages(suppressWarnings(library("shinyjs",character.only = TRUE)))
suppressMessages(suppressWarnings(library("leaflet",character.only = TRUE)))
suppressMessages(suppressWarnings(library("shinyalert",character.only = TRUE)))
suppressMessages(suppressWarnings(library("magrittr",character.only = TRUE)))
suppressMessages(suppressWarnings(library("shinycssloaders",character.only = TRUE)))
suppressMessages(suppressWarnings(library("magrittr",character.only = TRUE)))
suppressMessages(suppressWarnings(library("reactable",character.only = TRUE)))
suppressMessages(suppressWarnings(library("tippy",character.only = TRUE)))
suppressMessages(suppressWarnings(library("shinyWidgets",character.only = TRUE)))
suppressMessages(suppressWarnings(library("auth0",character.only = TRUE)))
suppressMessages(suppressWarnings(library("data.table",character.only = TRUE)))
suppressMessages(suppressWarnings(library("dplyr",character.only = TRUE)))
suppressMessages(suppressWarnings(library("shinydashboardPlus",character.only = TRUE)))
suppressMessages(suppressWarnings(library("shinythemes",character.only = TRUE)))
suppressMessages(suppressWarnings(library("tools",character.only = TRUE)))
suppressMessages(suppressWarnings(library("rmarkdown",character.only = TRUE)))
if(!'aws.s3' %in% installed.packages()[, 'Package']) {install.packages('aws.s3', repos = 'http://cran.us.r-project.org')}
if(!'data.table' %in% installed.packages()[, 'Package']) {install.packages('data.table', repos = 'http://cran.us.r-project.org')}
suppressMessages(suppressWarnings(library("data.table",character.only = TRUE)))
suppressMessages(suppressWarnings(library("aws.s3",character.only = TRUE)))
if(!'auth0' %in% installed.packages()[, 'Package']) {install.packages('auth0', repos = 'http://cran.us.r-project.org')}
suppressMessages(suppressWarnings(library("auth0",character.only = TRUE)))
if(!'gganimate' %in% installed.packages()[, 'Package']) {install.packages('gganimate', repos = 'http://cran.us.r-project.org')}
suppressMessages(suppressWarnings(library("gganimate",character.only = TRUE)))
if(!'DT' %in% installed.packages()[, 'Package']) {install.packages('DT', repos = 'http://cran.us.r-project.org')}
suppressMessages(suppressWarnings(library("DT",character.only = TRUE)))

# load functions+files
source('support_fun.R')

#### Define UI for application 
ui <- 
  fluidPage(
    #fix refresh/reload error by removing the token from URL, (also sets timeout)
    tags$head(
      tags$script(HTML("setTimeout(function() { history.pushState({}, 'Page Title', '/'); }, 2000);"))
    ),
    shinyjs::useShinyjs(),
    extendShinyjs(text = jscode, functions = "hrefAuto"),
    #display only after login
    uiOutput("conditionalBox"), 
    #load the defined UI
    uiOutput("sidebarpanel", padding = 0) 
  )

#### Define server logic 
server <- function(input, output, session) {
  keep_alive <- shiny::reactiveTimer(intervalMs = 10000, session = shiny::getDefaultReactiveDomain())
  shiny::observe({keep_alive()})
  
  shinyjs::runjs("
    $(document).on('shiny:connected', function(event) {
      // When a tab is clicked, update the input$nav value
      $('.navbar-nav a').on('click', function() {
        var selectedTab = $(this).attr('data-value');
        Shiny.setInputValue('nav', selectedTab);
      });
    });
  ")
  
  user_use_case_data <- names(session$userData$auth0_info$eia_apps)
  # Reorder to start with "DEMO" to avoid empty acc display
  if ("DEMO" %in% user_use_case_data) {
    user_use_case_data <- c("DEMO", user_use_case_data[user_use_case_data != "DEMO"])
  }
  
  if ("ex-Wcover-Ghana" %in% user_use_case_data) {
    if (!("GH-CerLeg-Esoko" %in% user_use_case_data)) {
      user_use_case_data[user_use_case_data == "ex-Wcover-Ghana"] <- "GH-CerLeg-Esoko"
    }
  }
  
  # IF USER NOT ASSOCIATED WITH ANY USECASE DATA... Show demo or warning?
  # Render the warning based on user_use_case_data
  output$conditionalBox <- renderUI({
    if (is.null(user_use_case_data) || length(user_use_case_data) == 0) {
      tags$div(
        style = "display: flex; justify-content: center; align-items: center; height: 100vh;",
        tags$div(
          class = "alert alert-warning",
          style = "background-color: #fdb415; color: #000; border-radius: 10px; padding: 20px; box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);",
          tags$strong(icon("exclamation-triangle"), " Warning!"),  # Font Awesome icon
          tags$p(" No usecase data is available for this user. For further inquiries, please contact Eduardo Garcia (IITA) at email: e.bendito@cgiar.org.", style = "margin: 10px 0;")
        )
      )
    } else {
      NULL  # No warning to display
    }
  })
  
  ## Define UI render function ----------------------
  #Render UI: Require login
  ##########################################################################################################################################
  #################################################### UI RENDER ####################################################################
  ##########################################################################################################################################
  
  output$sidebarpanel <- renderUI({
    # List of active use cases/ ensure only active are on dropdown menu
    active_use_case_list <- c("DEMO", "Mercy-Corps-SPROUT", "Solidaridad-Soy-Advisory", 
                              "GH-CerLeg-Esoko", "ex-Wcover-Ghana", "KALRO", "SNS-RWANDA")
    
    # Filter user use case data based on active use cases
    user_use_case_data <- user_use_case_data[user_use_case_data %in% active_use_case_list]
    
    # Reset UI or additional setup if needed
    reset()
    
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
      
      # Pass the filtered user_use_case_data directly to create_navbarMenu
      create_navbarMenu(user_use_case_data)
    )
  })
  
  
  ##########################################################################################################################################
  #################################################### SERVER FUNCTIONS ####################################################################
  ##########################################################################################################################################
  
  observeEvent(input$dashboard, {
    # Disable the menu item, toggle content with animation, then re-enable menu item after animation
    shinyjs::toggle("dashboard")
    shinyjs::toggle("collapsible-content", anim = TRUE) 
    shinyjs::toggleState("dashboard") 
  })
  
  observeEvent(input$logout, {
    auth0::logoutButton() # Log the user out
  })
  
  ## Clear session data at the beginning of each navigation change
  reset()
  datacrop <<- data.frame()   
  rawdata <<- data.frame()    
  columns_to_append <<- c()  
  patternissues <<- ""   
  patternissuesE <<- ""  
  # Clear individual UI elements for each use case
  lapply(names(usecases.index), function(uc) {
    # Clear individual UI elements for each use case
    output[[paste0("trials_map_", uc)]] <- renderPlot(NULL)
    output[[paste0("submission_trend_", uc)]] <- renderPlot(NULL)
    output[[paste0("tabledownload_", uc)]] <- renderUI(NULL)
    output[[paste0("tableR_", uc)]] <- renderTable(NULL)
    output[[paste0("ranking_", uc)]] <- renderTable(NULL)
    output[[paste0("rankingevents_", uc)]] <- renderTable(NULL)
    output[[paste0("issues_", uc)]] <- renderTable(NULL)
  })
  
  
  ##Define data for each usecase   #auth0 put names
  observeEvent(input$nav,{
    
    tryCatch( 
      if (input$nav== "SNS-RWANDA"){
        
        RWA.O_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "SNSRwandaOdata.csv"),
                                  file = tempfile(fileext = ".csv")
        ) %>%
          fread()
        
        RWA.SUM_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "SNSRwandaSUMdata.csv"),
                                    file = tempfile(fileext = ".csv")
        ) %>%
          fread()
        
        RWA.O_data <-RWA.O_data%>%
          rename(
            ENID = wrong_ENID,
            HHID = wrong_ID)%>%
          mutate(Stage = "Validation"  ) # for 'stage' filter purpose 
        
        
        datacrop <- RWA.SUM_data
        rawdata <- RWA.O_data
        columns_to_append <- c("ENID", "HHID", "Trial",#"treat",
                               "Site Selection", "event1", "event2", "event3", "event4", "event5", "event6","event7")
        patternissues<-"^RSENRW"
        patternissuesE<-"^RSHHRW"
        
        
      }else if (input$nav== "Solidaridad-Soy-Advisory"){
        SOL.O_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "SolidaridadOdata.csv"),
                                  file = tempfile(fileext = ".csv")
        ) %>%
          fread()
        
        SOL.SUM_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "SolidaridadSUMdata.csv"),
                                    file = tempfile(fileext = ".csv")
        ) %>%
          fread()
        
        SOL.NOT_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "SolidaridadNOTdata.csv"),
                                    file = tempfile(fileext = ".csv")
        ) %>%
          fread()
        
        datacrop <- SOL.SUM_data
        rawdata <- SOL.O_data
        patternissues<-"^SDENMW|SDENZM|SDENMZ"
        patternissuesE<-"^SDHHMW|SDHHZM|SDHHMZ|SDRP"
        columns_to_append <- c("ENID", "HHID", "Trial",#"treat",
                               "Site Selection", "event1", "event2", "event3", "event4", "event5", "event6","event7", "event8a", "event8b","event8c")
        
        
      }else if (input$nav== "KALRO"){
        KL.O_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "KLOdata.csv"),
                                 file = tempfile(fileext = ".csv")
        ) %>%
          fread()
        
        KL.SUM_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "KLSUMdata.csv"),
                                   file = tempfile(fileext = ".csv")
        ) %>%
          fread()
        
        datacrop <- KL.SUM_data
        rawdata <- KL.O_data
        patternissues<-""
        patternissuesE<-""
        columns_to_append <- c("ENID", "HHID", "Trial",#"treat",
                               "Site Selection", "eventS", "event1","event1", "event2", "event3", "event4", "event5", "event6", "event8")
        
        
        
      }else if (input$nav== "Mercy-Corps-SPROUT"){
        MC.O_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "MCOdata.csv"),
                                 file = tempfile(fileext = ".csv")
        ) %>%
          fread()
        
        MC.SUM_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "MCSUMdata.csv"),
                                   file = tempfile(fileext = ".csv")
        ) %>%
          fread()
        
        datacrop <- MC.SUM_data
        rawdata <- MC.O_data
        patternissues<-""
        patternissuesE<-""
        columns_to_append <- c("ENID", "HHID", "Trial",#"treat",
                               "Site Selection", "event1", "event2", "event3", "event4", "event5", "event6", "event7")
        
      }else if (input$nav== "GH-CerLeg-Esoko"){
        CE.O_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "CEOdata.csv"),
                                 file = tempfile(fileext = ".csv")
        ) %>%
          fread()
        
        CE.SUM_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "CESUMdata.csv"),
                                   file = tempfile(fileext = ".csv")
        ) %>%
          fread()
        
        CE.ICO_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "CEICOdata.csv"),
                                   file = tempfile(fileext = ".csv")
        ) %>%
          fread()
        
        CE.ICSUM_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "CEICSUMdata.csv"),
                                     file = tempfile(fileext = ".csv")
        ) %>%
          fread()
        datacrop <- CE.SUM_data
        rawdata <- CE.O_data
        patternissues<-""
        patternissuesE<-""
        columns_to_append <- c("ENID", "HHID", "Trial",#"treat",
                               "Site Selection", "event1", "event2", "event5", "event6", "event7", "event8", "event9")
        
      }else if (input$nav== "DEMO"){
        DEMO.O_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "DEMOOdata.csv"),
                                   file = tempfile(fileext = ".csv")
        ) %>%
          fread()
        
        DEMO.SUM_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "DEMOSUMdata.csv"),
                                     file = tempfile(fileext = ".csv")
        ) %>%
          fread()
        
        datacrop <- DEMO.SUM_data
        rawdata <- DEMO.O_data
        patternissues<-""
        patternissuesE<-""
        columns_to_append <- c("ENID", "HHID", "Trial",#"treat",
                               "Site Selection","event1", "event2", "event3", "event4", "event5", "event6", "event7")
        
      }else{
        datacrop <- data.frame()
        rawdata <- data.frame()
        columns_to_append <- c()
        patternissues<-""
        patternissuesE<-""
        
      },
      error = function(e) NULL)
    
    
    selectInput_ids <- list()
    selectInput_values <- list()
    
    lapply(names(usecases.index), function(k) {
      i<- usecases.index[names(usecases.index[ k ])]
      
      selectInput_ids <- c(selectInput_ids,
                           list(
                             stage = paste0("stagefinder_", i),
                             experiment = paste0("experimentfinder_", i),
                             season = paste0("seasonfinder_", i),
                             date = paste0("datefinder_", i),
                             enumerator = paste0("enumeratorfinder_", i),
                             region = paste0("regionfinder_", i),
                             household = paste0("householdfinder_", i)
                           )
      )
      
      output[[paste0("stagefinderr_",i)]] <-renderUI({
        selectInput(
          paste0("stagefinder_",i),
          label = "Stage",
          multiple=FALSE,
          choices =c('Research','Validation','Piloting'),
          selected= "Validation")
      })
      
      output[[paste0("experimentfinderr_",i)]] <-renderUI({
        if (!is.null(input[[paste0("stagefinder_", i)]])) {
          
          if (input[[paste0("stagefinder_", i)]] == 'Research' ){
            selectInput(
              paste0("experimentfinder_",i),
              label = "Experiment",
              multiple=FALSE,
              choices =c('NOT','Variety Selection', 'Planting Date'),
              selected= (c(sort(unique(datacrop$Trial))))[1])
          }else if (input[[paste0("stagefinder_", i)]] == 'Validation'){
            selectInput(
              paste0("experimentfinder_",i),
              label = "Experiment",
              multiple=FALSE,
              choices =c('Fertilizer Recommendation','Variety Selection', 'Planting Date', 'Intercropping'),
              selected= (c(sort(unique(datacrop$Trial))))[1])
          }else if (input[[paste0("stagefinder_", i)]] == 'Piloting'){
            selectInput(
              paste0("experimentfinder_",i),
              label = "Experiment",
              multiple=FALSE,
              choices =c('Fertilizer Recommendation','Variety Selection', 'Planting Date'),
              selected= (c(sort(unique(datacrop$Trial))))[1])
          }
        } else {
          selectInput(
            paste0("experimentfinder_",i),
            label = "Experiment",
            multiple=FALSE,
            choices =NULL,
            selected= NULL
          )
        }
      })
      
      output[[paste0("cropfinderr_",i)]] <-renderUI({
        selectInput(
          paste0("cropfinder_",i),
          label = "Crop",
          multiple=TRUE,
          choices =c("All", sort(unique(datacrop$Crop))),
          selected= "All")
      })
      
      output[[paste0("datefinderr_",i)]] <-renderUI({
        dateRangeInput(paste0("datefinder_",i),
                       "Date",
                       start = min(na.omit(rawdata$today)),
                       end   =  Sys.time())
      })
      
      output[[paste0("enumeratorfinderr_",i)]] <-renderUI({
        selectInput(
          paste0("enumeratorfinder_",i),
          label = "Enumerator",
          multiple=T,
          choices = c("All", sort(unique(datacrop$ENID))),
          selected= "All")
      })
      
      output[[paste0("regionfinderr_",i)]] <-renderUI({
        selectInput(
          paste0("regionfinder_",i),
          label = "Country",
          multiple=FALSE,
          choices = c() )
      })
      
      output[[paste0("householdfinderr_",i)]] <-renderUI({
        selectInput(
          paste0("householdfinder_",i),
          label = "Household",
          multiple=T,
          choices = c("All", sort(unique(na.omit(datacrop$HHID)))
          ),
          selected= "All")
      })
      
      output[[paste0("Totsub_box_",i)]] <-renderUI({
        infoBox(
          "Total submissions",paste0(nrow(rawdata)), icon = icon("list"),
          color = "olive", width = "100%"       )
      })
      
      output[[paste0("country_",i)]] <-renderUI({
        infoBox(
          "Country", HTML(paste(unique(na.omit(rawdata$Country)), collapse = ", ")) , icon = icon("globe"),
          color = "olive",width = "100%"       )
        
      })
      
      output[[paste0("project_",i)]] <-renderUI({
        infoBox(
          "Usecase", as.character(input$nav), icon = icon("barcode"),
          color = "olive",width = "100%"       )
      })
      
    })
    
    observe({
      input_nav <- input$nav
      
      # Create a reactive expression for all use cases
      lapply(names(usecases.index), function(k) {
        
        i <- usecases.index[names(usecases.index[ k ])]
        
        experimentUsecase <- input[[paste0("experimentfinder_", i)]]
        stageUsecase <- input[[paste0("stagefinder_", i)]]
        cropUsecase <- input[[paste0("cropfinder_", i)]]
        dateUsecase <- input[[paste0("datefinder_", i)]]
        enumeratorUsecase <- input[[paste0("enumeratorfinder_", i)]]
        householdUsecase <- input[[paste0("householdfinder_", i)]]
        applyfilter<-input[[paste0("apply_filters", i)]]
        
        
        reactive_expr <- reactive({
          req(input_nav,experimentUsecase, stageUsecase,cropUsecase, dateUsecase, enumeratorUsecase, householdUsecase)
          
        }) %>%
          bindCache(experimentUsecase, stageUsecase, cropUsecase, dateUsecase, enumeratorUsecase, householdUsecase)
        
        observeEvent(reactive_expr(), {
          
          tryCatch(
            if (input$nav== "SNS-RWANDA"){  
              
              datacrop <- RWA.SUM_data
              rawdata <- RWA.O_data
              columns_to_append <- c("ENID", "HHID", "Trial",#"treat",
                                     "Site Selection", "event1", "event2", "event3", "event4", "event5", "event6","event7")
              
            }else if (input$nav== "Solidaridad-Soy-Advisory"){
              if ("Validation" %in% stageUsecase ){
                datacrop <- SOL.SUM_data
                rawdata <- SOL.O_data
                columns_to_append <- c("ENID", "HHID", "Trial",#"treat",
                                       "Site Selection", "event1", "event2", "event3", "event4", "event5", "event6","event7", "event8a", "event8b","event8c")
                
              }else if ("Research" %in% stageUsecase ){
                datacrop <- SOL.SUM_data
                rawdata <- SOL.NOT_data
                columns_to_append <- c("ENID", "HHID", "Trial",#"treat",
                                       "Site Selection","event1",  "event2", "event3", "event4", "event5", "event6","event7", "event8", "event9", "event10","event11", "event12", "event13", "event14", "event15", "event16","event17", "event18", "event19", "event20","event21")
                
              }
            }else if (input$nav== "KALRO"){
              KL.O_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "KLOdata.csv"),
                                       file = tempfile(fileext = ".csv")
              ) %>%
                fread()
              
              KL.SUM_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "KLSUMdata.csv"),
                                         file = tempfile(fileext = ".csv")
              ) %>%
                fread()
              
              datacrop <- KL.SUM_data
              rawdata <- KL.O_data
              patternissues<-""
              patternissuesE<-""
              columns_to_append <- c("ENID", "HHID", "Trial",#"treat",
                                     "Site Selection", "eventS", "event1","event1", "event2", "event3", "event4", "event5", "event6", "event8")
              
              
              
              
            }else if (input$nav== "Mercy-Corps-SPROUT"){
              MC.O_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "MCOdata.csv"),
                                       file = tempfile(fileext = ".csv")
              ) %>%
                fread()
              
              MC.SUM_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "MCSUMdata.csv"),
                                         file = tempfile(fileext = ".csv")
              ) %>%
                fread()
              
              datacrop <- MC.SUM_data
              rawdata <- MC.O_data
              patternissues<-""
              patternissuesE<-""
              columns_to_append <- c("ENID", "HHID", "Trial",#"treat",
                                     "Site Selection", "event1", "event2", "event3", "event4", "event5", "event6", "event7")
              
            }else if (input$nav== "GH-CerLeg-Esoko"){
              CE.O_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "CEOdata.csv"),
                                       file = tempfile(fileext = ".csv")
              ) %>%
                fread()
              
              CE.SUM_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "CESUMdata.csv"),
                                         file = tempfile(fileext = ".csv")
              ) %>%
                fread()
              
              CE.ICO_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "CEICOdata.csv"),
                                         file = tempfile(fileext = ".csv")
              ) %>%
                fread()
              
              CE.ICSUM_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "CEICSUMdata.csv"),
                                           file = tempfile(fileext = ".csv")
              ) %>%
                fread()
              if ("Validation" %in% stageUsecase ){
                datacrop <- CE.SUM_data
                rawdata <- CE.O_data
                patternissues<-""
                patternissuesE<-""
                columns_to_append <- c("ENID", "HHID", "Trial",#"treat",
                                       "Site Selection", "event1", "event2", "event5", "event6", "event7", "event8", "event9")
                
              }else if ("Research" %in% stageUsecase ){
                datacrop <- CE.ICSUM_data
                rawdata <- CE.ICO_data
                patternissues<-""
                patternissuesE<-""
                columns_to_append <- c("ENID", "HHID", "Trial",#"treat",
                                       "Site Selection", "event1","event11", "event2", "event3","event4","event5", "event6", "event7", "event8", "event9","event10")
                
              }
              
              
            }else if (input$nav== "DEMO"){
              DEMO.O_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "DEMOOdata.csv"),
                                         file = tempfile(fileext = ".csv")
              ) %>%
                fread()
              
              DEMO.SUM_data <- save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), "DEMOSUMdata.csv"),
                                           file = tempfile(fileext = ".csv")
              ) %>%
                fread()
              
              datacrop <- DEMO.SUM_data
              rawdata <- DEMO.O_data
              patternissues<-""
              patternissuesE<-""
              if ("rice" %in% experimentUsecase ){
                columns_to_append <- c("ENID", "HHID", "Trial","Site Selection","event1", "event2", "event3", "event4", "event5", "event6", "event7")
              } else if ("cassava" %in% experimentUsecase ){
                columns_to_append <- c("ENID", "HHID", "Trial","Site Selection","event1", "event2", "event3", "event4", "event5", "event6", "event7","event8")
              } else if ("cassava" %in% experimentUsecase ){
                columns_to_append <- c("ENID", "HHID", "Trial","Site Selection","event1", "event2", "event3", "event4", "event5")
              }
              
            }else {
              datacrop <- data.frame()
              rawdata <- data.frame()
              columns_to_append <- c()
              
            }
            ,error = function(e) NULL)
          
          
          if (stageUsecase == 'Research') {
            experimentfinderr_new_choices <- c('NOT', 'Variety Selection', 'Planting Date')
          } else if (stageUsecase == 'Validation') {
            experimentfinderr_new_choices <- c('Fertilizer Recommendation', 'Variety Selection', 'Planting Date', 'Intercropping')
          } else if (stageUsecase == 'Piloting') {
            experimentfinderr_new_choices <- c('Fertilizer Recommendation', 'Variety Selection', 'Planting Date')
          }
          cropfinderr_new_choices <- c("All", sort(unique(datacrop$Crop)))
          enumeratorfinderr_new_choices <- c("All", sort(unique(datacrop$ENID)))
          householdfinderr_new_choices <- c("All", sort(unique(na.omit(datacrop$HHID))))
          datefinderr_new_choices <- min(na.omit(rawdata$today))
          
          
          updateSelectInput(session, paste0("experimentfinderr_",i), choices =  experimentfinderr_new_choices)
          updateSelectInput(session, paste0("cropfinderr_",i), choices =  cropfinderr_new_choices)
          updateSelectInput(session, paste0("enumeratorfinderr_",i), choices = enumeratorfinderr_new_choices)
          updateSelectInput(session, paste0("householdfinderr_",i), choices = householdfinderr_new_choices)
          updateDateRangeInput(session, paste0("datefinderr_",i), start = datefinderr_new_choices, end = Sys.time())
         
          
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
          wgroup <-tryCatch( 
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
              ggplotly(Ir, tooltip=c("x","y")) 
              ,error = function(e) NULL)
          })
          
          
          ##Enumerator Ranking
          
          datacroptable<-datacrop 
          
          # Columns to append
          datacroptable<-as.data.frame(datacroptable)
          
          # # Check if columns exist in the dataframe
          missing_columns <- setdiff(columns_to_append, colnames(datacroptable))
          #missing_columns2 <- setdiff(columns_to_append, colnames(datacroptablev))
          
          # 
          # # Append missing columns only
          tryCatch(  if (length(missing_columns) > 0) {
            datacroptable[, missing_columns] <- NA
          } ,error = function(e) NULL)
          
          datacroptable<-  tryCatch(  datacroptable %>%
                                        select(any_of(columns_to_append ))
          )
          colnames(datacroptable) <- toTitleCase(colnames(datacroptable)) #Title case for table headers
          
          ranks.events<-  tryCatch(  datacroptable %>%
                                       #select(any_of(columns_to_append)) %>%
                                       select(-any_of(c("ENID", "HHID", "Trial"))) %>%
                                       dplyr::summarise(across(.fns = ~sum(!is.na(.)))) %>%  suppressWarnings() ,error = function(e) NULL)  #total submissions for each event
          
          
          
          ranks<-  tryCatch(  datacroptable %>%
                                # select(any_of(columns_to_append)) %>%
                                select(-any_of(c( "HHID", "Trial")))%>%
                                group_by(ENID) %>%
                                dplyr::summarise(across(.fns = ~sum(!is.na(.))))%>%  suppressWarnings()
                              ,error = function(e) NULL)  #total submissions,  for each event per enumerator
          
          
          #datacroptable$Site.Selection <-as.Date(datacroptable$Site.Selection)
          
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
          datacropI<-datacroptable 
          datacropissues<-datacropI %>%
            dplyr::select(any_of(c("ENID", "HHID")))
          
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
          # Subset rows based on conditions
          datacropissuesA <-tryCatch(  datacropissues %>%
                                         filter(!grepl(patternissues, ENID)) %>%
                                         mutate(Issues = ifelse(!grepl(patternissues, ENID), "Check ENID", NA))%>%
                                         mutate(Issues = as.character(Issues)),error = function(e) NULL) 
          datacropissuesB <- tryCatch( datacropissues %>%
                                         filter(!grepl(patternissuesE, HHID)) %>%
                                         mutate(Issues = ifelse(!grepl(patternissuesE, HHID), "Check HHID", NA)) %>%
                                         mutate(Issues = as.character(Issues)),error = function(e) NULL) 
          datacropissuesC <- tryCatch( datacropI %>%
                                         filter(apply(datacropI[, 3:ncol(datacropI)], 1, event_conditions)) %>% 
                                         #filter(apply(datacropI[, 4:ncol(datacropI)], 1, event_conditions))%>% # Consider columns from "event1" to the end
                                         dplyr::select(any_of(c("ENID", "HHID")))%>%
                                         mutate(Issues = "Check submission events" ),error = function(e) NULL) 
          
          datacropissues <-bind_rows(datacropissuesA, datacropissuesB,datacropissuesC)
          datacropissues <- as.data.frame( datacropissues)
          
          output[[paste0("issues_",i)]]  <- renderReactable({
            reactable(datacropissues,
                      pagination = FALSE,
                      showPagination = TRUE,
                      paginateSubRows = FALSE
            )
          }) %>%
            bindCache(datacropissues)
          
          
          ##Enumerator Tracker Table
          output[[paste0("tableR_",i)]] <- renderReactable({
            reactable(datacroptable,
                      pagination = FALSE,
                      showPagination = TRUE,
                      paginateSubRows = FALSE,
                      defaultExpanded = TRUE,
                      columns = list(
                        Crop= colDef(filterable = TRUE,
                                     style  = function(value) {
                                       list(background ="white")
                                     }),
                        HHID = colDef(
                          html = TRUE,
                          #filterable = TRUE,
                          show = TRUE,
                          cell =    function(value,index) {
                            s2<-datacrop[which(datacrop$HHID==value ), ]
                            tippy(value,tooltip = paste("NAME:", unique(s2$HHfirstName) , unique(s2$HHSurname), "<br>", "CONTACT:", unique(s2$HHphoneNo)))
                          },
                          
                          style  = function(value) {
                            list(background ="white")
                          }),
                        `Site Selection` = colDef(
                          #style  = function(value) {
                          
                          style = function(value) {
                            # Check if the value is missing or not in the expected date format
                            if (is.na(value) ) {
                              list(background = "#c3531f")  # Set default background color for missing or invalid values
                            } else {
                              list(background = "#55b047")
                            }
                          }
                        ),
                        Event1 = colDef(
                          style  = function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d")  
                            
                            target_dates <- as.Date(datacroptable$`Site Selection`[index], format = "%Y-%m-%d") + 14
                            
                            if (is.na(target_dates)&& is.na(value) ) {
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
                            }else {
                              color <-"#c3531f"
                              list(background =color)
                            }
                            
                          }
                        ),
                        Event1R = colDef(
                          style  = function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d")  
                            
                            target_dates <- as.Date(datacroptable$`Site Selection`[index], format = "%Y-%m-%d") + 14
                            
                            if (is.na(target_dates)&& is.na(value) ) {
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
                        Event11 = colDef(
                          style  = function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d")  
                            target_dates <- as.Date(datacroptable$`Site Selection`[index], format = "%Y-%m-%d") + 14
                            
                            if (is.na(target_dates)&& is.na(value) ) {
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
                        Event2 = colDef(
                          style  =    function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d")  
                            target_dates <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 29
                            if (!is.na(target_dates)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates) {
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
                            }
                          }
                        ),
                        Event3 = colDef(
                          style  = function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d") 
                            target_dates <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 43
                            target_dates_prev <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 29
                            
                            if (!is.na(target_dates)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates) {
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
                            
                            if (!is.na(target_dates)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates) {
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
                            if (!is.na(target_dates)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates) {
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
                            if (!is.na(target_dates)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates) {
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
                            if (!is.na(target_dates)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates) {
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
                            }
                          }
                        ),
                        Event8 = colDef(
                          style  = function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d")  
                            target_dates_prev <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 92
                            target_dates <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 112
                            if (!is.na(target_dates)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates) {
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
                            }
                            
                          }
                        ),
                        Event9 = colDef(
                          style  = function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d")  
                            target_dates_prev <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 92
                            target_dates <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 112
                            
                            #print(!is.na(value) && current_date > target_dates)
                            if (!is.na(target_dates)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates) {
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
                            }
                            
                          }
                        ),
                        Event10 = colDef(
                          style  = function(value,index) {
                            current_date <-as.Date(Sys.Date() , format = "%Y-%m-%d")  
                            target_dates_prev <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 92
                            target_dates <- as.Date(datacroptable$Event1[index], format = "%Y-%m-%d") + 112
                            
                            #print(!is.na(value) && current_date > target_dates)
                            if (!is.na(target_dates)&& !is.na(value) &&  as.Date(value , format = "%Y-%m-%d") <= target_dates) {
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
                            }
                            
                          }
                        ),
                        
                        ENID = colDef(
                          html = TRUE,
                          #filterable = TRUE,
                          show = TRUE,
                          cell =    function(value,index) {
                            s2<-datacrop[which(datacrop$ENID==value ), ]
                            tippy(value,tooltip = paste("NAME:", unique(s2$ENfirstName) , unique(s2$ENSurname), "<br>", "CONTACT:", unique(s2$ENphoneNo)))
                          },
                          header = function(value) {tippy(value,tooltip = paste("NAME:", "<br>", "CONTACT:"))},
                          style  = function(value) {
                            list(background ="white")
                          }
                        )
                      ),
                      defaultColDef = colDef(
                        align = "center",
                        minWidth = 70,
                        
                        style  = function(value) {
                          
                          color<-ifelse(is.na(value) ,"#BE93D4","#55b047")
                        }
                        
                      ),
                      bordered = TRUE
            )
            
          })%>%
            bindCache(datacroptable)
          
          
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
          
          output[[paste0("tabledownload_",i)]] <- DT::renderDT(datacropdown)
          
          output[[paste0("downloadData_",i)]] <- downloadHandler(
            filename = function() {
              paste("data_",gsub("-", "",Sys.Date()), ".csv", sep = "")
            },
            content = function(file) {
              write.csv(datacropdown, file, row.names = FALSE)
            }
          )
          
          outputOptions(output, paste0("trials_map_",i), suspendWhenHidden = FALSE)
          outputOptions(output, paste0("submission_trend_",i), suspendWhenHidden = FALSE)
          outputOptions(output, paste0("tabledownload_",i), suspendWhenHidden = FALSE)
          outputOptions(output, paste0("tableR_",i), suspendWhenHidden = FALSE)
          outputOptions(output, paste0("ranking_",i), suspendWhenHidden = FALSE)
          outputOptions(output, paste0("rankingevents_",i), suspendWhenHidden = FALSE)
          outputOptions(output, paste0("issues_",i), suspendWhenHidden = FALSE)
          
        })
      })
    })
    
  })
  
  session$allowReconnect(TRUE)
  
}

# Run the application
#shinyApp(ui = ui, server = server,options = list(port = 8000))    #auth0 rmv
auth0::shinyAppAuth0(ui = ui, server = server,options = list(port = 8000))   #auth0 put


