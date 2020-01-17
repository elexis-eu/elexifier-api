# Elexifier api

## Requirements
 - python 3

## Stack
 - Flask
 - Postgres
 - Docker

## Getting started

### Local development
Docker and docker-compose are required to run the container locally. Database is running inside a Docker container.

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

### Database migration
When models are changed locally, migrations must be run.

When done updating models, follow migration process below:
1. `$ docker exec -it elexifier_flask_1 /bin/bash`<br>
Will attach your terminal to docker container. When attached to the container you are able to detect and run migrations.
2. `$ python manage.py db migrate -m "<short_descriptive_name>"`<br>
Will compare migrations and generate an new migrations file, which contains queries used for database update.
2. `$ python manage.py db upgrade`<br>
Will upgrade the database according to the new migrations file.

Commit the **CORRECT** migration file to version control with a descriptive message, as it will be used to migrate the databases on staging and production.
___


## [DEPRECATED]
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
