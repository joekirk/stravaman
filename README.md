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

Follow installation instructions for gcloud: [https://cloud.google.com/sdk/docs/install#linux]

Create a new application: [https://console.cloud.google.com/]

Login to your account

```
(env) $ gcloud auth login 
```

```
(env) $ gcloud config set project PROJECT_ID 
```

```
(env) $ gcloud app deploy 
```

To deploy the cron jobs to google cloud

```
(env) $ gcloud deploy app cron.yaml
```
