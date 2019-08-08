# Elexifier #

## Installation, documentation ##

Python 3 is needed. These instructions are for linux.<br/>
Clone the project from the repository.<br/>
Go inside the folder:

<code>cd elexifier</code><br/>

Make a media folder for xml files:

<code>mkdir media</code><br/>

Install python virtual environment if you don't have it yet:

<code>pip install virtualenv</code><br/>

Create virtual environment:

<code>virtualenv venv</code><br/>

Warning: If python 3 is not your default python and if you also have python 2 installed, you also have to specify the path to the python 3 binary in the above command, for example, on linux with python3.5 installed, the command would be:

<code>virtualenv -p /usr/bin/python3.5 venv</code><br/>

Activate virtual environment:

<code>source venv/bin/activate</code><br/>

Install dependencies: 

<code>pip install -r requirements.txt</code><br/>

Create the sqlite database and migrate the models into it: 

<code>python manage.py db init</code><br/>
<code>python manage.py db migrate</code><br/>
<code>python manage.py db upgrade</code><br/>

Create a user so you can log in:

<code>python create_user.py</code><br/>

Run the local server:

<code>python server.py</code><br/>

Go to url:

http://0.0.0.0:8081<br/>

Warning: The backend is still buggy so changes will be made to it. If after some new commit the server starts crashing, the easiest way to fix it is to just delete the database (app.db file in the elexifier folder) and the generated migrations folder. Than repeat these four steps:

<code>python manage.py db init</code><br/>
<code>python manage.py db migrate</code><br/>
<code>python manage.py db upgrade</code><br/>
<code>python create_user.py</code><br/>

If you still can't make this work, send me an email: matejmart@gmail.com







