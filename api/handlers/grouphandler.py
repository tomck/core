import datetime

from .. import base
from .. import util
from .. import config
from .. import debuginfo
from .. import validators
from ..auth import groupauth, always_ok
from ..dao import containerstorage

log = config.log


class GroupHandler(base.RequestHandler):

    def __init__(self, request=None, response=None):
        super(GroupHandler, self).__init__(request, response)

    def get(self, _id):
        self._init_storage()
        group = self._get_group(_id)
        if not group:
            self.abort(404, 'no such Group: ' + _id)
        permchecker = groupauth.default(self, group)
        result = permchecker(self.storage.exec_op)('GET', _id)
        if not self.superuser_request:
            self._filter_roles([result], self.uid, self.user_site)
        return result

    def delete(self, _id):
        if _id == 'unknown':
            self.abort(400, 'The group "unknown" can\'t be deleted as it is integral within the API')
        self._init_storage()
        group = self._get_group(_id)
        if not group:
            self.abort(404, 'no such Group: ' + _id)
        permchecker = groupauth.default(self, group)
        result = permchecker(self.storage.exec_op)('DELETE', _id)
        if result.deleted_count == 1:
            return {'deleted': result.deleted_count}
        else:
            self.abort(404, 'Group {} not removed'.format(_id))
        return result

    def get_all(self, uid=None):
        self._init_storage()
        query = None
        projection = {'name': 1, 'created': 1, 'modified': 1, 'roles': [], 'tags': []}
        permchecker = groupauth.list_permission_checker(self, uid)
        results = permchecker(self.storage.exec_op)('GET', projection=projection)
        if results is None:
            self.abort(404, 'Not found')
        if not self.superuser_request:
            self._filter_roles(results, self.uid, self.user_site)
        if self.debug:
            debuginfo.add_debuginfo(self, 'groups', results)
        return results

    def put(self, _id):
        self._init_storage()
        group = self._get_group(_id)
        if not group:
            self.abort(404, 'no such Group: ' + _id)
        permchecker = groupauth.default(self, group)
        payload = self.request.json_body
        mongo_schema_uri = util.schema_uri('mongo', 'group.json')
        mongo_validator = validators.decorator_from_schema_path(mongo_schema_uri)
        payload_schema_uri = util.schema_uri('input', 'group.json')
        payload_validator = validators.from_schema_path(payload_schema_uri)
        payload_validator(payload, 'PUT')
        result = mongo_validator(permchecker(self.storage.exec_op))('PUT', _id=_id, payload=payload)
        if result.modified_count == 1:
            return {'modified': result.modified_count}
        else:
            self.abort(404, 'Group {} not updated'.format(_id))

    def post(self):
        self._init_storage()
        permchecker = groupauth.default(self, None)
        payload = self.request.json_body
        mongo_schema_uri = util.schema_uri('mongo', 'group.json')
        mongo_validator = validators.decorator_from_schema_path(mongo_schema_uri)
        payload_schema_uri = util.schema_uri('input', 'group.json')
        payload_validator = validators.from_schema_path(payload_schema_uri)
        payload_validator(payload, 'POST')
        payload['created'] = payload['modified'] = datetime.datetime.utcnow()
        payload['roles'] = [{'_id': self.uid, 'access': 'admin', 'site': self.user_site}] if self.uid else []
        result = mongo_validator(permchecker(self.storage.exec_op))('POST', payload=payload)
        if result.acknowledged:
            if result.upserted_id:
                return {'_id': result.upserted_id}
            else:
                self.response.status_int = 201
                return {'_id': payload['_id']}
        else:
            self.abort(404, 'Group {} not updated'.format(payload['_id']))

    def _init_storage(self):
        self.storage = containerstorage.GroupStorage('groups', use_object_id=False)

    def _get_group(self, _id):
        group = self.storage.get_container(_id)
        if group is not None:
            return group
        else:
            self.abort(404, 'Group {} not found'.format(_id))

    def _filter_roles(self, results, uid, site):
        """
        if the user is not admin only her role is returned.
        """
        for result in results:
            user_perm = util.user_perm(result.get('roles', []), uid, site)
            if user_perm.get('access') != 'admin':
                result['roles'] = [user_perm] if user_perm else []
        return results
