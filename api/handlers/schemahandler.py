import os
import json
import datetime
import jinja2

from .. import base
from .. import config

log = config.log

class SchemaHandler(base.RequestHandler):

    def __init__(self, request=None, response=None):
        super(SchemaHandler, self).__init__(request, response)

    def get(self, schema, **kwargs):

    	schema_type = 'mongo'

        log.debug('Attempting to serve jinja templated json schema file {}'.format(schema))

        template = config.jinja_env.get_template(schema)
        return json.loads(str(template.render(schema_type=schema_type)))
