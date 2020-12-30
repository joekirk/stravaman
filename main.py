#!flask/bin/python
from collections import defaultdict
from logging import basicConfig, getLogger, INFO
from datetime import datetime as dt
from firebase_admin import credentials, firestore, initialize_app
from flask import Flask, render_template, redirect, url_for, request, jsonify, Response
from stravalib import Client
from functools import wraps
from flask import abort

app = Flask(__name__)
app.config.from_envvar('APP_SETTINGS')

cred = credentials.ApplicationDefault()
initialize_app(cred, {'projectId': 'strava-man'})

LOG = getLogger(__name__)

ATHLETE_TOKENS = 'tokens'
ATHLETE_ACTIVITY_SUMMARY = 'activity_summary'
ATHLETE_TEAM = 'team'


@app.route("/token_refresh")
def refresh_all_tokens():
    LOG.info("Refreshing all access tokens")
    db = firestore.client()
    athlete_tokens = db.collection(ATHLETE_TOKENS).list_documents()
    client = Client()
    for athlete in athlete_tokens:
        try:
            doc_ref = db.collection(ATHLETE_TOKENS).document(athlete.id)
            record = doc_ref.get()
            refresh_response = client.refresh_access_token(
                client_id=app.config['STRAVA_CLIENT_ID'],
                client_secret=app.config['STRAVA_CLIENT_SECRET'],
                refresh_token=record.get('refresh_token'))
            doc_ref.update({
                'firstname': record.get('firstname'),
                'lastname': record.get('lastname'),
                'access_token': refresh_response["access_token"],
                'refresh_token': refresh_response["refresh_token"],
                'expires': refresh_response["expires_at"]
            })
        except Exception as e:
            LOG.error(f"Could not refresh token for athlete {athlete.id}")
    LOG.info("Finished refreshing tokens")
    status_code = Response(status=200)
    return status_code


@app.route("/strava_data/<date>/<batch>")
def get_strava_data(date, batch):

    try:
        after = dt.strptime(date, '%Y-%m-%d')
        batch_size = int(batch)
    except Exception:
        return Response(status=400)

    db = firestore.client()
    athlete_tokens = db.collection(ATHLETE_TOKENS).list_documents()

    query_count = 0
    LOG.info(f"Starting strava query. Start date {after} , Batch Size {batch_size}")

    for athlete in athlete_tokens:

        if query_count == batch_size:
            LOG.info("Batch limit reached")
            break
        try:
            doc_ref = db.collection(ATHLETE_TOKENS).document(athlete.id)
            token_record = doc_ref.get()
            client = Client(access_token=token_record.get('access_token'))

            summary_doc = db.collection(ATHLETE_ACTIVITY_SUMMARY).document(athlete.id)
            summary_record = summary_doc.get()

            try:
                last_update = dt.strptime(summary_record.get('update_date'), "%Y-%m-%d").date()
            except (KeyError, TypeError):
                last_update = None

            if last_update and last_update == dt.today().date():
                LOG.info(f"No update required for athlete {token_record.get('firstname')} {token_record.get('lastname')}")
                continue

            query_count += 1
            LOG.info(f"Requesting activity data for {token_record.get('firstname')} {token_record.get('lastname')}")
            athlete_summary = defaultdict(float)
            try:
                activities = client.get_activities(after=after)
                athlete_summary = create_athlete_summary(activities)
            except Exception:
                LOG.error(f"Could not get data from strava for athlete {athlete.id}, setting to zero")
            finally:
                athlete_summary['firstname'] = token_record.get('firstname')
                athlete_summary['lastname'] = token_record.get('lastname')
                athlete_summary['update_date'] = dt.today().strftime("%Y-%m-%d")
                summary_doc.set(athlete_summary)
        except Exception as e:
            LOG.exception(f"Failed to create request for athlete {athlete.id}")

    status_code = Response(status=200)
    return status_code


def create_athlete_summary(activities):
    activity_summary = defaultdict(float)
    for activity in activities:
        if activity.type in ('Workout', 'Yoga'):
            activity_summary[activity.type] += activity.elapsed_time.total_seconds()
        else:
            activity_summary[activity.type] += activity.distance.num
    return activity_summary


def authorize(f):
    @wraps(f)
    def decorated_function(*args, **kws):
        if not 'Authorization' in request.headers:
           abort(401)

        data = request.headers['Authorization']
        token = str.replace(str(data), 'Bearer ','')
        if token != app.config['SECRET']:
            abort(401)

        return f(*args, **kws)
    return decorated_function


@app.route("/activity-data")
@authorize
def activity_data():
    db = firestore.client()
    activities = db.collection(ATHLETE_ACTIVITY_SUMMARY).list_documents()
    activity_summary = defaultdict(defaultdict)

    for athlete in activities:
        try:
            activity = db.collection(ATHLETE_ACTIVITY_SUMMARY).document(athlete.id).get().to_dict()
            team = db.collection(ATHLETE_TEAM).document(athlete.id).get().get('team')

            if team:
                activity.update({'team': team})
                activity_summary[team][athlete.id] = activity
            else:
                raise RuntimeError("Cannot find team")
        except Exception as e:
            LOG.exception(f"Can't create summary for athlete {athlete.id}")
    return jsonify(activity_summary)


@app.route("/")
def login():
    c = Client()
    url = c.authorization_url(client_id=app.config['STRAVA_CLIENT_ID'],
                              redirect_uri=url_for('.logged_in', _external=True),
                              approval_prompt='auto',
                              scope=['read', 'activity:read'])

    return render_template('login.html', authorize_url=url)


@app.route('/team/<athleteid>')
def team(athleteid):
    return render_template('register_team.html', athleteid=athleteid)


@app.route('/register-team', methods=['POST'])
def register_team():
    try:
        team = request.form['team']
        athleteid = request.form['athleteid']
        db = firestore.client()
        doc_ref = db.collection(ATHLETE_TEAM).document(str(athleteid))
        doc_ref.set({
            'team': team
        })
    except Exception as e:
        return render_template('login_error.html', error=e)

    return redirect(url_for('success'))


@app.route("/strava-oauth")
def logged_in():
    """
    Method called by Strava (redirect) that includes parameters.
    - state
    - code
    - error
    """
    error = request.args.get('error')
    scope = request.args.get('scope')
    if error:
        return render_template('login_error.html', error=error)
    else:
        try:
            code = request.args.get('code')
            client = Client()
            access_token = client.exchange_code_for_token(client_id=app.config['STRAVA_CLIENT_ID'],
                                                          client_secret=app.config['STRAVA_CLIENT_SECRET'],
                                                          code=code)
            strava_athlete = client.get_athlete()
            db = firestore.client()
            doc_ref = db.collection(ATHLETE_TOKENS).document(str(strava_athlete.id))
            doc_ref.set({
                'firstname': strava_athlete.firstname,
                'lastname': strava_athlete.lastname,
                'access_token': access_token["access_token"],
                'refresh_token': access_token["refresh_token"],
                'expires': access_token["expires_at"],
                'scope': scope
            })
            return redirect(url_for('team', athleteid=str(strava_athlete.id)))
        except Exception as e:
            return render_template('login_error.html', error=e)

@app.route("/success")
def success():
    return render_template('login_results.html')


if __name__ == '__main__':
    basicConfig(level=INFO)
    LOG.info("Starting stravaman")
    app.run(debug=True)

