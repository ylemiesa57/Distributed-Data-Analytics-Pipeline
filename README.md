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


# Distributed Data Analytics Pipeline

This project demonstrates a scalable, real-time data analytics pipeline that ingests social media comments from the Reddit API, processes them using Apache Spark, and stores the results in AWS S3 for downstream analysis.

The core objective is to perform real-time trend identification (e.g., sentiment analysis) on a high-volume stream of data.

---

### 🏛️ Architecture

> **Status:** Only the ingestion stage (`reddit_producer.py`) and the
> Kafka/Zookeeper/Spark infrastructure (`docker-compose.yml`) are
> implemented in this repo right now. The processing (Spark job),
> S3 storage, and SQL analysis pieces described below are the target
> design for this project and are not yet built -- there is currently
> no `src/processing/`, `src/cpp_module/`, or `sql/` in this repo.

The pipeline follows a standard streaming architecture:

1.  **Ingestion**: A Python script (`reddit_producer.py`) connects to the Reddit API, fetches a live stream of comments, and publishes them as messages to an Apache Kafka topic.
2.  **Streaming & Processing**: An Apache Spark Structured Streaming job (`spark_streaming_analysis.py`) subscribes to the Kafka topic. For each message, it performs:
    * Data cleaning and transformation.
    * A sentiment analysis UDF to classify the comment's tone.
    * Aggregation of results into 1-minute windows.
3.  **Storage**: The processed and aggregated data is continuously written to an **AWS S3** bucket in the efficient Parquet format.
4.  **Analysis**: The data stored in S3 can be queried using tools like AWS Athena or Spark SQL to generate reports (as seen in the `/sql` directory).

---

### 🛠️ Tech Stack

* **Data Streaming**: Apache Kafka
* **Data Processing**: Apache Spark
* **Programming**: Python, SQL, C++ (for a high-performance text cleaning module)
* **Infrastructure**: Docker, AWS S3

---

### 🚀 How to Run

1.  **Prerequisites**:
    * Docker and Docker Compose
    * AWS Account with an S3 bucket and credentials configured
    * Reddit API credentials

2.  **Build the C++ Module** *(not yet implemented -- `src/cpp_module/`
    doesn't exist in this repo yet; skip this step for now)*:
    ```bash
    pip install pybind11
    cd src/cpp_module
    python setup.py install
    ```

3.  **Start the Infrastructure**:
    This command will start Kafka, Zookeeper, and a Spark cluster.
    ```bash
    docker-compose up -d
    ```

4.  **Run the Pipeline**:
    * Start the data ingestion from Reddit:
        ```bash
        python reddit_producer.py
        ```
        (Note: the layout diagram above describes the target
        `src/ingestion/...` structure; `reddit_producer.py` currently
        lives at the repo root, so run it from there until the
        `src/` reorg lands.)
    * Submit the Spark processing job *(not yet implemented --
      `src/processing/spark_streaming_analysis.py` doesn't exist in
      this repo yet, so this command won't work as-is)*:
        ```bash
        # (Command to submit spark job, see official docs)
        spark-submit --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.3.0 src/processing/spark_streaming_analysis.py
        ```
