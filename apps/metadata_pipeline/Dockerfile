FROM thepsalmist/mc_pipeline_common:v1

COPY src /app/src
COPY plumbing.json /app/plumbing.json
COPY supervisord.conf /app/supervisord.conf
COPY run.sh /app/run.sh


RUN chmod +x run.sh
