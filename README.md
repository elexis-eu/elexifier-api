# Elexifier #

## Installation, documentation ##

#Local installation#

Python 3 is needed. These instructions are for linux.<br/>
Clone the project from the repository.<br/>
Go inside the folder:

<code>cd elexifier-api</code><br/>

Install python virtual environment if you don't have it yet:

<code>pip install virtualenv</code><br/>

Create virtual environment:

<code>virtualenv venv</code><br/>

Warning: If python 3 is not your default python and if you also have python 2 installed, you also have to specify the path to the python 3 binary in the above command, for example, on linux with python3.5 installed, the command would be:

<code>virtualenv -p /usr/bin/python3.5 venv</code><br/>

OSX:

```
virtualenv -p /usr/local/bin/python3.5 venv
```

Activate virtual environment:

<code>source venv/bin/activate</code><br/>

Install dependencies: 

<code>pip install -r requirements.txt</code><br/>

If the command fails for OSX users because of `psycopg2` package, then run the following command to install the missing package (nd then run the install command for requirements.txt again):<br/>
<code>env LDFLAGS="-I/usr/local/opt/openssl/include -L/usr/local/opt/openssl/lib" pip install psycopg2</code>

Create the sqlite database and migrate the models into it: 

<code>python manage.py db init</code><br/>
<code>python manage.py db migrate</code><br/>
<code>python manage.py db upgrade</code><br/>

OSX:
If you get: 
```
ImportError: Unable to find magic library
```
install and run db commands again:
```
brew link libmagic
```

Create a user so you can log in:

<code>python create_user.py</code><br/>

Run the local server:

<code>python run.py</code><br/>

Go to url:

http://0.0.0.0:8081<br/>

Warning: The backend is still buggy so changes will be made to it. If after some new commit the server starts crashing, the easiest way to fix it is to just delete the database (app.db file in the elexifier folder) and the generated migrations folder. Than repeat these four steps:

<code>python manage.py db init</code><br/>
<code>python manage.py db migrate</code><br/>
<code>python manage.py db upgrade</code><br/>
<code>python create_user.py</code><br/>


#Docker installation#

You need docker and docker compose (https://docs.docker.com/compose/install/)

If you want just the flask docker, write:

<code>docker build -t flask .</code><br/>
<code>docker run -d -p 8080:8080 --name=flask flask</code><br/>

The app becomes available at localhost:8080.

If nginx is neeeded, or for development, run:

<code>docker-compose build</code><br/>
<code>docker-compose up</code><br/>


The app is fed through nginx at localhost:8001.

On docker, the user is generated automatically:

User: user
Pass: user

If you still can't make this work, send me an email: matejmart@gmail.com







