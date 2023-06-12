#!flask/bin/python
import pandas as pd

from collections import defaultdict, namedtuple
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
initialize_app(cred, {'projectId': app.config['GCLOUD_APP_ID']})

LOG = getLogger(__name__)

ATHLETE_TOKENS = 'tokens'
ACTIVITIES = 'activities'
ACTIVITIES_SUMMARY = 'activities_summary'
PROFILE = 'profile'
STRAVA = 'strava'
ATHLETES = 'athletes'


Activity = namedtuple(
    'Activity',
    ('athlete_id', 'firstname', 'lastname', 'team', 'type', 'distance', 'elapsed_time', 'timestamp')
)


@app.route("/token_refresh")
def refresh_all_tokens():
    LOG.info("Refreshing all access tokens")
    db = firestore.client()
    client = Client()
    for athlete in db.collection(STRAVA).document(ATHLETES).collections():
        try:
            doc_ref = db.collection(STRAVA).document(ATHLETES).collection(athlete.id).document(ATHLETE_TOKENS)
            record = doc_ref.get()
            refresh_response = client.refresh_access_token(
                client_id=app.config['STRAVA_CLIENT_ID'],
                client_secret=app.config['STRAVA_CLIENT_SECRET'],
                refresh_token=record.get('refresh_token'))
            doc_ref.update({
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

    query_count = 0
    LOG.info(f"Starting strava query. Start date {after} , Batch Size {batch_size}")
    for athlete in db.collection(STRAVA).document(ATHLETES).collections():

        if query_count == batch_size:
            LOG.info("Batch limit reached")
            break
        try:
            token = db.collection(STRAVA).document(ATHLETES).collection(athlete.id).document(ATHLETE_TOKENS).get()
            client = Client(access_token=token.get('access_token'))

            profile_doc_ref = db.collection(STRAVA).document(ATHLETES).collection(athlete.id).document(PROFILE)
            profile = profile_doc_ref.get()

            athlete_ref = db.collection(STRAVA).document(ATHLETES).collection(athlete.id)

            try:
                last_update = dt.strptime(profile.get('update_date'), "%Y-%m-%d").date()
            except (KeyError, TypeError):
                last_update = None

            if last_update and last_update == dt.today().date():
                LOG.info(f"No update required for athlete {profile.get('firstname')} {profile.get('lastname')}")
                continue

            query_count += 1
            LOG.info(f"Requesting activity data for {profile.get('firstname')} {profile.get('lastname')}")
            try:
                activities = client.get_activities(after=after)
                update_athlete_activities(activities, athlete_ref)
            except Exception:
                LOG.error(f"Error occurred processing data from strava for athlete {athlete.id}. Setting to zero.")
                reset_athlete_activities(athlete_ref)
            finally:
                profile_doc_ref.update({
                    'update_date': dt.today().strftime("%Y-%m-%d")
                })
        except Exception as e:
            LOG.exception(f"Failed to create request for athlete {athlete.id}")

    status_code = Response(status=200)
    return status_code


def update_athlete_activities(activities, athlete_ref):
    athlete_summary = defaultdict(float)
    summary = athlete_ref.document(ACTIVITIES_SUMMARY)
    for activity in activities:
        details = athlete_ref.document(ACTIVITIES).collection(activity.type).document(activity.start_date.isoformat())
        distance = activity.distance.num
        time = activity.elapsed_time.total_seconds()
        data = {
           'distance': distance,
           'elapsed_time': time
        }
        details.set(data)

        if distance == 0 and time != 0:
            athlete_summary[activity.type] += time
        else:
            athlete_summary[activity.type] += distance

    summary.set(athlete_summary)


def reset_athlete_activities(athlete_ref):
    summary = athlete_ref.document(ACTIVITIES_SUMMARY)
    activities = athlete_ref.document(ACTIVITIES).collections()
    for type in activities:
        activity_list = type.list_documents()
        for activity in activity_list:
            activity.delete()
    summary.set({})

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
    activity_data = defaultdict(defaultdict)
    for athlete in db.collection(STRAVA).document(ATHLETES).collections():
        try:
            athlete_summary = db.collection(STRAVA).document(ATHLETES).collection(athlete.id).document(ACTIVITIES_SUMMARY).get().to_dict()
            if not athlete_summary:
                athlete_summary = {}

            profile = db.collection(STRAVA).document(ATHLETES).collection(athlete.id).document(PROFILE).get()
            team = profile.get('team')
            if team:
                firstname = profile.get('firstname')
                lastname = profile.get('lastname')
                athlete_summary.update({'team': team, 'firstname': firstname, 'lastname': lastname})
                activity_data[team][athlete.id] = athlete_summary
            else:
                raise RuntimeError("Cannot find team")
        except Exception as e:
            LOG.exception(f"Can't create summary for athlete {athlete.id}")
    return jsonify(activity_data)


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
        doc_ref = db.collection(STRAVA).document(ATHLETES).collection(str(athleteid)).document(PROFILE)
        doc_ref.update({
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
            profile_doc_ref = db.collection(STRAVA).document(ATHLETES).collection(str(strava_athlete.id)).document(PROFILE)
            profile_doc_ref.set({
                'firstname': strava_athlete.firstname,
                'lastname': strava_athlete.lastname,
                'update_date': dt.today().strftime("%Y-%m-%d")
            })
            token_doc_ref = db.collection(STRAVA).document(ATHLETES).collection(str(strava_athlete.id)).document(ATHLETE_TOKENS)
            token_doc_ref.set({
                'access_token': access_token["access_token"],
                'refresh_token': access_token["refresh_token"],
                'expires': access_token["expires_at"],
                'scope': scope
            })

            return redirect(url_for('team', athleteid=str(strava_athlete.id)))
        except Exception as e:
            return render_template('login_error.html', error=f"{e} [Exception in parsing response]")


@app.route("/whodoneit/<route>/<place>/<distance>")
def whodoneit(route, place, distance):
    distance = float(distance)
    db = firestore.client()

    # first check whether out not we've looked this one up
    threshold_activity_doc_ref = db.collection(route).document(place)
    threshold_activity = threshold_activity_doc_ref.get().to_dict()
    if not threshold_activity:
        threshold_activity = calculate_threshold_activity(distance, db)
        threshold_activity_doc_ref.set(threshold_activity)

    return jsonify(threshold_activity)


def calculate_threshold_activity(distance, db):
    all_activity_data = []
    for athlete in db.collection(STRAVA).document(ATHLETES).collections():
        activities_doc_ref = db.collection(STRAVA).document(ATHLETES).collection(athlete.id).document(ACTIVITIES)
        activities = activities_doc_ref.collections()
        profile = db.collection(STRAVA).document(ATHLETES).collection(athlete.id).document(PROFILE).get().to_dict()
        for type in activities:
            for activity in type.list_documents():
                data = Activity(
                    athlete.id,
                    profile.get('firstname'),
                    profile.get('lastname'),
                    profile.get('team', None),
                    type.id,
                    activity.get().get('distance'),
                    activity.get().get('elapsed_time'),
                    activity.id
                )
                all_activity_data.append(data)

    def _adjust(distance, time):
        if distance == 0:
            # Equate 1 hr of activity to 10km travelled
            return (time / 60) / 6
        else:
            # distance to km
            return distance / 1000



    df = pd.DataFrame(data=all_activity_data)
    if df.empty:
        return {}

    df = df.sort_values(by='timestamp')
    df['adjusted_distance'] = df.apply(lambda x: _adjust(x['distance'], x['elapsed_time']), axis=1)
    df['accumulated_distance'] = df['adjusted_distance'].cumsum()
    activities_above_threshold = df[df.accumulated_distance >= distance]

    if activities_above_threshold.empty:
        threshold = {}
    else:
        threshold = activities_above_threshold.iloc[0].to_dict()

    return threshold

@app.route("/success")
def success():
    return render_template('login_results.html')


if __name__ == '__main__':
    basicConfig(level=INFO)
    LOG.info("Starting stravaman")
    app.run(debug=True)

