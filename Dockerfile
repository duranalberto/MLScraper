FROM    python:3.10.8-slim-buster
LABEL   maintainer="Alberto Duran"

ENV     INSTALL_PATH /MLScraper
ENV     REQUIEREMENTS requirements.txt
WORKDIR ${INSTALL_PATH}

COPY    requirements.txt ${REQUIEREMENTS}
RUN     pip install -r ${REQUIEREMENTS}

COPY    . .

EXPOSE  80

CMD     python app.py