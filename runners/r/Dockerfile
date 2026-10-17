FROM rocker/r-ver:4.5.1@sha256:03b023fbf7b1b24ac1bb8b2ac5fd7e15a767e67b40ff50c155e328110981c2aa

# Keep the workarea runtime reproducible. jsonlite is required by generated
# Analysis IR programs; tidyr and its pinned-snapshot dependencies are the
# supported tabular toolkit for manually authored R workareas.
ARG R_REPOSITORY=https://packagemanager.posit.co/cran/__linux__/noble/2026-10-15
RUN install2.r --error --skipinstalled --repos "${R_REPOSITORY}" jsonlite tidyr \
    && Rscript --vanilla -e \
      'stopifnot(requireNamespace("jsonlite", quietly=TRUE), requireNamespace("tidyr", quietly=TRUE))'

RUN groupadd --system runner && useradd --system --gid runner --uid 10001 runner
COPY --chmod=0555 runners/run-program.sh /runner/run-program.sh
WORKDIR /workspace
USER 10001:10001

ENTRYPOINT ["/runner/run-program.sh", "r"]
