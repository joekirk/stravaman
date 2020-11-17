#Stravaman


Create Virtualenv
=================

```
$ cd /path/to/stravaman
$ python3 -m venv env
$ source env/bin/activate
(env) $ pip install -r requirements.txt && python setup.py develop
```

Create a Config File
====================

Create a config file for example `settings.cfg`:

```
(env) $ vi settings.cfg
```
The config file must contain your strava client id, strava client secret and a secret of your own making to authenticate
the activity-data endpoint

```python
STRAVA_CLIENT_ID=123
STRAVA_CLIENT_SECRET='deadbeefdeadbeefdeadbeef'
SECRET
```

Run Server
==========

Run the Flask server, specifying the path to this file in your `APP_SETTINGS`
environment var:

```
(env) $ APP_SETTINGS=settings.cfg python main.py
```

Deployment
==========

To deploy the app to google cloud

```
(env) $ gcloud deploy app
```

To deploy the cron jobs to google cloud

```
(env) $ gcloud deploy app cron.yaml
```

