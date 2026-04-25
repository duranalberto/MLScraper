FROM    python:3.14.2-slim
LABEL   maintainer="Alberto Duran"

ENV     INSTALL_PATH /MLScraper
ENV     REQUIEREMENTS requirements.txt
WORKDIR ${INSTALL_PATH}

COPY    requirements.txt ${REQUIEREMENTS}
RUN     pip install -r ${REQUIEREMENTS}

COPY    . .

VOLUME ["/MLScraper/data"]

EXPOSE  80
EXPOSE  443

CMD ["python3", "app.py"]