# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
#     http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.
from __future__ import absolute_import

import os

import numpy as np
import pytest

import sagemaker_containers as smc
import test

dir_path = os.path.dirname(os.path.realpath(__file__))

USER_SCRIPT = """
import os
import test.miniml as miniml
import numpy as np

def train(channel_input_dirs, hyperparameters):
    data = np.load(os.path.join(channel_input_dirs['training'], hyperparameters['training_data_file']))
    x_train = data['features']
    y_train = data['labels']

    model = miniml.Model(loss='categorical_crossentropy', optimizer='SGD')

    model.fit(x=x_train, y=y_train, epochs=hyperparameters['epochs'], batch_size=hyperparameters['batch_size'])

    return model
"""

USER_SCRIPT_WITH_SAVE = """
import os
import test.miniml as miniml
import numpy as np

def train(channel_input_dirs, hyperparameters):
    data = np.load(os.path.join(channel_input_dirs['training'], hyperparameters['training_data_file']))
    x_train = data['features']
    y_train = data['labels']

    model = miniml.Model(loss='categorical_crossentropy', optimizer='SGD')

    model.fit(x=x_train, y=y_train, epochs=hyperparameters['epochs'], batch_size=hyperparameters['batch_size'])

    return model

def save(model, model_dir):
    model.save(model_file)
"""


class TestFramework(object):
    @staticmethod
    def framework_training_fn():
        env = smc.TrainingEnvironment()

        mod = smc.modules.download_and_import(env.module_dir, env.module_name)

        model = mod.train(**smc.functions.matching_args(mod.train, env))

        if model:
            if hasattr(mod, 'save'):
                mod.save(model, env.model_dir)
            else:
                model_file = os.path.join(env.model_dir, 'saved_model')
                model.save(model_file)

    @pytest.mark.parametrize('user_script', [USER_SCRIPT, USER_SCRIPT_WITH_SAVE])
    def test_training_framework(self, user_script):
        channel = test.Channel.create(name='training')

        features = [1, 2, 3, 4]
        labels = [0, 1, 0, 1]
        np.savez(os.path.join(channel.path, 'training_data'), features=features, labels=labels)

        module = test.UserModule(test.File(name='user_script.py', content=user_script))

        hyperparameters = dict(training_data_file='training_data.npz', sagemaker_program='user_script.py',
                               epochs=10, batch_size=64)

        test.prepare(user_module=module, hyperparameters=hyperparameters, channels=[channel])

        self.framework_training_fn()

        model = smc.environment.read_json(os.path.join(smc.environment.MODEL_PATH, 'saved_model'))

        assert model == dict(loss='categorical_crossentropy', y=labels, epochs=10,
                             x=features, batch_size=64, optimizer='SGD')
