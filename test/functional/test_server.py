# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the 'License'). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
#     http://aws.amazon.com/apache2.0/
#
# or in the 'license' file accompanying this file. This file is
# distributed on an 'AS IS' BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.
import os
import threading
import time

import urllib3

import sagemaker_containers


def test_server():
    os.environ[sagemaker_containers.environment.FLASK_APP_ENV] = 'test.functional.simple_flask:app'
    os.environ[sagemaker_containers.environment.USE_NGINX_ENV] = 'false'

    env = sagemaker_containers.environment.ServingEnvironment()
    print(env.flask_app)

    def worker():
        sagemaker_containers.server.start_server(env.flask_app)

    t = threading.Thread(target=worker)
    t.start()

    time.sleep(2)

    http = urllib3.PoolManager()
    base_url = 'http://127.0.0.1:8080'
    r = http.request('GET', '{}/ping'.format(base_url))
    assert r.status == 200

    r = http.request('GET', '{}/invocations'.format(base_url))
    assert r.status == 200
    assert r.data.decode('utf-8') == 'invocation'

    # shut down the server or else it will go on forever.
    try:
        http.request('GET', '{}/shutdown'.format(base_url))
    except urllib3.exceptions.MaxRetryError:
        # the above request will kill the server so it is expected that it fails.
        pass
