FROM    python:3.14.2-slim
LABEL   maintainer="Alberto Duran"

ENV     INSTALL_PATH /MLScraper
ENV     REQUIEREMENTS requirements.txt
WORKDIR ${INSTALL_PATH}

COPY    requirements.txt ${REQUIEREMENTS}
RUN     pip install -r ${REQUIEREMENTS}

COPY    . .

# Declare data volume so price history survives container rebuilds (Phase 3 fix)
# Uncomment when ready: VOLUME ["/MLScraper/data"]

EXPOSE  80
EXPOSE  443

# FIX 1: original CMD referenced a Python binary version that does not exist
# in the python:3.14.2-slim base image; the container exited immediately.
CMD ["python3", "app.py"]