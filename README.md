# Elexifier api

## Requirements
 - python 3

## Stack
 - Flask
 - Postgres
 - Sqlite
 - Docker

## Getting started

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

## Warning 
The backend is still buggy so changes will be made to it. 
If after some new commit the server starts crashing, 
the easiest way to fix it is to just delete the database 
(app.db file in the elexifier folder) and the generated migrations folder. 
Then repeat these four steps:

```
python manage.py db init
```
```
python manage.py db migrate
`````
```
python manage.py db upgrade
```
```
python create_user.py
````







