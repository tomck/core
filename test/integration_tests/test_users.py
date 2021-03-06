import json
import logging

log = logging.getLogger(__name__)
sh = logging.StreamHandler()
log.addHandler(sh)


def test_users(api_as_admin):
    new_user_id = 'new@user.com'

    # Get self
    r = api_as_admin.get('/users/self')
    assert r.ok

    # Add new user
    r = api_as_admin.get('/users/' + new_user_id)
    assert r.status_code == 404
    payload = json.dumps({
        '_id': new_user_id,
        'firstname': 'New',
        'lastname': 'User',
    })
    r = api_as_admin.post('/users', data=payload)
    assert r.ok
    r = api_as_admin.get('/users/' + new_user_id)
    assert r.ok

    # Modify existing user
    payload = json.dumps({
        'firstname': 'Realname'
    })
    r = api_as_admin.put('/users/' + new_user_id, data=payload)
    assert r.ok

    # Cleanup
    r = api_as_admin.delete('/users/' + new_user_id)
    assert r.ok
