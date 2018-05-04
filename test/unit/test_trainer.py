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
from mock import Mock, patch, PropertyMock

from sagemaker_containers import env, trainer


HYPERPARAMS = {
    'x': 1,
    'sagemaker_region': 'us-west-2',
    'sagemaker_job_name': 'sagemaker-training-job',
    'sagemaker_program': 'main.py',
    'sagemaker_submit_directory': 'imagenet',
    'sagemaker_enable_cloudwatch_metrics': True
}


@patch('importlib.import_module')
@patch('sagemaker_containers.env.read_hyperparameters', lambda: HYPERPARAMS)
@patch('sagemaker_containers.env.read_input_data_config', lambda: {'input': 'yes'})
@patch('sagemaker_containers.env.read_resource_config', lambda: {'current_host': '1', 'hosts': ['1']})
@patch.object(env.TrainingEnv, 'model_dir', PropertyMock(return_value='model_dir'))
@patch.object(env.TrainingEnv, 'framework_module', PropertyMock(return_value='my_framework:train'))
def test_train(import_module):
    framework = Mock()

    import_module.return_value = framework
    trainer.train()

    import_module.assert_called_with('my_framework')
    framework.train.assert_called()