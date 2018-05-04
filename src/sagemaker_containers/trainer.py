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
import importlib
import os

from sagemaker_containers import env, functions


def train():
    training_env = env.TrainingEnv()

    # TODO: iquintero - add error handling for ImportError to let the user know
    # if the framework module is not defined.
    framework = importlib.import_module(training_env.framework_module)
    model = framework.train(**functions.matching_args(framework.train, training_env))

    if model:
        if hasattr(framework, 'save'):
            framework.save(model, training_env.model_dir)
        else:
            model_file = os.path.join(training_env.model_dir, 'saved_model')
            model.save(model_file)
