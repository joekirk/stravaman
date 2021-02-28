#!flask/bin/python
from firebase_admin import credentials, firestore, initialize_app

cred = credentials.ApplicationDefault()
initialize_app(cred, {'projectId': 'strava-man'})


ATHLETE_TOKENS = 'tokens'
ATHLETE_ACTIVITY_SUMMARY = 'activity_summary'
ATHLETE_TEAM = 'team'
ATHLETE_ACTIVITY_LIST = 'athlete_activity_list'
STRAVA  = 'strava'
ATHLETES = 'athletes'

if __name__ == "__main__":
    db = firestore.client()
    athlete_tokens = db.collection(ATHLETE_TOKENS).list_documents()
    for athlete in athlete_tokens:
        record = db.collection(ATHLETE_TOKENS).document(athlete.id).get()
        token_ref = db.collection(STRAVA).document(ATHLETES).collection(athlete.id).document('tokens')
        try:
            scope = record.get("scope")
            token_ref.set({
                'scope': scope,
                'access_token': record.get("access_token"),
                'refresh_token': record.get("refresh_token"),
                'expires': record.get("expires")
            })
        except Exception:
            token_ref.set({
                'access_token': record.get("access_token"),
                'refresh_token': record.get("refresh_token"),
                'expires': record.get("expires")
            })


        profile_ref = db.collection(STRAVA).document(ATHLETES).collection(athlete.id).document('profile')
        profile_ref.set({
            'firstname': record.get('firstname'),
            'lastname': record.get('lastname')
        })

    athlete_teams = db.collection(ATHLETE_TEAM).list_documents()
    for team in athlete_teams:
        record = db.collection(ATHLETE_TEAM).document(team.id).get()
        profile_ref = db.collection(STRAVA).document(ATHLETES).collection(team.id).document('profile')
        profile_ref.update({
            'team': record.get('team')
        })

