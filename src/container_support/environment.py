import inspect
import traceback

import abc

import container_support as cs
import importlib
import json
import logging
import multiprocessing
import os
import subprocess
import sys
import tempfile

logger = logging.getLogger(__name__)


class ContainerEnvironment(object):
    """Provides access to common aspects of the container environment, including
    important system characteristics, filesystem locations, and configuration settings.
    """
    BASE_DIRECTORY = "/opt/ml"
    USER_SCRIPT_NAME_PARAM = "sagemaker_program"
    USER_SCRIPT_ARCHIVE_PARAM = "sagemaker_submit_directory"
    CLOUDWATCH_METRICS_PARAM = "sagemaker_enable_cloudwatch_metrics"
    CONTAINER_LOG_LEVEL_PARAM = "sagemaker_container_log_level"
    JOB_NAME_PARAM = "sagemaker_job_name"
    CURRENT_HOST_ENV = "CURRENT_HOST"
    JOB_NAME_ENV = "JOB_NAME"
    USE_NGINX_ENV = "SAGEMAKER_USE_NGINX"
    SAGEMAKER_REGION_PARAM_NAME = 'sagemaker_region'
    FRAMEWORK_MODULE_NAME = "CONTAINER_MODULE_NAME"

    def __init__(self, base_dir=BASE_DIRECTORY):
        self.base_dir = base_dir
        "The current root directory for SageMaker interactions (``/opt/ml`` when running in SageMaker)."

        self.model_dir = os.path.join(base_dir, "model")
        "The directory to write model artifacts to so they can be handed off to SageMaker."

        self.code_dir = os.path.join(base_dir, "code")
        "The directory where user-supplied code will be staged."

        self.available_cpus = self._get_available_cpus()
        "The number of cpus available in the current container."

        self.available_gpus = self._get_available_gpus()
        "The number of gpus available in the current container."

        # subclasses will override
        self.user_script_name = None
        "The filename of the python script that contains user-supplied training/hosting code."

        # subclasses will override
        self.user_script_archive = None
        "The S3 location of the python code archive that contains user-supplied training/hosting code"

        self.enable_cloudwatch_metrics = False
        "Report system metrics to CloudWatch? (default = False)"

        # subclasses will override
        self.container_log_level = None
        "The logging level for the root logger."

        # subclasses will override
        self.sagemaker_region = None
        "The current AWS region."

    def download_user_module(self):
        """Download user-supplied python archive from S3.
        """
        tmp = os.path.join(tempfile.gettempdir(), "script.tar.gz")
        cs.download_s3_resource(self.user_script_archive, tmp)
        cs.untar_directory(tmp, self.code_dir)

    def import_user_module(self):
        """Import user-supplied python module.
        """
        sys.path.insert(0, self.code_dir)

        script = self.user_script_name
        if script.endswith(".py"):
            script = script[:-3]

        user_module = importlib.import_module(script)
        return user_module

    def start_metrics_if_enabled(self):
        if self.enable_cloudwatch_metrics:
            logger.info("starting metrics service")
            subprocess.Popen(['telegraf', '--config', '/usr/local/etc/telegraf.conf'])

    @staticmethod
    def _get_available_cpus():
        return multiprocessing.cpu_count()

    @staticmethod
    def _get_available_gpus():
        gpus = 0
        try:
            output = subprocess.check_output(["nvidia-smi", "--list-gpus"]).decode('utf-8')
            gpus = sum([1 for x in output.split('\n') if x.startswith('GPU ')])
        except Exception as e:
            logger.debug("exception listing gpus (normal if no nvidia gpus installed): %s" % str(e))

        return gpus

    @staticmethod
    def _load_config(path):
        with open(path, 'r') as f:
            return json.load(f)


class TrainingEnvironment(ContainerEnvironment):
    """Provides access to aspects of the container environment relevant to training jobs.
    """
    HYPERPARAMETERS_FILE = "hyperparameters.json"
    RESOURCE_CONFIG_FILE = "resourceconfig.json"
    INPUT_DATA_CONFIG_FILE = "inputdataconfig.json"
    S3_URI_PARAM = 'sagemaker_s3_uri'

    def __init__(self, base_dir=ContainerEnvironment.BASE_DIRECTORY):
        super(TrainingEnvironment, self).__init__(base_dir)
        self.input_dir = os.path.join(self.base_dir, "input")
        "The base directory for training data and configuration files."

        self.input_config_dir = os.path.join(self.input_dir, "config")
        "The directory where standard SageMaker configuration files are located."

        self.output_dir = os.path.join(self.base_dir, "output")
        "The directory where training success/failure indications will be written."

        self.resource_config = self._load_config(os.path.join(
            self.input_config_dir, TrainingEnvironment.RESOURCE_CONFIG_FILE))
        "dict of resource configuration settings."

        self.hyperparameters = self._load_hyperparameters(
            os.path.join(self.input_config_dir, TrainingEnvironment.HYPERPARAMETERS_FILE))
        "dict of hyperparameters that were passed to the CreateTrainingJob API."

        # TODO: change default.
        self.network_interface_name = self.resource_config.get('network_interface_name', 'ethwe')
        "the name of the network interface to use for distributed training."

        self.current_host = self.resource_config.get('current_host', '')
        "The hostname of the current container."

        self.hosts = self.resource_config.get('hosts', [])
        "The list of hostnames available to the current training job."

        self.output_data_dir = os.path.join(
            self.output_dir,
            "data",
            self.current_host if len(self.hosts) > 1 else '')
        "The dir to write non-model training artifacts (e.g. evaluation results) which will be retained by SageMaker. "

        # TODO validate docstring
        self.channels = self._load_config(
            os.path.join(self.input_config_dir, TrainingEnvironment.INPUT_DATA_CONFIG_FILE))
        "dict of training input data channel name to directory with the input files for that channel."

        # TODO validate docstring
        self.channel_dirs = {channel: self._get_channel_dir(channel) for channel in self.channels}

        self.user_script_name = self.hyperparameters.get(ContainerEnvironment.USER_SCRIPT_NAME_PARAM, '')
        self.user_script_archive = self.hyperparameters.get(ContainerEnvironment.USER_SCRIPT_ARCHIVE_PARAM, '')

        self.enable_cloudwatch_metrics = self.hyperparameters.get(ContainerEnvironment.CLOUDWATCH_METRICS_PARAM, False)
        self.container_log_level = self.hyperparameters.get(ContainerEnvironment.CONTAINER_LOG_LEVEL_PARAM)

        os.environ[ContainerEnvironment.JOB_NAME_ENV] = self.hyperparameters.get(
            ContainerEnvironment.JOB_NAME_PARAM, '')
        os.environ[ContainerEnvironment.CURRENT_HOST_ENV] = self.current_host

        self.sagemaker_region = self.hyperparameters[ContainerEnvironment.SAGEMAKER_REGION_PARAM_NAME]
        os.environ[ContainerEnvironment.SAGEMAKER_REGION_PARAM_NAME.upper()] = self.sagemaker_region

        self.distributed = len(self.hosts) > 1

        self.kwargs_for_training = {
            'hyperparameters': dict(self.hyperparameters),
            'input_data_config': dict(self.channels),
            'channel_input_dirs': dict(self.channel_dirs),
            'output_data_dir': self.output_data_dir,
            'model_dir': self.model_dir,
            'num_gpus': self.available_gpus,
            'num_cpus': self.available_cpus,
            'hosts': list(self.hosts),
            'current_host': self.current_host
        }
        """ Returns a dictionary of key-word arguments for input to the user supplied module train function. """
        self.training_parameters = None

    def load_training_parameters(self, fn):
        self.training_parameters = self.matching_parameters(fn)

    def matching_parameters(self, fn):
        train_args = inspect.getargspec(fn)
        # avoid forcing our callers to specify **kwargs in their function
        # signature. If they have **kwargs we still pass all the args, but otherwise
        # we will just pass what they ask for.
        if train_args.keywords is None:
            kwargs_to_pass = {}
            for arg in train_args.args:
                if arg != "self" and arg in self.kwargs_for_training:
                    kwargs_to_pass[arg] = self.kwargs_for_training[arg]
        else:
            kwargs_to_pass = self.kwargs_for_training
        return kwargs_to_pass

    def train(self):
        logger.info("started training: {}".format(repr(self.__dict__)))

        try:
            self.start_metrics_if_enabled()
            self.download_user_module()
            user_module = self.import_user_module()
            training_parameters = self.load_training_parameters(user_module)

            self.__train__(user_module, training_parameters)
            self.write_success_file()
        except Exception as e:
            trc = traceback.format_exc()
            message = 'uncaught exception during training: {}\n{}\n'.format(e, trc)
            TrainingEnvironment.write_failure_file(message, self.base_dir)
            raise e

    def _load_hyperparameters(self, path):
        serialized = self._load_config(path)
        return self._deserialize_hyperparameters(serialized)

    # TODO expecting serialized hyperparams might break containers that aren't launched by python sdk
    @staticmethod
    def _deserialize_hyperparameters(hp):
        return {k: json.loads(v) for (k, v) in hp.items()}

    def write_success_file(self):
        TrainingEnvironment.ensure_directory(self.output_dir)
        path = os.path.join(self.output_dir, 'success')
        open(path, 'w').close()

    @staticmethod
    def write_failure_file(message, base_dir=None):
        base_dir = base_dir or ContainerEnvironment.BASE_DIRECTORY
        output_dir = os.path.join(base_dir, "output")
        TrainingEnvironment.ensure_directory(output_dir)
        with open(os.path.join(output_dir, 'failure'), 'a') as fd:
            fd.write(message)

    @staticmethod
    def ensure_directory(dir):
        if not os.path.exists(dir):
            os.makedirs(dir)

    def _get_channel_dir(self, channel):
        """ Returns the directory containing the channel data file(s).

        This is either:

        - <self.base_dir>/input/data/<channel> OR
        - <self.base_dir>/input/data/<channel>/<channel_s3_suffix>

        Where channel_s3_suffix is the hyperparameter value with key <S3_URI_PARAM>_<channel>.

        The first option is returned if <self.base_dir>/input/data/<channel>/<channel_s3_suffix>
        does not exist in the file-system or <S3_URI_PARAM>_<channel> does not exist in
        self.hyperparmeters. Otherwise, the second option is returned.

        TODO: Refactor once EASE downloads directly into /opt/ml/input/data/<channel>
        TODO: Adapt for Pipe Mode

        Returns:
            (str) The input data directory for the specified channel.
        """
        channel_s3_uri_param = "{}_{}".format(TrainingEnvironment.S3_URI_PARAM, channel)
        if channel_s3_uri_param in self.hyperparameters:
            channel_s3_suffix = self.hyperparameters.get(channel_s3_uri_param)
            channel_dir = os.path.join(self.input_dir, 'data', channel, channel_s3_suffix)
            if os.path.exists(channel_dir):
                return channel_dir
        return os.path.join(self.input_dir, 'data', channel)


class HostingEnvironment(ContainerEnvironment):
    """ Provides access to aspects of the container environment relevant to hosting jobs.
    """

    MODEL_SERVER_WORKERS_PARAM = 'SAGEMAKER_MODEL_SERVER_WORKERS'
    MODEL_SERVER_TIMEOUT_PARAM = "SAGEMAKER_MODEL_SERVER_TIMEOUT"

    def __init__(self, base_dir=ContainerEnvironment.BASE_DIRECTORY):
        super(HostingEnvironment, self).__init__(base_dir)
        self.model_server_timeout = os.environ.get(HostingEnvironment.MODEL_SERVER_TIMEOUT_PARAM, 60)
        self.user_script_name = os.environ.get(ContainerEnvironment.USER_SCRIPT_NAME_PARAM.upper(), None)
        self.user_script_archive = os.environ.get(ContainerEnvironment.USER_SCRIPT_ARCHIVE_PARAM.upper(), None)

        self.enable_cloudwatch_metrics = os.environ.get(
            ContainerEnvironment.CLOUDWATCH_METRICS_PARAM.upper(), 'false').lower() == 'true'

        self.use_nginx = os.environ.get(ContainerEnvironment.USE_NGINX_ENV, 'true') == 'true'
        "Use nginx as front-end HTTP server instead of gunicorn."

        self.model_server_workers = int(os.environ.get(
            HostingEnvironment.MODEL_SERVER_WORKERS_PARAM,
            self.available_cpus))
        "The number of model server processes to run concurrently."

        self.container_log_level = int(os.environ[ContainerEnvironment.CONTAINER_LOG_LEVEL_PARAM.upper()])

        self.sagemaker_region = os.environ[ContainerEnvironment.SAGEMAKER_REGION_PARAM_NAME.upper()]
        os.environ[ContainerEnvironment.SAGEMAKER_REGION_PARAM_NAME.upper()] = self.sagemaker_region

        os.environ[ContainerEnvironment.JOB_NAME_ENV] = os.environ.get(
            ContainerEnvironment.JOB_NAME_PARAM.upper(), '')


def configure_logging():
    format = '%(asctime)s %(levelname)s - %(name)s - %(message)s'
    default_level = logging.INFO

    level = None

    for c in [HostingEnvironment, TrainingEnvironment]:
        try:
            level = int(c().container_log_level)
            break
        except:  # noqa
            pass

    logging.basicConfig(format=format, level=level or default_level)

    if not level:
        logging.warn("error reading log_level, using INFO")

    if not level or level >= logging.INFO:
        logging.getLogger("boto3").setLevel(logging.WARNING)


def import_framework_module():
    """Import the deep learning framework needed for the current training job.
    """
    framework_module_name = os.environ.get(ContainerEnvironment.FRAMEWORK_MODULE_NAME, None)
    if framework_module_name:
        return importlib.import_module(framework_module_name)

    # TODO less atrocious implementation -- perhaps set in env or hyperparameters?
    try:
        return importlib.import_module('mxnet_container')
    except ImportError:
        return importlib.import_module('tf_container')
