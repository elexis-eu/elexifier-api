#!/bin/bash
app="docker.test"
docker build -t flask .
docker run -d -p 80:8000 --name="flask" -v $PWD:/app "flask"