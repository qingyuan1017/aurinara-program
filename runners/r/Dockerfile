FROM rocker/r-ver:4.5.1

RUN groupadd --system runner && useradd --system --gid runner --uid 10001 runner
WORKDIR /workspace
USER 10001:10001

ENTRYPOINT ["Rscript", "--vanilla"]
