#The base image for the container 
FROM    python:3.10.8-slim-buster
 
# Keeps Python from generating .pyc files in the container 
ENV     PYTHONDONTWRITEBYTECODE=1
RUN     apt-get update && \
        apt-get install -yq tzdata && \
        ln -fs /usr/share/zoneinfo/America/Mexico_City /etc/localtime && \
        dpkg-reconfigure -f noninteractive tzdata

ENV     TZ="America/Mexico_City"
 
# Turns off buffering for easier container logging 
ENV     PYTHONUNBUFFERED=1 
 
RUN     apt -y update
RUN     apt -y install git
RUN     git config --global user.name "Azlbert"
RUN     git config --global user.email agzlbert@gmail.com

# Copy python requirements to the docker container and install
COPY    ../requirements.txt .
RUN     python -m pip install -r requirements.txt
