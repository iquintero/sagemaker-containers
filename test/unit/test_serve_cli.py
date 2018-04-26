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
from mock import patch, PropertyMock

from sagemaker_containers.cli import serve
from sagemaker_containers.environment import ServingEnvironment


@patch.object(ServingEnvironment, 'flask_app', new_callable=PropertyMock)
@patch('sagemaker_containers.server.start_server')
def test_entry_point(start_server, flask_app):
    flask_app.return_value = 'my_flask_app'
    serve.main()
    start_server.assert_called_with('my_flask_app')
