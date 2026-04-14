# Data Collection and Monitoring Tool (DCMT) re-design

This document outlines the decisions made to redesign the new architecture of the DCMT.

## High-Level Architecture
The goal is to move from a monolithic R Shiny application to a decoupled service-oriented architecture.

### Phase 1: Directory Separation (Current)
- **Backend (`/pipeline`):** R scripts (`okapi.R`, `processing.R`) focused on ETL.
- **Frontend (`/app`):** R Shiny focused on UI/UX and visualization.
- **Communication:** Shared Cloud Storage (Azure Blob/S3) via CSV/Parquet files.

### Phase 2: Python Migration (Proposed)
- **ETL Engine:** Transition from `dplyr` to **Polars** for high-performance data manipulation.
- **Logic:** Encapsulate country-specific logic (Rwanda, KLARRO, etc.) into Python modules.

### Phase 3: API Integration
- **Backend Service:** **FastAPI** to serve processed data via REST endpoints.
- **Data Validation:** Use Pydantic models to enforce data integrity.
- **Frontend:** Shiny (or future JS framework) consumes data via HTTP requests instead of direct file access.

## Technology Stack Decisions

| Component | Current Tech | Target Tech |
| :--- | :--- | :--- |
| Data Ingestion | R (okapi) | Python (httpx/requests) |
| Data Processing | R (dplyr/tidyr) | Python (Polars) |
| API Layer | None (File-based) | FastAPI |
| Frontend | R Shiny | R Shiny (Consumer) |
| Orchestration | Cron in Docker | Docker Compose / Airflow |

## Benefits
1. **Decoupling:** Frontend changes won't break data processing logic.
2. **Scalability:** Polars handles larger datasets more efficiently.
3. **Interoperability:** The API can support mobile apps or other dashboards in the future.

## Structure
```
./dcmt/
├── back/             # The "Backend"
│   ├── okapi.R           # Data Access Layer
│   ├── dataprocessing.R  # Transformation logic
│   ├── clean_utils.R     # Data cleaning (e.g., blank2na)
│   └── run_etl.R         # Entry point for CRON
├── front/                  # The "Frontend"
│   ├── ui.R              # Shiny UI
│   ├── server.R          # Shiny Server
│   ├── ui_helpers.R      # UI Builders (extracted from support_fun.R)
│   ├── app_utils.R       # App-specific logic (load_data, themes)
│   ├── www/
│   │   └── style.css     # UI Assets
│   └── auth0.R           # Auth logic
├── .Renviron             # Shared Secrets
└── docker-compose.yml    # Orchestrates both
```

## Considerations and alerts

⚠️ Need to do cleaning and delete old use cases
- 🧹 KALRO use case need to be removed.
- 🚫 Solidaridad is non standard
- 🚮 BioSSA is broken

### Analysis of `support_fun.R`
Here is how the functions in that script should be distributed:
1. Frontend (App) Only:
- jscode: Pure JavaScript for the Shiny UI.
- basemap_future: Leaflet map initialization.
create_tab_panel & create_navbarMenu: These are massive UI builders. They define the layout of the dashboard.
- them2: A ggplot2 theme for visualizations.
- get_user_country: Runtime IP tracking for users visiting the app.
- load_data: This is the Data Consumer. It belongs in the app because it fetches the processed files from Azure to display them.
2. ~~Backend (Pipeline) Only:~~
- ~~blank2na: This is a data cleaning utility. It should be used during your ETL process in dataprocessing.R to ensure consistent data quality before the app ever sees it.~~
3. The "Shared" Problem:
- usecases.index: Both the backend (to know which files to generate) and the frontend (to know which tabs to build) need this list.
- dynamic_colorcodeS: This contains Business Logic (calculating if an event is "Overdue" or "Missing"). In a decoupled architecture, the backend should ideally calculate a status column, and the frontend should simply map that status to a color.