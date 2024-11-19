# Some support functions and definitions

#basemap for leaflet
basemap <- leaflet() %>%
  addProviderTiles(providers$CartoDB.Positron) #%>%

#ggplot theme
them2<-theme(panel.background = element_rect(fill = "white"), # bg of the panel
             plot.background = element_rect(fill = "white", color = NA), # bg of the plot
             panel.grid.major = element_blank(),
             panel.grid.minor = element_blank(),
             plot.title = element_text(size=12, face="bold",color = "#a9a9a9", hjust = 0.5 ),
             strip.text.x = element_text(size = 15, color = "#a9a9a9", face = "bold"),
             axis.text=element_text(color = "#a9a9a9",size=10),
             axis.text.x = element_text(angle = 60, hjust = 1),
             #axis.text.y = element_blank(),
             #axis.title=element_text(size=16,face="bold"),
             axis.title=element_text(color = "#a9a9a9",size=10),
             legend.title = element_text(color = "#a9a9a9",face="bold", size = 12),
             legend.text = element_text(color = "#a9a9a9", size = 10),                   
             legend.background = element_rect(fill = "black"),                   
             panel.border = element_blank(),
             #axis.line.x = element_line(color="black", size = 0.3),
             #scale_x_date(date_breaks = "months" , date_labels = "%b-%y"),
             #axis.line.y = element_line(color="black", size = 0.3))  
             axis.line.x = element_blank(),
             #hovertemplate = paste('%{x}', '<br>lifeExp: %{text:.2s}<br>'),
             axis.line.y = element_blank())

jscode <- "
shinyjs.hrefAuto = function(url) { window.location.href = url;};"

usecases.index<-c("ATAFI-MOVE" =1 , "BAYGAP-(BAYER)" =2 ,  "Cocoa-Soils" = 3  , "DEMO"  =21   , "DRC-Coffee-OLAM" =5 ,
                  "DSR-Extension-Vietnam"=6 ,   "DSRC-SE-ASIA" =7  ,"DigGreen-ETHIOPIA" =8 , "Fert-Ethiopia" =9 ,"Govt-Egypt"   =10 ,
                  "Govt-LatAm"=11 , "KALRO"  =20,  "Mercy-Corps-SPROUT" = 18  ,    "Morocco-CA" =14     , "One-Acre-Fund"  =12   ,
                  "Planting-S-Asia"  =16  ,      "Rainforest-Alliance" =17  ,   "SAA-NIGERIA"   =13    ,  "SNS-RWANDA" =4 ,
                  "Solidaridad-Soy-Advisory"=15,  "GH-CerLeg-Esoko"  =19, "ex-Wcover-Ghana" = 22)


create_tab_panel <- function(tab_name) {
  uc <- usecases.index[[tab_name]]
  
  # Helper function to generate the sidebar menu items
  generate_sidebar_ui <- function(uc) {
    menu_items <- c("stage", "experiment", "crop", "date", "enumerator", "household")
    lapply(menu_items, function(item) {
      uiOutput(paste0(item, "finderr_", uc))
    })
  }
  
  # Helper function to generate summary info box row
  generate_summary_info_boxes <- function(uc) {
    fluidRow(
      column(width = 12, align = 'left', 
             infoBoxOutput(paste0("project_", uc)),
             infoBoxOutput(paste0("country_", uc)),
             infoBoxOutput(paste0("Totsub_box_", uc))
      )
    )
  }
  
  # Helper function for rendering leaflet and plotly
  generate_maps_and_charts <- function(uc) {
    fluidRow(
      column(width = 6, 
             h4("Trials by Location", align = 'center'), 
             leafletOutput(paste0('trials_map_', uc), height = "50vh"),
             style = "background-color: #f2f2f2;"
      ),
      column(width = 6, 
             h4("Trend of Submissions", align = 'center'), 
             plotlyOutput(paste0('submission_trend_', uc), height = "50vh"),
             style = "background-color: #f2f2f2;"
      )
    )
  }
  
  # Helper function for generating the data tables
  generate_data_table_section <- function(uc) {
    div(class = "section levell",
        fluidRow(
          h4("Summary of Complete Submissions", align = 'center'),
          div(style = "text-align: right;", downloadButton(paste0("downloadsummary_", uc), "Download Summary")),
          HTML('<br>')
        ),
        fluidRow(class = "section level1", column(width = 12, align = 'center', reactableOutput(paste0("rankingevents_", uc)))),
        fluidRow(class = "section level1", column(width = 12, align = 'center', reactableOutput(paste0("ranking_", uc))))
    )
  }
  
  # Define main tabPanel structure
  tabPanel(
    tab_name,
    dashboardPage(
      dashboardHeader(
        tags$li(
          class = "dropdown",
          auth0::logoutButton()  # Add logout button to header
        )
      ),
      dashboardSidebar(
        width = 200,
        useShinyjs(),
        id = paste0("sidebar-", uc),
        tags$head(tags$style(HTML("
          .collapsible-content {
            display: none;
            padding: 5px;
          }
          .collapsed .collapsible-content {
            display: none;
          }
          .expanded .collapsible-content {
            display: block;
          }
        "))),
        sidebarMenu(
          id = paste0("tabs-", uc),
          menuItem(
            "DATA", tabName = 'dashboard', icon = icon('dashboard'),
            startExpanded = TRUE,
            generate_sidebar_ui(uc)  # Add dynamic UI outputs for filters
          )
        )
      ),
      dashboardBody(
        tabsetPanel(
          id = paste0("tabss-", uc),
          type = "tabs",
          
          # Summary tab
          tabPanel(tabName = "Summary", "SUMMARY",
                   div(class = "container-fluid2", 
                       div(class = "section levell", HTML('<br>'), generate_summary_info_boxes(uc)),
                       div(class = "section levell", generate_maps_and_charts(uc)),
                       HTML('<br>'),
                       generate_data_table_section(uc)
                   )
          ),
          
          # Enumerators tab
          tabPanel(tabName = "Enumerators", "ENUMERATORS",
                   div(class = "container-fluid2", 
                       HTML('<br>'),
                       HTML('<span style="background-color: #55b047;" class="dot">Complete</span> &nbsp; 
                             <span style="background-color: #fdb415;" class="dot">Missing Details</span> &nbsp;
                             <span style="background-color: #c3531f;" class="dot">Overdue</span> &nbsp;
                             <span style="background-color: #BE93D4;" class="dot">Future Event</span>'),
                       HTML('<br>'),
                       div(class = "section levell", reactableOutput(paste0("tableR_", uc)))
                   )
          ),
          
          # Issues tab
          tabPanel(tabName = "issues", "ISSUES",
                   div(class = "container-fluid2", 
                       HTML('<h5> The list below includes all enumerator IDs (ENID), household IDs (HHID), and data collection events that require review due to being flagged as unusual.</h5>'),
                       div(class = "section levell", 
                           fluidRow(column(width = 12, h4("", align = 'center'), reactableOutput(paste0("issues_", uc)))))
                   )
          ),
          
          # Data preview tab
          tabPanel(tabName = "data", "DATA PREVIEW",
                   div(class = "container-fluid2", 
                       div(style = "text-align: right;", downloadButton(paste0("downloadData_", uc), "Download CSV")),
                       HTML('<br>'),
                       div(class = "section level1", DT::DTOutput(paste0('tabledownload_', uc)), 
                           style = "height:75vh; overflow-y: scroll;overflow-x: scroll;")
                   )
          ),
          
          # Glossary tab
          tabPanel(tabName = "glossary", "GLOSSARY",
                   suppressWarnings(
                     includeHTML(paste0('./www/Glossary/glossary_', uc, '.html'))
                   )
          ),
          
          # HowTo tab
          tabPanel(tabName = "howto", "GUIDE",
                   suppressWarnings(
                     includeHTML('./www/Guide/HowTo.html')
                   )
          )
        )
      )
    )
  )
}


# Function to create navbarMenu with tabPanel elements
create_navbarMenu <- function(tab_names) {
  
  # Create a list of tab panels using lapply
  tab_panels <- lapply(tab_names, create_tab_panel)
  
  # Use do.call to create the navbarMenu with the list of tab panels
  do.call(navbarMenu, c("Usecase", tab_panels))
}





blank2na = function(x,na.strings=c('','.','NA','na','N/A','n/a','<NA>','NaN','nan')) {
  if (is.factor(x)) {
    lab = attr(x, 'label', exact = T)
    labs1 <- attr(x, 'labels', exact = T)
    labs2 <- attr(x, 'value.labels', exact = T)
    
    # trimws will convert factor to character
    x = trimws(x,'both')
    if (! is.null(lab)) lab = trimws(lab,'both')
    if (! is.null(labs1)) labs1 = trimws(labs1,'both')
    if (! is.null(labs2)) labs2 = trimws(labs2,'both')
    
    if (!is.null(na.strings)) {
      # convert to NA
      x[x %in% na.strings] = NA
      # also remember to remove na.strings from value labels 
      labs1 = labs1[! labs1 %in% na.strings]
      labs2 = labs2[! labs2 %in% na.strings]
    }
    
    # the levels will be reset here
    x = factor(x)
    
    if (! is.null(lab)) attr(x, 'label') <- lab
    if (! is.null(labs1)) attr(x, 'labels') <- labs1
    if (! is.null(labs2)) attr(x, 'value.labels') <- labs2
  } else if (is.character(x)) {
    lab = attr(x, 'label', exact = T)
    labs1 <- attr(x, 'labels', exact = T)
    labs2 <- attr(x, 'value.labels', exact = T)
    
    # trimws will convert factor to character
    x = trimws(x,'both')
    if (! is.null(lab)) lab = trimws(lab,'both')
    if (! is.null(labs1)) labs1 = trimws(labs1,'both')
    if (! is.null(labs2)) labs2 = trimws(labs2,'both')
    
    if (!is.null(na.strings)) {
      # convert to NA
      x[x %in% na.strings] = NA
      # also remember to remove na.strings from value labels 
      labs1 = labs1[! labs1 %in% na.strings]
      labs2 = labs2[! labs2 %in% na.strings]
    }
    
    if (! is.null(lab)) attr(x, 'label') <- lab
    if (! is.null(labs1)) attr(x, 'labels') <- labs1
    if (! is.null(labs2)) attr(x, 'value.labels') <- labs2
  } else {
    x = x
  }
  return(x)
}





# Helper function to load and process data
load_and_process_data <- function(path_prefix, data_files, columns_to_rename = NULL, pattern_issues = NULL) {
  data_list <- lapply(data_files, function(file) {
    save_object(paste0("s3://rtbglr/", Sys.getenv("bucket_path"), file), 
                file = tempfile(fileext = ".csv")) %>%
      fread()
  })
  
  if (!is.null(columns_to_rename)) {
    data_list[[1]] <- data_list[[1]] %>%
      rename(!!!columns_to_rename) %>%
      mutate(Stage = "Validation") # for 'stage' filter purpose
  }
  
  return(list(
    raw_data = data_list[[1]],
    data_crop = data_list[[2]],
    pattern_issues = pattern_issues
  ))
}

# Helper function for generating UI elements
generate_ui_elements <- function(i, datacrop, rawdata) {
  list(
    stage_ui = renderUI({
      selectInput(
        paste0("stagefinder_", i),
        label = "Stage",
        multiple = FALSE,
        choices = c('Research', 'Validation', 'Piloting'),
        selected = "Validation"
      )
    }),
    experiment_ui = renderUI({
      req(input[[paste0("stagefinder_", i)]])
      stage <- input[[paste0("stagefinder_", i)]]
      
      experiment_choices <- if (stage == 'Research') {
        c('NOT', 'Variety Selection', 'Planting Date')
      } else if (stage == 'Validation') {
        c('Fertilizer Recommendation', 'Variety Selection', 'Planting Date', 'Intercropping')
      } else {
        c('Fertilizer Recommendation', 'Variety Selection', 'Planting Date')
      }
      
      selectInput(paste0("experimentfinder_", i), label = "Experiment", multiple = FALSE, 
                  choices =experiment_choices , selected = sort(unique(datacrop$Trial))[1])
    }),
    crop_ui = renderUI({
      selectInput(
        paste0("cropfinder_", i),
        label = "Crop",
        multiple = TRUE,
        choices = c("All", sort(unique(datacrop$Crop))),
        selected = "All"
      )
    }),
    date_ui = renderUI({
      dateRangeInput(paste0("datefinder_", i),
                     "Date",
                     start = min(na.omit(rawdata$today)),
                     end = Sys.time())
    }),
    enumerator_ui = renderUI({
      selectInput(paste0("enumeratorfinder_", i),
                  label = "Enumerator",
                  multiple = TRUE,
                  choices = c("All", sort(unique(datacrop$ENID))),
                  selected = "All")
    }),
    household_ui = renderUI({
      selectInput(paste0("householdfinder_", i),
                  label = "Household",
                  multiple = TRUE,
                  choices = c("All", sort(unique(na.omit(datacrop$HHID)))),
                  selected = "All")
    }),
    totals_ui = renderUI({
      infoBox("Total submissions", paste0(nrow(rawdata)), icon = icon("list"),
              color = "olive", width = "100%")
    }),
    country_ui = renderUI({
      infoBox("Country", HTML(paste(unique(na.omit(rawdata$Country)), collapse = ", ")), icon = icon("globe"),
              color = "olive", width = "100%")
    }),
    project_ui = renderUI({
      infoBox("Usecase", as.character(input$nav), icon = icon("barcode"),
              color = "olive", width = "100%")
    })
  )
}
