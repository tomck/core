import bson
import copy
import datetime
import dateutil.parser
import difflib
import pymongo
import re

from .. import files
from .. import util
from .. import config
from . import APIStorageException, containerutil

log = config.log

PROJECTION_FIELDS = ['group', 'name', 'label', 'timestamp', 'permissions', 'public']

class TargetContainer(object):

    def __init__(self, container, level):
        self.container = container
        self.level = level
        self.dbc = config.db[level]
        self._id = container['_id']

    def find(self, filename):
        for f in self.container.get('files', []):
            if f['name'] == filename:
                return f
        return None

    def update_file(self, fileinfo):

        update_set = {'files.$.modified': datetime.datetime.utcnow()}
        # in this method, we are overriding an existing file.
        # update_set allows to update all the fileinfo like size, hash, etc.
        for k,v in fileinfo.iteritems():
            update_set['files.$.' + k] = v
        return self.dbc.find_one_and_update(
            {'_id': self._id, 'files.name': fileinfo['name']},
            {'$set': update_set},
            return_document=pymongo.collection.ReturnDocument.AFTER
        )

    def add_file(self, fileinfo):
        return self.dbc.find_one_and_update(
            {'_id': self._id},
            {'$push': {'files': fileinfo}},
            return_document=pymongo.collection.ReturnDocument.AFTER
        )

# TODO: already in code elsewhere? Location?
def get_container(cont_name, _id):
    cont_name += 's'
    _id = bson.ObjectId(_id)

    return config.db[cont_name].find_one({
        '_id': _id,
    })

def propagate_changes(cont_name, _id, query, update):
    """
    Propagates changes down the heirarchy tree.

    cont_name and _id refer to top level container (which will not be modified here)
    """

    if cont_name == 'groups':
        project_ids = [p['_id'] for p in config.db.projects.find({'group': _id}, [])]
        session_ids = [s['_id'] for s in config.db.sessions.find({'project': {'$in': project_ids}}, [])]

        project_q = copy.deepcopy(query)
        project_q['_id'] = {'$in': project_ids}
        session_q = copy.deepcopy(query)
        session_q['_id'] = {'$in': session_ids}
        acquisition_q = copy.deepcopy(query)
        acquisition_q['session'] = {'$in': session_ids}

        config.db.projects.update_many(project_q, update)
        config.db.sessions.update_many(session_q, update)
        config.db.acquisitions.update_many(acquisition_q, update)

    elif cont_name == 'projects':
        session_ids = [s['_id'] for s in config.db.sessions.find({'project': _id}, [])]

        session_q = copy.deepcopy(query)
        session_q['project'] = _id
        acquisition_q = copy.deepcopy(query)
        acquisition_q['session'] = {'$in': session_ids}

        config.db.sessions.update_many(session_q, update)
        config.db.acquisitions.update_many(acquisition_q, update)

    elif cont_name == 'sessions':
        query['sessions'] = _id
        config.db.acquisitions.update_many(query, update)
    else:
        raise ValueError('changes can only be propagated from group, project or session level')

def upsert_fileinfo(cont_name, _id, fileinfo):
    # TODO: make all functions take singular noun
    cont_name += 's'

    # TODO: make all functions consume strings
    _id = bson.ObjectId(_id)

    # OPPORTUNITY: could potentially be atomic if we pass a closure to perform the modification
    result = config.db[cont_name].find_one({
        '_id': _id,
        'files.name': fileinfo['name'],
    })

    if result is None:
        fileinfo['created'] = fileinfo['modified']
        return add_fileinfo(cont_name, _id, fileinfo)
    else:
        return update_fileinfo(cont_name, _id, fileinfo)

def update_fileinfo(cont_name, _id, fileinfo):
    update_set = {'files.$.modified': datetime.datetime.utcnow()}
    # in this method, we are overriding an existing file.
    # update_set allows to update all the fileinfo like size, hash, etc.
    for k,v in fileinfo.iteritems():
        update_set['files.$.' + k] = v
    return config.db[cont_name].find_one_and_update(
        {'_id': _id, 'files.name': fileinfo['name']},
        {'$set': update_set},
        return_document=pymongo.collection.ReturnDocument.AFTER
    )

def add_fileinfo(cont_name, _id, fileinfo):
    return config.db[cont_name].find_one_and_update(
        {'_id': _id},
        {'$push': {'files': fileinfo}},
        return_document=pymongo.collection.ReturnDocument.AFTER
    )

def _group_id_fuzzy_match(group_id, project_label):
    existing_group_ids = [g['_id'] for g in config.db.groups.find(None, ['_id'])]
    if group_id.lower() in existing_group_ids:
        return group_id.lower(), project_label
    group_id_matches = difflib.get_close_matches(group_id, existing_group_ids, cutoff=0.8)
    if len(group_id_matches) == 1:
        group_id = group_id_matches[0]
    else:
        project_label = group_id + '_' + project_label
        group_id = 'unknown'
    return group_id, project_label

def _find_or_create_destination_project(group_id, project_label, timestamp):
    group_id, project_label = _group_id_fuzzy_match(group_id, project_label)
    group = config.db.groups.find_one({'_id': group_id})
    project = config.db.projects.find_one_and_update(
        {'group': group['_id'],
         'label': {'$regex': re.escape(project_label), '$options': 'i'}
        },
        {
            '$setOnInsert': {
                'label': project_label,
                'permissions': group['roles'], 'public': False,
                'created': timestamp, 'modified': timestamp
            }
        },
        PROJECTION_FIELDS,
        upsert=True,
        return_document=pymongo.collection.ReturnDocument.AFTER,
        )
    return project


def _create_session_query(session, project, type_):
    if type_ == 'label':
        return {
            'label': session['label'],
            'project': project['_id']
        }
    elif type_ == 'uid':
        return {
            'uid': session['uid']
        }
    else:
        raise NotImplementedError('upload type is not handled by _create_session_query')


def _create_acquisition_query(acquisition, session, type_):
    if type_ == 'label':
        return {
            'label': acquisition['label'],
            'session': session['_id']
        }
    elif type_ == 'uid':
        return {
            'uid': acquisition['uid']
        }
    else:
        raise NotImplementedError('upload type is not handled by _create_acquisition_query')


def _upsert_session(session, project_obj, type_, timestamp):
    session['modified'] = timestamp
    if session.get('timestamp'):
        session['timestamp'] = dateutil.parser.parse(session['timestamp'])
    session['subject'] = containerutil.add_id_to_subject(session.get('subject'), project_obj['_id'])
    session_operations = {
        '$setOnInsert': dict(
            group=project_obj['group'],
            project=project_obj['_id'],
            permissions=project_obj['permissions'],
            public=project_obj.get('public', False),
            created=timestamp
        ),
        '$set': session
    }
    session_obj = config.db.sessions.find_one_and_update(
        _create_session_query(session, project_obj, type_),
        session_operations,
        upsert=True,
        return_document=pymongo.collection.ReturnDocument.AFTER,
    )
    return session_obj

def _upsert_acquisition(acquisition, session_obj, type_, timestamp):
    if acquisition.get('timestamp'):
        acquisition['timestamp'] = dateutil.parser.parse(acquisition['timestamp'])
        session_operations = {'$min': dict(timestamp=acquisition['timestamp'])}
        if acquisition.get('timezone'):
            session_operations['$set'] = {'timezone': acquisition['timezone']}
        config.db.sessions.update_one({'_id': session_obj['_id']}, session_operations)

    acquisition['modified'] = timestamp
    acq_operations = {
        '$setOnInsert': dict(
            session=session_obj['_id'],
            permissions=session_obj['permissions'],
            public=session_obj.get('public', False),
            created=timestamp
        ),
        '$set': acquisition
    }
    acquisition_obj = config.db.acquisitions.find_one_and_update(
        _create_acquisition_query(acquisition, session_obj, type_),
        acq_operations,
        upsert=True,
        return_document=pymongo.collection.ReturnDocument.AFTER
    )
    return acquisition_obj


def _get_targets(project_obj, session, acquisition, type_, timestamp):
    target_containers = []
    if not session:
        return target_containers
    session_files = dict_fileinfos(session.pop('files', []))
    session_obj = _upsert_session(session, project_obj, type_, timestamp)
    target_containers.append(
        (TargetContainer(session_obj, 'session'), session_files)
    )
    if not acquisition:
        return target_containers
    acquisition_files = dict_fileinfos(acquisition.pop('files', []))
    acquisition_obj = _upsert_acquisition(acquisition, session_obj, type_, timestamp)
    target_containers.append(
        (TargetContainer(acquisition_obj, 'acquisition'), acquisition_files)
    )
    return target_containers


def upsert_bottom_up_hierarchy(metadata):
    group = metadata.get('group', {})
    project = metadata.get('project', {})
    session = metadata.get('session', {})
    acquisition = metadata.get('acquisition', {})

    # Fail if some fields are missing
    try:
        group_id = group['_id']
        project_label = project['label']
        session_uid = session['uid']
        acquisition_uid = acquisition['uid']
    except Exception as e:
        log.error(metadata)
        raise APIStorageException(str(e))

    now = datetime.datetime.utcnow()

    session_obj = config.db.sessions.find_one({'uid': session_uid}, ['project'])
    if session_obj: # skip project creation, if session exists
        project_files = dict_fileinfos(project.pop('files', []))
        project_obj = config.db.projects.find_one({'_id': session_obj['project']}, projection=PROJECTION_FIELDS + ['name'])
        target_containers = _get_targets(project_obj, session, acquisition, 'uid', now)
        target_containers.append(
            (TargetContainer(project_obj, 'project'), project_files)
        )
        return target_containers
    else:
        return upsert_top_down_hierarchy(metadata, 'uid')


def upsert_top_down_hierarchy(metadata, type_='label'):
    group = metadata['group']
    project = metadata['project']
    session = metadata.get('session')
    acquisition = metadata.get('acquisition')

    now = datetime.datetime.utcnow()
    project_files = dict_fileinfos(project.pop('files', []))
    project_obj = _find_or_create_destination_project(group['_id'], project['label'], now)
    target_containers = _get_targets(project_obj, session, acquisition, type_, now)
    target_containers.append(
        (TargetContainer(project_obj, 'project'), project_files)
    )
    return target_containers


def dict_fileinfos(infos):
    dict_infos = {}
    for info in infos:
        dict_infos[info['name']] = info
    return dict_infos


def update_container_hierarchy(metadata, cid, container_type):
    c_metadata = metadata.get(container_type)
    now = datetime.datetime.utcnow()
    if c_metadata.get('timestamp'):
        c_metadata['timestamp'] = dateutil.parser.parse(c_metadata['timestamp'])
    c_metadata['modified'] = now
    c_obj = _update_container({'_id': cid}, {}, c_metadata, container_type)
    if c_obj is None:
        raise APIStorageException('container does not exist')
    if container_type in ['session', 'acquisition']:
        update_timestamp = True if c_metadata.get('timestamp') else False
        _update_hierarchy(c_obj, container_type, metadata, update_timestamp)
    return c_obj


def _update_container(query, update, set_update, container_type):
    coll_name = container_type if container_type.endswith('s') else container_type+'s'
    update['$set'] = util.mongo_dict(set_update)
    return config.db[coll_name].find_one_and_update(query,update,
        return_document=pymongo.collection.ReturnDocument.AFTER
    )


def _update_hierarchy(container, container_type, metadata, update_timestamp=False):
    project_id = container.get('project') # for sessions
    now = datetime.datetime.utcnow()

    if container_type == 'acquisition':
        update = {}
        session = metadata.get('session', {})
        session_obj = None
        if update_timestamp:
            update['$min'] = dict(timestamp=container['timestamp'])
            session['timezone'] = dict(timezone=container.get('timezone'))
        if update.keys() or session.keys():
            session['modified'] = now
            session_obj = _update_container({'_id': container['session']}, update, session, 'sessions')
        if session_obj is None:
            session_obj = get_container('session', container['session'])
        project_id = session_obj['project']

    if project_id is None:
        raise APIStorageException('Failed to find project id in session obj')
    update = {}
    project = metadata.get('project', {})
    if update_timestamp:
        update['$max'] = dict(timestamp=container['timestamp'])
        project['timezone'] = dict(timezone=container.get('timezone'))
    if project.keys():
        project['modified'] = now
        project_obj = _update_container({'_id': project_id}, update, project, 'projects')


def merge_fileinfos(parsed_files, infos):
    """it takes a dictionary of "hard_infos" (file size, hash)
    merging them with infos derived from a list of infos on the same or on other files
    """
    merged_files = {}
    for info in infos:
        parsed = parsed_files.get(info['name'])
        if parsed:
            path = parsed.path
            new_infos = copy.deepcopy(parsed.info)
        else:
            path = None
            new_infos = {}
        new_infos.update(info)
        merged_files[info['name']] = files.ParsedFile(new_infos, path)
    return merged_files
