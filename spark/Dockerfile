FROM apache/spark:3.5.1
USER root
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/jobs

# Pre-fetch the jars Spark needs for s3a + Postgres so we don't pull them
# every run.
RUN mkdir -p /opt/jars && \
    curl -sSL -o /opt/jars/hadoop-aws-3.3.4.jar \
       https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/3.3.4/hadoop-aws-3.3.4.jar && \
    curl -sSL -o /opt/jars/aws-java-sdk-bundle-1.12.262.jar \
       https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-bundle/1.12.262/aws-java-sdk-bundle-1.12.262.jar && \
    curl -sSL -o /opt/jars/postgresql-42.7.3.jar \
       https://repo1.maven.org/maven2/org/postgresql/postgresql/42.7.3/postgresql-42.7.3.jar && \
    cp /opt/jars/*.jar /opt/spark/jars/

RUN pip install --no-cache-dir psycopg2-binary==2.9.9

COPY jobs/ /opt/jobs/

ENV PATH=/opt/spark/bin:$PATH
CMD ["/opt/spark/bin/spark-submit", "--master", "local[*]", "/opt/jobs/curate.py"]
