# Elexifier api

## Requirements
 - python 3

## Stack
 - Flask
 - Postgres
 - Sqlite
 - Docker

## Getting started

### Local development
Docker and docker-compose are required to run the container locally.

1. Copy properties from `.example.env` file to a `.env` file and fill with desired values.<br>
`$ cat .example.env >> .env`

Docker volume is bound to your local development repository and changing files will result in reloaded python application.

##### Building image
`$ docker-compose -f docker-compose.yml -p elexifier build`

##### Starting container
`$ docker-compose -f docker-compose.yml -p elexifier up`

Optionally add `-d` to the command above to keep it running in the background.

Run `$ docker logs -f elexifier_flask_1` to attach to the container and view logs.

Development server will be running on http://localhost:5000/.
___

Run the following script from the root folder. 
It will install all of the environment dependencies required to run the project on your computer.
```
/bin/bash ./.scripts/install_environment.sh
```

<small>If something goes wrong, check the [local installation](https://github.com/vidrepar/elexifier-api/issues/16).</small>

After the local installation, run the local server:

```
python run.py
```

Server is running on: http://0.0.0.0:8081

## Docker
Check these [instructions](https://github.com/vidrepar/elexifier-api/issues/17).

## Changing the database
First change the models.py folder. After that, run:

```
python manage.py db migrate
`````
```
python manage.py db upgrade
```

Sqlite3 does not support the DROP statement for deleting database columns, therefore use this hack when removing a column:  https://www.youtube.com/watch?v=CxCK1DkikgA







