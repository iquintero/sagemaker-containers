import os
import logging
import signal
import sys
import json
from flask import Flask, request, Response
import container_support as cs
import subprocess
import shutil

from container_support.retrying import retry

logger = logging.getLogger(__name__)

NPY_CONTENT_TYPE = "application/x-npy"
JSON_CONTENT_TYPE = "application/json"
CSV_CONTENT_TYPE = "text/csv"
OCTET_STREAM_CONTENT_TYPE = "application/octet-stream"
ANY_CONTENT_TYPE = '*/*'
UTF8_CONTENT_TYPES = [JSON_CONTENT_TYPE, CSV_CONTENT_TYPE]


class Server(object):
    """A simple web service wrapper for custom inference code.
    """

    def __init__(self, name, transform_fn, model):
        """ Initialize the web service instance.

        :param name: the name of the service
        :param transform_fn: a function that transforms incoming request data to
                            an outgoing inference response.
        :param model:
        """
        self.transform_fn = transform_fn
        self.app = self._build_flask_app(name)
        self.log = self.app.logger
        self.model = model

    @classmethod
    @retry(stop_max_delay=1000 * 60 * 10,
           wait_exponential_multiplier=100,
           wait_exponential_max=60000)
    def _download_user_module(cls, env):
        Server._download_user_module_internal(env)

    @classmethod
    def _download_user_module_internal(cls, env):
        path = os.path.join(env.code_dir, env.user_script_name)
        if os.path.exists(path):
            return

        try:
            env.download_user_module()
        except:  # noqa
            try:
                shutil.rmtree(env.code_dir)
            except OSError:
                pass
            raise

    @staticmethod
    def _sigterm_handler(nginx_pid, gunicorn_pid):
        logger.info("stopping inference server")

        if nginx_pid:
            try:
                os.kill(nginx_pid, signal.SIGQUIT)
            except OSError:
                pass

        try:
            os.kill(gunicorn_pid, signal.SIGTERM)
        except OSError:
            pass

        sys.exit(0)

    def _build_flask_app(self, name):
        """ Construct the Flask app that will handle requests.

        :param name: the name of the service
        :return: a Flask app ready to handle requests
        """
        app = Flask(name)
        app.add_url_rule('/ping', 'healthcheck', self._healthcheck)
        app.add_url_rule('/invocations', 'invoke', self._invoke, methods=["POST"])
        app.register_error_handler(Exception, self._default_error_handler)
        return app

    def _invoke(self):
        """Handles requests by delegating to the transform_fn function.

        :return: 200 response, with transform_fn result in body.
        """

        # Accepting both ContentType and Content-Type headers. ContentType because Coral and Content-Type because,
        # well, it is just the html standard
        input_content_type = request.headers.get('ContentType', request.headers.get('Content-Type', JSON_CONTENT_TYPE))
        requested_output_content_type = request.headers.get('Accept', JSON_CONTENT_TYPE)

        # utf-8 decoding is automatic in Flask if the Content-Type is valid. But that does not happens always.
        content = request.get_data().decode('utf-8') if input_content_type in UTF8_CONTENT_TYPES else request.get_data()

        try:
            response_data, output_content_type = \
                self.transform_fn(self.model, content, input_content_type, requested_output_content_type)
            # OK
            ret_status = 200
        except Exception as e:
            ret_status, response_data = self._handle_invoke_exception(e)
            output_content_type = JSON_CONTENT_TYPE

        return Response(response=response_data,
                        status=ret_status,
                        mimetype=output_content_type)

    def _handle_invoke_exception(self, e):
        data = json.dumps(e.message)
        if isinstance(e, UnsupportedContentTypeError):
            # Unsupported Media Type
            return 415, data
        elif isinstance(e, UnsupportedAcceptTypeError):
            # Not Acceptable
            return 406, data
        elif isinstance(e, UnsupportedInputShapeError):
            # Precondition Failed
            return 412, data
        else:
            self.log.exception(e)
            raise e

    @staticmethod
    def _healthcheck():
        """Default healthcheck handler. Returns 200 status with no content. Note that the
        `InvokeEndpoint API`_ contract requires that the service only returns 200 when
        it is ready to start serving requests.

        :return: 200 response if the serer is ready to handle requests.
        """
        return '', 200

    def _default_error_handler(self, exception):
        """ Default error handler. Returns 500 status with no content.

        :param exception: the exception that triggered the error
        :return: 500 response
        """

        self.log.error(exception)
        return '', 500


class Transformer(object):
    """A ``Transformer`` encapsulates the function(s) responsible for parsing incoming request data,
    passing it through a prediction function, and converting the result into something
    that can be returned as the body of an HTTP response.
    """

    def __init__(self, transform_fn=lambda x, y, z: (x, z)):
        self.transform_fn = transform_fn

    def transform(self, data, input_content_type, output_content_type):
        """Transforms input data into a prediction result. The input data must
        be in a format compatible with the configured ``input_fn``. The output format
        will be determined by the ``output_fn``.

        :param data: input data
        :param input_content_type: content type of input specified in request header
        :param output_content_type: requested content type of output specified in request header
        :return: the transformed result
        """
        return self.transform_fn(data, input_content_type, output_content_type)


class UnsupportedContentTypeError(Exception):
    def __init__(self, *args, **kwargs):
        super(Exception, self).__init__(args[1:], **kwargs)
        self.message = 'Requested unsupported ContentType: ' + args[0]


class UnsupportedAcceptTypeError(Exception):
    def __init__(self, *args, **kwargs):
        super(Exception, self).__init__(args[1:], **kwargs)
        self.message = 'Requested unsupported ContentType in Accept: ' + args[0]


class UnsupportedInputShapeError(Exception):
    def __init__(self, *args, **kwargs):
        super(Exception, self).__init__(args[1:], **kwargs)
        self.message = 'Model can have only 1 input data, but it has: ' + str(args[0])
