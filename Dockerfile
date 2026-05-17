FROM    python:3.14.5-slim
LABEL   maintainer="Alberto Duran"

ENV     INSTALL_PATH /MLScraper
ENV     REQUIREMENTS_FILE requirements.txt
WORKDIR ${INSTALL_PATH}

COPY    requirements.txt ${REQUIREMENTS_FILE}
RUN     pip install -r ${REQUIREMENTS_FILE}
RUN     python -m playwright install --with-deps chromium

COPY    . .

VOLUME ["/MLScraper/data"]

EXPOSE  80
EXPOSE  443

CMD ["python3", "app.py"]
