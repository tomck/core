import requests
import json
import logging
log = logging.getLogger(__name__)
sh = logging.StreamHandler()
log.addHandler(sh)

requests.packages.urllib3.disable_warnings()

base_url = 'https://localhost:8080/api'

def test_users():
    session = requests.Session()
    session.verify = False
    _id = 'new@user.com'
    r = session.get(base_url + '/users/self?user=test@user.com')
    assert r.ok
    r = session.get(base_url + '/users/' + _id + '?user=test@user.com&root=true')
    assert r.status_code == 404
    payload = {
        '_id': _id,
        'firstname': 'New',
        'lastname': 'User',
    }
    payload = json.dumps(payload)
    r = session.post(base_url + '/users?user=test@user.com&root=true', data=payload)
    assert r.ok
    r = session.get(base_url + '/users/' + _id + '?user=test@user.com&root=true')
    assert r.ok
    payload = {
        'firstname': 'Realname'
    }
    payload = json.dumps(payload)
    r = session.put(base_url + '/users/' + _id + '?user=test@user.com&root=true', data=payload)
    assert r.ok
    r = session.delete(base_url + '/users/' + _id + '?user=test@user.com&root=true')
    assert r.ok
