# @author:  Gunnar Schaefer

import json
import webapp2
import bson.json_util

import nimsapiutil


class Sessions(nimsapiutil.NIMSRequestHandler):

    def count(self):
        """Return the number of Sessions."""
        self.response.write('sessions count\n')

    def post(self):
        """Create a new Session"""
        self.response.write('sessions post\n')

    def get(self, exp_id):
        """Return the list of Experiment Sessions."""
        experiment = self.app.db.experiments.find_one({'_id': bson.objectid.ObjectId(exp_id)})
        if not experiment:
            self.abort(404)
        if not self.user_is_superuser and self.userid not in experiment['permissions']:
            self.abort(403)
        query = {'experiment': bson.objectid.ObjectId(exp_id)}
        projection = ['timestamp', 'subject']
        sessions = list(self.app.db.sessions.find(query, projection))
        self.response.write(json.dumps(sessions, default=bson.json_util.default))

    def put(self):
        """Update many Sessions."""
        self.response.write('sessions put\n')


class Session(nimsapiutil.NIMSRequestHandler):

    def get(self, sess_id):
        """Return one Session, conditionally with details."""
        session = self.app.db.sessions.find_one({'_id': bson.objectid.ObjectId(sess_id)})
        if not session:
            self.abort(404)
        experiment = self.app.db.experiments.find_one({'_id': bson.objectid.ObjectId(session['experiment'])})
        if not experiment:
            self.abort(500)
        if not self.user_is_superuser and self.userid not in experiment['permissions']:
            self.abort(403)
        self.response.write(json.dumps(session, default=bson.json_util.default))

    def put(self, _id):
        """Update an existing Session."""
        self.response.write('session %s put, %s\n' % (_id, self.request.params))

    def delete(self, _id):
        """Delete an Session."""
        self.response.write('session %s delete, %s\n' % (_id, self.request.params))

    def move(self, _id):
        """
        Move a Session to another Experiment.

        Usage:
            /nimsapi/sessions/123/move?dest=456
        """
        self.response.write('session %s move, %s\n' % (_id, self.request.params))