import os
import logging


class Logger(object):

    def __init__(self, name):
        name = name.replace('.log', '')
        logger = logging.getLogger('robin.%s' % name)
        logger.setLevel(logging.DEBUG)
        if not logger.handlers:
            file_name = os.path.join(".", '%s.log' % name)
            handler = logging.FileHandler(file_name)
            formatter = logging.Formatter('%(asctime)s %(levelname)s:%(name)s %(message)s')
            handler.setFormatter(formatter)
            handler.setLevel(logging.DEBUG)
            logger.addHandler(handler)
        self._logger = logger

    def get(self):
        return self._logger
