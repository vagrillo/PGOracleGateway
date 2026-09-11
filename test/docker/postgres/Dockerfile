FROM postgres:17

# orafce: Oracle-compatible functions/packages (NVL, DECODE, dbms_output, ...)
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-17-orafce \
    && rm -rf /var/lib/apt/lists/*

COPY 01_init.sql /docker-entrypoint-initdb.d/
