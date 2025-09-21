# Distributed-Data-Analytics-Pipeline
apache spark project

distributed-data-pipeline/
├── .gitignore
├── README.md
├── docker-compose.yml
├── requirements.txt
├── src/
│   ├── ingestion/
│   │   └── reddit_producer.py
│   ├── processing/
│   │   └── spark_streaming_analysis.py
│   └── cpp_module/
│       ├── text_cleaner.cpp
│       ├── CMakeLists.txt
│       └── setup.py
└── sql/
    ├── create_results_table.sql
    └── daily_trend_report.sql
