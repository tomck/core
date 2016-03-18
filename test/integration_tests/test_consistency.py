import requests
import json
import time
import logging
log = logging.getLogger(__name__)
sh = logging.StreamHandler()
log.addHandler(sh)

base_url = 'https://localhost:8080/api'

def test_consistency_checker():
    session = requests.Session()
    session.verify = False
    # all the requests will be performed as root
    session.params = {
        'user': 'test@user.com',
        'root': True
    }
    gid = 'test_group_' + str(int(time.time()*1000))
    payload = {
        '_id': gid
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/groups', data=payload)
    assert r.ok
    payload = {
        'group': gid,
        'label': 'test_project',
        'public': False
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/projects', data=payload)
    assert r.ok
    pid = json.loads(r.content)['_id']
    r = session.delete(base_url + '/groups/' + gid)
    assert r.status_code == 400
    r = session.delete(base_url + '/projects/' + pid)
    assert r.ok
    r = session.delete(base_url + '/groups/' + gid)
    assert r.ok
